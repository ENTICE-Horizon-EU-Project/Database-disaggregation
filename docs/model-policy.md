# Entropy-first model and solver policy

`run_model_trial.py` now defaults to `config/model-trials/entropy-first.json`.
This is an orchestration policy: the formulations remain inspectable in MARIO's
individual `mario/ops/cvxlab_models/` folders. No objective formula is generated
or rewritten during a run.

| Stage | Preferred template | Alternative after entropy attempts fail |
| --- | --- | --- |
| First insertion group | `Split_sectors_MRIO_KL` | `Split_sectors_MRIO_quadratic` |
| Subsequent insertion groups | `Split_sectors_MRIO_partial_entropy_V_signed_kl` | `Split_sectors_MRIO_quadratic` |

Each insertion group can contain several sectors. “Subsequent” means that the
checkpoint already contains completed children. Later groups return to the
preferred entropy model even if an earlier group needed quadratic. Model history
records this choice; objectives from different formulations are not comparable
as model-quality scores.

## Solvers and acceptance

- Entropy: MOSEK, then Clarabel, then SCS.
- Quadratic: Gurobi, then MOSEK, then Clarabel, then OSQP.
- Affine feasibility: Gurobi, then HiGHS, then Clarabel on technical failure.
  An infeasible preflight is recorded and rejects that model/solver attempt.

This is the project's current preferred order, not a claim that one solver is
universally fastest. MOSEK and Gurobi require installed Python packages and valid
licences. MOSEK 11.2.6 was restored and licence-tested in the current Python
environment; Gurobi 13.0.2 was already available. Both versions are recorded in
new trial manifests. Install them in your active environment with
`python -m pip install Mosek==11.2.6 gurobipy==13.0.2`, then configure your own
licences. The policy keeps open solvers available for missing/expired licences,
solver failures and rejected numerical solutions. MOSEK uses the dual solve form
of CVXPY's canonical problem. Solver-specific controls live in the policy JSON.

All solvers for the preferred entropy formulation are tried before changing to
quadratic. Each retry uses a fresh copy of the preceding accepted database;
failed candidates cannot become the starting point of a later attempt. No target,
constraint, tolerance or matrix is patched to make an attempt pass. Independent
constraint, accounting and conservation checks still determine acceptance. This
policy also requires a finite evaluated objective (`require_finite_objective=true`):
a numerically negative entropy operand can make the objective infinite even when
affine residuals pass. Such a point is rejected and another solver is tried; it
is never clipped into the entropy domain.
Invalid input schemas, changed completed inputs and programming errors stop the
run instead of being treated as numerical failure.

`model_attempts.json` records ordered attempts, model, solver, settings, status,
errors, duration and working directories. The accepted checkpoint records its
actual model definition, solver and cumulative `model_history`. Shared results
also retain the attempt diagnostics, including `entropy_support.json`.

The runner's default changed from the historical model to this policy. To use a
fixed model/solver, pass `--options`, `--solver` and `--solver-options` as before;
to select the historical model explicitly, use `--historical-model`. These modes
bypass the automatic model/solver policy. `run_disaggregation.py` still prepares
inputs by default; the controlled model runner is the documented execution path.

## Data-derived entropy support

For each insertion step, collect the monetary priors in **enabled entropy
terms**, after preparing the inputs and before numerical scaling. Their smallest
nonzero absolute value is `m`. The additive support is

```text
magnitude = 10 ** floor(log10(m))
entropy_support = magnitude * 1e-4
```

For `m = 0.03`, support is `1e-6`, not `0.03 * 1e-4`. Signed priors contribute
their absolute magnitude. Zeros have no decimal order and are excluded. Masks,
weights, tolerances, accounting residuals, output/trade targets and disabled
losses do not set the coefficient. For partial entropy, conditional refinement
priors count only when that refinement term is active; otherwise supply priors
carry the refinement without a second penalty.

The common support is added to the references in KL/relative-entropy terms,
including both nonnegative components of signed TTM/Tax. It supplies numerical
support; it is not an empirical observation, objective weight or hard lower bound
on the final flows. Structural-zero constraints and factor/sign domains remain
in force. Negative Capital/Labor priors are still rejected by entropy models.

`entropy_support.json` records the selected prior tables, minimum, decimal
exponent, coefficient in original units and coefficient divided by `scale`.
An all-zero set of references cannot define a data-derived magnitude and raises
an explicit error; nonfinite values and numerical underflow are also rejected.
The quadratic objective retains its separate normalisation floor, so this change
does not alter the historical quadratic weighting rule.

## Checkpoints and reproducibility

The numerical-support rule changes the entropy objective. Existing published
matrices are untouched. Historical checkpoints remain readable but cannot be
silently resumed with the new model revision; start a fresh experiment or use
the exact recorded old code/configuration.

Within a new policy run, MARIO's explicit `allow_model_change=True` permits a
named-objective transition for pending groups. It does not permit changes in
accounting, weights, scaling, feasibility policy, satellite policy or completed
inventories. Previous model hashes are verified before a transition. Direct
`Database.add_sectors` calls retain the default `allow_model_change=False`.


## Verification of this change

The model/step/template checks passed in the matching MARIO worktree, including
scale covariance, signed priors, structural zeros and checkpoint protection.
A semantic comparison of all 36 MRIO workbooks confirmed that constraints were
unchanged and objective expressions changed only to use the entropy-support
control. Policy and publication unit tests also passed.

A small two-region/two-group pipeline run accepted the initial KL and subsequent
partial-entropy stages with MOSEK and finite objectives. A second run simulated
MOSEK being unavailable: Clarabel/SCS entropy results were rejected by the finite
objective criterion, after which Gurobi quadratic results were accepted. Both
runs preserved input hashes, passed conservation/accounting checks and published
their complete attempt diagnostics into isolated temporary folders. No existing
shared database was modified, and this verification did not rerun the 49-region
pilot under the new objective.

MOSEK's entropy/exponential-cone support is described in the
[MOSEK modelling cookbook](https://docs.mosek.com/modeling-cookbook/expo.html).
The current CVXPY solver compatibility is documented in its
[solver feature table](https://www.cvxpy.org/tutorial/solvers/index.html).

### Explicit factor-prior reconciliation for controlled trials

Entropy requires admissible Capital/Labor priors, in addition to constraints on
optimized values. The ordinary preparation currently preserves existing negative
factor observations, so it can expose a genuine source conflict here. Do not take
absolute values or use the earlier optimized quadratic result as a new prior.

For an explicitly authorized experiment, create a separate preparation:

```sh
PYTHONPATH=src python scripts/reconcile_factor_priors.py \
  --prepared path/to/original/prepared \
  --output path/to/new/prepared --sectors MCU
```

Only selected-sector profiles with negative nonnegative-domain factors are
changed. The rule minimizes `sum((v-q)^2/abs(q))`, preserves total net V and imposes
nonnegativity on all factors except Tax/TTM. For a zero prior the variance is the
smallest nonzero absolute factor prior. Intermediate inputs, output, trade,
exclusions, tolerances, stage plan and baseline remain unchanged. Unchanged XLSX
members are verified byte for byte; `reconciliation.json` records the changed
cells, original/reconciled values, source hashes and interpretation. The baseline
is copied and verified, and the source is immutable.

This is a prior assumption, not empirical evidence for the true VA composition.
If negative Capital/Labor almost cancel positive Tax/TTM in the source, preserving
net V can yield zero Capital/Labor and near-zero signed factors. Report that
explicitly. The regular preparation policy is not changed by this opt-in tool.
Run **both** KL/MOSEK and quadratic/Gurobi on this same transformed workbook;
compare them primarily with each other and use the old quadratic run separately
to assess the effect of the input transformation. The fixed quadratic/Gurobi
configuration also requires a finite objective, as does the fixed KL trial.
