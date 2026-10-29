# Explicit workflow prototype

Database disaggregation's APIs are consolidated on **`main`**, under the
`database_disaggregation` namespace. The separated MARIO model stages currently
require its experimental **`codex/explicit-workflow`** checkout. Use an environment
with both checkouts importable, CVXLab and the chosen solver.

The example notebook uses configured real data and has at most two code lines
per cell. Synthetic database construction belongs in `tests/test_workflow.py`.
Preparation, model execution and export are commented for the workshop; saved
checkpoint analysis remains executable.

The complete executable example is [disaggregation.ipynb](../examples/disaggregation.ipynb).

| Diagram stage | API | Responsibility |
| --- | --- | --- |
| Parse and aggregate the MRIO | MARIO parser and `db.aggregate(...)` | MARIO |
| Clean and prepare inventories | `workflow.prepare_inputs(...)` or `workflow.prepare_model_inputs(...)` | Existing Database disaggregation rules |
| Set up the optimization | `workflow.build_model(db, inputs, directory=...)` | `db.build_split_model(...)` |
| Solve | `workflow.solve_model(model, solver=...)` | MARIO/CVXLab |
| Assemble the database | `workflow.assemble_database(solution)` | MARIO |
| Export the result | `workflow.export_database(result, new_directory, inputs=inputs)` | Database disaggregation + MARIO Parquet |
| Post-process and display | `workflow.build_dashboard(exported_run, html_path)` | Existing analysis/reporting modules |

```python
from database_disaggregation import workflow

model = workflow.build_model(db, prepared_inputs, directory=work / "model")
solution = workflow.solve_model(model, solver="CLARABEL")
result = workflow.assemble_database(solution)
exported = workflow.export_database(result, work / "database", inputs=prepared_inputs)
dashboard = workflow.build_dashboard(exported, work / "dashboard.html")
```

`prepare_inputs` handles resolved native inventories and optional reconciliation.
`prepare_model_inputs` retains the existing extended ENTICE collection recipe;
this prototype does not replace that recipe or rerun the 61-region case.
Neither preparation API parses the database again or exports it on the in-memory
route. Choose the same regional mapping explicitly for inventories and database.

The public one-problem orchestrator `workflow.run(db, inputs, directory=...,
solver=..., model_options={"split_model_options": ...})` calls the same five
stage functions in order. It starts after input preparation. It does not hide
parsing, aggregation, or source policies.

## Stage contracts and grouped execution

Building initializes the CVXLab/CVXPY problem without running a feasibility or
optimization solver. Solving performs the existing feasibility and numerical
checks and archives the point, without reconstructing the database. Assembly
reads that validated point and returns MARIO matrices. Each model/solution is
consumed once. All three stages operate on a private copy of the source database.
An error propagates; failed handles cannot be assembled or retried. Use a new
model and directory to retry. Existing directories are never overwritten by the
new public workflow APIs.

**The explicit API currently builds one problem for the complete workbook.**
It does not execute the workbook's Intermediate steps sheet. Transactional
group execution, failure continuation and checkpoint resumption remain in
`db.add_sectors(..., intermediate_steps=True, ...)`; that controller now uses
the same extracted construction, solve and assembly implementations. In a
future public group controller these stages must repeat per group, using the
preceding accepted result. Building all group models up front is incorrect.

An exported run is distinct from an intermediate checkpoint. `load_database`
validates its recorded file digests and restores saved independent output X;
it does not infer a completed group history or resume the plan. Keep the native
MARIO checkpoint API for resumption. Solver/model options and pending satellite
recalculation are recorded. Original numerical diagnostics remain in the model
directory. Exported data are not labelled economically certified.

Dashboard rendering reuses the common dashboard, sector identities and target
checks from the archived workbook. Cross-database cases require an explicitly
matching `references=` package or `benchmark=` report; the tiny example does
not fabricate references. All available final demand remains in use heatmaps.

## Validation

Run from this repository with the experimental MARIO checkout on PYTHONPATH:

```bash
python -m pytest tests/test_workflow.py tests/test_database_input.py -q
```

The tests execute a 3-region, 2-sector source aggregated to 2 regions, adding
one child sector, with a real CLARABEL solve. They check exported/reloaded
matrices and X, source immutability, file changes, and the stage orchestrator.
MARIO's stage tests compare quadratic and KL results against `add_sectors`.

## Integration verification

The integration combines the notebook/preprocessing APIs, the explicit stage
workflow, common dashboards, model-region reconciliation, memory probes and
cross-database mappings. The original worktrees are preserved as snapshots.
MARIO model code remains in its own repository.

The complete Python test suite is run against the integrated code with the
matching MARIO checkout. Synthetic tests execute actual small solves, check
the staged orchestrator, verify checkpoint targets and preserve independent X.
Notebook structure checks enforce the two-line code-cell limit and exclude
synthetic table construction. The real 61-region model is not rerun.

The notebook was executed against tiny native flows and a validated saved checkpoint after integration. All 17 code cells have at most two lines; no preparation or MRIO solve is launched by default.

Final integration checks: **194 tests passed, 5 skipped, 2 subtests passed**. The preprocessing API also passed with a second Python hash seed. The package wheel includes the renamed namespace, workflow APIs, shared templates and logos.
