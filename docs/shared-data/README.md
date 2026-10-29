# ENTICE — Data split

This WSP SharePoint folder contains the project inputs, generated inventories
and resulting databases. Maintained code lives in the
[Database disaggregation repository](https://github.com/SESAM-Polimi/Database-disaggregation)
(data preparation, reconciliation and runs) and
[MARIO](https://github.com/it-is-me-mario/MARIO) (database and split model).
Local repository `build/` folders are computational workspaces; the paired
folders below are the shared copies to use and exchange.

## Folder structure

```text
Data split/
├── README.md
├── Data collection/
│   ├── Final/                            Operational inputs read by the pipeline
│   │   ├── Inventory_*.xlsx, Add_sector_*.xlsx
│   │   ├── VA.xlsx
│   │   └── PURDUE/Shared material/
│   │       ├── Cost structures/          EXIOIOT, copper and supporting cost data
│   │       ├── Output and trade targets/ Selected splttargs workbook and GDX
│   │       └── Trades/                   Selected trade workbook and GDX
│   └── Raw data/                         Other deliveries and historical versions
│       ├── <partner>/                    Purdue, ICCS, POLIMI & ENEXTGEN, etc.
│       ├── Shared sources.xlsx
│       ├── source_consolidation_20261021.json
│       └── current_data_layout.json       Map of historical paths to current paths
├── Classifications/                      Shared classification workbooks
├── Inventories/
│   ├── D2.4 inventories/                  Released D2.4 per-sector workbooks
│   │   ├── MARIO inventories/20260630/    Original add_sectors inputs (split=False)
│   │   └── Regenerated 20261001/          67 regenerated D2.4 reference inventories
│   └── D2.8 inventories/
│       └── <run name>/                    MARIO inputs for one split trial
├── Database/
│   ├── _GTAP Power 2023/
│   │   ├── Original/                     Original licensed GTAP archive
│   │   └── Cache/                        Baseline matrices and GTAP12_X.xlsx
│   ├── D2.4/
│   │   └── 20260630/                     Historical result of split=False
│   └── D2.8/
│       └── <same run name>/              MRIO result, state and diagnostics
└── _others/
    └── FNAM split/                       Preserved alternative-method examples
```

`Data collection/Final` contains the selected operational inputs: partner
templates and VA.xlsx directly, and Purdue cost/output/trade packages in their
own subdirectories. `Final` means selected input, not an independently validated
final database. `Data collection/Raw data` preserves other deliveries, source
documentation and historical or alternative versions. Different byte versions
are kept separately; folder reorganisation does not change source selection.

Generated inventories, classifications and databases are siblings of the README.
The former `Inventory generation` level has been removed. `_others/FNAM split`
is retained reference material, not the maintained MRIO pipeline.

## Pairing a trial's inputs and results

Use **`YYYYMMDD HHMM - N regions and M sectors`** for both folders. The date and
time refer to the original trial start in Europe/Rome. Never generate another
timestamp when saving its database. `M` counts cumulative disaggregated child
sectors; the total database sector count, including GTAP parents, is in
`run.json`. Failed attempts use the intended cumulative count and are clearly
marked `failed`; their diagnostics stay with the input workbooks and no database
folder is created.

Accepted D2.8 inventory packages use these roles:

- `add_sectors.xlsx`: cumulative inputs from the accepted stages, plus any pending
  sectors in the latest source, with the editable **`Intermediate steps`** plan.
- `step_add_sectors.xlsx`: exact compiled input of the last accepted step,
  intentionally without the global plan.
- `source_add_sectors.xlsx`: original source of that trial; a resumed trial may
  contain only its pending children.
- `remaining_add_sectors.xlsx`: only sectors still to execute; empty at completion.
- `inventory_manifest.json`: coverage, executed/pending plan, source hashes and
  stage-equivalence checks for the assembled workbook.
- `README.md` and `run.json`: file roles, status and paired database location.

The folder count `M` is the number of **completed** children, not the number of
rows in the full plan. Earlier publication used `add_sectors.xlsx` for only the
last incremental step. The three accepted packages listed below have been
upgraded without changing the database matrices or their original source,
remaining and compiled step inputs. Failed historical attempts retain the old
layout and are explicitly marked failed.

The final 67-child workbook covers all 67 children across 13 regions (871
inventories), with executed groups of 17, 32 and 18. It combines the source
actually accepted for each group, including the final trade reconciliation;
it is not a copy of the first unreconciled 67-child source. Each group is
recompiled and compared against its saved input without solving the model.
This assembled reference is not evidence of a new run or exact numerical replay;
use the original stage inputs and recorded code for historical reproduction.

To upgrade another accepted legacy package without a model rerun, use
`python scripts/upgrade_published_inventories.py --database "Database/D2.8/<run name>"`
from `codex/configurable-regions`, with the matching MARIO checkout selected.
Repeat `--database` in chronological order for a chain. The command refuses an
already upgraded package, verifies all stages before replacing the primary
workbook, archives the previous file and checks database bytes are unchanged.

The prior accepted database is recorded in `source_database_directory`, relative
to the result database folder. The stages retain their original workbooks.

Each accepted database folder contains `flows/` directly, with Z, Y, V, X, E,
EY, VY and units in Parquet, plus `metadata.json`, `state.json`, `run.json` and
`diagnostics/`. No `build/model_trials/.../checkpoints/.../database` traversal is
needed. File hashes are preserved and checkpoint loading remains available with
the MARIO `codex/mrio-model-improvements` branch. From that environment:

```python
from pathlib import Path
from mario.ops.add_sector_steps import load_checkpoint

root = Path("/your/local/Data split")
name = "20261021 0655 - 13 regions and 67 sectors"
db = load_checkpoint(root / "Database" / "D2.8" / name)
```

Use checkpoint loading for these inherited-accounting runs: it retains the
independent output targets X and the intermediate-step state. The generic
flow parser recomputes X from rows.

## Accepted MRIO results, 21 October 2026

| Shared run name | Completed children | Total sectors | Result |
|---|---:|---:|---|
| `20261020 2209 - 13 regions and 17 sectors` | 17 | 93 | Mining checkpoint |
| `20261021 0641 - 13 regions and 49 sectors` | 49 | 125 | Mining plus 32 children |
| `20261021 0655 - 13 regions and 67 sectors` | 67 | 143 | Complete monetary split |

The last row is the complete, independently verified result on 13 regions.
All 871 original output targets are unchanged. The nine incompatible trade
groups were reconciled as estimates; their changes and assumptions are in the
final database's `diagnostics/trade_reconciliation/`. **E is provisional and
must still be recalculated**, as recorded in `pending_recalculations`.
The other nine published attempts failed; their logs are in their D2.8 input folders.

## Creating future trials

The MRIO trial commands below are on ENTICE `codex/configurable-regions`,
with MARIO `codex/mrio-model-improvements`. The other ENTICE branches retain
their own pipeline features and share the updated dataset paths.

Configure `data_root` in the repository's versioned `paths.local.json` to your
local `Data split` directory. It currently contains the maintainer's paths;
`config/paths.example.json` provides a generic starting point. Dataset roles
are relative to `data_root`, so the same shared layout works for every user.
`ENTICE_CONFIG` can select a separate configuration file.
`scripts/run_model_trial.py` publishes finished trials to these paired WSP
folders by default; `--no-publish` is reserved for explicitly private/CI work.
`scripts/publish_model_trial.py TRIAL_DIRECTORY` publishes an existing finished
trial. Existing published names are never overwritten.

The additional eNextGen source consolidation checked 340 raw assets: 42 were
already on WSP and 298 were copied with SHA-256 verification (about 10.16 GB,
including two large GTAP Power archives). Original source files remain in the
archive. `Data collection/Raw data/source_consolidation_20261021.json` records
each checked source, its original WSP destination and hash. Its captured paths
remain historical evidence. Use `Data collection/Raw data/current_data_layout.json`
(also in the repository's `manifests/`) to locate them after the latest moves:
apply its single longest matching prefix once. Its `repository_relocation`
entry also records the local checkout rename; captured trial manifests retain
the repository paths used when those trials actually ran.

The operational Purdue `Cost structures`, `Output and trade targets` and `Trades`
packages are now in `Data collection/Final/PURDUE/Shared material`. Their 26 data
files were moved with before/after SHA-256 verification. The `June1`, `May13`
and `_old/May27` deliveries remain in `Data collection/Raw data/PURDUE/Shared material`.
Other eNextGen material is filed by partner in `Raw data`; `Raw data/eNextGen sources`
contains additional classifications and shared documents, not all eNextGen files.
The licensed GTAP baseline is under `Database/_GTAP Power 2023`; classification
workbooks are under `Classifications`. These roles remain explicit in configuration.

Original deliveries, the GTAP baseline and the historical D2.4 result remain
reference inputs. Create a new paired run for changed data or settings. Keep
source hashes, model options, verification and estimation assumptions with its
result. Storage reorganisation preserves the numerical matrices.
