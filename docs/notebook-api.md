# A notebook using the repository APIs

The notebook imports MARIO and `database_disaggregation` directly. Configuration contains
paths and solver options; importing the package does not load an IO database or
start a run. The example keeps at most two code lines per cell. Numerical preparation and reporting are repository APIs; synthetic data construction stays in tests.

Start with [the example notebook](../examples/disaggregation.ipynb). Copy
[the example configuration](../config/notebook.example.json) to
`settings.json` beside it and set the checkout/data paths.

## Use a checkout

With the MARIO/CVXLab dependencies available in the selected Python environment:

```python
from pathlib import Path
import sys
sys.path.insert(0, str(Path('/path/to/Database disaggregation') / 'src'))

from database_disaggregation import Geography, SplitPlan, prepare_inputs
from database_disaggregation import analysis, reporting
```

For a separate environment, install the existing local MARIO and CVXLab checkouts
and this checkout with its optional dependencies. The repository itself can also
remain uninstalled and be imported through `src` as above. Do not install an
unrelated MARIO distribution from PyPI for these experimental split workflows.

```bash
python -m pip install -e '/path/to/cvxlab'
python -m pip install -e '/path/to/MARIO'
python -m pip install -e '/path/to/Database disaggregation[analysis,reconcile]'
```

MARIO/CVXLab versions and solver settings must match the selected checkpoint.
Licensed datasets and personal paths belong in local configuration, not Git.

## Input metadata and preparation

For the complete collected-data pipeline, pass the parsed MARIO database and
the shared data root explicitly:

```python
geography = database_disaggregation.Geography.read(DATA_ROOT / settings['geography'])
preprocessed_data = database_disaggregation.prepare_inputs(
    database=db,
    data_root=DATA_ROOT,
    geography=geography,
    output_dir=Path('prepared_inputs'),
    missing_output='parent_share',
    missing_cost_structure='same_sector_then_parent',
    inconsistent_targets='reconcile',
)
```

This API uses the existing complete collection recipe, including the additional
activities. It returns a `PreprocessedData` object:

- `.database`: a MARIO database aggregated to the requested geography, with the
  prepared workbook read in and ready for the subsequent modelling steps;
- `.workbook`: the path to `add_sectors.xlsx`;
- `.audit`: the directory with source fingerprints, assumptions and adjustments.

The original database and collected files are preserved. No baseline Parquet is
written and no MRIO disaggregation is solved. Output/trade reconciliation can
use its existing optimisation solver. `output_dir` must be a new directory.

Conversions, mappings and accounting checks are always applied. Missing-data
choices are explicit: `missing_output='parent_share'` estimates missing native
country outputs using child/parent shares; `missing_cost_structure=
'same_sector_then_parent'` borrows child profiles within the selected region,
then globally, then uses the parent. `inconsistent_targets='reconcile'` adjusts
incompatible output observations and parent/output trade budgets. Each accepts
`'raise'` instead to stop when that estimation/adjustment is needed. The strict
target option still permits geographic allocation consistent with the supplied
observations, within the existing numerical tolerances. The selected options
are recorded in `policy.json`, `preparation.json` and the audit summary.

The legacy `prepare_inputs(source_dir, output_dir, ...)` and
`prepare_model_inputs(...)` calls retain their directory return values.

```python
geography = Geography.read('regions.json')
plan = SplitPlan.read('add_sectors.xlsx')
prepared = prepare_inputs(
    native_inventories, new_output_directory,
    database=native_db, geography=geography, steps=plan.steps,
    cleaning_policy=True, output_reference_dir=output_references,
)
```

`SplitPlan` reads metadata only. It validates that named intermediate steps
partition the sectors; MARIO still owns inventory parsing and split validation.
`prepare_inputs` accepts an already parsed MARIO IOT through `database`.
`native_db` can come from any MARIO parser; preparation does not inspect its
original file format or read a second database. Source inventories, region
mapping, sector names, units and cleaning policy must match that database.

Pass the database at the **source inventories' regional resolution**. Reconciliation
uses its native parent budgets and regional weights. The function aggregates a
copy when `geography` is supplied and leaves the caller's database unchanged.
For a native-resolution run, omit `geography`. Retain the native object when
constructing the database to solve:

```python
db = native_db.aggregate(None, levels='Region', region_aggregation=geography.mapping,
                         zero_output_epsilon=None, inplace=False)
db.read_add_sectors_excel(prepared / 'add_sectors.xlsx', read_inventories=True, split=True)
```

Object-based preparation writes the input workbook and audit evidence, with
in-memory matrix/unit fingerprints. It does not save a baseline Parquet copy.
The notebook continues with the existing `db` object. File-based callers may
still use `baseline_path` and `baseline_format` instead; these arguments cannot
be combined with `database`. Their existing baseline snapshot and CLI workflow
are retained. An object-based package can be used by another session by reading
its workbook into the matching MARIO database; it is not a saved database.

In the demonstration notebook, the configured reviewed workbook is read explicitly
before `db.add_sectors`. This reproduces the verified result. A newly prepared
candidate can be selected as input after review; it is not silently substituted
for the reviewed workbook. Fresh temporary run directories keep preparation,
blank templates and solver checkpoints outside the presentation folder.

## Extended collection and the current saved example

Use MARIO branch `codex/mrio-memory` for the current 61-region example.
The repository APIs are integrated into `main`. The example settings
select the 61-region published run with 128 total sectors: 52 of the 69 planned
additions succeeded, and 17 remain in their parents. Preparation and optimization
cells are commented out for the demonstration.

The extended recipe already used for that run is available directly:

```python
from database_disaggregation import prepare_model_inputs
prepared = prepare_model_inputs(native_db, new_directory,
                                geography=geography, steps=plan.steps)
```

This reuses the existing project source rules for BAR, SGI and rebuilt PCP,
together with the other collected sectors. It accepts the native MARIO database
in memory, writes to a new directory and does not reload or export the database.
It uses the existing source path configuration and Gurobi reconciliation policy.
The generic `prepare_inputs` API remains available for resolved inventories.

The selected model run uses Gurobi with `on_step_failure="continue"` and a
one-sector-per-group plan. Failed optimization groups remain in their parents;
invalid input or export errors still raise. Fresh runs require the solver and
licence and write new checkpoints. The demonstration calls no solver.

Published residual names are reversible. Use
`database_disaggregation.core.residual_labels.load_checkpoint_with_codes` to preserve
independent output X and restore computational codes before further analysis.
The dashboard uses the published labels from the matching report.

## Analysis

```python
checks = analysis.check_targets(result, input_workbook)
profile = analysis.use_profile(result, 'APP')
profile.shares  # using sectors/final consumers x destination regions
analysis.plot_use_profile(profile).show()
```

All supplying origins are summed. Each valid destination column sums to 100%
over intermediate use and **all available final-demand categories**, including
households, government, NPISH, investment, stocks, margins and other native Y categories.
Missing final-demand categories stay unavailable. Signed flows are retained;
nonpositive denominators are undefined. `final_demand` and `minimum_total` can be
supplied explicitly for other datasets/units.

All negative use shares are shown in red, including residuals below 1 USD;
raw signed values remain in the profile and tooltip. `check_targets` explicitly requires M USD input
observations and tests total interregional deliveries, including all final uses.
It checks agreement with supplied constraints, rather than independent validity.
For a partial reconstruction, `check_targets(..., sectors=selected_codes)` checks
only explicitly selected sectors present in the database. Unknown selected codes
raise; omitted input targets are not reported as successful checks.

## Reference observations

```python
reference_set = analysis.ReferenceSet.read(reference_package)
comparisons = reference_set.compare(result)
```

A reference set contains audited baseline/reference observations, their unit and
scope qualifications, and an explicit supplier-group mapping. `compare` recomputes
only current-result metrics from authoritative `X`, `Z` and `Y`. It sums before
forming ratios, retains all counterpart regions, and never reapplies a currency
conversion. Missing current sectors or supplier groups raise an error instead of
silently narrowing a comparison. Absent geographic cases are omitted.

`ReferenceSet.from_comparisons(data, supplier_groups, provenance=...)` and
`ReferenceSet.write(path)` prepare reusable reference input packages. Source
hashes, currency metadata and geographic/sector scope qualifications should be
recorded in their provenance. The existing native EXIOBASE/EMERGING/GLORIA profile
reducers and concordance tools remain in `core.reference_benchmark` and
`core.reference_mapping`; those existing reference modules were carried unchanged
from the configurable-regions working tree for this branch.

## One explicit report output

```python
reporting.write_dashboard(
    result, 'results/dashboard.html', checks=checks, references=comparisons, workbook=input_workbook,
    title='GTAP disaggregation results',
)
```

The optional `workbook` supplies the new-sector and parent identities from
`Master`. Selected sectors are marked New sector, Residual parent or Original
sector, and newly created sectors show their parent. Residual-parent status
takes precedence if a new sector is itself split in a later step. Missing
workbook metadata is not replaced by guesses from sector codes or target rows.

The renderer consumes analysis results and packaged HTML/JS/logo resources. It
writes only the requested standalone HTML, including its JavaScript and images.
It does not generate companion CSV, JSON, PNG or checkpoint files. Checks and
external references are optional. Reference charts retain all available databases
with stable colours, an HTML legend and explicit layout heights.

## Use a matching saved numerical report

```python
reporting.write_dashboard(result, 'results/dashboard.html',
                          benchmark=run_directory / 'benchmarking.json')
```

For a workshop that skips the solve, pass the saved checkpoint directory
instead of an in-memory database:

```python
run_directory = DATA_ROOT / settings['result_database']
dashboard_file = database_disaggregation.reporting.write_dashboard(
    database=run_directory,
    output=Path('results/MARIO_workshop_dashboard.html'),
    benchmark=run_directory / 'benchmarking.json',
)
```

The existing checkpoint loader verifies saved matrix hashes, preserves the
independent X targets and restores computational sector codes. This path
requires a completed checkpoint; a bare Parquet export has no checkpoint state.
No preprocessing, optimisation or external-database parsing is run. A fresh
in-memory result remains supported and needs checks/references for that result,
instead of the archived report of another run.

The saved report supplies published sector names/status, parent identities,
recorded target checks, compatible reference cases and numerical audit findings.
The renderer verifies its region/sector universe and saved independent outputs
against the supplied database. Audit links point to the existing report files;
no companion JSON/CSV is created in the notebook directory.

A benchmark attached in this way describes that saved run. Do not attach it to
a fresh solve. The example's fresh-result branch instead computes current target
checks for the sectors actually present and renders those result views. Generate
a matching benchmark/reference package before attaching an audit to a new run.

The saved example retains `report_only` monetary review findings and pending E
recalculation. Its source matrices and input workbooks are not changed by this
presentation workflow. All native final-demand categories remain in the use
heatmap denominator, as in the common dashboard.
