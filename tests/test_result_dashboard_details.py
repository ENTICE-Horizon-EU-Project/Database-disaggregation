from io import BytesIO
import json
from types import SimpleNamespace
from zipfile import ZipFile

import numpy as np
import pandas as pd
import pytest

from database_disaggregation.analysis.flows import cost_profile
from database_disaggregation.reporting.constraints import archived_constraints
from database_disaggregation.reporting.dashboard import dashboard_payload
from test_workshop_dashboard import database


def test_costs_sum_all_origins_include_signed_value_added_and_do_not_use_x():
    db = database()
    db.V = pd.DataFrame([[10., 20., 30., 40.], [-2., -3., -4., -5.]],
                        index=['Labor', 'Tax'], columns=db.Z.columns)
    before_z, before_v = db.Z.copy(), db.V.copy()
    actual = cost_profile(db, 'p')
    expected = np.vstack([db.Z.iloc[[0, 2], [0, 2]].sum(axis=0),
                          db.Z.iloc[[1, 3], [0, 2]].sum(axis=0), [10., 30.], [-2., -4.]])
    np.testing.assert_allclose(actual.amounts, expected)
    np.testing.assert_allclose(actual.shares, expected / expected.sum(axis=0) * 100)
    assert actual.shares.loc['VA · Tax'].lt(0).all()
    assert list(actual.shares.index) == ['p', 'q', 'VA · Labor', 'VA · Tax']
    assert actual.totals.iloc[0] != db.X.iloc[0, 0]
    pd.testing.assert_frame_equal(db.Z, before_z)
    pd.testing.assert_frame_equal(db.V, before_v)


def test_nonpositive_total_cost_is_unavailable_instead_of_a_fake_recipe():
    db = database()
    db.V = pd.DataFrame([-db.Z.sum(axis=0).to_numpy()], index=['Tax'], columns=db.Z.columns)
    assert cost_profile(db, 'p').shares.isna().all().all()


def effective_archive(tmp_path):
    root = tmp_path / 'saved'
    (root / 'diagnostics').mkdir(parents=True)
    (root / 'state.json').write_text(json.dumps({'completed_sectors': ['p']}))
    (root / 'execution_report.json').write_text(json.dumps({'attempts': [
        {'status': 'accepted', 'step_index': 2, 'step': 'Step 2', 'sectors': ['p']},
        {'status': 'failed', 'step_index': 1, 'step': 'Step 1', 'sectors': ['q']},
    ]}))
    payload = BytesIO()
    with pd.ExcelWriter(payload) as w:
        pd.DataFrame([['p', 'A', 30., 'M USD'], ['p', 'B', 50., 'M USD']],
                     columns=['Sector', 'Region', 'Quantity', 'Unit']).to_excel(w, sheet_name='Total outputs', index=False)
        pd.DataFrame([['p', 'A', 'B', 0., 'M USD'], ['p', 'A', 'A', 99., 'M USD']],
                     columns=['Sector_from', 'Region_from', 'Region_to', 'Quantity', 'Unit']).to_excel(w, sheet_name='Trades', index=False)
        pd.DataFrame([['delta', 0.]], columns=['tol_Name', 'values']).to_excel(w, sheet_name='Tolerances', index=False)
    with ZipFile(root / 'diagnostics/step-artifacts.zip', 'w') as z:
        z.writestr('002_Step_2/step_add_sectors.xlsx', payload.getvalue())
    return root, payload.getvalue()


def test_effective_constraints_keep_selected_zero_routes_and_exclude_domestic_rows(tmp_path):
    root, payload = effective_archive(tmp_path)
    targets, rows = archived_constraints(root, export_inputs=root / 'inputs/steps')
    p = targets['p']
    assert p['trade_targets'] == {'A': {'B': 0.}}
    assert p['output_cells'] == {'A': 'Total outputs!D2', 'B': 'Total outputs!D3'}
    assert p['trade_cells'] == {'A': {'B': 'Trades!E2'}}
    assert (root / p['input_href']).read_bytes() == payload
    assert len(rows) == 3
    assert set(rows.scope) == {'production', 'bilateral total of intermediate and all final-demand deliveries'}
    data = dashboard_payload(database(), labels={}, target_profiles=targets)['payload']['p']
    assert data['output_reference_kind'] == 'Constraint'
    assert data['trade_constraint'] == [[None, 0.], [None, None]]
    assert data['output_target'] == [30., 50.]


def test_a_reference_is_not_relabelled_as_a_verified_model_constraint():
    p = dashboard_payload(database(), labels={}, target_profiles={'p': {'output_targets': {'A': 30.}}})['payload']['p']
    assert p['output_reference_kind'] == 'Prepared reference'
    assert all(value is None for row in p['trade_constraint'] for value in row)


def test_offline_cache_requires_recorded_checksum_and_exact_geography(tmp_path):
    from database_disaggregation.core.reference_benchmark import verified_profile_cache
    from database_disaggregation.core.benchmark import sha256
    path = tmp_path / 'cache.json'
    identity = dict(path='/unmounted/source.zip', size=100, mtime_ns=123,
                    engine='original-extraction', groups={'s': 2}, geography={'A': ['a']})
    path.write_text(json.dumps(dict(identity=identity, source_sha256='source-digest', profiles={})))
    recorded = dict(path=identity['path'], size=100, mtime_ns=123,
                    profile_sha256=sha256(path), sha256='source-digest')
    assert verified_profile_cache(path, family='EXIOBASE', recorded=recorded,
        groups={'s': 2}, geography={'A': ['a']})['identity']['engine'] == 'original-extraction'
    with pytest.raises(ValueError, match='geography or supplier mapping'):
        verified_profile_cache(path, family='EXIOBASE', recorded=recorded,
            groups={'s': 2}, geography={'A': ['b']})
    path.write_text(path.read_text() + ' ')
    with pytest.raises(ValueError, match='checksum mismatch'):
        verified_profile_cache(path, family='EXIOBASE', recorded=recorded,
            groups={'s': 2}, geography={'A': ['a']})


def test_sharepoint_document_metadata_preserves_exact_effective_input_parts(tmp_path):
    from database_disaggregation.reporting.constraints import verify_workbook_input_parts
    _, original = effective_archive(tmp_path)
    def changed(*, alter_sheet=False):
        exported = BytesIO()
        with ZipFile(BytesIO(original)) as source, ZipFile(exported, 'w') as target:
            for name in source.namelist():
                payload = source.read(name)
                if alter_sheet and name == 'xl/worksheets/sheet1.xml':
                    payload = payload.replace(b'>30<', b'>31<')
                target.writestr(name, payload)
            target.writestr('customXml/item1.xml', '<metadata/>')
        return exported.getvalue()
    assert verify_workbook_input_parts(original, changed())['input_parts_identical']
    with pytest.raises(ValueError, match='effective input data changed'):
        verify_workbook_input_parts(original, changed(alter_sheet=True))


def test_region_names_require_exact_membership_not_just_a_matching_label(tmp_path):
    from database_disaggregation.analysis.labels import read_region_names
    path = tmp_path / 'names.csv'
    path.write_text('code,name,native_regions\nAB,Combined countries,A | B\n')
    assert read_region_names(path, regions=['AB'], geography={'A': 'AB', 'B': 'AB'}) == {'AB': 'Combined countries'}
    with pytest.raises(ValueError, match='membership differs'):
        read_region_names(path, regions=['AB'], geography={'A': 'AB', 'C': 'AB'})
    with pytest.raises(ValueError, match='region universe'):
        read_region_names(path, regions=['Other'])


def test_region_display_names_are_metadata_and_do_not_rename_flow_coordinates():
    db = database()
    payload = dashboard_payload(db, labels={}, region_names={'A': 'Country A', 'B': 'Country B'})
    assert payload['regions'] == ['A', 'B']
    assert payload['region_names'] == {'A': 'Country A', 'B': 'Country B'}
    assert list(db.Z.index.get_level_values('Region').unique()) == ['A', 'B']
    with pytest.raises(ValueError, match='cover the exact saved regions'):
        dashboard_payload(db, labels={}, region_names={'A': 'Country A'})
