"""Experimental trade projection with fixed outputs and signed row budgets.

This necessary-condition projection does not certify full MRIO feasibility.
Column accounting, cell-specific zeros and factor accounts are checked by the
subsequent MARIO solve. It is deliberately separate from default ingestion.
"""
import numpy as np


def fit_row_trade(positive, negative, row_targets, outputs, priors, weights, origin, *, observed=None, scale=None, solver=None):
    """Fit one parent/origin family, including its residual parent row.

    Arrays positive/negative have one entry per destination. The first row of
    row_targets/outputs is the residual parent; remaining rows are children.
    Priors and weights have child x destination shape. Domestic priors are
    ignored. Zero priors can increase: they are references, not structural zeros.
    The export bound includes the positive inherited row discrepancy. With no
    explicit scale, independent row problems use their own monetary magnitude,
    bounded by 1e-6 and 1000 to avoid magnifying sub-precision residues;
    this multiplies the entire loss by one positive constant
    and does not change its minimizer or its acceptance in original units.
    """
    import cvxpy as cp
    from scipy.optimize import linprog
    from scipy.sparse import lil_matrix

    positive, negative, row_targets, outputs, priors, weights = (
        np.asarray(a, dtype=float) for a in (positive, negative, row_targets, outputs, priors, weights))
    nr, ns = len(positive), len(row_targets)
    if (negative.shape != (nr,) or outputs.shape != (ns,) or priors.shape != (ns-1, nr)
            or weights.shape != priors.shape or not 0 <= origin < nr):
        raise ValueError('Inconsistent row/trade projection dimensions.')
    if not all(np.isfinite(a).all() for a in (positive,negative,row_targets,outputs,priors,weights)):
        raise ValueError('Nonfinite row/trade projection inputs.')
    if any((a < 0).any() for a in (positive,negative,outputs,priors)) or (weights <= 0).any():
        raise ValueError('Invalid budgets, outputs, priors or weights.')
    if abs(row_targets.sum()-(positive-negative).sum()) > 1e-6:
        raise ValueError('Family row totals do not conserve the preceding matrix.')
    if scale is None:
        largest = max(float(np.abs(a).max(initial=0.)) for a in (positive, negative, row_targets, outputs))
        scale = min(1000., max(1e-6, largest))
        scale_rule = 'min(1000, max(1e-6, largest row budget/target/output))'
    else:
        scale_rule = 'explicit numerical scale'
    if not np.isfinite(scale) or scale <= 0:
        raise ValueError('Numerical scale must be positive and finite.')
    # MARIO accounting='inherit' fixes the preceding row discrepancy. A child
    # can therefore deliver output + that inherited discrepancy, not output
    # alone. Keep negative discrepancies from increasing the export budget.
    export_caps = np.maximum(outputs[1:], row_targets[1:])
    inherited_allowance = np.maximum(row_targets[1:]-outputs[1:], 0.)
    foreign = np.flatnonzero(np.arange(nr) != origin)
    capacity_original = np.maximum(positive[foreign]-negative[foreign],0.)
    movable = (export_caps[:,None]>0) & (capacity_original[None,:]>0)
    candidate_priors = priors.copy()
    supported_foreign = candidate_priors[:,foreign].copy()
    supported_foreign[~movable] = 0.
    candidate_priors[:,foreign] = supported_foreign
    structural_changes = int(np.count_nonzero(candidate_priors-priors))

    observed = np.ones_like(priors,dtype=bool) if observed is None else np.asarray(observed,dtype=bool)
    if observed.shape != priors.shape:
        raise ValueError('Inconsistent observed-trade mask.')
    # With one child, no remaining parent output and no negative deliveries,
    # every preceding foreign delivery belongs to that child. The projection
    # has no trade degrees of freedom: keep the exact supplied budgets rather
    # than turn a solver's sub-dollar residual into a new hard MRIO target.
    if (ns == 2 and outputs[0] == 0 and outputs[1] > 0 and not negative.any()
            and positive.any() and observed[:,foreign].all()):
        total = float(np.sum(positive))
        foreign_total = float(np.sum(positive[foreign]))
        violation = max(abs(float(row_targets[0])), abs(float(row_targets[1])-total),
                        foreign_total-float(export_caps[0]), 0.)
        if violation <= 1e-6:
            result = priors.copy()
            result[0,foreign] = positive[foreign]
            change = result[:,foreign]-priors[:,foreign]
            return result, dict(status='optimal', solver='analytical_unique_row', attempts=[],
                solver_seconds=0., max_constraint_violation_MUSD=violation,
                export_cap_policy='output + positive inherited row discrepancy',
                positive_inherited_row_allowance_MUSD=inherited_allowance.tolist(),
                numerical_scale_MUSD=float(scale),numerical_scale_rule=scale_rule,
                structural_zero_trade_cells=structural_changes,
                changed_routes=int((np.abs(change)>1e-6).sum()),
                absolute_trade_change_MUSD=float(np.abs(change).sum()),
                reason='One fully allocated child, zero residual output and no negative row budget: unique foreign deliveries.')
    # Retain a family/origin's original targets if its signed row LP is feasible.
    count = ns*nr
    eq = lil_matrix((2*nr+ns+int(observed[:,foreign].sum()), 2*count))
    rhs = []
    k = 0
    for sign,budget in enumerate((positive,negative)):
        for j in range(nr):
            eq[k, sign*count + np.arange(ns)*nr+j] = 1
            rhs.append(budget[j]/scale); k += 1
    for i in range(ns):
        eq[k, i*nr:(i+1)*nr] = 1
        eq[k, count+i*nr:count+(i+1)*nr] = -1
        rhs.append(row_targets[i]/scale); k += 1
    for i in range(1,ns):
        for j in foreign:
            if not observed[i-1,j]:
                continue
            eq[k, i*nr+j], eq[k, count+i*nr+j] = 1,-1
            rhs.append(candidate_priors[i-1,j]/scale); k += 1
    if solver not in (None, 'GUROBI'):
        raise ValueError('Explicit row-trade solver must be GUROBI; None retains the legacy open solver policy.')
    gurobi_options = dict(Threads=2, TimeLimit=120., FeasibilityTol=1e-9,
                          OptimalityTol=1e-9, BarConvTol=1e-12, NumericFocus=3, reoptimize=True)
    if solver == 'GUROBI':
        point = cp.Variable(2*count, nonneg=True)
        probe_problem = cp.Problem(cp.Minimize(0.), [eq.tocsr() @ point == np.asarray(rhs)])
        probe_problem.solve(solver='GUROBI', **gurobi_options)
        probe_success = probe_problem.status == 'optimal'
        if not probe_success and probe_problem.status != 'infeasible':
            raise RuntimeError(f'Row feasibility probe failed: {probe_problem.status}')
    else:
        probe = linprog(np.zeros(2*count), A_eq=eq.tocsr(), b_eq=rhs, bounds=(0,None),
                        method='highs', options={'primal_feasibility_tolerance':1e-9})
        probe_success = probe.success
        if not probe.success and probe.status != 2:
            raise RuntimeError(f'Row feasibility probe failed: {probe.message}')
    prior_capacities_pass = ((candidate_priors[:,foreign].sum(axis=0)<=capacity_original+1e-6).all()
                            and (candidate_priors[:,foreign].sum(axis=1)<=export_caps+1e-6).all())
    if probe_success and prior_capacities_pass:
        return candidate_priors, {'status':'already_row_feasible', 'changed_routes':structural_changes,
                               'structural_zero_trade_cells':structural_changes,
                               'positive_inherited_row_allowance_MUSD':inherited_allowance.tolist(),
                               'numerical_scale_MUSD':float(scale),'numerical_scale_rule':scale_rule}
    # Destination fractions keep sub-cent negative budgets and large positive
    # deliveries on comparable variable scales without dropping either budget.
    p, n = cp.Variable((ns,nr), nonneg=True), cp.Variable((ns,nr), nonneg=True)
    net = cp.multiply(positive[None,:]/scale,p)-cp.multiply(negative[None,:]/scale,n)
    t = net[1:,foreign]
    capacity = np.maximum(positive[foreign]-negative[foreign],0.)/scale
    prior = priors[:,foreign]/scale
    denominator = np.maximum(np.maximum(prior, .01*capacity[None,:]), 1e-6/scale)
    coefficients = weights[:,foreign]/denominator
    coefficients[~movable] = 0.
    # Keep the natural chi-square objective scale: normalizing by the largest
    # coefficient would let near-zero routes flatten the loss on major trades.
    constraints = [cp.sum(p,axis=0)==(positive>0).astype(float), cp.sum(n,axis=0)==(negative>0).astype(float),
                   # The residual row equality is implied by destination budgets
                   # and child rows; audit it independently in monetary units.
                   cp.sum(net[1:,:],axis=1)==row_targets[1:]/scale, t>=0,
                   cp.sum(t,axis=0)<=capacity, cp.sum(t,axis=1)<=export_caps/scale]
    problem = cp.Problem(cp.Minimize(cp.sum(cp.multiply(coefficients,cp.square(t-prior)))),constraints)
    attempts = []
    solver_policy = [('GUROBI', gurobi_options)] if solver == 'GUROBI' else [
            ('CLARABEL',dict(tol_gap_abs=1e-11,tol_gap_rel=1e-11,tol_feas=1e-12,max_iter=600,
                             static_regularization_constant=1e-11,iterative_refinement_max_iter=20)),
            ('OSQP',dict(eps_abs=1e-12,eps_rel=1e-12,max_iter=200000,polishing=True,time_limit=20.))]
    for solver,options in solver_policy:
        try:
            problem.solve(solver=solver,**options)
        except cp.error.SolverError as exc:
            attempts.append(dict(solver=solver,error=str(exc)))
            continue
        attempt = dict(solver=solver,status=problem.status,solver_options=dict(options))
        attempts.append(attempt)
        if problem.status not in ('optimal','optimal_inaccurate') or t.value is None:
            continue
        monetary_p, monetary_n = np.asarray(p.value)*positive[None,:], np.asarray(n.value)*negative[None,:]
        monetary_net = monetary_p-monetary_n
        monetary_t = monetary_net[1:,foreign]
        residual = float(max(np.abs(monetary_p.sum(axis=0)-positive).max(initial=0.),
                             np.abs(monetary_n.sum(axis=0)-negative).max(initial=0.),
                             np.abs(monetary_net.sum(axis=1)-row_targets).max(initial=0.),
                             -monetary_p.min(initial=0.),-monetary_n.min(initial=0.),-monetary_t.min(initial=0.),
                             (monetary_t.sum(axis=0)-capacity_original).max(initial=0.),
                             (monetary_t.sum(axis=1)-export_caps).max(initial=0.)))
        attempt['max_constraint_violation_MUSD'] = residual
        if np.isfinite(residual) and residual <= 1e-6:
            break
    else:
        raise RuntimeError(f'Row trade reconciliation failed numerical acceptance: {attempts}')
    result = priors.copy()
    fitted_foreign = np.maximum(np.asarray(t.value)*scale,0.)
    before_support_cleanup = fitted_foreign.copy()
    fitted_foreign[~movable] = 0.
    result[:,foreign] = fitted_foreign
    support_cleanup = float(np.abs(before_support_cleanup-fitted_foreign).sum(axis=1).max(initial=0.))
    changes = result[:,foreign]-priors[:,foreign]
    return result, dict(status=problem.status, solver=solver,attempts=attempts,solver_seconds=problem.solver_stats.solve_time,
                        max_constraint_violation_MUSD=residual,
                        export_cap_policy='output + positive inherited row discrepancy',
                        structural_zero_trade_cells=structural_changes,
                        max_postsolve_support_cleanup_sum_MUSD=support_cleanup,
                        numerical_scale_MUSD=float(scale),numerical_scale_rule=scale_rule,
                        positive_inherited_row_allowance_MUSD=inherited_allowance.tolist(),
                        changed_routes=int((np.abs(changes)>1e-6).sum()),
                        absolute_trade_change_MUSD=float(np.abs(changes).sum()),
                        largest_increase_MUSD=float(changes.max(initial=0.)),
                        largest_decrease_MUSD=float(-changes.min(initial=0.)))
