"""Queue one reconciled sector retry after a sequential build has finished.

Uses the final accepted checkpoint, the same model options and one explicit
solver configuration. No concurrent solve, model fallback or parameter sweep.
"""
import argparse
import hashlib
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback

import pandas as pd
import psutil

from reconcile_model_trade import rewrite_sheets
from run_sequential_model import archive_solver_cache, front_plan, write_json


def ready(run, completion):
    if run['status'] == 'failed':
        raise RuntimeError('The source build stopped unexpectedly; do not retry automatically.')
    if run['status'] not in ('complete', 'partial'):
        return False
    return completion is None or completion['status'] in ('complete', 'failed')


def solver_changes(original, retry):
    changed = {k: dict(previous=original.get(k), retry=retry.get(k))
               for k in original.keys() | retry.keys() if original.get(k) != retry.get(k)}
    if set(changed) - {'TimeLimit', 'NumericFocus'}:
        raise ValueError('A bounded retry may change only TimeLimit and NumericFocus.')
    if retry.get('TimeLimit', 0) < original.get('TimeLimit', 0):
        raise ValueError('The retry must not reduce the time allowance.')
    if not original.get('NumericFocus', 0) <= retry.get('NumericFocus', 0) <= 3:
        raise ValueError('NumericFocus must retain or increase numerical care, up to 3.')
    return changed


def checkpoint_workbook(checkpoint):
    """Prefer the checksum-verified executed input over an Excel re-export.

    A checkpoint's source_add_sectors.xlsx is a readable copy written by Excel
    tooling; its numeric serialization can differ at the final binary digits.
    The controlled trial records the exact workbook actually supplied to MARIO.
    Never substitute it silently after a checksum failure.
    """
    checkpoint = Path(checkpoint)
    manifest_path = checkpoint.parent.parent/'trial.json'
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text())
        source = Path(manifest['source_workbook'])
        if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != manifest['source_workbook_sha256']:
            raise RuntimeError('The exact executed source workbook is missing or changed.')
        return source
    return checkpoint/'source_add_sectors.xlsx'


def verify_completed_inputs(checkpoint, workbook_path):
    """Retain MARIO's exact fingerprint guard before preparing a new solve."""
    from mario.ops.add_sector_workbook import load_add_sector_workbook_input
    from mario.ops.add_sector_steps import _fingerprint
    state = json.loads((Path(checkpoint)/'state.json').read_text())
    workbook = load_add_sector_workbook_input(workbook_path, table='IOT',
                                              read_inventories=True, split=True)[0]
    completed = state['completed_sectors']
    if not set(completed) <= set(workbook.master_sheet.Sector):
        raise RuntimeError('Expected the full executed source, including all completed children.')
    changed = [sector for sector in completed
               if _fingerprint(workbook, sector) != state['sector_fingerprints'][sector]]
    if changed:
        raise RuntimeError(f'Prepared retry changed completed input fingerprints: {changed}')
    return dict(completed_input_fingerprints_checked=len(completed), all_exact_matches=True,
                fingerprint_validation_weakened=False)


def archive_pre_solve_failure(journal):
    """Allow an orchestration repair only when no model checkpoint work began."""
    record = json.loads(journal.read_text())
    error = record.get('error') or ''
    trial = Path(record.get('trial', ''))
    if (record.get('status') != 'failed' or not error.startswith('Completed sector ')
            or 'was edited; resume from an earlier checkpoint.' not in error
            or record.get('accepted_checkpoints') or (trial/'checkpoints').exists()):
        raise RuntimeError('This is not a verified pre-solver fingerprint failure; no extra retry is authorised.')
    destination = journal.with_name(journal.stem + '-pre-solver-' + datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S') + '.json')
    if destination.exists():
        raise FileExistsError(destination)
    journal.rename(destination)
    return str(destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--sector', required=True)
    parser.add_argument('--solver-options', type=Path, required=True)
    parser.add_argument('--build-pid', type=int)
    parser.add_argument('--repair-pre-solve-failure', action='store_true',
                        help='Repair an exact-input lookup error that never reached the model; retains its journal.')
    args = parser.parse_args()
    root = args.run.resolve()
    journal = root/f'retry-{args.sector}.json'
    params = json.loads(args.solver_options.read_text())
    original = json.loads((root/'solver_options.json').read_text())
    changes = solver_changes(original, params)
    repair_record = None
    if journal.exists():
        if not args.repair_pre_solve_failure:
            raise FileExistsError('This sector already has a queued retry; inspect its journal.')
        repair_record = archive_pre_solve_failure(journal)
    record = dict(status='waiting_for_build', source_run=str(root), sector=args.sector,
                  requested_at=datetime.now(timezone.utc).isoformat(), max_attempts=1,
                  solver='GUROBI', solver_options=params, solver_parameter_changes=changes,
                  model_changed=False, tolerances_changed=False,
                  original_attempt_note='See the native source-run log: CVXPY user_limit alone does not identify which termination condition occurred.',
                  runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    if repair_record:
        record.update(repaired_pre_solve_record=repair_record,
                      preceding_queued_solver_attempts=0,
                      orchestration_fix='Use the exact executed input; retain every completed-sector fingerprint.')
    write_json(journal, record)
    try:
        while True:
            run = json.loads((root/'sequential-run.json').read_text())
            completion_path = root/'completion.json'
            completion = json.loads(completion_path.read_text()) if completion_path.is_file() else None
            if ready(run, completion):
                break
            if args.build_pid and run['status'] == 'running':
                try:
                    process = psutil.Process(args.build_pid)
                    alive = process.is_running() and process.status() != psutil.STATUS_ZOMBIE
                except psutil.NoSuchProcess:
                    alive = False
                if not alive:
                    raise RuntimeError('The build process exited without writing a final status.')
            time.sleep(10)
        checkpoint = Path(run['last_checkpoint'])
        state = json.loads((checkpoint/'state.json').read_text())
        if args.sector in state['completed_sectors']:
            record.update(status='not_needed', reason='Sector already accepted in the finished build.')
            write_json(journal, record)
            return 0
        workbook = checkpoint_workbook(checkpoint)
        master = pd.read_excel(workbook, sheet_name='Master')
        parents = master.set_index('Sector')['Parent Sector'].to_dict()
        if args.sector not in parents:
            raise ValueError('Requested child is absent from the final source workbook.')
        parent = parents[args.sector]
        siblings = sorted(s for s,p in parents.items() if p == parent and s not in state['completed_sectors'])
        plan_frame = pd.read_excel(workbook, sheet_name='Intermediate steps')
        plan = {k: v.dropna().astype(str).tolist() for k,v in plan_frame.items()}
        group = [name for name, sectors in plan.items() if args.sector in sectors]
        if len(group) != 1 or plan[group[0]] != [args.sector]:
            raise ValueError('One-sector retry requires a singleton group in the saved plan.')
        name = group[0]
        started = datetime.now(timezone.utc)
        output = root.parent/f'{started:%Y%m%d_%H%M%S}_{args.sector}_retry_after_full61'
        output.mkdir(exist_ok=False)
        shutil.copy2(__file__, output/'retry_sector_after_run.py')
        write_json(output/'solver_options.json', params)
        shutil.copy2(root/'split_model_options.json', output/'split_model_options.json')
        record.update(status='reconciling', started_at=started.isoformat(), output=str(output),
                      source_checkpoint=str(checkpoint), source_workbook=str(workbook), pending_siblings=siblings,
                      causal_comparison_note='Final-checkpoint retry; other sectors have since been added and pending trade is re-reconciled. A different outcome cannot be attributed to solver parameters alone.')
        write_json(journal, record)
        scripts = Path(__file__).resolve().parent
        subprocess.run([sys.executable, '-u', str(scripts/'reconcile_checkpoint_trade.py'),
                        '--checkpoint', str(checkpoint), '--workbook', str(workbook),
                        '--sectors', *siblings, '--output', str(output/'reconciliation'),
                        '--trade-audit', str(root/'prepared/trades_audit.csv'),
                        '--policy', str(root/'prepared/policy.json')], check=True)
        reordered = front_plan(plan, name)
        input_path = output/'add_sectors.xlsx'
        rewrite_sheets(output/'reconciliation/add_sectors.xlsx', input_path,
                       {'Intermediate steps': pd.DataFrame({k: pd.Series(v) for k,v in reordered.items()})})
        record['completed_input_verification'] = verify_completed_inputs(checkpoint, input_path)
        record.update(status='solving', trial=str(output/'trial'))
        write_json(journal, record)
        command = [sys.executable, '-u', str(scripts/'run_model_trial.py'), '--resume', str(checkpoint),
                   '--workbook', str(input_path), '--output', str(output/'trial'),
                   '--options', str(output/'split_model_options.json'), '--solver', 'GUROBI',
                   '--solver-options', str(output/'solver_options.json'), '--stop-after-step', name,
                   '--on-step-failure', 'raise', '--no-publish']
        result = subprocess.run(command, check=False)
        manifest = json.loads((output/'trial/trial.json').read_text())
        accepted = manifest.get('accepted_checkpoints', [])
        if result.returncode == 0:
            if len(accepted) != 1:
                raise RuntimeError('Success requires exactly one newly accepted checkpoint.')
            final = json.loads((Path(accepted[0])/'state.json').read_text())
            if final['completed_sectors'] != state['completed_sectors'] + [args.sector]:
                raise RuntimeError('Retry checkpoint does not contain exactly the requested addition.')
            outcome = 'accepted'
        else:
            if accepted:
                raise RuntimeError('Runner failed after writing an accepted checkpoint; inspect before publishing.')
            outcome = 'failed'
        record.update(status='publishing', outcome=outcome, exit_code=result.returncode,
                      model_status=manifest['status'], completed_sectors=manifest.get('completed_sectors', []),
                      accepted_checkpoints=accepted, error=manifest.get('error'))
        write_json(journal, record)
        archive_solver_cache(output/'trial', output/'solver-cache.zip')
        from database_disaggregation.core.shared_runs import publish_trial
        publication = publish_trial(output/'trial')
        record.update(status=outcome, publication=publication, finished_at=datetime.now(timezone.utc).isoformat())
        write_json(journal, record)
        write_json(output/'retry.json', record)
        for target in (publication.get('database'), publication.get('inventory')):
            if target:
                folder = Path(target)
                shutil.copy2(output/'retry.json', folder/'retry.json')
                shutil.copytree(output/'reconciliation', folder/'retry_reconciliation')
        print(json.dumps(record, indent=2), flush=True)
        return 0 if outcome == 'accepted' else 1
    except Exception as exc:
        record.update(status='error', error=str(exc), traceback=traceback.format_exc(),
                      finished_at=datetime.now(timezone.utc).isoformat())
        write_json(journal, record)
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
