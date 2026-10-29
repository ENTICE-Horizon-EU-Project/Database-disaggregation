# Data collection dashboard

The dashboard has one economic data model and three views. Its controls select
activities and regions, never source files or worksheets. Every new sector
remains in the same sector selector, including activities whose current source
is missing or reported only at product-group level.

```python
from database_disaggregation.reporting import SourceCollection, write_source_dashboard

collection = SourceCollection.from_pipeline()
write_source_dashboard(collection, "results/ENTICE_data_sources.html")
```

Use the repository's configured shared-data paths and the `analysis` dependency
extra. No MARIO run, coefficient insertion or split optimisation is needed.
Optional `inventory_dir`, `baseline_path`, `source_paths`, `policy` and `registry`
arguments select another explicitly configured set of pipeline inputs.

## Data boundary and source rules

`SourceCollection` builds the complete activity universe from the adopted
reconciliation policy: the current selection has **67 new sectors**.
Archived agricultural drafts and inactive catalogue records are outside that
selection. The canonical activity name comes from the policy rather than a
possibly copied template label.

The adapter reuses the repository's readers and rules:

- `read_sector_templates` identifies the standardised source inventories and
  their collection metadata. This is the common input boundary before database
  coefficient construction, including activities supplied in shared data tables.
  Conflicting duplicate inventories fail; identical normalised duplicates are
  collapsed.
- `Sources.observations` selects production columns, validates their headers,
  applies adopted monetary conversions and share rules, and preserves sparse
  parameter zero semantics. `observation_geographies`, also used by
  `prepare_outputs`, applies inclusive/residual scopes and explicit exclusions.
  There is no extra geographic fitting or imputation in the dashboard adapter.
- `rows`, `clusters` and `expand` read the common inventory schema and resolve
  exact input/factor/group identities. Coefficients are divided by the declared
  functional output amount (blank means one, as in the inventory contract).
  Input origins are summed for an input recipe. Monetary sectors and factors
  are retained; satellite extensions are outside this view. Existing estimated
  profiles are labelled. No new balancing or cluster allocation takes place.
- `selected_trade_observations`, also used by `prepare_trade`, owns paired/direct
  source precedence and parent-pattern exclusions. The dashboard additionally
  exposes a policy-defined product-group observation where there is no individual
  series. It retains that observation as a group: it does not allocate the same
  group total to its children or generate a new parent-based estimate.

Input groups have a common identity based on item type and exact member codes.
The same group is shared across activities even when its original labels differ;
matching names with different memberships remain distinct. Sector and factor
namespaces stay separate. All processing uses the selected pipeline identities,
without inferring sector codes from filenames.

Collection attribution is separate for production, costs and trade. Shared
Purdue inputs are credited to Purdue; an individual partner's production/cost
lead is not inherited by its trade series. Accompanying collection references
are retained in the secondary source panel. `collection.evidence` records input
hashes, classification/registry fingerprints and the exact policy digest.

## Views

- **Total Production:** choose a sector for its regional observations. Bars and
  values share a common unit (million USD) and the adopted reference year. Group
  totals are labelled and never copied into member-country values. No missing
  observation becomes zero. Share-derived estimates are labelled.
- **Cost Structure:** choose a sector to compare its recipes across producing
  regions/groups. Values are input cost per 100 output units, without a new
  normalisation. The initial view ranks the largest 25 input categories; search
  or “Show all inputs” exposes the remainder. Group names open exact membership
  definitions. Comparison columns are paginated.
- **Trades:** choose a product, origins and destinations to inspect a compact
  canvas heatmap containing all selected regions together. Axes display only
  region codes, with tick spacing adapted to the available size. Hover or tap
  any cell for full names and its trade value; arrow keys also inspect cells.
  There are no values printed inside the heatmap. International source-parameter
  zeros remain zero, while the domestic diagonal is outside scope. Product-group
  coverage and unavailable series retain their explicit labels.

Only the sector-led views are exposed: there is no “Explore by” mode selector or
“by Region” view. Selectors, search fields and control buttons have a common
42-pixel height. The footer reads “Dashboard developed by POLIMI & eNextGen”.

All three views show collection attribution for the current selection. The
interface is English and uses ENTICE branding. All data are embedded in one
local HTML and loaded by activity; no external scripts or web server are needed.
The file is a snapshot and must be regenerated after source changes. Share it
under the same conditions as its underlying data.

## Verification

```bash
PYTHONPATH=src python -m pytest -q tests/test_source_dashboard.py tests/test_reconciliation.py
node tests/source_dashboard_smoke.cjs /path/to/ENTICE_data_sources.html
```

The Python tests cover the common schema, role-specific attribution, source
precedence, composite coverage, missing versus zero, functional amounts,
conflicting duplicates and shared geographic rules. The JavaScript check opens
every new sector in all three views and exercises cluster dialogs, full trade
matrices, code-only axes, exact hover values, zero/diagonal cells, keyboard
inspection, high-density canvas scaling, filters, search and cost pagination.
It uses a minimal DOM and does not verify rendered browser layout.
