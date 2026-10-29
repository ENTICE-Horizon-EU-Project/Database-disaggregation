from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil

import pandas as pd
import pytest
from database_disaggregation.core.shared_runs import publish_trial, remaining_workbook, run_name


def trial_fixture(tmp_path,status='accepted'):
    from test_inventory_history import make_trial, payload
    if status == 'accepted':
        return make_trial(tmp_path, payload(('New',)), active=['New'], completed=['New'], index=1)[0]
    from test_parent_budgets import _baseline
    _baseline(tmp_path)
    trial=tmp_path/'trial';trial.mkdir()
    source=trial/'add_sectors.xlsx'
    pd.DataFrame({'Sector':['New']}).to_excel(source,sheet_name='Master',index=False)
    manifest=dict(status=status,started_at='2026-10-21T04:55:00+00:00',source_preparation=str(tmp_path),
                  accepted_checkpoints=[])
    (trial/'trial.json').write_text(json.dumps(manifest))
    return trial


@pytest.mark.parametrize('status',['accepted','failed'])
def test_publication_pairs_names_and_preserves_inputs_and_matrices(tmp_path,status):
    trial=trial_fixture(tmp_path,status)
    original={str(p.relative_to(trial)):hashlib.sha256(p.read_bytes()).hexdigest() for p in trial.rglob('*') if p.is_file()}
    options=dict(inventory_root=tmp_path/'Inventories/D2.8 inventories',database_root=tmp_path/'Database')
    result=publish_trial(trial,**options)
    inventory=Path(result['inventory'])
    database=tmp_path/'Database'/result['name']
    assert inventory.name==database.name=='20261021 0655 - 3 regions and 1 sectors'
    assert (inventory/'source_add_sectors.xlsx').read_bytes()==(trial/'add_sectors.xlsx').read_bytes()
    if status=='accepted':
        checkpoint=Path(json.loads((trial/'trial.json').read_text())['accepted_checkpoints'][-1])
        assert (inventory/'step_add_sectors.xlsx').read_bytes()==(checkpoint/'step_add_sectors.xlsx').read_bytes()
        assert pd.read_excel(inventory/'add_sectors.xlsx',sheet_name='Master').Sector.nunique()==1
        assert 'Intermediate steps' in pd.ExcelFile(inventory/'add_sectors.xlsx').sheet_names
    else:
        assert (inventory/'add_sectors.xlsx').read_bytes()==(trial/'add_sectors.xlsx').read_bytes()
    assert (database/'flows').exists()==(status=='accepted')
    if status=='accepted':
        assert result['database']==str(database)
        assert remaining_workbook(database)==inventory/'remaining_add_sectors.xlsx'
        state=json.loads((database/'state.json').read_text())
        assert state['database_directory']=='.'
        assert all(hashlib.sha256((database/p).read_bytes()).hexdigest()==digest for p,digest in state['files'].items())
        from mario.ops.add_sector_steps import load_checkpoint
        assert load_checkpoint(database).get_index('Region')==['R1','R2','R3']
    else:
        assert result['database'] is None and not database.exists()
        assert (inventory/'diagnostics/trial.json').is_file()
    assert original=={str(p.relative_to(trial)):hashlib.sha256(p.read_bytes()).hexdigest() for p in trial.rglob('*') if p.is_file()}
    with pytest.raises(FileExistsError):publish_trial(trial,**options)


def test_run_name_keeps_original_project_time_and_rejects_ambiguous_times():
    assert run_name('2026-10-20T20:09:02+00:00',13,17)=='20261020 2209 - 13 regions and 17 sectors'
    with pytest.raises(ValueError):run_name(datetime(2026,10,21),13,67)


@pytest.mark.parametrize('report_only', [False, True])
def test_publication_keeps_raw_and_cleaned_points_and_approximate_label(tmp_path, report_only):
    trial = trial_fixture(tmp_path)
    manifest = json.loads((trial/'trial.json').read_text())
    checkpoint = Path(manifest['accepted_checkpoints'][-1])
    state_path = checkpoint/'state.json'
    state = json.loads(state_path.read_text())
    validation = dict(status='postprocessed_pending_review' if report_only else 'approximate_after_cleanup',
                      absolute_tolerance_original_units=1e-6 if report_only else .01,
                      relative_tolerance=1e-8, residuals_enforced=not report_only)
    state['preservation'] = {'numerical_validation': validation}
    state_path.write_text(json.dumps(state))
    model = checkpoint/'cvxlab/model'
    model.mkdir(parents=True)
    artifacts = {'solution_cleanup.json': b'{"status":"accepted_with_cleanup"}',
                 'raw_model_solution.json': b'[{"objective_finite":false}]',
                 'returned_solution_scaled.npz': b'raw point',
                 'cleaned_solution_scaled.npz': b'cleaned point'}
    for name, contents in artifacts.items():
        (model/name).write_bytes(contents)
    published = publish_trial(trial, inventory_root=tmp_path/'Inventories', database_root=tmp_path/'Database')
    database = Path(published['database'])
    assert json.loads((database/'run.json').read_text())['numerical_validation'] == validation
    for name, contents in artifacts.items():
        assert (database/'diagnostics'/name).read_bytes() == contents
    assert validation['status'] in (database/'README.md').read_text()
    assert validation['status'] in (Path(published['inventory'])/'README.md').read_text()
    if report_only:
        assert 'diagnostic only' in (database/'README.md').read_text()
