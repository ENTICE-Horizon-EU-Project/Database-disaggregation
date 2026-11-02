"""Read-only, post-solve benchmarking of monetary MARIO IOT checkpoints.

This module deliberately has no MARIO, CVXLab or optimisation dependency.
X is read from disk, never inferred from Z/Y. Numerical results stay with data.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import io
import zipfile
import json
import os
from pathlib import Path
import subprocess
import tempfile
import warnings

import numpy as np
import pandas as pd

ATOL, RTOL = 1e-6, 1e-8  # M USD; same acceptance tolerances as the checkpoint


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprints(folder):
    folder = Path(folder)
    paths = list((folder / 'flows').glob('*.parquet'))
    paths += [folder / n for n in ('state.json', 'metadata.json', 'run.json', 'baseline_provenance.json')
              if (folder / n).is_file()]
    return {str(p.relative_to(folder)): sha256(p) for p in sorted(paths)}


def sector_axis(axis):
    if not isinstance(axis, pd.MultiIndex) or 'Region' not in axis.names:
        raise ValueError('Expected an explicit MARIO Region/Item sector axis.')
    if 'Level' in axis.names and set(axis.get_level_values('Level')) != {'Sector'}:
        raise ValueError('Only monetary IOT sector axes are supported.')
    result = pd.MultiIndex.from_arrays([axis.get_level_values('Region'), axis.get_level_values(-1)],
                                       names=['Region', 'Sector'])
    if result.has_duplicates:
        raise ValueError('Duplicate sector coordinates.')
    return result


@dataclass
class Flows:
    root: Path
    frames: dict
    hashes: dict

    @classmethod
    def read(cls, root):
        root = Path(root).resolve()
        hashes = fingerprints(root)
        frames = {n: pd.read_parquet(root / 'flows' / f'{n}.parquet') for n in ('Z', 'Y', 'V', 'X')}
        for n in ('EY', 'VY'):
            if (root / 'flows' / f'{n}.parquet').is_file():
                frames[n] = pd.read_parquet(root / 'flows' / f'{n}.parquet')
        state_path = root / 'state.json'
        renames = json.loads(state_path.read_text()).get('residual_index_renames', {}) if state_path.exists() else {}
        if len(set(renames.values())) != len(renames):
            raise ValueError('Non-invertible published sector names.')
        inverse = {label: code for code, label in renames.items()}
        # Only sector coordinates may be renamed; demand/factor labels stay intact.
        for f in frames.values():
            for attr in ('index', 'columns'):
                axis = getattr(f, attr)
                if isinstance(axis, pd.MultiIndex) and 'Region' in axis.names:
                    if 'Level' in axis.names and set(axis.get_level_values('Level')) != {'Sector'}:
                        continue
                    tuples = [(*v[:-1], inverse.get(v[-1], v[-1])) for v in axis]
                    setattr(f, attr, pd.MultiIndex.from_tuples(tuples, names=axis.names))
        for n, f in frames.items():
            if not np.isfinite(f.to_numpy(dtype=float)).all():
                raise ValueError(f'{root}: non-finite values in {n}.')
        for n in ('Z', 'Y', 'X'):
            frames[n].index = sector_axis(frames[n].index)
        for n in ('Z', 'V'):
            frames[n].columns = sector_axis(frames[n].columns)
        axis = frames['X'].index
        if frames['X'].shape[1] != 1 or (frames['X'].iloc[:, 0] < -ATOL).any():
            raise ValueError('X must have one finite, nonnegative production column (numerical dust tolerated).')
        for n in ('Z', 'Y'):
            if set(frames[n].index) != set(axis):
                raise ValueError(f'{n}: sector rows differ from X.')
            frames[n] = frames[n].reindex(index=axis)
        for n in ('Z', 'V'):
            if set(frames[n].columns) != set(axis):
                raise ValueError(f'{n}: sector columns differ from X.')
            frames[n] = frames[n].reindex(columns=axis)
        for n in ('Y', 'EY', 'VY'):
            if n in frames and (frames[n].columns.has_duplicates or frames[n].index.has_duplicates):
                raise ValueError(f'{n}: duplicate coordinates.')
        units = pd.read_parquet(root / 'flows/units.parquet')
        for group in ('Sector', 'Factor of production'):
            if set(units.xs(group, level=0).iloc[:, 0]) != {'M USD'}:
                raise ValueError('Benchmark monetary thresholds require all sectors/factors in M USD.')
        return cls(root, frames, hashes)

    def __getitem__(self, name):
        return self.frames[name]


def mapping_to_baseline(base, final, parents):
    baxis, faxis = base['X'].index, final['X'].index
    if set(baxis.get_level_values(0)) != set(faxis.get_level_values(0)):
        raise ValueError('Baseline and final database must have exactly the same regions.')
    bsectors, fsectors = set(baxis.get_level_values(1)), set(faxis.get_level_values(1))
    if set(parents) != fsectors - bsectors or not set(parents.values()) <= bsectors:
        raise ValueError('Checkpoint child/parent mapping must explain every new sector exactly once.')
    mapped = pd.MultiIndex.from_tuples([(r, parents.get(s, s)) for r, s in faxis], names=baxis.names)
    if set(mapped) != set(baxis):
        raise ValueError('Mapped final sector universe differs from the baseline.')
    return mapped


def aggregate_to_baseline(base, final, mapped):
    """Reaggregate Z on BOTH axes; preserve labels and explicit baseline order."""
    out = {}
    for n in ('Z', 'Y', 'V', 'X', 'EY', 'VY'):
        if n not in base.frames or n not in final.frames:
            continue
        f = final[n].copy()
        if n in ('Z', 'Y', 'X'):
            f.index = mapped
            f = f.groupby(level=[0, 1], sort=False).sum()
        if n in ('Z', 'V'):
            f.columns = mapped
            f = f.T.groupby(level=[0, 1], sort=False).sum().T
        if set(f.index) != set(base[n].index) or set(f.columns) != set(base[n].columns):
            raise ValueError(f'{n}: labels do not match the baseline after reaggregation.')
        out[n] = f.reindex(index=base[n].index, columns=base[n].columns)
    return out


def difference(name, actual, expected, *, unit='M USD', atol=ATOL, rtol=RTOL):
    a, b = np.asarray(actual, dtype=float), np.asarray(expected, dtype=float)
    if a.shape != b.shape or not np.isfinite(a).all() or not np.isfinite(b).all():
        raise ValueError(f'{name}: comparison requires aligned finite arrays of identical shape.')
    delta = np.abs(a - b)
    limit = atol + rtol * np.abs(b)
    worst = np.unravel_index(int(np.argmax(delta)), delta.shape)
    material = np.abs(b) > atol
    return dict(name=name, passed=bool((delta <= limit).all()), cells=int(delta.size),
                failed_cells=int((delta > limit).sum()), max_absolute=float(delta.max()),
                max_relative=float((delta[material] / np.abs(b[material])).max()) if material.any() else None,
                worst_coordinate=[int(i) for i in worst], unit=unit, atol=atol, rtol=rtol)


def accounting(base, final, mapped):
    bx, fx = base['X'].iloc[:, 0], final['X'].iloc[:, 0]
    bp = bx.reindex(mapped).to_numpy()
    weights = np.divide(fx.to_numpy(), bp, out=np.zeros(len(fx)), where=np.abs(bp) > ATOL)
    out, tests = {}, []
    for kind in ('row', 'column'):
        def residual(db):
            if kind == 'row':
                return db['Z'].sum(axis=1) + db['Y'].sum(axis=1) - db['X'].iloc[:, 0]
            return db['Z'].sum(axis=0) + db['V'].sum(axis=0) - db['X'].iloc[:, 0]
        br, fr = residual(base), residual(final)
        expected = br.reindex(mapped).to_numpy() * weights
        # Nonzero discrepancies on zero-output parents cannot be allocated by output shares.
        unsupported = (np.abs(bp) <= ATOL) & (np.abs(br.reindex(mapped).to_numpy()) > ATOL)
        if unsupported.any():
            raise ValueError(f'{kind}: nonzero inherited discrepancy on a zero-output baseline parent.')
        tests.append(difference(f'Inherited {kind} accounting', fr.to_numpy(), expected))
        out[kind] = dict(baseline=br.to_numpy(), final=fr.to_numpy(), expected=expected)
    return out, tests


def ratio(numerator, denominator):
    return float(numerator / denominator) if denominator > ATOL else None


def profiles(db, common_sectors, parents=None):
    """Shares use authoritative X. Missing/zero denominators remain null."""
    parents = parents or {}
    axis, x = db['X'].index, db['X'].iloc[:, 0].to_numpy()
    regions = list(axis.get_level_values(0).unique())
    zr, yr = db['Z'].to_numpy(), db['Y'].to_numpy()
    z = db['Z'].copy()
    z.index = [parents.get(s, s) for _, s in axis]
    inputs = z.groupby(level=0, sort=False).sum().reindex(common_sectors).to_numpy().T
    deliveries = db['Z'].T.groupby(level='Region', sort=False).sum().T.add(
        db['Y'].T.groupby(level='Region', sort=False).sum().T, fill_value=0).reindex(columns=regions).to_numpy()
    categories = list(db['Y'].columns.get_level_values(-1).unique())
    yf = db['Y'].copy()
    yf.columns = yf.columns.get_level_values(-1)
    demand = yf.T.groupby(level=0, sort=False).sum().T.reindex(columns=categories).to_numpy()
    factors = list(db['V'].index)
    rows = []
    row_regions = np.array(axis.get_level_values(0))
    for i, (r, s) in enumerate(axis):
        domestic = row_regions == r
        ri = regions.index(r)
        foreign = np.array([k != r for k in regions])
        ex = deliveries[i, foreign]
        positive_exports = np.maximum(ex, 0)
        total_ex = positive_exports.sum()
        rows.append(dict(region=r, sector=s, parent=parents.get(s, s), is_child=s in parents,
                         output=float(x[i]), intermediate_inputs=float(zr[:, i].sum()),
                         intermediate_input_ratio=ratio(zr[:, i].sum(), x[i]),
                         imported_input_share=ratio(zr[~domestic, i].sum(), zr[:, i].sum()),
                         va_ratio=ratio(db['V'].iloc[:, i].sum(), x[i]),
                         final_demand_ratio=ratio(yr[i].sum(), x[i]),
                         positive_y=float(np.maximum(yr[i], 0).sum()),
                         negative_y=float(-np.minimum(yr[i], 0).sum()),
                         negative_y_ratio=ratio(-np.minimum(yr[i], 0).sum(), x[i]),
                         exports=float(ex.sum()), export_ratio=ratio(ex.sum(), x[i]),
                         export_hhi=float(((positive_exports / total_ex) ** 2).sum()) if total_ex > ATOL else None,
                         gross_z_output=float(np.abs(zr[i]).sum()), gross_z_input=float(np.abs(zr[:, i]).sum()),
                         gross_y=float(np.abs(yr[i]).sum()), gross_v=float(np.abs(db['V'].iloc[:, i]).sum()),
                         factors=[float(v) for v in db['V'].iloc[:, i]],
                         factor_shares=[ratio(v, x[i]) for v in db['V'].iloc[:, i]],
                         demand=[float(v) for v in demand[i]],
                         destinations=[float(v) for v in deliveries[i]],
                         input_coefficients=[ratio(v, x[i]) for v in inputs[i]]))
    return rows, dict(regions=regions, sectors=list(common_sectors), factors=factors, categories=categories)


def leontief(db):
    """Linear algebra only. Exclude <=1 USD output rows/columns, report their flows."""
    from scipy.linalg import lu_factor, lu_solve
    from scipy.linalg.lapack import dgecon
    from scipy.sparse.linalg import eigs, ArpackNoConvergence

    x, z = db['X'].iloc[:, 0].to_numpy(), db['Z'].to_numpy()
    active = x > ATOL
    a = z[np.ix_(active, active)] / x[active][None, :]
    m = np.eye(len(a)) - a
    with warnings.catch_warnings():
        warnings.simplefilter('error')
        lu, piv = lu_factor(m)
    rcond, info = dgecon(lu, np.linalg.norm(m, 1))
    if info or not np.isfinite(rcond) or rcond <= 0:
        raise ValueError('Leontief matrix is singular or its condition estimate failed.')
    if len(a) <= 3:
        rho = float(np.max(np.abs(np.linalg.eigvals(a))))
    else:
        try:
            rho = float(np.abs(eigs(a, k=1, which='LM', v0=np.ones(len(a)), tol=1e-9,
                                   maxiter=2000, return_eigenvectors=False)[0]))
        except ArpackNoConvergence:
            rho = None
    mult = lu_solve((lu, piv), np.ones(len(a)), trans=1)
    full_mult = np.full(len(x), np.nan)
    full_mult[active] = mult
    return dict(active=active, matrix=m, lu=(lu, piv), multipliers=full_mult,
                summary=dict(active_sectors=int(active.sum()), excluded_sectors=int((~active).sum()),
                             excluded_gross_z_rows=float(np.abs(z[~active]).sum()),
                             excluded_gross_z_columns=float(np.abs(z[:, ~active]).sum()),
                             spectral_radius=rho, condition_1_estimate=float(1 / rcond),
                             multiplier_min=float(mult.min()), multiplier_max=float(mult.max()),
                             multiplier_median=float(np.median(mult)),
                             negative_multipliers=int((mult < -RTOL).sum()),
                             multiplier_solve_residual_max=float(np.abs(m.T @ mult - 1.).max())))


def compare_systems(base, final):
    """Stability and multiplier summaries only; no hypothetical demand shocks."""
    from contextlib import nullcontext
    try:
        from threadpoolctl import threadpool_limits
        thread_limit = threadpool_limits(limits=2)
    except ImportError:
        thread_limit = nullcontext()
    with thread_limit:
        b, f = leontief(base), leontief(final)
    return dict(baseline=b['summary'], final=f['summary']), b['multipliers'], f['multipliers']


def prepared_targets(final, state):
    """Audit selected support-table observations from each published stage once."""
    outputs, trades, sources, changes = {}, {}, [], []
    # New cumulative publications archive the exact, dynamically remapped inputs
    # for every accepted step. A cumulative workbook is not that step's input.
    archive = final.root / 'diagnostics/step-artifacts.zip'
    if not archive.exists():
        archive = final.root / 'diagnostics/exact-inputs.zip'
    manifest = final.root / 'execution_report.json'
    if not manifest.exists():
        manifest = final.root / 'diagnostics/run_report.json'
    if archive.is_file() and manifest.is_file():
        attempts = json.loads(manifest.read_text())['attempts']
        accepted = [a for a in attempts if a['status'] == 'accepted']
        accepted_sectors = [s for a in accepted for s in a['sectors']]
        if len(set(accepted_sectors)) != len(accepted_sectors) or set(accepted_sectors) != set(state['completed_sectors']):
            raise ValueError('Archived accepted steps do not match completed sectors.')
        sources += [dict(path=str(archive), sha256=sha256(archive)),
                    dict(path=str(manifest), sha256=sha256(manifest))]
        with zipfile.ZipFile(archive) as z:
            for attempt in accepted:
                member = f"{attempt['step_index']:03d}_{attempt['step'].replace(' ', '_')}/step_add_sectors.xlsx"
                payload = z.read(member)
                with pd.ExcelFile(io.BytesIO(payload)) as workbook:
                    for name, keys, store, field in (
                        ('Total outputs', ['Sector', 'Region'], outputs, 'Sector'),
                        ('Trades', ['Sector_from', 'Region_from', 'Region_to'], trades, 'Sector_from'),
                    ):
                        table = pd.read_excel(workbook, sheet_name=name)
                        table = table.loc[table[field].isin(attempt['sectors'])]
                        if table.duplicated(keys).any() or not table.Unit.eq('M USD').all():
                            raise ValueError(f'{member}: invalid or duplicate {name} targets.')
                        for row in table.to_dict('records'):
                            key = tuple(row[k] for k in keys); quantity = float(row['Quantity'])
                            if not np.isfinite(quantity) or key in store:
                                raise ValueError(f'Duplicate or non-finite archived target: {key}')
                            store[key] = quantity
        current = Path('/nonexistent-benchmark-history')
    else:
        current = final.root
    seen = set()
    while (current / 'run.json').is_file():
        if current in seen:
            raise ValueError('Cycle in published run provenance.')
        seen.add(current)
        run = json.loads((current / 'run.json').read_text())
        step = json.loads((current / 'state.json').read_text())
        inventory = (current / run['inventory_directory']).resolve()
        workbook = inventory / 'step_add_sectors.xlsx'
        if not workbook.is_file():
            workbook = inventory / 'add_sectors.xlsx'  # Legacy incremental package.
        digest = sha256(workbook)
        sources.append(dict(path=str(workbook), sha256=digest, step_sectors=step['step_sectors']))
        for name, keys, store, field in (
            ('Total outputs', ['Sector', 'Region'], outputs, 'Sector'),
            ('Trades', ['Sector_from', 'Region_from', 'Region_to'], trades, 'Sector_from'),
        ):
            table = pd.read_excel(workbook, sheet_name=name)
            table = table.loc[table[field].isin(step['step_sectors'])]
            if table.duplicated(keys).any() or not table.Unit.eq('M USD').all():
                raise ValueError(f'{workbook}: invalid or duplicate {name} targets.')
            for row in table.to_dict('records'):
                key = tuple(row[k] for k in keys)
                quantity = float(row['Quantity'])
                if not np.isfinite(quantity) or key in store:
                    raise ValueError(f'Duplicate or non-finite target: {key}')
                store[key] = quantity
        audit = current / 'diagnostics/trade_reconciliation/trade_changes.csv'
        if audit.is_file():
            sources.append(dict(path=str(audit), sha256=sha256(audit)))
            changes += pd.read_csv(audit).to_dict('records')
        previous = run.get('source_database_directory')
        if not previous:
            break
        current = (current / previous).resolve()
    if not sources:
        return [], dict(status='unavailable', outputs=0, trade_routes=0), [], []
    x = final['X'].iloc[:, 0]
    deliveries = final['Z'].T.groupby(level='Region').sum().T.add(
        final['Y'].T.groupby(level='Region').sum().T, fill_value=0)
    actual_x = np.array([x.at[(r, s)] for s, r in outputs])
    actual_t = np.array([deliveries.at[(r, s), dest] for s, r, dest in trades])
    checks = []
    if outputs:
        checks.append(difference('Prepared output targets', actual_x, list(outputs.values())))
    if trades:
        checks.append(difference('Selected prepared trade targets', actual_t, list(trades.values())))
    for row in changes:
        row['final'] = float(deliveries.at[(row['origin'], row['sector']), row['destination']])
        row['adjustment'] = float(row['reconciled'] - row['prior'])
    by_sector = {}
    for sector in state['completed_sectors']:
        oi=np.array([s==sector for s,r in outputs],dtype=bool)
        ti=np.array([s==sector for s,r,d in trades],dtype=bool)
        actual=np.concatenate([actual_x[oi],actual_t[ti]])
        target=np.concatenate([np.array(list(outputs.values()))[oi],np.array(list(trades.values()))[ti]])
        delta=np.abs(actual-target)
        by_sector[sector]=dict(count=int(len(actual)),passed=int((delta<=ATOL+RTOL*np.abs(target)).sum()),
            max_error=float(delta.max()) if len(delta) else None,
            output_targets={r:q for (s,r),q in outputs.items() if s==sector})
    return checks, dict(status='checked', by_sector=by_sector, outputs=len(outputs), trade_routes=len(trades),
                        expected_child_outputs=len(state['completed_sectors']) * len(x.index.get_level_values(0).unique()),
                        note='Prepared targets, after harmonisation; adherence is not independent validation.'), changes, sources



def build_report(baseline, database, *, system=True):
    base, final = Flows.read(baseline), Flows.read(database)
    baseline_record = base.root / 'baseline_provenance.json'
    if baseline_record.is_file():
        for relative, digest in json.loads(baseline_record.read_text())['sha256'].items():
            path = (base.root / relative).resolve()
            if not path.is_relative_to(base.root) or sha256(path) != digest:
                raise ValueError(f'Baseline provenance checksum failed: {relative}')
    state = json.loads((final.root / 'state.json').read_text())
    if state.get('split_model_options', {}).get('accounting') != 'inherit':
        raise ValueError('This first benchmark version requires checkpoint accounting="inherit".')
    if {k: state.get('tolerances', {}).get(k) for k in ('absolute', 'relative')} != {'absolute': ATOL, 'relative': RTOL}:
        raise ValueError('Checkpoint tolerances differ from the audited benchmark policy.')
    completed = state['completed_sectors']
    if len(set(completed)) != len(completed) or set(completed) - state['sector_parents'].keys():
        raise ValueError('Invalid completed-sector mapping in checkpoint.')
    # Partial checkpoints also retain parent mappings for future planned children.
    parents = {sector: state['sector_parents'][sector] for sector in completed}
    mapped = mapping_to_baseline(base, final, parents)
    for relative, digest in state['files'].items():
        p = (final.root / relative).resolve()
        if not p.is_relative_to(final.root) or sha256(p) != digest:
            raise ValueError(f'Checkpoint checksum failed: {relative}')
    aggregated = aggregate_to_baseline(base, final, mapped)
    checks = [difference(f'Reaggregation {n}', f, base[n], unit='row-specific' if n == 'EY' else 'M USD',
                         atol=0 if n in ('EY', 'VY') else ATOL, rtol=0 if n in ('EY', 'VY') else RTOL)
              for n, f in aggregated.items()]
    negative_z = final['Z'].to_numpy() < -ATOL
    checks.append(dict(name='Nonnegative Z within 1 USD per cell', passed=not bool(negative_z.any()),
                       cells=int(negative_z.size), failed_cells=int(negative_z.sum()),
                       max_absolute=float(max(0, -final['Z'].to_numpy().min())), unit='M USD', atol=ATOL, rtol=0))
    acct, accounting_checks = accounting(base, final, mapped)
    checks += accounting_checks
    report_only = state.get('numerical_validation_policy', {}).get('validation') == 'report_only'
    common = list(base['X'].index.get_level_values(1).unique())
    b_rows, dims = profiles(base, common)
    rows, _ = profiles(final, common, parents)
    b_lookup = {(r['region'], r['sector']): i for i, r in enumerate(b_rows)}
    parent_set = set(parents.values())
    issues = []
    def issue(row, metric, value, note, severity='review'):
        issues.append(dict(region=row['region'], sector=row['sector'], parent=row['parent'],
                           metric=metric, value=float(value), note=note, severity=severity,
                           unit='fraction (1 = 100 pp)' if metric.endswith('change') else 'M USD'))
    for i, row in enumerate(rows):
        bi = b_lookup[(row['region'], row['parent'])]
        ref = b_rows[bi]
        row.update(baseline_index=bi, is_residual=row['sector'] in parent_set,
                   parent_output=ref['output'], output_share=ratio(row['output'], ref['output']),
                   row_residual=float(acct['row']['final'][i]), column_residual=float(acct['column']['final'][i]),
                   new_row_residual=float(acct['row']['final'][i] - acct['row']['expected'][i]),
                   new_column_residual=float(acct['column']['final'][i] - acct['column']['expected'][i]))
        a, b = row['input_coefficients'], ref['input_coefficients']
        row['technology_distance'] = float(np.abs(np.array(a) - np.array(b)).sum()) if a[0] is not None and b[0] is not None else None
        if row['output'] <= ATOL:
            # Gross measures prevent cancellation of implausible signed flows.
            gross = max(row['gross_z_output'], row['gross_z_input'], row['gross_y'], row['gross_v'])
            if gross > ATOL:
                issue(row, 'Flows at output ≤ 1 USD', gross, 'Maximum gross Z row/column, Y row or V column, M USD.')
        if row['is_residual'] and ref['output'] > ATOL and row['output'] <= ATOL:
            issue(row, 'Parent residual exhausted', row['output'], 'Children absorb the parent output; review scope and prepared targets.')
        for factor, value, old in zip(dims['factors'], row['factors'], ref['factors']):
            if factor.lower() in ('capital', 'labor', 'labour') and value < -ATOL:
                issue(row, f'Negative {factor}', value, 'Already negative in baseline parent.' if old < -ATOL else 'Baseline parent was not negative.')
        if row['is_child'] or row['is_residual']:
            for metric, oldmetric, label in [('va_ratio', 'va_ratio', 'VA/X change'),
                                             ('export_ratio', 'export_ratio', 'Exports/X change'),
                                             ('imported_input_share', 'imported_input_share', 'Imported input share change'),
                                             ('final_demand_ratio', 'final_demand_ratio', 'Final demand/X change')]:
                a, b = row[metric], ref[oldmetric]
                if a is not None and b is not None and abs(a - b) > .25:
                    issue(row, label, a - b, 'Difference >25 percentage points vs baseline parent; screening threshold, not rejection.')
    target_checks, target_summary, changes, sources = prepared_targets(final, state)
    checks += target_checks
    if target_summary['status'] == 'checked' and target_summary['outputs'] != target_summary['expected_child_outputs']:
        checks.append(dict(name='Complete prepared output coverage', passed=False, failed_cells=1,
                           max_absolute=None, unit='observations', cells=target_summary['expected_child_outputs']))
    # Retain every strict result and dollar residual. Follow the saved policy
    # for enforcement; report_only is not a declaration of economic validity.
    for check in checks:
        check['enforced'] = not report_only or check.get('unit') not in ('M USD',)
        if check['name'] == 'Reaggregation VY':
            check['enforced'] = True
    systems = dict(status='not_computed')
    if system:
        try:
            systems, bm, fm = compare_systems(base, final)
            systems['status'] = 'computed'
            for row, m in zip(b_rows, bm):
                row['multiplier'] = float(m) if np.isfinite(m) else None
            for row, m in zip(rows, fm):
                row['multiplier'] = float(m) if np.isfinite(m) else None
        except (ValueError, RuntimeError, np.linalg.LinAlgError, Warning) as exc:
            systems = dict(status='unavailable', reason=str(exc))
    # Keep only meaningful input comparisons, not full IO matrices, in the dashboard.
    for row in rows:
        ref = b_rows[row['baseline_index']]
        if row['output'] > ATOL and ref['output'] > ATOL:
            a, b = np.array(row['input_coefficients']), np.array(ref['input_coefficients'])
            top = np.argsort(np.maximum(np.abs(a), np.abs(b)))[::-1][:12]
            row['top_inputs'] = [dict(sector=common[k], final=float(a[k]), baseline=float(b[k])) for k in top]
        else:
            row['top_inputs'] = []
        row.pop('input_coefficients')
    for row in b_rows:
        row.pop('input_coefficients')
    if fingerprints(base.root) != base.hashes or fingerprints(final.root) != final.hashes:
        raise RuntimeError('Source files changed during benchmarking; no report will be published.')
    for source in sources:
        if sha256(source['path']) != source['sha256']:
            raise RuntimeError('A prepared input/audit changed during benchmarking.')
    summary = dict(regions=len(dims['regions']), baseline_sectors=len(common),
                   final_sectors=int(final['X'].index.get_level_values(1).nunique()),
                   new_sectors=len(parents), output_baseline=float(base['X'].sum().iloc[0]),
                   output_final=float(final['X'].sum().iloc[0]),
                   va_baseline=float(base['V'].to_numpy().sum()), va_final=float(final['V'].to_numpy().sum()),
                   y_baseline=float(base['Y'].to_numpy().sum()), y_final=float(final['Y'].to_numpy().sum()),
                   exports_baseline=sum(r['exports'] for r in b_rows), exports_final=sum(r['exports'] for r in rows),
                   baseline_negative_v_by_factor={str(k): float(-np.minimum(base['V'].loc[k], 0).sum()) for k in base['V'].index},
                   final_negative_v_by_factor={str(k): float(-np.minimum(final['V'].loc[k], 0).sum()) for k in final['V'].index},
                   baseline_negative_y=float(-np.minimum(base['Y'].to_numpy(), 0).sum()),
                   final_negative_y=float(-np.minimum(final['Y'].to_numpy(), 0).sum()),
                   z_minimum=float(final['Z'].to_numpy().min()),
                   z_negative_cells_over_1usd=int((final['Z'].to_numpy() < -ATOL).sum()),
                   zero_output_gross_z_inputs=sum(r['gross_z_input'] for r in rows if r['output'] <= ATOL),
                   zero_output_gross_y=sum(r['gross_y'] for r in rows if r['output'] <= ATOL),
                   zero_output_gross_v=sum(r['gross_v'] for r in rows if r['output'] <= ATOL),
                   hard_checks_passed=all(c['passed'] or not c['enforced'] for c in checks),
                   strict_checks_passed=all(c['passed'] for c in checks),
                   numerical_review_checks=sum(not c['passed'] and not c['enforced'] for c in checks),
                   planned_new_sectors=len(state.get('planned_sectors', state['sector_parents'])),
                   skipped_sectors=sorted(set(state.get('planned_sectors', state['sector_parents'])) - set(completed)),
                   review_flags=len(issues),
                   review_sector_regions=len({(r['region'], r['sector']) for r in issues}),
                   pending_recalculations=state.get('pending_recalculations', []))
    try:
        revision = subprocess.check_output(['git', '-C', str(Path(__file__).parent), 'rev-parse', 'HEAD'], text=True,
                                           stderr=subprocess.DEVNULL).strip()
    except subprocess.CalledProcessError:
        revision = None
    from database_disaggregation.core.registry import Registry
    registry = Registry.load()
    dims['sector_names'] = {code: item['name'] for code, item in registry.sectors.items()}
    dims['sector_names'].update({item['id']: item.get('name', item.get('label', item['id']))
                                for item in registry.adapters['GTAP12']['parent_catalogue']})
    dims['baseline_sector_names'] = dict(dims['sector_names'])
    dims['sector_names'].update(state.get('residual_index_renames', {}))
    region_name_source = final.root / 'diagnostics/provenance/region-names.csv'
    region_name_provenance = None
    if region_name_source.is_file():
        from database_disaggregation.analysis.labels import read_region_names
        digest = sha256(region_name_source)
        dims['region_names'] = read_region_names(region_name_source, regions=dims['regions'])
        if sha256(region_name_source) != digest:
            raise RuntimeError('Published region-name source changed during benchmarking.')
        region_name_provenance = dict(path=str(region_name_source), sha256=digest)
    name_sources = []
    additions = final.root / 'diagnostics/provenance/additional-sectors-13.json'
    if additions.is_file():
        digest = sha256(additions)
        items = json.loads(additions.read_text()).get('sectors', {})
        for code, item in items.items():
            dims['sector_names'].setdefault(code, item['name'])
        if sha256(additions) != digest:
            raise RuntimeError('Published sector-name source changed during benchmarking.')
        name_sources.append(dict(path=str(additions), sha256=digest))
    return dict(format='entice-benchmark-v2', generated_at=datetime.now(timezone.utc).isoformat(),
                summary=summary, dimensions=dims, checks=checks, targets=target_summary,
                sectors=rows, baseline_sectors=b_rows, issues=issues, systems=systems,
                trade_changes=changes,
                provenance=dict(baseline=str(base.root), database=str(final.root), baseline_sha256=base.hashes,
                                database_sha256=final.hashes, sources_unchanged=True, auxiliary_sources=sources,
                                code_revision=revision, engine_sha256=sha256(__file__),
                                region_name_source=region_name_provenance,
                                registry_sha256=registry.fingerprints, published_name_sources=name_sources,
                                baseline_source_hashes_verified=baseline_record.is_file(),
                                baseline_origin=json.loads((base.root / 'baseline_provenance.json').read_text())
                                if (base.root / 'baseline_provenance.json').is_file() else None),
                policy=dict(atol_MUSD=ATOL, rtol=RTOL, active_output_threshold_MUSD=ATOL,
                            share_screening_threshold=.25,
                            accounting='inherit', monetary_unit='M USD',
                            numerical_validation='report_only' if report_only else 'strict',
                            economic_review='pending'))



def write_report(report, output, *, overwrite=False):
    """Self-contained offline dashboard + machine-readable JSON/CSV, atomically replaced."""
    output = Path(output).resolve()
    if output.suffix != '.html':
        raise ValueError('Dashboard output must end in .html.')
    for key in ('database', 'baseline'):
        if output.is_relative_to(Path(report['provenance'][key]) / 'flows'):
            raise ValueError('Benchmark outputs cannot be written into source flows.')
    destinations = [output, output.with_suffix('.json'), output.with_name(output.stem + '-sectors.csv')]
    if any(p.exists() for p in destinations) and not overwrite:
        raise FileExistsError('Benchmark output exists; pass --overwrite to refresh only these report files.')
    from database_disaggregation.reporting.saved import render_saved_dashboard
    html = render_saved_dashboard(report,audit_stem=output.stem)
    template_path=Path(__file__).parents[1]/'reporting/templates/dashboard.html'
    report['provenance']['dashboard_template_sha256']=sha256(template_path)
    report['provenance']['dashboard_style']='MARIO workshop'
    package=Path(__file__).parents[1]
    report['provenance']['dashboard_renderer_sha256']={name:sha256(package/name) for name in (
        'reporting/dashboard.py','reporting/render.py','reporting/saved.py','analysis/flows.py',
        'reporting/templates/dashboard.html','reporting/templates/comparisons.html','reporting/templates/comparisons.js')}
    output.parent.mkdir(parents=True, exist_ok=True)
    flat = [{k: v for k, v in row.items() if not isinstance(v, (list, dict))} for row in report['sectors']]
    with tempfile.TemporaryDirectory(prefix='.benchmark-', dir=output.parent) as work:
        work = Path(work)
        (work / 'dashboard').write_text(html)
        (work / 'data').write_text(json.dumps(report, indent=2, allow_nan=False))
        pd.DataFrame(flat).to_csv(work / 'sectors', index=False)
        for source, target in zip(('dashboard', 'data', 'sectors'), destinations):
            os.replace(work / source, target)
    return destinations
