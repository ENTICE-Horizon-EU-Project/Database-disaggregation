"""Only an explicit, bounded solver retry can follow a finished build."""
from pathlib import Path
import sys
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from retry_sector_after_run import (ready, solver_changes, checkpoint_workbook,
                                    verify_completed_inputs, archive_pre_solve_failure)
import hashlib
import json


@pytest.mark.parametrize('build,publication,expected',[
    ('running',None,False),
    ('running',{'status':'complete'},False),
    ('partial',{'status':'waiting_for_model'},False),
    ('partial',{'status':'checking_saved_results'},False),
    ('partial',{'status':'publishing_saved_results'},False),
    ('partial',{'status':'complete'},True),
    ('complete',{'status':'complete'},True),
    ('partial',{'status':'failed'},True),
])
def test_no_retry_before_the_build_and_saved_result_processing_finish(build,publication,expected):
    assert ready({'status':build},publication) is expected


def test_unexpected_source_failure_is_not_an_automatic_retry():
    with pytest.raises(RuntimeError,match='stopped unexpectedly'):
        ready({'status':'failed'},{'status':'failed'})


def test_override_changes_only_time_and_numerical_care():
    original=dict(Threads=2,TimeLimit=600.,NumericFocus=1,NonConvex=0,OutputFlag=1)
    retry={**original,'TimeLimit':1800.,'NumericFocus':3}
    changes=solver_changes(original,retry)
    assert set(changes)=={'TimeLimit','NumericFocus'}
    assert original['TimeLimit']==600. and original['NumericFocus']==1
    with pytest.raises(ValueError,match='only TimeLimit and NumericFocus'):
        solver_changes(original,{**retry,'FeasibilityTol':1e-4})
    with pytest.raises(ValueError,match='reduce'):
        solver_changes(original,{**retry,'TimeLimit':60.})
    with pytest.raises(ValueError,match='NumericFocus'):
        solver_changes(original,{**retry,'NumericFocus':0})


def test_resume_uses_the_checksum_verified_executed_file_not_excel_reexport(tmp_path):
    checkpoint=tmp_path/'trial/checkpoints/001_A';checkpoint.mkdir(parents=True)
    exact=tmp_path/'executed.xlsx';exact.write_bytes(b'full-precision source')
    (checkpoint/'source_add_sectors.xlsx').write_bytes(b're-export with different floating serialization')
    (checkpoint.parent.parent/'trial.json').write_text(json.dumps(dict(
        source_workbook=str(exact),source_workbook_sha256=hashlib.sha256(exact.read_bytes()).hexdigest())))
    assert checkpoint_workbook(checkpoint)==exact
    exact.write_bytes(b'edited source')
    with pytest.raises(RuntimeError,match='missing or changed'):
        checkpoint_workbook(checkpoint)


def test_completed_fingerprints_are_still_exactly_enforced(tmp_path):
    from test_inventory_history import payload
    from mario.ops.add_sector_steps import write_workbook_payload, _fingerprint
    from mario.ops.add_sector_workbook import load_add_sector_workbook_input
    from reconcile_model_trade import rewrite_sheets
    source=tmp_path/'source.xlsx';write_workbook_payload(payload(('A',)),source)
    restored=load_add_sector_workbook_input(source,table='IOT',read_inventories=True,split=True)[0]
    checkpoint=tmp_path/'cp';checkpoint.mkdir()
    (checkpoint/'state.json').write_text(json.dumps(dict(completed_sectors=['A'],
        sector_fingerprints={'A':_fingerprint(restored,'A')})))
    assert verify_completed_inputs(checkpoint,source)['all_exact_matches']
    changed=restored.split_info['Trades'].copy();changed['Quantity']=changed['Quantity'].astype(float);changed.loc[0,'Quantity']+=.01
    other=tmp_path/'edited.xlsx';rewrite_sheets(source,other,{'Trades':changed})
    with pytest.raises(RuntimeError,match='changed completed'):
        verify_completed_inputs(checkpoint,other)


def test_orchestration_repair_preserves_journal_but_cannot_repeat_a_solver_failure(tmp_path):
    trial=tmp_path/'trial';trial.mkdir()
    path=tmp_path/'retry-A.json'
    record=dict(status='failed',error="Completed sector 'A' was edited; resume from an earlier checkpoint.",
                trial=str(trial),accepted_checkpoints=[])
    path.write_text(json.dumps(record));archived=Path(archive_pre_solve_failure(path))
    assert not path.exists() and json.loads(archived.read_text())==record
    (trial/'checkpoints').mkdir();path.write_text(json.dumps(record))
    with pytest.raises(RuntimeError,match='no extra retry'):
        archive_pre_solve_failure(path)
    assert path.exists()
