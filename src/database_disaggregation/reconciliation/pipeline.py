"""Produce reconciled inventories and complete audit evidence, without a split solve."""
from collections import Counter
import csv
import hashlib
from importlib.metadata import version
import json
import logging
from pathlib import Path
import platform

import pandas as pd

from database_disaggregation.core.baseline import load_baseline
from database_disaggregation.core.geography import Geography
from database_disaggregation.core.paths import data_path, local_config
from database_disaggregation.core.parent_budgets import (
    ChildTargets, ParentBudgets, evaluate_parent_budgets, read_child_targets, require_parent_budgets,
    OUTPUT_COLUMNS, TRADE_COLUMNS,
)
from database_disaggregation.core.registry import Registry
from .audit import Audit
from .baseline import NativeBaseline
from .policy import load_policy
from .profiles import ProfileBuilder
from .sources import Sources
from .targets import resolve_parents, prepare_outputs, prepare_trade, reconcile_trade

logger=logging.getLogger(__name__)


def _csv(path,rows,columns):
    with path.open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=columns)
        writer.writeheader();writer.writerows(rows)


def reconcile_inventories(source_dir,output_dir,*,geography=None,policy=True,baseline_path=None,
                          baseline_format=None,output_reference_dir=None,source_paths=None,
                          selected_database=None,registry=None):
    """Build a new run directory; success is marked only after read-back checks.

    The function never rewrites source workbooks or baseline matrices. A failed
    run retains ``failure.json`` and audit records without a success manifest.
    ``source_paths`` explicitly overrides existing source roles; a None trade
    path is supported for custom policies which intentionally use parent priors.
    """
    output_dir=Path(output_dir)
    if output_dir.exists():raise FileExistsError(f'Reconciliation output already exists: {output_dir}')
    policy,policy_sha=load_policy(policy)
    output_dir.mkdir(parents=True)
    reports=output_dir/'audit';audit=Audit(reports)
    (reports/'policy.json').write_text(json.dumps(policy,indent=2))
    registry=registry or Registry.load()
    try:
        code_fingerprints={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob('*.py')}
        import mario
        integration_files=[(f'database_disaggregation/core/{name}.py',Path(__file__).parent.parent/'core'/f'{name}.py')
                           for name in ('disaggregation','geography','parent_budgets','registry','paths','baseline')]
        integration_files += [(f'mario/ops/{name}.py',Path(mario.__file__).parent/'ops'/f'{name}.py')
                              for name in ('add_sector_steps','add_sector_workbook')]
        integration_fingerprints={name:hashlib.sha256(path.read_bytes()).hexdigest() for name,path in integration_files}
        logger.info('Reading native baseline budgets and explicit source decisions.')
        baseline_path=Path(baseline_path) if baseline_path is not None else data_path('baseline',required=True)
        baseline_format=baseline_format or local_config().get('baseline_format','mario_parquet')
        original=None if baseline_format=='mario_parquet' else load_baseline(baseline_path,baseline_format)
        native=NativeBaseline(baseline_path,database=original,audit=audit)
        geography=geography or Geography({r:r for r in native.regions},'native')
        geography.validate(native.regions)
        database=selected_database or load_baseline(baseline_path,baseline_format,geography=geography)
        files=sorted(p for p in Path(source_dir).glob('*.xlsx') if not p.name.startswith('~$'))
        if not files:raise ValueError('No resolved native inventory files supplied.')
        references=None
        if output_reference_dir is not None:
            from database_disaggregation.core.disaggregation import read_output_references
            references=read_output_references(output_reference_dir,
                read_bytes=lambda path:audit.read(path,role='original_output_reference'))
        targets=read_child_targets(files,output_references=references)
        for path,digest in targets.sources.items():
            if path not in audit.files:
                audit.files[path]={'sha256':digest,'bytes':Path(path).stat().st_size,'role':'resolved_inventory'}
        parents,old_parents=resolve_parents(policy,targets,registry,native,audit)
        native_budget=native.budgets
        budgets=native_budget.aggregate(geography)
        before=evaluate_parent_budgets(budgets,targets.aggregate(geography))
        (reports/'checks_before.json').write_text(json.dumps(before,indent=2,allow_nan=False))
        paths={}
        for name in ('purdue_split_targets','purdue_trade','partner_templates'):
            if source_paths is not None and name in source_paths:
                paths[name]=Path(source_paths[name]) if source_paths[name] is not None else None
            else:
                needed=name=='purdue_trade' or (name=='purdue_split_targets' and any(r['output_source']['kind']=='purdue' for r in policy['sectors'].values()))
                needed|=name=='partner_templates' and any(r['output_source']['kind'].startswith('template') for r in policy['sectors'].values())
                paths[name]=data_path(name,required=needed) if needed else None
        sources=Sources(paths,registry,native,policy,audit)
        logger.info('Preparing all native output targets and geographic observations.')
        native_outputs,outputs,confidence=prepare_outputs(policy,sources,native,geography,targets,parents,old_parents,audit)
        priors,kinds=prepare_trade(policy,sources,native,geography,parents,native_outputs,outputs,audit)
        trade,solver_records=reconcile_trade(priors,kinds,parents,outputs,budgets,policy,audit)
        logger.info('Output and trade reconciliation complete; constructing technology priors.')
        master=pd.DataFrame([[c,parents[c],'Split'] for c in parents],columns=['Sector','Parent Sector','Add or Split'])
        output_frame=pd.DataFrame([[c,r,q,policy['currency_unit']] for (c,r),q in outputs.items()],columns=OUTPUT_COLUMNS)
        trade_frame=pd.DataFrame([[c,o,d,q,policy['currency_unit']] for (c,o,d),q in trade.items() if q>0],columns=TRADE_COLUMNS)
        require_parent_budgets(budgets,ChildTargets(master,output_frame,trade_frame),report_path=reports/'checks_targets.json')
        builder=ProfileBuilder(native,geography,parents,native_outputs,policy,audit)
        written=[];inventory_sources={}
        for path in files:
            book=audit.workbook(path,role='resolved_profiles')
            try:
                header,*data=book['Master'].values
                sector=next(dict(zip(header,row))['Sector'] for row in data if row[1] is not None)
            finally:book.close()
            logger.info('Preparing reconciled inventories: %s',sector)
            profiles,settings=builder.build(path,sector,old_parents[sector])
            destination=output_dir/'inventories'/f'{sector}.xlsx'
            builder.write(destination,sector,profiles,settings,outputs,trade,database)
            written.append(destination)
            inventory_sources[sector]=str(path)
        checked=read_child_targets(written)
        after=require_parent_budgets(budgets,checked,report_path=reports/'checks_after.json')
        after['source_files']={str(Path(p).relative_to(output_dir)):v for p,v in after['source_files'].items()}
        (reports/'checks_after.json').write_text(json.dumps(after,indent=2))
        original_aggregated=targets.aggregate(geography)
        old_x={(r.Sector,r.Region):float(r.Quantity) for r in original_aggregated.output.itertuples()}
        output_rows=[{'sector':c,'parent':parents[c],'region':r,'original_written':old_x.get((c,r)),
                      'reconciled':q,'unit':policy['currency_unit']} for (c,r),q in outputs.items()]
        _csv(reports/'outputs.csv',output_rows,['sector','parent','region','original_written','reconciled','unit'])
        _csv(reports/'trades.csv',[{'sector':c,'parent':parents[c],'origin':o,'destination':d,
             'prior':priors[(c,o,d)],'reconciled':q,'source_kind':kinds[(c,o,d)],'unit':policy['currency_unit']}
             for (c,o,d),q in sorted(trade.items())],
             ['sector','parent','origin','destination','prior','reconciled','source_kind','unit'])
        _csv(reports/'sectors.csv',[{'sector':c,'name':policy['sectors'][c]['name'],
             'old_parent':old_parents[c],'parent':parents[c],'scope':policy['sectors'][c].get('scope'),
             'output_source':policy['sectors'][c]['output_source']['kind'],
             'output_assumption':policy['sectors'][c]['output_source']['assumption'],
             'total_output':sum(q for (s,r),q in outputs.items() if s==c),
             'total_trade_prior':sum(q for (s,o,d),q in priors.items() if s==c),
             'total_trade_reconciled':sum(q for (s,o,d),q in trade.items() if s==c)} for c in parents],
             ['sector','name','old_parent','parent','scope','output_source','output_assumption',
              'total_output','total_trade_prior','total_trade_reconciled'])
        (reports/'solvers.json').write_text(json.dumps(solver_records,indent=2))
        summary={'status':'complete','policy_id':policy['id'],'policy_sha256':policy_sha,
                 'geography':{'name':geography.name,'mapping':geography.mapping},
                 'registry_fingerprints':registry.fingerprints,'sectors':len(parents),
                 'code_fingerprints':code_fingerprints,
                 'integration_fingerprints':integration_fingerprints,
                 'runtime':{'python':platform.python_version(),**{p:version(p) for p in
                     ('database-disaggregation','mariopy','cvxlab','cvxpy','scipy','pandas','numpy')}},
                 'inventory_sources':inventory_sources,
                 'regions':len(geography.regions),'profile_count':len(parents)*len(geography.regions),
                 'checks_before':before['summary'],'checks_after':after['summary'],
                 'parent_changes':{c:{'before':old_parents[c],'after':parents[c]} for c in parents if old_parents[c]!=parents[c]},
                 'solver_status_counts':dict(Counter(r['status'] for r in solver_records)),
                 'interpretation':'Reconciled project priors, not newly observed or independently certified values',
                 'source_certified':False,
                 'MRIO_split_solved':False}
        audit.finish(summary)
        lines=[f"# Reconciliation run: {policy['id']}",'',
               f"Status: complete; {len(parents)} sectors; {len(geography.regions)} selected regions.",'',
               'These are reconciled project priors. Source workbooks and GTAP matrices were preserved.',
               'The run prepares inventories; no MRIO split model was solved.','',
               '## Evidence','',
               '- `audit/policy.json`: exact assumptions and per-sector source-column/scope decisions.',
               '- `audit/inputs.json`: source roles and SHA-256 snapshots.',
               '- `audit/changes.jsonl`: raw values, transformations, donor weights, solver adjustments and source coordinates.',
               '- `audit/outputs.csv`, `trades.csv`, `sectors.csv`: reviewable targets and totals.',
               '- `audit/checks_before.json`, `checks_targets.json`, `checks_after.json`: diagnostics before, after fitting and after Excel read-back.',
               '- `audit/solvers.json`, `audit/summary.json`: solver statuses and run summary.','',
               '## Global assumptions','',*[f'- {v}' for v in policy['assumptions']],'',
               '## Sector decisions','', '| Sector | Parent | Output source | Scope | Assumption |',
               '|---|---|---|---|---|']
        lines += [f"| {c} | {parents[c]} | {policy['sectors'][c]['output_source']['kind']} | {policy['sectors'][c].get('scope','inherited working scope')} | {policy['sectors'][c]['output_source']['assumption']} |" for c in parents]
        (output_dir/'README.md').write_text('\n'.join(lines)+'\n')
        (output_dir/'complete.json').write_text(json.dumps(summary,indent=2,allow_nan=False))
        return output_dir
    except Exception as exc:
        audit.finish({'status':'failed','error':str(exc),'policy_sha256':policy_sha})
        (output_dir/'failure.json').write_text(json.dumps({'status':'failed','error':str(exc)},indent=2))
        raise
    finally:
        audit.close()
