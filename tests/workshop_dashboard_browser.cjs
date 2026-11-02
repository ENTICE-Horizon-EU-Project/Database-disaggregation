// Offline browser regression for the shared MARIO workshop dashboard.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const {pathToFileURL}=require('node:url');
const path=require('node:path');
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'chrome'});
 try{
  for(const file of process.argv.slice(2)){
   const page=await browser.newPage({viewport:{width:1440,height:1050}}),errors=[],requests=[];
   page.on('pageerror',e=>errors.push(e.message));
   page.on('request',r=>{if(/^https?:/.test(r.url()))requests.push(r.url())});
  async function pickSector(code){await page.locator('#product').fill(code);await page.locator('#product-options [data-sector="'+code+'"]').click();await page.waitForFunction(code=>selectedProduct===code,code)}
   await page.goto(pathToFileURL(path.resolve(file)).href);
   await page.waitForFunction(()=>document.getElementById('output').data?.length>0);
   const meta=await page.evaluate(()=>({regions:D.regions.length,sectors:D.products.length,refs:D.references.rows.length,
      child:D.products.find(p=>D.payload[p].sector_type?.kind==='new')||D.products[0],
      commonRegion:D.references.rows.find(r=>r.region==='USA')?.region||D.references.rows[0]?.region,
      basket:D.references.rows.some(r=>r.basket==='all')?'all':D.references.rows[0]?.basket}));
   assert.match(await page.locator('label[for=product]').textContent(),/Select a sector/);
   await pickSector(meta.child);
   await page.waitForFunction(p=>document.getElementById('output').data[0].y.every((v,i)=>v===D.payload[p].output[i]),meta.child);
   await page.selectOption('#tradeview','matrix');
   await page.waitForFunction(()=>document.getElementById('trade').data[0].type==='heatmap');
   const dims=await page.evaluate(()=>({rows:document.getElementById('trade').data[0].z.length,columns:document.getElementById('trade').data[0].z[0].length}));
   assert.deepEqual(dims,{rows:meta.regions,columns:meta.regions});
   assert.equal(await page.evaluate(()=>document.getElementById('output').layout.xaxis.tickangle),-90);
   const smallNegative=await page.evaluate(()=>useScale([[-1e-13,20,100]]));
   assert.equal(smallNegative.low,-1e-13);assert.equal(smallNegative.colors[0][1],'#b2182b');
   const closure=await page.evaluate(()=>{const v=D.payload[selectedProduct];return v.totals.every((total,j)=>{const trade=v.trade.reduce((sum,row)=>sum+row[j],0);return Math.abs(total-trade)<=1e-7+1e-10*Math.abs(trade)})});
   assert.ok(closure,'All final-demand categories must be present in the use denominator.');
   const route=await page.evaluate(()=>{const v=D.payload[selectedProduct];let best=null;for(let i=0;i<D.regions.length;i++)for(let j=0;j<D.regions.length;j++)if(i!==j&&v.trade[i][j]>0&&(!best||v.trade[i][j]>best.value))best={origin:D.regions[i],destination:D.regions[j],value:v.trade[i][j]};if(best)return best;for(let i=0;i<D.regions.length;i++)if(v.trade[i][i]>0)return {origin:D.regions[i],destination:D.regions[i],value:v.trade[i][i]};return null});
   assert.ok(route);
   await page.selectOption('#tradeview','sankey');
   await page.click('#origin-picker summary');await page.click('#origin-clear');
   assert.match(await page.locator('#trade').textContent(),/Select at least one origin/);
   await page.locator('#origin-options input[value="'+route.origin+'"]').check();
   await page.click('#destination-picker summary');await page.click('#destination-clear');
   await page.locator('#destination-options input[value="'+route.destination+'"]').check();
   await page.click('#destination-picker summary');
   const one=await page.evaluate(()=>({labels:document.getElementById('trade').data[0].node.label,values:document.getElementById('trade').data[0].link.value}));
   assert.deepEqual(one.labels,['Origin · '+route.origin,'Use · '+route.destination]);assert.deepEqual(one.values,[route.value]);
   assert.match(await page.locator('#trade-selection').textContent(),/1 origin × 1 destination/);
   await page.selectOption('#tradeview','matrix');
   assert.deepEqual(await page.evaluate(()=>document.getElementById('trade').data[0].z),[[route.value]]);
   const alternate=await page.evaluate(child=>D.products.find(p=>p!==child),meta.child);
   await pickSector(alternate); // A sector change preserves the selected regions.
   assert.match(await page.locator('#trade-selection').textContent(),/1 origin × 1 destination/);
   await pickSector(meta.child);
   await page.selectOption('#tradeview','sankey');
   if(meta.regions===61){
    await page.locator('.panel').filter({has:page.locator('#output')}).screenshot({path:'/private/tmp/entice-production-vertical61.png'});
    await page.locator('.panel').filter({has:page.locator('#trade')}).screenshot({path:'/private/tmp/entice-trade-filter61.png'});
   }
   const other=await page.evaluate(route=>({origin:D.regions.find(r=>r!==route.origin),destination:D.regions.find(r=>r!==route.destination)}),route);
   await page.click('#origin-picker summary');await page.locator('#origin-options input[value="'+other.origin+'"]').check();
   await page.click('#destination-picker summary');await page.locator('#destination-options input[value="'+other.destination+'"]').check();await page.click('#destination-picker summary');
   await page.selectOption('#tradeview','matrix');
   const multi=await page.evaluate(()=>{const graph=document.getElementById('trade').data[0],values=D.payload[selectedProduct].trade;return {shown:graph.z,expected:graph.y.map(origin=>graph.x.map(destination=>values[D.regions.indexOf(origin)][D.regions.indexOf(destination)]))}});
   assert.equal(multi.shown.length,2);assert.equal(multi.shown[0].length,2);assert.deepEqual(multi.shown,multi.expected);
   await page.click('#origin-picker summary');await page.click('#origin-all');
   await page.click('#destination-picker summary');await page.click('#destination-all');await page.click('#destination-picker summary');
   assert.equal(await page.evaluate(()=>document.getElementById('trade').data[0].z.length),meta.regions);

   if(meta.regions===61)await page.screenshot({path:'/private/tmp/entice-workshop61-results.png',fullPage:true});
   if(meta.refs){
    await page.click('#show-references');await page.selectOption('#reference-region',meta.commonRegion);await page.selectOption('#reference-basket',meta.basket);
    await page.waitForFunction(()=>document.getElementById('reference-input').data?.length>0);
    const expected=await page.evaluate(()=>D.references.rows.filter(r=>r.region===document.getElementById('reference-region').value&&r.basket===document.getElementById('reference-basket').value).length+2);
    assert.equal(await page.locator('#reference-table tbody tr').count(),expected);
    const download=page.waitForEvent('download');await page.click('#export-reference-comparisons');assert.equal((await download).suggestedFilename(),'reference-comparisons-2023.csv');
    if(meta.regions===61)await page.screenshot({path:'/private/tmp/entice-workshop61-references.png',fullPage:true});
   }else{assert.equal(await page.locator('#show-references').isVisible(),false)}
   await page.setViewportSize({width:390,height:844});
   await page.waitForFunction(()=>document.documentElement.scrollWidth<=innerWidth+1,{},{timeout:10000});
   const overflow=await page.evaluate(()=>({scroll:document.documentElement.scrollWidth,width:innerWidth}));
   assert.ok(overflow.scroll<=overflow.width+1,JSON.stringify(overflow));
   if(meta.regions===61)await page.screenshot({path:'/private/tmp/entice-workshop61-mobile.png',fullPage:true});
   assert.deepEqual(errors,[]);assert.deepEqual(requests,[]);
   console.log(JSON.stringify({file:path.basename(path.dirname(file)),...meta,console_errors:errors,network_requests:requests,mobile_overflow:false}));
   await page.close();
  }
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
