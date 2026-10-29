"""Conservation is necessary but cannot establish fine-sector plausibility."""
import json
import os
from pathlib import Path
import subprocess

import numpy as np
import pandas as pd
import pytest

from database_disaggregation.core.benchmark import (
    ATOL, Flows, accounting, aggregate_to_baseline, build_report, compare_systems,
    fingerprints, mapping_to_baseline, profiles, sha256, write_report,
)


def axis(nodes):
    return pd.MultiIndex.from_tuples([(r, 'Sector', s) for r, s in nodes], names=['Region', 'Level', 'Item'])


@pytest.fixture
def pair(tmp_path):
    bnodes = [('R1', 'P'), ('R1', 'Q'), ('R2', 'P'), ('R2', 'Q')]
    fnodes = [('R1', 'P'), ('R1', 'C'), ('R1', 'Q'), ('R2', 'P'), ('R2', 'C'), ('R2', 'Q')]
    bx = np.array([100., 80., 60., 40.])
    bz = np.array([[10., 4., 2., 1.], [3., 8., 1., 2.], [2., 1., 6., 3.], [1., 2., 4., 4.]])
    y = np.zeros((4, 4))
    y[:, 0] = (bx - bz.sum(1) + np.array([.2, -.3, .1, .4])) * .6
    y[:, 3] = (bx - bz.sum(1) + np.array([.2, -.3, .1, .4])) * .4
    v = np.stack([bx - bz.sum(0) + 1.4, np.full(4, -1.)])
    w = np.array([[.7, 0, 0, 0], [.3, 0, 0, 0], [0, 1, 0, 0],
                  [0, 0, .4, 0], [0, 0, .6, 0], [0, 0, 0, 1.]])
    yc = pd.MultiIndex.from_product([['R1', 'R2'], ['Consumption category'], ['hhd', 'inv']], names=['Region', 'Level', 'Item'])
    for root, nodes, x, z, yy, vv in [(tmp_path / 'base', bnodes, bx, bz, y, v),
                                    (tmp_path / 'final', fnodes, w @ bx, w @ bz @ w.T, w @ y, v @ w.T)]:
        flow = root / 'flows'
        flow.mkdir(parents=True)
        index = axis(nodes)
        frames = dict(X=pd.DataFrame(x, index=index, columns=['production']),
                      Z=pd.DataFrame(z, index=index, columns=index), Y=pd.DataFrame(yy, index=index, columns=yc),
                      V=pd.DataFrame(vv, index=pd.Index(['Labor', 'Tax'], name='Item'), columns=index),
                      EY=pd.DataFrame([[1., 2., 3., 4.]], index=['CO2'], columns=yc),
                      VY=pd.DataFrame(np.zeros((2, 4)), index=['Labor', 'Tax'], columns=yc))
        units = [('Sector', s) for s in dict.fromkeys(s for _, s in nodes)] + [('Factor of production', s) for s in ('Labor', 'Tax')]
        frames['units'] = pd.DataFrame('M USD', index=pd.MultiIndex.from_tuples(units), columns=['unit'])
        for name, frame in frames.items():
            frame.to_parquet(flow / f'{name}.parquet')
    state = dict(sector_parents={'C': 'P'}, completed_sectors=['C'], pending_recalculations=['E'],
                 split_model_options={'accounting': 'inherit'}, tolerances={'absolute': ATOL, 'relative': 1e-8},
                 files={k: v for k, v in fingerprints(tmp_path / 'final').items() if k.startswith('flows/')})
    (tmp_path / 'final/state.json').write_text(json.dumps(state))
    return tmp_path / 'base', tmp_path / 'final'


def update_hash(root, name):
    state = json.loads((root / 'state.json').read_text())
    state['files'][f'flows/{name}.parquet'] = sha256(root / 'flows' / f'{name}.parquet')
    (root / 'state.json').write_text(json.dumps(state))


def test_reaggregation_both_axes_and_explicit_x(pair):
    base, final = map(Flows.read, pair)
    mapped = mapping_to_baseline(base, final, {'C': 'P'})
    aggregate = aggregate_to_baseline(base, final, mapped)
    for n in ('X', 'Z', 'Y', 'V', 'EY', 'VY'):
        np.testing.assert_allclose(aggregate[n], base[n], atol=1e-12)
    assert base['X'].iloc[0, 0] == 100
    assert base['Z'].iloc[0].sum() + base['Y'].iloc[0].sum() != 100
    ac, checks = accounting(base, final, mapped)
    assert all(c['passed'] for c in checks)
    np.testing.assert_allclose(ac['column']['expected'], [.28, .12, .4, .16, .24, .4], atol=1e-12)


def test_multiplier_summaries_match_exact_reference(pair):
    base, final = map(Flows.read, pair)
    mapped = mapping_to_baseline(base, final, {'C': 'P'})
    system, bm, fm = compare_systems(base, final)
    expected = np.linalg.inv(np.eye(4) - base['Z'].to_numpy() / base['X'].iloc[:, 0].to_numpy()[None, :])
    np.testing.assert_allclose(bm, expected.sum(0), atol=1e-12)
    assert system['baseline']['active_sectors'] == 4
    assert system['final']['active_sectors'] == 6
    np.testing.assert_allclose(fm, expected.sum(0)[[0, 0, 1, 2, 2, 3]], atol=1e-12)


def test_zero_output_uses_null_ratios_and_gross_signed_flows(pair):
    _, final_path = pair
    db = Flows.read(final_path)
    db['X'].iloc[1, 0] = 0
    db['Y'].iloc[1, :] = [5., -5., 0, 0]
    rows, _ = profiles(db, ['P', 'Q'], {'C': 'P'})
    assert rows[1]['final_demand_ratio'] is None
    assert rows[1]['factor_shares'] == [None, None]
    assert rows[1]['gross_y'] == 10
    assert rows[1]['negative_y'] == 5
    assert rows[1]['output'] == 0


def test_conservation_pass_can_still_have_new_negative_labor(pair):
    bp, fp = pair
    v = pd.read_parquet(fp / 'flows/V.parquet')
    transfer = v.iloc[0, 1] + 1
    v.iloc[0, 1] -= transfer
    v.iloc[0, 0] += transfer
    v.iloc[1, 1] += transfer
    v.iloc[1, 0] -= transfer
    v.to_parquet(fp / 'flows/V.parquet')
    update_hash(fp, 'V')
    before = fingerprints(fp)
    report = build_report(bp, fp, system=False)
    assert report['summary']['hard_checks_passed']
    assert report['summary']['baseline_negative_v_by_factor']['Labor'] == 0
    flag = next(i for i in report['issues'] if i['metric'] == 'Negative Labor')
    assert flag['sector'] == 'C' and flag['value'] == -1
    assert 'was not negative' in flag['note']
    assert fingerprints(fp) == before


def test_checksum_and_nonfinite_data_fail_explicitly(pair):
    bp, fp = pair
    x = pd.read_parquet(fp / 'flows/X.parquet')
    x.iloc[0, 0] += 1
    x.to_parquet(fp / 'flows/X.parquet')
    with pytest.raises(ValueError, match='checksum'):
        build_report(bp, fp, system=False)
    x.iloc[0, 0] = np.nan
    x.to_parquet(fp / 'flows/X.parquet')
    with pytest.raises(ValueError, match='non-finite'):
        Flows.read(fp)


def test_baseline_provenance_is_verified_not_just_recorded(pair):
    bp, fp = pair
    (bp / 'baseline_provenance.json').write_text(json.dumps({'description': 'Fixture', 'sha256': fingerprints(bp)}))
    x = pd.read_parquet(bp / 'flows/X.parquet')
    x.iloc[0, 0] += .01
    x.to_parquet(bp / 'flows/X.parquet')
    with pytest.raises(ValueError, match='Baseline provenance checksum'):
        build_report(bp, fp, system=False)


def test_listed_zero_trade_target_is_checked_and_missing_route_is_not_zero(pair):
    from database_disaggregation.core.benchmark import prepared_targets
    bp, fp = pair
    inv = fp.parent / 'inventories'
    inv.mkdir()
    with pd.ExcelWriter(inv / 'add_sectors.xlsx') as writer:
        pd.DataFrame([['C', 'R1', 30., 'M USD'], ['C', 'R2', 36., 'M USD']],
                     columns=['Sector', 'Region', 'Quantity', 'Unit']).to_excel(writer, sheet_name='Total outputs', index=False)
        pd.DataFrame([['C', 'R1', 'R2', 0., 'M USD']],
                     columns=['Sector_from', 'Region_from', 'Region_to', 'Quantity', 'Unit']).to_excel(writer, sheet_name='Trades', index=False)
    state = json.loads((fp / 'state.json').read_text())
    state['step_sectors'] = ['C']
    (fp / 'state.json').write_text(json.dumps(state))
    (fp / 'run.json').write_text(json.dumps({'inventory_directory': '../inventories'}))
    checks, summary, changes, sources = prepared_targets(Flows.read(fp), state)
    assert summary['outputs'] == 2 and summary['trade_routes'] == 1
    assert checks[0]['passed']
    assert not checks[1]['passed'] and checks[1]['failed_cells'] == 1
    assert len(sources) == 1
    # A new cumulative reference may differ; audit the exact archived step.
    import shutil
    shutil.copy2(inv / 'add_sectors.xlsx', inv / 'step_add_sectors.xlsx')
    (inv / 'add_sectors.xlsx').write_bytes(b'Not the historical step workbook')
    _, repeated, _, recorded = prepared_targets(Flows.read(fp), state)
    assert repeated == summary
    assert recorded[0]['path'].endswith('/step_add_sectors.xlsx')


def test_geography_or_parent_mismatch_is_not_silently_filled(pair):
    base, final = map(Flows.read, pair)
    with pytest.raises(ValueError, match='mapping'):
        mapping_to_baseline(base, final, {'C': 'Unknown'})
    final['X'].index = pd.MultiIndex.from_tuples([('Other', s) for _, s in final['X'].index], names=['Region', 'Sector'])
    with pytest.raises(ValueError, match='same regions'):
        mapping_to_baseline(base, final, {'C': 'P'})


def test_export_is_self_contained_and_protects_sources(pair, tmp_path):
    report = build_report(*pair, system=False)
    before = [fingerprints(p) for p in pair]
    target = tmp_path / 'report/benchmarking.html'
    files = write_report(report, target)
    assert all(p.is_file() for p in files)
    html = target.read_text()
    assert '__BENCHMARK_DATA__' not in html
    assert 'href="benchmarking.json"' in html
    assert 'MARIO workshop' == report['provenance']['dashboard_style']
    custom=tmp_path/'custom dashboard.html'
    write_report(report,custom)
    assert 'href="custom dashboard.json"' in custom.read_text()
    assert 'href="custom dashboard-sectors.csv"' in custom.read_text()
    assert 'script src=' not in html and '<link rel="stylesheet" href="http' not in html
    assert json.loads(files[1].read_text())['provenance']['sources_unchanged']
    assert [fingerprints(p) for p in pair] == before
    with pytest.raises(FileExistsError):
        write_report(report, target)
    with pytest.raises(ValueError, match='source flows'):
        write_report(report, pair[1] / 'flows/report.html')


@pytest.mark.skipif(os.environ.get('ENTICE_BENCHMARK_BROWSER_TEST') != '1', reason='Optional offline browser check')
def test_dashboard_dom_interactions(pair, tmp_path):
    report = build_report(*pair)
    report['issues'] = [dict(region='R1', sector='C', parent='P', metric='Negative Labor', value=-1,
                             note='Synthetic finding', unit='M USD', severity='review')]
    report['trade_changes'] = [dict(sector='C', parent='P', origin='R1', destination='R2', prior=1,
                                    reconciled=2, final=2, adjustment=1, source_kind='direct', previously_observed=True)]
    target = tmp_path / 'fixture.html'
    write_report(report, target)
    result = subprocess.run(['node', str(Path(__file__).with_name('workshop_dashboard_browser.cjs')), str(target)],
                            text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_partial_checkpoint_benchmarks_completed_children_only(pair):
    bp, fp = pair
    state = json.loads((fp / 'state.json').read_text())
    state['sector_parents']['Future child'] = 'Q'
    (fp / 'state.json').write_text(json.dumps(state))
    report = build_report(bp, fp, system=False)
    assert report['summary']['hard_checks_passed']
    assert report['summary']['new_sectors'] == 1
    assert all(not row['is_residual'] for row in report['sectors'] if row['sector'] == 'Q')
