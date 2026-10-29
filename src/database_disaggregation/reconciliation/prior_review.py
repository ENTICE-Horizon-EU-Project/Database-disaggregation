"""Data-only, opt-in proposals for source profiles with invalid factor signs.

These recipes are declared donor assumptions. They do not alter the preparation
policy, any source workbook, targets or model, and they never call a solver.
"""
import math


def parent_factor_proposal(profile, parent_factors, *, mode='nonnegative_block', signed_factors=('Tax', 'TTM')):
    """Replace a factor block from a regional parent; rebalance the Z total.

    ``nonnegative_block`` inherits all non-Tax/non-TTM factors and retains the
    child's signed factors. ``all_factors`` inherits the complete parent V block.
    In both recipes, the intermediate-input composition/origin shares are held
    fixed while their common scale closes Z+V=1. The old net V is not preserved.
    This is a coefficient-prior transformation, not a database balancing step.
    """
    if mode not in ('nonnegative_block', 'all_factors'):
        raise ValueError('Unknown factor-donor proposal.')
    rows = [dict(row) for row in profile]
    sectors = [i for i, row in enumerate(rows) if row.get('Item type') == 'Sector']
    factors = [i for i, row in enumerate(rows) if row.get('Item type') == 'Factor of production']
    if not sectors or not factors:
        raise ValueError('The proposal requires both intermediate inputs and factor priors.')
    monetary = sectors + factors
    if any(rows[i].get('Unit') != 'M USD' for i in monetary):
        raise ValueError('Monetary coefficient priors must be expressed in M USD per unit output.')
    if any(not math.isfinite(float(rows[i]['Quantity'])) for i in monetary):
        raise ValueError('Nonfinite monetary prior.')
    if any(float(rows[i]['Quantity']) < 0 for i in sectors):
        raise ValueError('Negative intermediate-input priors require a separate source decision.')
    current = {rows[i]['DB Item']: float(rows[i]['Quantity']) for i in factors}
    if len(current) != len(factors):
        raise ValueError('Resolve duplicate factor rows before constructing a donor proposal.')
    parent = {key: float(value) for key, value in parent_factors.items()}
    if not parent or not all(math.isfinite(v) for v in parent.values()):
        raise ValueError('The parent factor block must be finite and complete.')
    if any(value < 0 for key, value in parent.items() if key not in signed_factors):
        raise ValueError('The parent has an inadmissible nonnegative-factor prior.')
    if set(current) - parent.keys():
        raise ValueError('The parent is missing a factor present in the child profile.')
    replacement = {key: value for key, value in parent.items()
                   if mode == 'all_factors' or key not in signed_factors}
    if mode == 'nonnegative_block' and set(signed_factors) - current.keys():
        raise ValueError('Resolve missing child Tax/TTM priors explicitly before retaining them.')
    updated = {**current, **replacement}
    if any(value < 0 for key, value in updated.items() if key not in signed_factors):
        raise ValueError('The proposal retains an inadmissible factor prior.')
    z_before = math.fsum(float(rows[i]['Quantity']) for i in sectors)
    v_before, v_after = math.fsum(current.values()), math.fsum(updated.values())
    z_target = 1. - v_after
    if z_target < 0 or z_before <= 0:
        raise ValueError('The donor proposal requires negative inputs or lacks an input pattern.')
    scale = z_target / z_before
    for i in sectors:
        rows[i]['Quantity'] = float(rows[i]['Quantity']) * scale
    for i in factors:
        rows[i]['Quantity'] = updated[rows[i]['DB Item']]
    for key in replacement.keys() - current.keys():
        rows.append({'Quantity': replacement[key], 'Unit': 'M USD', 'Input': key,
                     'Item type': 'Factor of production', 'DB Item': key,
                     'DB Region': None, 'Change type': 'Update'})
    total = math.fsum(float(row['Quantity']) for row in rows if row.get('Item type') in ('Sector', 'Factor of production'))
    if abs(total - 1.) > 1e-12:
        raise ArithmeticError('The candidate monetary prior does not close at unit output.')
    return rows, dict(mode=mode, status='proposal_only', net_v_before=v_before, net_v_after=v_after,
        z_before=z_before, z_after=z_target, common_intermediate_scale=scale,
        original_factors=current, candidate_factors=updated, replaced_factors=sorted(replacement),
        assumption='Regional parent factor coefficients are a proxy, not independent evidence for the child. Intermediate composition and origins are retained, but their absolute cost intensity is rescaled.',
        monetary_total=total, satellites_unchanged=True)
