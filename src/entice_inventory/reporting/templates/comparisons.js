
const EXT=D.references;
const refElement=id=>document.getElementById(id);
const escapeRef=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const refFormat=v=>v==null||!Number.isFinite(v)?'—':new Intl.NumberFormat('en-GB',{maximumFractionDigits:2}).format(v);
const refPercent=v=>v==null?'—':refFormat(v*100)+'%';
const referenceColors={ENTICE:teal,'GTAP baseline':'#B5BEC5',EXIOBASE:'#1D3E53',EMERGING:'#4D7495',FIGARO:'#7E8899',GLORIA:'#70988C'};
function referenceOptions(id,entries,preferred){
 const el=refElement(id);el.innerHTML='';
 entries.forEach(([value,label])=>{const option=document.createElement('option');option.value=value;option.textContent=label;el.appendChild(option)});
 el.value=entries.some(([v])=>v===preferred)?preferred:(entries[0]?.[0]||'');
}
function referenceRegion(){
 const region=refElement('reference-region').value;
 const choices=new Map(EXT.rows.filter(r=>r.region===region).map(r=>[r.basket,r.label]));
 const entries=[...choices].sort((a,b)=>a[0]==='all'?-1:b[0]==='all'?1:a[1].localeCompare(b[1]));
 referenceOptions('reference-basket',entries,refElement('reference-basket').value||'all');
 refElement('reference-selection').textContent=choices.size+' comparable sectors / groups in '+region+'. Availability follows sector coverage and geographic compatibility.';
 referenceBasket();
}
function referenceBasket(){drawReference()}
function drawReference(){
 const rows=EXT.rows.filter(r=>r.region===refElement('reference-region').value&&r.basket===refElement('reference-basket').value);
 const row=rows[0];
 if(!row){refElement('reference-status').textContent='No compatible reference is available.';return}
 const commonScope=rows.every(r=>JSON.stringify([...r.entice_sectors].sort())===JSON.stringify([...row.entice_sectors].sort()));
 const baselineName=r=>'GTAP baseline'+(r.baseline_scope==='same aggregate families'?'':' · broader parent');
 const datasets=commonScope?[['ENTICE',row.entice,'ENTICE'],[baselineName(row),row.baseline,'GTAP baseline'],...rows.map(r=>[r.family,r.reference,r.family])]:rows.flatMap(r=>[['ENTICE · '+r.family+' scope',r.entice,'ENTICE'],[baselineName(r)+' · '+r.family+' scope',r.baseline,'GTAP baseline'],[r.family,r.reference,r.family]]);
 const headers=['Database','Output · M USD','Intermediate inputs / X','Imported input share','Net final demand / X','Foreign deliveries / X'];
 const cells=([label,m])=>[escapeRef(label),refFormat(m.output),refPercent(m.intermediate_input_ratio),refPercent(m.imported_input_share),refPercent(m.final_demand_ratio),refPercent(m.export_ratio)];
 refElement('reference-table').innerHTML='<table><thead><tr>'+headers.map(h=>'<th>'+h+'</th>').join('')+'</tr></thead><tbody>'+datasets.map(d=>'<tr>'+cells(d).map(v=>'<td>'+v+'</td>').join('')+'</tr>').join('')+'</tbody></table>';
 refElement('reference-status').textContent=row.label+' · '+row.region+' · All '+rows.length+' available reference database(s) shown with ENTICE and the GTAP baseline. All monetary values are in M USD.';
 refElement('reference-coverage').textContent='Inputs assigned to one broad group: '+datasets.map(([name,m])=>name+' '+refPercent(m.mixed_input_share==null?null:1-m.mixed_input_share)).join('; ')+'.';
 refElement('reference-legend').innerHTML=datasets.map(([name,,family])=>'<li><span aria-hidden="true" style="background:'+referenceColors[family]+'"></span>'+escapeRef(name)+'</li>').join('');
 const layout={...common,height:Math.max(510,120+EXT.input_groups.length*datasets.length*14),margin:{l:180,r:30,t:20,b:70},barmode:'group',bargap:.18,showlegend:false,xaxis:{title:'Input / output (%)',automargin:true},yaxis:{autorange:'reversed',automargin:true}};
 const compare=(name,values,color)=>({type:'bar',orientation:'h',name,y:EXT.input_groups,x:values.map(v=>v==null?null:100*v),marker:{color,line:{color:'white',width:.5}},hovertemplate:'%{y}<br>%{x:.2f}%<extra>'+name+'</extra>'});
 const tradeLabels=['Imported input share','Foreign deliveries / output'];
 const trace=(name,m,color)=>({type:'bar',orientation:'h',name,y:tradeLabels,x:[m.imported_input_share,m.export_ratio].map(v=>v==null?null:v*100),marker:{color,line:{color:'white',width:.5}},hovertemplate:'%{y}<br>%{x:.2f}%<extra>'+name+'</extra>'});
 const units='EXIOBASE and FIGARO converted from EUR using the recorded 2023 annual rate ('+EXT.currency.exiobase_EUR_to_USD+' USD/EUR); GLORIA converted from thousands to millions of USD. Currency conversion does not harmonise valuation or sector definitions.';
 refElement('reference-scope').innerHTML=rows.map(r=>{
  const source=EXT.sources.find(s=>s.family===r.family),flags=(EXT.entice_scope_warnings||[]).filter(w=>r.entice_sectors.includes(w.entice_code));
  return '<p><b>'+escapeRef(r.family)+' · '+escapeRef(r.comparison_basis.replaceAll('_',' '))+'</b><br>'+escapeRef(r.qualification)+'</p><p><b>ENTICE:</b> '+r.entice_sectors.map(s=>escapeRef(s+' · '+(D.payload[s]?.name||s))).join('; ')+'</p><p><b>'+escapeRef(r.family)+':</b> '+r.native_names.map(escapeRef).join('; ')+'</p><p>'+escapeRef(r.baseline_scope==='same aggregate families'?'GTAP baseline: same aggregate families.':'GTAP baseline: broader original parent, shown as context.')+'</p><p><b>Representation:</b> '+escapeRef(source?.representation||'')+'</p>'+(flags.length?'<p><b>Recorded scope notes:</b> '+flags.map(w=>escapeRef(w.entice_code+' · '+w.note)).join('; ')+'</p>':'');
 }).join('<hr>')+'<p>'+escapeRef(units)+'</p>';
 if(!refElement('references-view').hidden){
  renderPlot('reference-input',datasets.map(([name,m,family])=>compare(name,m.input_coefficients,referenceColors[family])),layout);
  renderPlot('reference-trade',datasets.map(([name,m,family])=>trace(name,m,referenceColors[family])),{...layout,height:Math.max(320,120+2*datasets.length*20),xaxis:{title:'Share (%)',automargin:true}});
 }
}
referenceOptions('reference-region',[...new Set(EXT.rows.map(r=>r.region))].sort().map(r=>[r,r]),'USA');
refElement('reference-region').addEventListener('change',referenceRegion);
refElement('reference-basket').addEventListener('change',referenceBasket);
referenceRegion();
function referenceView(show){
 refElement('results-view').hidden=show;refElement('references-view').hidden=!show;
 refElement('show-results').setAttribute('aria-selected',String(!show));refElement('show-references').setAttribute('aria-selected',String(show));
 refElement('show-results').className=show?'':'active';refElement('show-references').className=show?'active':'';
 if(show)drawReference();else draw();
}
refElement('show-results').addEventListener('click',()=>referenceView(false));
refElement('show-references').addEventListener('click',()=>referenceView(true));
