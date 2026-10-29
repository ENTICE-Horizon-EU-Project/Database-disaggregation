"""Reconcile desired model groups with indivisible native database regions."""
from collections import defaultdict
import json
from pathlib import Path


def coarsen_model_regions(country_groups, native_members, *, unrepresented=None):
    """Merge connected desired groups without splitting a native region.

    This is the finest common coarsening: only groups connected through a
    native region are merged. Native regions without a listed country require
    an explicit assignment; no GDP or territorial proxy is inferred.
    """
    unrepresented = dict(unrepresented or {})
    if not country_groups or not native_members:
        raise ValueError('Country groups and native membership must be nonempty.')
    for country, group in country_groups.items():
        if not isinstance(country, str) or not country.strip() or not isinstance(group, str) or not group.strip():
            raise ValueError('Country and desired group codes must be populated strings.')
    owners = defaultdict(list)
    for native, members in native_members.items():
        for country in set(members):
            owners[country].append(native)
    missing = set(country_groups)-owners.keys()
    ambiguous = {c:owners[c] for c in country_groups if len(owners[c]) > 1}
    if missing or ambiguous:
        raise ValueError(f'Country/native membership is incomplete or ambiguous: missing={sorted(missing)}, ambiguous={ambiguous}')
    parent = {group:group for group in set(country_groups.values())}

    def find(group):
        if parent[group] != group:
            parent[group] = find(parent[group])
        return parent[group]

    def join(left, right):
        left, right = find(left), find(right)
        if left != right:
            parent[max(left, right)] = min(left, right)

    represented = {}
    conflicts = []
    for native, members in native_members.items():
        groups = sorted({country_groups[c] for c in members if c in country_groups})
        represented[native] = groups
        for group in groups[1:]:
            join(groups[0], group)
        if len(groups) > 1:
            conflicts.append(dict(native_region=native, desired_groups=groups))
    unmatched = {native for native, groups in represented.items() if not groups}
    if set(unrepresented) != unmatched:
        raise ValueError(f'Explicit assignments required exactly for native regions without listed countries: {sorted(unmatched)}')
    components = defaultdict(list)
    for group in sorted(parent):
        components[find(group)].append(group)
    desired_to_effective = {group:'_'.join(component) for component in components.values() for group in component}
    codes = {'_'.join(component) for component in components.values()}
    if len(codes) != len(components) or codes & set(unrepresented.values()) or len(set(unrepresented.values())) != len(unrepresented):
        raise ValueError('Effective region codes collide.')
    mapping = {native:desired_to_effective[groups[0]] if groups else unrepresented[native]
               for native, groups in represented.items()}
    countries = {country:mapping[owners[country][0]] for country in country_groups}
    return dict(mapping=mapping, country_mapping=countries,
        country_native={country:owners[country][0] for country in country_groups},
        desired_to_effective=desired_to_effective,
        components=sorted(components.values()), native_conflicts=conflicts,
        unrepresented_native=unrepresented,
        source_regions=len(mapping), desired_regions=len(parent), target_regions=len(set(mapping.values())))


def read_model_region_inputs(workbook, scope, *, missing_groups=None):
    """Read the selected model partition and explicit native territorial scope."""
    from openpyxl import load_workbook
    missing_groups = dict(missing_groups or {})
    book = load_workbook(workbook, read_only=True, data_only=True)
    try:
        values = list(book['Country mapping'].values)
        headers = values[0]
        required = {'ISO3','Country','Common code','Common region','Common 3 GTAP models','Common 3 GTAP models-long name'}
        if not required <= set(headers):
            raise ValueError('Country mapping headers changed.')
        rows, groups, labels, corrections = [], {}, {}, []
        for number, values in enumerate(values[1:], 2):
            if not values or all(v is None for v in values):
                continue
            row = dict(zip(headers, values))
            country = row['ISO3']
            if not isinstance(country, str) or not country.strip():
                raise ValueError(f'Invalid or duplicate ISO3 in Country mapping row {number}.')
            country = country.strip()
            if country in groups:
                raise ValueError(f'Invalid or duplicate ISO3 in Country mapping row {number}.')
            group = row['Common 3 GTAP models']
            label = row['Common 3 GTAP models-long name']
            if not isinstance(group, str) or not group.strip():
                group = missing_groups.get(country)
                if not group or group != row['Common code']:
                    raise ValueError(f'Unassigned desired group for {country}; explicit correction required.')
                label = row['Common region']
                corrections.append(dict(country=country, row=number, field='Common 3 GTAP models',
                    before=None, after=group, basis='Explicit correction agrees with the existing Common code.'))
            group = group.strip()
            if not isinstance(label, str) or not label.strip():
                raise ValueError(f'Missing desired region name for {country}.')
            if group in labels and labels[group] != label:
                raise ValueError(f'Conflicting names for desired region {group}.')
            groups[country], labels[group] = group, label
            rows.append(dict(iso3=country, country=row['Country'], desired_group=group, desired_name=label))
        unused = {country for country,group in missing_groups.items() if groups.get(country) != group}
        if unused:
            raise ValueError(f'Stale missing-group corrections: {sorted(unused)}')
        models = {}
        model_values = list(book['GEO'].values)
        for values in model_values[1:]:
            if len(values) > 1 and values[1] in groups:
                models[values[1]] = {k:(str(v).strip() if v is not None else None)
                    for k,v in zip(model_values[0],values) if k in ['GEM-E3','OPEN-PROM','GEMINI-E3','SORMAC-25']}
    finally:
        book.close()
    metadata = json.loads(Path(scope).read_text())
    by_name = {r['country'].casefold():r['iso3'] for r in rows}
    native_members = {}
    native_names = {}
    for region in metadata['regions']:
        code = region['label']
        if code in native_members:
            raise ValueError(f'Duplicate native region: {code}')
        members = set(region.get('members', []))
        if region.get('iso3'):
            members.add(region['iso3'])
        # Some country regions include named overseas territories in GTAP's
        # source. Use exact supplied country names; do not infer sovereignty.
        members.update(by_name[name.casefold()] for name in region.get('source_members', []) if name.casefold() in by_name)
        native_members[code] = sorted(members)
        native_names[code] = region['name']
    return dict(country_groups=groups, country_rows=rows, desired_names=labels,
        native_members=native_members, native_names=native_names,
        corrections=corrections, model_regions=models, metadata=metadata)
