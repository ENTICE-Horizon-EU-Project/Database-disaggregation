"""Consolidate already solved sector identities through MARIO aggregation.

Unlike source selection, post-solve aggregation sums both accounts on every
flow axis. No solved observation is deleted and no optimisation is performed.
"""
from copy import deepcopy
import json
from pathlib import Path

import numpy as np
import pandas as pd


def canonical_axis(axis, aliases):
    if not isinstance(axis,pd.MultiIndex) or 'Region' not in axis.names:
        return axis
    if 'Level' in axis.names and set(axis.get_level_values('Level'))!={'Sector'}:
        return axis
    return pd.MultiIndex.from_tuples([(*row[:-1],aliases.get(row[-1],row[-1])) for row in axis],names=axis.names)


def aggregate_flow(frame,aliases):
    """Independent reference implementation used to verify MARIO's result."""
    result=frame.copy()
    result.index=canonical_axis(result.index,aliases)
    result.columns=canonical_axis(result.columns,aliases)
    if result.index.has_duplicates:result=result.groupby(level=list(range(result.index.nlevels)),sort=False).sum()
    if result.columns.has_duplicates:result=result.T.groupby(level=list(range(result.columns.nlevels)),sort=False).sum().T
    return result


def aggregate_database(database,aliases):
    """Use public MARIO APIs and retain the independently recorded X vector."""
    sectors=database.get_index('Sector')
    if set(aliases)-set(sectors) or set(aliases.values())-set(sectors):
        raise ValueError('Both source and canonical sector must exist in the saved database.')
    if any(old==new or new in aliases for old,new in aliases.items()):
        raise ValueError('Consolidation aliases must be direct and acyclic.')
    production=aggregate_flow(database.query('X'),aliases)
    mapping=pd.DataFrame({'Aggregation':[aliases.get(s,s) for s in sectors]},index=sectors)
    database.reset_to_flows('baseline')
    database.aggregate({'Sector':mapping},levels='Sector',drop=[],calc_all=False,
                       ignore_nan=False,zero_output_epsilon=None,inplace=True)
    database.set_block('X',production.reindex(database.query('Z').index),scenario='baseline')
    database.add_note('Saved sector identities consolidated by flow aggregation; X retained as sum of recorded production. No optimisation or IO quantity solve.')
    return database


def merge_state(state,aliases):
    result=deepcopy(state)
    parents={}
    for child in state['completed_sectors']:
        code=aliases.get(child,child);parent=state['sector_parents'][child]
        if code in parents and parents[code]!=parent:
            raise ValueError('Merged solved sectors must share a baseline parent.')
        parents[code]=parent
    result['completed_sectors']=list(parents)
    result['sector_parents']=parents
    if 'planned_sectors' in result:
        result['planned_sectors']=list(dict.fromkeys(aliases.get(s,s) for s in result['planned_sectors']))
    return result


def combine_constraints(by_sector,records,aliases):
    """Sum historical observations with explicit lineage, never invent a cell."""
    records=records.copy()
    records['source_product']=records['product']
    records['product']=records['product'].map(lambda s:aliases.get(s,s))
    merged={};combined=[]
    for sector in dict.fromkeys(aliases.get(s,s) for s in by_sector):
        originals=[s for s in by_sector if aliases.get(s,s)==sector]
        if len(originals)==1 and originals[0]==sector:
            merged[sector]=deepcopy(by_sector[sector]);continue
        deltas={by_sector[s]['trade_delta'] for s in originals}
        if len(deltas)!=1:raise ValueError('Cannot present one trade band for different source tolerances.')
        merged[sector]=dict(constraints_verified=True,output_targets={},trade_targets={},
            output_cells={},trade_cells={},trade_delta=deltas.pop(),
            trade_scope='bilateral total of intermediate and all final-demand deliveries',
            output_reference_kind='Aggregated original disaggregation constraints',
            historical_sector_components=originals,
            source_components=[dict(product=s,metadata=by_sector[s]) for s in originals],
            input_representation='sum of separately solved historical constraints; not a jointly solved constraint')
    for key,rows in records.groupby(['product','kind','origin','destination'],sort=False,dropna=False):
        sector,kind,origin,destination=key
        row=rows.iloc[0].to_dict();row['constraint']=float(rows.constraint.sum())
        if len(rows)>1 or any(rows.source_product!=sector):
            components=rows.astype(object).where(rows.notna(),None).to_dict('records')
            row.update(source_product=' + '.join(rows.source_product),
                input_file=' + '.join(dict.fromkeys(rows.input_file)),
                input_cell=' + '.join(f"{x.source_product}: {x.input_cell}" for x in rows.itertuples()),
                source='sum of historical '+ ' + '.join(rows.source_product)+' observations',
                notes='Post-solve identity aggregation; source inputs remain unchanged',
                source_components=json.dumps(components,allow_nan=False))
            if kind=='Output':
                merged[sector]['output_targets'][origin]=row['constraint']
                merged[sector]['output_cells'][origin]=row['input_cell']
            else:
                merged[sector]['trade_targets'].setdefault(origin,{})[destination]=row['constraint']
                merged[sector]['trade_cells'].setdefault(origin,{})[destination]=row['input_cell']
        combined.append(row)
    return merged,pd.DataFrame(combined)


def consolidate_finalization(finalization,aliases,regions,original_activity_count):
    """Keep activation history and label mixed observed/assigned technologies."""
    result=deepcopy(finalization)
    for old,new in aliases.items():
        profiles=result['activation_profiles'];old_regions=set(profiles.get(old,{}))
        profiles[new]={**profiles.get(new,{}),**profiles.get(old,{})};profiles.pop(old,None)
        result['recipe_sources'].pop(old,None)
        result['recipe_sources'][new]='production-weighted aggregate of original observed and assigned technologies'
        result.setdefault('recipe_status_by_region',{})[new]={region:
            ('Production-weighted aggregate of assigned source recipes; original sourcing retained' if region in old_regions
             else 'Observed source technology plus former empty epsilon account; production-weighted, original sourcing retained')
            for region in regions}
    result['source_activity_count']=original_activity_count
    result['identity_consolidation_note']='Activation counts describe the predecessor; sector identities were subsequently combined without adding demand or solving quantities.'
    return result
