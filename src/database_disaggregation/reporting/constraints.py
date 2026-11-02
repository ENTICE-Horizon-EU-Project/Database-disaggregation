"""Read effective step inputs without loading MARIO or invoking a solver."""
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
from zipfile import ZipFile
from collections import Counter
from xml.etree import ElementTree as ET

import numpy as np
import pandas as pd


def verify_workbook_input_parts(original, exported):
    """Allow SharePoint document metadata only; preserve every input byte.

    The immutable archive remains the source of the original workbook digest.
    Office may add custom XML/properties after an XLSX is synced to SharePoint.
    No worksheet, formula, style, existing relationship or input part may change.
    """
    if original == exported:
        return dict(byte_identical=True, input_parts_identical=True, metadata_changes=[])
    def signature(node):
        return (node.tag, tuple(sorted(node.attrib.items())), (node.text or '').strip(),
                tuple(signature(child) for child in node))
    def records(payload):
        root = ET.fromstring(payload)
        return root, Counter((child.tag, tuple(sorted(child.attrib.items()))) for child in root)
    changed = []
    with ZipFile(BytesIO(original)) as a, ZipFile(BytesIO(exported)) as b:
        before, after = set(a.namelist()), set(b.namelist())
        if before - after or any(not (name.startswith(('customXml/', '[trash]/')) or
                                      name == 'docProps/custom.xml') for name in after - before):
            raise ValueError('Exported effective input has removed or unexpected parts.')
        for name in sorted(before):
            left, right = a.read(name), b.read(name)
            if left == right:
                continue
            if name in ('[Content_Types].xml', '_rels/.rels', 'xl/_rels/workbook.xml.rels'):
                ar, ac = records(left); br, bc = records(right)
                if ar.tag != br.tag or ar.attrib != br.attrib or ac - bc:
                    raise ValueError('An existing input relationship changed.')
                for _, attrs in (bc - ac).elements():
                    attrs = dict(attrs)
                    if name == '[Content_Types].xml':
                        valid = attrs.get('PartName', '').startswith(('/customXml/', '/docProps/custom.xml'))
                    else:
                        valid = attrs.get('Type', '').endswith(('/customXml', '/custom-properties'))
                    if not valid:
                        raise ValueError('An added relationship is not Office document metadata.')
            elif name == 'docProps/core.xml' and signature(ET.fromstring(left)) == signature(ET.fromstring(right)):
                pass
            else:
                raise ValueError(f'Exported effective input data changed: {name}')
            changed.append(name)
    return dict(byte_identical=False, input_parts_identical=True, metadata_changes=changed)


def archived_constraints(database, *, export_inputs=None):
    """Return output and selected bilateral constraints, with cell provenance.

    Only accepted steps count. Domestic trade observations are not constraints:
    MARIO's Trade_selector explicitly disables same-region entries. A selected
    foreign route constrains the total Z+Y delivery, not its individual uses.
    """
    database = Path(database)
    state = json.loads((database / 'state.json').read_text())
    report_path = database / 'execution_report.json'
    if not report_path.exists():
        report_path = database / 'diagnostics/run_report.json'
    report = json.loads(report_path.read_text())
    archive = database / 'diagnostics/step-artifacts.zip'
    if not archive.exists():
        archive = database / 'diagnostics/exact-inputs.zip'
    accepted = [attempt for attempt in report['attempts'] if attempt['status'] == 'accepted']
    completed = [sector for attempt in accepted for sector in attempt['sectors']]
    if len(completed) != len(set(completed)) or set(completed) != set(state['completed_sectors']):
        raise ValueError('Accepted archived steps differ from the final checkpoint.')
    by_sector, records = {}, []
    with ZipFile(archive) as bundle:
        for attempt in accepted:
            member = f"{attempt['step_index']:03d}_{attempt['step'].replace(' ', '_')}/step_add_sectors.xlsx"
            payload = bundle.read(member)
            digest = sha256(payload).hexdigest()
            filename = f"{attempt['step_index']:03d}_{'-'.join(attempt['sectors'])}.xlsx"
            href = f'inputs/steps/{filename}'
            if export_inputs is not None:
                destination = Path(export_inputs) / filename
                destination.parent.mkdir(parents=True, exist_ok=True)
                if destination.exists():
                    verify_workbook_input_parts(payload, destination.read_bytes())
                else:
                    destination.write_bytes(payload)
            with pd.ExcelFile(BytesIO(payload)) as workbook:
                outputs = pd.read_excel(workbook, sheet_name='Total outputs')
                trades = pd.read_excel(workbook, sheet_name='Trades')
                tolerance = pd.read_excel(workbook, sheet_name='Tolerances')
            delta = dict(zip(tolerance.iloc[:, 0], tolerance.iloc[:, 1])).get('delta')
            if delta is None or not np.isfinite(delta) or not 0 <= delta < 1:
                raise ValueError('Unknown trade-constraint band in effective step input.')
            for sector in attempt['sectors']:
                by_sector[sector] = dict(constraints_verified=True, step=attempt['step'],
                    step_index=attempt['step_index'], input_href=href, archive_member=member,
                    input_sha256=digest, output_targets={}, output_cells={},
                    trade_targets={}, trade_cells={}, trade_delta=float(delta),
                    trade_scope='bilateral total of intermediate and all final-demand deliveries')
            for sheet, table, field in [('Total outputs', outputs, 'Sector'), ('Trades', trades, 'Sector_from')]:
                for position, row in table.iterrows():
                    if row[field] not in attempt['sectors']:
                        continue
                    if row['Unit'] != 'M USD' or not np.isfinite(row['Quantity']):
                        raise ValueError(f'Invalid effective constraint in {member}/{sheet}')
                    sector, quantity = row[field], float(row['Quantity'])
                    data = by_sector[sector]
                    cell = f"{sheet}!{'D' if sheet == 'Total outputs' else 'E'}{position + 2}"
                    if sheet == 'Total outputs':
                        region = str(row['Region'])
                        if region in data['output_targets']:
                            raise ValueError('Duplicate effective output constraint.')
                        data['output_targets'][region] = quantity
                        data['output_cells'][region] = cell
                        origin, destination, kind = region, '', 'Output'
                    else:
                        origin, destination = str(row['Region_from']), str(row['Region_to'])
                        if origin == destination:
                            continue
                        targets = data['trade_targets'].setdefault(origin, {})
                        if destination in targets:
                            raise ValueError('Duplicate effective bilateral constraint.')
                        targets[destination] = quantity
                        data['trade_cells'].setdefault(origin, {})[destination] = cell
                        kind = 'Trade'
                    records.append(dict(kind=kind, product=sector, origin=origin, destination=destination,
                        constraint=quantity, unit='M USD', scope='production' if kind == 'Output' else data['trade_scope'],
                        trade_delta=None if kind == 'Output' else float(delta), step=attempt['step'],
                        input_file=href, input_cell=cell, input_sha256=digest,
                        source='' if pd.isna(row.get('Source')) else str(row['Source']),
                        notes='' if pd.isna(row.get('Notes')) else str(row['Notes'])))
    return by_sector, pd.DataFrame(records)
