"""One workshop template for notebook and saved database dashboards."""
from importlib.resources import files
import base64
import html
import json

def _audit(report, audit_stem):
    if report is None:return '', ''
    esc=lambda value:html.escape(str(value))
    summary=report['summary'];policy=report.get('policy',{})
    review=sum(not c['passed'] for c in report['checks'])
    rows=[]
    for c in report['checks']:
        status='PASS' if c['passed'] else 'REVIEW' if c.get('enforced',True) is False else 'Outside recorded tolerance'
        value=c.get('max_absolute');unit=c.get('unit','')
        if value is not None and unit=='M USD':value*=1e6;unit='USD'
        rows.append('<tr><td>'+esc(c['name'])+'</td><td>'+status+'</td><td>'+('—' if value is None else format(value,',.6g'))+'</td><td>'+esc(unit)+'</td></tr>')
    skipped=summary.get('skipped_sectors',[])
    notice=('<div class="checks muted"><b>Saved result · internal review.</b> '+
        esc(str(summary['new_sectors'])+' added activities; '+str(summary['final_sectors'])+' total sectors. ')+
        (esc(str(len(skipped))+' planned activities remain inside their parents: '+', '.join(skipped)+'. ') if skipped else '')+
        esc(str(review)+' comparisons outside the strict recorded tolerance; residuals remain visible in the audit. ' if review else '')+
        'Economic review and environmental extensions remain separate.</div>')
    panel=('<details class="panel"><summary><b>Numerical audit, baseline and sources</b></summary><p class="muted">'+
        'Saved monetary flows and baseline are unchanged. Numerical policy: '+esc(policy.get('numerical_validation','strict'))+
        '. Strict deviations are reported without altering the saved result. Targets are prepared model inputs, not independent validation.</p>'+
        '<div class="scroll"><table><thead><tr><th>Check</th><th>Recorded result</th><th>Max absolute difference</th><th>Unit</th></tr></thead><tbody>'+''.join(rows)+'</tbody></table></div>'+
        '<p class="muted">Economic screening flags: '+esc(summary.get('review_flags',0))+'. Gross intermediate inputs where output is at most 1 USD: '+format(summary.get('zero_output_gross_z_inputs',0),',.6g')+' M USD. Undefined ratios are not replaced by zero. Environmental extensions remain pending.</p>'+
        '<p class="muted">Exact baseline: '+esc(report['provenance']['baseline'])+'</p>'+
        '<p><a href="'+esc(audit_stem+'.json')+'" download>Full numerical audit · JSON</a> · <a href="'+esc(audit_stem+'-sectors.csv')+'" download>Sector KPIs · CSV</a></p></details>')
    return notice,panel

def render_dashboard(payload, *, title='Sector disaggregation results', subtitle='', benchmark=None, audit_stem="benchmarking"):
    from plotly.offline import get_plotlyjs
    resource=files('database_disaggregation.reporting')
    page=resource.joinpath('templates/dashboard.html').read_text()
    refs=payload['references'];notice,audit=_audit(benchmark,audit_stem)
    replacements={'__PLOTLY__':get_plotlyjs(),'__TITLE__':html.escape(title),'__SUBTITLE__':html.escape(subtitle),
        '__REFERENCE_PANEL__':resource.joinpath('templates/comparisons.html').read_text().replace('__REFERENCE_YEAR__',html.escape(str(refs.get('year','')))),
        '__REFERENCE_SCRIPT__':resource.joinpath('templates/comparisons.js').read_text(),
        '__DATA__':json.dumps(payload,allow_nan=False,separators=(',',':')).replace('<',r'\u003c'),
        '__RESULT_NOTICE__':notice,'__BENCHMARK_AUDIT__':audit}
    for token,name,mime in [('__ENTICE_LOGO__','entice.svg','image/svg+xml'),('__MARIO_LOGO__','mario-logo.png','image/png')]:
        replacements[token]='data:'+mime+';base64,'+base64.b64encode(resource.joinpath('assets',name).read_bytes()).decode('ascii')
    for token,value in replacements.items():page=page.replace(token,value)
    if not refs['rows']:page=page.replace('id="show-references"','id="show-references" hidden')
    return page
