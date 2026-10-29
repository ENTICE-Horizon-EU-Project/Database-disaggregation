# Benchmarking saved monetary MRIO databases

The active experimental branches provide an **offline, read-only dashboard**
for saved monetary MRIO results. The current 61-region result has 128 total
sectors (76 original sectors/residuals plus 52 added activities); its baseline
has 76 sectors at the same geography. The earlier 13-region and 49-region
results are retained separately. Every database dashboard uses the same MARIO
workshop template.

This is post-processing: it imports no MARIO/CVXLab/optimisation solver and does
not run the disaggregation, balance flows, reconcile targets or recalculate E.
Keep the numerical dashboard, JSON and CSV in the shared Data split storage.
The repository contains code, methodology and synthetic tests only.


## Standard dashboard format

All generated **database dashboards** use the MARIO workshop layout, including
the existing 13-region result, both 49-region pilots and the 61-region result.
The same packaged templates and renderer are used by `reporting.write_dashboard`
in notebooks and by `benchmark_database.py` / `benchmark_references.py` for saved
results. The renderer is available on `codex/notebook-api`,
`codex/configurable-regions` and `codex/mrio-memory`; no MARIO or CVXLab model
change is involved.

The shared interface has two views:

1. **Results:** sector selector and new/residual/original status; production and
   available prepared output targets; Sankey or signed trade matrix; destination
   use shares across using sectors and **all native final-demand categories**.
   Both views include all Z + Y, including investment, stocks and margins.
   Production labels are vertical. Origin/destination checkbox dropdowns filter
   only the trade chart (Sankey and matrix), retain the chosen regions when the
   sector changes, and provide search, select-all and clear controls. Missing consumers stay grey
   and undefined denominators stay unavailable. Large regional cases get a wider
   scrollable heatmap and enough vertical space for Sankey labels.
2. **Cross-database comparison:** the existing five KPIs, baseline and all
   available reference sources, broad input structure, trade shares, explicit
   sector scope and CSV export. The tab is hidden when no references were saved;
   no source comparison is invented from an unrelated geography.

The numerical baseline audit, strict residuals and source context remain in an
expandable section. Full KPIs, screening findings and reference audits remain
in their JSON/CSV sidecars. This changes presentation, not the model, database,
saved baseline indicators or reference values. E stays outside this dashboard.

To refresh existing reports without recomputing the numerical benchmark or
reading an external source database:

```bash
pip install -e '.[benchmark]'
python scripts/refresh_dashboards.py --all --overwrite

# Or refresh just one saved database:
python scripts/refresh_dashboards.py \
  --database 'Database/D2.8/20261028 1754 - 61 regions and 52 sectors' \
  --overwrite
```

Paths use the usual `paths.local.json` / `ENTICE_DATA_ROOT`. Existing monetary
matrices must be locally readable (OneDrive can need time to download older
placeholders). The external SSD is unnecessary: external profiles are already
saved in each benchmark JSON. Source datasets, matrices and baseline are never
rewritten. Cached per-sector targets, or exact step inputs already archived
with the result, supply the production markers. A legacy report without this
sector-level cache keeps its original audit and displays no inferred target.
`--all` touches only directories containing a saved `benchmarking.json`; it does
not attempt a model run or manufacture a benchmark for every checkpoint.

The original workshop HTML is a reference artifact and is left unchanged.
Source-data browsing and solver-comparison reports have different purposes and
are separate from these database dashboards. All outputs remain internal and
offline, with Plotly, logos and numerical chart data embedded in one HTML file.

## Run

```bash
pip install -e '.[benchmark]'
python scripts/benchmark_database.py \
  --database 'Database/D2.8/20261021 0655 - 13 regions and 67 sectors' \
  --baseline 'Database/_GTAP Power 2023/ENTICE13 baseline'
```

Relative paths resolve against `data_root` in the usual `paths.local.json`
configuration (or `ENTICE_DATA_ROOT`). Explicit absolute paths are also accepted.
Both database arguments are required; the script never guesses the latest run.
It writes three files directly beside the final database:

- `benchmarking.html`: self-contained interactive dashboard, with embedded data;
  open in a browser, including offline. No web server, CDN, external fonts or
  online accounts are needed. SharePoint's preview may not execute HTML: open
  the synchronised/downloaded file in a browser.
- `benchmarking.json`: full KPIs, checks, screening findings and input hashes.
- `benchmarking-sectors.csv`: scalar KPIs for every sector-region pair. Baseline
  parent indices/outputs are explicit; detailed factor/demand/route arrays are
  in the JSON and dashboard.

`--output` chooses another HTML filename, with matching JSON and CSV stems.
Existing report files are protected unless `--overwrite` is supplied. Output
inside source `flows/` is rejected. `--skip-system` skips Leontief linear algebra
and explicitly marks those diagnostics as not computed. Exit code 2 means a
hard benchmark check failed; review flags alone do not cause failure.

The published `ENTICE13 baseline` is a byte-for-byte copy of the original
accepted Mining trial's pre-split baseline. `baseline_provenance.json` records
its source and original hashes. The copy requires no model or geography rerun.
Do not substitute the D2.4 `split=False` database, the 163-region cache or a
preceding 17/49-child checkpoint for this comparison.

## Dashboard views

The current interface is the **standard MARIO workshop format** described above.
Numerical results remain for **internal ENTICE use** and must not be copied to
MARIO's public Explorer or a public documentation build. The detailed indicators
and numerical methodology below describe the retained JSON/CSV audits; they do
not imply that every metric needs a separate panel in the simplified interface.
External comparisons, where already saved, remain attached. Comtrade customs
validation is separate and is not populated by a presentation refresh.

## Hard checks

All monetary flows must be finite; labels must be unique and align explicitly;
the geography and child-parent map must match. Sector/factor units must be M USD.
Final checkpoint files are verified against `state.json`. Baseline provenance
hashes are verified when present. Source hashes are checked again at the end;
an input change aborts publication.

- Reaggregate children **and the remaining original parent** to the baseline.
  Aggregate both axes of Z, the rows of Y/X and the columns of V. Compare EY and
  VY unchanged, without adding unlike environmental units together.
- Read **authoritative X from X.parquet**. A generic flow parser that recomputes
  X from row sums would erase inherited discrepancies and invalidate this test.
- Row discrepancy: `sum(Z row) + sum(Y row) - X`. Column discrepancy:
  `sum(Z column) + sum(V column) - X`. For `accounting="inherit"`, the expected
  final discrepancy is the original parent's discrepancy times `X_child/X_parent`.
- Monetary comparisons use `1e-6 + 1e-8 * abs(reference)` M USD per cell, matching
  the accepted checkpoint. EY/VY are unchanged exactly. Z values below −1 USD
  per cell fail the nonnegativity check. Gross sums can exceed 1 USD despite
  every constituent cell falling within tolerance; both views are reported.
- Traverse the published run's predecessor chain and inspect only each stage's
  applied `step_sectors` in its paired `step_add_sectors.xlsx` (falling back to
  `add_sectors.xlsx` for legacy incremental packages). Recheck every listed
  output and bilateral trade observation, including explicit zero targets.
  Unlisted routes are unobserved, not zero. Target adherence concerns the
  **prepared** data and is not independent validation. A missing published chain
  is marked unavailable; incomplete child-output coverage in an available
  chain fails a hard check.

This first version deliberately requires the saved `accounting="inherit"`
policy and the above tolerances. Other policies need their own explicit audits.

## Economic indicators and screening

The reference for a fine sector is its **original parent in the baseline**, not
the parent's remaining residual in the final database. Intermediate input
coefficients use `Z_ij/X_j`; supplier rows are summed over all origins and
mapped to original sectors. Technology distance is the L1 sum of differences
between the two complete coefficient vectors; the dashboard plots the 12 largest
input coefficients across the two profiles. Input import share divides foreign
intermediate inputs by all intermediate inputs; export propensity divides
foreign Z+Y deliveries by X. Export HHI uses positive foreign deliveries only.
Final demand categories sum over destinations and retain their signs. Factor
shares, net Y/X and gross positive/negative Y are available separately.

There is no universal “good share” constraint or composite quality score.
Transparent first screening rules are:

- negative labor or capital beyond 1 USD, with the baseline parent's sign;
- remaining gross Z/Y/V flows beyond 1 USD when X is at most 1 USD;
- exhausted parent residuals where the baseline parent had material output;
- V/X, exports/X, input import share or Y/X differing by >25 percentage points
  from the baseline parent.

These thresholds select cases to inspect; they are **not empirical acceptance
tests**. Ratios for denominators ≤1 USD remain null. The output filter helps
separate tiny sectors from material results. Negative taxes and margins are
reported, without being automatically interpreted as errors.

## Leontief diagnostics

Build `A = Z / X` by column and solve `(I-A)^T m = 1` by LU for the
column-sum output multipliers, without optimisation. Report the spectral radius,
a 1-norm condition estimate, multipliers and their linear solve residual. Tiny signed Z values remain in A.
X≤1 USD rows/columns are excluded; report their gross input and output flows.
**Material excluded inputs make the resulting multipliers conditional on that
exclusion** and require review even when the matrix is numerically stable.

The dashboard does not simulate hypothetical final demand shocks. Stability
and multiplier distributions remain descriptive comparisons; fine and coarse
sector universes differ, so those distributions need not coincide.

## Limits and next steps

E/energy/emission intensities and footprints are unavailable until recalculation.
Prepared-prior adherence, model sensitivity, sequential-order sensitivity,
external/held-out observations and the full raw→prepared harmonisation chain
are separate work. The current route-level adjustment view covers the recorded
final row-feasibility projection only. This report does not certify full MRIO
economic plausibility merely because the hard accounting tests pass.

## Verification

```bash
python -m pytest tests/test_benchmark.py -q
```

Synthetic tests cover two-axis aggregation, independent X, inherited accounting,
multipliers against a direct inverse, undefined ratios/gross signed flows,
new negative labor despite exact conservation, hash/non-finite/mapping failures,
offline export and source/overwrite protection. Browser verification of the
generated report should cover tab navigation, filters, sector drill-down, trade
views, system diagnostics and review exports before sharing a new template version.

An optional DOM smoke test exercises those interactions on a synthetic exported
fixture, including JSON/CSV downloads. It is not a visual browser/layout test:

```bash
npm install --prefix /tmp/benchmark-dom --no-audit --no-fund jsdom@26.1.0
NODE_PATH=/tmp/benchmark-dom/node_modules ENTICE_BENCHMARK_DOM_TEST=1 \
  python -m pytest tests/test_benchmark.py -q
```


### Complete use shares and regional trade filters (29 October 2026)

The default `analysis.use_profile` includes every category in Y. Households,
government and NPISH retain their familiar grouping; all other native categories
are appended without imputation or omission. An explicit `final_demand` mapping
still permits a deliberately selected subset. Default destination totals equal
the column totals of the complete Z + Y trade matrix after summing origins.
Signed values are retained; nonpositive or at-most-1-USD denominators remain
undefined. Every negative use share is on the red side of the colour scale,
including residuals below 1 USD. Nothing is clipped or set to zero.

The two regional multi-select dropdowns affect only the deliveries chart, in
either Sankey or matrix mode. They retain exact selected-route values and keep
the same selection across sector changes. The use heatmap and database KPIs
continue to cover their full declared scope. Empty selections show an explicit
message rather than a stale chart. The Sankey shows positive flows; signed
routes remain available in the matrix.
