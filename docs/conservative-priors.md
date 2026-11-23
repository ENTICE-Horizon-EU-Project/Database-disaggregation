# Conservative intermediate priors and reproducible sequential builds

MARIO prepares the objective references; this repository reconciles collected
trade targets and orchestrates accepted intermediate steps. CVXLab is unchanged.
The correction changes references, not the accounting constraints or objective
family. A quadratic run remains quadratic; an entropy run remains entropy.

## What changed in MARIO

An original supplier-to-buyer parent cell becomes a block when its sectors are
split. The old references could count the same original budget more than once,
particularly in the residual parent's buying column. That encouraged a new
supplier's output to remain concentrated in its parent.

The conservative policy builds one complete reference for each affected
parent-to-parent block, separately for every origin/destination pair:

1. Retain the prepared recipes for new buying sectors where compatible with
   the original block budget and structural support.
2. Allocate the remaining budget in the residual buying column among supplier
   children and their residual parent using output shares in the origin region.
3. If child recipes alone exceed the available budget, rescale those references
   and record the adjustment. Unsupported blocks are reported explicitly.
4. Project that same complete reference into both `Z_use0` and `Z0`. Do not
   normalize a partial legacy `Z0` independently.

For example, suppose the original self-consumption is 45 and a child accounts
for 10% of its supplying family output. A child buying recipe requires 4.5 from
the residual supplier and zero from itself. The remaining 40.5 is split 90/10:

| Supplier / buyer | Residual parent | Child |
| --- | ---: | ---: |
| Residual parent | 36.45 | 4.50 |
| Child | 4.05 | 0.00 |

The four references add to 45. The previous toy reference added to 85.5. This is
a neutral fallback for missing information, not an observation that the child
must sell to any particular industry. Explicit compatible child recipes take
precedence over this fallback.

`split_model_options['intermediate_prior_policy']` selects `conservative`
(default) or `legacy` for controlled comparisons. Application precedes prior
thresholding and entropy floors. Baseline matrices, output/trade targets,
signed Y/V references and structural-zero masks are preserved. The audit files
`intermediate_prior_preparation.json` and `.csv` record conservation, unsupported
groups and recipe rescaling. These audits are copied to shared results.

The model revision and preparation-code fingerprints changed. An old checkpoint
remains readable; it cannot silently continue with the new reference policy.
Rebuild from the unsplit baseline to obtain a consistent full database.

## Controlled LFP pilot, 13 regions

The legacy and conservative trials used identical input constraints and the
same quadratic/Gurobi model. Only the generated `Z_use0.csv` differed. Sparse
trade support was retained in this A/B comparison: the common reconciliation
check required no numerical trade adjustments, and missing routes were not
turned into new zero constraints for the comparison.

| Measure | Legacy prior | Conservative prior |
| --- | ---: | ---: |
| Solver status | optimal | optimal |
| Global LFP output, M USD | 70,111.05 | 70,111.05 |
| Share used by EEQ | 76.09% | 22.24% |
| Share used by MVH | 1.12% | 3.12% |
| Share going to final demand | 13.15% | 37.77% |
| Maximum affine constraint residual, USD | 0.0041 | 0.0036 |

No compatible child recipe required rescaling and there were no unsupported
budgets. This validates the prior correction and demonstrates its material
effect on EEQ concentration. It does **not** establish that MVH or final demand
now has the economically correct share. Assess that using inventories and
independent demand evidence, separately from constraint checks.

## Integrated sequential pipeline

Use a compatible MARIO `codex/mrio-memory` checkout and the CVXLab version
recorded with the run. Supply an unsplit preparation, the preparation's
trade-source audit and its reconciliation policy:

```bash
python scripts/run_sequential_model.py \
  --prepared /path/to/prepared \
  --output /path/to/new-build \
  --trade-audit /path/to/audit/trades.csv \
  --policy /path/to/policy.json \
  --options config/model-trials/conservative-quadratic.json \
  --solver-options config/model-trials/solver-gurobi-standard.json
```

The runner follows the workbook's explicit Intermediate steps plan. It does not
change the insertion order, group sizes, objective or solver. For a bounded
pilot, `--sectors LFP` selects an entire existing plan group; split a larger
group in a separate preparation copy before using this option.

Before each group, the runner jointly reconciles **all pending siblings** of
the affected parents against the last accepted database. Thus it reserves
budgets for children that will be attempted later, including previously failed
children. The baseline and prepared profiles remain intact. Trade targets are
rewritten. Pending outputs are only normalized for the audited sub-precision
empty-parent and single-child excess cases described below; other outputs stay
fixed. Each stage retains its exact full workbook,
reconciliation audit, compiled MARIO workbook, model diagnostics and database.

The reconciliation uses the existing signed-row trade projection and source
reliability weights with Gurobi. Fitted routes, including zeros, become explicit
scenario constraints. A previously absent route is a weak zero reference in
the fit, not an independently observed zero. This target-support choice is
reported in every audit. Row feasibility alone does not certify full MRIO
feasibility.

There is one attempt per scheduled group. Recoverable model failures retain
the preceding database and continue; no objective or solver fallback is used.
Unexpected data/programming errors stop the build. `sequential-run.json` lists
accepted/failed children and the authoritative final checkpoint. E is deferred
and must be recalculated later, as recorded in the checkpoint.

Only generated solver CSV/SQLite working caches from this new build are moved
to lossless ZIP archives, after byte verification. Matrices, checkpoint state,
workbooks and diagnostics remain in place. To inspect a CSV later, extract its
relative path from the stage's `solver_cache_archive.json` archive. Existing
historical builds are never pruned by this runner.

To reproduce a result, retain the initial preparation, policy/audit, exact
options and runtime/code identities, then use this single sequential entry
point. Do not manually patch the final database. Publish the last accepted
trial with the saved-result publication command:

```bash
python scripts/publish_sequential_run.py --run /path/to/new-build
```

It copies the final database, cumulative inventories and a reproducibility
package to the configured shared folders, without solving again. The cumulative
inventory exporter follows the checkpoint chain and verifies each compiled input
against its stage source.


## One deferred solver retry

A user-authorised singleton retry can wait for the ongoing build and its saved-result
checks/publication to finish, then start from its final accepted checkpoint:

```bash
python scripts/retry_sector_after_run.py \
  --run /path/to/new-build \
  --sector MGC \
  --solver-options config/model-trials/solver-gurobi-numeric-30min.json
```

This is one attempt, with TimeLimit 1800 seconds and NumericFocus 3; other solver
parameters and all model options/tolerances remain unchanged. The current build
is untouched. Pending siblings are jointly re-reconciled on copies against the
final checkpoint, then MARIO adds only the selected sector. Outcome, exact inputs
and audits are saved separately and published to paired shared folders.

The MGC source log on 22 November 2026 stopped after 28.95 seconds with native
SUBOPTIMAL, which CVXPY maps to user_limit; the 600-second cap was not exhausted.
Increasing time alone therefore does not address the observed numerical stall.
NumericFocus increases numerical care without weakening tolerances. The retry
occurs after other sectors have been inserted, so its different checkpoint and
reconciled targets prevent attributing a changed outcome solely to parameters.


The sequential build and the explicitly queued MGC retry are experimental.
They are not yet the final handoff procedure. The
[release requirements](reproducibility-requirements.md) require one documented
entry point, frozen common settings or a general bounded retry policy, and a
clean full replay without manually selected sector-specific adjustments.


For a controlled local checkpoint, resume from the checksum-verified
`source_workbook` recorded in its trial manifest. The readable
`source_add_sectors.xlsx` re-export can contain last-digit floating-point
serialization changes and is not a substitute for the executed file. Before a
retry, all completed-sector fingerprints are verified exactly. An orchestration
failure before checkpoint/model work begins can be repaired while preserving
its journal; this does not authorise an additional optimisation attempt or
weaken the integrity guard.


## Fixed quadratic numerical remedy: primal simplex

The subsequent MGC trial used the generic versioned preset
`config/model-trials/solver-gurobi-primal-simplex.json`: Gurobi Method=0,
NumericFocus=3 and a 900-second cap. It ran through the unchanged MARIO/CVXLab
pipeline with the same final 58-child checkpoint. All 24 generated CSV inputs
and model/coordinate files matched the failed barrier case exactly (Excel
document timestamps excluded); the native model fingerprint also matched.
No objective, constraint, target, prior, scale or tolerance was changed.

Primal simplex returned optimal in 127.33 native solver seconds and MARIO
accepted the checkpoint: 59 children added, 135 total sectors, 61 regions.
The entire controlled trial took 473.18 seconds. The comparison isolates an
algorithmic numerical issue at this checkpoint; it does not establish a
production policy for every sector or an entropy formulation. The fixed preset
can be selected in the existing trial/sequential runner before a run.

The existing optimal-solution reporting policy was retained. The cleaned point
has a maximum affine residual of about 985.45 USD and 475 cells above the strict
diagnostic tolerance; Gurobi also printed an unscaled dual-quality warning.
These diagnostics remain in the shared report. They are not silently treated
as strict accounting passes or as economic validation. E remains deferred.
The accepted checkpoint, paired inputs, unchanged-input comparison and final
report are published separately from the earlier failed attempts.


## Resuming the integrated sequential runner

The same runner can continue an accepted checkpoint using `--resume` in place
of `--prepared`. It chooses the checksum-verified executed full workbook from
the checkpoint trial manifest, verifies every completed-sector fingerprint and
schedules only pending children while retaining all Master groups in the file.
Use `--workbook` only for an explicit full input override. The original checkpoint
and workbook remain immutable; preparation snapshots, audits and new checkpoints
are written to the fresh output directory.

```bash
python scripts/run_sequential_model.py \
  --resume /path/to/accepted-checkpoint \
  --output /path/to/new-continuation \
  --options config/model-trials/conservative-quadratic.json \
  --solver-options config/model-trials/solver-gurobi-primal-30min.json \
  --trade-audit /path/to/original/trades_audit.csv \
  --policy /path/to/original/policy.json \
  --save-native-models
```

This fixed preset uses primal simplex, NumericFocus=3 and a 30-minute solver cap
for every group, without sector-specific mathematical changes. Native model
exports and Gurobi logs are optional diagnostic artifacts, saved separately per
stage. A first resumed pass still attempts each group once and preserves the
last accepted database after a recoverable failure; further work must follow
the failure evidence instead of repeating unchanged unsuccessful attempts.


## Actual time limits and the bounded continuation

The native log is authoritative when interpreting a failed numerical solve.
CVXPY can expose Gurobi SUBOPTIMAL as `user_limit`, even if the configured time
cap was not reached. Those cases require numerical diagnosis, not an assumption
that more time will fix them. The first primal-simplex recovery pass produced a
true TIME_LIMIT for AGT after 1801.25 seconds, with a feasible point and unfinished
optimality checks; it is distinct from its earlier barrier SUBOPTIMAL outcome.

The first research continuation planned a TIME_LIMIT-only queue using
`config/model-trials/solver-gurobi-primal-2h.json`: Method=0, NumericFocus=3,
two threads and TimeLimit=7200. That queue was cancelled when the first pass
stopped before PLSR's solver; it did not execute the later recovery. Following
specific preparation corrections, the remaining-sector batches used the same
7200-second preset through the generic runner. Their exact settings, source
checkpoints and adjusted scenario inputs are retained per attempt. This is
research history, not an automatic production fallback policy or evidence that
more time alone fixed every failure. Solver tolerances and the MRIO objective
and constraints remain unchanged.

The same generic runner performs the continuation with `--resume` and optional
`--sectors` selection. Keep the full workbook and exact completed-sector
fingerprints. A deferred attempt uses the latest checkpoint and reconciles
pending trade again, so its outcome must not be attributed to the time cap alone.
Unsuccessful attempts remain in the numerical history even when a later attempt
is accepted. Before external handoff, integrate and freeze the selected rule
and complete the [clean full replay](reproducibility-requirements.md).


## Aggregated output at a fully allocated parent

The first recovery pass reached 66 accepted children, then stopped before the
PLSR solver because its target exceeded a residual RPP output by approximately
0.000494 USD. The source matrices and full workbook were unchanged. The older
pre-solver guard allowed only a binary subtraction-error bound, which did not
cover this aggregate-input discrepancy.

MARIO now applies the existing absolute numerical tolerance (1e-6 in the
original monetary units, or 1 USD for these MUSD tables) as a floor for that
pre-solver check in named models. Child output targets and source matrices stay
exact. A negative residual parent within the same band is represented as zero
and recorded in output_roundoff.json; larger budget excesses still fail.
This does not change the optimizer's objective, constraints, solver tolerances
or the optimal-solution export policy. The continuation can therefore retain
the 66 accepted children and their protected mathematical model definition.
The generated roundoff report is included in shared-result diagnostics.


## Input consistency with inherited accounting and zero support

The resumed AGT/MST preparation exposed a concrete mismatch: its fixed output
was about 299,397.07 USD and the preceding row carried a positive accounting
discrepancy of 13.4641 USD. A production-only export cap left the signed-row
projection infeasible by 12.4991 USD. The main MRIO already preserves that row
discrepancy. The trade projection now uses output plus the positive inherited
row discrepancy as its export cap. Original outputs, baseline and source weights
are preserved. Negative discrepancies do not enlarge export capacity.
Checkpoint monetary budget checks use the existing diagnostic trial policy;
missing outputs, invalid units/axes and nonfinite data remain blocking. This is
not an exemption from the MRIO's constraints.

Each independent row projection now chooses the numerical scale
`min(1000, max(1e-6, largest absolute row budget/target/output))`. This improves
small-region conditioning without magnifying values below declared precision.
The original-unit constraints are unchanged and the entire quadratic trade loss
is multiplied by one positive constant, preserving its minimizer. An explicit
scale can be supplied for a controlled comparison. The original common Gurobi
algorithm is retained, with standard ambiguity reoptimization. Effective scales,
solver settings, source weights and residuals are reported per row. A failed
projection saves exact arrays in row_trade_failure.npz and its region/context in
row_trade_failure.json so it can be reproduced without rerunning the MRIO.

Prepared PLSR targets included values around 1e-39 MUSD in DZL and ZAF even
though their remaining parent output was exactly zero. The copy-only preparation
normalizes a pending family's output to zero when its whole observed total is
at most 1e-6 original units and the parent is exactly empty. For one pending child,
an excess above its remaining parent is also snapped down only when that excess
is at most 1e-6 original units. Targets below a positive parent budget are not
rounded up to exhaust it, larger requests are retained, missing observations are
not filled, and completed sectors are never edited. Every changed scenario cell
and its prior value/unit is in output_support_cleanup.csv and the reconciliation
JSON. Original workbooks stay immutable. This is an explicit numerical exception
to bit-for-bit preservation of prepared outputs; it does not rescale meaningful
production observations.

Foreign trade is represented as exact zero on an exactly zero route capacity or
export budget, before retaining reference targets and after a projection solve.
Raw priors and changes stay in the audit. These cells already have zero capacity
in the projection, so this does not create a different free-cell optimum. It
prevents positive numerical solver residue from becoming a hard MARIO target on
an empty route.

When exactly one child receives the complete remaining parent output and all
preceding deliveries are nonnegative, the residual parent cannot deliver any
output. Each foreign delivery is therefore uniquely fixed at its old parent
budget. The projection copies these foreign budgets directly, preserving source
precision, instead of estimating an already determined value with a QP. This is
recorded as analytical_unique_row; ambiguous/signed or incomplete cases retain
the regular projection. In the PLSR investigation this removed trade differences
up to 0.0994 USD, while numerical production excesses were below 0.000591 USD.
No MRIO objective, MRIO constraint or solver tolerance was changed, and CVXLab
was not edited. The exact-algebra input preparation is separate from validation
of the resulting economic recipes.


## Checking a numerical infeasibility diagnosis

PLSR returned INF_OR_UNBD during the default primal presolve. The frozen native
QP was retained for independent diagnostics. A MOSEK run also reported a primal
infeasibility certificate, but reconstructing its 226 reported ray components
gave zero stationarity residual and a **negative** bound objective
(-3.49819628e-8). A valid certificate of primal infeasibility requires a strictly
positive value. The reported subproblem concerns CAC-to-ZAF deliveries: the
preceding RPP budget was about 175.549 USD versus a 140.567 USD PLSR trade target,
leaving positive capacity. These reported statuses alone therefore did not
establish a contradiction in the original economic inputs. The native logs
and the certificate assessment are both retained.

The controlled `solver-gurobi-primal-no-aggregation.json` preset sets Aggregate=0
while preserving the other common primal settings and all solver tolerances.
It tests the solver's presolve representation through MARIO/CVXLab; it does not
relax the optimization constraints. Its result must be checked in its native
log and accepted checkpoint, rather than inferred from the configuration name.
Diagnostic feasibility points never replace an accepted model solution.

Primary references: [MOSEK certificate definition](https://docs.mosek.com/latest/matlabapi/prob-def-linear-equal.html)
and [Gurobi numerical parameters](https://docs.gurobi.com/projects/optimizer/en/current/concepts/numericguide/numeric_parameters.html).

The Aggregate=0 attempt still ended INF_OR_UNBD after 9.81 native seconds during
uncrushing. The next controlled preset, `solver-gurobi-primal-no-presolve.json`,
sets Presolve=0 instead. Its 24 generated CSV payloads and native mathematical
fingerprint (0xf1414c58) match the default-presolve attempt exactly. This isolates
a numerical option change, without an objective/constraint or tolerance change.
Acceptance still depends on the native final status and normal MARIO checks.


## Completed recovery and retained numerical discrepancies

All 69 requested children were accepted: 145 total sectors, 61 regions. The
last PLSR solve returned Gurobi OPTIMAL through MARIO/CVXLab after 5807.08 native
seconds with Presolve=0. The exact generated CSV payloads and original compiled
fingerprint matched the default-presolve attempt. No objective, constraint or
solver tolerance changed, and CVXLab remained untouched. The standard presolve
reported INF_OR_UNBD on those same original inputs; this is a demonstrated
numerical status sensitivity, not evidence that a new economic model was needed.

The saved database follows the agreed postprocessing policy. PLSR's raw point
had a maximum affine/domain residual of 996.87 USD. Zeroing numerical sign and
structural-zero violations increased its largest affine residual to 63267.31
USD by accumulating many cell adjustments in one column. The cleaned point is
not independently certified optimal or rebalanced. Globally, the change from
inherited column accounting reaches 63269.73 USD in DEU/RPP, whose output is
42.02 billion USD (about 0.0001506%). Reaggregated Z differs by at most 2997.10
USD, Y by 36.25 USD, V by 2.15 USD and X by less than 0.001 USD from the original
baseline. Strict checks are reported separately; they are not represented as
passes. Source matrices and workbooks remained unchanged during every attempt.
E recalculation, economic review and a clean frozen baseline replay remain
separate acceptance work.

The independent tighter-precision diagnostic returned INFEASIBLE on its saved
MPS reimport in 1.60 seconds. That reimport's native fingerprint differs from
the original CVXLab compilation; it is not a bitwise original-model proof.
No diagnostic point was used as a database. The accepted comparison is the
MARIO/CVXLab rebuild with matching original compiled fingerprints.
