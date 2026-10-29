"""The preparation API consumes MARIO objects, independent of parser/storage."""
import hashlib
import json

import pandas as pd
import pytest

from database_disaggregation import Geography, prepare_inputs
from database_disaggregation.core.parent_budgets import read_child_targets


def make_database():
    import mario
    axis = pd.MultiIndex.from_product([['R1', 'R2', 'R3'], ['Sector'], ['Parent']],
                                      names=['Region', 'Level', 'Item'])
    demand = pd.MultiIndex.from_product([['R1', 'R2', 'R3'], ['Consumption category'], ['HH']],
                                        names=axis.names)
    units = {kind: pd.DataFrame({'unit': [unit]}, index=[item]) for kind, item, unit in
             [('Sector', 'Parent', 'M USD'), ('Factor of production', 'VA', 'M USD')]}
    matrices = dict(Z=pd.DataFrame(2., index=axis, columns=axis),
                    Y=pd.DataFrame(4., index=axis, columns=demand),
                    V=pd.DataFrame(12., index=['VA'], columns=axis))
    units['Satellite account'] = pd.DataFrame({'unit': ['tonne']}, index=['CO2'])
    matrices.update(E=pd.DataFrame(1., index=['CO2'], columns=axis),
                    EY=pd.DataFrame(0., index=['CO2'], columns=demand))
    return mario.Database(name='Generic monetary IOT', table='IOT', units=units, **matrices)


@pytest.mark.parametrize('aggregate', [False, True])
@pytest.mark.parametrize('clean', [False, True])
def test_preparation_from_database_has_no_disk_roundtrip(tmp_path, monkeypatch, aggregate, clean):
    import mario
    from test_geography import inventory
    from test_reconciliation import toy_policy
    from database_disaggregation.core import disaggregation
    from database_disaggregation.reconciliation import pipeline

    database = make_database()
    originals = {name: database.resolve(name).copy() for name in ('Z', 'Y', 'V', 'E', 'X')}
    source = tmp_path/'source'; source.mkdir()
    inventory(source/'A.xlsx', sector='A', outputs=(6., 6., 6.))
    original_hash = hashlib.sha256((source/'A.xlsx').read_bytes()).hexdigest()
    geo = Geography({'R1':'G', 'R2':'G', 'R3':'H'}) if aggregate else None

    def forbidden(*args, **kwargs):
        pytest.fail('An in-memory Database must not be reloaded or exported during preparation.')
    monkeypatch.setattr(disaggregation, 'load_baseline', forbidden)
    monkeypatch.setattr(pipeline, 'load_baseline', forbidden)
    monkeypatch.setattr(mario, 'parse_gtap', forbidden)
    monkeypatch.setattr(mario, 'parse_from_parquet', forbidden)
    monkeypatch.setattr(mario.Database, 'to_parquet', forbidden)

    prepared = prepare_inputs(source, tmp_path/'prepared', database=database,
        geography=geo, steps={'First':['A']}, cleaning_policy=toy_policy(('A',)) if clean else None,
        source_paths={'purdue_trade':None, 'purdue_split_targets':None, 'partner_templates':None})
    assert not list(prepared.rglob('*.parquet'))
    manifest = json.loads((prepared/'preparation.json').read_text())
    assert manifest['baseline_kind'] == 'mario_database'
    assert manifest['baseline_exported'] is False
    if clean:
        events = [json.loads(line) for line in (prepared/'reconciled/audit/changes.jsonl').read_text().splitlines()]
        fingerprints = [e for e in events if e['rule']=='in_memory_baseline']
        assert {e['matrix'] for e in fingerprints} == {'Z', 'Y', 'V', 'E', 'X'}
        assert all(len(e['sha256'])==64 for e in fingerprints)

    output = read_child_targets([prepared/'add_sectors.xlsx']).output
    assert set(output.Region) == ({'G', 'H'} if aggregate else {'R1','R2','R3'})
    assert output.Quantity.sum() == pytest.approx(18.)
    target = database.aggregate(None, levels='Region', region_aggregation=geo.mapping,
                                zero_output_epsilon=None, inplace=False) if geo else database.copy()
    target.read_add_sectors_excel(prepared/'add_sectors.xlsx', read_inventories=True, split=True)
    assert target.add_sectors_workbook.intermediate_steps == {'First':['A']}
    for name, frame in originals.items():
        pd.testing.assert_frame_equal(database.resolve(name), frame)
    assert database.get_index('Region') == ['R1','R2','R3']
    assert hashlib.sha256((source/'A.xlsx').read_bytes()).hexdigest() == original_hash


def test_ambiguous_database_and_file_inputs_fail_before_writing(tmp_path):
    database = make_database()
    for kwargs in ({'baseline_path':tmp_path/'unused'}, {'baseline_format':'gtap_csv'}):
        with pytest.raises(ValueError, match='not both'):
            prepare_inputs(tmp_path/'source', tmp_path/'prepared', database=database, **kwargs)
    assert not (tmp_path/'prepared').exists()



def test_memory_and_file_inputs_prepare_the_same_workbook(tmp_path):
    from test_geography import inventory
    from test_reconciliation import toy_policy
    from openpyxl import load_workbook
    database = make_database()
    database.to_parquet(path=tmp_path/'baseline', flows=True, coefficients=False)
    source = tmp_path/'source'; source.mkdir()
    inventory(source/'A.xlsx', sector='A', outputs=(6., 6., 6.))
    options = dict(geography=Geography({'R1':'G', 'R2':'G', 'R3':'H'}),
                   cleaning_policy=toy_policy(('A',)), intermediate_steps=True,
                   source_paths={'purdue_trade':None, 'purdue_split_targets':None, 'partner_templates':None})
    memory = prepare_inputs(source, tmp_path/'memory', database=database, **options)
    disk = prepare_inputs(source, tmp_path/'disk', baseline_path=tmp_path/'baseline/flows', **options)
    a = load_workbook(memory/'add_sectors.xlsx', read_only=True, data_only=True)
    b = load_workbook(disk/'add_sectors.xlsx', read_only=True, data_only=True)
    try:
        assert a.sheetnames == b.sheetnames
        for sheet in a.sheetnames:
            pd.testing.assert_frame_equal(pd.DataFrame(a[sheet].values), pd.DataFrame(b[sheet].values),
                                          check_exact=False, rtol=1e-12, atol=1e-12)
    finally:
        a.close(); b.close()
