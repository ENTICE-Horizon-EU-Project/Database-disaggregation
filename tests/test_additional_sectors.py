from types import SimpleNamespace
import pytest
from database_disaggregation.reconciliation.additional_sectors import select_profile, CountryComponentSources


def test_country_profile_wins_over_group_and_global_without_double_counting():
    profiles={'direct':[1], 'regional':[2], 'global':[3]}
    members={'direct':['A'], 'regional':['A','B'], 'global':['A','B','C']}
    assert select_profile('A',profiles,members)=='direct'
    assert select_profile('B',profiles,members)=='regional'
    assert select_profile('C',profiles,members)=='global'
    assert select_profile('D',profiles,members) is None


def test_equally_specific_conflicting_profiles_are_not_silently_selected():
    with pytest.raises(ValueError,match='Ambiguous'):
        select_profile('A',{'one':[1],'two':[2]},{'one':['A','B'],'two':['A','C']})


@pytest.mark.parametrize('complete',[False,True])
def test_country_components_sum_once_with_explicit_coverage(complete):
    observations=[dict(identifier=k,members=['REST'],value=q,source=k,kind='direct') for k,q in [('One',2.),('Two',3.)]]
    source=SimpleNamespace(native=SimpleNamespace(regions=['REST']),region_lookup={},observations=lambda *a:observations)
    members=['One','Two'] if complete else ['One','Two','Three']
    rules={'S':{k:dict(target='REST',country=k,all_members=members) for k in ['One','Two']}}
    audit=SimpleNamespace(record=lambda *a,**k:None)
    result=CountryComponentSources(source,rules,audit).observations('S','P')
    assert len(result)==1 and result[0]['value']==5.
    assert result[0]['kind']==('direct' if complete else 'cluster')
    assert result[0]['confidence']==(1. if complete else .1)


def test_complete_native_observation_is_not_added_to_its_components():
    observations=[dict(identifier='One',members=['REST'],value=2.,source='One',kind='direct'),
                  dict(identifier='REST',members=['REST'],value=7.,source='REST',kind='direct')]
    source=SimpleNamespace(native=SimpleNamespace(regions=['REST']),region_lookup={},observations=lambda *a:observations)
    rules={'S':{'One':dict(target='REST',country='One',all_members=['One','Two'])}}
    result=CountryComponentSources(source,rules,SimpleNamespace(record=lambda *a,**k:None)).observations('S','P')
    assert len(result)==1 and result[0]['value']==7.


def test_output_cap_uses_current_residual_not_original_parent(tmp_path):
    from test_reconciliation import toy_policy, budgets
    from database_disaggregation.core.geography import Geography
    from database_disaggregation.core.parent_budgets import ChildTargets
    from database_disaggregation.reconciliation.audit import Audit
    from database_disaggregation.reconciliation.targets import prepare_outputs
    import pandas as pd
    native = SimpleNamespace(regions=['R1','R2'], budgets=budgets(('R1','R2'), output=100.))
    selected = budgets(('G',), output=5.)
    source = SimpleNamespace(observations=lambda *_:[dict(members=['R1'], value=20., identifier='R1',
        source='test', state='numeric', kind='direct', confidence=1.)])
    targets = ChildTargets(pd.DataFrame(), pd.DataFrame(columns=['Sector','Region','Quantity']), pd.DataFrame())
    geo = Geography({'R1':'G','R2':'G'})
    audit = Audit(tmp_path/'audit')
    native_values, output, _ = prepare_outputs(toy_policy(('A',)), source, native, geo, targets,
        {'A':'Parent'}, {'A':'Parent'}, audit, selected_parent_budgets=selected)
    audit.close()
    assert output[('A','G')] == pytest.approx(5.)
    assert native_values[('A','R1')] == pytest.approx(2.5)
    assert native.budgets.output.loc[('R1','Parent')] == 100.


def test_nonunitary_monetary_profile_is_retained_before_reconciliation(tmp_path, monkeypatch):
    import database_disaggregation.reconciliation.additional_sectors as module
    from database_disaggregation.core.geography import Geography
    from database_disaggregation.reconciliation.audit import Audit
    from openpyxl import Workbook
    registry = SimpleNamespace(sectors={}, regions=lambda:[{'id':'R1','name':'One'}])
    monkeypatch.setattr(module.Registry, 'load', lambda:registry)
    monkeypatch.setattr(module, 'load_legacy_gtap12_maps', lambda _ : ({'Broad':'Parent'}, {}))
    book = Workbook(); del book['Sheet']
    for name in ['Region','Sector','Primary input']:
        book.create_sheet(name)
    ws = book.create_sheet('Unit process')
    ws.append([None]*6+['One',None])
    ws.append([None]*6+['monetary',None])
    ws.append([None]*6+[1,'USD'])
    ws.append([None]*8); ws.append([None]*8)
    ws.append(['Sector',None,'Broad','GLOBAL',None,None,.8,'USD'])
    ws.append(['Primary_input',None,'Labor',None,None,None,.1972469214277204,'USD'])
    path=tmp_path/'source.xlsx';book.save(path);book.close()
    audit = Audit(tmp_path/'audit')
    profiles, membership, groups, _ = module.read_cost_profiles(path,'NEW',SimpleNamespace(regions=['R1']),
        Geography({'R1':'G'}), {'Parent','CHILD'}, {'CHILD':'Parent'},
        {'name':'New activity', 'matching':tmp_path/'unused'}, audit)
    audit.close()
    assert membership['One'] == ['R1']
    assert sum(row['Quantity'] for row in profiles['One']) == pytest.approx(.9972469214277204)
    assert set(next(iter(groups.values()))) == {'Parent','CHILD'}
