# Reproducibility and handoff requirements

The deliverable is an executable process that another researcher can run from
the initial inputs to the final database. A collection of manually adjusted
experiments and their logs does not meet this requirement.

## Release contract

- Provide one documented entry point covering preparation, regional aggregation,
  reconciliation, insertion planning, sector addition, validation, exports and
  the final report. Internal stages can remain separate reusable functions.
- The operator supplies input locations, the regional classification/case and
  an output location. Document data access, solver licences, software and memory
  prerequisites before execution. Model or solver tuning must not be an
  additional operating step.
- Freeze the model, objective, weights, prior rules, accounting/sign conventions,
  numerical cleanup and solver configuration in versioned release settings.
  Apply these settings consistently across sectors. Alternative research models
  may remain available as explicitly selected cases.
- If a numerical retry is retained, define its native solver-status trigger,
  settings, maximum attempts and position in the sequence in advance. Apply the
  same rule to every eligible sector. Do not create a special exception for MGC
  or select a new parameter value after inspecting an individual outcome.
- Freeze reconciliation rules, reliability weights and missing-data assumptions.
  Preserve original observations and audit every transformation, including
  explicit fitted trade zeros. Do not manually repair a workbook or final
  matrix outside the pipeline to make a sector pass.
- Define sector ordering and tie-breaking reproducibly. Project pending or
  failed children onto the actual residual parents automatically. Report actual
  completed and failed sectors and the resulting classification. Completion
  of the process must not imply that every requested child was feasible.
- Save input identities, exact effective settings, dependency/code versions,
  the executed plan, all attempts, effective constraints and checks. Checkpoint
  resumption must preserve the same declared procedure and previous inputs.
- Publish executable code with pinned compatible repository versions and an
  environment specification. Saved diffs and private temporary scripts are
  useful research evidence; they are not the release installation procedure.

## Acceptance test

After selecting the final procedure, run it once from the initial inputs in a
clean output directory, through the documented entry point and supported
environment, without using experimental checkpoints or making manual edits.
Verify completed/failed sector coverage, production and trade constraints,
accounting and reaggregation, reported numerical discrepancies and output
classification. Check that the generated package includes the inputs and
reports needed to explain the result. Record any deferred calculation, such as E.

This full replay is an acceptance check of the selected release procedure,
not an invitation to keep searching model/solver combinations until one passes.
Do not claim handoff readiness before it succeeds.

## Current experimental status — 23 November 2026

The conservative-prior 61-region build and its numerical recovery are research
runs. The sequential runner integrates per-step pending-sibling trade
reconciliation and can resume verified checkpoints. Preparation, continuation,
publication and the operational recovery queue are not yet one frozen release
entry point.

The original pass accepted 58 children. A controlled MGC trial then returned
optimal with Gurobi primal simplex (Method=0), NumericFocus=3 and a 900-second
cap: 59 children, 135 total sectors. Its 24 generated CSV inputs and mathematical
model files matched the unsuccessful barrier trial exactly; a longer cap alone
had not fixed that earlier native SUBOPTIMAL termination.

The recovery completed all 69 requested children: 145 total sectors and 61
regions. PLSR was accepted through MARIO/CVXLab after Gurobi returned OPTIMAL
with Presolve=0 in 5807.08 native seconds. Its 24 generated CSV inputs and native
compiled mathematical fingerprint (0xf1414c58) matched the default-presolve
attempt. Objective, constraints and solver tolerances were unchanged; CVXLab
was not edited. The first recovery used a common 1800-second primal
simplex cap. Its queued TIME_LIMIT-only continuation was cancelled when the run
stopped before PLSR's solver. Subsequent remaining-sector continuations use a
common 7200-second preset, while identified input-preparation inconsistencies
are corrected generically and audited: inherited export capacity, numerical
row scaling, exact zero support, sub-precision single-child budget excesses and
uniquely determined foreign deliveries. This is research history, not a claim
that a larger time cap alone fixed the failed sectors.

All accepted MRIO solves still use the same quadratic formulation. Native
solver outcomes and separate bounded diagnostics are retained. No non-optimal
diagnostic point was substituted for an accepted MARIO/CVXLab result. Exact
settings, scenario changes and all attempts are part of the research package.
The database is the postprocessed point, not a new optimality certificate after
cleanup. Against the original baseline, the largest reaggregated Z difference
is about 2997.10 USD; the largest change in inherited column accounting is
63269.73 USD (DEU/RPP, approximately 0.0001506% of its 42.02 billion USD output).
These are diagnostic results under the agreed report-only policy, not a strict
accounting or economic-validation pass. E remains deferred.

Structural production-support review is also required. Examples include
zero-output ZAF/PLSR with about 14.984 million USD intermediate inputs offset by
negative TTM/Tax, and zero-output SSA/OXT with 2.648 billion USD Capital offset by
negative TTM/Tax. Some are inherited from earlier checkpoints; tiny positive
prepared outputs also need support review. Ordinary per-unit coefficients
require consistent treatment of these accounts. The 69-child solve completion
does not close this structural validation issue. Review MARIO's support/prior
allocation and the pipeline's preservation of production zeros before the clean
replay; CVXLab needs no new solver capability for these masks.

A deferred attempt starts from the latest accepted database and repeats the
existing pending-sibling trade reconciliation. Because intervening insertions
change the checkpoint, it is not a controlled test of the time cap alone.
Select and integrate the final common configuration or bounded retry rule, then
perform the clean full replay required above before claiming handoff readiness.
Do not silently replace published research outputs with a different procedure.

## Archive the observed execution

A finished local sequential build can retain its exact accepted history without
copying complete intermediate database matrices:

```bash
python scripts/archive_sequential_history.py \
  --run /path/to/finished/sequential-build \
  --output /path/to/accepted-history.zip
```

Repeat `--additional-run /path/to/recovery` to include failed-only research
batches too. The script follows accepted checkpoint history, prefers the
checksum-verified executed full input over readable Excel re-exports, and keeps
compiled steps, state files, available raw/cleaned solver diagnostics and batch
code snapshots. Raw active-variable arrays are diagnostics; complete checkpoint
database matrices and SQLite caches are not duplicated. Missing required
historical inputs are errors. Every archived file is read back and hash-checked
before the temporary ZIP becomes the requested output. Sources are never edited
and no optimization is run. Licence identifiers are redacted from copied logs.

The 69-child research archive contains 1593 verified files (approximately
3.71 GB), including all 69 accepted steps. Keep this once in the paired
database's `reproducibility/accepted-history.zip`, alongside the original
baseline and final result. It is historical evidence, not a replacement for the
clean-replay release check above.

Related guides: [conservative priors and sequential execution](conservative-priors.md),
[data reconciliation](reconciliation.md), and
[path/environment setup](../README.md#getting-started).
