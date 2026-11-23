"""Solved identities aggregate all four self-consumption cells and preserve GDP/X."""
from copy import deepcopy
import json
import numpy as np
import pandas as pd
import pytest
from database_disaggregation.reconciliation.saved_identity import aggregate_database,aggregate_flow,combine_constraints,merge_state


def database():
    import mario
    sectors=['EEQ','NCM','NMC'];regions=['R1','R2']
    axis=pd.MultiIndex.from_product([regions,['Sector'],sectors],names=['Region','Level','Item'])
    demand=pd.MultiIndex.from_product([regions,['Consumption category'],['hhd']],names=axis.names)
    units={kind:pd.DataFrame({'unit':[unit]*len(items)},index=items) for kind,items,unit in
        [('Sector',sectors,'M USD'),('Factor of production',['Labor','Tax'],'M USD'),('Satellite account',['CO2'],'tonne')]}
    z=pd.DataFrame(np.arange(36,dtype=float).reshape(6,6)/10,index=axis,columns=axis)
    y=pd.DataFrame(np.arange(12,dtype=float).reshape(6,2)/10-1,index=axis,columns=demand)
    v=pd.DataFrame([np.arange(6)+10.,-np.arange(6)-1.],index=['Labor','Tax'],columns=axis)
    e=pd.DataFrame(np.arange(6,dtype=float).reshape(1,-1),index=['CO2'],columns=axis)
    db=mario.Database(table='IOT',units=units,Z=z,Y=y,V=v,E=e,EY=pd.DataFrame(0.,index=['CO2'],columns=demand))
    db.set_block('X',pd.DataFrame(np.arange(6)+100.,index=axis,columns=['production']).reindex(db.Z.index),scenario='baseline')
    return db


def test_mario_aggregation_retains_all_flows_signed_values_and_recorded_production():
    db=database();before={name:db.query(name).copy() for name in ['Z','Y','V','E','EY','VY','X']}
    aggregate_database(db,{'NCM':'NMC'})
    assert set(db.get_index('Sector'))=={'EEQ','NMC'}
    for name,original in before.items():
        expected=aggregate_flow(original,{'NCM':'NMC'});actual=db.query(name).reindex(index=expected.index,columns=expected.columns)
        pd.testing.assert_frame_equal(actual,expected,check_names=False,check_exact=True)
    assert db.query('V').sum().sum()==before['V'].sum().sum()
    selected=[('R1','Sector',s) for s in ['NCM','NMC']]
    assert db.Z.loc[('R1','Sector','NMC'),('R1','Sector','NMC')]==pytest.approx(before['Z'].loc[selected,selected].sum().sum())
    assert not np.allclose(db.X.iloc[:,0],db.Z.sum(axis=1)+db.Y.sum(axis=1))
    assert np.isfinite(db.z).all().all() and np.isfinite(db.v).all().all()


def test_state_collapses_counts_only_when_original_parents_match():
    original={'completed_sectors':['NCM','NMC','LFP'],'planned_sectors':['NCM','LFP','NMC'],
              'sector_parents':{'NCM':'EEQ','NMC':'EEQ','LFP':'EEQ'}}
    result=merge_state(original,{'NCM':'NMC'})
    assert result['completed_sectors']==['NMC','LFP'] and result['planned_sectors']==['NMC','LFP']
    assert original['completed_sectors']==['NCM','NMC','LFP']
    original['sector_parents']['NMC']='OME'
    with pytest.raises(ValueError,match='share a baseline parent'):merge_state(original,{'NCM':'NMC'})


def test_combined_historical_constraints_preserve_both_input_references():
    metadata={s:dict(trade_delta=.01,output_targets={'R1':q},trade_targets={'R1':{'R2':q/2}},
                    output_cells={},trade_cells={},input_href=s+'.xlsx') for s,q in [('NCM',100.),('NMC',0.)]}
    rows=pd.DataFrame([dict(product=s,kind=kind,origin='R1',destination='' if kind=='Output' else 'R2',
        constraint=q if kind=='Output' else q/2,input_file=s+'.xlsx',input_cell='Total outputs!D2',
        trade_delta=np.nan if kind=='Output' else .01) for s,q in [('NCM',100.),('NMC',0.)] for kind in ['Output','Trade']])
    merged,records=combine_constraints(metadata,rows,{'NCM':'NMC'})
    assert set(merged)=={'NMC'} and len(records)==2
    assert merged['NMC']['output_targets']=={'R1':100.}
    assert merged['NMC']['trade_targets']=={'R1':{'R2':50.}}
    assert merged['NMC']['historical_sector_components']==['NCM','NMC']
    for row in records.itertuples():
        components=json.loads(row.source_components)
        assert {component['source_product'] for component in components}=={'NCM','NMC'}
        assert row.constraint==sum(component['constraint'] for component in components)
    assert 'not a jointly solved constraint' in merged['NMC']['input_representation']


def test_recipe_notes_distinguish_observed_and_assigned_predecessor_accounts():
    from database_disaggregation.reconciliation.saved_identity import consolidate_finalization
    history={'activated_accounts':3,'recipe_sources':{'NCM':'global','NMC':'inventory'},
        'activation_profiles':{'NCM':{'R2':0.},'NMC':{'R1':0.,'R2':0.}}}
    result=consolidate_finalization(history,{'NCM':'NMC'},['R1','R2'],69)
    assert set(result['recipe_sources'])=={'NMC'}
    assert 'Observed source technology' in result['recipe_status_by_region']['NMC']['R1']
    assert 'aggregate of assigned' in result['recipe_status_by_region']['NMC']['R2']
    assert result['activated_accounts']==3 and result['source_activity_count']==69
    assert 'NCM' in history['recipe_sources']


def test_nested_finalization_archive_resolution_detects_cycles(tmp_path):
    from database_disaggregation.reporting.constraints import constraint_archive
    a,b,c=[tmp_path/name for name in ['canonical','activated','original']]
    for path in [a,b,c]:path.mkdir()
    for current,source in [(a,b),(b,c)]:
        (current/'state.json').write_text(json.dumps({'format':'entice-finalized-database-v1','source_database_directory':str(source)}))
    (c/'reproducibility').mkdir();archive=c/'reproducibility/accepted-history.zip';archive.write_bytes(b'test')
    assert constraint_archive(a)==archive
    archive.unlink()
    (c/'state.json').write_text(json.dumps({'format':'entice-finalized-database-v1','source_database_directory':str(a)}))
    with pytest.raises(ValueError,match='Cycle'):constraint_archive(a)
