"""Publish paired MARIO inputs and flat databases to the shared project data."""
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from zoneinfo import ZoneInfo

from database_disaggregation.core.paths import data_path


MODEL_DIAGNOSTICS = (
    'feasibility.json', 'model_solution.json', 'split_model_options.json',
    'entropy_support.json', 'model_definition.json', 'constraint_diagnostics.json',
    'raw_model_solution.json', 'raw_constraint_diagnostics.json',
    'solution_cleanup.json', 'solution_cleanup.csv',
    'returned_solution_scaled.npz', 'returned_solution_index.json',
    'cleaned_solution_scaled.npz', 'cleaned_solution_index.json', 'solver_replay.json',
)


def run_name(started_at, regions, sectors):
    """Use the original start, in project time, once for both output folders."""
    if isinstance(started_at,str):
        started_at=datetime.fromisoformat(started_at)
    if started_at.tzinfo is None or regions<1 or sectors<1:
        raise ValueError('A run needs a timezone-aware start and positive region/sector counts.')
    return f'{started_at.astimezone(ZoneInfo("Europe/Rome")):%Y%m%d %H%M} - {regions} regions and {sectors} sectors'


def remaining_workbook(checkpoint):
    checkpoint=Path(checkpoint)
    conventional=checkpoint/'remaining_add_sectors.xlsx'
    if conventional.is_file():
        return conventional
    publication=json.loads((checkpoint/'run.json').read_text())
    return (checkpoint/publication['inventory_directory']/'remaining_add_sectors.xlsx').resolve()


def _copy(source,destination):
    destination.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(source,destination)
    digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    if digest(source)!=digest(destination):
        raise RuntimeError(f'Copy checksum failed: {source}')


def publish_trial(trial, *, inventory_root=None, database_root=None):
    """Copy a finished controlled trial; never edit its inputs or checkpoints.

    Failed attempts keep diagnostics with their inputs and have no database folder.
    Existing published names are never overwritten. Computational caches stay
    in the ignored work directory; authoritative inputs/results live on WSP.
    """
    import pandas as pd
    trial=Path(trial).resolve()
    manifest=json.loads((trial/'trial.json').read_text())
    if manifest['status'] not in ('accepted','failed'):
        raise ValueError('Only finished trials can be published.')
    checkpoints=[Path(p) for p in manifest.get('accepted_checkpoints',[])]
    candidates=sorted((trial/'checkpoints').glob('*')) if (trial/'checkpoints').exists() else []
    step=checkpoints[-1] if checkpoints else next((p for p in candidates if (p/'step_add_sectors.xlsx').is_file()),None)
    source=Path(manifest.get('source_checkpoint',manifest.get('source_preparation','')))
    previous=json.loads((source/'state.json').read_text()) if (source/'state.json').is_file() else {}
    state=json.loads((step/'state.json').read_text()) if step and (step/'state.json').is_file() else None
    if manifest['status']=='accepted' and state is None:
        raise ValueError('An accepted controlled trial needs its completed checkpoint.')
    applied=step/'step_add_sectors.xlsx' if step else trial/'add_sectors.xlsx'
    master=pd.read_excel(applied,sheet_name='Master')
    pending=set(master.Sector.dropna())-set(previous.get('completed_sectors',[]))
    if not step and manifest.get('stop_after_step'):
        plan=pd.read_excel(applied,sheet_name='Intermediate steps')
        pending=set(plan[manifest['stop_after_step']].dropna())
    sectors=len(state['completed_sectors']) if state else len(set(previous.get('completed_sectors',[]))|pending)
    if state:
        x=pd.read_parquet(step/'database/flows/X.parquet')
    elif (source/'state.json').is_file():
        directory=source/previous.get('database_directory','database')
        x=pd.read_parquet(directory/'flows/X.parquet')
    else:
        x=pd.read_parquet(source/'baseline/flows/X.parquet')
    regions=len(x.index.get_level_values(0).unique())
    started=manifest.get('started_at')
    if not started:
        timestamp=getattr(trial.stat(),'st_birthtime',None)
        if timestamp is None:
            raise ValueError('Supply started_at for a historical trial without a birth timestamp.')
        started=datetime.fromtimestamp(timestamp,ZoneInfo('Europe/Rome')).isoformat()
    name=run_name(started,regions,sectors)
    inventory_root=Path(inventory_root) if inventory_root else data_path('split_inventory_runs')
    database_root=Path(database_root) if database_root else data_path('database_runs')
    inventory,database=inventory_root/name,database_root/name
    if inventory.exists() or database.exists():
        raise FileExistsError(f'Published run already exists: {name}')
    inventory_root.mkdir(parents=True,exist_ok=True);database_root.mkdir(parents=True,exist_ok=True)
    invstage=Path(tempfile.mkdtemp(prefix='.publishing-',dir=inventory_root))
    dbstage=Path(tempfile.mkdtemp(prefix='.publishing-',dir=database_root))
    record=dict(format='entice-shared-run-v1',name=name,started_at=started,status=manifest['status'],
                regions=regions,disaggregated_sectors=sectors,
                total_database_sectors=len(x.index.get_level_values(-1).unique()) if state else None,
                pending_recalculations=(state or {}).get('pending_recalculations',[]),
                inventory_directory=os.path.relpath(inventory,database),
                database_directory=os.path.relpath(database,inventory) if state else None,
                source_trial=str(trial),original_checkpoint=str(step) if state else None,
                source_checkpoint=str(source) if previous else None,
                source_run_manifest=manifest)
    validation = (state or {}).get('preservation', {}).get('numerical_validation')
    if validation:
        record['numerical_validation'] = validation
    try:
        if state:
            from database_disaggregation.core.inventory_history import checkpoint_history, assemble_inventory_history
            _copy(applied,invstage/'step_add_sectors.xlsx')
            coverage=assemble_inventory_history(checkpoint_history(step),invstage/'add_sectors.xlsx')
            (invstage/'inventory_manifest.json').write_text(json.dumps(coverage,indent=2,allow_nan=False))
            record['inventory_format']='cumulative-with-executed-plan-v1'
        else:
            _copy(applied,invstage/'add_sectors.xlsx')
        _copy(trial/'add_sectors.xlsx',invstage/'source_add_sectors.xlsx')
        if step and (step/'remaining_add_sectors.xlsx').is_file():
            _copy(step/'remaining_add_sectors.xlsx',invstage/'remaining_add_sectors.xlsx')
        if state:
            # Verify original checkpoint bytes before changing only its layout.
            for relative,digest in state['files'].items():
                path=step/relative
                if not path.resolve().is_relative_to(step.resolve()) or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
                    raise ValueError(f'Original checkpoint checksum failed: {relative}')
            for path in (step/'database').rglob('*'):
                if path.is_file():_copy(path,dbstage/path.relative_to(step/'database'))
            state=dict(state,database_directory='.',files={str(Path(k).relative_to('database')):v for k,v in state['files'].items()})
            (dbstage/'state.json').write_text(json.dumps(state,indent=2,allow_nan=False))
        diagnostics=dbstage/'diagnostics';diagnostics.mkdir()
        for path in trial.iterdir():
            if path.is_file() and path.suffix in ('.json','.log','.txt','.csv','.py','.patch'):
                _copy(path,diagnostics/path.name)
        prior_folder=Path(manifest.get('source_workbook','')).parent
        if (prior_folder/'reconciliation.json').is_file():
            for path in prior_folder.iterdir():
                if path.is_file() and path.suffix in ('.json','.csv','.py','.log'):
                    _copy(path,diagnostics/'trade_reconciliation'/path.name)
        if step:
            for name_in in MODEL_DIAGNOSTICS:
                for path in step.rglob(name_in):_copy(path,diagnostics/name_in)
        # Keep attempt diagnostics apart: a solver or objective fallback must
        # remain auditable after publication, without copying computational caches.
        if (trial/'attempts').is_dir():
            for path in (trial/'attempts').rglob('*'):
                if path.is_file() and (path.name in MODEL_DIAGNOSTICS or path.suffix == '.log'):
                    _copy(path,diagnostics/'attempts'/path.relative_to(trial/'attempts'))
        accepted_attempts = [a for a in manifest.get('model_attempts', [])
                             if a.get('status') == 'accepted' and state and a.get('step_index') == state['step_index']]
        if accepted_attempts:
            accepted_work = Path(accepted_attempts[-1]['work_directory'])
            for name_in in MODEL_DIAGNOSTICS:
                matches = list(accepted_work.rglob(name_in))
                if len(matches) > 1:
                    raise ValueError(f'Ambiguous accepted attempt diagnostic: {name_in}')
                if matches:
                    _copy(matches[0],diagnostics/name_in)
        if previous and (source/'run.json').is_file():
            record['source_database_directory']=os.path.relpath(source,database)
        if state:
            (invstage/'README.md').write_text(
                f'# {name} — MARIO inputs\n\n'
                '`add_sectors.xlsx` contains cumulative inputs and the editable `Intermediate steps` plan, '
                'including pending sectors from the latest source where applicable. The folder name counts '
                'completed children; see `inventory_manifest.json` for complete coverage and stage checks.\n\n'
                '`step_add_sectors.xlsx` is the exact compiled workbook of the last accepted step. '
                '`source_add_sectors.xlsx` is that trial’s original source, which may contain only pending children. '
                '`remaining_add_sectors.xlsx` contains only work still to do and is empty at completion.\n\n'
                'The cumulative workbook is assembled from accepted stages; no new model was solved. '
                'For exact historical replay retain the original stage workbooks and the recorded code revision.\n')
        for folder in (invstage,dbstage):
            (folder/'run.json').write_text(json.dumps(record,indent=2,allow_nan=False))
        (dbstage/'README.md').write_text(
            f'# {name}\n\nStatus: **{manifest["status"]}**. '
            +('MARIO matrices are in `flows/`; `state.json` supports checkpoint reload.\n' if state else 'No database was accepted for this attempt.\n')
            +'\nThe paired input folder is recorded in `run.json`. E recalculation status is recorded there and in the checkpoint.\n')
        if validation:
            note = (f'\nNumerical validation: **{validation["status"]}**. '
                    + ('Monetary residuals are diagnostic only; economic review is pending. Reference absolute tolerance: '
                     if validation.get('residuals_enforced') is False else 'Absolute accounting/reaggregation tolerance: ')
                    + f'{validation["absolute_tolerance_original_units"]} in original monetary units; '
                    f'relative tolerance: {validation["relative_tolerance"]}. '
                    'This result uses deterministic numerical cleanup; raw and cleaned points '
                    'and residuals are retained in diagnostics. E remains pending where recorded.\n')
            for folder in (invstage, dbstage):
                readme = folder / 'README.md'
                readme.write_text((readme.read_text() if readme.exists() else '') + note)
        if state:
            invstage.rename(inventory)
            try:dbstage.rename(database)
            except Exception:
                inventory.rename(invstage);raise
        else:
            (dbstage/'diagnostics').rename(invstage/'diagnostics')
            (dbstage/'README.md').rename(invstage/'README.md')
            invstage.rename(inventory)
            shutil.rmtree(dbstage)
    except Exception:
        shutil.rmtree(invstage,ignore_errors=True);shutil.rmtree(dbstage,ignore_errors=True);raise
    return dict(name=name,inventory=str(inventory.resolve()),database=str(database.resolve()) if state else None,status=manifest['status'])
