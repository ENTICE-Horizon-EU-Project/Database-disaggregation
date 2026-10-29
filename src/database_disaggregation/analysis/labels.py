"""Sector display names from the existing installed-or-checkout registry."""
from database_disaggregation.core.registry import Registry


def sector_labels(registry=None, *, target='GTAP12'):
    registry = registry or Registry.load()
    labels = {s['id']: s['name'] for s in registry.adapters[target]['parent_catalogue']}
    labels.update({s['id']: s['name'] for s in registry.sectors.values()})
    return labels
