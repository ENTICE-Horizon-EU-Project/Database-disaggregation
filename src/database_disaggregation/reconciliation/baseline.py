"""Native budgets and lazily read parent profiles, without materialising global Z."""
import ast
import hashlib
from functools import lru_cache
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from database_disaggregation.core.parent_budgets import ParentBudgets, _sector_index
from .audit import file_sha256


class NativeBaseline:
    def __init__(self, path=None, *, database=None, audit=None, chunk_size=256):
        if path is None and database is None:
            raise ValueError('Supply a MARIO Database or a baseline directory.')
        self.path = Path(path) if path is not None else None
        self.database, self.audit = database, audit
        self._parquets = {}
        if database is not None:
            self.budgets = ParentBudgets.from_database(database)
            self.units = database.units
        else:
            unit_path = self.path/'units.parquet'
            units = pd.read_parquet(unit_path)
            self.units = {k:f.droplevel(0) for k,f in units.groupby(level=0, sort=False)}
            bilateral = None
            for name in ('Z', 'Y'):
                parquet, index_columns, columns = self._parquet(name)
                for offset in range(0, len(columns), chunk_size):
                    frame = parquet.read(columns=columns[offset:offset+chunk_size]+index_columns).to_pandas()
                    if not np.isfinite(frame.to_numpy(dtype=float)).all():
                        raise ValueError(f'Non-finite native {name} flows.')
                    grouped = frame.T.groupby(level='Region', sort=False).sum().T
                    grouped.index = _sector_index(grouped.index)
                    bilateral = grouped if bilateral is None else bilateral.add(grouped, fill_value=0)
            self.budgets = ParentBudgets(bilateral.sum(axis=1), bilateral, self.units['Sector']['unit'].to_dict())
        self.regions = list(self.budgets.output.index.get_level_values('Region').unique())
        self.sectors = list(self.units['Sector'].index)
        if audit is not None and self.path is None:
            matrices = ['Z', 'Y', 'V', 'X']
            if len(self.units.get('Satellite account', [])):
                matrices.append('E')
            for name in matrices:
                frame = database.resolve(name)
                digest = hashlib.sha256()
                digest.update(pd.util.hash_pandas_object(frame.columns).to_numpy().tobytes())
                for start in range(0, len(frame), chunk_size):
                    digest.update(pd.util.hash_pandas_object(frame.iloc[start:start+chunk_size],
                                                            index=True).to_numpy().tobytes())
                audit.record('in_memory_baseline', kind='baseline', matrix=name,
                             shape=list(frame.shape), sha256=digest.hexdigest())
            for kind, frame in self.units.items():
                digest = hashlib.sha256(pd.util.hash_pandas_object(frame,index=True).to_numpy().tobytes())
                audit.record('in_memory_baseline_units', kind='baseline', item_type=kind,
                             sha256=digest.hexdigest())
        if audit is not None and self.path is not None:
            for name in ('Z', 'Y', 'V', 'E', 'EY', 'VY', 'X', 'units'):
                path = self.path/f'{name}.parquet'
                if database is None and path.exists():
                    digest = file_sha256(path)
                    audit.files[str(path)] = {'sha256': digest, 'bytes': path.stat().st_size, 'role':'baseline'}
            if database is not None:
                for path in sorted(p for p in self.path.rglob('*') if p.is_file()):
                    digest=file_sha256(path)
                    audit.files[str(path)]={'sha256':digest,'bytes':path.stat().st_size,'role':'baseline_native_parser_input'}

    def _parquet(self, name):
        if name not in self._parquets:
            parquet = pq.ParquetFile(self.path/f'{name}.parquet')
            meta = json.loads(parquet.schema_arrow.metadata[b'pandas'])
            index = [v for v in meta['index_columns'] if isinstance(v, str)]
            columns = [v['field_name'] for v in meta['columns'] if v['field_name'] not in index]
            self._parquets[name] = parquet, index, columns
        return self._parquets[name]

    def _columns(self, name, regions, parent):
        if self.database is not None:
            frame = self.database.resolve(name)
            return frame.loc[:, frame.columns.get_level_values('Region').isin(regions)
                             & (frame.columns.get_level_values('Item' if 'Item' in frame.columns.names else 'Sector')==parent)]
        parquet, index, columns = self._parquet(name)
        selected = []
        for column in columns:
            label = ast.literal_eval(column)
            if label[0] in regions and label[-1] == parent:
                selected.append(column)
        if not selected:
            raise ValueError(f'No {name} baseline columns for {parent}/{regions}')
        return parquet.read(columns=selected+index).to_pandas()

    @lru_cache(maxsize=64)
    def input_column(self, region, parent):
        frame = self._columns('Z', (region,), parent)
        series = frame.iloc[:, 0].copy()
        series.index = _sector_index(series.index)
        return series

    @lru_cache(maxsize=64)
    def profile(self, regions, parent):
        """Parent cost/intensity prior; zero-output regions use a global donor."""
        regions = tuple(regions)
        production = sum(float(self.budgets.output.loc[(r, parent)]) for r in regions)
        donor_regions = regions if production > 0 else tuple(self.regions)
        production = sum(float(self.budgets.output.loc[(r, parent)]) for r in donor_regions)
        if production <= 0:
            raise ValueError(f'Cannot infer a technology for globally zero-output parent {parent}.')
        rows = []
        for matrix, kind, item_level in (('Z','Sector',True), ('V','Factor of production',False),
                                         ('E','Satellite account',False)):
            if matrix == 'E' and not len(self.units.get('Satellite account', [])):
                continue
            if self.database is None and not (self.path/f'{matrix}.parquet').exists():
                if matrix == 'E':
                    continue
                raise FileNotFoundError(self.path/f'{matrix}.parquet')
            values = self._columns(matrix, donor_regions, parent).sum(axis=1)
            if item_level:
                values = values.groupby(level='Item' if 'Item' in values.index.names else 'Sector').sum()
            for item, value in values.items():
                q = float(value)/production
                if q:
                    rows.append({'Quantity':q, 'Unit':self.units[kind].loc[item,'unit'], 'Input':item,
                                 'Item type':kind, 'DB Item':item,
                                 'DB Region':'GLOBAL' if kind == 'Sector' else None, 'Change type':'Update'})
        return rows, donor_regions

    def origin_weights(self, producing_region, parent, input_items, origins):
        column = self.input_column(producing_region, parent)
        selected = column.loc[column.index.get_level_values('Sector').isin(input_items)
                              & column.index.get_level_values('Region').isin(origins)]
        weights = selected.groupby(level='Region').sum().reindex(origins, fill_value=0).clip(lower=0)
        if weights.sum() <= 0:
            weights = pd.Series({r:sum(max(0.,float(self.budgets.output.loc[(r,s)]))
                                      for s in input_items) for r in origins})
        if weights.sum() <= 0:
            weights[:] = 1.
        return (weights/weights.sum()).to_dict()
