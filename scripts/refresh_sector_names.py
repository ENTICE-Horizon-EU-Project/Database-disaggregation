"""Refresh post-split display names on saved results, without solving a model.

Stable sector codes, flows, coefficients, baseline names and exact historical
inputs remain unchanged. GDX set descriptions can be refreshed with
export_saved_gdx.py --overwrite after this command.
"""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import shutil

from database_disaggregation.core.benchmark import fingerprints,sha256
from database_disaggregation.core.residual_labels import post_split_display_names
from database_disaggregation.reporting.saved import render_saved_dashboard


def refresh(database):
    database=Path(database).resolve()
    before=fingerprints(database)
    state=json.loads((database/'state.json').read_text())
    source=database/'benchmarking.json'
    report=json.loads(source.read_text())
    labels=report['dimensions']['sector_names']
    updated=post_split_display_names(labels,state['sector_parents'],state['completed_sectors'])
    changes={code:{'before':labels.get(code),'after':name} for code,name in updated.items() if labels.get(code)!=name}
    if not changes:
        return {'status':'unchanged','model_rerun':False}
    stamp=datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
    backup=database/'.archive'/f'{stamp}-sector-names'
    backup.mkdir(parents=True,exist_ok=False)
    for name in ['benchmarking.json','benchmarking.html','database.gdx.json','exports.json']:
        path=database/name
        if path.exists():shutil.copy2(path,backup/name)
    report['dimensions']['sector_names']=updated
    evidence={'format':'entice-sector-display-names-v1','generated_at':datetime.now(timezone.utc).isoformat(),
        'changes':changes,'model_rerun':False,'numerical_values_changed':False,
        'source_fingerprints':before,'backup':str(backup.relative_to(database))}
    report['provenance']['sector_display_name_update']=evidence
    html=render_saved_dashboard(report)
    if fingerprints(database)!=before:raise ValueError('Database changed during name refresh.')
    temp=database/'.benchmarking.names.tmp'
    temp.write_text(html);temp.replace(database/'benchmarking.html')
    temp=database/'.benchmarking.names.json.tmp'
    temp.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n');temp.replace(source)
    evidence['outputs']={name:sha256(database/name) for name in ['benchmarking.json','benchmarking.html']}
    (database/'sector-names.json').write_text(json.dumps(evidence,indent=2)+'\n')
    return evidence


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(refresh(args.database),indent=2))
