"""Publish a finished sequential build and its complete replay evidence.

This command reads saved results only. It never calls an optimisation solver.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil

from database_disaggregation.core.shared_runs import publish_trial, MODEL_DIAGNOSTICS


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path,required=True)
    args=parser.parse_args()
    root=args.run.resolve()
    state=json.loads((root/'sequential-run.json').read_text())
    if state['status'] not in ('complete','partial') or not state.get('last_accepted_trial'):
        raise ValueError('A finished build with at least one accepted stage is required.')
    pointer=root/'publication.json'
    if pointer.exists():
        raise FileExistsError('This build already has a publication record.')
    publication=publish_trial(state['last_accepted_trial'], started_at=state['started_at'])
    database=Path(publication['database'])
    evidence=database/'reproducibility'
    evidence.mkdir()
    shutil.copy2(root/'sequential-run.json',evidence/'sequential-run.json')
    shutil.copytree(root/'code',evidence/'code')
    for name in ('split_model_options.json','solver_options.json', 'resource-summary.json',
                 'resources.csv','prior-changes.md','global-preservation.json','build-summary.json','final-report.md'):
        if (root/name).is_file():
            shutil.copy2(root/name,evidence/name)
    shutil.copytree(root/'prepared',evidence/'initial-preparation')
    for stage in sorted((root/'stages').iterdir()):
        destination=evidence/'stages'/stage.name
        destination.mkdir(parents=True)
        for name in ('trial.json','add_sectors.xlsx','solver_cache_archive.json','reconciliation_failure.json'):
            if (stage/name).is_file():
                shutil.copy2(stage/name,destination/name)
        if (stage/'reconciliation').is_dir():
            shutil.copytree(stage/'reconciliation',destination/'reconciliation')
        for checkpoint in (stage/'checkpoints').iterdir() if (stage/'checkpoints').is_dir() else []:
            if not checkpoint.is_dir():
                continue
            step=destination/'checkpoints'/checkpoint.name
            step.mkdir(parents=True)
            for name in ('state.json','failure.json','step_add_sectors.xlsx','source_add_sectors.xlsx','remaining_add_sectors.xlsx'):
                if (checkpoint/name).is_file():
                    shutil.copy2(checkpoint/name,step/name)
            for name in MODEL_DIAGNOSTICS:
                for path in checkpoint.rglob(name):
                    shutil.copy2(path,step/name)
    log=root.with_suffix('.log')
    if log.is_file():
        text=log.read_text(errors='replace')
        text=re.sub(r'(LicenseID to value )\d+',r'\1[redacted]',text)
        text=re.sub(r'(License ID )[0-9]+',r'\1[redacted]',text)
        (evidence/'run.log').write_text(text)
    hashes={str(p.relative_to(evidence)):digest(p) for p in evidence.rglob('*') if p.is_file()}
    (evidence/'checksums.json').write_text(json.dumps(hashes,indent=2)+'\n')
    (evidence/'README.md').write_text(
        '# Sequential build evidence\n\n'
        'The initial preparation, exact options, code identities, and every stage input/trade audit are retained here. '
        'The final database is in the parent directory; its paired cumulative inventory is recorded in run.json. '
        'No model was run during publication.\n\n'
        'The authoritative execution order and accepted/failed children are in sequential-run.json. '
        'To rebuild, use initial-preparation/baseline/flows and its add_sectors.xlsx with the matching MARIO/CVXLab '
        'versions and run_sequential_model.py. Initial-preparation/trades_audit.csv and policy.json provide '
        'source confidence for the integrated projections. The copied runner snapshots are audit records; '
        'use the recorded repository checkout as the executable environment.\n\n'
        'Generated solver CSV/SQLite caches stay in verified local ZIP archives. They are not needed to rerun '
        'from the retained inputs. Historical intermediate database matrices stay in the local checkpoints. '
        'State files copied here are evidence, not standalone reloadable intermediate databases. '
        'E remains deferred where stated in the final checkpoint.\n\n'
        'Office synchronisation can add container metadata to XLSX files after publication. '
        'The numerical worksheet payload, not the later container byte hash alone, establishes input equivalence.\n')
    publication.update(sequential_status=state['status'],accepted_sectors=state['accepted_sectors'],
                       failed_sectors=state['failed_sectors'],reproducibility=str(evidence))
    pointer.write_text(json.dumps(publication,indent=2)+'\n')
    print(json.dumps(publication,indent=2))


if __name__=='__main__':
    main()
