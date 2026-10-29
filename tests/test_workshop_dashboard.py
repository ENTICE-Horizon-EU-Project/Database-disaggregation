"""The shared workshop presentation preserves saved economic results."""
import json
from types import SimpleNamespace
import numpy as np
import pandas as pd
import pytest
from database_disaggregation.reporting.dashboard import dashboard_payload,write_dashboard

def database():
    axis=pd.MultiIndex.from_product([['A','B'],['Sector'],['p','q']],names=['Region','Level','Item'])
    cols=pd.MultiIndex.from_product([['A','B'],['Final demand'],['hhd','gov','inv']],names=['Region','Level','Item'])
    z=pd.DataFrame(np.arange(1.,17.).reshape(4,4),index=axis,columns=axis)
    y=pd.DataFrame(np.arange(1.,25.).reshape(4,6),index=axis,columns=cols)
    db=SimpleNamespace(Z=z,Y=y,X=pd.DataFrame([30.,40.,50.,60.],index=axis))
    db.get_index=lambda level:['A','B'] if level=='Region' else ['p','q']
    return db

def test_workshop_data_retains_trade_scope_and_undefined_final_consumers():
    db=database();before=db.Z.copy()
    data=dashboard_payload(db,labels={'p':'Sector P','q':'Sector Q'},
        target_profiles={'p':{'count':2,'passed':1,'max_error':3.,'output_targets':{'A':31.}}})
    p=data['payload']['p']
    assert data['format']=='entice-workshop-dashboard-v1'
    assert p['output']==[30.,50.] and p['output_target']==[31.,None]
    assert p['checks']['passed']==1
    np.testing.assert_allclose(np.nansum(np.array(p['shares'],dtype=float),axis=1),100.)
    assert all(row[data['uses'].index('FD · NPISH')] is None for row in p['shares'])
    assert 'FD · inv' in data['uses']
    np.testing.assert_allclose(p['totals'],np.array(p['trade']).sum(axis=0))
    # Both views include every Y category; percentages use destination totals.
    expected=db.Z.loc[('A','Sector','p')].iloc[2:].sum()+db.Y.loc[('A','Sector','p')].iloc[3:].sum()
    assert p['trade'][0][1]==expected
    pd.testing.assert_frame_equal(db.Z,before)

def test_workshop_assets_and_payload_are_self_contained_and_escape_labels(tmp_path):
    p=write_dashboard(database(),tmp_path/'report.html',labels={'p':'</script><script>wrong</script>'})
    text=p.read_text();data,_=json.JSONDecoder().raw_decode(text.split('const D=',1)[1])
    assert data['payload']['p']['name']=='</script><script>wrong</script>'
    assert '</script><script>wrong</script>' not in text
    assert 'data:image/svg+xml;base64,' in text and 'data:image/png;base64,' in text
    assert 'Select a sector' in text and "Who uses the sector's output?" in text
    assert 'id="show-references" hidden' in text
    assert '__BENCHMARK_AUDIT__' not in text
    assert list(tmp_path.iterdir())==[p]

def test_explicit_sector_status_requires_exact_saved_universe():
    with pytest.raises(ValueError,match='exact saved sectors'):
        dashboard_payload(database(),labels={},sector_metadata={'p':None})


def test_all_final_demand_including_negative_native_categories_is_retained():
    from database_disaggregation.analysis.flows import use_profile,trade_matrix,final_demand_mapping
    from database_disaggregation.analysis.plots import plot_use_profile
    db=database();columns=list(db.Y.columns);columns[2]=('A','Final demand','tmg');columns[5]=('B','Final demand','tmg')
    db.Y.columns=pd.MultiIndex.from_tuples(columns,names=db.Y.columns.names)
    db.Y.iloc[0,2]=-1e-9;db.Y.iloc[2,2]=0
    before=db.Y.copy()
    profile=use_profile(db,'p')
    assert profile.amounts.loc['FD · tmg','A']==-1e-9
    assert profile.shares.loc['FD · tmg','A']<0
    np.testing.assert_allclose(profile.totals,trade_matrix(db,'p').sum(axis=0))
    mapping=final_demand_mapping(db).set_index('Use')
    assert mapping.loc['tmg','Included in denominator']
    figure=plot_use_profile(profile)
    assert figure.data[0].zmin<0 and figure.data[0].colorscale[0][1]=='#b2182b'
    pd.testing.assert_frame_equal(db.Y,before)


def saved_benchmark(db):
    rows=[]
    for coordinate,row in db.X.iterrows():
        region,_,sector=coordinate
        rows.append(dict(region=region,sector=sector,output=float(row.iloc[0]),
                         parent='q' if sector=='p' else sector,
                         is_child=sector=='p',is_residual=sector=='q'))
    return dict(dimensions=dict(regions=['A','B'],sectors=['q'],
                    sector_names={'p':'New activity','q':'Remaining parent'},
                    baseline_sector_names={'q':'Original parent'}),
        sectors=rows,summary=dict(regions=2,new_sectors=1,final_sectors=2,
                                 skipped_sectors=['pending']),checks=[],
        targets={'by_sector':{'p':{'count':2,'passed':1,'max_error':.1,
                                  'output_targets':{'A':30.,'B':50.}}}},
        provenance=dict(database='/saved/run',baseline='/saved/run/baseline'),
        policy={'numerical_validation':'report_only'},external_comparisons=None)


def test_matching_saved_report_renders_names_parents_and_existing_audit_links(tmp_path):
    db=database();report=saved_benchmark(db)
    source=tmp_path/'benchmarking.json';source.write_text(json.dumps(report))
    target=tmp_path/'notebook.html'
    write_dashboard(db,target,benchmark=source)
    page=target.read_text();data,_=json.JSONDecoder().raw_decode(page.split('const D=',1)[1])
    assert data['payload']['p']['name']=='New activity'
    assert data['payload']['p']['sector_type']['parents']==[{'code':'q','name':'Original parent'}]
    assert data['payload']['p']['checks']['passed']==1
    assert '1 planned activities remain inside their parents' in page
    assert source.as_uri() in page


def test_a_saved_report_cannot_be_attached_to_a_different_output(tmp_path):
    db=database();report=saved_benchmark(db);db.X.iloc[0,0]+=1.
    with pytest.raises(ValueError,match='outputs differ'):
        write_dashboard(db,tmp_path/'wrong.html',benchmark=report)


def test_partial_target_checks_require_an_explicit_sector_selection(tmp_path):
    from database_disaggregation.analysis import check_targets
    db=database();path=tmp_path/'inputs.xlsx'
    outputs=pd.DataFrame([['p','A',30.,'M USD'],['pending','A',10.,'M USD']],
                         columns=['Sector','Region','Quantity','Unit'])
    trades=pd.DataFrame(columns=['Sector_from','Region_from','Region_to','Quantity','Unit'])
    with pd.ExcelWriter(path) as writer:
        outputs.to_excel(writer,sheet_name='Total outputs',index=False)
        trades.to_excel(writer,sheet_name='Trades',index=False)
    selected=check_targets(db,path,sectors=['p'])
    assert len(selected)==1 and selected.passed.all()
    with pytest.raises(ValueError,match='absent from the database'):
        check_targets(db,path,sectors=['pending'])


def test_dashboard_reads_saved_checkpoint_and_preserves_independent_production(tmp_path):
    import hashlib
    from pathlib import Path
    from test_shared_runs import trial_fixture
    trial = trial_fixture(tmp_path/'source')
    checkpoint = Path(json.loads((trial/'trial.json').read_text())['accepted_checkpoints'][-1])
    output_path = checkpoint/'database/flows/X.parquet'
    expected = pd.read_parquet(output_path)*1.1
    expected.to_parquet(output_path)
    state_path = checkpoint/'state.json'
    state = json.loads(state_path.read_text())
    state['split_model_options'] = {'accounting': 'inherit'}
    state['files']['database/flows/X.parquet'] = hashlib.sha256(output_path.read_bytes()).hexdigest()
    state_path.write_text(json.dumps(state))
    output = write_dashboard(checkpoint, tmp_path/'dashboard.html')
    data, _ = json.JSONDecoder().raw_decode(output.read_text().split('const D=', 1)[1])
    for region, value in expected.xs('Parent', level='Item').iloc[:, 0].items():
        position = data['regions'].index(region[0])
        assert data['payload']['Parent']['output'][position] == pytest.approx(value)
