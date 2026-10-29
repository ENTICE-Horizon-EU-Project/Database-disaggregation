"""Refresh presentation from a saved benchmark, never from a solver."""
from pathlib import Path
from types import SimpleNamespace
import json
from .dashboard import dashboard_payload
from .render import render_dashboard

def benchmark_context(report):
    """Reuse declared identities and archived observations from a saved report."""
    labels=report['dimensions'].get('sector_names',{})
    base_labels=report['dimensions'].get('baseline_sector_names',labels)
    types={}
    for row in report['sectors']:
        kind='new' if row['is_child'] else 'residual_parent' if row['is_residual'] else 'original'
        types[row['sector']]=dict(kind=kind,label={'new':'New sector','residual_parent':'Residual parent','original':'Original sector'}[kind],
            parents=[dict(code=row['parent'],name=base_labels.get(row['parent'],row['parent']))] if row['is_child'] else [])
    return dict(labels=labels,sector_metadata=types,
                target_profiles=report['targets'].get('by_sector',{}),
                references=report.get('external_comparisons'))

def render_saved_dashboard(report, *, audit_stem="benchmarking"):
    from database_disaggregation.core.benchmark import Flows, fingerprints, prepared_targets
    root=Path(report['provenance']['database']);flows=Flows.read(root)
    if flows.hashes!=report['provenance']['database_sha256']:
        raise ValueError('Saved benchmark no longer matches its source matrices.')
    database=SimpleNamespace(Z=flows['Z'],Y=flows['Y'],X=flows['X'])
    database.get_index=lambda level:list(database.X.index.get_level_values(0 if level=='Region' else -1).unique())
    if 'by_sector' not in report['targets']:
        state_path=root/'state.json'
        if state_path.is_file() and (root/'diagnostics/exact-inputs.zip').is_file():
            try:
                _,targets,_,sources=prepared_targets(flows,json.loads(state_path.read_text()))
            except FileNotFoundError:
                report['targets']['presentation_note']='Archived inputs unavailable for per-sector target markers; previously recorded numerical checks retained.'
            else:
                if targets.get('status')=='checked':report['targets']['by_sector']=targets.get('by_sector',{})
    payload=dashboard_payload(database,**benchmark_context(report))
    if fingerprints(root)!=flows.hashes:
        raise RuntimeError('Source matrices changed while rendering the dashboard.')
    summary=report['summary']
    return render_dashboard(payload,title='Sector disaggregation results',
        subtitle=f"{summary['regions']} regions · {summary['final_sectors']} sectors · {summary['new_sectors']} added activities",benchmark=report,audit_stem=audit_stem)
