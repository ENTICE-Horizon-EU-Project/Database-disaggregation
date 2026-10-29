"""Public collected-data API: real preparation, matching geography and failure choices."""
import hashlib
import json
from types import SimpleNamespace

import pandas as pd
import pytest
from openpyxl import load_workbook

import database_disaggregation
from database_disaggregation.core.parent_budgets import ChildTargets
from database_disaggregation.reconciliation.audit import Audit
from database_disaggregation.reconciliation.targets import prepare_outputs, reconcile_trade
from test_database_input import make_database
from test_geography import inventory
from test_reconciliation import budgets, toy_policy


@pytest.fixture
def collected_data(tmp_path, monkeypatch):
    from database_disaggregation.reconciliation import model_inputs
    data_root = tmp_path/'Data split'
    source = data_root/'native'
    source.mkdir(parents=True)
    inventory(source/'A.xlsx', sector='A', outputs=(6., 6., 6.))
    repository = tmp_path/'repository'
    (repository/'config').mkdir(parents=True)
    (repository/'config/additional-sectors-13.json').write_text(
        json.dumps({'sectors': {}, 'country_components': {}}))
    policy = toy_policy(('A',))
    actual_load_policy = model_inputs.load_policy
    monkeypatch.setattr(model_inputs, 'PROJECT_ROOT', repository)
    monkeypatch.setattr(model_inputs, 'load_policy',
                        lambda value=True: actual_load_policy(policy if value is True else value))
    return dict(data_root=data_root, source_paths={
        'resolved_inventories': 'native', 'mario_inventories': None,
        'purdue_split_targets': None, 'purdue_trade': None, 'partner_templates': None})


def test_public_collected_preparation_returns_matching_database_workbook_and_audit(tmp_path, monkeypatch, collected_data):
    import mario
    db = make_database()
    original = {name: db.resolve(name).copy() for name in ('Z', 'Y', 'V', 'E', 'X')}
    source = collected_data['data_root']/'native/A.xlsx'
    digest = hashlib.sha256(source.read_bytes()).hexdigest()

    def forbidden(*args, **kwargs):
        pytest.fail('The in-memory preparation must not parse/export a database or run an MRIO split.')
    for name in ('parse_gtap', 'parse_from_parquet'):
        monkeypatch.setattr(mario, name, forbidden)
    monkeypatch.setattr(mario.Database, 'to_parquet', forbidden)
    monkeypatch.setattr(mario.Database, 'add_sectors', forbidden)

    result = database_disaggregation.prepare_inputs(
        database=db, geography={'R1': 'G', 'R2': 'G', 'R3': 'H'}, output_dir=tmp_path/'result',
        missing_output='parent_share', missing_cost_structure='same_sector_then_parent',
        inconsistent_targets='reconcile', **collected_data)
    assert isinstance(result, database_disaggregation.PreprocessedData)
    assert set(result.database.get_index('Region')) == {'G', 'H'}
    assert result.workbook.is_file()
    assert result.audit.is_dir()
    assert (result.audit/'changes.jsonl').is_file()
    assert not list(result.workbook.parent.rglob('*.parquet'))
    targets = ChildTargets.from_workbook(result.database.add_sectors_workbook)
    assert set(targets.output.Region) == {'G', 'H'}
    assert targets.output.Quantity.sum() == pytest.approx(18.)
    assert result.database.add_sectors_workbook.intermediate_steps == {'Sector A': ['A']}
    summary = json.loads((result.audit/'summary.json').read_text())
    assert summary['preprocessing_options'] == dict(missing_output='parent_share',
        missing_cost_structure='same_sector_then_parent', inconsistent_targets='reconcile')
    assert summary['MRIO_split_solved'] is False
    for name, frame in original.items():
        pd.testing.assert_frame_equal(db.resolve(name), frame)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest


@pytest.mark.parametrize('argument,value', [
    ('missing_output', 'zero'), ('missing_cost_structure', 'average'), ('inconsistent_targets', 'ignore')])
def test_invalid_options_fail_before_creating_results(tmp_path, collected_data, argument, value):
    out = tmp_path/'result'
    with pytest.raises(ValueError, match=argument):
        database_disaggregation.prepare_inputs(database=make_database(), output_dir=out,
            **collected_data, **{argument: value})
    assert not out.exists()


def test_missing_output_can_stop_before_imputation(tmp_path, collected_data):
    out = tmp_path/'result'
    with pytest.raises(ValueError, match='missing native output'):
        database_disaggregation.prepare_inputs(database=make_database(), output_dir=out,
            missing_output='raise', **collected_data)
    assert not (out/'add_sectors.xlsx').exists()
    assert (out/'failure.json').is_file()


def test_missing_cost_structure_can_stop_before_donor_transfer(tmp_path, collected_data):
    path = collected_data['data_root']/'native/A.xlsx'
    book = load_workbook(path)
    book['Master'].delete_rows(3)
    book.save(path)
    book.close()
    with pytest.raises(ValueError, match='R2: missing cost structure'):
        database_disaggregation.prepare_inputs(database=make_database(), output_dir=tmp_path/'result',
            missing_cost_structure='raise', **collected_data)


def test_output_over_parent_budget_can_stop_without_proportional_capping(tmp_path, collected_data):
    inventory(collected_data['data_root']/'native/A.xlsx', sector='A', outputs=(20., 20., 20.))
    with pytest.raises(ValueError, match='child outputs exceed the parent budget'):
        database_disaggregation.prepare_inputs(database=make_database(), output_dir=tmp_path/'result',
            inconsistent_targets='raise', **collected_data)


def test_trade_over_budget_can_stop_before_adjustment(tmp_path):
    audit = Audit(tmp_path/'audit')
    try:
        with pytest.raises(ValueError, match='trade targets exceed'):
            reconcile_trade({('A', 'R1', 'R2'): 8.}, {('A', 'R1', 'R2'): 'direct'},
                {'A': 'Parent'}, {('A', 'R1'): 10.}, budgets(trade=5.), toy_policy(('A',)), audit,
                inconsistent_targets='raise')
    finally:
        audit.close()


def test_strict_consistent_cluster_totals_are_preserved(tmp_path):
    observations = [dict(members=['R1'], value=2., identifier='R1', source='test',
                        kind='direct', confidence=1.),
                    dict(members=['R1', 'R2'], value=6., identifier='GROUP', source='test',
                         kind='cluster', confidence=1.)]
    source = SimpleNamespace(observations=lambda *_: observations)
    native = SimpleNamespace(regions=['R1', 'R2'], budgets=budgets(('R1', 'R2')))
    targets = ChildTargets(pd.DataFrame(), pd.DataFrame(columns=['Sector', 'Region', 'Quantity']), pd.DataFrame())
    audit = Audit(tmp_path/'audit')
    try:
        values, _, _ = prepare_outputs(toy_policy(('A',)), source, native,
            database_disaggregation.Geography({'R1': 'G', 'R2': 'G'}), targets,
            {'A': 'Parent'}, {'A': 'Parent'}, audit, inconsistent_targets='raise')
    finally:
        audit.close()
    assert values[('A', 'R1')] == pytest.approx(2.)
    assert sum(values.values()) == pytest.approx(6.)
