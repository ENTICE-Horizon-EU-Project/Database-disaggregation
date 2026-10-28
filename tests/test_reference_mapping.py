import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from entice_inventory.core import reference_mapping as M


@pytest.fixture
def nodes():
    return {
        'B':dict(parent=None), '07':dict(parent='B'), '07.2':dict(parent='07'),
        '07.29':dict(parent='07.2'),
        'C':dict(parent=None),'24':dict(parent='C'),'24.4':dict(parent='24'),
        '24.42':dict(parent='24.4'),'24.44':dict(parent='24.4'),
        '25':dict(parent='C'),'25.9':dict(parent='25'),'25.99':dict(parent='25.9')}


def test_identifiers_and_unknown_classification(nodes):
    assert M.hs_code('0101.21')=='010121'
    assert M.hs_code(10121.0)=='010121'
    for value in [None,'','1e5','01','TOTAL']:
        with pytest.raises(ValueError):M.hs_code(value)
    assert M.leaves(['24'],nodes)=={'24.42','24.44'}
    with pytest.raises(ValueError,match='Unknown NACE'):M.leaves(['24.99'],nodes)
    assert M.common_ancestor(['24.42','24.44'],nodes)=='24.4'
    assert M.common_ancestor(['24.42','07.29'],nodes) is None


def test_correlations_keep_all_destinations_and_reject_conversion(monkeypatch):
    import openpyxl
    class Sheet:
        def iter_rows(self,**kwargs):
            return iter([('Between',None,None),('HS 2022','HS 2017','Relationship'),
                ('010121','010110','n:n'),('010121','010190','n:n')])
    class Book:
        def __getitem__(self,k):return Sheet()
        def close(self):pass
    monkeypatch.setattr(openpyxl,'load_workbook',lambda *a,**k:Book())
    rows=M.correlation_pairs(Path('unused.xlsx'),'HS2022-HS2017 Correlations')
    assert [(r[0],r[1]) for r in rows]==[('010121','010110'),('010121','010190')]
    with pytest.raises(ValueError,match='correlation sheet'):
        M.correlation_pairs(Path('unused.xlsx'),'HS2022-HS2017 Conversions')


def test_official_route_retains_partial_flags_and_multiple_producers(tmp_path,monkeypatch):
    (tmp_path/'cpc21-isic4.txt').write_text('CPC21code,CPC21partial,ISIC4code,ISIC4partial\n02131,1,0142,1\n')
    (tmp_path/'nace2-isic4.txt').write_text('NACE2code,NACE2part,ISIC4code,ISIC4part\n01.43,0,0142,0\n01.49,1,0142,1\n')
    (tmp_path/'cpc21-hs2017.csv').write_text('HS 2017,HS partial,CPC Ver. 2.1,CPC partial\n0101.21,1,02131,1\n')
    (tmp_path/'cpc21-hs2012.txt').write_text('CPC21code,CPC21partial,HS12code,HS12partial\n02131,1,0101.21,0\n')
    monkeypatch.setattr(M,'correlation_pairs',lambda p,s:[('010131','010121','n:1',3)] if '2022' in p.name else [('010121','010110','1:n',3)])
    rows=M.official_hs_routes(tmp_path)
    for edition in ['H2','H4','H5','H6']:
        actual=[r for r in rows if r['hs_edition']==edition]
        assert {r['nace2'] for r in actual}=={'01.43','01.49'}
        assert {r['hs6'] for r in actual}==({'010110'} if edition=='H2' else {'010131'} if edition=='H6' else {'010121'})
        assert all(r['allocation_weight'] is None for r in actual)
        assert all(r['cpc_to_isic_partial']==1 for r in actual)
        if edition=='H2':
            assert all(r['revision_traversal']=='reverse' and r['source_revision_relationship']=='1:n'
                       and r['revision_relationship']=='n:1' for r in actual)


def test_no_automatic_revision_or_product_activity_identity(nodes):
    item=dict(links={'24.44':dict(nodes=[['CPA2.2','24.44.11']],steps=[],status='reviewed')})
    revisions={'24.44':[dict(left=['NACE2','24.44'],relation='Equivalent')]}
    codes,paths,qualification=M.footprint_from_explorer(item,revisions,nodes,product=True)
    assert codes==['24.44']
    assert 'not an industry/product identity' in qualification
    codes,_,_=M.footprint_from_explorer(item,{},nodes,product=True)
    assert codes==[]  # No inference from identical-looking code prefixes.


def test_envelope_expands_for_spillovers_and_rejects_cross_section(nodes):
    row=lambda code,values:dict(native_code=code,nace2_classes=values,qualification='')
    rows=[row('copper',['24.44','25.99']),row('aluminium',['24.42'])]
    result=M.comparison_envelope({'24.44'},rows,nodes)
    assert result['nace2_envelope']=='C'
    assert not result['quantitative_ready']
    rows.append(row('mixed',['25.99','07.29']))
    assert M.comparison_envelope({'24.44'},rows,nodes)['status']=='no_single_nace_envelope'


def test_whole_regions_never_split_rest_of_world_or_ignore_dependencies():
    r=lambda code,values,complete=True:dict(native_code=code,members=values,membership_complete=complete)
    rows=[r('FR',['FRA']),r('WL',['GLP','MTQ','BRA']),r('WF',['REU','ZAF'])]
    result=M.whole_region_selection(['FRA','GLP','MTQ','REU'],rows)
    assert not result['exact_on_declared_membership']
    assert result['native_regions']==['FR']
    assert set(result['source_regions_requiring_split'])=={'WL','WF'}
    assert M.whole_region_selection(['FRA'],rows)['exact_on_declared_membership']
    assert not M.whole_region_selection(['FRA'],[r('unknown',['FRA'],False)])['exact_on_declared_membership']
    assert M.partition_audit([r('A',['FRA']),r('B',['FRA'])])['overlaps']=={'FRA':['A','B']}
    with pytest.raises(ValueError,match='Overlapping'):
        M.whole_region_selection(['FRA'],[r('A',['FRA']),r('B',['FRA'])])
    with pytest.raises(ValueError,match='empty geographic'):M.whole_region_selection([],rows)


def test_bundle_detects_modified_or_missing_generated_file(tmp_path):
    file=tmp_path/'mapping.csv';file.write_text('code\n010121\n')
    package={'artifacts':{'mapping.csv':M.digest(file)}}
    (tmp_path/'mapping-package.json').write_text(json.dumps(package))
    assert M.verify_artifacts(tmp_path)==package
    file.write_text('changed')
    with pytest.raises(ValueError,match='artifact changed'):M.verify_artifacts(tmp_path)


def test_reviewed_emerging_serials_are_not_hs_codes():
    rules=json.loads((Path(__file__).resolve().parents[1]/'data/benchmarking/sector_scopes.json').read_text())
    goods={r['native_index']:r for r in rules['emerging_goods']}
    assert goods[27]['expected_raw_label'].startswith('27 inorganic chemicals')
    assert goods[27]['hs_chapter']=='28'
    assert goods[76]['hs_chapter']=='78'  # Reserved HS chapter 77 is not a sector.
    assert all(r['source_hs_edition']=='H2' for r in goods.values())
    assert len(rules['entice'])==67
