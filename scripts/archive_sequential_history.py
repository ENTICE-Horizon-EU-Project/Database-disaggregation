"""Archive accepted inputs and diagnostics without copying database matrices or solving."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import tempfile
import zipfile

from database_disaggregation.core.inventory_history import checkpoint_history
from database_disaggregation.core.shared_runs import MODEL_DIAGNOSTICS
from retry_sector_after_run import checkpoint_workbook


def digest(path):
    sha = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024*1024), b''):
            sha.update(chunk)
    return sha.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--additional-run', type=Path, action='append', default=[])
    args = parser.parse_args()
    root, output = args.run.resolve(), args.output.resolve()
    run = json.loads((root/'sequential-run.json').read_text())
    if run['status'] not in ('complete','partial') or not run['last_checkpoint']:
        raise ValueError('A finished run with an accepted checkpoint is required.')
    if output.exists() or output.with_suffix('.json').exists():
        raise FileExistsError(output)
    history = checkpoint_history(run['last_checkpoint'])
    if history[-1].state['completed_sectors'] != run['accepted_sectors']:
        raise ValueError('Checkpoint history does not match accepted children.')
    output.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(prefix='.'+output.name+'.', suffix='.part', dir=output.parent, delete=False)
    temporary = Path(handle.name)
    handle.close()
    files, accepted = {}, []
    batches = {root, *[p.resolve() for p in args.additional_run]}
    try:
        with zipfile.ZipFile(temporary, 'w', allowZip64=True) as archive:
            def add(source, name):
                source = Path(source)
                if not source.is_file():
                    return
                if name in files:
                    raise ValueError(f'Duplicate archive entry: {name}')
                before = digest(source)
                if source.suffix == '.log':
                    raw = source.read_text(errors='replace')
                    clean = re.sub(r'(LicenseID to value |License ID )\d+', r'\1[redacted]', raw)
                    payload = clean.encode()
                    archive.writestr(name, payload, compress_type=zipfile.ZIP_DEFLATED, compresslevel=1)
                    archived_sha = hashlib.sha256(payload).hexdigest()
                    redacted = raw != clean
                else:
                    compressed = source.suffix in ('.xlsx','.npz','.zip')
                    archive.write(source, name, compress_type=zipfile.ZIP_STORED if compressed else zipfile.ZIP_DEFLATED, compresslevel=1)
                    archived_sha, redacted = before, False
                if digest(source) != before:
                    raise RuntimeError(f'Immutable source changed: {source}')
                files[name] = dict(source=str(source), source_sha256=before, archived_sha256=archived_sha,
                                   source_bytes=source.stat().st_size, license_identifier_redacted=redacted)

            for number, stage in enumerate(history, 1):
                label = re.sub(r'[^A-Za-z0-9_-]+', '_', '_'.join(stage.state['step_sectors']))
                base = f'accepted/{number:03d}_{label}'
                trial = stage.checkpoint.parent.parent
                batch = trial.parent.parent if trial.parent.name == 'stages' else trial.parent
                batches.add(batch)
                source = checkpoint_workbook(stage.checkpoint)
                for required in (source, stage.applied, stage.checkpoint/'state.json'):
                    if not required.is_file():
                        raise FileNotFoundError(f'Required historical input is unavailable: {required}')
                add(source, base+'/exact_source_add_sectors.xlsx')
                add(stage.applied, base+'/compiled_step_add_sectors.xlsx')
                add(stage.checkpoint/'state.json', base+'/state.json')
                add(trial/'trial.json', base+'/trial.json')
                add(trial/'gurobi.log', base+'/gurobi.log')
                for name in MODEL_DIAGNOSTICS:
                    matches = list(stage.checkpoint.rglob(name))
                    if len(matches)>1:
                        raise ValueError(f'Ambiguous diagnostic {name} in {stage.checkpoint}')
                    if matches:
                        add(matches[0], base+'/diagnostics/'+name)
                accepted.append(dict(step=number,sectors=stage.state['step_sectors'],checkpoint=str(stage.checkpoint),
                                     exact_source=base+'/exact_source_add_sectors.xlsx',compiled=base+'/compiled_step_add_sectors.xlsx'))
            for batch in sorted(batches):
                base = 'batches/'+batch.name
                for name in ('sequential-run.json','split_model_options.json','solver_options.json','same-input-numerical-comparison.json','verification.json'):
                    add(batch/name, base+'/'+name)
                if (batch/'code').is_dir():
                    for path in sorted((batch/'code').rglob('*')):
                        if path.is_file() and path.suffix in ('.py','.json','.md','.patch'):
                            add(path, base+'/code/'+str(path.relative_to(batch/'code')))
                statefile = batch/'sequential-run.json'
                if statefile.is_file():
                    batchstate=json.loads(statefile.read_text())
                    for attempt in batchstate['attempts']:
                        if attempt['status']=='accepted':
                            continue
                        directory=Path(attempt['directory']); failed=base+'/failed/'+directory.name
                        for name in ('trial.json','add_sectors.xlsx','gurobi.log','reconciliation_failure.json'):
                            add(directory/name,failed+'/'+name)
                        if (directory/'reconciliation').is_dir():
                            for path in sorted((directory/'reconciliation').iterdir()):
                                if path.is_file() and path.suffix in ('.json','.csv','.npz','.xlsx'):
                                    add(path, failed+'/reconciliation/'+path.name)
            manifest=dict(format='entice-accepted-history-v1',run=str(root),accepted_sectors=run['accepted_sectors'],
                          completed_steps=accepted,batches=sorted(map(str,batches)),files=files,
                          original_sources_unchanged=True,optimization_rerun=False,
                          limitation='Historical audit package. Code identities/snapshots do not replace the frozen clean-replay release acceptance test.')
            archive.writestr('MANIFEST.json',json.dumps(manifest,indent=2)+'\n',compress_type=zipfile.ZIP_DEFLATED,compresslevel=1)
            archive.writestr('README.md',
                '# Accepted input history\n\nExact executed full workbooks, readable compiled steps, checkpoint states and available raw/cleaned solver diagnostics are retained for every accepted child. Failed attempts and recorded batch code snapshots are included. File identities are in MANIFEST.json. No complete intermediate database matrices, SQLite caches or optimization runs are copied or created. Raw and cleaned active-variable arrays remain available as diagnostics. Original baseline matrices and the final database are in the enclosing result package. A frozen clean baseline replay remains a separate release acceptance check.\n')
        with zipfile.ZipFile(temporary) as archive:
            for name, info in files.items():
                sha=hashlib.sha256()
                with archive.open(name) as stream:
                    for chunk in iter(lambda:stream.read(1024*1024),b''):
                        sha.update(chunk)
                if sha.hexdigest()!=info['archived_sha256']:
                    raise RuntimeError(f'Archive content verification failed: {name}')
        record=dict(format='entice-accepted-history-archive-v1',archive=str(output),sha256=digest(temporary),
                    bytes=temporary.stat().st_size,files=len(files),accepted_steps=len(history),
                    accepted_children=len(run['accepted_sectors']),all_archived_file_hashes_verified=True,
                    original_sources_unchanged=True,optimization_rerun=False)
        if output.exists():
            raise FileExistsError(output)
        temporary.rename(output)
        output.with_suffix('.json').write_text(json.dumps(record,indent=2)+'\n')
        print(json.dumps(record,indent=2))
    finally:
        temporary.unlink(missing_ok=True)


if __name__=='__main__':
    main()
