"""Prepare all 69 activities on the native-compatible model geography."""
import argparse
from collections import defaultdict
from copy import deepcopy
from dataclasses import replace
import json
import logging
from pathlib import Path

import pandas as pd

from database_disaggregation.core.paths import PROJECT_ROOT, data_path, project_data_root
from database_disaggregation.core.geography import Geography
from database_disaggregation.core.baseline import load_baseline
from database_disaggregation.core.registry import Registry
from database_disaggregation.core.disaggregation import read_output_references
from database_disaggregation.core.parent_budgets import ChildTargets, read_child_targets, require_parent_budgets, ParentBudgets
from database_disaggregation.reconciliation.audit import Audit
from database_disaggregation.reconciliation.baseline import NativeBaseline
from database_disaggregation.reconciliation.policy import load_policy
from database_disaggregation.reconciliation.sources import Sources
from database_disaggregation.reconciliation.targets import resolve_parents, prepare_outputs, prepare_trade, reconcile_trade
from database_disaggregation.reconciliation.profiles import ProfileBuilder, balance_profile
from database_disaggregation.reconciliation.additional_sectors import CountryComponentSources, read_cost_profiles, select_profile


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();root=args.output.resolve();root.mkdir(parents=True,exist_ok=False)
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(message)s')
    audit=Audit(root/'audit')
    extra=json.loads((PROJECT_ROOT/'config/additional-sectors-13.json').read_text())
    policy,_=load_policy();policy=deepcopy(policy)
    policy['id']='entice-69-model-regions-v1'
    for sector,rule in extra['sectors'].items():
        policy['sectors'][sector]=deepcopy(rule)
        if sector in extra['country_components']:
            policy['sectors'][sector]['country_components']=extra['country_components'][sector]
    policy['require_all_sectors']=True
    policy['trade']['parent_pattern_only']=list(dict.fromkeys([*policy['trade']['parent_pattern_only'],*extra['sectors']]))
    policy['trade']['solver']='GUROBI'
    policy['trade']['solver_parameters']={'Threads':2,'TimeLimit':120.,'OutputFlag':0}
    load_policy(policy)
    (root/'policy.json').write_text(json.dumps(policy,indent=2)+'\n')
    geo=Geography.read(PROJECT_ROOT/'data/geographies/gtap-models-compatible.json')
    baseline=data_path('baseline',required=True)
    logging.info('Reading native budgets and aggregating baseline to %s regions',len(geo.regions))
    native=NativeBaseline(baseline,audit=audit)
    geo.validate(native.regions)
    database=load_baseline(baseline,'mario_parquet',geography=geo)
    files={p.stem:p for p in data_path('resolved_inventories',required=True).glob('*.xlsx') if p.stem not in extra['sectors']}
    assert len(files)==66 and len(policy['sectors'])==69
    references=read_output_references(data_path('mario_inventories',required=True),
        read_bytes=lambda p:audit.read(p,role='native_output_reference'))
    targets=read_child_targets(list(files.values()),output_references=references)
    for p,h in targets.sources.items():audit.files[p]={'sha256':h,'bytes':Path(p).stat().st_size,'role':'native_resolved_inventory'}
    master=pd.concat([targets.master,pd.DataFrame([{'Sector':s,'Parent Sector':r['declared_parent'],'Add or Split':'Split'}
        for s,r in extra['sectors'].items()])],ignore_index=True)
    targets=ChildTargets(master,targets.output,targets.trade,targets.sources)
    parents,old=resolve_parents(policy,targets,Registry.load(),native,audit)
    paths={name:data_path(name,required=True) for name in ['purdue_split_targets','purdue_trade','partner_templates']}
    sources=CountryComponentSources(Sources(paths,Registry.load(),native,policy,audit),extra['country_components'],audit)
    logging.info('Reconciling outputs jointly for all 69 activities')
    native_outputs,outputs,_=prepare_outputs(policy,sources,native,geo,targets,parents,old,audit)
    priors,kinds=prepare_trade(policy,sources,native,geo,parents,native_outputs,outputs,audit)
    trade,records=reconcile_trade(priors,kinds,parents,outputs,native.budgets.aggregate(geo),policy,audit)
    pd.DataFrame([dict(sector=s,parent=parents[s],origin=o,destination=d,prior=priors[(s,o,d)],
        reconciled=q,source_kind=kinds[(s,o,d)],unit='M USD') for (s,o,d),q in trade.items()]).to_csv(root/'audit/trades.csv',index=False)
    (root/'audit/trade-solvers.json').write_text(json.dumps(records,indent=2)+'\n')
    builder=ProfileBuilder(native,geo,parents,native_outputs,policy,audit)
    for sector,path in files.items():
        logging.info('Preparing existing profile %s',sector)
        profiles,settings=builder.build(path,sector,old[sector])
        builder.write(root/'inventories'/f'{sector}.xlsx',sector,profiles,settings,outputs,trade,database)
    identity=Geography({r:r for r in native.regions},'native')
    for sector,rule in extra['sectors'].items():
        logging.info('Preparing collected profile %s',sector)
        local={**rule,'matching':PROJECT_ROOT/'data/GTAP12_matching.xlsx',
            'new_sector_names':{s:r['name'] for s,r in policy['sectors'].items()}}
        profiles,membership,groups,factors=read_cost_profiles(paths['partner_templates']/rule['output_source']['file'],
            sector,native,identity,set(native.sectors)|set(parents),parents,local,audit)
        selected={r:select_profile(r,profiles,membership) for r in native.regions}
        aggregated={}
        for group in geo.regions:
            countries=[r for r,g in geo.mapping.items() if g==group]
            total=sum(native_outputs[(sector,r)] for r in countries)
            accumulated=defaultdict(float)
            for country in countries:
                weight=native_outputs[(sector,country)]/total if total else 1./len(countries)
                if not weight:continue
                own=selected[country]
                donors=[country] if own else [r for r in countries if selected[r] and native_outputs[(sector,r)]>0]
                mode='own_or_group' if own else 'same_child_macroregion'
                if not donors:
                    donors=[r for r in native.regions if selected[r] and native_outputs[(sector,r)]>0];mode='same_child_global'
                if not donors:
                    donors=[r for r in native.regions if selected[r]];mode='same_child_unweighted'
                if not donors:raise ValueError(f'No explicit profile available for {sector}')
                denominator=sum(native_outputs[(sector,r)] for r in donors)
                donor_weights={r:native_outputs[(sector,r)]/denominator if denominator else 1./len(donors) for r in donors}
                audit.record('additional_profile_donor',kind='profile_lineage',sector=sector,region=country,
                    macroregion=group,profile=own,donors=donor_weights,mode=mode)
                for donor,fraction in donor_weights.items():
                    canonical=builder.canonical(profiles[selected[donor]],donor,parents[sector],groups,factors,{})
                    for row in canonical:
                        accumulated[(row['Item type'],row['DB Item'],row['DB Region'])]+=weight*fraction*row['Quantity']
            rows=[dict(Quantity=q,Unit='M USD',Input=k[1],**{'Item type':k[0],'DB Item':k[1],
                'DB Region':k[2],'Change type':'Update'}) for k,q in accumulated.items()]
            aggregated[group]=balance_profile(rows,policy,audit,sector=sector,region=group)
        builder.write(root/'inventories'/f'{sector}.xlsx',sector,aggregated,{},outputs,trade,database)
    logging.info('Reading native MARIO inventory payload and building one-sector steps')
    database.read_add_sectors_excel(root/'inventories',read_inventories=True,split=True)
    payload=database.add_sectors_workbook
    previous_state=json.loads((project_data_root()/'Database/D2.8/20261021 0655 - 13 regions and 67 sectors/state.json').read_text())
    order=[*previous_state['completed_sectors'],'BAR','SGI']
    assert set(order)==set(parents) and len(order)==69
    steps={f'Sector {s}':[s] for s in order}
    support=dict(payload.split_info)
    # Explicit complete foreign routes preserve subsequent sibling budgets.
    support['Trades']=pd.DataFrame([[s,o,d,float(trade.get((s,o,d),0.)),'M USD',policy['id'],'Prepared prior; not certified observed zero']
        for s in order for o in geo.regions for d in geo.regions if o!=d],
        columns=['Sector_from','Region_from','Region_to','Quantity','Unit','Source','Notes'])
    payload=replace(payload,split_info=support,intermediate_steps=steps)
    require_parent_budgets(ParentBudgets.from_database(database),ChildTargets.from_workbook(payload),report_path=root/'parent_budgets.json')
    from mario.ops.add_sector_steps import write_workbook_payload,validate_plan
    validate_plan(payload,database.get_index('Sector'))
    write_workbook_payload(payload,root/'add_sectors.xlsx',instance=database)
    database.to_parquet(path=root/'baseline',flows=True,coefficients=False,include_meta=True)
    summary=dict(status='prepared',regions=len(geo.regions),sectors=order,profiles=len(payload.master_sheet),
        steps=steps,geography=geo.mapping,policy=str(root/'policy.json'),MRIO_split_solved=False,
        excluded=['AMM','HYS','new_silicon_extraction'],scope='66 original activities plus rebuilt PCP and new BAR/SGI')
    (root/'preparation.json').write_text(json.dumps(summary,indent=2)+'\n')
    audit.finish(summary);audit.close()
    logging.info('Preparation complete: %s regions, %s activities, %s profiles',len(geo.regions),len(order),len(payload.master_sheet))


if __name__=='__main__':main()
