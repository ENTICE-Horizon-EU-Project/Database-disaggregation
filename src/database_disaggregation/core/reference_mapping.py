"""Source-referenced classification and geography audits; no economic allocation.

All sets are membership/candidate footprints. They must never be used as a
many-to-many multiplication matrix for monetary flows.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from collections import defaultdict
from pathlib import Path


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def hs_code(value):
    """Six-digit commodity identifiers, including numeric Excel source cells."""
    if value is None:
        raise ValueError('Missing HS code')
    text = str(value).strip()
    if re.fullmatch(r'\d+\.0', text):
        text = text[:-2]
    text = text.replace('.', '')
    if not text.isdigit() or not 5 <= len(text) <= 6:
        raise ValueError(f'Invalid HS6 identifier: {value!r}')
    return text.zfill(6)


def csv_rows(path):
    return list(csv.DictReader(Path(path).read_text(encoding='utf-8-sig').splitlines()))


def correlation_pairs(path, sheet):
    """Use correlations, never the lossy one-destination conversion sheet."""
    from openpyxl import load_workbook
    book = load_workbook(path, read_only=True, data_only=True)
    try:
        if 'correlation' not in sheet.casefold():
            raise ValueError('A correlation sheet is required, not a conversion sheet')
        result = []
        for number, row in enumerate(book[sheet].iter_rows(values_only=True), 1):
            try:
                left, right = hs_code(row[0]), hs_code(row[1])
            except ValueError:
                if number <= 2 or not any(v is not None for v in row):
                    continue
                raise ValueError(f'Invalid correlation row {number}: {row}')
            result.append((left, right, str(row[2] or 'unknown'), number))
        if not result:
            raise ValueError('Empty HS correlation table')
        return result
    finally:
        book.close()


def official_hs_routes(source_dir):
    """HS 2002/2012/2017/2022 → CPC2.1 → ISIC4 → NACE2, retaining routes."""
    source_dir = Path(source_dir)
    producer = defaultdict(list)
    for row in csv_rows(source_dir / 'cpc21-isic4.txt'):
        producer[row['CPC21code']].append(row)
    nace = defaultdict(list)
    for row in csv_rows(source_dir / 'nace2-isic4.txt'):
        if re.fullmatch(r'\d\d\.\d\d', row['NACE2code']):
            nace[row['ISIC4code']].append(row)
    routes = []
    for edition, filename in [('H5', 'cpc21-hs2017.csv'), ('H4', 'cpc21-hs2012.txt')]:
        for row in csv_rows(source_dir / filename):
            code = hs_code(row['HS 2017'] if edition == 'H5' else row['HS12code'])
            cpc = row['CPC Ver. 2.1'] if edition == 'H5' else row['CPC21code']
            hp = row['HS partial'] if edition == 'H5' else row['HS12partial']
            cp = row['CPC partial'] if edition == 'H5' else row['CPC21partial']
            for industry in producer[cpc]:
                for activity in nace[industry['ISIC4code']]:
                    routes.append(dict(hs_edition=edition, hs6=code, via_hs_edition=edition,
                        via_hs6=code, cpc21=cpc, isic4=industry['ISIC4code'],
                        nace2=activity['NACE2code'], hs_partial=int(hp), cpc_partial=int(cp),
                        cpc_to_isic_partial=int(industry['CPC21partial']),
                        isic_producer_partial=int(industry['ISIC4partial']),
                        nace_partial=int(activity['NACE2part']),
                        isic_to_nace_partial=int(activity['ISIC4part']),
                        revision_relationship='native', source_revision_relationship='native',
                        revision_traversal='native', revision_row=None,
                        relation='product_to_producing_activity', allocation_weight=None))
    by_h5 = defaultdict(list)
    for row in routes:
        if row['hs_edition'] == 'H5':
            by_h5[row['hs6']].append(row)
    revisions = [('H6', 'hs2022-hs2017.xlsx', 'HS2022-HS2017 Correlations', False),
                 ('H2', 'hs2017-hs2002.xlsx', 'Correlation HS17-HS02', True)]
    for edition, filename, sheet, reverse in revisions:
        for left, right, relation, number in correlation_pairs(source_dir / filename, sheet):
            code, via = (right, left) if reverse else (left, right)
            for base in by_h5[via]:
                routes.append({**base, 'hs_edition': edition, 'hs6': code,
                    'revision_relationship': {'1:n':'n:1','n:1':'1:n'}.get(relation,relation) if reverse else relation,
                    'source_revision_relationship': relation,
                    'revision_traversal': 'reverse' if reverse else 'forward',
                    'revision_row': number})
    # Multiple legitimate paths survive, but exact duplicate records do not.
    return list({json.dumps(r, sort_keys=True): r for r in routes}.values())


def nace_hierarchy(source_dir, names):
    nodes, section = {}, None
    for r in csv_rows(Path(source_dir) / 'nace2-isic4.txt'):
        code = r['NACE2code']
        if len(code) == 1 and code.isalpha():
            section = code
        parent = None if len(code) == 1 else section if len(code) == 2 else code[:2] if len(code) == 4 else code[:4]
        nodes[code] = dict(code=code, parent=parent, section=section,
                           name=names.get('NACE2:' + code, code))
    if sum(bool(re.fullmatch(r'\d\d\.\d\d', k)) for k in nodes) != 615:
        raise ValueError('NACE Rev. 2 class vocabulary changed')
    return nodes


def leaves(codes, nodes):
    result = set()
    for code in codes:
        if code not in nodes:
            raise ValueError(f'Unknown NACE Rev. 2 code: {code}')
        for candidate in nodes:
            if not re.fullmatch(r'\d\d\.\d\d', candidate):
                continue
            ancestors, cur = {candidate}, candidate
            while nodes[cur]['parent']:
                cur = nodes[cur]['parent']; ancestors.add(cur)
            if code in ancestors:
                result.add(candidate)
    return result


def common_ancestor(codes, nodes):
    if not codes:
        return None
    paths = []
    for code in codes:
        chain = [code]
        while nodes[chain[-1]]['parent']:
            chain.append(nodes[chain[-1]]['parent'])
        paths.append(chain[::-1])
    shared = None
    for level in zip(*paths):
        if len(set(level)) != 1:
            break
        shared = level[0]
    return shared


def comparison_envelope(target, records, nodes):
    """Smallest single NACE node closed under all intersecting known footprints.

    This is a classification limit, not certification of quantitative scope.
    Unknown and explicitly partial records cannot silently become zero flows.
    """
    anchor = common_ancestor(target, nodes)
    original = anchor
    while anchor:
        wanted = leaves([anchor], nodes)
        selected = [r for r in records if set(r['nace2_classes']) & wanted]
        union = wanted | {v for r in selected for v in r['nace2_classes']}
        next_anchor = common_ancestor(union, nodes)
        if next_anchor == anchor:
            covered = {v for r in selected for v in r['nace2_classes']}
            return dict(nace2_envelope=anchor, initial_nace2_envelope=original,
                native_codes=[r['native_code'] for r in selected],
                uncovered_classes=sorted(wanted-covered),
                qualifications=sorted({r['qualification'] for r in selected if r['qualification']}),
                status='candidate_classification_envelope' if selected else 'unavailable',
                quantitative_ready=False)
        anchor = next_anchor
    return dict(nace2_envelope=None, initial_nace2_envelope=original,
        native_codes=[r['native_code'] for r in records if set(r['nace2_classes']) & set(target)],
        uncovered_classes=[], qualifications=['Footprints cross NACE sections; no single closed NACE group.'],
        status='no_single_nace_envelope' if target else 'unavailable', quantitative_ready=False)


def partition_audit(regions):
    owners = defaultdict(list)
    for r in regions:
        for member in r['members']:
            owners[member].append(r['native_code'])
    return dict(overlaps={k: v for k, v in owners.items() if len(v) > 1},
                unresolved=[r['native_code'] for r in regions if not r['membership_complete']],
                member_count=len(owners))


def whole_region_selection(target_members, regions):
    """Select whole source regions only. No rest-of-world subdivision."""
    target = set(target_members)
    if not target:
        raise ValueError('Cannot select an empty geographic target')
    selected, split, covered = [], [], set()
    for r in regions:
        members = set(r['members'])
        overlap = target & members
        if not overlap:
            continue
        if r['membership_complete'] and members <= target:
            if covered & members:
                raise ValueError('Overlapping source regions in requested geography')
            selected.append(r['native_code']); covered |= members
        else:
            split.append(r['native_code'])
    missing = sorted(target-covered)
    return dict(native_regions=selected, source_regions_requiring_split=split,
                missing_members=missing, exact_on_declared_membership=not missing and not split,
                membership_basis='explicit_membership_only')


def footprint_from_explorer(item, revisions, nodes, *, product=False):
    """Stop existing routes at NACE2; invert 2.1 revision links explicitly if needed."""
    codes, paths, qualifications = set(), [], set()
    for key, link in item.get('links', {}).items():
        routes = [link, *link.get('alternatives', [])]
        for route in routes:
            prefix = [v[1] for v in route.get('nodes', []) if v[0] == 'NACE2']
            if not prefix:
                ref = key[:5] if product else key
                candidates = revisions.get(ref, [])
                prefix = [e['left'][1] for e in candidates]
                if len(set(prefix)) != 1 or any(e.get('relation') != 'Equivalent' for e in candidates):
                    qualifications.add('NACE 2.1 → 2 revision overlap')
            codes.update(c for c in prefix if c in nodes)
            paths.append(dict(reference=key, nodes=route.get('nodes', []),
                steps=route.get('steps', []), status=link.get('status'),
                mapping_origin=link.get('mapping_origin', item.get('mapping_origin'))))
            if link.get('status') == 'partial':
                qualifications.add('Partial or qualified source correspondence')
    if product:
        qualifications.add('Product-origin footprint; not an industry/product identity')
    return sorted(leaves(codes, nodes)), paths, '; '.join(sorted(qualifications))


def xlsx_records(path, sheet):
    from openpyxl import load_workbook
    book = load_workbook(path, read_only=True, data_only=True)
    try:
        return list(book[sheet].iter_rows(values_only=True))
    finally:
        book.close()


def write_csv(path, records, fields=None):
    records = list(records)
    fields = fields or list(dict.fromkeys(k for r in records for k in r))
    with Path(path).open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fields)
        writer.writeheader()
        for row in records:
            writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict))
                             else v for k, v in row.items()})


def verify_artifacts(folder):
    """Reject incomplete or modified generated concordance bundles."""
    folder = Path(folder).resolve()
    package = json.loads((folder / 'mapping-package.json').read_text())
    if not package.get('artifacts'):
        raise ValueError('Missing mapping artifact checksums')
    for name, expected in package['artifacts'].items():
        path = (folder / name).resolve()
        if not path.is_relative_to(folder) or not path.is_file() or digest(path) != expected:
            raise ValueError(f'Mapping artifact changed or unavailable: {name}')
    return package


def checkpoint_geography(mapping, native_to_target, target_regions):
    """Audit a saved GTAP aggregation using whole declared source regions."""
    native = mapping['geography']['GTAP12']
    if set(native_to_target) != {r['native_code'] for r in native}:
        raise ValueError('Region map must cover the exact native GTAP universe')
    if set(native_to_target.values()) != set(target_regions):
        raise ValueError('Region map targets differ from the saved database')
    if partition_audit(native)['overlaps']:
        raise ValueError('Overlapping declared GTAP membership')
    grouped = {r: set() for r in target_regions}; incomplete = set()
    for row in native:
        target = native_to_target[row['native_code']]
        grouped[target].update(row['members'])
        if not row['membership_complete']: incomplete.add(target)
    result = []
    for target, members in grouped.items():
        for family in ('EXIOBASE', 'EMERGING', 'GLORIA'):
            selection = whole_region_selection(members, mapping['geography'][family])
            if target in incomplete: selection['exact_on_declared_membership'] = False
            result.append(dict(target_geography=f'ENTICE{len(grouped)}', target_region=target,
                source_family=family, target_members=sorted(members),
                target_membership_complete=target not in incomplete, **selection))
    return result
