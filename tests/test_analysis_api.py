from copy import deepcopy
from types import SimpleNamespace
import json
import numpy as np
import pandas as pd
import pytest
from database_disaggregation.analysis import use_profile, trade_matrix, plot_use_profile, ReferenceSet, check_targets
from database_disaggregation.reporting import write_dashboard
from database_disaggregation.analysis.flows import FD_GROUPS


def database():
    axis=pd.MultiIndex.from_product([['A','B'],['Sector'],['p','q']],names=['Region','Level','Item'])
    cols=pd.MultiIndex.from_product([['A','B'],['Final demand'],['hhd','gov','inv','stocks']],names=['Region','Level','Item'])
    z=pd.DataFrame([[2,3,5,7],[1,2,3,4],[11,13,17,19],[5,6,7,8]],index=axis,columns=axis,dtype=float)
    y=pd.DataFrame([[10,2,100,99,20,3,200,99],[0]*8,[30,4,300,99,40,5,400,99],[0]*8],index=axis,columns=cols,dtype=float)
    db=SimpleNamespace(Z=z,Y=y,X=pd.DataFrame([200.,100.,300.,150.],index=axis))
    db.get_index=lambda level: ['A','B'] if level=='Region' else ['p','q']
    return db


def test_use_profile_sums_origins_excludes_investment_and_leaves_npish_missing():
    db=database();before=db.Z.copy(deep=True)
    p=use_profile(db,'p',final_demand=FD_GROUPS)
    assert list(p.shares.columns)==['A','B']
    assert list(p.shares.index)==['p','q','FD · Households','FD · Government','FD · NPISH']
    assert p.totals.to_dict()=={'A':75.,'B':116.}
    np.testing.assert_allclose(p.shares['A'].iloc[:4],[13,16,40,6]/np.array(75.)*100)
    assert p.amounts['A']['FD · Households']==40
    assert p.shares.loc['FD · NPISH'].isna().all()
    np.testing.assert_allclose(p.shares.sum(),100)
    pd.testing.assert_frame_equal(db.Z,before)
    # Trade has the larger scope, including investment/stocks, unlike use shares.
    t=trade_matrix(db,'p')
    np.testing.assert_allclose(t.to_numpy(),[[216,334],[457,580]])


def test_zero_denominators_and_signed_residuals_are_not_replaced():
    db=database();db.Z.iloc[[0,2],2:]=0;db.Y.iloc[[0,2],4:]=0
    assert use_profile(db,'p').shares['B'].isna().all()
    db=database();db.Z.iloc[2,1]=-3.0000000001
    p=use_profile(db,'p');assert p.amounts.loc['q','A']<0
    f=plot_use_profile(p);assert f.data[0].zmin<0
    assert np.nanmin(np.asarray(f.data[0].z,dtype=float))<0
    db.Z.iloc[2,1]=-3.1
    assert plot_use_profile(use_profile(db,'p')).data[0].zmin<0


def references():
    metric=dict(output=1.,intermediate_inputs=0.,imported_inputs=0.,net_final_demand=0.,exports=0.,
        intermediate_input_ratio=0.,imported_input_share=None,final_demand_ratio=0.,export_ratio=0.,
        input_coefficients=[0.]*10,mixed_input_share=None,output_demand_residual=0.)
    return ReferenceSet.from_comparisons({'rows':[dict(family='EXIOBASE',region='A',basket='all',label='All',
        entice_sectors=['p','q'],baseline_sectors=['p','q'],baseline_scope='same aggregate families',
        baseline=metric,reference=deepcopy(metric))], 'input_groups':[str(i) for i in range(10)],'monetary_unit':'M USD'}, {'p':0,'q':2})


def test_references_use_authoritative_x_sum_before_ratios_and_keep_frozen_values(tmp_path):
    r=references();frozen=deepcopy(r.data);p=r.write(tmp_path/'refs.json');r=ReferenceSet.read(p)
    d=r.compare(database());m=d['rows'][0]['entice']
    assert m['output']==300. and m['intermediate_inputs']==43.
    assert m['imported_inputs']==35.
    assert m['imported_input_share']==pytest.approx(35/43)
    assert sum(m['input_coefficients'])==pytest.approx(43/300)
    assert d['rows'][0]['reference']==frozen['rows'][0]['reference']
    assert r.data==frozen
    with pytest.raises(ValueError,match='supplier groups'):
        ReferenceSet.from_comparisons(r.data,{'p':0}).compare(database())
    bad=deepcopy(r.data);bad['rows'][0]['entice_sectors']=['missing']
    with pytest.raises(ValueError,match='absent current sectors'):
        ReferenceSet.from_comparisons(bad,{'p':0,'q':2}).compare(database())


def test_dashboard_writes_only_one_file_and_uses_packaged_assets(tmp_path):
    p=write_dashboard(database(),tmp_path/'report.html',labels={'p':'Product','q':'Buyer'})
    assert list(tmp_path.iterdir())==[p]
    html=p.read_text();assert 'data:image/svg+xml;base64,' in html and 'data:image/png;base64,' in html
    assert '__TITLE__' not in html and '__DATA__' not in html
    assert 'POLIMI' in html and 'eNextGen' in html
    assert 'id="show-references" hidden' in html


def test_target_checks_include_all_deliveries_and_validate_units(tmp_path):
    p=tmp_path/'targets.xlsx'
    outputs=pd.DataFrame([['p','A',200.,'M USD']],columns=['Sector','Region','Quantity','Unit'])
    trades=pd.DataFrame([['p','A','B',334.,'M USD']],columns=['Sector_from','Region_from','Region_to','Quantity','Unit'])
    with pd.ExcelWriter(p) as writer:outputs.to_excel(writer,sheet_name='Total outputs',index=False);trades.to_excel(writer,sheet_name='Trades',index=False)
    checks=check_targets(database(),p);assert checks.passed.all() and len(checks)==2
    outputs['Unit']='EUR'
    with pd.ExcelWriter(p) as writer:outputs.to_excel(writer,sheet_name='Total outputs',index=False);trades.to_excel(writer,sheet_name='Trades',index=False)
    with pytest.raises(ValueError,match='unit'):check_targets(database(),p)


def test_nonfinite_threshold_and_reference_values_are_rejected():
    with pytest.raises(ValueError,match='minimum_total'):
        use_profile(database(),'p',minimum_total=float('nan'))
    r=references();bad=deepcopy(r.data);bad['rows'][0]['reference']['output']=float('inf')
    with pytest.raises(ValueError,match='Non-finite'):
        ReferenceSet.from_comparisons(bad,{'p':0,'q':2})
