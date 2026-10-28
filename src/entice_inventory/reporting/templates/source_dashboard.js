'use strict';
const sourceData=JSON.parse(document.getElementById('source-data').textContent);
const byId=id=>document.getElementById(id);
const sourceState={file:null,table:null,filtered:[],page:0,token:0};
const PAGE_SIZE=40;
let currentChunk=null,currentTable=null;
const textValue=v=>v===null||v===undefined?'':String(v);
const folded=v=>textValue(v).normalize('NFKD').replace(/[\u0300-\u036f]/g,'').toLocaleLowerCase();
function node(tag,text,className){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(className)n.className=className;return n}
function columnName(index){let name='';while(index){index--;name=String.fromCharCode(65+index%26)+name;index=Math.floor(index/26)}return name}
function renderFileList(){
 const q=folded(byId('file-search').value),group=byId('file-group').value;
 const visible=sourceData.files.filter(f=>(!group||f.kind===group)&&folded([f.title,f.path,...Object.values(f.info)].join(' ')).includes(q));
 const list=byId('file-list');list.replaceChildren();
 for(const f of visible){const b=node('button',undefined,'file-button'+(sourceState.file?.id===f.id?' active':''));b.type='button';b.title=f.path;b.setAttribute('aria-pressed',String(sourceState.file?.id===f.id));b.append(node('span',f.title,'file-name'),node('span',f.extension.toUpperCase()+' · '+f.kind,'file-kind'));b.addEventListener('click',()=>selectFile(f.id).catch(showError));list.append(b)}
 if(!visible.length)list.append(node('p','Nessun file corrispondente.','empty-list'));
 byId('file-count').textContent=visible.length+' / '+sourceData.files.length+' file';
}
async function unpackTable(key){
 if(currentChunk===key&&currentTable)return currentTable;
 if(typeof DecompressionStream==='undefined')throw new Error('Per leggere le tabelle usa un browser aggiornato con supporto DecompressionStream.');
 const encoded=byId('chunk-'+key).textContent.trim();
 const bytes=Uint8Array.from(atob(encoded),c=>c.charCodeAt(0));
 // Native gzip decoding: https://developer.mozilla.org/en-US/docs/Web/API/DecompressionStream
 const table=await new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'))).json();
 currentChunk=key;currentTable=table;return table;
}
function showError(error){byId('table-status').textContent='Impossibile leggere la tabella: '+error.message;byId('sheet-select').disabled=false;byId('data-table').replaceChildren();byId('page-status').textContent='';byId('previous-page').disabled=true;byId('next-page').disabled=true}
async function selectFile(id){
 const f=sourceData.files.find(f=>f.id===id);if(!f)throw new Error('File non trovato.');
 sourceState.file=f;sourceState.table=null;sourceState.filtered=[];sourceState.page=0;sourceState.token++;
 byId('file-title').textContent=f.title;byId('file-path').textContent=f.path;
 const info=[];if(f.info.Lead)info.push('Partner: '+f.info.Lead);if(f.info['New sector'])info.push('Settore dichiarato nel file: '+f.info['New sector']);if(f.info['Parent sector'])info.push('Settore padre: '+f.info['Parent sector']);
 if(f.error)info.push('Lettura incompleta: '+f.error);
 byId('file-info').textContent=info.join('\n');byId('file-info').hidden=!info.length;
 byId('original-link').href=f.uri;byId('original-link').title=f.path;
 byId('table-search').value='';byId('show-formulas').checked=false;
 renderFileList();const selector=byId('sheet-select');selector.replaceChildren();
 for(const [i,t] of f.tables.entries()){const option=node('option',t.name+(t.hidden?' · nascosto nel file':''));option.value=String(i);selector.append(option)}
 byId('data-view').hidden=!f.tables.length;byId('binary-message').hidden=!!f.tables.length;
 if(!f.tables.length){
  const msg=byId('binary-message');msg.replaceChildren();msg.append(node('p',f.error?'Lettura non riuscita: '+f.error:'Questo file è in formato '+f.extension.toUpperCase()+'.'));
  if(f.alternatives.length){msg.append(node('p','Per consultare le tabelle, apri la versione disponibile:'));for(const other of f.alternatives){const alternative=sourceData.files.find(v=>v.id===other);const b=node('button',alternative.name,'alternative');b.type='button';b.addEventListener('click',()=>selectFile(other).catch(showError));msg.append(b)}}
  else msg.append(node('p','Il file originale è disponibile dal collegamento qui sopra.'));
  return;
 }
 const preferred=['Total production','REPOUT','NTSCIF'];let index=-1;for(const name of preferred){index=f.tables.findIndex(t=>t.name===name);if(index>=0)break}if(index<0)index=0;selector.value=String(index);await selectSheet(index);
}
async function selectSheet(index){
 const selected=sourceState.file.tables[index];if(!selected)throw new Error('Tabella non trovata.');
 const token=++sourceState.token;sourceState.table=null;sourceState.page=0;byId('table-search').value='';byId('show-formulas').checked=false;
 byId('sheet-select').disabled=true;byId('data-table').replaceChildren();byId('table-empty').hidden=true;byId('table-status').textContent='Caricamento della tabella…';byId('page-status').textContent='';
 const table=await unpackTable(selected.key);if(token!==sourceState.token)return;
 sourceState.table=table;byId('sheet-select').disabled=false;byId('formula-label').hidden=!table.formula_count;filterTable();
}
function cellDisplay(cell){
 if(!cell)return {text:'—',className:'missing',title:'Cella vuota'};
 const [,value,formula]=cell;const formulas=byId('show-formulas').checked;
 if(formulas&&formula)return {text:formula,className:'formula',title:formula+(value!==null?'\nValore salvato: '+textValue(value):'\nNessun valore salvato')};
 if(value===null||value==='')return formula?{text:'ƒx',className:'formula',title:formula+'\nNessun valore salvato'}:{text:'—',className:'missing',title:'Cella vuota'};
 return {text:textValue(value),className:'',title:textValue(value)+(formula?'\nFormula: '+formula:'')};
}
function filterTable(){
 const t=sourceState.table;if(!t)return;const query=folded(byId('table-search').value),formulas=byId('show-formulas').checked;
 const headers=new Set(t.header_rows);sourceState.filtered=[];
 for(const row of t.rows){if(headers.has(row[0]))continue;const values=row[1].filter(c=>c[1]!==null&&c[1]!==''||(formulas&&c[2]));if(!values.length)continue;if(!query||values.some(c=>folded(formulas&&c[2]?c[2]:c[1]).includes(query)))sourceState.filtered.push(row)}
 sourceState.page=0;renderTable();
}
function renderTable(){
 const t=sourceState.table;if(!t)return;const table=byId('data-table');table.replaceChildren();
 const head=node('thead'),tr=node('tr');tr.append(node('th','#','row-number'));
 for(const [i,col] of t.columns.entries()){
  const th=node('th',undefined,i===0?'first-data':'');th.scope='col';th.append(node('small',columnName(col)));
  const labels=t.rows.filter(r=>t.header_rows.includes(r[0])).map(r=>r[1].find(c=>c[0]===col)).filter(Boolean).map(c=>textValue(c[1])).filter(Boolean);
  const label=labels.join(' · ')||columnName(col);const span=node('span',label,'cell-text');span.title=label;th.append(span);tr.append(th);
 }
 head.append(tr);table.append(head);const body=node('tbody');const start=sourceState.page*PAGE_SIZE;
 for(const [number,cells] of sourceState.filtered.slice(start,start+PAGE_SIZE)){
  const row=node('tr');row.append(node('td',String(number),'row-number'));const map=new Map(cells.map(c=>[c[0],c]));
  for(const [i,col] of t.columns.entries()){const c=cellDisplay(map.get(col));const td=node('td',undefined,(i===0?'first-data ':'')+c.className);const value=node('span',c.text,'cell-text');value.title=columnName(col)+number+'\n'+c.title;td.append(value);row.append(td)}
  body.append(row);
 }
 table.append(body);const count=sourceState.filtered.length;byId('table-empty').hidden=count!==0;
 byId('table-status').textContent=count.toLocaleString('it-IT')+' righe'+(byId('table-search').value?' corrispondenti':' con valori')+' · '+t.columns.length+' colonne';
 byId('page-status').textContent=count?(start+1)+'–'+Math.min(start+PAGE_SIZE,count)+' di '+count.toLocaleString('it-IT'):'';
 byId('previous-page').disabled=sourceState.page===0;byId('next-page').disabled=start+PAGE_SIZE>=count;
}
let tableSearchTimer;
byId('file-search').addEventListener('input',renderFileList);byId('file-group').addEventListener('change',renderFileList);
byId('sheet-select').addEventListener('change',()=>selectSheet(Number(byId('sheet-select').value)).catch(showError));
byId('table-search').addEventListener('input',()=>{clearTimeout(tableSearchTimer);tableSearchTimer=setTimeout(filterTable,200)});
byId('show-formulas').addEventListener('change',filterTable);
byId('previous-page').addEventListener('click',()=>{sourceState.page=Math.max(0,sourceState.page-1);renderTable()});
byId('next-page').addEventListener('click',()=>{if((sourceState.page+1)*PAGE_SIZE<sourceState.filtered.length){sourceState.page++;renderTable()}});
const firstSource=sourceData.files.find(f=>f.name==='Inventory_Manufacture of primary aluminum.xlsx')||sourceData.files.find(f=>f.tables.length)||sourceData.files[0];
const sourceReady=selectFile(firstSource.id).catch(showError);
