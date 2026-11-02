const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const {pathToFileURL}=require('node:url');
const path=require('node:path');
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'chrome'});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1050}}),errors=[],requests=[];
  page.on('pageerror',error=>errors.push(error.message));
  page.on('request',request=>{if(/^https?:/.test(request.url()))requests.push(request.url())});
  async function pickSector(code){await page.locator('#product').fill(code);await page.locator('#product-options [data-sector="'+code+'"]').click();await page.waitForFunction(code=>selectedProduct===code,code)}
  await page.goto(pathToFileURL(path.resolve(process.argv[2])).href);
  await page.waitForFunction(()=>document.getElementById('costs').data?.length>0);
  const meta=await page.evaluate(()=>({regions:D.regions.length,sectors:D.products.length,
    child:D.products.find(p=>D.payload[p].output_reference_kind==='Constraint'),
    references:D.references.rows.length}));
  assert.ok(meta.child);
  await pickSector(meta.child);
  assert.ok(await page.evaluate(()=>D.payload.BAR?.name==='Cultivation of barley'));
  assert.match(await page.locator('#origin-options').textContent(),/United States/);
  const before=await page.evaluate(()=>{
   const v=D.payload[selectedProduct],cost=document.getElementById('costs'),uses=document.getElementById('uses');
   for(const key of ['production-note','trade-note','cost-note','use-note'])if(!document.getElementById(key).textContent.includes(selectedProduct+' · '+v.name))throw Error('Selected sector missing from '+key);
   return {names:document.getElementById('output').data.map(t=>t.name),
    costs:cost.data[0].y.length,expectedCosts:D.products.length+4,
    costRows:[...cost.data[0].y].sort(),expectedRows:[...D.cost_items].sort(),
    costX:cost.layout.xaxis.title.text,costY:cost.layout.yaxis.title.text,
    usesX:uses.layout.xaxis.title.text,usesY:uses.layout.yaxis.title.text,
    closure:v.cost_shares.every(row=>row.every(x=>x===null)||Math.abs(row.reduce((sum,value)=>sum+(value||0),0)-100)<1e-8)};
  });
  assert.ok(before.names.includes('Constraint'));
  assert.equal(await page.locator('#input-evidence').count(),0);
  assert.ok(await page.evaluate(()=>Object.values(D.payload).every(v=>!('input_provenance' in v)&&!('output_cells' in v)&&!('trade_cells' in v))));
  assert.ok(await page.evaluate(()=>D.references.sources.every(s=>!('path' in s)&&!('profile_cache' in s))));
  assert.ok(await page.evaluate(()=>[...document.querySelectorAll('a[href]')].every(a=>!a.getAttribute('href')||a.getAttribute('href').startsWith('#')||a.getAttribute('href').startsWith('blob:'))));
  assert.equal(before.costs,before.expectedCosts);assert.deepEqual(before.costRows,before.expectedRows);
  assert.equal(before.costX,'Destination regions');assert.equal(before.costY,'Input sectors / value added');
  assert.equal(before.usesX,'Destination regions');assert.equal(before.usesY,'Using sectors / final-demand categories');
  assert.ok(before.closure);
  assert.deepEqual(await page.evaluate(()=>document.getElementById('costs').data[0].y),await page.evaluate(()=>D.cost_items));
  assert.deepEqual(await page.evaluate(()=>document.getElementById('uses').data[0].y),await page.evaluate(()=>D.uses));
  assert.equal(await page.locator('#production-mode,#production-region,#cost-order,#use-order').count(),0);
  const byName=await page.evaluate(code=>D.payload[code].name.toLowerCase(),meta.child);
  await page.selectOption('#sector-kind','new');
  await page.locator('#product').fill(byName);
  assert.ok(await page.locator('#product-options [data-sector="'+meta.child+'"]').count());
  assert.ok(await page.evaluate(()=>[...document.querySelectorAll('#product-options [data-sector]')].every(o=>D.payload[o.dataset.sector].sector_type.kind==='new')));
  await page.locator('#product-options [data-sector="'+meta.child+'"]').click();
  await page.locator('#product').fill('no matching sector 123456');
  assert.match(await page.locator('#product-options').textContent(),/No sectors match/);
  await page.locator('#product').press('Escape');
  assert.equal(await page.getAttribute('#product','aria-expanded'),'false');
  for(const kind of ['residual_parent','original']){await page.selectOption('#sector-kind',kind);await page.locator('#product').fill('');assert.ok(await page.evaluate(kind=>[...document.querySelectorAll('#product-options [data-sector]')].every(o=>D.payload[o.dataset.sector].sector_type.kind===kind),kind));await page.locator('#product').press('Escape')}
  await page.selectOption('#sector-kind','all');await pickSector(meta.child);
  const region=await page.evaluate(()=>D.regions[D.payload[selectedProduct].output.map((v,i)=>({v,i})).sort((a,b)=>b.v-a.v)[1].i]);
  const regionIndex=await page.evaluate(r=>D.regions.indexOf(r),region);
  const bar=page.locator('#output .barlayer .point path').nth(regionIndex);await bar.scrollIntoViewIfNeeded();const box=await bar.boundingBox();await page.mouse.click(box.x+box.width/2,box.y+box.height/2);
  await page.waitForFunction(region=>document.getElementById('production-detail').textContent.startsWith(region+' ·'),region);
  assert.match(await page.locator('#show-references').textContent(),/Beta/);
  assert.ok(await page.locator('#references-view h2 .beta-badge').count());
  const parent=await page.evaluate(()=>D.payload[selectedProduct].sector_type.parents[0].code);
  await page.selectOption('#family-sector',parent);
  assert.equal(await page.evaluate(()=>selectedProduct),parent);
  await page.selectOption('#family-sector',meta.child);
  assert.equal(await page.evaluate(()=>selectedProduct),meta.child);
  const route=await page.evaluate(()=>{
   const v=D.payload[selectedProduct];
   for(let i=0;i<D.regions.length;i++)for(let j=0;j<D.regions.length;j++)if(i!==j&&v.trade[i][j]>0&&v.trade_constraint[i][j]!==null)return {origin:D.regions[i],destination:D.regions[j],i,j};
  });
  assert.ok(route);
  await page.click('#origin-picker summary');await page.click('#origin-clear');
  await page.locator('#origin-options input[value="'+route.origin+'"]').check();
  await page.click('#destination-picker summary');await page.click('#destination-clear');
  await page.locator('#destination-options input[value="'+route.destination+'"]').check();
  await page.click('#destination-picker summary');
  const hover=await page.evaluate(()=>document.getElementById('trade').data[0].link.customdata[0]);
  const routeNames=await page.evaluate(route=>[D.region_names[route.origin],D.region_names[route.destination]],route);for(const name of routeNames)assert.ok(hover.replaceAll('<br>',' ').includes(name));
  assert.match(hover,/Result:/);assert.match(hover,/Constraint:/);assert.match(hover,/Difference:/);assert.match(hover,/total Z \+ all Y/);assert.doesNotMatch(hover,/Input:|Trades!/);
  await page.selectOption('#tradeview','matrix');
  assert.equal(await page.evaluate(()=>document.getElementById('trade').data[0].text[0][0]),hover);
  assert.ok(await page.evaluate(()=>document.getElementById('trade').layout.height<=740));
  await page.click('#show-references');
  assert.ok(await page.locator('#reference-table tbody tr').count()>=3);
  const download=page.waitForEvent('download');await page.click('#export-reference-comparisons');
  assert.equal((await download).suggestedFilename(),'reference-comparisons-2023.csv');
  await page.setViewportSize({width:390,height:844});
  await page.waitForFunction(()=>document.documentElement.scrollWidth<=innerWidth+1);
  await page.click('#show-results');
  await page.waitForFunction(()=>document.documentElement.scrollWidth<=innerWidth+1);
  assert.deepEqual(errors,[]);assert.deepEqual(requests,[]);
  console.log(JSON.stringify({meta,all_cost_rows:true,signed_cost_closure:true,search_by_code_and_name:true,sector_type_filter:true,original_row_order:true,production_click_evidence:true,region_full_names:true,bar_full_name:true,effective_constraints:true,
   no_external_file_links:true,bilateral_hover_scope:true,sibling_navigation:true,reference_export:true,mobile_overflow:false,errors,requests}));
 }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exit(1)});
