const fs=require('fs'),vm=require('vm'),assert=require('assert');
const html=fs.readFileSync(process.argv[2],'utf8');
const manifest=JSON.parse(html.match(/<script id="source-data" type="application\/json">([\s\S]*?)<\/script>/)[1]);
class Element{
 constructor(tag){this.tagName=tag;this.children=[];this.value='';this.checked=false;this.hidden=false;this.disabled=false;this.textContent='';this.attributes={};this.events={};this.open=false;}
 append(...nodes){this.children.push(...nodes)}replaceChildren(...nodes){this.children=[...nodes]}setAttribute(k,v){this.attributes[k]=v}addEventListener(k,fn){this.events[k]=fn}showModal(){this.open=true}close(){this.open=false}
}
const elements=Object.fromEntries([...html.matchAll(/\bid="([^"]+)"/g)].map(m=>[m[1],new Element(m[1])]));
elements['source-data'].textContent=JSON.stringify(manifest);
for(const [,key,data] of html.matchAll(/id="chunk-([a-f0-9]+)">([A-Za-z0-9+/=]+)<\/script>/g))elements['chunk-'+key].textContent=data;
const script=html.slice(html.lastIndexOf('<script>')+8,html.lastIndexOf('</script>'));
const context=vm.createContext({document:{getElementById(id){assert(id in elements,'Missing element '+id);return elements[id]},createElement(tag){return new Element(tag)}},Blob,Response,DecompressionStream,Uint8Array,atob,setTimeout,clearTimeout,console});
vm.runInContext(script,context);const run=code=>vm.runInContext(code,context),select=id=>run(`selectDataset(${id})`);
function text(n){return n.textContent+' '+n.children.map(text).join(' ')}
function descendants(n){return [n,...n.children.flatMap(descendants)]}
(async()=>{
 await run('sourceReady');assert(run('sourceState.view!==null'));
 assert.equal(manifest.files.filter(f=>f.error).length,0);
 assert.deepEqual([...new Set(manifest.datasets.map(d=>d.category))].sort(),['costs','production','trades']);
 for(const d of manifest.datasets){await select(d.id);assert.equal(elements['source-title'].textContent,d.title);assert(run('sourceState.view!==null'));assert(run('sourceState.filtered.length')>=0)}
 for(const category of ['production','trades','costs']){await run(`selectCategory('${category}')`);assert.equal(run('sourceState.category'),category);assert.equal(elements['source-list'].children.filter(n=>n.tagName==='button').length,manifest.datasets.filter(d=>d.category===category).length)}
 const inventory=manifest.datasets.find(d=>d.layout==='unit_process'&&d.title==='Cultivation of barley')||manifest.datasets.find(d=>d.layout==='unit_process');
 await select(inventory.id);
 const clusters=descendants(elements['data-table']).filter(n=>n.tagName==='button'&&n.className==='cluster-link');assert(clusters.length,'Expected clickable cost clusters');clusters[0].events.click();assert(elements['cluster-dialog'].open);assert(elements['cluster-title'].textContent);elements['cluster-close'].events.click();assert(!elements['cluster-dialog'].open);
 // Definitions are scoped by input type and template; direct Capital is not CAPITAL.
 const f=manifest.files[inventory.file];if(f.clusters.factors.CAPITAL){assert(run("clusterFor('CAPITAL','factors')!==null"));assert(run("clusterFor('Capital','factors')===null"))}
 const regionSelect=elements.facets.children.flatMap(n=>n.children).find(n=>n.tagName==='select');assert(regionSelect);if(regionSelect.children.length>1){regionSelect.value=regionSelect.children[1].value;regionSelect.events.change();assert.equal(run('sourceState.unitColumn'),Number(regionSelect.value))}
 assert(run("sourceState.view.rows.every(r=>!['Emissions','Energy'].includes(valueAt(r,1)))"));
 elements['table-search'].value='no-matching-observation-882266';run('filterTable()');assert.equal(run('sourceState.filtered.length'),0);assert(!elements['table-empty'].hidden);
 elements['table-search'].value='';run('filterTable()');elements['show-formulas'].checked=true;run('filterTable()');
 const production=manifest.datasets.find(d=>d.layout==='production');await select(production.id);if(run('sourceState.filtered.length')>40){elements['next-page'].events.click();assert.equal(run('sourceState.page'),1);elements['previous-page'].events.click();assert.equal(run('sourceState.page'),0)}
 await run("selectCategory('costs')");await run("selectLead('PURDUE')");assert(elements['source-list'].children.filter(n=>n.tagName==='button').length);await run("selectCategory('trades')");assert.equal(elements['source-list'].children.filter(n=>n.tagName==='button').length,manifest.datasets.filter(d=>d.category==='trades').length);
 const trade=manifest.datasets.find(d=>d.layout==='ntscif');await select(trade.id);const sectorSelect=elements.facets.children[0].children.find(n=>n.tagName==='select');sectorSelect.value=sectorSelect.children[1].value;sectorSelect.events.change();assert(run('sourceState.filtered.length')>0);assert(run('sourceState.filtered.every(r=>valueAt(r,1)===sourceState.facets.get(1))'));
 await run("selectLead('POLIMI')");assert.equal(run('sourceState.dataset'),null);assert(elements['data-view'].hidden);await run("selectLead('')");
 elements['source-search'].value='no-matching-file-991188';await run('refreshSelection()');assert(text(elements['source-list']).includes('No matching sources'));elements['source-search'].value='';await run('refreshSelection()');
 const slow=manifest.datasets.find(d=>d.layout==='exioiot');const pending=select(slow.id);await select(production.id);await pending;assert.equal(run('sourceState.dataset.id'),production.id);assert.equal(run('sourceState.table!==null'),true);
 assert(!/<script[^>]+src=/.test(html));assert(!script.includes('innerHTML'));assert(!html.includes('MARIO_workshop_dashboard'));assert(!html.includes('database-link'));assert(html.includes('<html lang="en">'));
 console.log({source_files:manifest.files.length,datasets:manifest.datasets.length,all_datasets_opened:true,three_categories:true,lead_filters:true,region_and_sector_filters:true,cluster_dialog:true,case_sensitive_factor_clusters:true,search_and_pagination:true,stale_loads_ignored:true,english:true,standalone:true});
})().catch(e=>{console.error(e);process.exitCode=1});
