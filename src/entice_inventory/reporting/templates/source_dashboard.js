'use strict';
const sourceData=JSON.parse(document.getElementById('source-data').textContent);
const byId=id=>document.getElementById(id);
const sourceState={category:'production',lead:'',dataset:null,file:null,table:null,view:null,filtered:[],page:0,token:0,facets:new Map(),unitColumn:null};
const PAGE_SIZE=40;
let currentChunk=null,currentTable=null;
const textValue=v=>v===null||v===undefined?'':String(v);
const folded=v=>textValue(v).normalize('NFKD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
const leadName=s=>s==='PURDUE'?'Purdue':s.replace('ENEXTGEN','eNextGen');
const node=(tag,text,className)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(className)n.className=className;return n};
const cellAt=(row,col)=>row[1].find(c=>c[0]===col);
const valueAt=(row,col)=>cellAt(row,col)?.[1];
const columnName=index=>{let name='';while(index){index--;name=String.fromCharCode(65+index%26)+name;index=Math.floor(index/26)}return name};
const categoryName=id=>({production:'Total production',trades:'Trades',costs:'Cost structure'})[id];
const layouts={
 repout:{columns:[[1,'Region','regions'],[2,'Sector','sectors'],[3,'Reported output']],facets:[[2,'Sector'],[1,'Region']]},
 ntscif:{columns:[[1,'Sector','sectors'],[2,'Origin','regions'],[3,'Destination','regions'],[4,'Trade value · M USD']],facets:[[1,'Sector'],[2,'Origin'],[3,'Destination']],note:'Imports at CIF prices for traded sectors, scaled to GTAP [M USD].'},
 blttrd:{columns:[[1,'Origin','regions'],[2,'Destination','regions'],[3,'Sector','sectors'],[4,'Trade value']],facets:[[3,'Sector'],[1,'Origin'],[2,'Destination']],note:'Reported bilateral trade targets (BLTTRD). Values and scale are retained as supplied.'},
 exioiot:{columns:[[1,'Input','input'],[2,'Producing sector','sectors'],[3,'Region','regions'],[4,'Source value']],facets:[[2,'Producing sector'],[3,'Region'],[1,'Input']],note:'EXIOIOT values as supplied. These are not normalised cost shares in this view.'},
 copcosts:{columns:[[1,'Input','input'],[2,'Producing sector','sectors'],[3,'Region','regions'],[4,'Cost share']],facets:[[2,'Producing sector'],[3,'Region'],[1,'Input']],note:'Copper cost shares as supplied by Purdue.'},
 nfcostshr:{columns:[[1,'Region','regions'],[2,'Input component'],[3,'Cost share']],facets:[[1,'Region'],[2,'Input component']]},
 pfcostshr:{columns:[[1,'Input component'],[2,'Cost share']],facets:[]},
 kfcostshr:{columns:[[1,'Input component'],[2,'Cost share']],facets:[]}
};
function visibleDatasets(){const q=folded(byId('source-search').value);return sourceData.datasets.filter(d=>{const f=sourceData.files[d.file];return d.category===sourceState.category&&(!sourceState.lead||f.contributor===sourceState.lead)&&folded(d.title+' '+f.path+' '+f.contributor).includes(q)})}
function renderLeads(){
 const list=byId('lead-list');list.replaceChildren();
 const leads=[...new Set(sourceData.files.map(f=>f.contributor))].sort();
 for(const lead of ['',...leads]){
  const templates=sourceData.files.filter(f=>f.partner_template&&(!lead||f.contributor===lead)).length;
  const categories=new Set(sourceData.datasets.filter(d=>!lead||sourceData.files[d.file].contributor===lead).map(d=>d.category));
  const b=node('button',lead?leadName(lead):'All contributors','lead-button'+(sourceState.lead===lead?' active':''));b.type='button';b.setAttribute('aria-pressed',String(sourceState.lead===lead));
  b.append(node('span',templates+' partner template'+(templates===1?'':'s')+(categories.has('trades')?' · trade data':'')));
  b.addEventListener('click',()=>selectLead(lead).catch(showError));list.append(b);
 }
}
function renderSources(){
 for(const category of ['production','trades','costs']){byId('tab-'+category).className='tab'+(sourceState.category===category?' active':'');byId('tab-'+category).setAttribute('aria-pressed',String(sourceState.category===category));byId('count-'+category).textContent=sourceData.datasets.filter(d=>d.category===category&&(!sourceState.lead||sourceData.files[d.file].contributor===sourceState.lead)).length}
 const available=visibleDatasets(),list=byId('source-list');list.replaceChildren();
 for(const d of available){const f=sourceData.files[d.file];const b=node('button',undefined,'source-button'+(sourceState.dataset?.id===d.id?' active':''));b.type='button';b.setAttribute('aria-pressed',String(sourceState.dataset?.id===d.id));b.title=f.path+' · '+d.sheet;b.append(node('span',d.title,'source-name'),node('span',leadName(f.contributor),'source-lead'));b.addEventListener('click',()=>selectDataset(d.id).catch(showError));list.append(b)}
 if(!available.length)list.append(node('p','No matching sources. Select another contributor or clear the search.','empty-list'));
 byId('source-count').textContent=available.length+' source'+(available.length===1?'':'s');
}
async function selectLead(lead){sourceState.lead=lead;renderLeads();await refreshSelection()}
async function selectCategory(category){sourceState.category=category;await refreshSelection()}
async function refreshSelection(){const available=visibleDatasets();renderSources();if(available.some(d=>d.id===sourceState.dataset?.id))return;if(available.length)await selectDataset(available[0].id);else clearSelection()}
function clearSelection(){sourceState.token++;sourceState.dataset=null;sourceState.file=null;sourceState.table=null;sourceState.view=null;byId('source-title').textContent='No matching sources';byId('source-lead').textContent=categoryName(sourceState.category);byId('source-info').textContent='Choose another contributor or clear the source search.';byId('source-info').hidden=false;byId('source-path').textContent='';byId('original-link').hidden=true;byId('data-view').hidden=true;byId('cluster-dialog').close()}
async function unpackTable(key){
 if(currentChunk===key&&currentTable)return currentTable;
 if(typeof DecompressionStream==='undefined')throw new Error('Use a current browser with DecompressionStream support to read these tables.');
 const bytes=Uint8Array.from(atob(byId('chunk-'+key).textContent.trim()),c=>c.charCodeAt(0));
 const table=await new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'))).json();
 currentChunk=key;currentTable=table;return table;
}
function showError(error){byId('table-status').textContent='Unable to read this table: '+error.message;byId('data-table').replaceChildren();byId('page-status').textContent='';byId('previous-page').disabled=true;byId('next-page').disabled=true}
async function selectDataset(id){
 const d=sourceData.datasets.find(d=>d.id===id);if(!d)throw new Error('Source not found.');const f=sourceData.files[d.file],token=++sourceState.token;
 sourceState.dataset=d;sourceState.file=f;sourceState.category=d.category;sourceState.table=null;sourceState.view=null;sourceState.facets=new Map();sourceState.unitColumn=null;sourceState.filtered=[];sourceState.page=0;
 byId('cluster-dialog').close();byId('source-title').textContent=d.title;byId('source-lead').textContent=leadName(f.contributor)+' · '+categoryName(d.category);byId('source-path').textContent=f.path+' · '+d.sheet;
 const info=[];if(f.info['Parent sector'])info.push('Parent sector: '+f.info['Parent sector']);if(f.info['New sector']&&f.info['New sector']!==f.title)info.push('Sector declared in the file: '+f.info['New sector']);if(f.error)info.push('Incomplete read: '+f.error);
 byId('source-info').textContent=info.join('\n');byId('source-info').hidden=!info.length;byId('original-link').href=f.uri;byId('original-link').hidden=false;byId('data-view').hidden=false;
 byId('table-search').value='';byId('show-formulas').checked=false;byId('facets').replaceChildren();byId('data-table').replaceChildren();byId('table-empty').hidden=true;byId('table-context').hidden=true;byId('table-status').textContent='Loading source data…';byId('page-status').textContent='';byId('previous-page').disabled=true;byId('next-page').disabled=true;
 renderSources();const table=await unpackTable(d.key);if(token!==sourceState.token)return;
 sourceState.table=table;byId('formula-label').hidden=!table.formula_count;buildView();buildFacets();filterTable();
}
function buildView(){
 const d=sourceState.dataset,t=sourceState.table;
 if(d.layout==='unit_process'){
  const rows=t.rows.filter(r=>r[0]>=6&&['sector','primary input','factor of production'].includes(folded(valueAt(r,1)).replace(/_/g,' ')));
  const header=t.rows.find(r=>r[0]===1),kind=t.rows.find(r=>r[0]===2),functional=t.rows.find(r=>r[0]===3);
  const regions=(header?.[1]||[]).filter(c=>c[0]>=7&&(c[0]-7)%2===0&&c[1]!==null).map(c=>({col:c[0],region:textValue(c[1]),kind:textValue(kind&&valueAt(kind,c[0])),amount:functional&&valueAt(functional,c[0]),unit:functional&&valueAt(functional,c[0]+1)}));
  if(sourceState.unitColumn===null)sourceState.unitColumn=regions.find(r=>folded(r.kind)==='monetary')?.col||regions[0]?.col||7;
  const col=sourceState.unitColumn;
  sourceState.view={rows,columns:[[1,'Input type'],[2,'Input description'],[3,'Mapped input','mapped'],[4,'Input origin','regions'],[col,'Value'],[col+1,'Unit'],[5,'Source'],[6,'Notes']],regions,facets:[]};
 }else if(d.layout==='production'){
  const headers=t.rows.filter(r=>r[0]<=2);
  const columns=t.columns.map(col=>{const labels=headers.map(r=>valueAt(r,col)).filter(v=>v!==null&&v!==undefined&&!/free to fill/i.test(String(v)));return [col,col===1?'Region':labels.join(' · ')||columnName(col),col===1?'regions':null]});
  sourceState.view={rows:t.rows.filter(r=>r[0]>2&&valueAt(r,1)!==undefined&&valueAt(r,1)!==null&&valueAt(r,1)!==''),columns,facets:[]};
 }else{const layout=layouts[d.layout];if(!layout)throw new Error('Unknown source layout: '+d.layout);sourceState.view={...layout,rows:t.rows.filter(r=>r[0]>1)}}
 renderContext();
}
function optionLabel(value){const name=sourceData.sector_names[textValue(value).toLowerCase()];return name?value+' · '+name:textValue(value)}
function buildFacets(){
 const area=byId('facets');area.replaceChildren();const view=sourceState.view;
 if(view.regions){
  const label=node('label','Producing region / data type','facet'),select=node('select');select.setAttribute('aria-label','Producing region / data type');
  for(const r of view.regions){const o=node('option',r.region+(r.kind?' · '+r.kind:''));o.value=String(r.col);select.append(o)}select.value=String(sourceState.unitColumn);
  select.addEventListener('change',()=>{sourceState.unitColumn=Number(select.value);buildView();filterTable()});label.append(select);area.append(label);
 }
 for(const [col,title] of view.facets){
  const values=[...new Set(view.rows.map(r=>valueAt(r,col)).filter(v=>v!==null&&v!==undefined&&v!==''))].sort((a,b)=>textValue(a).localeCompare(textValue(b)));
  const label=node('label',title,'facet'),select=node('select');select.setAttribute('aria-label',title);const all=node('option','All '+title.toLowerCase()+'s');all.value='';select.append(all);
  for(const value of values){const o=node('option',title.includes('sector')||title==='Input'?optionLabel(value):textValue(value));o.value=textValue(value);select.append(o)}
  select.value='';select.addEventListener('change',()=>{sourceState.facets.set(col,select.value);filterTable()});label.append(select);area.append(label);
 }
}
function clusterFor(value,kind){
 const definitions=sourceState.file?.clusters||{};const key=textValue(value);
 if(kind==='input')return clusterFor(value,'factors')||clusterFor(value,'sectors');
 const groups=definitions[kind]||{};
 return groups[key]||(!sourceState.file?.partner_template?groups[key.toLowerCase()]:null)||null;
}
function openCluster(definition){
 byId('cluster-kind').textContent=definition.kind+' · '+(definition.members.length?definition.members.length+' listed member'+(definition.members.length===1?'':'s'):'catch-all identifier');byId('cluster-title').textContent=definition.name;
 byId('cluster-source').textContent='Definition: '+(sourceState.file.partner_template?sourceState.file.name+' · ':'')+definition.source;byId('cluster-note').textContent=definition.note;byId('cluster-note').hidden=!definition.note;
 const list=byId('cluster-members');list.replaceChildren();for(const member of definition.members){const li=node('li'),nested=clusterFor(member.name,definition.kind);if(nested&&nested!==definition){const b=node('button',member.name,'cluster-link');b.type='button';b.addEventListener('click',()=>openCluster(nested));li.append(b)}else li.append(node('span',member.name));if(member.code&&member.code!==member.name)li.append(node('code',member.code));list.append(li)}
 const dialog=byId('cluster-dialog');if(!dialog.open)dialog.showModal();
}
function clusterButton(value,kind){const definition=clusterFor(value,kind);if(!definition)return null;const b=node('button',textValue(value),'cluster-link');b.type='button';b.title='View '+kind+' definition';b.addEventListener('click',()=>openCluster(definition));return b}
function renderContext(){
 const context=byId('table-context');context.replaceChildren();const view=sourceState.view;
 if(view.regions){const r=view.regions.find(r=>r.col===sourceState.unitColumn);if(r){context.append(node('span','Producing region: '));context.append(clusterButton(r.region,'regions')||node('span',r.region));context.append(node('span',(r.kind?' · '+r.kind:'')+(r.amount!==null&&r.amount!==undefined?' · Functional unit: '+r.amount+' '+textValue(r.unit):'')))}}
 else if(view.note)context.append(node('span',view.note));context.hidden=!context.children.length;
}
function cellDisplay(cell){
 if(!cell)return {text:'—',className:'missing',title:'Blank cell'};
 const [,value,formula]=cell;if(byId('show-formulas').checked&&formula)return {text:formula,className:'formula',title:formula+(value!==null?'\nSaved value: '+textValue(value):'\nNo saved result')};
 if(value===null||value==='')return formula?{text:'ƒx',className:'formula',title:formula+'\nNo saved result'}:{text:'—',className:'missing',title:'Blank cell'};
 return {text:textValue(value),className:'',title:textValue(value)+(formula?'\nFormula: '+formula:'')};
}
function filterTable(){
 const view=sourceState.view;if(!view)return;const query=folded(byId('table-search').value),formulas=byId('show-formulas').checked,facets=[...sourceState.facets].filter(([,v])=>v!=='');sourceState.filtered=[];
 for(const row of view.rows){
  if(view.regions){const c=cellAt(row,sourceState.unitColumn);if(!c||c[1]===null&&!c[2])continue}
  if(facets.some(([col,value])=>textValue(valueAt(row,col))!==value))continue;
  if(query&&!view.columns.some(([col])=>{const c=cellAt(row,col);return c&&folded(formulas&&c[2]?c[2]:c[1]).includes(query)}))continue;
  sourceState.filtered.push(row);
 }
 sourceState.page=0;renderTable();
}
function renderTable(){
 const view=sourceState.view;if(!view)return;const table=byId('data-table');table.replaceChildren();const head=node('thead'),hr=node('tr');hr.append(node('th','#','row-number'));
 for(const [i,[col,label]] of view.columns.entries()){const th=node('th',undefined,i===0?'first-data':'');th.scope='col';th.append(node('small',columnName(col)),node('span',label,'cell-text'));th.title=label;hr.append(th)}head.append(hr);table.append(head);
 const body=node('tbody'),start=sourceState.page*PAGE_SIZE;
 for(const row of sourceState.filtered.slice(start,start+PAGE_SIZE)){
  const tr=node('tr');tr.append(node('td',String(row[0]),'row-number'));const cells=new Map(row[1].map(c=>[c[0],c]));
  for(const [i,[col,,kind]] of view.columns.entries()){const c=cells.get(col),display=cellDisplay(c),td=node('td',undefined,(i===0?'first-data ':'')+display.className);let type=kind;if(type==='mapped')type=folded(valueAt(row,1)).startsWith('primary')?'factors':'sectors';const button=kind&&c&&!display.className?clusterButton(c[1],type):null;const span=node('span',undefined,'cell-text');if(button)span.append(button);else span.textContent=display.text;span.title=columnName(col)+row[0]+'\n'+display.title;td.append(span);tr.append(td)}body.append(tr);
 }
 table.append(body);const count=sourceState.filtered.length;byId('table-empty').hidden=count!==0;byId('table-status').textContent=count.toLocaleString('en-GB')+' row'+(count===1?'':'s')+(byId('table-search').value?' matching the search':'');byId('page-status').textContent=count?(start+1)+'–'+Math.min(start+PAGE_SIZE,count)+' of '+count.toLocaleString('en-GB'):'';byId('previous-page').disabled=sourceState.page===0;byId('next-page').disabled=start+PAGE_SIZE>=count;
}
let tableSearchTimer;
for(const category of ['production','trades','costs'])byId('tab-'+category).addEventListener('click',()=>selectCategory(category).catch(showError));
byId('source-search').addEventListener('input',()=>refreshSelection().catch(showError));
byId('table-search').addEventListener('input',()=>{clearTimeout(tableSearchTimer);tableSearchTimer=setTimeout(filterTable,200)});
byId('show-formulas').addEventListener('change',filterTable);
byId('previous-page').addEventListener('click',()=>{sourceState.page=Math.max(0,sourceState.page-1);renderTable()});
byId('next-page').addEventListener('click',()=>{if((sourceState.page+1)*PAGE_SIZE<sourceState.filtered.length){sourceState.page++;renderTable()}});
byId('cluster-close').addEventListener('click',()=>byId('cluster-dialog').close());
renderLeads();renderSources();const firstSource=sourceData.datasets.find(d=>d.category==='production'&&d.title==='Manufacture of primary aluminum')||sourceData.datasets[0];
const sourceReady=selectDataset(firstSource.id).catch(showError);
