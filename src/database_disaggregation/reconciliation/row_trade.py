"""Experimental trade projection with fixed outputs and signed row budgets.

This necessary-condition projection does not certify full MRIO feasibility.
Column accounting, cell-specific zeros and factor accounts are checked by the
subsequent MARIO solve. It is deliberately separate from default ingestion.
"""
import numpy as np


def fit_row_trade(positive, negative, row_targets, outputs, priors, weights, origin, *, observed=None, scale=1000.):
    """Fit one parent/origin family, including its residual parent row.

    Arrays positive/negative have one entry per destination. The first row of
    row_targets/outputs is the residual parent; remaining rows are children.
    Priors and weights have child x destination shape. Domestic priors are
    ignored. Zero priors can increase: they are references, not structural zeros.
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
    foreign = np.flatnonzero(np.arange(nr) != origin)
    observed = np.ones_like(priors,dtype=bool) if observed is None else np.asarray(observed,dtype=bool)
    if observed.shape != priors.shape:
        raise ValueError('Inconsistent observed-trade mask.')
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
            rhs.append(priors[i-1,j]/scale); k += 1
    probe = linprog(np.zeros(2*count), A_eq=eq.tocsr(), b_eq=rhs, bounds=(0,None),
                    method='highs', options={'primal_feasibility_tolerance':1e-9})
    capacity_original = np.maximum(positive[foreign]-negative[foreign],0.)
    prior_capacities_pass = ((priors[:,foreign].sum(axis=0)<=capacity_original+1e-6).all()
                            and (priors[:,foreign].sum(axis=1)<=outputs[1:]+1e-6).all())
    if probe.success and prior_capacities_pass:
        return priors.copy(), {'status':'already_row_feasible', 'changed_routes':0}
    if not probe.success and probe.status != 2:
        raise RuntimeError(f'Row feasibility probe failed: {probe.message}')

    # Destination fractions keep sub-cent negative budgets and large positive
    # deliveries on comparable variable scales without dropping either budget.
    p, n = cp.Variable((ns,nr), nonneg=True), cp.Variable((ns,nr), nonneg=True)
    net = cp.multiply(positive[None,:]/scale,p)-cp.multiply(negative[None,:]/scale,n)
    t = net[1:,foreign]
    capacity = np.maximum(positive[foreign]-negative[foreign],0.)/scale
    prior = priors[:,foreign]/scale
    denominator = np.maximum(np.maximum(prior, .01*capacity[None,:]), 1e-6/scale)
    coefficients = weights[:,foreign]/denominator
    movable = (outputs[1:,None]>0) & (capacity[None,:]>0)
    coefficients[~movable] = 0.
    # Keep the natural chi-square objective scale: normalizing by the largest
    # coefficient would let near-zero routes flatten the loss on major trades.
    constraints = [cp.sum(p,axis=0)==(positive>0).astype(float), cp.sum(n,axis=0)==(negative>0).astype(float),
                   # The residual row equality is implied by destination budgets
                   # and child rows; audit it independently in monetary units.
                   cp.sum(net[1:,:],axis=1)==row_targets[1:]/scale, t>=0,
                   cp.sum(t,axis=0)<=capacity, cp.sum(t,axis=1)<=outputs[1:]/scale]
    problem = cp.Problem(cp.Minimize(cp.sum(cp.multiply(coefficients,cp.square(t-prior)))),constraints)
    attempts = []
    for solver,options in [
            ('CLARABEL',dict(tol_gap_abs=1e-11,tol_gap_rel=1e-11,tol_feas=1e-12,max_iter=600,
                             static_regularization_constant=1e-11,iterative_refinement_max_iter=20)),
            ('OSQP',dict(eps_abs=1e-12,eps_rel=1e-12,max_iter=200000,polishing=True,time_limit=20.))]:
        try:
            problem.solve(solver=solver,**options)
        except cp.error.SolverError as exc:
            attempts.append(dict(solver=solver,error=str(exc)))
            continue
        attempt = dict(solver=solver,status=problem.status)
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
                             (monetary_t.sum(axis=1)-outputs[1:]).max(initial=0.)))
        attempt['max_constraint_violation_MUSD'] = residual
        if np.isfinite(residual) and residual <= 1e-6:
            break
    else:
        raise RuntimeError(f'Row trade reconciliation failed numerical acceptance: {attempts}')
    result = priors.copy()
    result[:,foreign] = np.maximum(np.asarray(t.value)*scale,0.)
    changes = result[:,foreign]-priors[:,foreign]
    return result, dict(status=problem.status, solver=solver,attempts=attempts,solver_seconds=problem.solver_stats.solve_time,
                        max_constraint_violation_MUSD=residual,
                        changed_routes=int((np.abs(changes)>1e-6).sum()),
                        absolute_trade_change_MUSD=float(np.abs(changes).sum()),
                        largest_increase_MUSD=float(changes.max(initial=0.)),
                        largest_decrease_MUSD=float(-changes.min(initial=0.)))
