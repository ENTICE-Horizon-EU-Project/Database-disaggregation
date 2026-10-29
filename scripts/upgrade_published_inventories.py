"""Upgrade a legacy published input package; never run the optimisation model."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

from database_disaggregation.core.inventory_history import assemble_inventory_history, checkpoint_history
from database_disaggregation.core.paths import project_data_root


def upgrade(database):
    database = Path(database).resolve()
    run = json.loads((database/'run.json').read_text())
    if run['status'] != 'accepted':
        raise ValueError('Only accepted published databases can be upgraded.')
    inventory = (database/run['inventory_directory']).resolve()
    if (inventory/'inventory_manifest.json').exists() or (inventory/'step_add_sectors.xlsx').exists():
        raise FileExistsError(f'Package already upgraded or has an archive: {inventory}')
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    # All existing database files (including reports), and archived source/resume
    # inputs, must remain identical during this input-only migration.
    originals = {p: digest(p) for folder in (database, inventory) for p in folder.rglob('*')
                 if p.is_file() and (folder == database or p.name != 'README.md')}
    with tempfile.TemporaryDirectory(prefix='.cumulative-', dir=inventory.parent) as work:
        work = Path(work)
        manifest = assemble_inventory_history(checkpoint_history(database), work/'add_sectors.xlsx')
        old_digest = digest(inventory/'add_sectors.xlsx')
        for record in manifest['stages']:
            applied = Path(record['applied']['path'])
            archive = applied.with_name('step_add_sectors.xlsx')
            if archive.is_file() or applied.parent == inventory:
                record['applied']['path'] = str(archive)
            for role in ('source', 'applied'):
                record[role]['path'] = os.path.relpath(record[role]['path'], inventory)
        manifest.update(assembled_at=datetime.now(timezone.utc).isoformat(),
                        path_base='inventory_directory', original_last_step_sha256=old_digest,
                        database_files_unchanged=True)
        (work/'inventory_manifest.json').write_text(json.dumps(manifest, indent=2, allow_nan=False))
        if any(digest(p) != h for p, h in originals.items()):
            raise RuntimeError('An original file changed during assembly.')
        shutil.copy2(inventory/'add_sectors.xlsx', inventory/'step_add_sectors.xlsx')
        if digest(inventory/'step_add_sectors.xlsx') != old_digest:
            raise RuntimeError('Last-step archive copy failed.')
        os.replace(work/'add_sectors.xlsx', inventory/'add_sectors.xlsx')
        os.replace(work/'inventory_manifest.json', inventory/'inventory_manifest.json')
    (inventory/'README.md').write_text(
        f'# {inventory.name} — MARIO inputs\n\n'
        f'Completed children: **{len(manifest["completed_sectors"])}**. '
        f'Full editable plan: **{len(manifest["planned_sectors"])}** children; '
        f'{manifest["profiles"]} region/sector inventories.\n\n'
        '- `add_sectors.xlsx`: cumulative inputs and the `Intermediate steps` plan, '
        'including pending sectors from the latest source if any.\n'
        '- `step_add_sectors.xlsx`: exact original compiled input of the last accepted step.\n'
        '- `source_add_sectors.xlsx`: unchanged original source of that trial. '
        'For a resumed trial this can be incremental.\n'
        '- `remaining_add_sectors.xlsx`: unchanged pending inputs; empty when complete.\n'
        '- `inventory_manifest.json`: coverage, source hashes and verification.\n\n'
        'The cumulative input is assembled from accepted stages and uses the targets '
        'actually selected for each group. Every group was recompiled and compared with '
        'its saved input, including finer supplier observations. No model was rerun; '
        'all database files, source and remaining workbooks are unchanged.\n\n'
        'This assembled reference is not a new optimisation or exact numerical replay. '
        'Historical reproduction requires the original stage inputs and recorded model revision. '
        'The checkpoint and `run.json` retain their original provenance.\n')
    for p, h in originals.items():
        if p != inventory/'add_sectors.xlsx' and digest(p) != h:
            raise RuntimeError(f'Original file changed: {p}')
    print(f'{inventory.name}: {len(manifest["planned_sectors"])} planned, '
          f'{len(manifest["completed_sectors"])} completed; database and archives unchanged.', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True, action='append',
                        help='Accepted shared database; repeat in chronological order for a chain.')
    args = parser.parse_args()
    for path in args.database:
        upgrade(path if path.is_absolute() else project_data_root(required=True)/path)


if __name__ == '__main__':
    main()
