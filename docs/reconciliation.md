# Reproducible inventory reconciliation

This guide specifies the implemented cleaning stage between native source
observations/resolved D2.4 profiles and MARIO's add-sectors workbook. It applies
to both oneshot and sequential IOT builds. It prepares data without solving the
MRIO split model. Every completed run contains the exact policy, source hashes,
transformations, diagnostics, target tables and a generated guide to its sector
decisions.

The numerical rules are **project assumptions**. Reconciled values are estimates,
not newly collected observations or independently certified source corrections.
Source workbooks, the canonical registry and GTAP baseline matrices are read-only.

## Run the pipeline

Use the `mario` environment and MARIO `dev_SUT_disag`, which includes the
sequential-step and signed-account fixes. Experimental model trials use the
separate MARIO `codex/mrio-model-improvements` worktree. Reconciliation needs the optional dependencies
`pip install -e '.[reconcile]'`; MARIO is installed separately. The workflow has
been developed with CVXLAB 1.1.0. The detailed runtime versions and implementation
file hashes are recorded in each reconciliation run.

Add the following fields to the existing local configuration:

```json
{
  "geography": {
    "name": "ENTICE13",
    "mapping": "/absolute/path/to/data/geographies/gtap13.json"
  },
  "disaggregation": {
    "inventories": "Inventories/D2.4 inventories/Regenerated 20261001",
    "cleaning_policy": true,
    "steps": null
  }
}
```

`true` selects the bundled `config/cleaning-policy.json`. A string selects a
custom policy; configuration-relative strings resolve from `data_root`. CLI
policy and mapping paths resolve from the current working directory. The final
geography can contain any complete source-to-target partition; `null` retains
all native regions.

```bash
python scripts/run_disaggregation.py \
  --cleaning-policy config/cleaning-policy.json \
  --mapping data/geographies/gtap13.json \
  --intermediate-steps --output build/disaggregation/clean01
```

The command prepares inputs. It does not solve unless `--solve` is explicitly
supplied. Edit the generated `add_sectors.xlsx` to arrange every sector exactly
once in `Intermediate steps`, then run:

```bash
python scripts/run_disaggregation.py \
  --prepared build/disaggregation/clean01 --solve
```

The experimental MARIO checkout additionally accepts
`--model-options config/model-trials/accounting.json` or a custom options JSON
on solve/resume calls. These settings do not alter cleaning and are not selected
by default. Use a fresh trial/checkpoint root when changing the model; normalized
options are saved in accepted checkpoints and cannot change across a resume.
The project's `quadratic.json` sets `defer_satellite_recalculation=true` because
E will be rebuilt after the monetary split. E is provisional and explicitly
listed in `pending_recalculations`; its conservation does not block acceptance.
All monetary/accounting checks and the EY/VY checks remain enforced.
`scripts/run_model_trial.py` is the controlled comparison entry point described
in the baseline report: it copies inputs, records code/input identities and
checks their hashes after the run.

The same controlled runner can resume an accepted checkpoint in a new output
directory, retaining the checkpoint's model options and running all pending
groups unless `--stop-after-step` is supplied:

```bash
python scripts/run_model_trial.py \
  --resume build/model_trials/20261020/quadratic_deferred_E/checkpoints/001_Mining \
  --output build/model_trials/20261020/remaining50 \
  --solver-options config/model-trials/solver-qp-refined.json
```

The checkpoint is verified before loading, its remaining workbook is copied,
and cumulative budgets are checked against its remaining parent capacities.
The source checkpoint is hashed again after the run. An optional `--workbook`
selects an edited remaining plan without changing that source checkpoint.

For a first-group pilot, name its plan column `Mining` and add
`--stop-after-step Mining` to that solve command. MARIO writes the accepted
intermediate database and remaining workbook, then returns before the next
group. The complete plan and canonical future-sector references are preserved;
cleaning is not repeated. An unknown/already completed stop group is rejected
before solving, and a partial database is not labelled as the final build.

`--no-cleaning` requests the former preparation path. All numerical capacity
checks remain blocking; the flag does not allow incompatible inputs into a
solve. The D2.4 generation runner also honours `disaggregation.cleaning_policy`:
it writes its raw target diagnostics, reconciles those targets after native
profile export, and checks the reconciled inventories before accepting them.

### Use a MARIO database already in memory

```python
prepared = prepare_inputs(native_inventories, output_directory,
                          database=native_db, geography=geography,
                          cleaning_policy=True, output_reference_dir=output_references)
```

`native_db` is a MARIO IOT in the source inventories' geography, regardless of
the parser or file format used to construct it. Preparation and reconciliation
use that object directly; target geography is built on a copy. No database
reload or baseline export is needed. Sector identities, units and source data
must be compatible with the selected policy. Matrix and unit fingerprints are
recorded in the audit instead of claiming original-file provenance.

### Source roles

The existing `data_root`/`paths` configuration resolves these roles:

| Role | Used for |
|---|---|
| `baseline` | Native parent budgets and parent technology/intensity priors. |
| `mario_inventories` | Explicit original output rows missing from the D2.4 export. |
| `partner_templates` | Exact policy-selected monetary columns or source parent shares. |
| `purdue_split_targets` | One paired delivery's REG, REPSEC, REPOUT and BLTTRD. |
| `purdue_trade` | NTSCIF direct-code and composite-product trade priors. |

The default source selection uses the configured June1 paired output/trade
delivery. The earlier May27 material remains separate. Source releases are not
unioned or selected according to how many numerical checks they pass.
An API caller can explicitly override these roles through `source_paths`, e.g.
to use immutable local snapshots. The manifest records the paths and bytes
actually read. No analytical `build/audits` file is a hidden production input.

## Order of operations

1. Freeze policy, registry fingerprints and input identities; read native parent
   budgets in column batches without loading global Z into a DataFrame.
2. Resolve one working parent per child and identify any parent-dependent rebuild.
3. Read the explicit source columns, classify blanks/zeros, and make native output
   priors. Fit geographic totals jointly when clusters are present.
4. Allocate explicitly shared output observations once, then aggregate to the
   selected final geography and cap all siblings jointly.
5. Select paired/direct/composite trade priors or estimate them from the parent.
   Internalized routes are recorded and removed from foreign-trade targets.
6. Fit trade under producer and parent-route capacities, with source weights.
7. Construct technology priors using source/donor/parent profiles, project input
   geography and balance monetary coefficients while retaining signed factors.
8. Write inventory workbooks and read them back. All capacity checks must pass.
9. Merge the inventories into MARIO's workbook, validate the group plan and save
   the selected baseline. Only a separately requested call solves the MRIO.

All children are reconciled together **before the first sequential split**.
Grouping/insertion order cannot decide which sector consumes the available
output or trade budget during cleaning. New reconciliation policy, classification
or geography requires a new preparation directory. A resumed MARIO run retains
its completed results and cannot clean them again in place.

## Policy contract and sector identities

`config/cleaning-policy.json` is versioned, contains no numerical source payload,
and gives an explicit decision for all 67 released sector identities. Each entry
contains the expected declared parent and an output-source recipe. A different
declared input parent or an unknown child fails rather than silently changing
the meaning of a frozen policy. The default policy requires all 67 sectors;
custom policies can define smaller complete sets.

Reviewed registry parents take precedence. An explicitly selected conditional
scope is resolved through the existing registry bridge. Unreviewed identities
retain their declared working parent, with that conditional status in the log.
The canonical registry itself is not edited by the cleaning stage.

The initial scope conventions are:

| Sector | Selected scope | Working parent |
|---|---|---|
| PLP | Finished plastic products | RPP |
| PLR | Materials recovery | WTR |
| PLSR | Finished secondary plastic products | RPP |
| RAL | Secondary aluminium manufacture | NFM |
| RCP | Secondary copper manufacture | NFM |
| RER | Rare-earth chemical compounds | CHM |
| WNT | Electrical generating equipment | EEQ |

These are modelling conventions, not new NACE/HS certification. In particular,
the recovery/manufacturing and turbine/generator boundaries remain visible.
GAR and NMC also use their reviewed NFM and EEQ parents. A changed parent triggers
a new parent technology prior; it is not a label-only edit. NMC remains distinct
from NCM: absent an independently identified template, its historical global
child/old-parent share is transferred to the reviewed parent and labelled imputed.

The policy explicitly pairs one file with one identity. Copied `General info`
labels are logged as context and do not select a different activity or merge
related records. Repeated source rows with one identical positive value are used
once; conflicting distinct positive values require a revised source decision.

### Shared recycled-plastics observations

PLR and PLSR use an explicitly shared observation group. The initial policy takes
the PLSR monetary output prior once and allocates 50% to the recovery activity and
50% to the finished secondary-product activity. Both allocations are subsequently
subject to their own parent budgets. The equal split is a transparent assumption
made because separate compatible values are unavailable; it is not inferred from
the equality of source values alone and does not assert that every pair of equal
IO values is a duplicate. Alternative weights require a new policy/run.

## Source columns, units, years and missingness

The policy names the template file, value column, paired unit column, expected
first two column headers and conversion factor. Runtime header checks detect
layout changes. Cached formula values are snapshots; external links and Excel
formulas are not recalculated. Raw values, formulas, unit labels, headers,
coordinates, conversion factors and assumptions are written to `changes.jsonl`.

The initial exceptional decisions are:

| Case | Adopted operation | Meaning/limitation |
|---|---|---|
| MSI G and TVP E | Multiply by `1e-6`. | Literal USD-to-MUSD interpretation; derived regional estimates are regenerated afterwards. |
| PLSR E | Select the monetary product column. | The former physical-production column is not relabelled as money. |
| LMO E | Use its monetary row labels as the target-year interpretation. | The conflicting older header remains recorded. |
| CEM E | Use the cached dimensional monetary formula. | Price/year/scope uncertainty is retained as an assumption. |
| SDG I | Use the monetary row-unit interpretation. | Conflicting physical header remains recorded; geographic totals are soft observations. |
| RBR H | Treat stored fractions as fractions; multiply by operational parent X. | The old 2017 derived monetary F values are not treated as observed 2023 levels. |
| SDH | Use the historical global share as a weak fallback. | No positive monetary source is manufactured; a resulting zero is an imputed prior. |

Other selected columns are listed for every sector in the policy; the generated
run README lists the sector decisions and assumptions. The implementation does not invent exchange rates or product prices:
existing cached conversions and explicit factors are used. A source requiring a
different interpretation needs a corresponding policy recipe.

Three zero/missing cases remain distinct:

* **Structural baseline zero:** a native parent with zero production cannot
  provide positive child production. A zero foreign parent route cannot carry
  nonnegative child deliveries.
* **Source parameter zero:** an omitted REPOUT key is zero only inside its
  explicitly declared REG × REPSEC domain. A missing child code is not zero.
  Explicit and implicit parameter zeros have different provenance tags.
* **Unavailable observation:** a template blank, nonnumeric/unusable value or
  formula without a cached value supplies no numeric observation. The native
  target is estimated and tagged, not silently read as zero.

The configured RBR source has three country-share proxies: Iceland → XEF,
Myanmar → XSE, Republic of Moldova → XSU. Their shares are weak priors (confidence
0.1) for the corresponding native residual region, not observations of that
entire region's output. An unconfigured positive geography fails explicitly.
WORLD denotes the complete native geography.

## Output estimation and geographic observations

For a missing child/country target, the initial share is the ratio of summed
usable direct child outputs to summed corresponding parent outputs in the final
macroregion. If none are available, use the global ratio. Where only a cluster
is available, its level/parent capacity supplies the global reference ratio.
If the child has no usable monetary observation anywhere, use its historical
global child/old-parent ratio, including a labelled zero prior. Reference shares
are bounded to `[0,1]`; estimates are `share × native parent X`.

Direct point observations are used as priors. Sectors with geographic clusters
are fitted jointly using nonnegative scaled least squares. For observation j,
the model compares `sum(x[r], r in members[j])` with its source value. Default
weights are direct 100, regional cluster 10, whole-world 1, and prior-distance
0.01; observation confidence multiplies those weights. A stored template zero
has an additional 0.1 multiplier in this geographic fit. Numerical scaling is
`max(abs(observation), 0.01 × corresponding parent capacity, 1e-6)`; prior scaling
is `max(prior, 0.01 × country parent X, 1e-6)`. Countries with zero native parent
production remain zero.

Ordinary direct observations have confidence 1; explicitly converted template
values and parent-share observations have 0.5, and the three configured country
proxies have 0.1. Imputed outputs are tagged with confidence 0.1 in the audit;
their least-squares regularization uses the separately declared prior weight.

Inclusive totals cover every declared member. Residual totals exclude explicit
positive direct countries and other proper geographic subgroups. The policy
encodes APS's GBR exclusion from REST OF EUROPE and residual GLOBAL meanings for
SDG, SOP, PLR and PLSR. SDG WORLD is an inclusive, weak total (weight 0.1), so its
conflict with other source totals appears as a residual rather than disappearing.
Exact member sets, exclusions and achieved totals are logged. Contradictory
source totals are soft observations and can change; no statistical error band
is claimed for these project weights.

After fitting and any shared-observation allocation, outputs are aggregated to
the requested geography. For every parent p and selected region r, let S be the
sum of **all** its planned children. Apply the common factor

```
f[p,r] = min(1, X_parent[p,r] / S[p,r])     # f=1 when S=0
x_clean[c,r] = f[p,r] * x_prior[c,r]
```

The same factor is applied to that child's native components inside r, retaining
their relative weighting for cost aggregation. This rule preserves the relative
child composition. Source reliability is recorded, but this initial output cap
is deliberately proportional; a weighted output-cap alternative is not enabled.
When the cap binds, the children exhaust the parent's output and its residual
activity has zero output. No positive residual reserve is assumed. This activity
coverage convention remains a substantive assumption for the eventual split.

## Trade source selection, composites and reconciliation

Selection precedence is fixed by source identity/domain, not by numerical fit:

1. A Purdue-output child in paired REPSEC uses BLTTRD from that same delivery,
   including a source-domain prior of zero where all routes are absent.
2. Other children with positive direct-code NTSCIF use that code, unless the
   policy explicitly specifies parent-pattern estimation (PLR recovery service).
3. Missing direct codes use configured composite candidates once: ALM, CEMN,
   HYD, IST, LBT and PLT. The exact active memberships are in the policy.
4. A child with no selected direct/composite source inherits its parent pattern.

For a composite route, subtract selected priors of explicitly covered direct
members from its value, floor the residual at zero, and allocate that residual
once among missing compatible children using their native producer-output shares.
All operands and source conflicts are logged. These product/activity and chemistry
allocations are modelling assumptions. The resulting values are weak priors,
not exact composite-total constraints. A producer with zero allocated output
cannot be assigned positive trade by the allocation.

For an entirely unobserved child trade table the reference is

```
T_prior[c,o,d] = (x_clean[c,o] / X_parent[p,o]) * T_parent[p,o,d]
```

with zero for a zero-production parent. `T_parent` is the sum of the parent row's
Z and Y deliveries to destination d. This reference transfers the parent's
export propensity and destination mix. Absent routes in an explicitly selected
source parameter remain zero priors; the fallback is not a hidden union of
alternative sources. Native foreign routes that become domestic under regional
aggregation are logged as internalized and are omitted from foreign targets.

The selected trade levels may be CIF/customs data. The implemented calibration
uses them as priors on domestic-production deliveries within the MRIO envelope;
it is **not** an independently estimated CIF/basic-price or re-export bridge.
Source-specific confidence records that assumption.

For each parent/origin, one convex quadratic problem fits all positive child and
destination priors together. These groups are separable because no additional
import-total equality is imposed. The loss is weighted chi-square distance
`sum(w_source * (T - T_prior)^2 / T_prior)`, using fraction variables for numerical
scaling, with bounds:

```
0 <= T_clean <= T_prior
sum(children T_clean[p,o,d]) <= T_parent[p,o,d]
sum(foreign destinations T_clean[c,o,d]) <= x_clean[c,o]
```

Weights are paired 1, direct NTSCIF 0.5, composite 0.2 and imputed 0.1. They encode
relative project preference, not estimated sampling variances. Trade adjusts to
the corrected output budget; output is not increased by this trade-fitting step.
Zero producer/route capacity is applied explicitly. Already feasible groups
retain their priors. CLARABEL is the default solver; statuses and pre-polishing
constraint residuals are recorded. Downward capacity polishing removes numerical
overruns and cannot invalidate another upper bound. Only `optimal` and
`optimal_inaccurate` statuses are accepted, with an independent capacity check
required in both cases. Other statuses, nonfinite results or failed capacity
checks stop the run.

### Experimental projection against signed row budgets

The capacity-only fit above does not guarantee that child and residual-parent
rows can satisfy their output targets. In particular, a parent with zero
residual output may require **increases** in child exports. Decreasing priors
alone cannot resolve that case. The default ingestion policy is unchanged;
`scripts/reconcile_model_trade.py` provides a separate copy-only experiment from
an accepted checkpoint:

```bash
python scripts/reconcile_model_trade.py \
  --checkpoint /absolute/path/to/accepted_checkpoint \
  --trade-audit /absolute/path/to/reconciled/audit/trades.csv \
  --policy /absolute/path/to/reconciled/audit/policy.json \
  --output build/model_trials/my_trade_projection
```

For each parent/origin, retain the preceding Z/Y deliveries' positive and
negative budgets by destination. Allocate these budgets among all pending
children and the residual parent, requiring each row's net total to equal its
unchanged output plus its inherited accounting discrepancy. Foreign child
deliveries remain nonnegative and retain the producer-output and parent-route
upper bounds. The parent residual has its own row budget. Missing trade rows
are free in the feasibility probe; they are not silently treated as observed
zeros. A group whose existing targets pass this LP and the upper bounds is
preserved exactly, including its sparse target support.

In a conflicting group, minimize weighted squared trade deviations divided by
`max(abs(prior), 0.01*parent_route_capacity, 1e-6 MUSD)`. The original source
weights are used only after matching the source audit against the workbook;
previously absent routes have a zero reference and weight 0.1. Increases and
new fitted routes are allowed. This is an explicit experimental estimation
assumption, replacing the downward-only bound within these conflicting groups.
Budget fractions improve numerical scaling without deleting negative budgets.
CLARABEL is attempted first, then OSQP on numerical failure; both attempts and
their statuses are recorded. Only `optimal`/`optimal_inaccurate` results with an
independent monetary residual at most `1e-6 MUSD` pass the projection.

The output records every fitted route in `trade_changes.csv`, source hashes,
weights, solver diagnostics and the estimation rules in `reconciliation.json`.
Only the `Trades` and `Intermediate steps` ZIP members are rewritten; all other
workbook members, including output targets and technology profiles, remain
byte-identical. The source checkpoint is verified before loading and its hashes
must remain unchanged. The projected workbook puts all pending sectors in one
group for a subsequent controlled resume.

This projection is a **necessary row-feasibility check**, not full MRIO
certification: column accounting, cell-specific zeros and V still require the
normal MARIO solve and independent checkpoint verification. The report therefore
explicitly sets `full_mrio_certified: false`.

## Technology profiles and monetary balance

The boundary remains resolved native profiles, not unresolved input overrides.
For each child and selected producing region, weight source profiles by the
cleaned native outputs. A missing or unusable native profile borrows the same
child's positive-output profiles in the macroregion, then globally, then available
zero-output reference profiles; if none exist, use the selected parent prior.
Zero-output selected groups use unweighted available references. Every donor,
output weight, rejected-profile reason and original profile sheet is recorded.

A parent change rebuilds the profile from the **new** parent. Parent technology
and satellite intensities use the supplied Z, V and E divided by parent X;
globally averaged parent technology is the fallback for a zero-output donor
region. This rebuild is an explicit loss of child-specific information, visible
in the run log. The original child source is retained as evidence.

Sector/factor clusters are resolved into concrete items with parent-profile
shares. Input-origin GLOBAL uses the complete native universe. Origin clusters
which are unions of whole selected regions remain aggregate observations;
partially overlapping origin clusters are allocated using parent input-origin
weights, then parent output weights, then uniform weights if both are zero.
Source cost units must match baseline item units; an unusable profile is rejected
as a donor and follows the imputation hierarchy. Nonempty structural Exclusions
need an explicit coordinate policy and currently stop cleaning.

Only sector inputs and factors enter the unit-output monetary identity.
Satellites keep their own units and are not normalized. Existing negative factor
coefficients remain fixed, including signed Tax. Nonnegative sector input priors
are projected to zero where necessary and recorded. If an entire factor block
is absent and monetary costs do not balance, a signed parent factor prior is
inserted; a positive gap is apportioned according to its composition.

For a monetary residual within 0.01, positive coefficients are rescaled together
to balance around the fixed negative components. Larger residuals use a
nonnegative weighted chi-square projection, with sector weight 4 and factor
weight 1. Thus factors can change more readily than intermediate inputs. Negative
factors and satellites do not absorb the balancing residual. The written
monetary sum must equal one within `1e-10`.

For initially positive monetary components the projection minimizes
`sum(w[i] * (a[i] - a0[i])**2 / a0[i])`, subject to `a[i] >= 0` and
`sum(a[i]) = 1 - sum(fixed_negative_factors)`. Initially zero components remain
zero. An active-set solution removes any components that would otherwise become
negative and refits the remaining positive support.

The resulting costs remain CE priors. Cumulative input-flow feasibility is not
claimed: MARIO must still find flows under the exact preceding aggregates, its
structural support and signed-account formulation. Native GTAP accounting
residuals remain in the supplied baseline and must be distinguished from new
split residuals. Negative taxes are not data errors to erase.

## Acceptance, failure and replay

Acceptance checks run on fitted targets and again after writing/reading Excel:

* complete child/region output coverage;
* each parent/region sum of child outputs fits parent X;
* each directed foreign parent route fits parent Z + Y deliveries;
* each child's foreign exports fit its reconciled output;
* finite values, compatible units, unique target coordinates and monetary-profile
  balance.

Capacity allowance is `1e-6 + 1e-8 * abs(reference)` in each parent unit. It is
numerical precision, distinct from source confidence and optional review screens.
The checks do not certify full MRIO feasibility.

Each run contains:

| Artifact | Purpose |
|---|---|
| `README.md` | Run-specific assumptions and all sector decisions. |
| `audit/policy.json` | Exact policy; canonical SHA-256 in summary/complete manifest. |
| `audit/inputs.json` | Read source roles, bytes and SHA-256, including baseline. |
| `audit/changes.jsonl` | Source records, units, formulas, imputations, allocations, profile lineage, projections and solver adjustments. |
| `audit/outputs.csv` | Original written aggregate and reconciled output by child/region. |
| `audit/trades.csv` | Selected/estimated prior and final trade by child/origin/destination. |
| `audit/sectors.csv` | Parent changes, source assumptions and per-sector totals. |
| `audit/checks_before.json` | Raw-target diagnostic; incompatible raw data is not a successful cleaned input. |
| `audit/checks_targets.json` | Mandatory checks after target reconciliation. |
| `audit/checks_after.json` | Mandatory checks after inventory Excel read-back. |
| `audit/solvers.json`, `audit/summary.json` | Solver statuses, diagnostics and event counts. |
| `inventories/*.xlsx` | Complete inventories in the selected geography. |
| `complete.json` | Success marker, runtime/code/registry/policy fingerprints and source-certification status. |

A failed run retains `failure.json` and a failed audit summary, without a success
marker. `prepare_inputs` executes reconciliation inside its hidden staging
directory; the prepared directory is committed only after all workbooks and the
baseline have been written and validated. Existing run directories are never
overwritten. Private numerical reports belong under ignored build/shared data
directories, not public Git history.

When resuming, cleaning is not rerun over already accepted MARIO sectors. The
resume runner checks pending targets against the checkpoint's remaining budgets;
MARIO also verifies preceding-result preservation and completed-input fingerprints.
Changing an assumption affecting a completed sector requires an earlier baseline.

## Verified example and practical limits

The 20 October 2026 test prepared all 67 sectors on the bundled 13-region map,
without running the MRIO split. The raw-target diagnostics had 6 parent-output,
13 parent-route and 154 known producer-export violations, plus 31 missing native
output cells. All became zero violations/incomplete cells after the explicit
reconciliation recipes; missing values are now labelled estimates. The 871
written profiles have maximum monetary residual `6.89e-15`.

Two real preparations produced identical output/trade/sector audit CSVs. A
separate ZIP/OOXML reader and `math.fsum` calculations independently verified
coverage, monetary profiles and all capacities against the saved regional
baseline. All 174 recorded input files were rehashed unchanged, as were all 38
original shared partner/Purdue source captures. Private reproducible evidence is
in `build/qa_reconciliation_20261020/verification.json`. The automated suite has
64 passing tests with producer integration enabled; `pip check` passes in the
`mario` environment.

This verification covers data preparation on 13 regions. It is not a full
native-geography performance benchmark or an MRIO feasibility certificate. In
particular, the solver's relative-entropy treatment of signed Tax/TTM priors,
cumulative technology-input constraints and supplied baseline accounting
residuals still require model-level work. The default policy marks
`source_certified: false` and `MRIO_split_solved: false` in each success manifest.

The subsequent [real mining-first pilot](baseline/README.md#actual-mining-first-split-20-october-2026)
reached CLARABEL with all 17 mining sectors on 13 regions, then terminated with
`InsufficientProgress`; no accepted intermediate checkpoint was saved. Actual
V0 references and a negative fixed parent Tax total expose an entropy-domain
contradiction. The report distinguishes that structural certificate from the
full solver status and records negative Capital/Labor priors for separate review.


## Review of invalid nonnegative-factor priors

The [MCU source-prior review](prior-review.md) traces Capital/Labor conflicts to
EXIOIOT and exports two explicit parent-factor scenarios with joint Z/V
reconciliation. It also flags broader technology concerns. These are data-only
proposals; the ordinary preparation and input workbooks are unchanged. A sign
repair should not be mistaken for independent economic validation.
