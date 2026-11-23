# Saved database exports

These commands read an existing accepted checkpoint. They do not run preparation,
MARIO, CVXLab or an optimisation solver, and they do not rebalance the saved flows.

## GDX

```bash
PYTHONPATH=src python scripts/export_saved_gdx.py --database /path/to/saved/database
```

If necessary, pass `--system-directory /path/to/GAMS`. An installed GAMS Python
API and runtime are required; no optimisation licence is used. Existing exports
are protected unless `--overwrite` is specified.

The output is `database.gdx`, with `database.gdx.json` recording checksums and
verification. This is the **MARIO flow schema**, not a reconstruction of GTAP's
original tax, domestic/imported-use or valuation symbols:

| Symbol | Dimensions | Meaning |
|---|---|---|
| `Z` | `r,s,rr,ss` | Intermediate deliveries from origin region/sector to destination region/sector |
| `Y` | `r,s,rr,d` | Deliveries to final demand |
| `V` | `f,rr,ss` | Value added by factor |
| `X` | `r,s` | Saved production, read independently of Z and Y |
| `E` | `sat,rr,ss` | Satellite flows, only when recalculation is complete |
| `EY` | `sat,rr,d` | Final-demand satellite flows as stored |
| `VY` | `f,rr,d` | Value added associated with final demand |

`r`/`rr` are regions, `s`/`ss` sectors, `d` final-demand categories, `f` factors,
and `sat` satellite accounts. The second regional and sectoral domains are GAMS
aliases. Monetary flows retain M USD; unit mappings accompany sector, factor and
satellite sets. `new_sector`, `residual_parent` and `sector_parent` describe the
accepted disaggregation.

Only exact zeros are omitted from GDX records. Negative values and tiny nonzero
values are preserved. Every exported matrix is read back and compared with **all
source cells**, with no numerical tolerance, before the GDX is published.

The pending status of E is explicit in `satellite_recalculation_pending`.
Pending E is **omitted** from GDX and identified in `omitted_symbols` in the
verification sidecar; its source file is left unchanged. Completed satellite
arrays are exported as stored, without recalculation. `coefficient_analysis_validated=0` means this export is
not certification of coefficient or multiplier analyses. The saved numerical and
economic limitations continue to apply.

## Dashboard and cached reference comparisons

```bash
PYTHONPATH=src python scripts/refresh_saved_dashboard.py \
  --database /path/to/saved/database \
  --baseline /path/to/saved/unsplit/baseline \
  --cached-references /path/to/previous/reference-benchmarks \
  --geography /path/to/native-to-target.json \
  --region-names /path/to/regions.csv \
  --mario-source /path/to/MARIO
```

`--baseline` is optional when the baseline is already at `DATABASE/baseline`.
The region-name CSV must cover the exact region codes and native memberships.
Accepted constraints can be recovered from legacy step archives or the cumulative
`reproducibility/accepted-history.zip`. The latter keeps immutable source inputs
and readable compiled snapshots, identified separately in constraint provenance.

The dashboard is `benchmarking.html`, a standalone internal HTML file. External
2023 profiles and concordance files must match their recorded checksums. Only
ENTICE metrics are recomputed; the external profiles are reused from cache.
Leontief calculations and environmental recalculation are disabled. Flow and
baseline checksums must remain unchanged. The interface retains the MARIO workshop
style and hides local source-file links; detailed provenance stays in sidecars.
