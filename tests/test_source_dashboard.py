import base64
import gzip
import json
import re
import zipfile
from io import BytesIO
from xml.etree import ElementTree as E

from openpyxl import Workbook
from entice_inventory.reporting import write_source_dashboard
from entice_inventory.reporting.source_dashboard import _xlsx_tables, _csv_table, _template_clusters


def workbook(path):
    book=Workbook();sheet=book.active;sheet.title='Total production'
    sheet.append(['Region','2017 Value','2023 Value','Unit'])
    sheet.append(['Producing region','MUSD 2017','MUSD 2023',None])
    sheet.append(['USA',0,42,'MUSD 2023']);sheet.append(['IND',None,'=C3*2',None])
    sheet.append(['<script>alert(1)</script>',None,False,None]);sheet['AA8']='wide column'
    for i in range(9,80):sheet.append(['USA' if i%2 else 'IND',str(i),str(i),'MUSD'])
    info=book.create_sheet('General info');info['A4']='Lead';info['D4']='POLIMI';info['A5']='New sector';info['D5']='Example sector'
    up=book.create_sheet('Unit process');up['G1']='EU28';up['I1']='USA';up['G2']='monetary';up['I2']='monetary';up['G3']=1;up['H3']='USD'
    up.append([])
    for row,values in [(6,['Sector','Power','ENERGY','GLOBAL','Source A','',0,'USD',0.5,'USD']),
                       (7,['Primary_input','Rents','CAPITAL','GLOBAL','Source A','',0.6,'USD',0.3,'USD']),
                       (8,['Primary_input','Direct capital','Capital','GLOBAL','Source A','',0.4,'USD',0.2,'USD']),
                       (9,['Emissions','CO2','CO2','GLOBAL','Source A','',5,'ton',3,'ton'])]:
        for col,value in enumerate(values,1):up.cell(row,col,value)
    for name in ('Sector','Region','Primary input'):book.create_sheet(name)
    s=book['Sector'];s.append(['Identifiers','Sector','Code']);s.cell(3,1,'NACE_35');s.cell(3,2,'Gas power');s.cell(3,3,'GasBL');s.cell(4,1,'NACE_35');s.cell(4,2,'Wind power');s.cell(4,3,'WindBL')
    s.cell(369,1,'ENERGY');s.cell(369,2,'Gas power');s.cell(370,2,'Wind power')
    r=book['Region'];r.cell(4,1,'EUROPE');r.cell(4,2,'France');r.cell(4,3,'FRA');r.cell(5,1,'EUROPE');r.cell(5,2,'Germany');r.cell(5,3,'DEU');r.cell(328,1,'EU28');r.cell(328,2,'France');r.cell(329,2,'Germany')
    f=book['Primary input'];f.cell(3,1,'Land');f.cell(3,3,'land');f.cell(4,1,'Capital');f.cell(4,3,'capital');f.cell(17,1,'CAPITAL');f.cell(17,2,'Land');f.cell(18,2,'Capital')
    book.create_sheet('GTAP totals').append(['Not a data collection view'])
    book.save(path)


def test_saved_values_zero_missing_and_formulas_remain_distinct(tmp_path):
    path=tmp_path/'input.xlsx';workbook(path);raw=path.read_bytes()
    table=dict(_xlsx_tables(raw))['Total production'];rows={n:{c:(v,f) for c,v,f in cells} for n,cells in table['rows']}
    assert rows[3][2]==('0',None) and rows[4][3]==(None,'=C3*2')
    assert rows[5][3]==(False,None) and rows[8][27][0]=='wide column'
    assert table['uncached_formulas']==1 and table['header_rows']==[1,2]
    out=BytesIO()
    with zipfile.ZipFile(BytesIO(raw)) as source,zipfile.ZipFile(out,'w') as target:
        for name in source.namelist():
            content=source.read(name)
            if name=='xl/worksheets/sheet1.xml':
                tree=E.fromstring(content);ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
                cell=tree.find('.//s:c[@r="C4"]',ns);value=cell.find('s:v',ns)
                if value is None:value=E.SubElement(cell,'{'+ns['s']+'}v')
                value.text='84';content=E.tostring(tree)
            target.writestr(name,content)
    table=dict(_xlsx_tables(out.getvalue()))['Total production'];rows={n:{c:(v,f) for c,v,f in cells} for n,cells in table['rows']}
    assert rows[4][3]==('84','=C3*2') and table['uncached_formulas']==0


def test_csv_preserves_quotes_precision_blank_fields_and_source_rows():
    table=_csv_table(b'country,value,note\nUSA,0,"quoted, text"\nIND,0.0000000000000000123,\n')
    assert table['rows'][1]==[2,[[1,'USA',None],[2,'0',None],[3,'quoted, text',None]]]
    assert table['rows'][2][1][1][1]=='0.0000000000000000123'


def test_cluster_members_and_codes_follow_template_scopes(tmp_path):
    path=tmp_path/'input.xlsx';workbook(path)
    tables=dict(_xlsx_tables(path.read_bytes()));clusters=_template_clusters(tables)
    assert clusters['sectors']['ENERGY']['members']==[{'name':'Gas power','code':'GasBL'},{'name':'Wind power','code':'WindBL'}]
    assert clusters['regions']['EU28']['members']==[{'name':'France','code':'FRA'},{'name':'Germany','code':'DEU'}]
    assert clusters['factors']['CAPITAL']['members']==[{'name':'Land','code':'land'},{'name':'Capital','code':'capital'}]
    assert 'Capital' not in clusters['factors']
    assert not clusters['regions']['GLOBAL']['members'] and 'catch-all' in clusters['regions']['GLOBAL']['note']


def test_only_three_categories_and_one_english_standalone_output(tmp_path):
    source=tmp_path/'Final';source.mkdir();workbook(source/'Inventory_Test.xlsx')
    folder=source/'PURDUE';folder.mkdir()
    (folder/'EXIOIOT.csv').write_text('input,sector,region,value\npdr,pdr,USA,0\n')
    trade=Workbook();s=trade.active;s.title='NTSCIF';s.append(['Sector','Origin','Destination','Value']);s.append(['pdr','USA','IND',1]);trade.create_sheet('MTRAT').append(['Excluded tariff rates']);trade.save(folder/'trade.xlsx')
    (folder/'trade.gdx').write_bytes(b'not decoded');(source/'VA.xlsx').write_bytes(b'not a collection view');(source/'unrelated.csv').write_text('ignore,value\nx,1\n')
    before={str(p.relative_to(source)):p.read_bytes() for p in source.rglob('*') if p.is_file()}
    output=write_source_dashboard(source,tmp_path/'dashboard.html');text=output.read_text()
    manifest=json.loads(re.search(r'<script id="source-data" type="application/json">(.*?)</script>',text,re.S)[1])
    assert len(manifest['files'])==3
    assert {d['category'] for d in manifest['datasets']}=={'production','trades','costs'}
    assert {d['sheet'] for d in manifest['datasets']}=={'Total production','Unit process','NTSCIF','Data'}
    inventory=next(f for f in manifest['files'] if f['partner_template']);assert inventory['contributor']=='POLIMI'
    assert inventory['clusters']['sectors']['ENERGY']['members'][1]['name']=='Wind power'
    chunks=dict(re.findall(r'id="chunk-([a-f0-9]+)">([A-Za-z0-9+/=]+)</script>',text))
    for dataset in manifest['datasets']:assert json.loads(gzip.decompress(base64.b64decode(chunks[dataset['key']])))['rows']
    assert '<html lang="en">' in text and 'Collection leads' in text
    assert 'data:image/svg+xml;base64,' in text and not re.search(r'<script[^>]+src=',text)
    assert 'MARIO_workshop_dashboard' not in text and 'disaggregated' not in text.lower() and 'disaggregato' not in text
    assert {str(p.relative_to(source)):p.read_bytes() for p in source.rglob('*') if p.is_file()}==before
    assert {p.name for p in tmp_path.iterdir()}=={'Final','dashboard.html'}


def test_same_cluster_name_keeps_each_workbooks_definition(tmp_path):
    from openpyxl import load_workbook
    for name in ('First','Second'):workbook(tmp_path/f'Inventory_{name}.xlsx')
    path=tmp_path/'Inventory_Second.xlsx';book=load_workbook(path);book['Sector'].cell(369,2,'Different member');book.save(path)
    output=write_source_dashboard(tmp_path,tmp_path/'scoped.html',matching=tmp_path/'absent.xlsx')
    manifest=json.loads(re.search(r'<script id="source-data" type="application/json">(.*?)</script>',output.read_text(),re.S)[1])
    first,second=manifest['files']
    assert first['clusters']['sectors']['ENERGY']['members'][0]['name']=='Gas power'
    assert second['clusters']['sectors']['ENERGY']['members'][0]['name']=='Different member'
