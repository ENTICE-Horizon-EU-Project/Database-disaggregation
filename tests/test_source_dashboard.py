import base64,gzip,json,re,zipfile
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as E
from openpyxl import Workbook
from entice_inventory.reporting import write_source_dashboard
from entice_inventory.reporting.source_dashboard import _xlsx_tables,_csv_table


def workbook(path):
    b=Workbook();s=b.active;s.title='Total production';s.append(['Region','2017 Value','2023 Value','Unit'])
    s.append(['Producing region','MUSD 2017','MUSD 2023',None]);s.append(['USA',0,42,'MUSD 2023']);s.append(['IND',None,'=C3*2',None]);s.append(['<script>alert(1)</script>',None,False,None]);s['AA8']='wide column';b.save(path)


def test_saved_values_zero_missing_and_formulas_remain_distinct(tmp_path):
    p=tmp_path/'input.xlsx';workbook(p);raw=p.read_bytes()
    table=dict(_xlsx_tables(raw))['Total production'];rows={n:{c:(v,f) for c,v,f in cells} for n,cells in table['rows']}
    assert rows[3][2]==('0',None)
    assert rows[4][3]==(None,'=C3*2')
    assert rows[5][3]==(False,None)
    assert 27 in table['columns'] and rows[8][27][0]=='wide column'
    assert table['uncached_formulas']==1 and table['header_rows']==[1,2]
    # Independently write the Excel cached result into the source XML.
    out=BytesIO()
    with zipfile.ZipFile(BytesIO(raw)) as z,zipfile.ZipFile(out,'w') as target:
        for name in z.namelist():
            content=z.read(name)
            if name=='xl/worksheets/sheet1.xml':
                tree=E.fromstring(content);ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
                cell=tree.find('.//s:c[@r="C4"]',ns);value=cell.find('s:v',ns)
                if value is None:value=E.SubElement(cell,'{'+ns['s']+'}v')
                value.text='84';content=E.tostring(tree)
            target.writestr(name,content)
    table=dict(_xlsx_tables(out.getvalue()))['Total production'];rows={n:{c:(v,f) for c,v,f in cells} for n,cells in table['rows']}
    assert rows[4][3]==('84','=C3*2') and table['uncached_formulas']==0


def test_csv_preserves_quotes_precision_blank_fields_and_source_rows():
    t=_csv_table(b'country,value,note\nUSA,0,"quoted, text"\nIND,0.0000000000000000123,\n')
    assert t['rows'][1]==[2,[[1,'USA',None],[2,'0',None],[3,'quoted, text',None]]]
    assert t['rows'][2][1][1][1]=='0.0000000000000000123'
    assert t['header_rows']==[1]


def test_one_standalone_output_complete_catalogue_and_gdx_alternative(tmp_path):
    source=tmp_path/'Final';source.mkdir();workbook(source/'Inventory_Test.xlsx')
    (source/'trade.csv').write_text('sector,value\np,0\n');(source/'trade.gdx').write_bytes(b'fake gdx for catalogue')
    before={p.name:p.read_bytes() for p in source.iterdir()}
    p=write_source_dashboard(source,tmp_path/'dashboard.html',database_url='database.html')
    text=p.read_text();m=json.loads(re.search(r'<script id="source-data" type="application/json">(.*?)</script>',text,re.S)[1])
    assert len(m['files'])==3
    gdx=next(f for f in m['files'] if f['extension']=='gdx');assert len(gdx['alternatives'])==1 and not gdx['tables']
    chunks=dict(re.findall(r'id="chunk-([a-f0-9]+)">([A-Za-z0-9+/=]+)</script>',text))
    for f in m['files']:
        for t in f['tables']:
            payload=json.loads(gzip.decompress(base64.b64decode(chunks[t['key']])));assert payload['rows']
    assert 'data:image/svg+xml;base64,' in text and 'href="database.html"' in text
    assert '__TABLE_CHUNKS__' not in text and not re.search(r'<script[^>]+src=',text)
    assert {p.name:p.read_bytes() for p in source.iterdir()}==before
    assert {p.name for p in tmp_path.iterdir()}=={'Final','dashboard.html'}
