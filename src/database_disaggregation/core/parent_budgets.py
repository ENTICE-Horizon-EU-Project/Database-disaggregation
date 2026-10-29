"""Blocking cumulative child-output and bilateral-trade budget checks.

Budgets use the supplied baseline: X from row sums, and parent deliveries
Z + Y to each destination region. No target or baseline value is adjusted.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import hashlib
from io import BytesIO
import json
from pathlib import Path

import numpy as np
import pandas as pd

from database_disaggregation.core.geography import aggregate_frame

ATOL, RTOL = 1e-6, 1e-8
OUTPUT_COLUMNS = ['Sector', 'Region', 'Quantity', 'Unit']
TRADE_COLUMNS = ['Sector_from', 'Region_from', 'Region_to', 'Quantity', 'Unit']


def _sector_index(index):
    item = 'Sector' if 'Sector' in index.names else 'Item'
    return pd.MultiIndex.from_arrays(
        [index.get_level_values('Region'), index.get_level_values(item)], names=['Region', 'Sector'])


@dataclass(frozen=True)
class ParentBudgets:
    output: pd.Series
    trade: pd.DataFrame
    units: dict[str, str]

    @classmethod
    def from_database(cls, database):
        x = database.resolve('X').iloc[:, 0].copy()
        x.index = _sector_index(x.index)
        deliveries = []
        for name in ('Z', 'Y'):
            frame = database.resolve(name)
            grouped = frame.T.groupby(level='Region', sort=False).sum().T
            grouped.index = _sector_index(grouped.index)
            deliveries.append(grouped)
        trade = deliveries[0].add(deliveries[1], fill_value=0)
        return cls(x, trade, database.units['Sector']['unit'].to_dict())

    def aggregate(self, geography):
        geography.validate(self.output.index.get_level_values('Region').unique())
        output = aggregate_frame(self.output.to_frame('X'), geography)['X']
        trade = aggregate_frame(self.trade, geography)
        trade.columns = trade.columns.map(geography.mapping)
        trade = trade.T.groupby(level=0, sort=False).sum().T
        return ParentBudgets(output, trade, self.units)


@dataclass(frozen=True)
class ChildTargets:
    master: pd.DataFrame
    output: pd.DataFrame
    trade: pd.DataFrame
    sources: dict[str, str] | None = None
    incomplete_output: dict[tuple[str, str], list[str]] | None = None

    @classmethod
    def from_workbook(cls, workbook):
        support = workbook.split_info or {}
        return cls(workbook.master_sheet.copy(),
                   support.get('Total outputs', pd.DataFrame(columns=OUTPUT_COLUMNS)).copy(),
                   support.get('Trades', pd.DataFrame(columns=TRADE_COLUMNS)).copy())

    def pending(self, database):
        """On resume, compare pending children with the remaining parent budget."""
        master = self.master.loc[~self.master['Sector'].isin(database.get_index('Sector'))]
        sectors = set(master['Sector'])
        return ChildTargets(master, self.output.loc[self.output['Sector'].isin(sectors)],
                            self.trade.loc[self.trade['Sector_from'].isin(sectors)], self.sources,
                            {k: v for k, v in (self.incomplete_output or {}).items() if k[0] in sectors})

    def aggregate(self, geography):
        output, trade = self.output.copy(), self.trade.copy()
        incomplete = defaultdict(set)
        for sector in self.master['Sector'].dropna().unique():
            present = set(output.loc[output.Sector.eq(sector), 'Region'])
            for region in geography.mapping.keys() - present:
                incomplete[(sector, geography.mapping[region])].add(region)
        for (sector, region), missing in (self.incomplete_output or {}).items():
            incomplete[(sector, geography.mapping[region])].update(missing)
        for frame, columns in ((output, ['Region']), (trade, ['Region_from', 'Region_to'])):
            sector_column = 'Sector' if frame is output else 'Sector_from'
            if frame.duplicated([sector_column, *columns]).any():
                raise ValueError('Duplicate child target coordinates before geographic aggregation.')
            values = pd.to_numeric(frame['Quantity'], errors='raise')
            if not np.isfinite(values).all() or (values < 0).any() or frame['Unit'].isna().any():
                raise ValueError('Child targets require finite nonnegative quantities and explicit units.')
            frame['Quantity'] = values
            for column in columns:
                unknown = set(frame[column]) - geography.mapping.keys()
                if unknown:
                    raise ValueError(f'Unmapped target regions: {sorted(unknown)}')
                frame[column] = frame[column].map(geography.mapping)
        output = output.groupby(['Sector', 'Region', 'Unit'], sort=False, as_index=False)['Quantity'].sum(min_count=1)
        trade = trade.loc[trade.Region_from.ne(trade.Region_to)]
        trade = trade.groupby(['Sector_from', 'Region_from', 'Region_to', 'Unit'],
                              sort=False, as_index=False)['Quantity'].sum(min_count=1)
        return ChildTargets(self.master, output, trade, self.sources,
                            {k: sorted(v) for k, v in incomplete.items()})


def read_child_targets(paths, *, output_references=None):
    """Read only target/support sheets; unresolved profiles are not evaluated.

    Sparse exported output rows may be supplemented by explicit native output
    observations. Missing observations remain unknown and block acceptance.
    """
    from openpyxl import load_workbook

    def frame(book, name, columns):
        if name not in book:
            return pd.DataFrame(columns=columns)
        header, *rows = book[name].values
        return pd.DataFrame(rows, columns=header).dropna(how='all').reindex(columns=columns)

    masters, outputs, trades, sources, seen = [], [], [], {}, set()
    for path in paths:
        path = Path(path)
        raw = path.read_bytes()
        sources[str(path)] = hashlib.sha256(raw).hexdigest()
        book = load_workbook(BytesIO(raw), read_only=True, data_only=True)
        try:
            master = frame(book, 'Master', ['Sector', 'Parent Sector', 'Add or Split'])
            sectors = set(master['Sector'].dropna())
            if len(sectors) != 1 or sectors & seen:
                raise ValueError(f'Expected one unique child sector per workbook: {path}')
            seen.update(sectors)
            sector = next(iter(sectors))
            output = frame(book, 'Total outputs', OUTPUT_COLUMNS)
            reference = (output_references or {}).get(sector)
            if reference:
                extra = pd.DataFrame(reference['rows'], columns=OUTPUT_COLUMNS)
                if extra.duplicated(['Sector', 'Region']).any():
                    raise ValueError(f'Duplicate output-reference observations for {sector}')
                extra = extra.loc[~extra.Region.isin(output.Region)]
                output = pd.concat([output, extra], ignore_index=True)
                if not extra.empty:
                    sources[reference['source']] = reference['sha256']
            masters.append(master)
            outputs.append(output)
            trades.append(frame(book, 'Trades', TRADE_COLUMNS))
        finally:
            book.close()
    if not masters:
        raise ValueError('No child inventory workbooks supplied.')
    return ChildTargets(pd.concat(masters, ignore_index=True),
                        pd.concat([f for f in outputs if not f.empty], ignore_index=True)
                        if any(not f.empty for f in outputs) else pd.DataFrame(columns=OUTPUT_COLUMNS),
                        pd.concat([f for f in trades if not f.empty], ignore_index=True)
                        if any(not f.empty for f in trades) else pd.DataFrame(columns=TRADE_COLUMNS), sources)


def evaluate_parent_budgets(budgets, targets):
    """Return all violations together, including incomplete output coverage.

    A partial known sum exceeding its parent is already a definite violation;
    incomplete groups below the cap remain unverified, never a successful zero.
    The trade comparison uses the provided targets on directed foreign routes.
    """
    master = targets.master
    if 'Add or Split' in master:
        modes = master['Add or Split'].astype(str).str.strip().str.lower()
        if not modes.isin(['add', 'split']).all():
            raise ValueError('Master rows must explicitly declare Add or Split.')
        master = master.loc[modes.eq('split')]
    parents = {}
    for sector, rows in master.groupby('Sector', sort=False):
        values = rows['Parent Sector'].dropna().unique()
        if len(values) != 1 or not str(values[0]).strip():
            raise ValueError(f'{sector}: exactly one parent is required.')
        parents[sector] = values[0]
    children = defaultdict(list)
    for sector, parent in parents.items():
        if parent not in budgets.units:
            raise ValueError(f'Parent {parent!r} is absent from the baseline sector units.')
        children[parent].append(sector)
    regions = list(budgets.output.index.get_level_values('Region').unique())
    outputs, routes, exports = {}, defaultdict(dict), defaultdict(float)
    for frame, columns, sector_column in ((targets.output, OUTPUT_COLUMNS, 'Sector'),
                                          (targets.trade, TRADE_COLUMNS, 'Sector_from')):
        unknown = set(frame[sector_column]) - set(targets.master['Sector'])
        if unknown:
            raise ValueError(f'Unknown child sectors in target tables: {sorted(unknown)}')
        frame = frame.loc[frame[sector_column].isin(parents), columns].copy()
        keys = columns[:-2]
        if frame.duplicated(keys).any():
            raise ValueError(f'Duplicate child target coordinates: {keys}')
        quantities = pd.to_numeric(frame.Quantity, errors='raise')
        if not np.isfinite(quantities).all() or (quantities < 0).any():
            raise ValueError('Child output/trade targets must be finite and nonnegative.')
        frame['Quantity'] = quantities
        for row in frame.itertuples(index=False, name=None):
            sector, *coordinates, quantity, unit = row
            parent = parents[sector]
            if unit != budgets.units[parent]:
                raise ValueError(f'{sector}: target unit {unit!r} differs from parent unit {budgets.units[parent]!r}.')
            if set(coordinates) - set(regions):
                raise ValueError(f'{sector}: unknown target region coordinates {coordinates}')
            if sector_column == 'Sector':
                outputs[(sector, coordinates[0])] = float(quantity)
            elif coordinates[0] != coordinates[1]:
                routes[(parent, *coordinates)][sector] = float(quantity)
                exports[(sector,coordinates[0])] += float(quantity)

    output_failures, trade_failures, incomplete = [], [], []
    for parent, sectors in children.items():
        for region in regions:
            known = {s: outputs[(s, region)] for s in sectors if (s, region) in outputs}
            missing = sorted(s for s in sectors if s not in known or (s, region) in (targets.incomplete_output or {}))
            if missing:
                incomplete.append({'parent': parent, 'region': region, 'missing_children': missing,
                    'missing_native_regions': {s: targets.incomplete_output[(s, region)] for s in missing
                                              if (s, region) in (targets.incomplete_output or {})}})
            capacity = float(budgets.output.loc[(region, parent)])
            if not np.isfinite(capacity):
                raise ValueError(f'Non-finite parent output: {parent}/{region}')
            total = sum(known.values())
            allowance = ATOL + RTOL * abs(capacity)
            if total > capacity + allowance:
                output_failures.append(dict(parent=parent, region=region, child_sum=total,
                    parent_value=capacity, excess=total-capacity, allowance=allowance,
                    unit=budgets.units[parent], children=known, complete=not missing))
    for (parent, origin, destination), known in sorted(routes.items()):
        capacity = float(budgets.trade.loc[(origin, parent), destination])
        if not np.isfinite(capacity):
            raise ValueError(f'Non-finite parent trade: {parent}/{origin}/{destination}')
        total = sum(known.values())
        allowance = ATOL + RTOL * abs(capacity)
        if total > capacity + allowance:
            trade_failures.append(dict(parent=parent, origin=origin, destination=destination,
                child_sum=total, parent_value=capacity, excess=total-capacity,
                allowance=allowance, unit=budgets.units[parent], children=known))
    export_failures=[]
    for (sector,origin),total in sorted(exports.items()):
        if (sector,origin) not in outputs or (sector,origin) in (targets.incomplete_output or {}):
            continue
        cap=outputs[(sector,origin)]
        if total>cap+ATOL+RTOL*abs(cap):
            export_failures.append({'sector':sector,'parent':parents[sector],'origin':origin,
                                   'exports':total,'output':cap,'excess':total-cap,'unit':budgets.units[parents[sector]]})
    passed = not (output_failures or trade_failures or incomplete or export_failures)
    return {'status': 'passed' if passed else 'failed',
            'summary': {'sectors': len(parents), 'parents': len(children), 'regions': len(regions),
                        'output_groups': len(children)*len(regions), 'observed_trade_groups': len(routes),
                        'output_violations': len(output_failures), 'trade_violations': len(trade_failures),
                        'producer_export_violations':len(export_failures),
                        'incomplete_output_groups': len(incomplete),
                        'missing_output_cells': sum(len(r['missing_children']) for r in incomplete)},
            'tolerances': {'absolute': ATOL, 'relative': RTOL},
            'trade_definition': 'Parent Z + Y deliveries to each foreign destination region',
            'output_violations': output_failures, 'trade_violations': trade_failures,
            'export_violations':export_failures,
            'incomplete_outputs': incomplete, 'source_files': targets.sources or {}}


class ParentBudgetError(ValueError):
    def __init__(self, report, path=None):
        self.report = report
        self.report_path = path
        counts = report['summary']
        super().__init__(f"Cumulative child budgets exceeded or incomplete: "
                         f"output={counts['output_violations']}, trade={counts['trade_violations']}, "
                         f"producer_exports={counts['producer_export_violations']}, "
                         f"incomplete_output_groups={counts['incomplete_output_groups']}"
                         + (f". Report: {path}" if path else ''))


def require_parent_budgets(budgets, targets, *, report_path=None):
    report = evaluate_parent_budgets(budgets, targets)
    if report_path is not None:
        report_path = Path(report_path)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, allow_nan=False))
    if report['status'] != 'passed':
        raise ParentBudgetError(report, report_path)
    return report
