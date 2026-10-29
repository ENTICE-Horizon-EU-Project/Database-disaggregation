"""Explicit preparation, optimization, export and dashboard workflow.

MARIO owns the database and model stages. This module coordinates public APIs;
it contains no alternative disaggregation or data-cleaning algorithm.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

from database_disaggregation.core.disaggregation import prepare_inputs
from database_disaggregation.reconciliation.model_inputs import prepare_model_inputs

__all__ = ['prepare_inputs', 'prepare_model_inputs', 'build_model', 'solve_model',
           'assemble_database', 'export_database', 'load_database', 'build_dashboard', 'run']


def _workbook(path):
    path = Path(path).expanduser().resolve()
    return path / 'add_sectors.xlsx' if path.is_dir() else path


def build_model(database, inputs, *, directory, **options):
    """Build one IOT optimization problem from a workbook/prepared directory.

    Calls ``Database.build_split_model`` without solving or changing database.
    A workbook's Intermediate steps sheet is not executed here: this explicitly
    builds the entire workbook as one problem. Grouped execution remains
    available through ``Database.add_sectors(intermediate_steps=True, ...)``.
    """
    return database.build_split_model(_workbook(inputs), directory=directory, **options)


def solve_model(model, *, solver=None, solver_parameters=None):
    """Solve and validate a built MARIO model; return its unassembled solution."""
    return model.solve(solver=solver, solver_parameters=solver_parameters)


def assemble_database(solution):
    """Reconstruct MARIO matrices from a validated solution, without solving."""
    return solution.assemble_database()


def _digest(path):
    with Path(path).open('rb') as stream:
        digest = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
        return digest.hexdigest()


def export_database(database, directory, *, inputs=None, notes=None):
    """Save a new run directory atomically; existing runs are never overwritten.

    Store baseline flows (including independent X), optional input workbook,
    solver/model metadata and SHA-256 file digests. This is an exported result,
    not a sequential checkpoint: it does not invent completed-step history.
    Use ``load_database`` to retain independent X on reload. An optional
    Intermediate steps plan in the workbook is recorded, not executed.
    """
    if database.table_type != 'IOT':
        raise ValueError('The explicit workflow currently exports IOT databases only.')
    directory = Path(directory).expanduser().resolve()
    if directory.exists():
        raise FileExistsError(f'Use a new run directory: {directory}')
    workbook = _workbook(inputs) if inputs is not None else None
    if workbook is not None and not workbook.is_file():
        raise FileNotFoundError(workbook)
    directory.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f'.{directory.name}_', dir=directory.parent))
    try:
        database.to_parquet(path=staging, flows=True, coefficients=False, include_meta=True)
        if workbook is not None:
            shutil.copyfile(workbook, staging/'add_sectors.xlsx')
        model_definition = getattr(database, '_last_split_model_definition', None)
        manifest = dict(
            format='entice-explicit-workflow-v1',
            created_at=datetime.now(timezone.utc).isoformat(),
            regions=database.get_index('Region'), sectors=database.get_index('Sector'),
            solver=getattr(database, '_last_split_solver', None),
            solver_status=getattr(database, '_last_split_status', None),
            model_definition=model_definition,
            split_model_options=getattr(database, '_last_split_model_options', None),
            pending_recalculations=(['E'] if (getattr(database, '_last_split_model_options', None) or {}).get('defer_satellite_recalculation') else []),
            independent_output=True, notes=notes,
            workbook='add_sectors.xlsx' if workbook is not None else None,
            files={str(p.relative_to(staging)): _digest(p)
                   for p in sorted(staging.rglob('*')) if p.is_file()},
        )
        (staging/'run.json').write_text(json.dumps(manifest, indent=2, allow_nan=False)+'\n')
        staging.rename(directory)
    except Exception:
        shutil.rmtree(staging)
        raise
    return directory


def load_database(directory):
    """Verify an exported run's files and reload all flows, preserving saved X."""
    import mario
    import numpy as np
    import pandas as pd
    directory = Path(directory).expanduser().resolve()
    manifest = json.loads((directory/'run.json').read_text())
    if manifest.get('format') != 'entice-explicit-workflow-v1':
        raise ValueError('Not an explicit-workflow exported run.')
    files = manifest.get('files', {})
    if not files or 'flows/X.parquet' not in files:
        raise ValueError('Exported run is missing its flow manifest.')
    for relative, digest in files.items():
        source = directory/relative
        if not source.resolve().is_relative_to(directory) or not source.is_file() or _digest(source) != digest:
            raise ValueError(f'Exported run file changed or is missing: {relative}')
    database = mario.parse_from_parquet(str(directory/'flows'), table='IOT', mode='flows')
    output = pd.read_parquet(directory/'flows/X.parquet')
    if (not output.index.equals(database.Z.index) or output.shape[1] != 1
            or not np.isfinite(output.to_numpy()).all() or (output.to_numpy() < 0).any()):
        raise ValueError('Invalid independent output in exported run.')
    database.reset_to_flows('baseline')
    database.matrices['baseline']['X'] = output
    if (database.get_index('Region') != manifest['regions']
            or database.get_index('Sector') != manifest['sectors']):
        raise ValueError('Exported database differs from its recorded regions/sectors.')
    database._last_split_solver = manifest.get('solver')
    database._last_split_status = manifest.get('solver_status')
    database._last_split_model_definition = manifest.get('model_definition')
    database._last_split_model_options = manifest.get('split_model_options')
    return database


def build_dashboard(database_or_run, path, *, inputs=None, checks=None, **options):
    """Render the existing standalone dashboard from a database or exported run.

    If a run has an archived workbook, use it for sector identities and target
    checks. External comparisons require an explicitly matching reference set
    (``references=``) or saved report (``benchmark=``); none is fabricated.
    """
    from database_disaggregation import analysis, reporting
    if isinstance(database_or_run, (str, Path)):
        root = Path(database_or_run)
        database = load_database(root)
        if inputs is None and (root/'add_sectors.xlsx').is_file():
            inputs = root/'add_sectors.xlsx'
    else:
        database = database_or_run
    workbook = _workbook(inputs) if inputs is not None else None
    if checks is None and workbook is not None and options.get('benchmark') is None:
        from database_disaggregation import SplitPlan
        planned = set(SplitPlan.read(workbook).sectors)
        sectors = sorted(planned.intersection(database.get_index('Sector')))
        checks = analysis.check_targets(database, workbook, sectors=sectors)
    return reporting.write_dashboard(database, path, checks=checks, workbook=workbook, **options)


def run(database, inputs, *, directory, solver=None, solver_parameters=None,
        model_options=None, dashboard=True):
    """Run the same explicit one-problem stages in a new experiment directory.

    ``model_options`` contains arguments to ``build_model`` (for example
    ``split_model_options``). Parsing, regional aggregation and preparation stay
    explicit upstream. Failures leave their generated solver files for review.
    Return the exported run path; dashboard is optional.
    """
    directory = Path(directory).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=False)
    model = build_model(database, inputs, directory=directory/'model', **(model_options or {}))
    solution = solve_model(model, solver=solver, solver_parameters=solver_parameters)
    result = assemble_database(solution)
    exported = export_database(result, directory/'database', inputs=inputs)
    if dashboard:
        build_dashboard(exported, directory/'dashboard.html')
    return exported
