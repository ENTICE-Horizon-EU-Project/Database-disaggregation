# Regional scalability pilot

The first larger-geography experiment uses the inherited Purdue GTAP → EXIOBASE
crosswalk: 163 native GTAP regions → the legacy EXIOBASE 3 axis of 44 countries
and five rest-of-world aggregates. This remains a GTAP monetary IOT with GTAP
sectors; it does not import EXIOBASE transactions or change sector classification.

`data/geographies/exiobase49.json` is the complete partition. Its adjacent
`.source.json` records the shared source workbook, sheet, checksum and scope.
The source is `Classifications/_sources/Purdue/GTAP_EXIOBASE_maps.xlsx`,
`Regions_map`, with GTAP codes converted to uppercase. The inherited territorial
concordance is not independently certified. The same mapping is also present
in the consolidated classification workbook. The EXIOBASE axis is described at
<https://exiobase.eu/about-exiobase/>.

## Reproduce the one-sector test

These commands describe the recorded quadratic pilot below. New experiments
now default to the [entropy-first model/solver policy](model-policy.md); keep the
explicit quadratic arguments only to reproduce that formulation.

Select MARIO `codex/mrio-model-improvements` and this repository's
`codex/configurable-regions` branch; configure your own `data_root`. From this
repository root, with the MARIO environment activated:

```bash
export MARIO_SOURCE="/path/to/the/matching/MARIO/checkout"
export PYTHONPATH="$MARIO_SOURCE:$PWD/src"
python scripts/run_disaggregation.py \
  --mapping data/geographies/exiobase49.json \
  --cleaning-policy config/cleaning-policy.json \
  --steps config/exiobase49-pilot-steps.json \
  --output build/scalability/my_exio49/prepared
python scripts/run_model_trial.py \
  --prepared build/scalability/my_exio49/prepared \
  --options config/model-trials/quadratic-gurobi.json \
  --solver GUROBI \
  --solver-options config/model-trials/gurobi.json \
  --stop-after-step "Pilot MCU"
```

Preparation retains all 67 children for consistent cumulative output/trade
budgets and future supplier references. The solve introduces only **MCU (copper
ore mining)**; 66 children remain pending. The baseline has 76 sectors per
region (3,724 sector/region coordinates); an accepted pilot has 77 (3,773).

The quadratic formulation uses inherited accounting, Capital/Labor ≥ 0,
signed Tax/TTM, exact preceding aggregates and deferred E recalculation. Its normalized objective/accounting options match the previous quadratic
policy; the new policy selects Gurobi for the affine feasibility check as well
as the QP. A working Gurobi installation and licence are required. The two-thread,
1,800-second controls and tight solver tolerances do
not change the constraints, objective or independent acceptance criteria.
The feasibility probe retains the same absolute numerical envelope as before. Source data and
the native baseline are preserved; geography changes always start from scratch.

Record preparation and trial wall times separately, solver times, model variable
and constraint counts, sampled peak process-tree RSS (not a physical-memory/PSS
measurement), status, and independent checkpoint conservation/accounting/target
checks. A resource stop is not a proof of mathematical infeasibility. A successful
one-child pilot does not establish feasibility or runtime for all 67 children.
The historical 13-region Mining run introduced 17 children and used an older
factor policy, so its runtime is context rather than a controlled scaling ratio.

Numerical workspaces and resource logs stay under ignored `build/scalability/`;
published inputs/results use the standard paired SharePoint folders.

## Accepted result — 21 October 2026

The real MCU pilot completed with Gurobi in both stages and was published as
`20261021 1741 - 49 regions and 1 sectors`. This folder name counts newly
introduced sectors: the database contains **49 regions and 77 total sectors**.
The paired folders, relative to `data_root`, are:

- `Inventories/D2.8 inventories/20261021 1741 - 49 regions and 1 sectors`
- `Database/D2.8/20261021 1741 - 49 regions and 1 sectors`

The exact pre-split baseline is `Database/_GTAP Power 2023/EXIOBASE49 baseline`.
Run provenance records pipeline revision `6d75770` and MARIO revision `90da5c8`.

| Measurement | Accepted pilot |
| --- | ---: |
| Scalar variables in the feasibility probe | 749,602 |
| Canonical affine constraint rows | 3,350,168 |
| Gurobi feasibility solver time | 31.5 s |
| Gurobi QP solver time | 6.3 s |
| Trial wall time before publication | 544.3 s |
| Trial wall time including publication | 746.8 s |
| Peak sampled process-tree RSS | 3.59 GiB |
| Read-only benchmark wall time | 8.1 s |

The feasibility LP represents equality envelopes as two inequality rows, giving
3,922,324 native Gurobi rows. Its nominal absolute envelope and Gurobi's native
feasibility tolerance are both recorded in `diagnostics/feasibility.json`.
It is a preliminary diagnostic; the original QP constraints and independent
acceptance checks determine whether a checkpoint is accepted.

Most elapsed time was outside the native solver: workbook/database I/O,
construction, canonicalisation, verification and publication. These measurements
are from one run on an 18 GiB Mac, with two solver threads and one-second RSS
sampling. The RSS sum can double-count shared pages and excludes compressed
memory. Preparation is excluded from the successful-trial wall times above.

The independent checkpoint verifier accepted the result. The saved-matrix
benchmark passed all **11 hard checks**, including reaggregation, inherited
accounting, nonnegative Z, all 49 prepared child outputs and 346 selected prepared
trade observations. Capital and Labor are nonnegative in the affected child and
residual columns. The report computed Leontief stability diagnostics for both
databases. E remains pending recalculation.

The dashboard nevertheless reports **85 economic review flags across 45
sector/region coordinates**: 25 for gross flows at effectively zero output,
29 for imported-input share changes, 19 for export share changes, 11 for VA share
changes and one for a final-demand share change. Passing accounting and target
checks does not establish economic plausibility or independently validate the
harmonised targets. These flags remain visible for review; no post-hoc matrix
patch was applied.

### Preparation and attempt history

The full 67-child preparation contains **3,283 region/sector inventory sheets**.
Its first export was interrupted after about 19 minutes when profiling identified
a repeated quadratic sheet lookup in the Excel writer. MARIO now constructs the
same sheet-name mapping in one pass. A ZIP-member regression comparison verified
that the writer preserves the workbook contents. Serialization then resumed from
the 67 already reconciled, unchanged workbooks in 136.6 seconds, without a second
reconciliation. This is a recovery measurement, not a clean end-to-end preparation
benchmark. All 174 original source files were hash-verified unchanged.

An initial Clarabel trial reached `optimal`, but a sparse-expression error in the
independent verifier prevented acceptance and publication of a database. MARIO's
verifier now handles sparse affine domains without changing the acceptance
thresholds. Tests cover valid results and rejection of actual violations. The
subsequent Gurobi trial reused the same preparation and mathematical policy.
The two attempts are not a controlled solver-speed comparison.

The first read-only benchmark was also stopped: the published XLSX container
changed during reading. Comparison with the accepted local step input showed
identical model worksheets, workbook, strings and styles; differences were in
package metadata. The retry passed the original file-integrity checks, without
relaxing them. Both benchmark logs and the package comparison are retained.

The accepted database includes the dashboard (`benchmarking.html`), report JSON,
sector CSV, and `diagnostics/scalability/summary.json` with resource logs,
preparation audit and attempt history. The 66 pending children were not solved;
this result establishes only the feasibility of this one-child, 49-region pilot.

## KL/MOSEK comparison and factor-prior sensitivity — 21 October 2026

**No KL database was accepted.** The original-prior attempt stopped during model
construction; two further attempts on explicitly corrected priors passed affine
feasibility, but MOSEK ended with `UNKNOWN`. This is not a proof of mathematical
infeasibility. No solver/model fallback or post-hoc matrix correction was used in
these fixed-model trials.

The source MCU/Brazil inventory has negative Capital and Labor priors. Following
explicit approval, `scripts/reconcile_factor_priors.py` created a separate
preparation with Capital/Labor ≥0, preserving net V in each affected profile.
The weighted minimum-distance projection also adjusts the signed Tax/TTM rows.
Only eight numeric cells changed: four in MCU/Brazil and four in MCU/Lithuania,
where MCU output is zero. All other XLSX members, monetary intermediate priors,
output, trade, tolerances, exclusions, stage plan and baseline are unchanged.
Original sources and the previous quadratic database were hash-verified unchanged.
The regular preparation policy is unchanged; this remains an opt-in experiment.

The corrected input SHA256 is
`6235bf912e433c86064a1389538c6a912470af2c97fad11c39cd733047bdacec`.
Both new formulations use exactly that workbook, inherited accounting, weights
Y=0.1/supply=1, scale=1000, two solver threads, a 1,800-second native limit and
strict finite-objective verification. Gurobi performs affine feasibility.

| Trial | Outcome | Native optimiser | Before publication | Including publication | Peak sampled RSS |
| --- | --- | ---: | ---: | ---: | ---: |
| Original quadratic/Gurobi | Accepted | 6.33 s | 544.30 s | 746.82 s | 3.59 GiB |
| Corrected-prior quadratic/Gurobi | Accepted | 3.75 s | 303.47 s | 418.91 s | 5.53 GiB |
| Corrected-prior direct KL/MOSEK | UNKNOWN, rejected | 71.58 s | 316.23 s | 319.90 s | 5.09 GiB |
| Corrected-prior equivalent KL/MOSEK | UNKNOWN, rejected | 66.30 s | 316.63 s | 321.41 s | 4.43 GiB |

Failed times describe aborted attempts, not time to an accepted solution. Failed
publication saves inputs only; successful quadratic publication also saves a
database. Preparation is excluded. The objective, solver and numerical
representation differ between some cases, and these are individual executions,
so this is not an isolated solver-speed or statistically replicated benchmark.
RSS is sampled process-tree RSS and can double-count shared pages.

For fixed positive references, KL is exactly
`-entr(x) - (log(q)+1)*x + q`, including at x=0. MARIO revision `5f03354` uses
this representation to avoid tiny prior values as exponential-cone coordinates.
It resolves a small reproducible failure and preserves objective values, domains,
weights, support and physical constraints, with 116 relevant tests passing. It
**did not resolve this full MRIO case**. The coefficient still follows the literal
minimum-prior rule: minimum nonzero 4.079e-18 M USD, coefficient 1e-22 M USD
(1e-25 in scaled units). No clipping or numerical-floor increase was applied.
Original quadratic used MARIO `90da5c8`; corrected quadratic used `0f94b42`;
equivalent KL used `5f03354`. The quadratic expression/physical constraints are
unchanged across these revisions. Pipeline trial code was `5bf7c18`.

### Economic interpretation

The corrected quadratic database passes all **11 hard checks**, including all
49 output targets and 346 selected trade observations. It has 86 economic review
flags across 46 coordinates, versus 85 across 45 in the old quadratic. Capital,
Labor, Y and Z satisfy their nonnegative domains. Gross Z inputs in regions with
effectively zero output remain about 0.01616 M USD; E remains pending. These
issues were not patched after solving.

The material sensitivity is MCU/Brazil: net V/output changes from **71.8% to
0.68%** in the two quadratic results, despite identical output and trade targets.
The source negative Capital/Labor almost cancelled positive Tax/TTM, so the
sign-constrained, net-preserving projection moved all four priors near zero.
This is an assumption, not independent evidence for the true factor composition.
The new result should be treated as a sensitivity experiment. Review or rebuild
the affected V priors using defensible source information before adopting them;
a successful solver or stable aggregate Leontief diagnostics cannot establish
that either VA composition is empirically correct. With KL still uncertified,
there is no accepted KL-versus-quadratic economic comparison.

### Published files

Under the configured `data_root`, the accepted corrected quadratic result is:

- `Database/D2.8/20261021 2044 - 49 regions and 1 sectors`
- `Inventories/D2.8 inventories/20261021 2044 - 49 regions and 1 sectors`

The database includes `comparison-models.html`, `comparison-models.md`, complete
`comparison-models.json`, a 49-region MCU CSV, a performance PNG and the
`benchmarking.html` baseline dashboard. `diagnostics/model-comparison/` retains
all attempt logs, resource profiles, the eight-cell reconciliation audit,
reconciliation code, the equivalent-KL patch and reproducible report driver.
The HTML links/structure were checked statically and the PNG visually inspected;
the internal browser disallowed local-file preview.

Failed input-only folders are preserved under `Inventories/D2.8 inventories/`:

- `20261021 2018 - 49 regions and 1 sectors`: original signs rejected before solving.
- `20261021 2038 - 49 regions and 1 sectors`: corrected priors, direct KL UNKNOWN.
- `20261021 2052 - 49 regions and 1 sectors`: corrected priors, equivalent KL UNKNOWN.

No corresponding failed database folders were created. The earlier accepted
`20261021 1741 - 49 regions and 1 sectors` database remains unchanged.

## Native 163-region, two-sector probe

`data/geographies/gtap163.json` is an identity partition of all native regions,
verified against the native cache. `config/gtap163-two-sector-steps.json` retains
all 67 children and their cumulative preparation budgets, but puts only MCU and
CHR in the first group. The intended solve stops there: **163 regions, 78 total
sectors**. This is a fresh preparation and cannot resume a 49-region checkpoint.
The 17-child Mining sequence is not requested for this probe.

```bash
python scripts/run_disaggregation.py \
  --mapping data/geographies/gtap163.json \
  --cleaning-policy config/cleaning-policy.json \
  --steps config/gtap163-two-sector-steps.json \
  --output build/scalability/my_gtap163/prepared
python scripts/run_model_trial.py \
  --prepared build/scalability/my_gtap163/prepared \
  --output build/scalability/my_gtap163/trial \
  --policy config/model-trials/scalability-commercial.json \
  --stop-after-step "Pilot MCU and CHR"
```

The bounded pilot policy tries KL/MOSEK then quadratic/Gurobi, with the same
common options and independent acceptance checks as the standard policy. It
limits this resource probe to one solver per formulation; open-solver support
and the general entropy-first policy are unchanged. A negative Capital/Labor
prior rejects KL before optimisation, regardless of the solver. Original factor
priors are retained: the separate factor-repair experiment and proposed
parent-based prior recipes are not used.

The native geography re-runs the existing reconciliation rules, so its targets
are geography-specific rather than a disaggregation of the 49-region results.
Preparation trade fitting retains its recorded cleaning-policy solver. Resource
profiling covers preparation separately from the model trial; the initial
profile uses a 10 GiB process-tree RSS stop and a two-hour wall limit per phase.
A resource stop is an incomplete scalability probe, not mathematical
infeasibility or an accepted database. Numerical inputs, logs and profiles are
retained under the ignored local build directory.

### Recorded native probe — resource stop, 21 October 2026

The two-sector probe did **not** produce an accepted database. Preparation
completed, but the trial was stopped while the add-sectors engine was filling
the CHR input slices, before CVXLab optimisation. MOSEK had been selected by the
policy; neither its native optimiser nor the quadratic/Gurobi fallback ran.

| Measurement | Recorded native probe |
| --- | ---: |
| Preparation wall time | 576.2 s |
| Preparation peak sampled RSS | 4.59 GiB |
| Trial wall time to resource stop | 404.2 s |
| Trial peak sampled RSS | 5.27 GiB |
| macOS physical footprint at stop | about 19 GiB |
| macOS physical footprint peak | about 20 GiB |

The RSS-only guard **underestimated compressed/swapped allocations on macOS**.
An additional `vmmap -summary` measurement exposed the footprint and triggered
an external stop of the owned process group. A future macOS guard must include
footprint rather than rely on RSS alone. The raw RSS profiler output, original
interrupted manifests and external-stop record are all retained; the normalised
trial records `failure_category=resource_stopped`. The RSS and footprint figures
are different measures and must not be treated as interchangeable scaling ratios.

The native preparation retained all 67 children and passed cumulative output,
bilateral-trade and producer-export budget checks. Its full workbook contains
10,932 worksheets (10,921 child/region inventories). All **174 original source
files**, the prepared workbook/baseline and the working baseline were verified
unchanged. No factor-prior repair or donor proposal was adopted. The read-only
sign audit finds negative Capital/Labor for active MCU/Brazil; negative
MCU/Lithuania and CHR/Japan coefficient priors occur at zero prepared output.
This input-domain issue remains separate from the resource stop.

Inputs and complete diagnostics were published only under
`Inventories/D2.8 inventories/20261021 2205 - 163 regions and 2 sectors`.
`add_sectors.xlsx` is the exact two-sector compiled input;
`source_add_sectors.xlsx` retains the full preparation and pending plan.
`scalability.md`, JSON summaries, profiles, memory snapshot, source-integrity
checks, compressed preparation audit and reproduction scripts accompany them.
No corresponding database directory or baseline benchmark was created. The
probe establishes a pre-solver memory limitation of this execution, not
mathematical infeasibility or economic validity of a native-region solution.

After publication, the shared XLSX containers received Office metadata additions.
ZIP-member comparison verified byte-identical original model members and
worksheets, with every original relationship retained. The published
`diagnostics/publication-integrity.json` records both hashes and package
differences; `diagnostics/exact-inputs.zip` preserves the original containers
and was verified against their trial hashes. No numerical input was changed.
