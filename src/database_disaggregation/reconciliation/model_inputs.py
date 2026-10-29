"""Prepare all 69 activities on the native-compatible model geography."""
from collections import defaultdict
from copy import deepcopy
from dataclasses import replace
import json
import logging
from pathlib import Path

import pandas as pd

from database_disaggregation.core.paths import PROJECT_ROOT, data_path, project_data_root
from database_disaggregation.core.geography import Geography
from database_disaggregation.core.baseline import copy_database
from database_disaggregation.core.registry import Registry
from database_disaggregation.core.disaggregation import PreprocessedData, read_output_references
from database_disaggregation.core.parent_budgets import ChildTargets, read_child_targets, require_parent_budgets, ParentBudgets
from database_disaggregation.reconciliation.audit import Audit
from database_disaggregation.reconciliation.baseline import NativeBaseline
from database_disaggregation.reconciliation.policy import load_policy
from database_disaggregation.reconciliation.sources import Sources
from database_disaggregation.reconciliation.targets import resolve_parents, prepare_outputs, prepare_trade, reconcile_trade
from database_disaggregation.reconciliation.profiles import ProfileBuilder, balance_profile
from database_disaggregation.reconciliation.additional_sectors import CountryComponentSources, read_cost_profiles, select_profile


def prepare_model_inputs(database, output_dir, *, geography, steps=None, source_dir=None, extra_config=None):
    """Legacy directory-returning entry point for the full collection workflow."""
    return _prepare_model_inputs(database, output_dir, geography=geography, steps=steps,
                                 source_dir=source_dir, extra_config=extra_config).workbook.parent


def _prepare_model_inputs(database, output_dir, *, geography=None, steps=None, source_dir=None,
                          extra_config=None, data_root=None, source_paths=None,
                          missing_output="parent_share", missing_cost_structure="same_sector_then_parent",
                          inconsistent_targets="reconcile"):
    """Prepare the project's extended collected data from a native MARIO IOT.

    Reuses the published full-model-region preparation rules, including rebuilt
    coal products, barley and BF-BOF natural-gas injection. The database remains
    in memory; no baseline is loaded or exported. Source files are immutable.
    A supplied step plan controls ordering without changing data reconciliation.
    """
    options = {'missing_output': missing_output, 'missing_cost_structure': missing_cost_structure,
               'inconsistent_targets': inconsistent_targets}
    choices = {'missing_output': ('parent_share', 'raise'),
               'missing_cost_structure': ('same_sector_then_parent', 'raise'),
               'inconsistent_targets': ('reconcile', 'raise')}
    for name, value in options.items():
        if value not in choices[name]:
            raise ValueError(f'{name} must be one of {choices[name]}, got {value!r}.')
    if getattr(database, 'table_type', None) != 'IOT':
        raise ValueError('Input preparation requires a MARIO IOT Database.')
    if geography is None:
        geography = Geography({r: r for r in database.get_index('Region')}, 'native')
    elif isinstance(geography, (str, Path)):
        geography = Geography.read(geography)
    elif isinstance(geography, dict):
        geography = Geography(geography)
    if not isinstance(geography, Geography):
        raise TypeError('geography must be a Geography, mapping, or mapping-file path.')
    geography.validate(database.get_index('Region'))
    if data_root is not None:
        data_root = Path(data_root).expanduser().resolve()
        if not data_root.is_dir():
            raise FileNotFoundError(f'Data root is unavailable: {data_root}')
    if source_paths is not None and not isinstance(source_paths, dict):
        raise TypeError('source_paths must map source roles to paths.')

    def source_path(key):
        if source_paths is not None and key in source_paths:
            value = source_paths[key]
            if value is None:
                return None
            path = Path(value).expanduser()
            return path if path.is_absolute() else (data_root or project_data_root(required=True))/path
        return data_path(key, required=True, data_root=data_root)

    root=Path(output_dir).expanduser().resolve()
    root.mkdir(parents=True,exist_ok=False)
    audit=Audit(root/'audit')
    try:
        extra=json.loads(Path(extra_config or PROJECT_ROOT/'config/additional-sectors-13.json').read_text())
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
        policy['preprocessing_options'] = options
        load_policy(policy)
        (root/'policy.json').write_text(json.dumps(policy,indent=2)+'\n')
        geo=geography
        logging.info('Reading native budgets and aggregating baseline to %s regions',len(geo.regions))
        native=NativeBaseline(database=database,audit=audit)
        geo.validate(native.regions)
        database=copy_database(database,geo)
        files={p.stem:p for p in Path(source_dir or source_path('resolved_inventories')).glob('*.xlsx')
               if p.stem not in extra['sectors'] and not p.name.startswith('~$')}
        expected=set(policy['sectors'])-set(extra['sectors'])
        if set(files)!=expected:
            raise ValueError(f'Native inventory coverage differs from the policy: missing={expected-set(files)}, extra={set(files)-expected}')
        reference_dir = source_path('mario_inventories')
        references=read_output_references(reference_dir,
            read_bytes=lambda p:audit.read(p,role='native_output_reference')) if reference_dir is not None else {}
        targets=read_child_targets(list(files.values()),output_references=references)
        for p,h in targets.sources.items():audit.files[p]={'sha256':h,'bytes':Path(p).stat().st_size,'role':'native_resolved_inventory'}
        master=pd.concat([targets.master,pd.DataFrame([{'Sector':s,'Parent Sector':r['declared_parent'],'Add or Split':'Split'}
            for s,r in extra['sectors'].items()])],ignore_index=True)
        targets=ChildTargets(master,targets.output,targets.trade,targets.sources)
        parents,old=resolve_parents(policy,targets,Registry.load(),native,audit)
        paths={name:source_path(name) for name in ['purdue_split_targets','purdue_trade','partner_templates']}
        sources=CountryComponentSources(Sources(paths,Registry.load(),native,policy,audit),extra['country_components'],audit)
        logging.info('Reconciling outputs jointly for all 69 activities')
        native_outputs,outputs,_=prepare_outputs(policy,sources,native,geo,targets,parents,old,audit,
            missing_output=missing_output, inconsistent_targets=inconsistent_targets)
        priors,kinds=prepare_trade(policy,sources,native,geo,parents,native_outputs,outputs,audit)
        trade,records=reconcile_trade(priors,kinds,parents,outputs,native.budgets.aggregate(geo),policy,audit,
            inconsistent_targets=inconsistent_targets)
        pd.DataFrame([dict(sector=s,parent=parents[s],origin=o,destination=d,prior=priors[(s,o,d)],
            reconciled=q,source_kind=kinds[(s,o,d)],unit='M USD') for (s,o,d),q in trade.items()]).to_csv(root/'audit/trades.csv',index=False)
        (root/'audit/trade-solvers.json').write_text(json.dumps(records,indent=2)+'\n')
        builder=ProfileBuilder(native,geo,parents,native_outputs,policy,audit,
                               missing_cost_structure=missing_cost_structure)
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
                    if own is None and missing_cost_structure == 'raise':
                        audit.record('missing_cost_structure_rejected',kind='profile',sector=sector,region=country)
                        raise ValueError(f'{sector}/{country}: missing cost structure (missing_cost_structure="raise").')
                    donors=[country] if own else [r for r in countries if selected[r] and native_outputs[(sector,r)]>0]
                    mode='own_or_group' if own else 'same_child_macroregion'
                    if not donors:
                        donors=[r for r in native.regions if selected[r] and native_outputs[(sector,r)]>0];mode='same_child_global'
                    if not donors:
                        donors=[r for r in native.regions if selected[r]];mode='same_child_unweighted'
                    if not donors:
                        audit.record('additional_profile_donor',kind='profile_lineage',sector=sector,region=country,
                            macroregion=group,profile=None,donors={},mode='baseline_parent')
                        canonical = native.profile((country,), parents[sector])[0]
                        for row in canonical:
                            accumulated[(row['Item type'],row['DB Item'],row['DB Region'])]+=weight*row['Quantity']
                        continue
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
        steps=steps or {f'Sector {sector}':[sector] for sector in policy['sectors']}
        order=[sector for group in steps.values() for sector in group]
        if len(order)!=len(set(order)) or set(order)!=set(parents):
            raise ValueError('The step plan must contain each prepared sector exactly once.')
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
        database.read_add_sectors_excel(root/'add_sectors.xlsx',read_inventories=True,split=True)
        summary=dict(status='prepared',regions=len(geo.regions),sectors=order,profiles=len(payload.master_sheet),
            steps=steps,geography=geo.mapping,policy=str(root/'policy.json'),MRIO_split_solved=False,
            preprocessing_options=options,data_root=str(data_root or project_data_root()),baseline_exported=False,
            excluded=['AMM','HYS','new_silicon_extraction'],scope='66 original activities plus rebuilt PCP and new BAR/SGI')
        (root/'preparation.json').write_text(json.dumps(summary,indent=2)+'\n')
        audit.finish(summary)
        logging.info('Preparation complete: %s regions, %s activities, %s profiles',len(geo.regions),len(order),len(payload.master_sheet))
        return PreprocessedData(database=database, workbook=root/'add_sectors.xlsx', audit=root/'audit')

    except Exception as exc:
        (root/'failure.json').write_text(json.dumps({'status':'failed','error':str(exc)},indent=2)+'\n')
        audit.finish({'status':'failed','error':str(exc)})
        raise
    finally:
        audit.close()
