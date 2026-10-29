"""Saved reference observations with fresh metrics from a current MARIO result.

Reference values, currency conversions, scopes and baseline metrics are read
from an explicit data package. Only the current result's metrics are computed.
This module never balances data, reruns a solver or infers finer sector scopes.
"""
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
import json
import numpy as np
import pandas as pd
from database_disaggregation.core.reference_benchmark import profiles_from_iot, money_metrics
from database_disaggregation.core.benchmark import sector_axis


@dataclass(frozen=True)
class ReferenceSet:
    data: dict
    supplier_groups: dict[str, int]
    provenance: dict

    def __post_init__(self):
        groups = self.data.get('input_groups', [])
        if not groups or self.data.get('monetary_unit') != 'M USD':
            raise ValueError('References require explicit input groups and M USD monetary units.')
        if any(type(v) is not int or not 0 <= v < len(groups) for v in self.supplier_groups.values()):
            raise ValueError('Supplier group indices must address the declared input groups.')
        if len(groups) != 10:
            raise ValueError('The reference profile reducer requires ten declared supplier groups.')
        seen = set()
        for row in self.data.get('rows', []):
            key = row['family'], row['region'], row['basket']
            if key in seen:
                raise ValueError(f'Duplicate reference case: {key}')
            seen.add(key)
            if not row['entice_sectors'] or len(set(row['entice_sectors'])) != len(row['entice_sectors']):
                raise ValueError(f'Empty or repeated current sectors in {key}')
            for name in ('baseline', 'reference'):
                metrics = row[name]
                for metric, value in metrics.items():
                    if metric != 'input_coefficients' and value is not None and not np.isfinite(value):
                        raise ValueError(f'Non-finite reference metric {metric} in {key}')
                if len(metrics['input_coefficients']) != len(groups):
                    raise ValueError(f'Input group dimensions disagree for {key}')
                values = [v for v in metrics['input_coefficients'] if v is not None]
                if not all(np.isfinite(v) for v in values):
                    raise ValueError(f'Non-finite reference coefficients in {key}')

    @classmethod
    def from_comparisons(cls, comparisons, supplier_groups, *, provenance=None):
        """Freeze an audited comparison dataset; do not convert its units again."""
        return cls(deepcopy(comparisons), dict(supplier_groups), deepcopy(provenance or {}))

    @classmethod
    def read(cls, path):
        value = json.loads(Path(path).read_text())
        if value.get('format') != 'entice-reference-set-v1':
            raise ValueError('Unsupported reference-set format.')
        return cls(value['comparisons'], value['supplier_groups'], value.get('provenance', {}))

    def write(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'format': 'entice-reference-set-v1',
            'comparisons': self.data, 'supplier_groups': self.supplier_groups,
            'provenance': self.provenance}, separators=(',', ':'), allow_nan=False))
        return path

    def compare(self, database):
        """Return compatible geographic cases with current Z/Y/X metrics.

        All source counterparts remain in the reducer. A reference geography
        absent from the current database is omitted; sector scopes must match
        exactly, rather than being silently reduced to their intersection.
        """
        regions = list(database.get_index('Region'))
        sectors = list(database.get_index('Sector'))
        missing = set(sectors) - self.supplier_groups.keys()
        if missing:
            raise ValueError(f'No supplier groups for current sectors: {sorted(missing)}')
        data = deepcopy(self.data)
        data['rows'] = [r for r in data['rows'] if r['region'] in regions]
        for row in data['rows']:
            absent = set(row['entice_sectors']) - set(sectors)
            if absent:
                raise ValueError(f'Reference scope contains absent current sectors: {sorted(absent)}')
        axis = pd.MultiIndex.from_product([regions, sectors], names=['Region', 'Sector'])
        z = database.Z.copy(deep=False)
        z.index, z.columns = sector_axis(z.index), sector_axis(z.columns)
        y = database.Y.copy(deep=False)
        y.index = sector_axis(y.index)
        x = database.X.iloc[:, 0].copy()
        x.index = sector_axis(x.index)
        z = z.reindex(index=axis, columns=axis)
        y = y.reindex(index=axis)
        order = np.concatenate([np.flatnonzero(y.columns.get_level_values('Region') == r) for r in regions])
        profiles, audit = profiles_from_iot(x.reindex(axis).to_numpy(), regions, sectors,
            {r: [r] for r in regions}, [self.supplier_groups[s] for s in sectors],
            [(0, z.to_numpy())], [(0, y.iloc[:, order].to_numpy())])
        indices = {s: i for i, s in enumerate(sectors)}
        for row in data['rows']:
            row['entice'] = money_metrics(profiles[row['region']], [indices[s] for s in row['entice_sectors']])
        data['entice_profile_source'] = 'Current MARIO database'
        data['entice_profile_audit'] = audit
        return data
