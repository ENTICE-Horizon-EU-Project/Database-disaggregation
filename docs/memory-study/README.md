# Bounded MRIO memory study

This experiment lives on the **local** `codex/mrio-memory` branches of MARIO,
CVXLab and Database disaggregation. It preserves the current economic model.
No new KL database was accepted. See the Italian reports:

- [Implementation changes](changes-it.md)
- [Results, limitations and RAM estimates](results-it.md)

The two real model solves used CHR at 13 regions, KL/MOSEK and identical inputs:
one with the preceding code and one with the first memory revision. Both failed
the independent numerical acceptance checks. Later 49/163-region runs only
profiled preparation; they never called a solver. Native profiling stopped at
the 10 GiB footprint threshold, including after one targeted workbook-reader fix.
Do not interpret a successful preparation as a solved database.

## Reproducing a preparation profile

Use an already reconciled preparation and a fresh output directory. Preserve
all original input files. Select these three worktrees explicitly; an editable
installation may otherwise import another MARIO branch or installed CVXLab.

```bash
export MARIO_SOURCE="/path/to/MARIO/.worktrees/mrio-memory"
export CVXLAB_SOURCE="/path/to/cvxlab/.worktrees/mrio-memory"
export PYTHONPATH="$MARIO_SOURCE:$CVXLAB_SOURCE:$PWD/src"
export OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 VECLIB_MAXIMUM_THREADS=2
python scripts/prepare_memory_probe.py \
  --source /path/to/existing/preparation \
  --output build/memory-study/my-probe/prepared \
  --sectors CHR
python scripts/profile_model_command.py \
  --record build/memory-study/my-probe/resources.json \
  --log build/memory-study/my-probe/preparation.log \
  --footprint-limit-gib 10 --rss-limit-gib 10 \
  --disk-reserve-gib 8 --wall-limit-seconds 2400 \
  -- python scripts/profile_split_preparation.py \
  --prepared build/memory-study/my-probe/prepared \
  --output build/memory-study/my-probe/profile \
  --options config/model-trials/memory-kl.json
```

The preparation observer runs the normal intermediate-step API and constructs
CVXLab's numerical problems. It deliberately exits before affine feasibility,
solver canonicalisation, optimisation and reconstruction. Its authoritative status
is `prepared_only` in `preparation_profile.json`; the temporary MARIO step can
also contain `failure.json` for that deliberate interruption. It never publishes
a database. The resource monitor needs OS permission to inspect its child and
fails closed if measurement is unavailable.

For an explicitly authorised real solve, `run_model_trial.py --options
config/model-trials/memory-kl.json --solver MOSEK --solver-options
config/model-trials/memory-mosek.json` selects one fixed KL attempt, bypassing the
ordinary policy's quadratic fallback. This study did not run further real solves
after reproducing the 13-region numerical failure. Reconsider numerical acceptance
before scaling the solver.

Raw workspaces and profiles are ignored under `build/memory-study/`. The reports
identify the shared diagnostic package with exact inputs, baseline snapshots,
hashes, patches and commands. Existing successful databases were not replaced.


## Subsequent controlled KL trial — 23 October 2026

The separately authorised [prior-filter and reference-floor experiment](../kl-prior-floor.md)
uses the same CHR13 preparation, one KL/MOSEK attempt and unchanged CVXLab sources.
It adds an opt-in prior-only threshold and maximum-based support, preserving
baseline and targets. The native solver again reports optimal, but independent
checks reject the point. See that report for the numerical comparison and exact
input/diagnostic package. The historical memory-study results above are unchanged.

## Update: bounded KL result cleanup (23 October)

CHR13 now has an accepted approximate result using explicit numerical cleanup.
The same budget rejected the CHR49 result (8.70 GiB footprint, one new sector).
See [the complete report](../kl-solution-cleanup.md); this does not replace the
historical strict failures or certify the full 163-region/67-sector case.

## Update: saved-point post-processing (23 October)

The existing optimal CHR49 point now produces a database after sign cleanup,
with monetary residuals recorded for economic review and no dollar cutoff.
No optimizer was rerun. See [the current report](../kl-postprocessing.md).
The original 8.70 GiB remains the observed footprint for the one-sector solve;
the reconstruction footprint is a separate measurement.
