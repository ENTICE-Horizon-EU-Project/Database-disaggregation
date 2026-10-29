"""Audited model/solver attempts; each attempt starts from the preceding checkpoint.

The formulations stay in MARIO's named CVXLab folders. This module only chooses
which existing formulation and solver to try, and never edits an IO matrix.
"""
from copy import deepcopy
import json
from pathlib import Path
import time
import traceback


INITIAL = 'Split_sectors_MRIO_KL'
SUBSEQUENT = 'Split_sectors_MRIO_partial_entropy_V_signed_kl'
QUADRATIC = 'Split_sectors_MRIO_quadratic'


def validate_policy(policy):
    if policy.get('format') != 'entice-model-policy-v1':
        raise ValueError('Unsupported model policy format.')
    if (policy.get('initial_model'), policy.get('subsequent_model'), policy.get('fallback_model')) != (INITIAL, SUBSEQUENT, QUADRATIC):
        raise ValueError('The entropy-first policy requires the named initial KL, subsequent partial entropy and quadratic fallback models.')
    common = policy['split_model_options']
    if {'model', 'flow_loss', 'value_added_loss', 'complete_intermediate_priors'} & common.keys():
        raise ValueError('Objective choices belong in the named policy models, not in shared options.')
    for kind in ('entropy', 'quadratic'):
        sequence = policy['solvers'][kind]
        if not sequence or len({s['name'] for s in sequence}) != len(sequence):
            raise ValueError('Each solver sequence must be nonempty and contain distinct names.')
        if any(not isinstance(s['name'], str) or not s['name'] or not isinstance(s.get('options', {}), dict) for s in sequence):
            raise ValueError('A solver entry requires a name and an options dictionary.')
    return deepcopy(policy)


def attempt_order(policy, *, subsequent):
    preferred = policy['subsequent_model'] if subsequent else policy['initial_model']
    for model in (preferred, policy['fallback_model']):
        kind = 'quadratic' if model == QUADRATIC else 'entropy'
        for solver in policy['solvers'][kind]:
            yield dict(model=model, solver=solver['name'], solver_options=deepcopy(solver.get('options', {})))


def optimization_failure(exc):
    from mario.log_exc.exceptions import WrongInput
    from mario.ops.split_model import solver_failure
    if solver_failure(exc):
        return True
    # Input/schema/programming errors are not grounds for silently changing
    # solver or objective. These messages denote an explicit numerical/domain
    # rejection from the optimisation and independent acceptance stages.
    return isinstance(exc, WrongInput) and any(text in str(exc) for text in (
        'optimization did not solve optimally', 'feasibility check returned',
        'split constraint cells', 'Nonfinite model solution constraint residual', 'Nonfinite model solution objective',
        'Negative Capital/Labor', 'Step does not preserve preceding',
        'Step introduced row-accounting discrepancies', 'New-sector columns are not balanced',
        'Step introduced negative', 'Step changed the sign domain',
    ))


def try_stage(policy, *, subsequent, installed, solve, record, retryable=optimization_failure):
    """Try all solvers for entropy before allowing a different objective."""
    errors = []
    for spec in attempt_order(policy, subsequent=subsequent):
        item = dict(spec, status='running')
        if spec['solver'] not in installed:
            item['status'] = 'not_installed'
            record(item)
            continue
        started = time.monotonic()
        record(item)
        try:
            result = solve(spec)
        except Exception as exc:
            item.update(status='failed', error=str(exc), error_type=type(exc).__name__,
                        traceback=traceback.format_exc(), seconds=time.monotonic()-started)
            record(item)
            if not retryable(exc):
                raise
            errors.append(f"{spec['model']} / {spec['solver']}: {exc}")
        else:
            item.update(status='accepted', seconds=time.monotonic()-started)
            record(item)
            return result
    raise RuntimeError('No model/solver attempt was accepted. ' + '; '.join(errors))


def run_model_policy(db, workbook, output, policy, *, stop_after_step=None):
    import cvxpy as cp
    from mario.ops.add_sector_steps import validate_plan
    from mario.ops.split_model import normalize_options

    policy = validate_policy(policy)
    for name in ('initial_model', 'subsequent_model', 'fallback_model'):
        normalize_options(dict(policy['split_model_options'], model=policy[name]))
    state = getattr(db, '_intermediate_steps_state', {})
    plan, _ = validate_plan(db.add_sectors_workbook, db.get_index('Sector'), completed=state.get('completed_sectors', []))
    if stop_after_step is not None and stop_after_step not in dict(plan):
        raise ValueError('stop_after_step must name a pending group.')
    output, workbook = Path(output), Path(workbook)
    journal, attempts = output/'model_attempts.json', []
    for step, _ in plan:
        state = getattr(db, '_intermediate_steps_state', {})
        step_index = state.get('step_index', 0) + 1
        active = None

        def record(item):
            nonlocal active
            if item['status'] in ('running', 'not_installed'):
                active = dict(item, step=step, step_index=step_index, attempt=len(attempts)+1)
                attempts.append(active)
            else:
                active.update(item)
            journal.write_text(json.dumps(attempts, indent=2, allow_nan=False))

        def solve(spec):
            candidate = db.copy()
            work = output/'attempts'/f"{active['attempt']:03d}_{spec['solver']}"
            work.mkdir(parents=True, exist_ok=False)
            active['work_directory'] = str(work)
            journal.write_text(json.dumps(attempts, indent=2, allow_nan=False))
            print(f"Step {step!r}: {spec['model']} with {spec['solver']}", flush=True)
            candidate.add_sectors(
                workbook, split=True, intermediate_steps=True,
                save_intermediates=output/'checkpoints', stop_after_step=step,
                cvxlab_path=work, solver=spec['solver'], solver_parameters=spec['solver_options'],
                split_model_options=dict(policy['split_model_options'], model=spec['model']),
                allow_model_change=bool(state.get('completed_sectors')),
            )
            return candidate

        db = try_stage(policy, subsequent=bool(state.get('completed_sectors')),
                       installed=set(cp.installed_solvers()), solve=solve, record=record)
        if step == stop_after_step:
            break
    return db
