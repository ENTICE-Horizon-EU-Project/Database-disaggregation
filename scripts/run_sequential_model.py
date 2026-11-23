"""Run a fixed MARIO model with joint pending-sibling trade reconciliation.

Starts from an unsplit preparation or accepted checkpoint. Each group is attempted once. Failed
model steps retain the last accepted database; no solver/model fallback occurs.
Every exact stage input and reconciliation audit is retained for publication.
"""
import argparse
from dataclasses import replace
from datetime import datetime, timezone
import gc
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import shutil
import time
import traceback
from zipfile import ZipFile, ZIP_DEFLATED

import pandas as pd

from reconcile_checkpoint_trade import reconcile
from reconcile_model_trade import rewrite_sheets
from run_model_trial import code_identity, fingerprints


def now():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')
    temporary.replace(path)


def front_plan(plan, name):
    """Move only the selected group; preserve every other group's membership."""
    if name not in plan:
        raise ValueError(f'Unknown planned group: {name}')
    return {name: list(plan[name]), **{k: list(v) for k, v in plan.items() if k != name}}


def selected_plan(plan, sectors=None):
    if not sectors:
        return [(k, list(v)) for k, v in plan.items()]
    selected = set(sectors)
    available = {s for group in plan.values() for s in group}
    if selected - available:
        raise ValueError(f'Unknown selected children: {selected - available}')
    # Selection cannot silently split a simultaneous group into a different model.
    result = []
    for name, group in plan.items():
        if selected.intersection(group):
            if not set(group) <= selected:
                raise ValueError(f'Select the entire planned group: {name}: {group}')
            result.append((name, list(group)))
    return result


def execution_plan(workbook, existing, *, completed=(), sectors=None):
    """Retain all Master groups, but schedule only children not yet accepted."""
    from mario.ops.add_sector_steps import validate_plan
    pending, parents = validate_plan(workbook, existing, completed=completed)
    full = {name:list(group) for name,group in workbook.intermediate_steps.items()}
    return full, selected_plan(dict(pending), sectors), parents


def archive_solver_cache(stage, destination):
    """Losslessly archive generated CSV/SQLite caches after an attempt finishes.

    Flows, state, source/step workbooks and diagnostics remain in place. Verify
    every archived byte before removing the generated working copies.
    """
    stage, destination = Path(stage), Path(destination)
    files = sorted(p for p in (stage/'checkpoints').rglob('*') if p.is_file()
                   and 'cvxlab' in p.relative_to(stage).parts
                   and (p.name == 'database.db' or (p.suffix == '.csv' and 'input_data' in p.parts)))
    if not files:
        return dict(files=0, original_bytes=0, archive_bytes=0)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix('.zip.tmp')
    entries = {str(p.relative_to(stage)): dict(sha256=hashlib.sha256(p.read_bytes()).hexdigest(),
                                              bytes=p.stat().st_size) for p in files}
    with ZipFile(temporary, 'w', compression=ZIP_DEFLATED, compresslevel=1, allowZip64=True) as archive:
        for p in files:
            archive.write(p, str(p.relative_to(stage)))
    with ZipFile(temporary) as archive:
        for name, info in entries.items():
            digest = hashlib.sha256()
            with archive.open(name) as handle:
                for block in iter(lambda: handle.read(4*1024*1024), b''):
                    digest.update(block)
            if digest.hexdigest() != info['sha256']:
                raise RuntimeError(f'Archive verification failed: {name}')
    for p in files:
        if hashlib.sha256(p.read_bytes()).hexdigest() != entries[str(p.relative_to(stage))]['sha256']:
            raise RuntimeError(f'Working cache changed while archiving: {p}')
    temporary.replace(destination)
    record = dict(archive=str(destination), files=len(files), entries=entries,
                  original_bytes=sum(v['bytes'] for v in entries.values()),
                  archive_bytes=destination.stat().st_size, verified=True)
    write_json(stage/'solver_cache_archive.json', record)
    for p in files:
        p.unlink()
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument('--prepared', type=Path)
    source_group.add_argument('--resume', type=Path, help='Accepted checkpoint with its exact executed source.')
    parser.add_argument('--workbook', type=Path, help='Explicit full source workbook when resuming.')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--options', type=Path, required=True)
    parser.add_argument('--solver-options', type=Path, required=True)
    parser.add_argument('--trade-audit', type=Path, required=True)
    parser.add_argument('--policy', type=Path, required=True)
    parser.add_argument('--solver', default='GUROBI', choices=['GUROBI'])
    parser.add_argument('--sectors', nargs='+', help='Optional complete groups for a bounded pilot.')
    parser.add_argument('--keep-solver-cache', action='store_true')
    parser.add_argument('--save-native-models', action='store_true', help='Retain each native Gurobi model and log for diagnosis.')
    args = parser.parse_args()
    import mario
    import cvxlab
    import database_disaggregation
    from mario.ops.add_sector_steps import _attach, validate_plan, load_checkpoint, _fingerprint
    source, root = (args.resume or args.prepared).resolve(), args.output.resolve()
    if root == source or source in root.parents:
        parser.error('Output must be separate from the immutable source preparation.')
    if args.workbook and not args.resume:
        parser.error('--workbook requires --resume.')
    if args.resume:
        from retry_sector_after_run import checkpoint_workbook
        source_state = json.loads((source/'state.json').read_text())
        workbook_path = (args.workbook or checkpoint_workbook(source)).resolve()
        baseline_directory = source/source_state.get('database_directory','database')
    else:
        source_state = {}
        workbook_path = source/'add_sectors.xlsx'
        baseline_directory = source/'baseline'
    if not (baseline_directory/'flows').is_dir() or not workbook_path.is_file():
        parser.error('Expected source flows and the executed input workbook.')
    root.mkdir(parents=True, exist_ok=False)
    options = json.loads(args.options.read_text())
    solver_options = json.loads(args.solver_options.read_text())
    if options.get('accounting') != 'inherit' or options.get('intermediate_prior_policy') != 'conservative':
        parser.error('This build requires inherited accounting and conservative family priors.')
    baseline_hashes = fingerprints(source if args.resume else baseline_directory)
    workbook_hash = hashlib.sha256(workbook_path.read_bytes()).hexdigest()
    prepared = root/'prepared'
    prepared.mkdir()
    shutil.copytree(baseline_directory, prepared/'baseline')
    shutil.copy2(workbook_path, prepared/'add_sectors.xlsx')
    if args.resume:
        shutil.copy2(source/'state.json', prepared/'source-state.json')
    shutil.copy2(args.trade_audit, prepared/'trades_audit.csv')
    shutil.copy2(args.policy, prepared/'policy.json')
    for name in ('preparation.json', 'geography.json', 'targets.json'):
        if (source/name).is_file():
            shutil.copy2(source/name, prepared/name)
    shutil.copy2(args.options, root/'split_model_options.json')
    shutil.copy2(args.solver_options, root/'solver_options.json')
    scripts = root/'code'; scripts.mkdir()
    for name in ('run_sequential_model.py', 'reconcile_checkpoint_trade.py', 'reconcile_model_trade.py', 'run_model_trial.py', 'retry_sector_after_run.py'):
        shutil.copy2(Path(__file__).parent/name, scripts/name)
    for module in ('split_priors.py','split_model.py','cvxlab_bridge.py','split_solution.py','add_sector_steps.py','add_sector_split.py'):
        shutil.copy2(Path(mario.__file__).parent/'ops'/module, scripts/module)
    shutil.copy2(Path(mario.__file__).parent/'api/database.py', scripts/'database_api.py')
    shutil.copy2(Path(database_disaggregation.__file__).parent/'reconciliation/row_trade.py', scripts/'row_trade.py')
    code = {name: code_identity(module) for name, module in
            [('mario', mario), ('cvxlab', cvxlab), ('database_disaggregation', database_disaggregation)]}
    runtime = {name: version(name) for name in ('mariopy','cvxlab','cvxpy','numpy','pandas','gurobipy')}
    db = load_checkpoint(source) if args.resume else mario.parse_from_parquet(str(prepared/'baseline/flows'), table='IOT', mode='flows')
    db.read_add_sectors_excel(prepared/'add_sectors.xlsx', read_inventories=True, split=True)
    workbook = db.add_sectors_workbook
    initial_completed = list(source_state.get('completed_sectors', []))
    for sector in initial_completed:
        if _fingerprint(workbook,sector) != source_state['sector_fingerprints'][sector]:
            raise ValueError(f'Executed source changed completed input {sector!r}.')
    full_plan, schedule, parents = execution_plan(
        workbook, db.get_index('Sector'), completed=initial_completed, sectors=args.sectors)
    started = time.monotonic()
    progress = dict(format='entice-reconciled-sequential-v1', status='running', started_at=now(),
                    source_checkpoint=str(source) if args.resume else None,
                    source_preparation=None if args.resume else str(source),
                    source_workbook=str(workbook_path), source_baseline_sha256=baseline_hashes,
                    source_workbook_sha256=workbook_hash, regions=len(db.get_index('Region')),
                    baseline_sectors=len(db.get_index('Sector'))-len(initial_completed),
                    initial_completed_sectors=initial_completed,
                    requested_children_total=workbook.master_sheet.Sector.nunique(),
                    planned_children=sum(len(s) for _,s in schedule),
                    schedule=[dict(step=n, sectors=s) for n,s in schedule], attempts=[],
                    split_model_options=options, solver=args.solver, solver_options=solver_options,
                    runtime=runtime, code=code, accepted_sectors=initial_completed.copy(),
                    accepted_this_run=[], failed_sectors=[], last_checkpoint=str(source) if args.resume else None)
    progress_path = root/'sequential-run.json'
    write_json(progress_path, progress)
    current_workbook = prepared/'add_sectors.xlsx'
    last_checkpoint = source if args.resume else None
    try:
        for ordinal, (name, children) in enumerate(schedule, 1):
            stage = root/'stages'/f'{ordinal:03d}'
            stage.mkdir(parents=True)
            tick = time.monotonic()
            attempt = dict(ordinal=ordinal, step=name, sectors=children, status='reconciling', started_at=now(), directory=str(stage))
            progress['attempts'].append(attempt)
            progress['current_step'] = name
            write_json(progress_path, progress)
            print(f'\nSTAGE {ordinal}/{len(schedule)} START {name} {children}', flush=True)
            existing = set(db.get_index('Sector'))
            affected_parents = {parents[s] for s in children}
            siblings = sorted(s for s,p in parents.items() if p in affected_parents and s not in existing)
            kwargs = dict(database=db, workbook_payload=workbook)
            if last_checkpoint is None:
                kwargs['prepared'] = prepared
            try:
                reconciliation, updated = reconcile(last_checkpoint, current_workbook, siblings,
                    stage/'reconciliation', prepared/'trades_audit.csv', prepared/'policy.json', **kwargs)
            except RuntimeError as exc:
                # Expected projection/solver failure; no model call or parameter retries.
                attempt.update(status='trade_reconciliation_failed', error=str(exc), traceback=traceback.format_exc(),
                               elapsed_seconds=time.monotonic()-tick)
                progress['failed_sectors'].extend(children)
                write_json(stage/'reconciliation_failure.json', attempt)
                write_json(progress_path, progress)
                print(f'STAGE {ordinal} TRADE RECONCILIATION FAILED: {exc}', flush=True)
                continue
            reordered = front_plan(full_plan, name)
            workbook = replace(updated, intermediate_steps=reordered)
            stage_input = stage/'add_sectors.xlsx'
            frame = pd.DataFrame({k: pd.Series(v) for k,v in reordered.items()})
            rewrite_sheets(stage/'reconciliation/add_sectors.xlsx', stage_input, {'Intermediate steps':frame})
            _attach(db, workbook)
            stage_solver_options = dict(solver_options)
            if args.save_native_models:
                stage_solver_options.update(LogFile=str(stage/'gurobi.log'),
                                            save_file=str(stage/'numerical_model.mps.gz'))
            manifest = dict(status='running', started_at=now(), source_workbook=str(stage_input),
                            source_workbook_sha256=hashlib.sha256(stage_input.read_bytes()).hexdigest(),
                            source_baseline_sha256=fingerprints(last_checkpoint or prepared/'baseline'),
                            split_model_options=options, solver=args.solver, solver_options=stage_solver_options,
                            stop_after_step=name, on_step_failure='continue', runtime=runtime, code=code,
                            reconciliation=str(stage/'reconciliation/reconciliation.json'))
            manifest['source_checkpoint' if last_checkpoint else 'source_preparation'] = str(last_checkpoint or prepared)
            write_json(stage/'trial.json', manifest)
            attempt.update(status='solving', reconciled_siblings=siblings,
                           absolute_trade_change_MUSD=reconciliation['absolute_trade_change_MUSD'])
            write_json(progress_path, progress)
            try:
                db.add_sectors('inventories', split=True, intermediate_steps=True,
                    save_intermediates=stage/'checkpoints', stop_after_step=name,
                    on_step_failure='continue', solver=args.solver,
                    solver_parameters=stage_solver_options, split_model_options=options)
            except Exception as exc:
                manifest.update(status='failed', error=str(exc), traceback=traceback.format_exc(),
                                accepted_checkpoints=[], elapsed_seconds=time.monotonic()-tick)
                write_json(stage/'trial.json', manifest)
                raise
            report = db._intermediate_steps_report
            if len(report['attempts']) != 1 or report['attempts'][0]['step'] != name:
                raise RuntimeError('Expected exactly one scheduled group attempt.')
            result = report['attempts'][0]
            accepted = result['status'] == 'accepted'
            manifest.update(status='accepted' if accepted else 'failed', execution_report=report,
                            accepted_checkpoints=[report['last_checkpoint_this_call']] if accepted else [],
                            completed_sectors=getattr(db,'_intermediate_steps_state',{}).get('completed_sectors',[]),
                            source_baseline_unchanged=fingerprints(last_checkpoint or prepared/'baseline') == manifest['source_baseline_sha256'],
                            source_workbook_unchanged=hashlib.sha256(stage_input.read_bytes()).hexdigest() == manifest['source_workbook_sha256'],
                            elapsed_seconds=time.monotonic()-tick)
            if not manifest['source_baseline_unchanged'] or not manifest['source_workbook_unchanged']:
                raise RuntimeError('An immutable input changed during the attempt.')
            write_json(stage/'trial.json', manifest)
            if not args.keep_solver_cache:
                attempt['solver_cache_archive'] = archive_solver_cache(stage, root/'solver-archives'/f'{ordinal:03d}.zip')
            if accepted:
                last_checkpoint = Path(report['last_checkpoint_this_call'])
                progress['accepted_sectors'].extend(children)
                progress['accepted_this_run'].extend(children)
                progress['last_checkpoint'] = str(last_checkpoint)
                progress['last_accepted_trial'] = str(stage)
            else:
                progress['failed_sectors'].extend(children)
                attempt['error'] = result.get('error')
            current_workbook = stage_input
            attempt.update(status=result['status'], elapsed_seconds=time.monotonic()-tick, finished_at=now())
            progress['elapsed_seconds'] = time.monotonic()-started
            write_json(progress_path, progress)
            print(f'STAGE {ordinal}/{len(schedule)} END {name}: {result["status"]}; '
                  f'accepted={len(progress["accepted_sectors"])} elapsed={attempt["elapsed_seconds"]:.1f}s', flush=True)
            gc.collect()
        progress.update(status='complete' if not progress['failed_sectors'] else 'partial',
                        finished_at=now(), total_database_sectors=len(db.get_index('Sector')),
                        elapsed_seconds=time.monotonic()-started)
    except Exception as exc:
        progress.update(status='failed', error=str(exc), traceback=traceback.format_exc(), finished_at=now())
        traceback.print_exc()
    finally:
        progress['source_baseline_unchanged'] = fingerprints(source if args.resume else baseline_directory) == baseline_hashes
        progress['source_workbook_unchanged'] = hashlib.sha256(workbook_path.read_bytes()).hexdigest() == workbook_hash
        if not progress['source_baseline_unchanged'] or not progress['source_workbook_unchanged']:
            progress.update(status='failed', integrity_error='Original preparation changed.')
        write_json(progress_path, progress)
    print(json.dumps({k: progress.get(k) for k in ('status','accepted_sectors','failed_sectors','error','last_checkpoint')}, indent=2), flush=True)
    return 1 if progress['status']=='failed' else 0


if __name__ == '__main__':
    raise SystemExit(main())
