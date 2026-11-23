"""Sequential driver preserves plans, source data and recoverable caches."""
import json
from pathlib import Path
import sys
from zipfile import ZipFile

import numpy as np
import pandas as pd
import pytest

SCRIPTS = Path(__file__).resolve().parents[1]/'scripts'
sys.path.insert(0, str(SCRIPTS))
from run_sequential_model import archive_solver_cache, front_plan, selected_plan
import reconcile_checkpoint_trade as reconciliation


def test_current_group_first_keeps_all_children_and_does_not_split_groups():
    plan={'cars':['CAR'], 'batteries':['LFP','NMC'], 'other':['ABC']}
    result=front_plan(plan, 'batteries')
    assert list(result)==['batteries','cars','other']
    assert sorted(s for v in result.values() for s in v)==['ABC','CAR','LFP','NMC']
    assert list(plan)==['cars','batteries','other']
    assert selected_plan(plan,['LFP','NMC'])==[('batteries',['LFP','NMC'])]
    with pytest.raises(ValueError,match='entire planned group'):
        selected_plan(plan,['LFP'])
    with pytest.raises(ValueError,match='Unknown'):
        selected_plan(plan,['XYZ'])


def test_archive_round_trip_retains_state_flows_and_diagnostics(tmp_path):
    stage=tmp_path/'stage'
    cache=stage/'checkpoints/001/cvxlab/project/input_data'
    cache.mkdir(parents=True)
    original={cache/'Z.csv': b'row,value\n0,0.123456789012345\n',
              cache.parent/'database.db': bytes(range(256))*100}
    keep={stage/'checkpoints/001/state.json': b'{"complete":true}',
          cache.parent/'model_solution.json': b'{"status":"optimal"}',
          stage/'checkpoints/001/database/flows/Z.parquet': b'PARQUET'}
    for p,value in {**original,**keep}.items():
        p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(value)
    archive=tmp_path/'cache.zip'
    report=archive_solver_cache(stage,archive)
    assert report['verified'] and report['files']==2
    with ZipFile(archive) as zipped:
        assert {str(p.relative_to(stage)):v for p,v in original.items()}=={
            name:zipped.read(name) for name in zipped.namelist()}
    assert all(not p.exists() for p in original)
    assert all(p.read_bytes()==v for p,v in keep.items())


def test_in_memory_reconciliation_changes_only_pending_trade(tmp_path,monkeypatch):
    import mario
    from mario.ops.add_sector_steps import write_workbook_payload
    from test_parent_budgets import _baseline
    from test_inventory_history import payload
    source=tmp_path/'source';source.mkdir()
    flows=_baseline(source)
    db=mario.parse_from_parquet(str(flows),table='IOT',mode='flows')
    workbook=payload()
    workbook.split_info['Total outputs']['Quantity']=2.
    path=source/'add_sectors.xlsx'
    write_workbook_payload(workbook,path)
    audit=tmp_path/'trades.csv'
    pd.DataFrame(columns=['sector','origin','destination','source_kind']).to_csv(audit,index=False)
    policy=tmp_path/'policy.json';policy.write_text(json.dumps({'trade':{'weights':{'imputed':.1}}}))
    def fit(*args,**kwargs):
        return np.zeros_like(args[4]),dict(status='projected')
    monkeypatch.setattr(reconciliation,'fit_row_trade',fit)
    monkeypatch.setattr(mario,'parse_from_parquet',lambda *a,**k:pytest.fail('Do not reload live database'))
    report,updated=reconciliation.reconcile(None,path,['A','B'],tmp_path/'projection',audit,policy,
                                            prepared=source,database=db,workbook_payload=workbook)
    assert report['baseline_unchanged'] and report['outputs_unchanged']
    assert report['dense_foreign_target_count']==12
    assert updated.split_info['Trades']['Quantity'].eq(0.).all()
    pd.testing.assert_frame_equal(updated.split_info['Total outputs'],workbook.split_info['Total outputs'])
    assert updated.inventories_by_sheet is workbook.inventories_by_sheet
    assert workbook.split_info['Trades']['Quantity'].eq(2.).all()


def test_resume_schedules_pending_children_but_preserves_the_complete_plan():
    from test_inventory_history import payload
    from run_sequential_model import execution_plan
    from mario.ops.add_sector_steps import validate_plan
    from dataclasses import replace
    workbook=payload(("A","B","C"))
    full,schedule,parents=execution_plan(workbook,["Parent","A"],completed=["A"])
    assert list(full)==["Step A","Step B","Step C"]
    assert schedule==[("Step B",["B"]),("Step C",["C"])]
    assert parents=={"A":"Parent","B":"Parent","C":"Parent"}
    # The resumed per-call workbook must remain valid for MARIO itself.
    reordered=front_plan(full,"Step C")
    pending,_=validate_plan(replace(workbook,intermediate_steps=reordered),["Parent","A"],completed=["A"])
    assert pending==[("Step C",["C"]),("Step B",["B"])]
