"""Consolidate saved NCM/NMC accounts, rebuild offline reports and GDX; no solve."""
import argparse
from copy import deepcopy
from datetime import datetime,timezone
import gc
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import time

import numpy as np
import pandas as pd

from database_disaggregation.core.benchmark import fingerprints,sha256,write_report
from database_disaggregation.core.paths import PROJECT_ROOT,local_config
from database_disaggregation.reconciliation.saved_identity import aggregate_database,aggregate_flow,merge_state
from database_disaggregation.reporting.saved_gdx import export_saved_gdx


def consolidate(source,output,*,aliases=None):
    import mario
    aliases=aliases or {'NCM':'NMC'}
    source,output=Path(source).resolve(),Path(output).resolve()
    if output.exists():raise FileExistsError('Use a fresh result directory; the predecessor remains immutable.')
    before=fingerprints(source);tick=time.monotonic()
    original_state=json.loads((source/'state.json').read_text())
    if original_state.get('format')!='entice-finalized-database-v1':
        raise ValueError('This command operates on a finalized monetary IOT.')
    state=merge_state(original_state,aliases)
    old_report=json.loads((source/'benchmarking.json').read_text())
    for relative,digest in original_state['files'].items():
        if sha256(source/relative)!=digest:raise ValueError(f'Source checkpoint hash differs: {relative}')
    print('Load saved flows and aggregate sector identities through MARIO; no solver.',flush=True)
    db=mario.parse_from_parquet(str(source/'flows'),table='IOT',mode='flows')
    production=pd.read_parquet(source/'flows/X.parquet')
    db.set_block('X',production.reindex(db.query('Z').index),scenario='baseline')
    totals={s:float(production.xs(s,level=-1).sum().iloc[0]) for s in set(aliases)|set(aliases.values())}
    aggregate_database(db,aliases)
    output.mkdir(parents=True,exist_ok=False)
    try:
        print('Export aggregated flows and production-weighted coefficients.',flush=True)
        db.to_parquet(path=output,flows=True,coefficients=True,include_meta=True)
        (output/'coefficients/e.parquet').unlink(missing_ok=True)
        checks={}
        del db;gc.collect()
        for path in sorted((source/'flows').glob('*.parquet')):
            if path.stem=='units':continue
            original=pd.read_parquet(path);expected=aggregate_flow(original,aliases)
            actual=pd.read_parquet(output/'flows'/path.name).reindex(index=expected.index,columns=expected.columns)
            if actual.shape!=expected.shape or not np.allclose(actual,expected,rtol=1e-13,atol=1e-12,equal_nan=True):
                raise ValueError(f'Independent aggregation differs for {path.stem}')
            difference=float(np.nanmax(np.abs(actual.to_numpy()-expected.to_numpy())))
            checks[path.stem]={'max_absolute_difference':difference,'unit':'row-specific' if path.stem in ['E','EY'] else 'M USD'}
            if path.stem in ['X','V','Y']:
                old=math.fsum(original.to_numpy().ravel());new=math.fsum(actual.to_numpy().ravel())
                if not math.isclose(old,new,rel_tol=1e-14,abs_tol=1e-6):raise ValueError(f'Global total changed: {path.stem}')
                checks[path.stem].update(global_before=old,global_after=new,global_difference_USD=(new-old)*1e6)
            del original,expected,actual;gc.collect()
        for name in ['z','v']:
            frame=pd.read_parquet(output/'coefficients'/f'{name}.parquet')
            if not np.isfinite(frame.to_numpy()).all():raise ValueError(f'Nonfinite coefficients {name}')
            del frame
        diagnostics=output/'diagnostics/provenance';diagnostics.mkdir(parents=True)
        for name in ['region-names.csv','geography.json','additional-sectors-13.json']:
            shutil.copy2(source/'diagnostics/provenance'/name,diagnostics/name)
        shutil.copy2(__file__,diagnostics/Path(__file__).name)
        from database_disaggregation.reconciliation import saved_identity
        shutil.copy2(saved_identity.__file__,diagnostics/'saved_identity.py')
        operation={'format':'entice-saved-identity-consolidation-v1','aliases':aliases,
            'source_database':str(source),'source_sha256':before,'original_sector_output_MUSD':totals,
            'method':'MARIO aggregate on every monetary flow axis; independent X summed and restored; z/v regenerated from aggregated flows and X',
            'model_rerun':False,'io_quantities_resolved':False,'all_flows_retained':True,
            'global_totals_verified':True,'flow_checks':checks,'created_at':datetime.now(timezone.utc).isoformat()}
        state.update(source_database_directory=os.path.relpath(source,output),source_sha256=before,
            identity_consolidation=operation,
            files={str(p.relative_to(output)):sha256(p) for directory in ['flows','coefficients'] for p in sorted((output/directory).glob('*.parquet'))})
        (output/'state.json').write_text(json.dumps(state,indent=2,allow_nan=False)+'\n')
        run=json.loads((source/'run.json').read_text());run.update(total_database_sectors=len(pd.read_parquet(output/'flows/X.parquet').index.get_level_values(-1).unique()),
            disaggregated_sectors=len(state['completed_sectors']),source_database_directory=os.path.relpath(source,output),
            postprocessing='NCM/NMC identity consolidation',model_rerun=False,io_system_recomputed=False)
        (output/'run.json').write_text(json.dumps(run,indent=2)+'\n')
        for name in ['activation-policy.json','activated-accounts.parquet','production-changes.csv','regional-sourcing.parquet','finalization-report.json']:
            # These are labelled predecessor evidence, not newly generated 144-sector tables.
            if (source/name).exists():
                folder=diagnostics/'pre-consolidation';folder.mkdir(exist_ok=True)
                shutil.copy2(source/name,folder/name)
        return finish_consolidation(source,output)
    except Exception:
        (output/'INCOMPLETE.txt').write_text('Consolidation failed. Predecessor unchanged; do not use this partial output.\n')
        raise


def finish_consolidation(source,output):
    """Resume exports from verified aggregated flows, without repeating MARIO."""
    import mario
    source,output=Path(source).resolve(),Path(output).resolve()
    state=json.loads((output/'state.json').read_text())
    operation=state['identity_consolidation'];before=operation['source_sha256']
    if fingerprints(source)!=before:raise ValueError('Predecessor changed before report refresh.')
    for relative,digest in state['files'].items():
        if sha256(output/relative)!=digest:raise ValueError(f'Aggregated checkpoint hash failed: {relative}')
    original_state=json.loads((source/'state.json').read_text())
    old_report=json.loads((source/'benchmarking.json').read_text())
    run=json.loads((output/'run.json').read_text())
    aliases=operation['aliases'];checks=operation['flow_checks'];totals=operation['original_sector_output_MUSD']
    tick=time.monotonic()
    print('Rebuild benchmarks and 2023 comparisons from checksum-verified caches.',flush=True)
    spec=importlib.util.spec_from_file_location('refresh_saved_dashboard',PROJECT_ROOT/'scripts/refresh_saved_dashboard.py')
    refresh=importlib.util.module_from_spec(spec);spec.loader.exec_module(refresh)
    report=refresh.refresh(output,source/'reference-benchmarks',source/'diagnostics/provenance/geography.json',
        Path(local_config().get('mario_source',Path(mario.__file__).parents[1])),PROJECT_ROOT/'data/benchmarking/comparison_baskets.json',
        baseline_path=Path(old_report['provenance']['baseline']),region_names_path=source/'diagnostics/provenance/region-names.csv')
    from database_disaggregation.reconciliation.saved_identity import consolidate_finalization
    finalization=consolidate_finalization(old_report['finalization'],aliases,report['dimensions']['regions'],len(original_state['completed_sectors']))
    report['finalization']=finalization
    report['identity_consolidation']=operation
    for code in aliases:
        if code in report['dimensions']['sector_names'] and code not in report['dimensions']['sectors']:
            report['dimensions']['sector_names'].pop(code,None)
    report['targets']['note']='Historical disaggregation inputs. Aliased observations are summed with original file/cell lineage; they were not jointly imposed on this postprocessed scenario.'
    write_report(report,output/'benchmarking.html',overwrite=True)
    checkpath=output/'reference-benchmarks/verification.json'
    check=json.loads(checkpath.read_text());check['outputs']['benchmarking.html']=sha256(output/'benchmarking.html');check['outputs']['benchmarking.json']=sha256(output/'benchmarking.json');checkpath.write_text(json.dumps(check,indent=2)+'\n')
    print('Export GDX and verify every exported cell.',flush=True)
    gdx=export_saved_gdx(output)
    if fingerprints(source)!=before:raise ValueError('Predecessor changed during consolidation.')
    operation.update(source_unchanged=True,elapsed_seconds=time.monotonic()-tick,
        regions=run['regions'],total_sectors=run['total_database_sectors'],added_sectors=run['disaggregated_sectors'],
        gdx_all_exported_cells_exact=all(x['roundtrip_exact'] for x in gdx['symbols'].values()))
    (output/'identity-consolidation.json').write_text(json.dumps(operation,indent=2,allow_nan=False)+'\n')
    (output/'README.md').write_text(f"# Canonical modelling database\n\n{run['regions']} regions, {run['total_database_sectors']} total sectors, {run['disaggregated_sectors']} added activities. NCM and NMC have been combined under NMC (Manufacture of NMC batteries), using MARIO aggregation. All flows are retained; global production, final demand and value added are conserved. Coefficients are calculated from aggregated flows and the summed independently recorded production. No optimisation or IO quantity solve was performed.\n\nPCP is Manufacture of coke; the P_C residual is Manufacture of petroleum products. The predecessor database is preserved at `{os.path.relpath(source,output)}`. Original step workbooks still use their historical sector identifiers; aggregated references carry both source files/cells. They are historical observations, not constraints of the postprocessed scenario.\n\n`diagnostics/provenance/pre-consolidation` preserves the activation evidence of the predecessor with 145 sectors. E was aggregated only to align its sector axis and remains pending recalculation; environmental coefficients are omitted. Economic validation remains pending. `identity-consolidation.json` records independent flow checks and GDX read-back.\n")
    files=['benchmarking.html','benchmarking.json','benchmarking-sectors.csv','database.gdx','database.gdx.json','identity-consolidation.json']
    (output/'exports.json').write_text(json.dumps({'format':'entice-canonical-exports-v1','model_rerun':False,
        'regions':run['regions'],'total_sectors':run['total_database_sectors'],'added_sectors':run['disaggregated_sectors'],
        'source_unchanged':True,'outputs':{name:{'sha256':sha256(output/name),'bytes':(output/name).stat().st_size} for name in files}},indent=2)+'\n')
    print(json.dumps({'output':str(output),'regions':run['regions'],'sectors':run['total_database_sectors'],'added_sectors':run['disaggregated_sectors'],'original_output_MUSD':totals,'flow_checks':checks},indent=2),flush=True)
    (output/'INCOMPLETE.txt').unlink(missing_ok=True)
    return operation


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();consolidate(args.database,args.output)
