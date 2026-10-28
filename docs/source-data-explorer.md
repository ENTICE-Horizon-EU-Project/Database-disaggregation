# Source data explorer

`write_source_dashboard` makes one local English HTML page with three views:
**Total production**, **Trades** and **Cost structure**.

```python
from pathlib import Path
from entice_inventory.reporting import write_source_dashboard

write_source_dashboard(
    Path("/your/local/Data split/Data collection/Final"),
    "results/ENTICE_data_sources.html",
)
```

Open the HTML in a current browser. The collection-lead overview filters the
sources by partner. Partner attribution follows `General info → Lead`; joint
leads remain joint rather than being counted twice. The counts refer to source
partner templates, not to completed datasets or coverage. Purdue is also
credited for its shared tables.

The three views expose:

- **Total production:** `Total production` from partner `Inventory_*.xlsx`
  templates, and `splttargs.xlsx → REPOUT` from Purdue.
- **Trades:** Purdue `trade.xlsx → NTSCIF` (CIF values) and
  `splttargs.xlsx → BLTTRD` (bilateral targets), kept separate.
- **Cost structure:** intermediate inputs and primary factors from partner
  `Unit process` sheets; Purdue `EXIOIOT.csv`, `COPCOSTS.csv` and
  `costsup.xlsx → NFCOSTSHR / PFCOSTSHR / KFCOSTSHR`.

Select a producing region and data type for a partner cost structure. Its input
values, units, source and notes are shown together. Energy/emissions extension
rows are omitted. Purdue tables have sector/region/input filters as applicable;
trade tables have sector/origin/destination filters. Search and pagination apply
to the selected data. Production rows without a region identifier are omitted
as unfilled template rows. Other supporting sheets, tariff tables, VA.xlsx,
GDX files and duplicate supporting CSV deliveries are not browsing entries.

Underlined cluster names open a definition dialog:

- Partner sector, region and factor memberships come from that exact workbook's
  `Sector`, `Region` and `Primary input` sheets. Standard groupings and custom
  definitions (including carried-forward labels) retain original member names
  and available GTAP codes. Sector and factor namespaces stay separate;
  direct `Capital` must not be mistaken for the custom `CAPITAL` cluster.
- `GLOBAL` explains the catch-all convention. It is not assigned an invented
  fixed list of countries or interpreted as an unconditional world total.
- Purdue aggregate input codes use the repository's existing GTAPCE-to-GTAP12
  classification. The dialog labels that mapping as such. An optional
  `matching="/path/to/GTAP12_matching.xlsx"` selects a different workbook;
  without an available matching file these codes remain plain text.

Source values are read literally: no currency, year or unit conversion,
normalisation or formula recalculation. In particular, raw EXIOIOT values are
not presented as already-normalised shares. Cached formula values remain the
values saved by the source workbook; absent caches are marked `ƒx`, and zeros
remain distinct from blanks (`—`). “Show formulas” exposes expressions.
Headers preserve years and units; hover reveals full cell content and source
coordinates. Excel number formats and date styles are not applied.

All data are embedded in the HTML, compressed and decoded on selection. No web
service or model database is required and only the requested HTML is written.
The page is a snapshot: regenerate it after editing source files, and share it
under the same conditions as the input data. Original-file links refer to the
creator's local paths and may differ on another machine.

Verification:

```bash
PYTHONPATH=src python -m pytest -q tests/test_source_dashboard.py tests/test_analysis_api.py
node tests/source_dashboard_smoke.cjs /path/to/ENTICE_data_sources.html
```

The JavaScript smoke check exercises loading every dataset, category and lead
filters, cost-region selection, trade-sector filtering, cluster dialogs, search,
pagination and stale asynchronous loads using a minimal DOM. It does not verify
rendered browser layout.
