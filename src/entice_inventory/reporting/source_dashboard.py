"""A standalone, read-only catalogue/table viewer for collected source files.

No MARIO result or solver is loaded. Workbooks are read from their stored XML
values and formulas; formulas are displayed, never evaluated. Large tables are
compressed separately and opened on demand by the browser.
"""
from __future__ import annotations

import base64
import csv
import gzip
import hashlib
import html
from importlib.resources import files
from io import BytesIO, StringIO
import json
from pathlib import Path, PurePosixPath
import posixpath
import re
from xml.etree import ElementTree as ET
from zipfile import ZipFile

N = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
     'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
REL = 'http://schemas.openxmlformats.org/package/2006/relationships'
ROW = '{' + N['s'] + '}row'


def _column(address):
    match = re.match(r'([A-Za-z]+)', address)
    if not match:
        raise ValueError(f'Invalid Excel address: {address!r}')
    value = 0
    for char in match[1].upper():
        value = value * 26 + ord(char) - 64
    return value


def _cell_value(cell, shared):
    kind = cell.get('t', 'n')
    if kind == 'inlineStr':
        return ''.join(t.text or '' for t in cell.findall('.//s:t', N))
    value = cell.find('s:v', N)
    if value is None or value.text is None:
        return None
    if kind == 's':
        return shared[int(value.text)]
    if kind == 'b':
        return value.text == '1'
    return value.text  # Preserve stored precision, errors and source units.


def _xlsx_tables(raw):
    with ZipFile(BytesIO(raw)) as book:
        shared = []
        if 'xl/sharedStrings.xml' in book.namelist():
            doc = ET.fromstring(book.read('xl/sharedStrings.xml'))
            shared = [''.join(t.text or '' for t in item.findall('.//s:t', N)) for item in doc]
        links = {r.get('Id'): r.get('Target') for r in ET.fromstring(book.read('xl/_rels/workbook.xml.rels'))}
        workbook = ET.fromstring(book.read('xl/workbook.xml'))
        for sheet in workbook.findall('s:sheets/s:sheet', N):
            target = links[sheet.get('{' + N['r'] + '}id')]
            member = target.lstrip('/') if target.startswith('/') else posixpath.normpath('xl/' + target)
            if member not in book.namelist():
                # Chartsheets are catalogued without inventing a cell table.
                continue
            rows, columns, formulas, uncached = [], set(), 0, 0
            shared_formulas = {}
            with book.open(member) as stream:
                for _, row in ET.iterparse(stream, events=('end',)):
                    if row.tag != ROW:
                        continue
                    number = int(row.get('r'))
                    cells = []
                    for cell in row.findall('s:c', N):
                        coordinate = cell.get('r')
                        col = _column(coordinate)
                        value = _cell_value(cell, shared)
                        formula_node = cell.find('s:f', N)
                        formula = None
                        if formula_node is not None:
                            expr = formula_node.text
                            if formula_node.get('t') == 'shared':
                                key = formula_node.get('si')
                                if expr:
                                    shared_formulas[key] = (coordinate, expr)
                                elif key in shared_formulas:
                                    origin, base = shared_formulas[key]
                                    try:
                                        from openpyxl.formula.translate import Translator
                                        expr = Translator('=' + base, origin=origin).translate_formula(coordinate).lstrip('=')
                                    except Exception:
                                        expr = f'Formula condivisa {key}; definizione in {origin}: {base}'
                                else:
                                    expr = f'Formula condivisa {key}'
                            formula = '=' + expr if expr else 'Formula senza espressione salvata'
                            formulas += 1
                            uncached += value is None
                        if value is not None or formula is not None:
                            columns.add(col)
                            cells.append([col, value, formula])
                    if cells:
                        rows.append([number, cells])
                    row.clear()
            headers = [1, 2] if sheet.get('name') == 'Total production' else []
            if sheet.get('name') in {'REPOUT','BLTTRD','NTSCIF','NTSTAR','MTRAT','REG','REPSEC','NEWTRDSEC','GlobalSet',
                                     'NFCOSTSHR','PFCOSTSHR','KFCOSTSHR','NFCOSTS','PFCOSTS','KFCOSTS','GCEROWS',
                                     'MUTSEC','MINMSEC','SUPCATS','FRTCOM','CRPSEC','CMDEMD','COPSEC'}:
                headers = [1]
            yield sheet.get('name'), {'columns': sorted(columns), 'rows': rows, 'header_rows': headers,
                'formula_count': formulas, 'uncached_formulas': uncached,
                'hidden': sheet.get('state', 'visible') != 'visible'}


def _csv_table(raw):
    try:
        text = raw.decode('utf-8-sig')
        encoding = 'UTF-8'
    except UnicodeDecodeError:
        text = raw.decode('cp1252')
        encoding = 'Windows-1252'
    try:
        dialect = csv.Sniffer().sniff(text[:8192], delimiters=',;\t')
    except csv.Error:
        dialect = csv.excel
    rows, columns = [], set()
    for number, row in enumerate(csv.reader(StringIO(text, newline=''), dialect=dialect), 1):
        cells = [[i, value, None] for i, value in enumerate(row, 1) if value != '']
        if cells:
            columns.update(c[0] for c in cells)
            rows.append([number, cells])
    return {'columns': sorted(columns), 'rows': rows, 'header_rows': [1],
            'formula_count': 0, 'uncached_formulas': 0, 'hidden': False, 'encoding': encoding}


def _general_info(table):
    result = {}
    for _, cells in table['rows']:
        values = {c: v for c, v, _ in cells}
        label, value = values.get(1), values.get(4)
        if label in {'Lead', 'New sector', 'Parent sector', 'Version'} and value is not None:
            result[label] = value
    return result


def write_source_dashboard(source_dir, output, *, database_url=None, progress=None):
    """Catalogue every file and embed complete saved Excel/CSV cell tables.

    Source files are never changed. GDX and other binary formats remain in the
    catalogue, with links to matching Excel/CSV files when present. The only
    output is the requested standalone HTML. ``progress(relative_path)`` is an
    optional callback; no companion reports or caches are created.
    """
    source_dir, output = Path(source_dir).resolve(), Path(output)
    if not source_dir.is_dir():
        raise NotADirectoryError(source_dir)
    paths = sorted((p for p in source_dir.rglob('*') if p.is_file()
        and not any(part.startswith(('.', '~$')) for part in p.relative_to(source_dir).parts)),
        key=lambda p: str(p.relative_to(source_dir)).casefold())
    if not paths:
        raise ValueError('No source files found.')
    records, chunks = [], {}
    for path in paths:
        relative = path.relative_to(source_dir).as_posix()
        if progress:
            progress(relative)
        raw = path.read_bytes()
        record = {'id': len(records), 'name': path.name, 'path': relative,
            'title': path.stem.removeprefix('Inventory_').replace('_', ' '),
            'kind': 'Inventari' if path.name.startswith('Inventory_') else 'Purdue' if 'PURDUE' in relative.upper() else 'Altri',
            'extension': path.suffix.lower().lstrip('.'), 'size': len(raw),
            'sha256': hashlib.sha256(raw).hexdigest(), 'uri': path.as_uri(),
            'tables': [], 'info': {}}
        try:
            tables = _xlsx_tables(raw) if path.suffix.lower() == '.xlsx' else [('Dati', _csv_table(raw))] if path.suffix.lower() == '.csv' else []
            for name, table in tables:
                if name == 'General info':
                    record['info'] = _general_info(table)
                payload = json.dumps(table, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
                key = hashlib.sha256(payload).hexdigest()[:24]
                if key not in chunks:
                    chunks[key] = base64.b64encode(gzip.compress(payload, compresslevel=6, mtime=0)).decode('ascii')
                record['tables'].append({'name': name, 'key': key, 'rows': len(table['rows']),
                    'columns': len(table['columns']), 'formulas': table['formula_count'],
                    'uncached': table['uncached_formulas'], 'hidden': table['hidden']})
        except Exception as exc:
            record['error'] = f'{type(exc).__name__}: {exc}'
        records.append(record)
    for record in records:
        record['alternatives'] = [r['id'] for r in records if r['id'] != record['id']
            and str(PurePosixPath(r['path']).with_suffix('')) == str(PurePosixPath(record['path']).with_suffix(''))
            and r['tables']]
    resource = files(__package__)
    manifest = json.dumps({'files': records, 'folder': str(source_dir)}, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')
    page = resource.joinpath('templates/source_dashboard.html').read_text()
    logo = 'data:image/svg+xml;base64,' + base64.b64encode(resource.joinpath('assets/entice.svg').read_bytes()).decode('ascii')
    data = ''.join(f'<script type="application/octet-stream" id="chunk-{key}">{value}</script>' for key, value in chunks.items())
    script = resource.joinpath('templates/source_dashboard.js').read_text()
    replacements = {'__ENTICE_LOGO__': logo, '__MANIFEST__': manifest, '__TABLE_CHUNKS__': data,
        '__EXPLORER_SCRIPT__': script, '__DATABASE_LINK__':
        '<a class="database-link" href="' + html.escape(str(database_url), quote=True) + '">Database disaggregato ↗</a>' if database_url else ''}
    for token, value in replacements.items():
        page = page.replace(token, value)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(page, encoding='utf-8')
    return output
