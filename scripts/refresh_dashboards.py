"""Refresh saved database dashboards with the common MARIO workshop layout.

Reads saved matrices and cached comparisons only. No solver, source extraction,
data harmonisation or benchmark recomputation is performed.
"""
import argparse
from copy import deepcopy
from datetime import datetime,timezone
import json
import os
from pathlib import Path
from database_disaggregation.core.paths import project_data_root
from database_disaggregation.core.benchmark import write_report,sha256

def main():
    cli=argparse.ArgumentParser(description=__doc__)
    choice=cli.add_mutually_exclusive_group(required=True)
    choice.add_argument('--all',action='store_true',help='Refresh every saved benchmarking.json below Database.')
    choice.add_argument('--database',type=Path,help='One database folder, absolute or relative to configured Data split.')
    cli.add_argument('--overwrite',action='store_true',help='Replace only generated HTML/JSON/CSV reports.')
    args=cli.parse_args()
    if not args.overwrite:cli.error('Pass --overwrite to refresh generated report files.')
    if args.database:
        root=args.database if args.database.is_absolute() else project_data_root()/args.database
        reports=[root/'benchmarking.json']
    else:
        reports=[]
        for directory,folders,names in os.walk(project_data_root()/'Database'):
            folders[:]=[n for n in folders if n not in {'flows','baseline','references','reference-benchmarks','.archive','.git'}]
            if 'benchmarking.json' in names:reports.append(Path(directory)/'benchmarking.json')
    if not reports:raise FileNotFoundError('No saved benchmark reports found.')
    for path in sorted(reports):
        report=json.loads(path.read_text())
        frozen={key:deepcopy(report[key]) for key in ('summary','checks','sectors','baseline_sectors')}
        external=deepcopy(report.get('external_comparisons'))
        before=sha256(path)
        report['provenance'].update(presentation_refreshed_at=datetime.now(timezone.utc).isoformat(),
            presentation_source_report_sha256=before)
        write_report(report,path.with_suffix('.html'),overwrite=True)
        assert all(report[key]==value for key,value in frozen.items())
        assert report.get('external_comparisons')==external
        verification=path.parent/'reference-benchmarks/verification.json'
        if verification.is_file():
            proof=json.loads(verification.read_text())
            proof['presentation_refresh']=dict(style='MARIO workshop',model_rerun=False,
                numeric_benchmarks_unchanged=True,reference_values_unchanged=True,
                generated_at=report['provenance']['presentation_refreshed_at'])
            for name in proof.get('outputs',{}):proof['outputs'][name]=sha256(path.parent/name)
            verification.write_text(json.dumps(proof,indent=2)+'\n')
        print(str(path.with_suffix('.html')),flush=True)
    print(f'{len(reports)} dashboards refreshed. Saved numerical benchmarks and reference values unchanged; no solver or SSD read.',flush=True)
    return 0

if __name__=='__main__':raise SystemExit(main())
