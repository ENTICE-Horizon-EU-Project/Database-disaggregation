"""Run one MRIO model experiment from prepared inputs or an accepted checkpoint.

Inputs must already contain the intended Intermediate steps plan. No cleaning,
source selection, baseline closure or modification of the source run occurs.
Use a fresh output directory for every experiment.
"""
import argparse
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version, PackageNotFoundError
import inspect
import json
from pathlib import Path
import shutil
import subprocess
import time
import traceback


def fingerprints(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob('*')) if p.is_file()}


def code_identity(module):
    source = Path(module.__file__).resolve()
    result = {'module': str(source)}
    try:
        repo = Path(subprocess.check_output(
            ['git', '-C', str(source.parent), 'rev-parse', '--show-toplevel'], text=True,stderr=subprocess.DEVNULL).strip())
        result.update(repository=str(repo), revision=subprocess.check_output(
            ['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip(),
            dirty=bool(subprocess.check_output(
                ['git', '-C', str(repo), 'status', '--porcelain'], text=True).strip()))
        result['python_sha256'] = {str(p.relative_to(repo)): hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in sorted(source.parent.rglob('*.py'))}
    except subprocess.CalledProcessError:
        result['revision'] = None
        result['python_sha256'] = {str(p.relative_to(source.parent)): hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in sorted(source.parent.rglob('*.py'))}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument('--prepared', type=Path)
    source_group.add_argument('--resume', type=Path, help='Accepted MARIO intermediate checkpoint.')
    parser.add_argument('--workbook', type=Path, help='Remaining workbook override; requires --resume.')
    parser.add_argument('--output', type=Path, help='Local work directory; generated under build/model_trials if omitted.')
    parser.add_argument('--no-publish',action='store_true',help='Keep an explicitly private/CI trial local; otherwise publish paired WSP inputs/results.')
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument('--policy', type=Path, help='Model/solver policy JSON; default: config/model-trials/entropy-first.json.')
    selection.add_argument('--options', type=Path, help='One fixed MARIO split_model_options JSON, bypassing the model policy.')
    selection.add_argument('--historical-model', action='store_true', help='Use the historical formulation without the entropy-first policy.')
    parser.add_argument('--solver-options', type=Path)
    parser.add_argument('--solver', help='Solver for a fixed --options / --historical-model run.')
    parser.add_argument('--stop-after-step', help='Defaults to Mining for a fresh preparation; resume runs all pending groups.')
    args = parser.parse_args()
    started_at=datetime.now(timezone.utc)
    policy_path = args.policy or (Path(__file__).resolve().parents[1]/'config/model-trials/entropy-first.json' if not args.options and not args.historical_model else None)
    policy = json.loads(policy_path.read_text()) if policy_path else None
    if policy is not None and (args.solver or args.solver_options):
        parser.error('A model policy contains its solver order/options; use --options for a fixed solver run.')
    if policy is None and args.solver is None:
        args.solver = 'MOSEK'
    options = json.loads(args.options.read_text()) if args.options else None
    solver_options = json.loads(args.solver_options.read_text()) if args.solver_options else None
    if args.workbook and not args.resume:
        parser.error('--workbook requires --resume.')
    source = (args.resume or args.prepared).resolve()
    stop_after_step = args.stop_after_step if args.resume else args.stop_after_step or 'Mining'
    output = (args.output or Path(__file__).resolve().parents[1]/'build/model_trials'/started_at.strftime('%Y%m%d-%H%M%S')).resolve()
    if output == source or source in output.parents:
        parser.error('The output must be separate from the immutable preparation.')
    if args.resume:
        if not (source/'state.json').is_file():
            parser.error('Expected state.json in --resume.')
        if args.options is None and policy is None and not args.historical_model:
            options = json.loads((source/'state.json').read_text()).get('split_model_options')
        from database_disaggregation.core.shared_runs import remaining_workbook
        workbook = (args.workbook or remaining_workbook(source)).resolve()
    else:
        workbook = source/'add_sectors.xlsx'
    if not args.resume and (not (source/'baseline'/'flows').is_dir() or not workbook.is_file()):
        parser.error('Expected baseline/flows and add_sectors.xlsx in --prepared.')
    output.mkdir(parents=True, exist_ok=False)
    baseline_hashes = fingerprints(source if args.resume else source/'baseline')
    workbook_hash = hashlib.sha256(workbook.read_bytes()).hexdigest()
    if not args.resume:
        shutil.copytree(source/'baseline', output/'baseline')
    shutil.copy2(workbook, output/'add_sectors.xlsx')
    import mario
    import cvxlab
    import database_disaggregation
    from database_disaggregation.core.parent_budgets import ParentBudgets, ChildTargets, require_parent_budgets
    manifest = {'status': 'running', 'started_at':started_at.isoformat(),
                'source_checkpoint' if args.resume else 'source_preparation': str(source),
                'runner_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'source_baseline_sha256': baseline_hashes, 'source_workbook_sha256': workbook_hash,
                'split_model_options': options, 'solver': args.solver, 'solver_options': solver_options,
                'source_workbook': str(workbook), 'stop_after_step': stop_after_step,
                'runtime': {p: version(p) for p in ('mariopy','cvxlab','cvxpy','numpy','pandas','clarabel')},
                'code': {name: code_identity(module) for name,module in
                         [('mario',mario),('cvxlab',cvxlab),('database_disaggregation',database_disaggregation)]}}
    for package in ('Mosek', 'gurobipy', 'scs', 'osqp', 'highspy'):
        try:
            manifest['runtime'][package] = version(package)
        except PackageNotFoundError:
            pass
    if policy is not None:
        manifest['solver_selection'] = 'policy'
        manifest['model_policy'] = policy
        manifest['model_policy_source'] = str(policy_path.resolve())
        manifest['model_policy_sha256'] = hashlib.sha256(policy_path.read_bytes()).hexdigest()
    path = output/'trial.json'
    path.write_text(json.dumps(manifest, indent=2))
    started = time.monotonic()
    exit_code = 1
    try:
        if policy is not None and 'allow_model_change' not in inspect.signature(mario.Database.add_sectors).parameters:
            raise RuntimeError('The entropy-first policy requires the matching MARIO model-policy checkout.')
        if options is not None and 'split_model_options' not in inspect.signature(mario.Database.add_sectors).parameters:
            raise RuntimeError('The selected MARIO checkout does not support split_model_options.')
        if args.resume:
            from mario.ops.add_sector_steps import load_checkpoint
            db = load_checkpoint(source)
        else:
            db = mario.parse_from_parquet(str(output/'baseline'/'flows'), table='IOT', mode='flows')
        db.read_add_sectors_excel(output/'add_sectors.xlsx', read_inventories=True, split=True)
        targets = ChildTargets.from_workbook(db.add_sectors_workbook)
        if args.resume:
            targets = targets.pending(db)
        require_parent_budgets(ParentBudgets.from_database(db), targets,
                               report_path=output/'parent_budgets.json')
        if not db.add_sectors_workbook.intermediate_steps:
            raise ValueError('A model trial requires an explicit Intermediate steps plan.')
        kwargs = dict(split=True, intermediate_steps=True, save_intermediates=output/'checkpoints',
                      stop_after_step=stop_after_step, solver=args.solver, solver_parameters=solver_options)
        if options is not None:
            kwargs['split_model_options'] = options
        if policy is None:
            db.add_sectors('inventories', **kwargs)
        else:
            from database_disaggregation.core.model_policy import run_model_policy
            db = run_model_policy(db, output/'add_sectors.xlsx', output, policy, stop_after_step=stop_after_step)
            manifest['split_model_options'] = db._intermediate_steps_state['split_model_options']
            manifest['model_history'] = db._intermediate_steps_state.get('model_history', [])
            accepted_attempts = [a for a in json.loads((output/'model_attempts.json').read_text()) if a['status'] == 'accepted']
            manifest['solver'] = accepted_attempts[-1]['solver']
            manifest['solver_options'] = accepted_attempts[-1]['solver_options']
        manifest.update(status='accepted', completed_sectors=db._intermediate_steps_state['completed_sectors'],
                        pending_recalculations=db._intermediate_steps_state.get('pending_recalculations',[]))
        exit_code = 0
    except Exception as exc:
        manifest.update(status='failed', error=str(exc), traceback=traceback.format_exc())
        traceback.print_exc()
    finally:
        manifest['elapsed_seconds'] = time.monotonic()-started
        if (output/'model_attempts.json').is_file():
            manifest['model_attempts'] = json.loads((output/'model_attempts.json').read_text())
        manifest['source_baseline_unchanged'] = fingerprints(source if args.resume else source/'baseline') == baseline_hashes
        manifest['source_workbook_unchanged'] = hashlib.sha256(workbook.read_bytes()).hexdigest() == workbook_hash
        manifest['working_baseline_unchanged'] = (True if args.resume else fingerprints(output/'baseline') == baseline_hashes)
        manifest['accepted_checkpoints'] = [str(p.parent) for p in sorted((output/'checkpoints').glob('*/state.json'))
                                            if not p.parent.name.startswith('.')]
        if not all(manifest[k] for k in ('source_baseline_unchanged','source_workbook_unchanged','working_baseline_unchanged')):
            manifest.update(status='failed', integrity_error='Input hashes changed during the trial.')
            exit_code = 1
        path.write_text(json.dumps(manifest, indent=2, allow_nan=False))
        if not args.no_publish:
            try:
                from database_disaggregation.core.shared_runs import publish_trial
                manifest['publication']=publish_trial(output)
                print('Shared results: '+(manifest['publication']['database'] or manifest['publication']['inventory']))
            except Exception as exc:
                manifest['publication_error']=str(exc)
                traceback.print_exc()
                exit_code=1
            path.write_text(json.dumps(manifest,indent=2,allow_nan=False))
        print(json.dumps({k: manifest.get(k) for k in ('status','elapsed_seconds','error','completed_sectors',
                                                     'pending_recalculations')}, indent=2))
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
