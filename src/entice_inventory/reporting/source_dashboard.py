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
from importlib.resources import files
from io import BytesIO, StringIO
import json
from pathlib import Path
import posixpath
import re
from xml.etree import ElementTree as ET
from zipfile import ZipFile

N = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
     'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
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


def _xlsx_tables(raw, names=None):
    with ZipFile(BytesIO(raw)) as book:
        shared = []
        if 'xl/sharedStrings.xml' in book.namelist():
            doc = ET.fromstring(book.read('xl/sharedStrings.xml'))
            shared = [''.join(t.text or '' for t in item.findall('.//s:t', N)) for item in doc]
        links = {r.get('Id'): r.get('Target') for r in ET.fromstring(book.read('xl/_rels/workbook.xml.rels'))}
        workbook = ET.fromstring(book.read('xl/workbook.xml'))
        for sheet in workbook.findall('s:sheets/s:sheet', N):
            if names is not None and sheet.get('name') not in names:
                continue
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
                                        expr = f'Shared formula {key}; definition at {origin}: {base}'
                                else:
                                    expr = f'Shared formula {key}'
                            formula = '=' + expr if expr else 'Formula without a saved expression'
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


def _values(table):
    return {n: {c: v for c, v, _ in cells} for n, cells in table['rows']}


def _template_clusters(tables):
    """Read definitions from this template only; retain source names and codes."""
    result = {'sectors': {}, 'regions': {}, 'factors': {}}
    for sheet, kind, custom_start in [('Sector', 'sectors', 369),
                                       ('Region', 'regions', 328),
                                       ('Primary input', 'factors', 17)]:
        if sheet not in tables:
            continue
        rows = _values(tables[sheet])
        codes = {}
        for number, row in rows.items():
            if number < 3:
                continue
            name = row.get(1) if kind == 'factors' else row.get(2)
            if name and row.get(3):
                codes.setdefault(str(name).strip(), []).append(str(row[3]).strip())
        current = None
        for number, row in rows.items():
            if number < 3:
                continue
            label, member = row.get(1), row.get(2)
            if number < custom_start:
                current = str(label).strip() if label else None
            elif label:
                current = str(label).strip()
            if not current or not member or current.upper() == 'GLOBAL':
                continue
            name = str(member).strip()
            definition = result[kind].setdefault(current, {
                'name': current, 'kind': kind, 'source': sheet,
                'members': [], 'note': ''})
            if not any(m['name'] == name for m in definition['members']):
                definition['members'].append({'name': name,
                    'code': ', '.join(dict.fromkeys(codes.get(name, [])))})
    result['regions']['GLOBAL'] = {'name': 'GLOBAL', 'kind': 'regions',
        'source': 'Region / source template convention', 'members': [],
        'note': 'GLOBAL is a catch-all identifier. Where other regions or origins '
                'are specified, it can refer to the remaining regions. The source '
                'does not provide a fixed member list for this label.'}
    return result


def _purdue_definitions(matching):
    """Use the repository's existing GTAPCE-to-GTAP12 classification."""
    from entice_inventory.core.paths import find_data_file
    from entice_inventory.core.matching_utils import load_matching_rows
    from entice_inventory.inventory.exioiot_to_inventory import (
        _build_sector_resolution, _build_factor_resolution)
    path = Path(matching) if matching is not None else find_data_file('GTAP12_matching.xlsx')
    result = {'sectors': {}, 'regions': {}, 'factors': {}}
    if not path.is_file():
        return result, {}
    sectors, factors = load_matching_rows(path)
    names = {r.entice_code.lower(): r.entice_name for r in sectors if r.entice_code}
    grouped_names = {}
    for row in sectors:
        if row.gtapce:
            grouped_names.setdefault(row.gtapce.lower(), set()).add(row.entice_name)
    for code, labels in grouped_names.items():
        if len(labels) == 1:
            names[code] = next(iter(labels))
        else:
            names.pop(code, None)  # An aggregate must not inherit one member's name.
    for kind, rows, builder in [('sectors', sectors, _build_sector_resolution),
                                 ('factors', factors, _build_factor_resolution)]:
        _, clusters = builder(rows)
        for name, members in clusters.items():
            result[kind][name] = {'name': name, 'kind': kind,
                'source': path.name + ' · GTAPCE → GTAP12',
                'members': [{'name': member, 'code': member} for member in members],
                'note': 'Repository classification mapping; values remain in their original source classification.'}
    return result, names


def _source_spec(path, relative):
    if path.name.startswith('Inventory_') and path.suffix.lower() == '.xlsx':
        return {'Total production': ('production', 'Total production', 'production'),
                'Unit process': ('costs', 'Cost structure', 'unit_process')}
    if 'purdue/' not in relative.lower():
        return {}
    return {
        'splttargs.xlsx': {'REPOUT': ('production', 'Purdue · reported output', 'repout'),
                          'BLTTRD': ('trades', 'Purdue · bilateral trade targets', 'blttrd')},
        'trade.xlsx': {'NTSCIF': ('trades', 'Purdue · trade flows at CIF prices', 'ntscif')},
        'exioiot.csv': {'Data': ('costs', 'Purdue · EXIOIOT', 'exioiot')},
        'copcosts.csv': {'Data': ('costs', 'Purdue · copper cost structures', 'copcosts')},
        'costsup.xlsx': {name: ('costs', 'Purdue · ' + name, name.lower())
                        for name in ('NFCOSTSHR', 'PFCOSTSHR', 'KFCOSTSHR')},
    }.get(path.name.lower(), {})


def write_source_dashboard(source_dir, output, *, matching=None, progress=None):
    """Write one English source-data explorer: production, trade and cost inputs.

    Values and formulas remain as saved. Only relevant data tables are exposed;
    workbook definitions supply scoped, clickable cluster memberships. No model
    result is loaded. ``matching`` optionally
    selects the GTAPCE/GTAP12 workbook used to explain Purdue input clusters.
    """
    source_dir, output = Path(source_dir).resolve(), Path(output)
    if not source_dir.is_dir():
        raise NotADirectoryError(source_dir)
    paths = sorted((p for p in source_dir.rglob('*') if p.is_file()
        and not any(part.startswith(('.', '~$')) for part in p.relative_to(source_dir).parts)),
        key=lambda p: str(p.relative_to(source_dir)).casefold())
    records, datasets, chunks, baseline_names = [], [], {}, {}
    purdue_clusters, sector_names = _purdue_definitions(matching)
    for path in paths:
        relative = path.relative_to(source_dir).as_posix()
        spec = _source_spec(path, relative)
        if not spec:
            continue
        if progress:
            progress(relative)
        raw = path.read_bytes()
        partner = path.name.startswith('Inventory_')
        record = {'id': len(records), 'name': path.name, 'path': relative,
            'title': path.stem.removeprefix('Inventory_').replace('_', ' '),
            'sha256': hashlib.sha256(raw).hexdigest(), 'uri': path.as_uri(),
            'info': {}, 'partner_template': partner, 'clusters': {}}
        records.append(record)
        try:
            requested = set(spec) | ({'General info', 'Sector', 'Region', 'Primary input'} if partner else set())
            tables = dict(_xlsx_tables(raw, requested)) if path.suffix.lower() == '.xlsx' else {'Data': _csv_table(raw)}
            record['info'] = _general_info(tables['General info']) if 'General info' in tables else {}
            record['contributor'] = record['info'].get('Lead', 'Unspecified') if partner else 'PURDUE'
            record['clusters'] = _template_clusters(tables) if partner else purdue_clusters
            if partner and 'Sector' in tables:
                for number, row in _values(tables['Sector']).items():
                    if number >= 3 and row.get(3) and row.get(4):
                        baseline_names.setdefault(str(row[3]), str(row[4]))
            for sheet, (category, title, layout) in spec.items():
                if sheet not in tables:
                    continue
                table = tables[sheet]
                payload = json.dumps(table, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
                key = hashlib.sha256(payload).hexdigest()[:24]
                if key not in chunks:
                    chunks[key] = base64.b64encode(gzip.compress(payload, compresslevel=6, mtime=0)).decode('ascii')
                datasets.append({'id': len(datasets), 'file': record['id'],
                    'title': record['title'] if partner else title,
                    'category': category, 'layout': layout, 'sheet': sheet,
                    'key': key, 'rows': len(table['rows']), 'formulas': table['formula_count']})
        except Exception as exc:
            raise ValueError(f'Unable to read {relative}: {exc}') from exc
    if not datasets:
        raise ValueError('No production, trade or cost-structure data found.')
    for definition in purdue_clusters['sectors'].values():
        for member in definition['members']:
            member['name'] = baseline_names.get(member['code'], member['name'])
    resource = files(__package__)
    manifest = json.dumps({'files': records, 'datasets': datasets,
        'sector_names': sector_names, 'folder': str(source_dir)},
        ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')
    page = resource.joinpath('templates/source_dashboard.html').read_text()
    logo = 'data:image/svg+xml;base64,' + base64.b64encode(resource.joinpath('assets/entice.svg').read_bytes()).decode('ascii')
    data = ''.join(f'<script type="application/octet-stream" id="chunk-{key}">{value}</script>' for key, value in chunks.items())
    replacements = {'__ENTICE_LOGO__': logo, '__MANIFEST__': manifest,
        '__TABLE_CHUNKS__': data, '__EXPLORER_SCRIPT__': resource.joinpath('templates/source_dashboard.js').read_text()}
    for token, value in replacements.items():
        page = page.replace(token, value)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(page, encoding='utf-8')
    return output
