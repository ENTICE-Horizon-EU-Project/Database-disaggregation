"""Explicit working identities; published source snapshots remain immutable.

Aliases apply only when supplied by the selected reconciliation policy. Source
precedence chooses one whole inventory/table, never sums two historical records.
"""
from copy import deepcopy
from pathlib import Path


def rules_for(policy):
    return policy.get('sector_identities', {})


def default_rules():
    from database_disaggregation.reconciliation.policy import load_policy
    return rules_for(load_policy()[0])


def sector_code(value, rules):
    return rules.get('code_aliases', {}).get(value, value)


def sector_name(value, rules):
    aliases = rules.get('name_aliases', {})
    return next((new for old, new in aliases.items()
                 if isinstance(value, str) and old.casefold() == value.strip().casefold()), value)


def select_sources(sources, rules, *, audit=None, context='source'):
    """Return canonical keys with exactly one original value per activity."""
    grouped = {}
    for original, value in sources.items():
        grouped.setdefault(sector_code(original, rules), {})[original] = value
    selected = {}
    for canonical, candidates in grouped.items():
        preference = rules.get('preferred_sources', {}).get(canonical, [canonical])
        unknown = set(candidates) - set(preference)
        if unknown:
            raise ValueError(f'Unspecified identity source precedence for {canonical}: {unknown}')
        original = next(code for code in preference if code in candidates)
        selected[canonical] = candidates[original]
        if audit is not None and (original != canonical or len(candidates) > 1):
            audit.record('canonical_sector_source', kind='identity', sector=canonical,
                         context=context, selected_code=original,
                         superseded_codes=[code for code in candidates if code != original],
                         assumption='Choose one whole source record; no summation of aliases')
    return selected


def inventory_sources(paths, rules, *, audit=None):
    """Read Master identities rather than relying on inventory filenames."""
    from openpyxl import load_workbook
    sources = {}
    for path in paths:
        path = Path(path)
        book = (audit.workbook(path,role='inventory_identity') if audit is not None
                else load_workbook(path, read_only=True, data_only=True))
        try:
            header, *rows = book['Master'].values
            column = list(header).index('Sector')
            codes = {row[column] for row in rows if row[column] is not None}
            if len(codes) != 1:
                raise ValueError(f'Expected one child sector per workbook: {path}')
            code = codes.pop()
            if code in sources:
                raise ValueError(f'Duplicate inventory source for {code}: {path}')
            sources[code] = path
        finally:
            book.close()
    return select_sources(sources, rules, audit=audit, context='native_inventory')


def output_references(references, rules, *, audit=None):
    selected = select_sources(references or {}, rules, audit=audit, context='native_output_reference')
    result = deepcopy(selected)
    for record in result.values():
        for row in record['rows']:
            row['Sector'] = sector_code(row['Sector'], rules)
    return result


def intermediate_steps(steps, rules):
    """Collapse historical aliases once, preserving the supplied order.

    Repeating the same original code remains an invalid plan. Only the explicitly
    declared pair NCM/NMC can collapse to a single working entry.
    """
    result, seen, originals = {}, set(), set()
    for name, codes in steps.items():
        group = []
        for original in codes:
            if original in originals:
                raise ValueError(f'Duplicate sector in step plan: {original}')
            originals.add(original)
            canonical = sector_code(original, rules)
            if canonical not in seen:
                group.append(canonical)
                seen.add(canonical)
        if group:
            result[name] = group
    return result
