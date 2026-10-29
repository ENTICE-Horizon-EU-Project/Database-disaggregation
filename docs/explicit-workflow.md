# Explicit workflow prototype

Both **MARIO** and **Database disaggregation** must use their local branch
`codex/explicit-workflow`. These working-tree APIs have not been published.
Use a Python environment with these checkouts importable, CVXLab and an
installed solver. The small example uses CLARABEL and needs no licence or
SharePoint source data. Its inputs and results go in a fresh temporary directory.

The complete executable example is [explicit_workflow.ipynb](../examples/explicit_workflow.ipynb).

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

## Prototype verification on 29 October 2026

The source worktrees remain unchanged. The experiment uses separate worktrees
named `explicit-workflow`, each on local branch `codex/explicit-workflow`.
MARIO starts from `b860366`; Database disaggregation starts from `eb15f50` plus
the existing uncommitted notebook/dashboard APIs copied from `codex/notebook-api`.
The changes are local and have not been committed or pushed.

* Full MARIO operations and documentation tests: **402 passed, 1 skipped**.
  This includes explicit-stage quadratic/KL comparisons, real sequential solves,
  failure continuation and resumption, IOT/SUT insertion, both CSV and XLSX,
  compatibility adapters and parser-download round trips. The previous 13
  failures are corrected; no tests were disabled to obtain this result.
* Database disaggregation suite: **163 passed, 5 skipped, 2 subtests passed**,
  rerun against the experimental MARIO checkout after the repairs.
* Tiny observations are tested both unchanged by default and clipped with
  explicit `residue`. Signed final-demand shares are checked at both bounds,
  outside both bounds and through the resulting parent/child priors.
* Mixed Add/Split coverage uses a synthetic workbook with an actual non-split
  addition and verifies its reference coordinates and retained final demand.
  The old fixture did not exercise this condition. The two packaged inventories'
  empty Exclusions headers now use the current origin/destination schema;
  all other workbook ZIP members remain unchanged.
* The notebook's **9 code cells** executed successfully with a real Jupyter
  kernel and produced an exported database and standalone dashboard. The
  existing workshop notebook and the prototype's numerical workflow are unchanged.
* A **clean Sphinx build with warnings treated as errors succeeds**. The CSV
  and Parquet downloads are generated by `doc/scripts/build_parser_examples.py`,
  included in the checkout and tested by reloading flows and coefficients with
  their original units. The new guide/API and affected download links are checked.
* `git diff --check` passes in both experimental worktrees.

The real 61-region database was not rerun. This first prototype intentionally
exposes one optimization problem; the public transactional group iterator is
not part of this change. Existing grouped execution and resumption remain
available and tested through MARIO's controller.
