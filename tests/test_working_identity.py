"""NMC consumes the former NCM data once, without reviving the empty legacy record."""
from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace

import pandas as pd
import pytest
from openpyxl import Workbook,load_workbook

from database_disaggregation.core import working_identity as identities
from database_disaggregation.core.parent_budgets import read_child_targets, ChildTargets
from database_disaggregation.reconciliation.audit import Audit
from database_disaggregation.reconciliation.policy import load_policy
from database_disaggregation.reconciliation.profiles import ProfileBuilder
from database_disaggregation.reconciliation.sources import Sources
from test_geography import inventory
from test_database_input import make_database
from test_reconciliation import toy_policy


def test_collected_preparation_uses_real_profile_and_output_once(tmp_path, monkeypatch):
    import database_disaggregation
    from database_disaggregation.reconciliation import model_inputs
    native=tmp_path/'native';native.mkdir()
    inventory(native/'NCM.xlsx',sector='NCM',outputs=(6.,6.,6.),profiles=(.25,.25,.25))
    inventory(native/'NMC.xlsx',sector='NMC',outputs=(0.,0.,0.),profiles=(.9,.9,.9))
    hashes={p:hashlib.sha256(p.read_bytes()).hexdigest() for p in native.glob('*.xlsx')}
    (tmp_path/'config').mkdir()
    (tmp_path/'config/additional-sectors-13.json').write_text(json.dumps({'sectors':{},'country_components':{}}))
    monkeypatch.setattr(model_inputs,'PROJECT_ROOT',tmp_path)
    policy=toy_policy(('NMC',))
    actual_load_policy=model_inputs.load_policy
    monkeypatch.setattr(model_inputs,'load_policy',lambda value=True: actual_load_policy(policy if value is True else value))
    monkeypatch.setattr(model_inputs.Registry,'load',lambda:SimpleNamespace(sectors={},regions=lambda:[]))
    import mario
    monkeypatch.setattr(mario.Database,'add_sectors',lambda *a,**k: pytest.fail('No MRIO solve in preparation'))
    from test_database_input import make_database
    result=database_disaggregation.prepare_inputs(database=make_database(),data_root=tmp_path,
        source_dir=native,output_dir=tmp_path/'prepared',steps={'First':['NMC'],'Later':['NCM']},
        source_paths={'resolved_inventories':native,'mario_inventories':None,
                      'purdue_split_targets':None,'purdue_trade':None,'partner_templates':None})
    from database_disaggregation.core.parent_budgets import read_child_targets
    targets=read_child_targets([result.workbook.parent/'inventories/NMC.xlsx'])
    assert set(targets.master.Sector)=={'NMC'}
    assert targets.output.Quantity.sum()==pytest.approx(18.)
    assert not (result.workbook.parent/'inventories/NCM.xlsx').exists()
    assert result.database.add_sectors_workbook.intermediate_steps=={'First':['NMC']}
    book=load_workbook(result.workbook.parent/'inventories/NMC.xlsx',read_only=True,data_only=True)
    header,*rows=book['Master'].values
    profile_sheet=dict(zip(header,rows[0]))['Inventory sheet']
    profile=list(book[profile_sheet].values)
    names=profile[0];records=[dict(zip(names,row)) for row in profile[1:] if row[0] is not None]
    assert sum(row['Quantity'] for row in records if row.get('Item type')=='Sector')==pytest.approx(.25)
    book.close()
    assert all(hashlib.sha256(path.read_bytes()).hexdigest()==digest for path,digest in hashes.items())
    events=[json.loads(line) for line in (result.audit/'changes.jsonl').read_text().splitlines()]
    assert any(e.get('selected_code')=='NCM' and e.get('superseded_codes')==['NMC'] for e in events)


def test_reference_and_trade_selection_do_not_sum_legacy_records(tmp_path):
    rules=identities.default_rules()
    references={code:{'rows':[{'Sector':code,'Region':'R1','Quantity':q,'Unit':'M USD'}]}
                for code,q in [('NMC',9.),('NCM',100.)]}
    original=deepcopy(references)
    result=identities.output_references(references,rules)
    assert list(result)==['NMC']
    assert result['NMC']['rows'][0]['Quantity']==100.
    assert result['NMC']['rows'][0]['Sector']=='NMC'
    assert references==original
    book=Workbook();w=book.active;w.title='NTSCIF'
    w.append(['sector','origin','destination','value'])
    w.append(['NMC','R1','R2',9.]);w.append(['NCM','R1','R2',100.])
    book.save(tmp_path/'trade.xlsx');book.close()
    policy=toy_policy(('NMC',));audit=Audit(tmp_path/'audit')
    sources=Sources({'purdue_trade':tmp_path/'trade.xlsx'},
        SimpleNamespace(regions=lambda:[]),SimpleNamespace(regions=['R1','R2']),policy,audit)
    audit.close()
    assert sources.customs_trade=={'NMC':{('R1','R2'):100.}}


def test_target_aliases_normalize_identifiers_only(tmp_path):
    path=inventory(tmp_path/'NCM.xlsx',sector='NCM',outputs=(3.,4.,5.))
    target=read_child_targets([path],sector_aliases={'NCM':'NMC'})
    assert set(target.master.Sector)=={'NMC'}
    assert set(target.trade.Sector_from)=={'NMC'}
    assert target.output.Quantity.tolist()==[3.,4.,5.]
    assert target.trade.Quantity.tolist()==[1.,2.,3.]


def test_recipe_input_and_cluster_members_use_canonical_code(tmp_path):
    policy=toy_policy(('NMC',));audit=Audit(tmp_path/'audit')
    native=SimpleNamespace(sectors=['EEQ'],units={'Sector':pd.DataFrame({'unit':['M USD']},index=['EEQ'])})
    builder=ProfileBuilder(native,SimpleNamespace(regions=['R1'],mapping={'R1':'R1'}),
                           {'NMC':'EEQ'},{},policy,audit)
    def row(item,q):return {'Item type':'Sector','DB Item':item,'Quantity':q,'Unit':'M USD','DB Region':'GLOBAL'}
    result=builder.canonical([row('NCM',.3),row('Battery group',.2)],'R1','EEQ',
                             {'Battery group':['NCM','NMC']},{},{})
    audit.close()
    assert [row['DB Item'] for row in result]==['NMC','NMC']
    assert [row['Quantity'] for row in result]==[.3,.2]


def test_historical_policy_without_aliases_keeps_separate_records(tmp_path):
    legacy=toy_policy(('NCM','NMC'));legacy.pop('sector_identities')
    load_policy(legacy)
    files={}
    for code in ['NCM','NMC']:files[code]=inventory(tmp_path/f'{code}.xlsx',sector=code)
    selected=identities.inventory_sources(files.values(),identities.rules_for(legacy))
    assert set(selected)=={'NCM','NMC'}
    with pytest.raises(ValueError,match='must not also be an active'):
        load_policy(toy_policy(('NCM','NMC')))
    with pytest.raises(ValueError,match='Duplicate sector'):
        identities.intermediate_steps({'One':['NMC','NMC']},identities.default_rules())


def test_operational_matching_accepts_old_partner_name_and_code():
    from database_disaggregation.core.matching_utils import find_sector_match,find_sector_match_by_code
    from database_disaggregation.core.paths import PROJECT_ROOT
    for code in ['NCM','NMC']:
        match=find_sector_match_by_code(PROJECT_ROOT,code)
        assert (match.entice_code,match.gtap12)==('NMC','EEQ')
    match=find_sector_match(PROJECT_ROOT,'Manufacture of NCM batteries')
    assert match.entice_name=='Manufacture of NMC batteries'
