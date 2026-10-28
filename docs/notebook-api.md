# A notebook using the repository APIs

The notebook imports MARIO and `entice_inventory` directly. Configuration contains
paths and solver options; importing the package does not load an IO database or
start a run. There is no notebook-specific setup or orchestration module.

Start with [the example notebook](../examples/disaggregation.ipynb). Copy
[the example configuration](../config/notebook.example.json) to
`disaggregation.json` beside it and set the checkout/data paths.

## Use a checkout

With the MARIO/CVXLab dependencies available in the selected Python environment:

```python
from pathlib import Path
import sys
sys.path.insert(0, str(Path('/path/to/Database disaggregation') / 'src'))

from entice_inventory import Geography, SplitPlan, prepare_inputs
from entice_inventory import analysis, reporting
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

```python
geography = Geography.read('regions.json')
plan = SplitPlan.read('add_sectors.xlsx')
prepared = prepare_inputs(
    native_inventories, new_output_directory,
    geography=geography, steps=plan.steps,
    baseline_path=native_baseline, baseline_format='mario_parquet',
    cleaning_policy=True, output_reference_dir=output_references,
)
```

`SplitPlan` reads metadata only. It validates that named intermediate steps
partition the sectors; MARIO still owns inventory parsing and split validation.
`prepare_inputs` is the existing preparation/reconciliation implementation. Its
baseline argument refers to the **native** geography. It creates a new candidate
input package, without overwriting native source workbooks.

In the demonstration notebook, the configured reviewed workbook is read explicitly
before `db.add_sectors`. This reproduces the verified result. A newly prepared
candidate can be selected as input after review; it is not silently substituted
for the reviewed workbook. Fresh temporary run directories keep preparation,
blank templates and solver checkpoints outside the presentation folder.

## Analysis

```python
checks = analysis.check_targets(result, input_workbook)
profile = analysis.use_profile(result, 'APP')
profile.shares  # using sectors/final consumers x destination regions
analysis.plot_use_profile(profile).show()
```

All supplying origins are summed. Each valid destination column sums to 100%
over intermediate use and the selected final consumers. The defaults include
households, government and NPISH; they exclude investment, stocks and margins.
Missing final-demand categories stay unavailable. Signed flows are retained;
nonpositive denominators are undefined. `final_demand` and `minimum_total` can be
supplied explicitly for other datasets/units.

The plot uses a zero colour for negative residuals smaller than 1 USD when data
are in M USD, while preserving raw values in the profile and tooltip. Material
negative uses retain a red range. `check_targets` explicitly requires M USD input
observations and tests total interregional deliveries, including all final uses.
It checks agreement with supplied constraints, rather than independent validity.

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
    result, 'results/dashboard.html', checks=checks, references=comparisons,
    title='GTAP disaggregation results',
)
```

The renderer consumes analysis results and packaged HTML/JS/logo resources. It
writes only the requested standalone HTML, including its JavaScript and images.
It does not generate companion CSV, JSON, PNG or checkpoint files. Checks and
external references are optional. Reference charts retain all available databases
with stable colours, an HTML legend and explicit layout heights.
