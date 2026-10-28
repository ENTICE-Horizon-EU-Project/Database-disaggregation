const fs=require('fs'),vm=require('vm'),assert=require('assert');
const html=fs.readFileSync(process.argv[2],'utf8');const metadata=JSON.parse(html.match(/<script id="source-data" type="application\/json">([\s\S]*?)<\/script>/)[1]);
class Element{
 constructor(tag){this.tagName=tag;this.children=[];this.value='';this.checked=false;this.hidden=false;this.disabled=false;this.textContent='';this.attributes={};this.events={};this.open=false;this.style={};}
 append(...nodes){this.children.push(...nodes)}replaceChildren(...nodes){this.children=[...nodes]}setAttribute(k,v){this.attributes[k]=v}addEventListener(k,fn){this.events[k]=fn}showModal(){this.open=true}close(){this.open=false}
}
const elements=Object.fromEntries([...html.matchAll(/\bid="([^"]+)"/g)].map(m=>[m[1],new Element(m[1])]));elements['source-data'].textContent=JSON.stringify(metadata);
for(const [,key,value] of html.matchAll(/id="chunk-([A-Z0-9_]+)">([A-Za-z0-9+/=]+)<\/script>/g))elements['chunk-'+key].textContent=value;
const script=html.slice(html.lastIndexOf('<script>')+8,html.lastIndexOf('</script>'));
const ctx=vm.createContext({document:{getElementById(id){assert(id in elements,'Missing element '+id);return elements[id]},createElement(tag){return new Element(tag)}},Blob,Response,DecompressionStream,Uint8Array,atob,setTimeout,clearTimeout,console});vm.runInContext(script,ctx);const run=code=>vm.runInContext(code,ctx);
function all(n){return [n,...n.children.flatMap(all)]}function content(n){return n.textContent+' '+n.children.map(content).join(' ')}
(async()=>{
 await run('collectionReady');assert.equal(elements['sector-select'].children.length,metadata.sectors.length);
 assert(!html.includes('sheet-select'));assert(!html.includes('source-search'));assert(!html.includes('EXIOIOT'));assert(!html.includes('MARIO_workshop_dashboard'));
 for(const view of ['production','costs','trades']){
  await run(`changeView('${view}')`);
  if(view==='trades'){elements['origin-select'].value=Object.keys(metadata.regions)[0];elements['destination-select'].value=Object.keys(metadata.regions)[1]}
  for(const s of metadata.sectors){run(`state.sector=${JSON.stringify(s.id)};state.page=0`);await run('render()');assert.equal(elements['view-title'].textContent,s.name);assert(!elements['view-status'].textContent.startsWith('Unable'),s.id+' '+view);assert(content(elements['collector-summary']).includes(s[view].collector))}
 }
 await run("changeView('production')");await run("changeMode('region')");assert.equal(elements['region-select'].hidden,false);assert.equal(elements['data-table'].children[1].children.length,metadata.sectors.length);
 const missing=metadata.sectors.find(s=>s.id==='NMC');if(missing){run("state.sector='NMC'");await run("changeMode('sector')");assert(content(elements['view-status']).includes('0 numeric observations'));assert(!all(elements['data-table']).some(n=>n.tagName==='div'&&n.className==='bar'))}
 run("state.sector='APP'");await run("changeMode('sector')");await run("changeView('costs')");const buttons=all(elements['data-table']).filter(n=>n.tagName==='button'&&n.className==='cluster-link');assert(buttons.length);buttons[0].events.click();assert(elements['definition-dialog'].open);assert(elements['definition-members'].children.length>0);elements['definition-close'].events.click();assert(!elements['definition-dialog'].open);
 await run("changeMode('region')");assert.equal(elements['sector-control'].hidden,true);assert.equal(elements['region-control'].hidden,false);const app=await run("loadSector('APP')");ctx.samplePayload=app;assert.equal(run("profileAt(samplePayload,'USA').geo"),'USA');
 const columnsBefore=elements['columns-status'].textContent;run('state.page=1');await run('render()');assert.notEqual(elements['columns-status'].textContent,columnsBefore);
 elements['row-search'].value='no-such-input-993399';await run('render()');assert(!elements['view-empty'].hidden);elements['row-search'].value='';
 const direct=await run("loadSector('MCU')");const edge=direct.trade.edges[0];run("state.sector='MCU'");elements['origin-select'].value=edge[0];elements['destination-select'].value=edge[1];await run("changeView('trades')");assert.equal(elements['data-table'].children[1].children[0].children[1].textContent,run('number('+edge[2]+')'));assert(elements['collector-summary'].textContent.includes('Purdue'));
 run("state.sector='APP'");await run('render()');if(app.trade.scope==='product_group')assert(elements['view-description'].textContent.includes('product group'));
 const unavailable=metadata.sectors.find(s=>s.trades.collector==='Not available');if(unavailable){run('state.sector='+JSON.stringify(unavailable.id));await run('render()');assert(!elements['view-empty'].hidden);assert(elements['view-empty'].textContent.includes('No directly collected'))}
 const bvl=metadata.sectors.find(s=>s.id==='BVL');if(bvl&&metadata.regions.AUT){ctx.overlapPayload=await run("loadSector('BVL')");assert.equal(run("profileAt(overlapPayload,'AUT')"),null);run("state.region='AUT'");await run("changeView('costs')");await run("changeMode('region')");elements['column-search'].value='BVL';await run('render()');assert(content(elements['view-empty']).includes('Overlapping group recipes'));elements['column-search'].value='';}
 const a=run("changeView('production')"),b=run("changeView('costs')");await Promise.all([a,b]);assert(elements['view-eyebrow'].textContent.includes('Cost Structure'));assert(!/<script[^>]+src=/.test(html));assert(!script.includes('innerHTML'));
 console.log({sectors:metadata.sectors.length,all_sectors_opened_in_three_views:true,production_by_region:true,costs_by_region:true,cluster_definitions:true,role_specific_contributors:true,exact_trade_cell:true,group_trade_labelled:true,missing_values_preserved:true,search_and_pagination:true,stale_loads_ignored:true,english:true,standalone:true});
})().catch(e=>{console.error(e);process.exitCode=1});
