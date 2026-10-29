"""Residual activity names and reversible computational identifiers."""
import json
from pathlib import Path

import pandas as pd


def residual_names(parents, catalogue, existing):
    """P_C becomes petroleum products after the coal-products split."""
    result = {}
    for parent in sorted(set(parents.values()) & set(existing)):
        label = catalogue.get(parent, parent)
        result[parent] = ('Petroleum products' if parent == 'P_C'
                          else label if label.startswith('Rest of ') else 'Rest of '+label)
    if len(set(result.values())) != len(result) or (set(result.values()) & set(existing)):
        raise ValueError('Residual names collide with existing sector identifiers.')
    return result


def rename_in_memory(database, mapping):
    """Use MARIO's existing rename operation; do not solve or edit a source."""
    from mario.ops.add_sector_split import apply_split_parent_renames
    if not mapping:
        return database
    if not hasattr(database, 'add_sectors_master'):
        database.add_sectors_master = pd.DataFrame(columns=['Parent Sector'])
    apply_split_parent_renames(database, mapping, scenarios=['baseline'])
    return database


def load_checkpoint_with_codes(path):
    """Read a named published result and restore stable codes for modelling."""
    from mario.ops.add_sector_steps import load_checkpoint
    database = load_checkpoint(path)
    state = database._intermediate_steps_state
    mapping = state.get('residual_index_renames', {})
    if mapping:
        if len(set(mapping.values())) != len(mapping):
            raise ValueError('Non-invertible residual name concordance.')
        rename_in_memory(database, {name:code for code,name in mapping.items()})
    return database


def restore_frame_codes(frame, mapping):
    """Normalise published names before numerical cross-database comparisons."""
    from mario.ops.add_sector_split import _rename_sector_frame
    return _rename_sector_frame(frame, {name:code for code,name in mapping.items()}) if mapping else frame
