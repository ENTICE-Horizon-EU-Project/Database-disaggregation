"""Copy an existing preparation; change only its one/two-sector execution plan."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from entice_inventory.reconciliation.factor_domains import _sheet_paths


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--sectors', nargs='+', required=True)
    args = p.parse_args()
    if len(args.sectors) not in (1, 2) or len(set(args.sectors)) != len(args.sectors):
        p.error('This bounded study permits only one or two sectors per solve.')
    source, output = args.source.resolve(), args.output.resolve()
    if output.exists() or source in output.parents:
        p.error('Use a fresh output outside the immutable preparation.')
    manifest = json.loads((source / 'preparation.json').read_text())
    sectors = [c for group in manifest['steps'].values() for c in group]
    if set(args.sectors) - set(sectors):
        p.error('Selected sectors are missing from the source preparation.')
    plan = {'Memory probe': args.sectors, 'Remaining sectors': [s for s in sectors if s not in args.sectors]}
    original = sha(source / 'add_sectors.xlsx')
    output.mkdir(parents=True)
    shutil.copytree(source / 'baseline', output / 'baseline')
    ns = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    ET.register_namespace('', ns)
    sheet = ET.Element('{'+ns+'}worksheet')
    data = ET.SubElement(sheet, '{'+ns+'}sheetData')
    for i in range(max(map(len, plan.values())) + 1):
        row = ET.SubElement(data, '{'+ns+'}row', {'r': str(i+1)})
        for j, (label, values) in enumerate(plan.items()):
            text = label if i == 0 else values[i-1] if i <= len(values) else None
            if text is None:
                continue
            cell = ET.SubElement(row, '{'+ns+'}c', {'r': chr(65+j)+str(i+1), 't': 'inlineStr'})
            ET.SubElement(ET.SubElement(cell, '{'+ns+'}is'), '{'+ns+'}t').text = text
    payload = ET.tostring(sheet, encoding='utf-8')
    with ZipFile(source / 'add_sectors.xlsx') as old, ZipFile(output / 'add_sectors.xlsx', 'w') as new:
        member = _sheet_paths(old)['Intermediate steps']
        for item in old.infolist():
            new.writestr(item, payload if item.filename == member else old.read(item.filename))
    with ZipFile(source / 'add_sectors.xlsx') as old, ZipFile(output / 'add_sectors.xlsx') as new:
        changed = [n for n in old.namelist() if old.read(n) != new.read(n)]
        assert changed == [member], changed
    assert sha(source / 'add_sectors.xlsx') == original
    manifest.update(steps=plan, memory_probe=dict(source_preparation=str(source),
        source_workbook_sha256=original, workbook_sha256=sha(output / 'add_sectors.xlsx'),
        changed_zip_members=changed, numerical_inputs_changed=False, original_workbook_unchanged=True))
    (output / 'preparation.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest['memory_probe'], indent=2))


if __name__ == '__main__':
    main()
