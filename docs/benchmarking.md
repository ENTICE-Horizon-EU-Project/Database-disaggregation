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


## Internal cross-database design review — 2026-10-22

This is an internal working design, not a public data release or an implemented
external comparison. Do not include ENTICE data or numerical reports in MARIO's
public documentation. Moving the public Explorer to another repository is a
separate task. MARIO and CVXLab require no model changes for this benchmarking.

### Local 2023 reference inventory

The supplied SSD collection at `/Volumes/SanDisk SSD/Work/IO databases` contains:

| Family | Latest locally available version | 2023 source | Role |
| --- | --- | --- | --- |
| EXIOBASE | 3.11.2 | `EXIOBASE/3.11.2/IOT_2023_ixi.zip` and `IOT_2023_pxp.zip` | Reference; potential future disaggregation target |
| EMERGING | 2.2 | `EMERGING/2.2/EMERGING_V2_2023_m.mat` | Reference |
| GLORIA | 060 | `GLORIA/060/GLORIA_MRIO_Loop060_part_I_MRIOdatabase/GLORIA_MRIOs_60_2023.zip` | Reference |

These are source-file checks, not a new numerical extraction. Keep large original
archives on the SSD. Future source adapters should use configurable local paths
and produce cached, internal comparison profiles, one source at a time.

### One common comparison classification

Build and review an **HS–NACE bridge first**, then aggregate every source to one
common comparison axis. The proposed axis is NACE because it covers services as
well as goods and can serve GTAP, EXIOBASE and FIGARO. Select its revision and
usable detail after a coverage audit; 2023 source definitions commonly use NACE
Rev. 2, while the current Explorer also has reviewed NACE Rev. 2.1 links. Never
silently treat the two revisions as identical.

The official correspondence route can use HS → CPC → ISIC → NACE, or an
appropriate HS/CN → CPA → NACE route. Intermediate classifications support the
bridge; they do not become additional independent benchmark axes. Preserve the
HS edition, native sector identity, path, revision, partial-content flags and
evidence for every mapping. Official starting points:

- [UNSD classification correspondence tables](https://unstats.un.org/unsd/classifications/econ/).
- [Eurostat CPA correspondence tables](https://ec.europa.eu/eurostat/web/cpa/correspondence-tables).
- [Eurostat's method for combining correspondence tables](https://eurostat.github.io/correspondenceTables/articles/CombiningCorrespondenceTables.html).

Reuse Explorer/nxbase evidence rather than maintaining a second generic mapping
by hand. In the inspected MARIO checkout, `doc/classifications/sectoral/` owns
generated snapshots of that evidence: reviewed EXIOBASE monetary activity
correspondences, official ISIC/NACE revision bridges and product links. The
current `sectoral-scope.json` links 161/163 EXIOBASE monetary activities to NACE
and 193/200 products to CPA. It retains all 133 EMERGING 2.2 product categories,
but their detailed CPA links are still unverified. No EMERGING section mapping
was found in the inspected Explorer data on the current checkout or local main.
This does not establish that a bridge cannot be constructed from its source HS
definitions. Do not substitute another EMERGING release's vocabulary.

Existing shared workbooks provide additional evidence, relative to Data split:

- `Classifications/_sources/New sectors classification.xlsx`, sheet
  `New GTAP - HS concordance`: HS versions, new sector code and second/third
  candidate sector columns. Their existence is not proof of an exclusive map.
- `Classifications/_sources/Purdue/GTAP sectors H5.xlsx`, sheets
  `HS_6to5_codes` and `JobID-104_Concordance_H6_to_H5`: HS 2022/2017 links.
- `Classifications/ENTICE classifications.xlsx`: reviewed activity scopes,
  GTAP parents, EXIOBASE bridge and inherited regional memberships. Several
  regional links explicitly say their scope is not certified.

Store HS codes as fixed-length text. A six-digit HS code can span several NACE
activities. The bridge supplies candidate memberships, not economic allocation
weights. When a source cannot resolve those memberships, compare an explicit
larger basket or leave the fine result unavailable. Do not duplicate a full
source total into every linked class or divide it equally. Where NACE groups
several ENTICE technologies together, preserve the fine ENTICE identity and
compare it only with an equally specific source definition; otherwise compare
their common aggregate. Source ixi/pxp/SUT representations and commodity versus
producer interpretations remain explicit even when the display uses one axis.

Regional mapping needs the same discipline: versioned country/territory members,
disjoint groups, no inferred split of a source rest-of-world block, no simultaneous
sum of country and regional totals, and no missing-data-to-zero conversion.
Aggregate flows and denominators first, then calculate coefficients and shares.

### Minimal external comparisons

Start with output, input composition, comparable V components/net final use,
and import/export amounts and partner profiles. Harmonise currency/year,
valuation, factor definitions, geography and the chosen comparison basket before
showing a difference. Accounting V/X in the current GTAP report is not yet a
harmonised value-added measure. EMERGING's single V row cannot support a separate
labor/capital comparison. Environmental comparisons remain deferred until E is
recalculated. Keep provenance indicating whether a reference also supplied a
prior: Purdue's cost-structure material includes EXIOBASE-derived inputs, so
agreement with EXIOBASE may measure source consistency rather than independence.

### Comtrade acquisition

The [official free plan](https://uncomtrade.org/docs/subscriptions/) currently
documents 100,000 records per call and 500 calls/day with a free individual key.
The public preview has a 500-row limit for one period/product. Use a key held in
an environment variable, a throttled client and a local response cache; never
commit a key. An initial anonymous 2023 Brazil/copper-ore request returned HTTP
500, so live retrieval has not yet been validated and no trade values were
accepted from that attempt.

Acquire annual 2023 goods by explicit HS revision, reporter, partner and flow.
Preserve reported exports (normally FOB), imports (normally CIF), mirror flows,
re-exports and observation flags separately. Filter customs/transport/second-
partner dimensions consistently; world totals are controls, not extra bilateral
rows. Detect response truncation and incomplete coverage. After the HS–NACE
bridge and geographic aggregation, Comtrade is the external goods-trade reference;
prepared and reconciled MRIO targets stay separately labelled. Exact agreement
is not expected across valuations or customs/residence boundaries. HS does not
provide a complete service-sector reference.

### Source permissions

Internal storage is the project's default; it is not by itself permission for
every use. This review records terms rather than certifying consortium rights:

- **EXIOBASE 3.11.2:** the supplied `LICENSE.txt` and
  [release record](https://zenodo.org/records/23039074) specify a customised
  noncommercial licence. It excludes some commissioned and for-profit uses,
  limits publication of raw observations/coefficients, and requires prior written
  permission for competing derivative input-output databases. An EXIOBASE-based
  extension and reuse of EXIOBASE-derived priors need specific review before that
  route is implemented or results are distributed.
- **EMERGING 2.2:** the [record](https://zenodo.org/records/19461860) API metadata
  explicitly reports CC BY 4.0, verified on 2026-10-22.
- **GLORIA:** the existing MARIO licence record identifies CC BY-NC 3.0 Australia
  and the publisher's noncommercial-use statement. Verify the applicable 060
  source notice and consortium use before any distribution. Its MARIO-browser
  review is not blanket permission for ENTICE applications.
- **Comtrade:** the [use policy](https://uncomtrade.org/docs/policy-on-comtrade-data-use/)
  permits internal use and joint-project sharing under stated conditions;
  public redistribution has separate conditions.

### Future disaggregation targets

The target families are **GTAP, EXIOBASE and FIGARO**. This differs from the
reference set EXIOBASE, EMERGING and GLORIA. Keep the sector identities, source
inventories and reviewed HS–NACE bridge common. Add a baseline adapter per target
for native sectors, units, valuation, geography, parent budgets and V definitions.
For each proposed child, record whether it already exists with matching scope,
requires splitting one parent, spans multiple parents, or lacks enough evidence.
Reuse an existing native sector without inserting a duplicate. Do not transplant
GTAP parent shares or donor coefficients into another baseline unchanged.

First validate the bridge on a small, reviewed sector basket and a common
geography; then add cached external profiles and comparison columns. Full
cross-database adapters and new economic calculations are not implemented here.

## Build the internal 2023 mapping bundle

```bash
pip install -e '.[mappings]'
python scripts/build_reference_mappings.py
```

The `benchmarking` section in `paths.local.json` selects `reference_root` (the
local SSD collection), `source_dir` (the small official correspondence cache),
and `mapping_output`. Relative source/output paths resolve against `data_root`.
The existing `mario_source` supplies Explorer classification metadata. All four
locations can also be passed as command-line arguments. Copy the shared
`sources/` cache when preparing a separate installation; it includes the original
official files and their URL list. No API key or economic database download is
needed for this metadata workflow.

The command builds in a temporary directory, verifies metadata hashes and
generated artifacts, and publishes the complete internal package with its
manifest last. Existing generated results require `--overwrite`. The default
requires the SSD and directly verifies the native EXIOBASE unit tables, EMERGING
MATLAB sector/country lists, and GLORIA release metadata and 2023 archive identity.
It never reads the numerical transaction matrices. `--allow-explorer-cache`
explicitly permits a provisional build when the SSD is offline; the report then
marks direct source verification as pending.

The common reference is **NACE Rev. 2**. Official UNSD HS/CPC/ISIC and NACE
correspondences retain partial flags and all revision paths (HS 2002, 2012, 2017
and 2022). Correlation sheets are used instead of one-destination conversion
sheets. A mapping footprint never supplies an economic allocation weight.
`data/benchmarking/sector_scopes.json` records the separate editorial reviews of
EMERGING descriptors, supplementary ENTICE scope containment and specific native
candidates. It does not modify the operational sector registry.

The shared output `Classifications/Benchmark mappings/2023/README.md` explains
the concrete coverage, fine-sector candidates, HS inconsistencies, historical
region codes, territorial differences and ENTICE13 compatibility. CSV files are
for review; `mapping-package.json` retains evidence routes, source metadata and
artifact checksums. `verify_artifacts(folder)` rejects changed or incomplete
generated files before downstream use. This classification audit does not
certify monetary, price or product/industry equivalence.

Validation: `python -m pytest tests/test_reference_mapping.py -q`.

## Numerical 2023 references in the internal dashboard

The existing final **13-region, 143-total-sector checkpoint (67 new sectors)**
can now be compared with EXIOBASE 3.11.2 (industry IOT), EMERGING 2.2 and GLORIA
060 for 2023. The EXIOBASE industry representation retains separate primary and
secondary production activities useful for ENTICE; the product representation
is not additionally included in this first numerical version. This is post-processing of saved data: it does not run the model,
change input observations, reconcile targets or balance any source database.
The numerical outputs remain in shared Data split storage, outside Git.

Install the benchmark and mapping extras in the existing MARIO environment:

```bash
pip install -e '.[benchmark,mappings]'
```

Set `benchmarking.reference_root` to the directory containing `EXIOBASE/`,
`EMERGING/` and `GLORIA/`; set `mario_source` to the local MARIO checkout. The
mapping directory defaults to `Classifications/Benchmark mappings/2023` under
`data_root`. Paths are read from the same `paths.local.json` / `ENTICE_CONFIG`
used by the pipeline. Explicit `--reference-root`, `--mapping-dir`,
`--mario-source`, `--baskets` and `--output` overrides are supported.

Starting from an existing `benchmarking.json` with the exact baseline recorded:

```bash
python scripts/benchmark_references.py \
  --database 'Database/D2.8/20261021 0655 - 13 regions and 67 sectors' \
  --overwrite
```

This adds the **Reference databases · 2023** tab to `benchmarking.html`, retains
all original baseline comparisons, and saves a small `reference-benchmarks/`
folder beside it. That folder contains reusable native profiles, comparison
JSON/CSV, and source provenance. `--overwrite` replaces only the generated
benchmark files; source `flows/` are verified by SHA-256 before and after.
Read the dashboard locally: it is self-contained, has no network calls, and is
for internal use. Do not publish its data or HTML with the repository/site.

### What is compared

Five indicators are retained: gross output in million USD, intermediate inputs
/ output, imported intermediate inputs / total intermediate inputs, signed net
final demand / output, and foreign deliveries / output. Foreign deliveries are
Z + Y outside the selected common region, after geographical aggregation.
Counterpart regions outside the comparison panel remain in the denominator and
foreign totals; they are never dropped. Input composition uses nine broad NACE
section groups plus a visible **Mixed / unmapped** group. Whole source sectors
that span multiple groups remain mixed; there are no equal splits or inferred
allocation weights. Ratios are calculated after summing amounts. A denominator
at or below one USD is unavailable, not zero.

`data/benchmarking/comparison_baskets.json` defines whole-sector baskets with
expected source descriptors, ENTICE parent/child contents, NACE reference and
qualifications. Seven aggregates plus the whole economy cover all 67 inserted
sectors; 12 targets also have specific native descriptor comparisons in at least
one source. Aggregating an ENTICE parent means **its saved residual row plus all
inserted children**, rather than adding just the children or discarding the
residual. Fine child comparisons show the wider baseline parent only as context.
Baskets overlap; their totals must not be added.

For the first version, source-specific compatible geography is:

| Reference | ENTICE regions with the same declared country membership |
| --- | --- |
| EXIOBASE | India, USA, Russia |
| EMERGING | Oceania, China, Rest of Asia, India, Rest of North America, USA, Russia, Middle East, Africa, Rest of the World |
| GLORIA | China, India, USA, Russia, Middle East |

Thus India, USA and Russia can be compared with all three sources. China includes
Hong Kong in this ENTICE aggregation. Country membership and source region codes
are exposed in the dashboard. EU27 and other unmatched regional scopes are not
approximated by splitting a native ROW. Country comparisons below the saved
13-region resolution require a different existing checkpoint, not an invented
country disaggregation of this one.

### Accounting and interpretation

- **EXIOBASE:** original industry IOT, supplying rows / purchasing columns,
  million EUR. Multiply amounts by the verified 2023 annual ECB USD/EUR average,
  `1.081268627451`; the basket configuration records the official API URL and
  response checksum. This aligns currencies, not valuation conventions.
- **EMERGING:** native million USD, with Z transposed from its MATLAB storage.
  HDF5 supplying-column strips are read once, matching MARIO's parser orientation
  and avoiding a dense 32,585 × 32,585 global allocation. Raw label order is
  checked against the frozen mapping vocabulary, including serial 096 at the end.
- **GLORIA:** the original is an MR-SUT in **thousands USD**. A product IOT is
  derived with the standard industry-technology algebra
  `Zp = U diag(X_activity)^-1 S`, where S has activity rows and commodity columns.
  No balancing or optimisation is involved. Two streamed passes over basic-price
  T build sparse supply shares and aggregate U products; commodity Y is retained.
  Output is the sum of S over producing activities, not S + U. Multiply native
  amounts by 0.001 to obtain million USD. Unsupported same-type T blocks and
  activity-row Y must be zero; zero-output activity inputs are audited explicitly.

The scalar and input-structure indicators therefore have consistent arithmetic,
but native valuation, source construction, product/activity boundaries and
coverage still differ. The dashboard shows scope qualifications, whole native
components, accounting residuals and source hashes. EMERGING HS-based baskets
with unavoidable activity/product differences are marked **contextual scope**.
Detailed EMERGING/GLORIA NACE footprints include editorial reviews and should not
be read as publisher-certified equivalences. Existing HS scope conflicts (MIO,
PCP, RBR) are retained and surfaced; the benchmarking code does not repair them.
No automatic pass/fail threshold is assigned to gaps between databases.

V / value added is excluded from these external indicators until its tax,
margin, income and depreciation components are harmonised. E remains pending.
These IO foreign-delivery comparisons do not replace Comtrade customs validation.

Verification covers geographical aggregation before computing trade shares,
signed demand and currency conversion, native EMERGING orientation, and an
independent small dense SUT-to-IOT calculation for GLORIA. The existing baseline
benchmark tests and a real offline-browser check also remain applicable.


## 61-region saved result

The 29 October 2026 refresh benchmarks
`Database/D2.8/20261028 1754 - 61 regions and 52 sectors` without running MARIO
or CVXLab optimisation. It uses that directory's **own `baseline/`**, not the
13-region baseline or an unrelated D2.4 result. The matrices have 61 regions,
128 total sectors and 52 actually separated activities. All 69 planned activities
were attempted; 17 still belong to their original parents.

The benchmark reads reversible `residual_index_renames` to recover stable
computational codes while keeping readable residual/coal/petroleum names in
the dashboard. Factor and final-demand category names are preserved. Child
membership comes from `completed_sectors`, not the larger planned dictionary.
Exact output and selected trade targets are read from the archived input for
each **accepted** step in `diagnostics/exact-inputs.zip`. Failed steps do not
become standalone observations; later remapping is not mistaken for the original
input to an earlier step.

`report_only` preserves all strict comparisons and their measured residuals.
Deviations in monetary conservation, accounting or target adherence are REVIEW,
not automatic rejection. Source checksums, axis coverage, finite values, exact
unchanged EY/VY and target completeness remain checked. This policy neither
repairs matrices nor establishes economic validity. Leontief diagnostics were
not recomputed for this refresh; the five principal indicators do not require
them.

Geography is constructed from the existing native GTAP-to-model map and explicit
GTAP country/territory membership in the reviewed mapping package. The map must
cover the exact native GTAP universe and reproduce the saved checkpoint's region
set. An incomplete GTAP membership cannot be called exact, even if its known
members happen to match. Whole native source regions are then selected:

| Source | Compatible ENTICE regions out of 61 |
| --- | ---: |
| EXIOBASE 3.11.2 industry IOT, 2023 | 38 |
| EMERGING 2.2, 2023 | 58 |
| GLORIA 060, 2023 | 52 |

The complete inclusion/exclusion audit is saved as
`reference-benchmarks/geography-compatibility.json` and embedded in the dashboard.
All counterpart regions remain in import/export calculations. No native ROW is
split or imputed. Broad sector baskets include residuals plus **all actual**
children. A fine basket requiring an activity that was not separated is omitted
and listed as unavailable. BAR and SGI have no reviewed footprint in the frozen
mapping package: their supplier contributions remain Mixed / unmapped rather
than receiving an invented fine NACE allocation.

Commands, from this worktree with the existing MARIO Python environment and
`PYTHONPATH=src` (paths below are relative to configured Data split):

```bash
python scripts/benchmark_database.py \
  --database 'Database/D2.8/20261028 1754 - 61 regions and 52 sectors' \
  --baseline 'Database/D2.8/20261028 1754 - 61 regions and 52 sectors/baseline' \
  --skip-system --overwrite

python scripts/benchmark_references.py \
  --database 'Database/D2.8/20261028 1754 - 61 regions and 52 sectors' \
  --region-map 'Classifications/GTAP model regions/gtap-models-compatible.json' \
  --mapping-dir 'Database/D2.8/20261028 1754 - 61 regions and 52 sectors/reference-benchmarks/mapping-snapshot' \
  --overwrite
```

The mapping snapshot records a source revalidation: the local HS2022/2017 Excel
file no longer had its original byte checksum. Recomputing all **78,709** saved
HS–NACE routes produced exactly the same records, including qualifications and
revision row numbers; its correlation rows also matched a fresh official UNSD
download. Every other artifact matched its original hash. The original mapping
package was left untouched; the case-specific snapshot stores the new hashes,
official evidence and `revalidation/verification.json`. Source Excel workbooks
are preserved inside `source-spreadsheets.zip`: SharePoint rewrites custom XML
and document properties on uploaded Excel copies, so hashing those loose copies
is not a stable source identity. Their correlation rows were verified unchanged.
This was a source audit, not a change to NACE footprints or an economic allocation.

Reference profiles are streamed and cached beside the result. Cache identity
includes source path/size/mtime, extraction code, supplier groups and target
geography. Every cache retains the full source SHA-256 and extraction audits.
Reusing a cache is not evidence of a new SSD read; changing geography or code
requires extraction again. No reference matrix or benchmark is published online.


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
