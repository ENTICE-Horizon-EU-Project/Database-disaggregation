"""Portable end-to-end preparation through dashboard, using an actual solver."""
import json
import hashlib

import pandas as pd
import pytest

from database_disaggregation import workflow, Geography
from test_database_input import make_database
from test_geography import inventory


OPTIONS = dict(model='Split_sectors_MRIO_quadratic', accounting='inherit',
               compact_constraints=True, final_demand_weight=.1, supply_weight=1.,
               scale=10., check_feasibility=True, feasibility_solver='CLARABEL',
               defer_satellite_recalculation=True)


def small_database():
    import mario
    axis = pd.MultiIndex.from_product([['R1','R2','R3'],['Sector'],['Parent','Stable']],
                                       names=['Region','Level','Item'])
    demand = pd.MultiIndex.from_product([['R1','R2','R3'],['Consumption category'],['HH']], names=axis.names)
    units = {kind: pd.DataFrame({'unit':[unit]*len(items)}, index=items) for kind,items,unit in
             [('Sector',['Parent','Stable'],'M USD'),('Factor of production',['VA'],'M USD'),
              ('Satellite account',['CO2'],'tonne')]}
    return mario.Database(name='Small explicit workflow', table='IOT', units=units,
        Z=pd.DataFrame(1.,index=axis,columns=axis),Y=pd.DataFrame(4.,index=axis,columns=demand),
        V=pd.DataFrame(12.,index=['VA'],columns=axis),E=pd.DataFrame(1.,index=['CO2'],columns=axis),
        EY=pd.DataFrame(0.,index=['CO2'],columns=demand))


def test_full_explicit_workflow_and_orchestrator_match(tmp_path, monkeypatch):
    native = small_database()
    original = {n: native.resolve(n).copy() for n in ['Z','Y','V','E','EY','X']}
    source = tmp_path/'collection'; source.mkdir()
    inventory(source/'A.xlsx', sector='A', outputs=(6.,6.,6.))
    digest = hashlib.sha256((source/'A.xlsx').read_bytes()).hexdigest()
    geography = Geography({'R1':'G','R2':'G','R3':'H'})
    prepared = workflow.prepare_inputs(source, tmp_path/'prepared', database=native, geography=geography)
    database = native.aggregate(None, levels='Region', region_aggregation=geography.mapping,
                                zero_output_epsilon=None, inplace=False)
    model = workflow.build_model(database, prepared, directory=tmp_path/'model', split_model_options=OPTIONS)
    solution = workflow.solve_model(model, solver='CLARABEL')
    result = workflow.assemble_database(solution)
    assert set(result.get_index('Region')) == {'G','H'}
    assert set(result.get_index('Sector')) == {'Parent','Stable','A'}
    exported = workflow.export_database(result, tmp_path/'exported', inputs=prepared)
    restored = workflow.load_database(exported)
    for name in original:
        pd.testing.assert_frame_equal(result.resolve(name), restored.resolve(name), check_exact=True)
        pd.testing.assert_frame_equal(native.resolve(name), original[name], check_exact=True)
    manifest = json.loads((exported/'run.json').read_text())
    assert manifest['solver'] == 'CLARABEL'
    assert manifest['solver_status'] and manifest['model_definition']
    assert manifest['split_model_options']['accounting'] == 'inherit'
    assert manifest['pending_recalculations'] == ['E']
    assert restored._last_split_model_options == manifest['split_model_options']
    dashboard = workflow.build_dashboard(exported, tmp_path/'dashboard.html')
    html = dashboard.read_text()
    assert 'New sector' in html and 'Parent' in html
    assert 'Trade' in html and 'data:image/' in html
    assert hashlib.sha256((source/'A.xlsx').read_bytes()).hexdigest() == digest
    assert not list(prepared.rglob('*.parquet'))

    calls = []
    for name in ['build_model','solve_model','assemble_database','export_database','build_dashboard']:
        original_function = getattr(workflow, name)
        def trace(*args, _name=name, _function=original_function, **kwargs):
            calls.append(_name)
            return _function(*args, **kwargs)
        monkeypatch.setattr(workflow, name, trace)
    automated = workflow.run(database, prepared, directory=tmp_path/'automated', solver='CLARABEL',
                             model_options={'split_model_options':OPTIONS})
    assert calls == ['build_model','solve_model','assemble_database','export_database','build_dashboard']
    for name in original:
        pd.testing.assert_frame_equal(workflow.load_database(automated).resolve(name), result.resolve(name),
                                       atol=1e-7, rtol=1e-8)


def test_export_preserves_independent_output_and_rejects_changed_files(tmp_path):
    database = make_database()
    database.matrices['baseline']['X'] = database.X+.01
    exported = workflow.export_database(database, tmp_path/'exported')
    restored = workflow.load_database(exported)
    pd.testing.assert_frame_equal(database.X, restored.X, check_exact=True)
    with pytest.raises(FileExistsError):
        workflow.export_database(database, exported)
    path = exported/'flows/X.parquet'
    data = path.read_bytes(); path.write_bytes(data+b'changed')
    with pytest.raises(ValueError, match='changed or is missing'):
        workflow.load_database(exported)


def test_export_failure_does_not_publish_a_partial_run(tmp_path, monkeypatch):
    database = make_database()
    def fail(*args, **kwargs):
        raise RuntimeError('Synthetic export failure')
    monkeypatch.setattr(database, 'to_parquet', fail)
    with pytest.raises(RuntimeError, match='Synthetic export failure'):
        workflow.export_database(database, tmp_path/'exported')
    assert list(tmp_path.iterdir()) == []


def test_workflow_dashboard_accepts_a_validated_mario_checkpoint(tmp_path):
    from pathlib import Path
    from test_shared_runs import trial_fixture
    trial = trial_fixture(tmp_path/'source')
    checkpoint = Path(json.loads((trial/'trial.json').read_text())['accepted_checkpoints'][-1])
    expected = pd.read_parquet(checkpoint/'database/flows/X.parquet')
    page = workflow.build_dashboard(checkpoint, tmp_path/'checkpoint.html')
    data, _ = json.JSONDecoder().raw_decode(page.read_text().split('const D=', 1)[1])
    for coordinate, row in expected.iterrows():
        region, _, sector = coordinate
        assert data['payload'][sector]['output'][data['regions'].index(region)] == pytest.approx(row.iloc[0])
