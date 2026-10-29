# Database disaggregation

Data preparation and database disaggregation workflows for the ENTICE project,
using **MARIO and CVXLab**. The toolkit connects partner inventories and Purdue
datasets to a common input-output database: it builds sector inventories,
prepares output and trade targets, and supports database construction,
disaggregation, export and verification.

The current adapters target GTAP Power 2023. D2.4 is one historical application;
ongoing development also supports the D2.8 monetary MRIO split. Other databases
require an appropriate parser, classification adapter and validation of their
input conventions.

The Python distribution is `database-disaggregation`, with import namespace
`database_disaggregation`. Import the package with `import database_disaggregation`
and access its APIs as `database_disaggregation.Geography`,
`database_disaggregation.prepare_model_inputs`, or `database_disaggregation.reporting`.
Data and results live in the project SharePoint
**Data split** folder; this repository holds code, mappings, configuration and
provenance records.

## Workflow

1. Read structured partner templates, Purdue cost structures and production/trade
   observations.
2. Produce MARIO `add_sectors` inventories with explicit source and classification
   references.
3. Prepare the selected geography and reconcile input targets/profiles where the
   selected branch supports it.
4. Construct a database with MARIO. Historical D2.4 insertion uses `split=False`;
   monetary MRIO disaggregation uses `split=True` and CVXLab.
5. Export inventories, databases and diagnostics to paired shared folders.
6. Benchmark saved monetary MRIO results against their exact baseline, with an
   offline interactive dashboard and JSON/CSV KPIs; no model rerun is needed.

Source preparation, reconciliation and the optimisation model are separate
steps. Reproducing an inventory is distinct from validating the economic
plausibility of a balanced MRIO. Environmental E is still provisional in the
current accepted 13-region monetary split.

## Benchmark saved MRIO results

Database dashboards now use the **MARIO workshop format**: sector selection,
production, regional deliveries, use shares and available cross-database
comparisons. The same template serves notebook and saved-result reporting.
Refresh all existing reports with `python scripts/refresh_dashboards.py --all
--overwrite`; this reads saved results and needs no external SSD or model run.


The experimental branch includes a first dashboard for the accepted **13-region,
67-new-sector** split (143 total sectors), compared with its exact 76-sector
baseline. It covers conservation/accounting, technology, signed V/Y, trade,
stability and multipliers and a filterable economic review queue. E and environmental
footprints remain pending. See [benchmarking methodology and commands](docs/benchmarking.md).
Generated numerical reports stay beside the final database in Data split.

## Branches and reproducibility

| Branch or reference | Purpose |
|---|---|
| `main` | Core inventory tooling, historical reconstruction, configuration and shared-data access. |
| `codex/configurable-regions` | Configurable geography, reconciliation, sequential MRIO trial execution and publication. Use this branch for the current D2.8 experiments. |
| `codex/split-diagnostics-2026-10-14` | Source, target and model-readiness diagnostics. |
| `cleanup/pipeline-tidy` | Pipeline organisation and maintenance. |
| `reference/d2.4` | Dedicated D2.4 reconstruction reference, with current shared-data paths. |
| Tag `backup/main-before-registry-2026-10-01` | Preserved original pre-reconstruction code at `44097ea` (8 June 2026). |

The D2.4 reference starts from **`a15cf5a`**, the 2 October reconstruction state,
and carries the subsequent storage/configuration updates. The recorded replay
reproduced coefficient, output and trade records for all 67 distinct inventories
from the preserved MARIO inputs. This does not establish that the June code alone
recreates the published package from raw sources, nor that a historical byte-for-byte
execution environment has been recovered. See the D2.4 branch README and the
[maintained project report](docs/baseline/README.md).

MARIO model changes remain in its own repository. The current MRIO experiments
use MARIO `codex/mrio-model-improvements`; its options are separate from this
repository's path configuration. Features listed for the experimental branch
are not automatically available on `main` or the D2.4 reference.

## Installation

```bash
pip install -e .
```

The base package provides the inventory tools; numerical export, plots and
database operations need additional dependencies. The lightweight export
environment is recorded in `requirements/d24-export.txt`. For the pinned
MARIO/CVXLab reconstruction environment, see `scripts/bootstrap_producer.py`
and the [producer environment notes](docs/baseline/README.md#producer-environment-and-representative-verification).
MARIO is installed separately. Use the feature branch and matching dependencies
for MRIO reconciliation and model trials.

## Configure your own paths

**`paths.local.json` is the single user path configuration file.** It is
versioned at the owner's request and currently contains Lorenzo's Data split
location. Replace `data_root` with your own local SharePoint directory. The
configured dataset paths are relative to that root, so users with the same
shared folder structure normally change only that value.

`config/paths.example.json` is a generic starting point. You can copy it over
`paths.local.json` for a fresh setup, then supply your `data_root` and optional
geography. For example, the main path settings have this form:

```json
{
  "data_root": "/your/local/Data split",
  "baseline_format": "mario_parquet",
  "paths": {
    "partner_templates": "Data collection/Final",
    "purdue_trade": "Data collection/Final/PURDUE/Shared material/Trades/trade.xlsx",
    "baseline": "Database/_GTAP Power 2023/Cache"
  }
}
```

Omitted dataset roles use the defaults in `database_disaggregation.core.paths`.
Absolute paths are also accepted as explicit overrides; no user's OneDrive
location is embedded in the Python path resolver.

- `ENTICE_DATA_ROOT` overrides `data_root`.
- `ENTICE_CONFIG` selects another JSON configuration file, including one outside
  the checkout or one used by an installed package.
- `mario_source` optionally sets the local MARIO checkout used as an import fallback; installed MARIO remains the first choice.
- `paths` overrides individual datasets; `baseline_format` selects the baseline
  reader. Available formats are `mario_parquet`, `gtap_csv` and `gtap_gdx`;
  GTAP bundles must be extracted explicitly and GDX requires its runtime.

On `codex/configurable-regions`, the bundled 13-region map can be selected
without an absolute checkout path:

```json
"geography": {
  "name": "ENTICE13",
  "mapping": "data/geographies/gtap13.json",
  "mapping_base": "repository"
}
```

For an external relative mapping, omit `mapping_base` or set it to `data_root`.
Absolute mapping paths also work. The map is a complete source-to-target
partition; duplicate or missing source assignments are rejected.
`geography: null` retains the native geography. The disaggregation inventory
directory is configured separately and is relative to `data_root`.

## Run the MRIO pipeline with another regional aggregation

Use **this branch (`codex/configurable-regions`)** and MARIO
`codex/mrio-model-improvements`, with its dependencies installed. Run the commands
from the repository root. Select the intended MARIO checkout explicitly if your
environment already has another editable MARIO installation:

```bash
conda activate mario
export MARIO_SOURCE="/path/to/MARIO/checkout-on-codex-mrio-model-improvements"
export PYTHONPATH="$MARIO_SOURCE:$PWD/src"
```

1. Set your SharePoint `data_root` in `paths.local.json` (or select your own JSON
   with `ENTICE_CONFIG`). Keep the preparation baseline pointed at the **native
   GTAP cache**, `Database/_GTAP Power 2023/Cache`; do not replace it with a saved
   13-region result or the 13-region benchmark baseline.
2. Copy `data/geographies/gtap13.json` to a new mapping, such as
   `data/geographies/my_regions.json`, and edit its target labels. The JSON maps
   **all 163 source GTAP region codes to target region names**, one assignment
   per source. For example, changing `"ITA": "EU27"` to `"ITA": "Italy"` separates
   Italy from EU27 and creates a 14th region. Keep every other assignment; missing,
   duplicate and unknown source codes are rejected. CSV/TSV/XLSX with two columns
   (source, target) and a header row are also accepted.
3. Prepare a **new** working directory. This command aggregates the baseline and
   inventories, applies the reconciliation policy, checks cumulative budgets and
   writes the editable workbook; it **does not solve the model**:

```bash
python scripts/run_disaggregation.py \
  --mapping data/geographies/my_regions.json \
  --cleaning-policy config/cleaning-policy.json \
  --intermediate-steps \
  --output build/disaggregation/my_regions_01
```

`--mapping` overrides the geography in `paths.local.json`. Alternatively set
`geography.mapping` to the new file with `mapping_base: "repository"`, then omit
`--mapping`. Set `geography` to `null` to retain all native regions. Command-line
relative paths resolve from your current directory; dataset paths in the user
configuration resolve from `data_root`.

4. Open `build/disaggregation/my_regions_01/add_sectors.xlsx` and edit the
   **`Intermediate steps`** sheet. Each column is an ordered group; every `Master`
   sector must occur exactly once. Without a `--steps` JSON, preparation creates
   one column named `Step 1` containing all children. It does **not** automatically
   create a Mining group. For a staged trial, split this column into the intended
   groups and name the first one `Mining` if you use the example below. Instead
   of editing Excel you can pass `--steps config/my_steps.json` at preparation,
   with an ordered object such as `{"Mining": ["CHR", "COB", "..."], "Next": ["..."]}`;
   replace the illustrative lists with the complete sector plan.
5. Run a controlled first group, using the **entropy-first policy**:

```bash
python scripts/run_model_trial.py \
  --prepared build/disaggregation/my_regions_01 \
  --policy config/model-trials/entropy-first.json \
  --stop-after-step Mining
```

The fresh controlled runner currently defaults to stopping after `Mining`;
**supply the real group name explicitly**. If you kept the single `Step 1`
column, `--stop-after-step "Step 1"` solves all its children together. To execute
all groups in a fresh trial, name the last column as the stopping group.
The controlled runner now defaults to this policy when no fixed `--options` or
`--historical-model` is supplied. It tries **KL for the first group**, then
**partial entropy with signed KL for subsequent groups**. For each entropy model,
solver order is **MOSEK → Clarabel → SCS**. Only after those attempts fail does it
try the named **quadratic** model, with **Gurobi → MOSEK → Clarabel → OSQP**.
The feasibility preflight uses **Gurobi → HiGHS → Clarabel** for installation,
licence or numerical failures; a mathematical infeasibility stops that preflight.

Every attempt starts from the same preceding accepted database. The policy
requires a finite evaluated objective and retains all independent acceptance checks and records unsuccessful attempts and
model changes in `model_attempts.json` and checkpoint `model_history`. Schema,
input-integrity and programming errors stop the run instead of triggering an
objective change. Solver settings and order are editable in the policy JSON.
MOSEK and Gurobi need their Python packages and valid licences. Open solvers remain
supported, and unavailable commercial solvers are logged and skipped.

Entropy support is no longer a fixed `1e-8`: each step computes
`10 ** (floor(log10(min(abs(nonzero monetary prior)))) - 4)` across the references
in enabled entropy terms, before numerical scaling. For example, a minimum of
`0.03` gives `1e-6`. Zeros, masks, controls and disabled losses are excluded; signed
values use their absolute magnitude. `entropy_support.json` records the inputs,
coefficient and scaled coefficient. Quadratic normalisation keeps its separate
floor. See [model and solver policy](docs/model-policy.md) for details.

For a fixed formulation/solver without automatic fallback, keep using `--options`,
`--solver` and `--solver-options`. For the historical formulation use
`--historical-model --solver MOSEK`. MARIO's direct `add_sectors` call remains an
explicit single-model operation; the pipeline orchestrates the policy.

6. To continue a newly accepted checkpoint with the **same geography and policy**,
   use its database path printed by the runner:

```bash
python scripts/run_model_trial.py --resume "/path/to/accepted/checkpoint-or-shared-database"
```

Resume runs all pending groups when no stopping group is supplied. With the
default policy, it selects the subsequent-insertion entropy model. Fixed-model
replays must supply the matching `--options` and solver arguments explicitly.
To revise pending inputs, pass `--workbook` with an
edited copy of `remaining_add_sectors.xlsx`. The completed-sector fingerprints
remain protected. Checkpoints written before the adaptive-entropy-support
revision remain readable,
but cannot resume under this changed formulation. Start a fresh experiment, or
use the recorded historical code and configuration for an exact replay.

Changing geography always requires a new preparation from the native baseline;
it cannot reuse a checkpoint from another partition. A new aggregation can expose
different target conflicts, so a successful 13-region trial is not a guarantee
of feasibility for another map.

The controlled runner records inputs/code and automatically publishes paired
inventory/database folders to SharePoint. `build/` is temporary computational
storage. Accepted input packages now expose the cumulative workbook and its step
plan as `add_sectors.xlsx`; the exact last-step input is retained separately as
`step_add_sectors.xlsx`. The `remaining_...` file is a resume aid and is empty
when there is nothing left to split.

For a concrete larger-geography example, see the [49-region MCU scalability pilot](docs/scalability.md).

## Shared inputs and outputs

The maintained [Data split guide](docs/shared-data/README.md) explains the
complete structure. Its main roles are:

| Location under `Data split` | Role |
|---|---|
| `Data collection/Final` | Selected partner templates and VA.xlsx. |
| `Data collection/Final/PURDUE/Shared material` | Operational `Cost structures`, `Output and trade targets` and `Trades` packages. |
| `Data collection/Raw data` | Other deliveries, historical variants and source documents. |
| `Classifications` | Consolidated review workbook and source concordances. |
| `Database/_GTAP Power 2023` | Licensed baseline archive, cached matrices and output totals. |
| `Inventories/D2.4 inventories` | Historical inventories, preserved MARIO inputs and regenerated references. |
| `Inventories/D2.8 inventories` | Inputs for individual MRIO trials. |
| `Database/D2.4` and `Database/D2.8` | Resulting databases. |
| `_others/FNAM split` | Alternative-method reference material. |

D2.8 inputs and accepted results share the original name
`YYYYMMDD HHMM - N regions and M sectors`. Matrices are directly in the result's
`flows/`; state, provenance and diagnostics accompany them. Historical paths in
captured manifests can be located using `manifests/current_data_layout.json`.

Licensed GTAP values and generated numerical databases are supplied separately;
they are not bundled with the code. Source selection remains explicit: moving
files does not automatically replace the selected Purdue delivery.

## Entry points

| Task | Entry point |
|---|---|
| Build an inventory from a partner template | `database_disaggregation.inventory.template_to_inventory` |
| Build inventories from Purdue cost data | `database_disaggregation.inventory.exioiot_to_inventory`, `copcosts_to_inventory` where present |
| Historical D2.4 insertion and export | `scripts/run_d24_pipeline.py` (`#%%` cells; `split=False`) |
| Re-export one sector from saved coefficients | `scripts/export_d24_sector.py --help` |
| Inspect sector and region definitions | `scripts/registry.py --help` |
| Prepare configurable MRIO inputs | `scripts/run_disaggregation.py --help` on `codex/configurable-regions` |
| Execute/resume a controlled model trial | `scripts/run_model_trial.py --help` on `codex/configurable-regions` |
| Publish an existing trial | `scripts/publish_model_trial.py --help` on `codex/configurable-regions` |

The original inventory importers and the resolved-inventory MRIO preparation
have different inputs. For D2.4 reproduction, follow `reference/d2.4`; for the
current monetary split, use the experimental branch and its documented MARIO
checkout. The current accepted result is
`Database/D2.8/20261021 0655 - 13 regions and 67 sectors`, with E pending.

## Code layout and evidence

```text
config/                       portable examples and workflow policies
paths.local.json              user-editable path configuration
data/                         bundled mappings, registry and geography definitions
scripts/                      workflow, export and diagnostic commands
src/database_disaggregation/
  core/                       paths, baseline access and shared utilities
  inventory/                  source-to-inventory conversion
  export/                     inventory export and plots
  reconciliation/             reconciliation on the experimental branch
manifests/                    captured source identities and storage history
docs/baseline/README.md        maintained findings, evidence and decisions
docs/shared-data/README.md     maintained guide to shared data
build/                        ignored computational work and diagnostics
```

Historical audit records identify the code and files used at the time; they
are not rewritten to claim that an old run used today's configuration.
Structural checks and successful optimisation do not by themselves validate
economic assumptions. The first offline benchmark is available; economic review
thresholds and sensitivity experiments still need agreement with the project team.

## Notebook API

Use the repository directly for input metadata, preparation, monetary IO analysis,
reference comparisons and standalone reports. See [the notebook API guide](docs/notebook-api.md).

For unified production, cost-structure and bilateral-trade views by activity
and region, built from the selected pipeline inputs, see [the data collection dashboard](docs/source-data-explorer.md).
