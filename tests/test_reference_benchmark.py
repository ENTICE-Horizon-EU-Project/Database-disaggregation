"""Small numerical fixtures independently verify cross-database algebra."""
from types import SimpleNamespace,ModuleType
from unittest.mock import patch
import sys
import zipfile
import io

import numpy as np
import pytest

from database_disaggregation.core import reference_benchmark as R


def test_geography_aggregation_precedes_import_and_export_ratios():
    # Countries A/B merge into AB: A↔B deliveries become domestic.
    z=np.array([[1.,2.,3.,4.,5.,6.],[2.,1.,4.,3.,6.,5.],[3.,4.,1.,2.,7.,8.],
                [4.,3.,2.,1.,8.,7.],[5.,6.,7.,8.,1.,2.],[6.,5.,8.,7.,2.,1.]])
    y=np.arange(18.).reshape(6,3)-2
    x=z.sum(axis=1)+y.sum(axis=1)
    profiles,audit=R.profiles_from_iot(x,['A','B','C'],['s','t'],{'AB':['A','B'],'C':['C']},[0,1],[(0,z[:2]),(2,z[2:])],[(0,y)])
    p=profiles['AB'];selected=[0,1,2,3];by_s=[0,2]
    assert p['output'][0]==pytest.approx(x[by_s].sum())
    assert p['imported_inputs'][0]==pytest.approx(z[np.ix_([4,5],by_s)].sum())
    assert p['exports'][0]==pytest.approx(z[np.ix_(by_s,[4,5])].sum()+y[by_s,2].sum())
    m=R.money_metrics(p,[0,1]);assert m['imported_input_share']==pytest.approx(z[np.ix_([4,5],selected)].sum()/z[:,selected].sum())
    assert sum(m['input_coefficients'])==pytest.approx(m['intermediate_input_ratio'])
    assert audit['source_output_demand_relative_L1']==pytest.approx(0.)


def test_currency_conversion_signed_final_demand_and_zero_denominators():
    data=dict(output=[0.,10.],intermediate_inputs=[2.,3.],imported_inputs=[1.,1.],net_final_demand=[-2.,-4.],exports=[1.,2.],deliveries=[0.,10.],input_groups=[[2.]+[0.]*9,[3.]+[0.]*9])
    zero=R.money_metrics(data,[0]);assert zero['export_ratio'] is None and zero['final_demand_ratio'] is None
    a=R.money_metrics(data,[1]);b=R.money_metrics(data,[1],.001)
    assert a['final_demand_ratio']==-.4
    assert b['output']==.01 and b['imported_input_share']==a['imported_input_share']
    assert R.money_metrics(data,[0,1])['intermediate_input_ratio']==.5


def test_mixed_nace_classes_are_not_fractionally_allocated():
    nodes={'01.11':{'section':'A'},'01.12':{'section':'A'},'20.11':{'section':'C'}}
    assert R.group_for(['01.11','01.12'],nodes)==0
    assert R.group_for(['01.11','20.11'],nodes)==9
    assert R.group_for([],nodes)==9


def test_gloria_product_iot_matches_independent_dense_industry_technology(tmp_path):
    ns=120;nr=2;na=nr*ns
    S=np.zeros((na,na));U=np.zeros_like(S)
    # One multi-product activity and one other producing activity per region.
    S[0,0]=8;S[0,1]=2;S[1,1]=10;S[ns,ns]=7;S[ns,ns+1]=3;S[ns+1,ns+1]=10
    U[0,0]=2;U[1,1]=3;U[ns,0]=1;U[0,ns]=4;U[ns+1,ns+1]=2
    Y=np.zeros((na,nr));Y[0]=[3,1];Y[1]=[4,-1];Y[ns]=[1,2];Y[ns+1]=[0,3]
    a=np.concatenate([np.arange(r*2*ns,r*2*ns+ns) for r in range(nr)])
    c=a+ns;T=np.zeros((2*na,2*na));T[np.ix_(a,c)]=S;T[np.ix_(c,a)]=U
    raw_y=np.zeros((2*na,nr));raw_y[c]=Y
    archive=tmp_path/'2023.zip'
    def csv(v):
        b=io.StringIO();np.savetxt(b,v,delimiter=',',fmt='%.12g');return b.getvalue()
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:z.writestr('T.csv',csv(T));z.writestr('Y.csv',csv(raw_y))
    fake=ModuleType('mario.parsers.gloria')
    fake.detect_gloria_layout=lambda *a,**k:(SimpleNamespace(release='060',T_path=SimpleNamespace(member='T.csv'),Y_path=SimpleNamespace(member='Y.csv')),SimpleNamespace(sector_names=tuple(f's{i}' for i in range(ns)),region_codes=('A','B'),final_demand_names=('y',)))
    fake._activity_positions=lambda regions,n:np.concatenate([np.arange(r*2*n,r*2*n+n) for r in regions])
    fake._commodity_positions=lambda regions,n:fake._activity_positions(regions,n)+n
    native=[dict(native_code=str(i+1),native_name=f's{i}') for i in range(ns)]
    with patch.dict(sys.modules,{'mario':ModuleType('mario'),'mario.parsers':ModuleType('mario.parsers'),'mario.parsers.gloria':fake}):
        actual=R.gloria_profiles(archive,native,{'A':['A'],'B':['B']},{str(i+1):2 for i in range(ns)},mario_source=tmp_path)
    xa=S.sum(axis=1); inv=np.divide(1.,xa,out=np.zeros_like(xa),where=xa>0);Z=(U*inv[None,:])@S
    X=S.sum(axis=0)
    expected,_=R.profiles_from_iot(X,['A','B'],list(map(str,range(1,121))),{'A':['A'],'B':['B']},[2]*ns,[(0,Z)],[(0,Y)])
    for region in ['A','B']:
        for key in expected[region]:np.testing.assert_allclose(actual['regions'][region][key],expected[region][key],atol=1e-12)
    assert actual['native_unit']=='000 USD'
    assert actual['audit']['zero_output_activity_gross_inputs']==0


def test_emerging_transposed_column_storage_and_native_order(tmp_path):
    import h5py
    path=tmp_path/'2023.mat';Z=np.array([[1.,2.],[4.,3.]]);Y=np.array([[2.,-1.],[3.,2.]])
    with h5py.File(path,'w') as h:
        for key,labels in [('country_list',['A','B']),('sector_list',['001 sample'])]:
            refs=[]
            for i,label in enumerate(labels):
                d=h.create_dataset(f'{key}{i}',data=np.array([ord(c) for c in label],dtype='uint16'));refs.append(d.ref)
            h.create_dataset(key,data=np.array(refs,dtype=h5py.ref_dtype))
        h['z']=Z.T;h['f']=Y.T;h['X']=(Z.sum(axis=1)+Y.sum(axis=1))[None,:]
    p=R.emerging_profiles(path,[dict(native_code='001',native_name='sample')],{'A':['A'],'B':['B']},{'001':2})
    assert p['regions']['A']['intermediate_inputs']==[5.]
    assert p['regions']['A']['exports']==[1.]
    assert p['audit']['source_output_demand_relative_L1']==0
