'use strict';
const data=JSON.parse(document.getElementById('source-data').textContent);
const el=id=>document.getElementById(id);
const state={view:'production',mode:'sector',sector:data.sectors.some(s=>s.id==='APP')?'APP':data.sectors[0].id,region:data.regions.USA?'USA':Object.keys(data.regions)[0],page:0,token:0};
const cache=new Map(),COLS=12;
const text=v=>v===null||v===undefined?'':String(v);
const fold=v=>text(v).normalize('NFKD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
const node=(tag,value,cls)=>{const n=document.createElement(tag);if(value!==undefined)n.textContent=value;if(cls)n.className=cls;return n};
const sector=id=>data.sectors.find(s=>s.id===id);
const number=v=>v===null||v===undefined?'—':v!==0&&Math.abs(v)<.001?Number(v).toExponential(2):new Intl.NumberFormat('en-GB',{maximumFractionDigits:2}).format(v);
function matches(query,...values){return !query||fold(values.join(' ')).includes(query)}
async function loadSector(id){
 if(!cache.has(id))cache.set(id,(async()=>{if(typeof DecompressionStream==='undefined')throw new Error('A current browser is required to open the data.');const bytes=Uint8Array.from(atob(el(data.chunks[id]).textContent.trim()),c=>c.charCodeAt(0));return new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'))).json()})());
 return cache.get(id);
}
function labelCell(name,code,definition){const span=node('span',undefined,'row-label');if(definition){const b=node('button',name,'cluster-link');b.type='button';b.addEventListener('click',()=>openDefinition(definition));span.append(b)}else span.textContent=name;if(code)span.append(node('span',code,'code'));return span}
function geoDefinition(id){const g=data.geographies[id];return g?.is_group?{name:g.name,kind:'Region group',note:g.estimated?'Existing estimated recipe for the listed regions.':'This observation or recipe covers the listed regions as a group.',members:g.members.map(code=>({code,name:data.regions[code]}))}:null}
function openDefinition(definition){el('definition-title').textContent=definition.name;el('definition-kind').textContent=definition.kind;el('definition-note').textContent=definition.note||'';const list=el('definition-members');list.replaceChildren();for(const m of definition.members){const li=node('li');li.append(node('code',m.code),node('span',m.name));list.append(li)}if(!el('definition-dialog').open)el('definition-dialog').showModal()}
function configure(){
 for(const view of ['production','costs','trades']){el('tab-'+view).className='tab'+(state.view===view?' active':'');el('tab-'+view).setAttribute('aria-pressed',String(state.view===view))}
 for(const mode of ['sector','region']){el('mode-'+mode).className=state.mode===mode?'active':'';el('mode-'+mode).setAttribute('aria-pressed',String(state.mode===mode))}
 el('row-search-caption').textContent=state.view==='costs'?'Find an input':state.view==='trades'?'Find an origin region':state.mode==='sector'?'Find a region':'Find a sector';el('column-search-caption').textContent=state.view==='trades'?'Find a destination region':state.mode==='sector'?'Find a region or group':'Find a sector';
 const trades=state.view==='trades',matrix=state.view!=='production';el('mode-control').hidden=trades;el('sector-control').hidden=!trades&&state.mode!=='sector';el('region-control').hidden=trades||state.mode!=='region';el('origin-control').hidden=!trades;el('destination-control').hidden=!trades;
 el('column-search-label').hidden=!matrix;el('all-inputs-label').hidden=state.view!=='costs';el('matrix-pager').hidden=!matrix;
 el('row-search').placeholder=state.view==='costs'?'Input name or code…':trades?'Origin region…':'Region or sector…';el('column-search').placeholder=trades?'Destination region…':state.mode==='sector'?'Region or group…':'Sector name or code…';
}
function showError(error){el('view-status').textContent='Unable to display data: '+error.message;el('view-empty').textContent='Data could not be loaded.';el('view-empty').hidden=false}
function setTitle(eyebrow,title,description){el('view-eyebrow').textContent=eyebrow;el('view-title').textContent=title;el('view-description').textContent=description}
function tableHead(labels){const head=node('thead'),row=node('tr');for(const [i,label] of labels.entries()){const th=node('th',label,i===0?'sticky-label':'');th.scope='col';row.append(th)}head.append(row);return head}
function provenance(records){
 const unique=[...new Set(records.map(s=>s[state.view].collector))].sort();el('collector-summary').textContent='Collected by: '+unique.join(' · ');
 const groups=new Map();for(const s of records){const info=s[state.view],key=info.collector+'|'+info.reference;let g=groups.get(key);if(!g){g={...info,sectors:[]};groups.set(key,g)}g.sectors.push(s.name)}
 const list=el('source-list');list.replaceChildren();for(const g of groups.values()){const div=node('div',undefined,'source-entry');div.append(node('strong',g.collector),node('div',g.reference),node('div',g.sectors.length===1?g.sectors[0]:g.sectors.length+' sectors'));div.title=g.sectors.join('\n');list.append(div)}
 el('source-note').textContent=records.length===1?records[0][state.view].note:'Collection leads are shown for each sector. Missing observations remain unavailable; group observations are not copied into individual-country totals.';
}
function empty(message){el('data-table').replaceChildren();el('view-empty').hidden=false;el('view-empty').textContent=message;el('legend').hidden=true;el('view-status').textContent='';el('columns-status').textContent='';el('previous-columns').disabled=true;el('next-columns').disabled=true}
function productionAt(payload,region){const direct=payload.production.find(r=>r.geo===region);if(direct)return direct;const groups=payload.production.filter(r=>data.geographies[r.geo]?.members.includes(region));return {value:null,status:groups.length?'Reported only for a region group':'Not available',groups:groups.map(r=>data.geographies[r.geo].name)}}
function renderProduction(payloads){
 const query=fold(el('row-search').value);let records;
 if(state.mode==='sector'){
  const s=sector(state.sector),p=payloads.get(s.id);setTitle('Total Production · '+data.year,s.name,'Production observations in million USD. Region-group totals are shown separately from country observations.');
  const observed=p.production.map(r=>{const g=data.geographies[r.geo];return {...r,id:r.geo,name:g.name,collector:s.production.collector,definition:geoDefinition(r.geo),status:g.is_group?'Region-group total · '+r.status:r.status}});
  const covered=new Set(observed.map(r=>r.id));records=[...observed,...Object.entries(data.regions).filter(([id])=>!covered.has(id)).map(([id,name])=>({id,name,...productionAt(p,id),collector:s.production.collector}))];provenance([s]);
 }else{
  setTitle('Total Production · '+data.year,data.regions[state.region],'Production by sector, in million USD. A reported group total is not treated as an individual-country value.');
  records=data.sectors.map(s=>({id:s.id,name:s.name,...productionAt(payloads.get(s.id),state.region),collector:s.production.collector}));provenance(data.sectors);
 }
 records=records.filter(r=>matches(query,r.name,r.id)).sort((a,b)=>(b.value??-1)-(a.value??-1)||a.name.localeCompare(b.name));
 const table=el('data-table');table.replaceChildren();el('view-empty').hidden=!!records.length;el('legend').hidden=true;
 if(!records.length){empty('No observations match the selection.');return}
 table.append(tableHead([state.mode==='sector'?'Region / region group':'Sector','Production','million USD','Coverage','Collected by']));const head=table.children[0].children[0];head.children[1].className='bar-cell';const body=node('tbody'),max=Math.max(...records.map(r=>r.value||0),1);
 for(const r of records){const tr=node('tr'),label=node('td',undefined,'sticky-label');label.append(labelCell(r.name,r.id.startsWith('g:')?'':r.id,r.definition));tr.append(label);const bar=node('td',undefined,'bar-cell');if(r.value!==null){const track=node('div',undefined,'bar-track'),fill=node('div',undefined,'bar');fill.style.width=(100*r.value/max)+'%';track.append(fill);bar.append(track)}tr.append(bar);const value=node('td',number(r.value),'number'+(r.value===null?' unavailable':''));value.title=r.value===null?(r.groups||[]).join(', '):text(r.value)+' million USD';tr.append(value,node('td',r.status,'status'),node('td',r.collector));body.append(tr)}
 table.append(body);el('view-status').textContent=records.filter(r=>r.value!==null).length+' numeric observations · '+records.filter(r=>r.value===null).length+' unavailable country/sector values. No missing value is replaced by zero.';
}
function profileCandidates(payload,region){return payload.profiles.filter(p=>Object.keys(p.values).length&&data.geographies[p.geo].members.includes(region))}
function profileAt(payload,region){
 const direct=payload.profiles.find(p=>p.geo===region&&Object.keys(p.values).length);if(direct)return direct;
 const candidates=profileCandidates(payload,region),collected=candidates.filter(p=>!data.geographies[p.geo].estimated);
 if(collected.length===1)return collected[0];if(!collected.length&&candidates.length===1)return candidates[0];return null;
}
function pageColumns(columns){const total=columns.length;state.page=Math.min(state.page,Math.max(0,Math.ceil(total/COLS)-1));const start=state.page*COLS;el('columns-status').textContent=total?(start+1)+'–'+Math.min(start+COLS,total)+' of '+total+' columns':'No columns';el('previous-columns').disabled=state.page===0;el('next-columns').disabled=start+COLS>=total;return columns.slice(start,start+COLS)}
function colour(value,max){if(value<0)return {background:'#eee8f5',color:'#694786'};const t=Math.sqrt(Math.min(1,Math.max(0,value/max)));const a=[246,251,249],b=[24,87,109];return {background:'rgb('+a.map((v,i)=>Math.round(v+(b[i]-v)*t)).join(',')+')',color:t>.65?'#ffffff':'#193c50'}}
function matrixLegend(unit,max,extra){const legend=el('legend');legend.replaceChildren();legend.hidden=false;legend.append(node('span',unit),node('span','0'),node('span',undefined,'colour-ramp'),node('span',number(max)),node('span',undefined,'missing-key'),node('span','Unavailable / outside scope'));if(extra)legend.append(node('span',extra))}
function renderCosts(payloads){
 const q=fold(el('row-search').value),cq=fold(el('column-search').value);let columns;
 if(state.mode==='sector'){
  const s=sector(state.sector);setTitle('Cost Structure',s.name,'Compare input recipes across producing regions and the region groups used in the collection.');
  columns=payloads.get(s.id).profiles.map(p=>{const g=data.geographies[p.geo];return {id:p.geo,name:g.name,profile:p,collector:s.costs.collector,definition:geoDefinition(p.geo),sub:p.status}});provenance([s]);
 }else{
  setTitle('Cost Structure',data.regions[state.region],'Compare sector input recipes for this region. Region-group recipes are identified in the columns. Overlapping group recipes are left unresolved.');
  columns=data.sectors.map(s=>{const payload=payloads.get(s.id),p=profileAt(payload,state.region),alternatives=profileCandidates(payload,state.region);return {id:s.id,name:s.name,profile:p,collector:s.costs.collector,sub:p?(data.geographies[p.geo].is_group?data.geographies[p.geo].name:p.status):alternatives.length>1?'Overlapping group recipes; see sector view':'Not available'}});provenance(data.sectors);
 }
 columns=columns.filter(c=>matches(cq,c.name,c.id,c.sub)).sort((a,b)=>a.name.localeCompare(b.name));
 const keys=[...new Set(columns.flatMap(c=>Object.keys(c.profile?.values||{})))];let inputs=keys.map(id=>data.items[id]).filter(i=>matches(q,i.name,...i.members.flatMap(m=>[m.code,m.name])));
 inputs.sort((a,b)=>Math.max(...columns.map(c=>Math.abs(c.profile?.values[b.id]||0)))-Math.max(...columns.map(c=>Math.abs(c.profile?.values[a.id]||0)))||a.name.localeCompare(b.name));const allCount=inputs.length;if(!el('all-inputs').checked&&!q)inputs=inputs.slice(0,25);
 const shown=pageColumns(columns);if(state.mode==='region'&&columns.length)provenance(data.sectors.filter(s=>columns.some(c=>c.id===s.id)));if(!shown.length||!inputs.length){empty(shown.some(c=>c.sub.startsWith('Overlapping'))?'Overlapping group recipes: no single recipe can be assigned to this region. Explore the sector view to inspect each group.':'No cost observations match this selection.');return}
 const table=el('data-table');table.replaceChildren();el('view-empty').hidden=true;const head=node('thead'),hr=node('tr');hr.append(node('th','Input sector / factor','sticky-label'));
 for(const c of shown){const th=node('th',undefined,'heat-head');th.scope='col';th.append(labelCell(c.name,c.id.startsWith('g:')?'':c.id,c.definition),node('small',c.sub),node('small',c.collector));hr.append(th)}head.append(hr);table.append(head);
 const max=Math.max(...inputs.flatMap(i=>shown.map(c=>Math.abs(c.profile?.values[i.id]||0)*100)),1e-9),body=node('tbody');
 for(const i of inputs){const tr=node('tr'),label=node('td',undefined,'sticky-label');label.append(labelCell(i.name,i.kind,i.is_group?{name:i.name,kind:i.kind==='Sector'?'Input-sector group':'Factor group',note:'The listed members are retained as one collected input group. Its value has not been divided between members.',members:i.members}:null));tr.append(label);
  for(const c of shown){const value=c.profile?(c.profile.values[i.id]||0)*100:null,td=node('td',number(value),'heat-cell'+(value===null?' unavailable':''));if(value!==null)Object.assign(td.style,colour(value,max));td.title=i.name+' → '+c.name+'\n'+(value===null?'No available recipe':text(value)+' per 100 output units')+'\nCollected by: '+c.collector+'\n'+c.sub;tr.append(td)}body.append(tr)}
 table.append(body);matrixLegend('Input cost per 100 output units',max,'Purple values, if present, are negative.');el('view-status').textContent=inputs.length+' of '+allCount+' input categories · '+columns.length+' comparison columns. Original coefficients are retained; column totals may differ from 100.';
}
const groupNames={ALM:'Aluminium',IST:'Iron and steel',LBT:'Batteries',PLT:'Plastics',CEMN:'Cement',HYD:'Hydrogen'};
function renderTrades(payloads){
 const s=sector(state.sector),p=payloads.get(s.id),trade=p.trade,q=fold(el('row-search').value),cq=fold(el('column-search').value);provenance([s]);
 let description='International trade in million USD. Rows are origins; columns are destinations.';
 if(trade.scope==='product_group')description='Collected for the '+(groupNames[trade.product]||trade.product)+' product group. Individual-sector trade is not separately reported. Rows are origins; columns are destinations.';
 setTitle('Trades'+(trade.scope==='product_group'?' · product-group coverage':''),s.name,description);
 if(trade.scope==='unavailable'){empty('No directly collected trade series is available for this sector.');return}
 const origin=el('origin-select').value,destination=el('destination-select').value;
 const origins=Object.entries(data.regions).filter(([id,name])=>(!origin||id===origin)&&matches(q,id,name)).sort((a,b)=>a[1].localeCompare(b[1]));
 const columns=Object.entries(data.regions).filter(([id,name])=>(!destination||id===destination)&&matches(cq,id,name)).map(([id,name])=>({id,name})).sort((a,b)=>a.name.localeCompare(b.name));const shown=pageColumns(columns);
 if(!origins.length||!shown.length){empty('No trade routes match this selection.');return}
 const values=new Map(trade.edges.map(([o,d,v])=>[o+'|'+d,v]));const max=Math.max(...origins.flatMap(([o])=>shown.map(d=>values.get(o+'|'+d.id)||0)),1e-9);
 const table=el('data-table');table.replaceChildren();el('view-empty').hidden=true;const head=node('thead'),hr=node('tr');hr.append(node('th','Origin ↓ / destination →','sticky-label'));
 for(const c of shown){const th=node('th',undefined,'heat-head');th.scope='col';th.append(labelCell(c.name,c.id));hr.append(th)}head.append(hr);table.append(head);const body=node('tbody');
 for(const [id,name] of origins){const tr=node('tr'),label=node('td',undefined,'sticky-label');label.append(labelCell(name,id));tr.append(label);for(const c of shown){const value=id===c.id?null:values.get(id+'|'+c.id)||0;const td=node('td',number(value),'heat-cell'+(value===null?' unavailable':''));if(value!==null)Object.assign(td.style,colour(value,max));td.title=name+' → '+c.name+'\n'+(value===null?'Domestic flows are outside this view':text(value)+' million USD')+'\nCollected by Purdue'+(trade.scope==='product_group'?'\nCoverage: '+trade.members.map(id=>sector(id)?.name||id).join('; '):'');tr.append(td)}body.append(tr)}table.append(body);matrixLegend('million USD',max);el('view-status').textContent=origins.length+' origin regions · '+columns.length+' destination regions.'+(trade.scope==='product_group'?' The same collected group series applies to: '+trade.members.map(id=>sector(id)?.name||id).join('; ')+'.':'');
}
async function render(){
 const token=++state.token;configure();el('view-status').textContent='Loading observations…';el('data-table').replaceChildren();el('view-empty').hidden=true;el('definition-dialog').close();
 const ids=state.view!=='trades'&&state.mode==='region'?data.sectors.map(s=>s.id):[state.sector];const payloads=new Map(await Promise.all(ids.map(async id=>[id,await loadSector(id)])));if(token!==state.token)return;
 if(state.view==='production')renderProduction(payloads);else if(state.view==='costs')renderCosts(payloads);else renderTrades(payloads);
}
function changeView(view){state.view=view;state.page=0;el('row-search').value='';el('column-search').value='';return render()}
function changeMode(mode){state.mode=mode;state.page=0;el('row-search').value='';el('column-search').value='';return render()}
for(const s of [...data.sectors].sort((a,b)=>a.name.localeCompare(b.name))){const o=node('option',s.name+' · '+s.id);o.value=s.id;el('sector-select').append(o)}el('sector-select').value=state.sector;
for(const [id,name] of Object.entries(data.regions).sort((a,b)=>a[1].localeCompare(b[1])))for(const control of ['region-select','origin-select','destination-select']){const o=node('option',name+' · '+id);o.value=id;el(control).append(o)}el('region-select').value=state.region;
for(const view of ['production','costs','trades'])el('tab-'+view).addEventListener('click',()=>changeView(view).catch(showError));
for(const mode of ['sector','region'])el('mode-'+mode).addEventListener('click',()=>changeMode(mode).catch(showError));
el('sector-select').addEventListener('change',()=>{state.sector=el('sector-select').value;state.page=0;render().catch(showError)});el('region-select').addEventListener('change',()=>{state.region=el('region-select').value;state.page=0;render().catch(showError)});
for(const id of ['origin-select','destination-select','all-inputs'])el(id).addEventListener('change',()=>{state.page=0;render().catch(showError)});
let timer;for(const id of ['row-search','column-search'])el(id).addEventListener('input',()=>{clearTimeout(timer);timer=setTimeout(()=>{state.page=0;render().catch(showError)},150)});
el('previous-columns').addEventListener('click',()=>{state.page=Math.max(0,state.page-1);render().catch(showError)});el('next-columns').addEventListener('click',()=>{state.page++;render().catch(showError)});
el('definition-close').addEventListener('click',()=>el('definition-dialog').close());
el('collection-summary').textContent=data.sectors.length+' active sectors · '+Object.keys(data.regions).length+' regions';
const collectionReady=render().catch(showError);
