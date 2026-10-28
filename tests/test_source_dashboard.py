import base64
import copy
import gzip
import hashlib
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from openpyxl import Workbook

from entice_inventory.reporting import SourceCollection, write_source_dashboard
from entice_inventory.reporting.collection import select_trade
from entice_inventory.reconciliation.policy import load_policy
from entice_inventory.reconciliation.sources import observation_geographies, selected_trade_observations


def inventory(path, code, lead, amount=1., coefficient=.3):
    book=Workbook();s=book.active;s.title='Summary'
    for i,row in enumerate([['INFO'],['Sector',code,code+' activity'],['Parent sector','NFM'],['Inventory version','test'],['Data collection lead',lead],[],['Sources'],['Research reference','https://example.org']],1):
        for j,value in enumerate(row,1):s.cell(i,j,value)
    s=book.create_sheet('Master');s.append(['Region','Sector','Inventory sheet','Quantity','Unit','Final consumption','Consumption category','Parent Sector','Leave empty','Source','Notes','Add or Split']);s.append(['USA',code,'recipe',amount,'M USD',None,None,'NFM',None,None,None,'Split'])
    s=book.create_sheet('recipe');s.append(['Quantity','Unit','Input','Item type','DB Item','DB Region','Change type']);s.append([coefficient,'M USD',None,'Sector','ELECTRICITY','GLOBAL','Update']);s.append([.7,'M USD',None,'Factor of production','Capital','GLOBAL','Update'])
    s=book.create_sheet('Regions Clusters');s.append(['GLOBAL']);s.append(['USA']);s.append(['AUS'])
    s=book.create_sheet('Sectors Clusters');s.append(['ELECTRICITY']);s.append(['CoalBL']);s.append(['WindBL'])
    book.create_sheet('Factors Clusters').append([None]);s=book.create_sheet('DB units');s.append(['Level','Item','Unit']);s.append(['Factor of production','Capital','M USD'])
    s=book.create_sheet('Total outputs');s.append(['Sector','Region','Quantity','Unit']);s.append([code,'USA',100,'M USD']);book.save(path)


@pytest.fixture
def source_fixture(tmp_path):
    root=tmp_path/'inputs';root.mkdir();inv=root/'inventories';inv.mkdir();partner=root/'partners';partner.mkdir();base=root/'baseline';base.mkdir()
    for code,lead in [('APP','ORDECSYS'),('MCU','EXIOIOT pipeline'),('NMC','ICCS')]:inventory(inv/f'{code}.xlsx',code,lead)
    b=Workbook();s=b.active;s.title='General info';s['A4']='Lead';s['D4']='ORDECSYS';s['A5']='New sector';s['D5']='Copied name does not define the activity';s['D7']='NFM'
    s=b.create_sheet('Region');s.append(['Groups','Name','Code']);s.append([]);s.append(['GLOBAL','Global','GLOBAL']);s.append(['OCEANIA','Australia','AUS']);s.append(['NORTH AMERICA','United States of America','USA'])
    s=b.create_sheet('Total production');s.append(['Region','Parent','Source','Notes','2017','Unit','2023 Value','Unit']);s.append(['Region',None,None,None,None,None,'(free to fill)','MUSD']);s.append(['United States of America',None,None,None,None,None,25,'MUSD']);s.append(['Australia',None,None,None,None,None,'=G3*2','MUSD']);b.save(partner/'production.xlsx')
    b=Workbook();b.remove(b.active)
    for name,values in {'REG':[['Region','Value'],['USA',True],['AUS',True]],'REPSEC':[['Sector','Value'],['MCU',True]],'REPOUT':[['Region','Sector','Value'],['USA','MCU',20]],'BLTTRD':[['Origin','Destination','Sector','Value'],['USA','AUS','MCU',5]]}.items():
        s=b.create_sheet(name)
        for row in values:s.append(row)
    paired=root/'paired.xlsx';b.save(paired)
    b=Workbook();s=b.active;s.title='NTSCIF'
    for row in [['Sector','Origin','Destination','Value'],['MCU','USA','AUS',999],['ALM','USA','AUS',3],['ALM','USA','USA',7]]:s.append(row)
    customs=root/'customs.xlsx';b.save(customs)
    x=pd.DataFrame({'X':[100.,100.,100.,100.,100.,100.]},index=pd.MultiIndex.from_product([['USA','AUS'],['NFM','OXT','EEQ']],names=['Region','Sector']));x.to_parquet(base/'X.parquet')
    policy,_=load_policy();policy=copy.deepcopy(policy);policy['sectors']={k:v for k,v in policy['sectors'].items() if k in ('APP','MCU','NMC')};policy['sectors']['APP']['output_source'].update(file='production.xlsx');policy['overlap_groups']=[];policy['trade']['composites']={'ALM':['APP']};policy['trade']['parent_pattern_only']=[]
    registry=SimpleNamespace(regions=lambda:[{'id':'USA','name':'United States of America'},{'id':'AUS','name':'Australia'}],adapters={'GTAP12':{'parent_catalogue':[{'id':c,'name':c+' name'} for c in ['NFM','OXT','EEQ','CoalBL','WindBL']]}},fingerprints={'fixture':'test'})
    return dict(inventory_dir=inv,baseline_path=base,policy=policy,registry=registry,source_paths={'partner_templates':partner,'purdue_split_targets':paired,'purdue_trade':customs})


def test_pipeline_selection_complete_coverage_and_role_specific_collection(source_fixture):
    before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in source_fixture['inventory_dir'].parent.rglob('*') if p.is_file()}
    c=SourceCollection.from_pipeline(**source_fixture)
    assert set(c.sectors)=={'APP','MCU','NMC'}
    app=next(s for s in c.metadata['sectors'] if s['id']=='APP')
    assert app['production']['collector']==app['costs']['collector']=='ORDECSYS'
    assert app['trades']['collector']=='Purdue'
    assert c.sectors['APP']['production'][0]['value']==25
    assert not any(p['geo']=='AUS' for p in c.sectors['APP']['production']) # uncached formula is missing
    outputs={p['geo']:p['value'] for p in c.sectors['MCU']['production']};assert outputs=={'USA':20,'AUS':0} # declared sparse parameter zero
    assert not c.sectors['NMC']['production']
    assert c.sectors['MCU']['trade']['edges']==[['USA','AUS',5.]] # paired source precedes customs
    assert c.sectors['APP']['trade']['scope']=='product_group' and c.sectors['APP']['trade']['edges']==[['USA','AUS',3.]]
    assert c.sectors['NMC']['trade']['scope']=='unavailable'
    assert {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in source_fixture['inventory_dir'].parent.rglob('*') if p.is_file()}==before


def test_costs_have_one_common_schema_and_keep_cluster_members(source_fixture):
    c=SourceCollection.from_pipeline(**source_fixture)
    assert all('values' in p for s in c.sectors.values() for p in s['profiles'])
    electric=next(i for i in c.metadata['items'].values() if i['is_group'])
    assert [m['code'] for m in electric['members']]==['CoalBL','WindBL']
    assert all(c.sectors[s]['profiles'][0]['values'][electric['id']]==.3 for s in c.sectors)
    assert len(c.metadata['items'])==2 # same input group shared across all sectors, rather than duplicated by file


def test_conflicting_duplicate_inventories_fail(source_fixture):
    inventory(source_fixture['inventory_dir']/'APP_duplicate.xlsx','APP','ORDECSYS',coefficient=.9)
    with pytest.raises(ValueError,match='Conflicting duplicate'):SourceCollection.from_pipeline(**source_fixture)


def test_functional_output_amount_is_retained(source_fixture):
    inventory(source_fixture['inventory_dir']/'APP.xlsx','APP','ORDECSYS',amount=2.)
    c=SourceCollection.from_pipeline(**source_fixture);assert sum(c.sectors['APP']['profiles'][0]['values'].values())==.5


def test_geography_semantics_shared_with_reconciliation():
    obs=[dict(identifier='USA',kind='direct',members=['USA'],value=2),dict(identifier='GLOBAL',kind='cluster',members=['USA','AUS','NZL'],value=8),dict(identifier='OCEANIA',kind='cluster',members=['AUS','NZL'],value=3)]
    policy={'geography':{'cluster_modes':{'X':{'GLOBAL':{'mode':'residual'},'OCEANIA':{'exclude':['NZL']}}}}}
    result=observation_geographies(obs,policy,'X',['USA','AUS','NZL'])
    assert result[1]['members']==[] and result[2]['members']==['AUS']
    assert obs[1]['members']==['USA','AUS','NZL']


def test_empty_paired_domain_and_parent_pattern_do_not_fall_back():
    p={'sectors':{'X':{'output_source':{'kind':'purdue'}}},'trade':{'parent_pattern_only':[],'composites':{'G':['X']}}}
    s=SimpleNamespace(domain_sectors={'X'},paired_trade={},customs_trade={'X':{('A','B'):99},'G':{('A','B'):50}})
    assert selected_trade_observations('X',p,s)==({},'X','paired')
    p['trade']['parent_pattern_only']=['X'];assert select_trade('X',p,s)==({},None,'unavailable')


def test_single_english_artifact_and_no_file_navigation(source_fixture,tmp_path):
    c=SourceCollection.from_pipeline(**source_fixture);out=write_source_dashboard(c,tmp_path/'collection.html');h=out.read_text()
    m=json.loads(re.search(r'<script id="source-data" type="application/json">(.*?)</script>',h,re.S)[1])
    assert len(m['sectors'])==3 and len(m['chunks'])==3
    for code in c.sectors:
        chunk=re.search(r'id="chunk-'+code+r'">(.*?)</script>',h).group(1)
        assert json.loads(gzip.decompress(base64.b64decode(chunk)))==c.sectors[code]
    assert '<html lang="en">' in h and 'Total Production' in h and 'Cost Structure' in h and 'Trades' in h
    assert 'file-select' not in h and 'source-search' not in h and 'sheet-select' not in h and 'EXIOIOT' not in h
    assert not re.search(r'<script[^>]+src=',h) and 'MARIO_workshop_dashboard' not in h
