import json
import pandas as pd
import pytest
from database_disaggregation.reporting.dashboard import _sector_types, write_dashboard


def workbook(tmp_path, rows):
    path=tmp_path/'sectors.xlsx'
    # Reordered columns ensure classification follows the headers, not positions.
    pd.DataFrame(rows,columns=['Sector','Parent Sector','Add or Split'])[
        ['Add or Split','Sector','Parent Sector']].to_excel(path,sheet_name='Master',index=False)
    return path


def test_new_residual_original_and_parent_names_follow_master(tmp_path):
    path=workbook(tmp_path,[['Child','Parent','Split'],['Child','Parent','Split']])
    types=_sector_types(['Child','Parent','Stable'],path,{'Parent':'Parent industry'})
    assert {k:v['kind'] for k,v in types.items()}=={
        'Child':'new','Parent':'residual_parent','Stable':'original'}
    assert types['Child']['parents']==[{'code':'Parent','name':'Parent industry'}]
    assert types['Stable']['parents']==[]


def test_add_does_not_mark_parent_as_residual_and_pending_children_are_ignored(tmp_path):
    path=workbook(tmp_path,[['Added',None,'Add'],['Pending','Stable','Split']])
    types=_sector_types(['Added','Stable'],path,{})
    assert types['Added']['kind']=='new' and types['Added']['parents']==[]
    assert types['Stable']['kind']=='original'


def test_later_split_marks_a_new_child_as_residual_parent(tmp_path):
    path=workbook(tmp_path,[['Child','Parent','Split'],['Grandchild','Child','Split']])
    types=_sector_types(['Parent','Child','Grandchild'],path,{})
    assert types['Child']['kind']=='residual_parent'
    assert types['Child']['parents'][0]['code']=='Parent'
    assert types['Grandchild']['parents'][0]['code']=='Child'


def test_classification_is_not_guessed_without_workbook():
    assert _sector_types(['APP','NFM','Unknown'],None,{})=={'APP':None,'NFM':None,'Unknown':None}


def test_split_without_parent_fails(tmp_path):
    path=workbook(tmp_path,[['Child',None,'Split']])
    with pytest.raises(ValueError,match='requires a Parent Sector'):
        _sector_types(['Child'],path,{})


def test_report_embeds_metadata_for_the_selected_workbook(tmp_path):
    from test_analysis_api import database
    path=workbook(tmp_path,[['p','q','Split']])
    html=write_dashboard(database(),tmp_path/'report.html',workbook=path,
                         labels={'p':'Product','q':'Buyer'}).read_text()
    start=html.index('const D=')+len('const D=')
    data,_=json.JSONDecoder().raw_decode(html[start:])
    assert data['payload']['p']['sector_type']['label']=='New sector'
    assert data['payload']['p']['sector_type']['parents']==[{'code':'q','name':'Buyer'}]
    assert data['payload']['q']['sector_type']['label']=='Residual parent'
    assert 'id="sector-status"' in html and 'id="reference-sector-types"' in html
