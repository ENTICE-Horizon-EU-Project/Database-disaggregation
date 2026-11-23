import numpy as np
import pandas as pd
import pandas.testing as pdt
import pytest
import mario
from database_disaggregation.reconciliation.zero_activity import ActivationPolicy, activate_inactive_accounts


def fixture(*, globally_inactive=False, tiny=False):
    axis=pd.MultiIndex.from_product([['R1','R2'],['Sector'],['P','C','Q']],names=['Region','Level','Item'])
    demand=pd.MultiIndex.from_product([['R1','R2'],['Consumption category'],['hhd']],names=axis.names)
    x=np.array([100.,0. if globally_inactive else 50.,120.,100.,1e-310 if tiny else 0.,120.])
    a=np.zeros((6,6));a[2,[0,1,2]]=[.1,.2,.1];a[5,[3,4,5]]=[.1,0,.1]
    z=a*x[None,:]
    z[2,4]=.001 # spurious input to inactive C; compensated by signed Tax.
    y=np.zeros((6,2));y[np.arange(6),np.repeat([0,1],3)]=x-z.sum(axis=1)
    v=np.zeros((4,6));v[1]=x-z.sum(axis=0);v[3,4]=v[1,4];v[1,4]=0.
    units={g:pd.DataFrame({'unit':[u]*len(items)},index=items) for g,items,u in
           [('Sector',['P','C','Q'],'M USD'),('Factor of production',['Capital','Labor','TTM','Tax'],'M USD'),('Satellite account',['CO2'],'tonne')]}
    db=mario.Database(table='IOT',units=units,Z=pd.DataFrame(z,index=axis,columns=axis),
        Y=pd.DataFrame(y,index=axis,columns=demand),V=pd.DataFrame(v,index=['Capital','Labor','TTM','Tax'],columns=axis),
        E=pd.DataFrame(0.,index=['CO2'],columns=axis),EY=pd.DataFrame(0.,index=['CO2'],columns=demand))
    # Preserve independently recorded production through MARIO's block API.
    db.set_block('X',pd.DataFrame(x,index=axis,columns=['production']).reindex(db.Z.index),scenario='baseline')
    return db


@pytest.mark.parametrize('tiny',[False,True])
def test_inactive_recipe_is_global_but_sourcing_is_local_and_source_is_unchanged(tiny):
    db=fixture(tiny=tiny);before={n:db.query(n).copy() for n in ['Z','V','X','Y','E']}
    result,changes,targets,sourcing=activate_inactive_accounts(db,parents={'C':'P'})
    assert result['activated_accounts']==1
    assert result['positive_dust_accounts']==int(tiny)
    assert db.query('z',scenarios='model_ready').loc[('R2','Sector','Q'),('R2','Sector','C')]==pytest.approx(.2)
    assert db.query('z',scenarios='model_ready').loc[('R1','Sector','Q'),('R2','Sector','C')]==0
    delta=db.query('Y',scenarios='model_ready')-before['Y']
    assert np.count_nonzero(delta.to_numpy())==1
    assert delta.loc[('R2','Sector','C'),('R2','Consumption category','hhd')]==pytest.approx(1e-5)
    assert db.query('X',scenarios='model_ready').loc[('R2','Sector','C')].iloc[0]>1e-6
    for name,frame in before.items():pdt.assert_frame_equal(db.query(name),frame)
    assert result['row_balance_max_USD']<1e-5
    assert result['column_balance_max_USD']<1e-5
    assert db.query('V',scenarios='model_ready').loc[['Capital','Labor']].ge(0).all().all()
    assert not db.has_matrix('w',scenario='model_ready')
    assert any(r['source']=='active local buyer family' and r['input_sector']=='Q' for r in sourcing)
    pdt.assert_frame_equal(db.query('E',scenarios='model_ready'),before['E'])


def test_globally_inactive_technology_requires_explicit_recipe():
    db=fixture(globally_inactive=True)
    with pytest.raises(ValueError,match='explicit inventory recipe'):
        activate_inactive_accounts(db,parents={'C':'P'})
    assert db.scenarios==['baseline']
    a=np.array([0.,0.,.3]);v=np.array([0.,.7,0.,0.])
    result,*_=activate_inactive_accounts(db,parents={'C':'P'},recipes={'C':{'a':a,'v':v}})
    assert result['activated_accounts']==2
    assert (db.query('X',scenarios='model_ready')>0).all().all()
    assert db.query('z',scenarios='model_ready').loc[('R2','Sector','Q'),('R2','Sector','C')]==pytest.approx(.3)


def test_epsilon_and_domain_validation():
    with pytest.raises(ValueError,match='exceed'):
        ActivationPolicy(final_demand_usd=.1).validate()
