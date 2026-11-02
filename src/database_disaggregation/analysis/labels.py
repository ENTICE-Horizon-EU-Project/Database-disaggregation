"""Sector display names from the existing installed-or-checkout registry."""
from database_disaggregation.core.registry import Registry
from pathlib import Path
import pandas as pd


def sector_labels(registry=None, *, target='GTAP12'):
    registry = registry or Registry.load()
    labels = {s['id']: s['name'] for s in registry.adapters[target]['parent_catalogue']}
    labels.update({s['id']: s['name'] for s in registry.sectors.values()})
    return labels


def region_labels(registry=None, *, geography='GTAP12'):
    """Native region names only; aggregate names require explicit metadata."""
    registry = registry or Registry.load()
    return {region['id']: region['name'] for region in registry.geographies[geography]['regions']}


def read_region_names(path, *, regions, geography=None):
    """Read names for the exact saved geography, optionally checking membership."""
    table = pd.read_csv(Path(path), dtype=str, keep_default_na=False)
    if not {'code', 'name'} <= set(table) or table.code.duplicated().any():
        raise ValueError('Region names require unique code/name rows.')
    if set(table.code) != set(regions) or table.name.str.strip().eq('').any():
        raise ValueError('Region names differ from the exact saved region universe.')
    if geography is not None:
        if 'native_regions' not in table:
            raise ValueError('Native region membership is required to verify aggregate names.')
        for row in table.itertuples():
            declared = {code.strip() for code in row.native_regions.split('|') if code.strip()}
            actual = {native for native, target in geography.items() if target == row.code}
            if declared != actual:
                raise ValueError(f'Region-name membership differs from the saved geography: {row.code}')
    return dict(zip(table.code, table.name))
