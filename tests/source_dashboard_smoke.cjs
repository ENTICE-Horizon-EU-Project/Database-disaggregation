const fs=require('fs'),vm=require('vm'),assert=require('assert');
const file=process.argv[2];if(!file)throw new Error('Pass the generated HTML path.');
const html=fs.readFileSync(file,'utf8');
const manifest=JSON.parse(html.match(/<script id="source-data" type="application\/json">([\s\S]*?)<\/script>/)[1]);
class Element{
 constructor(tag){this.tagName=tag;this.children=[];this.value='';this.checked=false;this.hidden=false;this.disabled=false;this.textContent='';this.attributes={};this.events={};}
 append(...nodes){this.children.push(...nodes)}
 replaceChildren(...nodes){this.children=[...nodes]}
 setAttribute(name,value){this.attributes[name]=value}
 addEventListener(name,callback){this.events[name]=callback}
}
const ids=['file-search','file-group','file-count','file-list','file-title','file-path','file-info','original-link','table-search','show-formulas','data-view','binary-message','sheet-select','table-empty','table-status','page-status','previous-page','next-page','formula-label','data-table'];
const elements=Object.fromEntries(ids.map(id=>[id,new Element(id)]));elements['source-data']={textContent:JSON.stringify(manifest)};
for(const [,key,data] of html.matchAll(/id="chunk-([a-f0-9]+)">([A-Za-z0-9+/=]+)<\/script>/g))elements['chunk-'+key]={textContent:data};
const script=html.slice(html.lastIndexOf('<script>')+8,html.lastIndexOf('</script>'));
const context=vm.createContext({document:{getElementById(id){assert(id in elements,'Missing element '+id);return elements[id]},createElement(tag){return new Element(tag)}},Blob,Response,DecompressionStream,Uint8Array,atob,setTimeout,clearTimeout,console});
vm.runInContext(script,context);
const run=code=>vm.runInContext(code,context),select=id=>run(`selectFile(${id})`);
function text(node){return node.textContent+' '+(node.children||[]).map(text).join(' ')}
(async()=>{
 await run('sourceReady');assert(run('sourceState.table!==null'));
 assert.equal(elements['file-list'].children.length,manifest.files.length);
 // Every source file remains selectable, including binary originals.
 for(const f of manifest.files){
  await select(f.id);
  assert.equal(elements['file-title'].textContent,f.title);
  assert.equal(elements['data-view'].hidden,!f.tables.length);
  assert.equal(elements['binary-message'].hidden,!!f.tables.length);
  if(f.tables.length){assert.equal(elements['sheet-select'].children.length,f.tables.length);assert(run('sourceState.table!==null'));assert(run('sourceState.filtered.length')>=0)}
  else if(f.alternatives.length)assert(elements['binary-message'].children.some(n=>n.tagName==='button'));
 }
 const inventory=manifest.files.find(f=>f.name.includes('primary aluminum'))||manifest.files.find(f=>f.name.startsWith('Inventory_'));
 await select(inventory.id);
 elements['table-search'].value='USA';run('filterTable()');
 if(run('sourceState.filtered.length'))assert(text(elements['data-table']).toUpperCase().includes('USA'));
 elements['table-search'].value='no-matching-observation-882266';run('filterTable()');assert.equal(run('sourceState.filtered.length'),0);assert(!elements['table-empty'].hidden);
 elements['table-search'].value='';run('filterTable()');
 const count=run('sourceState.filtered.length');if(count>40){elements['next-page'].events.click();assert.equal(run('sourceState.page'),1);elements['previous-page'].events.click();assert.equal(run('sourceState.page'),0)}
 elements['show-formulas'].checked=true;run('filterTable()');assert(run('sourceState.filtered.length')>=count);
 elements['file-group'].value='Purdue';run('renderFileList()');assert.equal(elements['file-list'].children.filter(n=>n.tagName==='button').length,manifest.files.filter(f=>f.kind==='Purdue').length);
 elements['file-search'].value='no-matching-file-991182';run('renderFileList()');assert(text(elements['file-list']).includes('Nessun file'));
 elements['file-group'].value='';elements['file-search'].value='';run('renderFileList()');
 const binary=manifest.files.find(f=>!f.tables.length);if(binary){const pending=select(inventory.id);await select(binary.id);await pending;assert.equal(run('sourceState.file.id'),binary.id);assert(elements['data-view'].hidden)}
 assert(!/<script[^>]+src=/.test(html));assert(!script.includes('innerHTML'));
 console.log({files:manifest.files.length,tables:manifest.files.reduce((n,f)=>n+f.tables.length,0),all_files_opened:true,search_and_pagination:true,formulas:true,binary_alternatives:true,stale_loads_ignored:true,standalone:true});
})().catch(error=>{console.error(error);process.exitCode=1});
