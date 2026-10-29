"""Prepare additional activities on an existing database, without changing it.

Source cost coefficients are priors. Geographic/profile transfer and monetary
projection use the existing reconciliation rules and retain their audit trail.
"""
from collections import defaultdict
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import hashlib
import json

import numpy as np
import pandas as pd

from database_disaggregation.core.geography import Geography
from database_disaggregation.core.matching_utils import load_legacy_gtap12_maps
from database_disaggregation.core.parent_budgets import ParentBudgets, _sector_index
from database_disaggregation.core.registry import Registry, normalise
from database_disaggregation.reconciliation.audit import Audit
from database_disaggregation.reconciliation.baseline import NativeBaseline
from database_disaggregation.reconciliation.policy import load_policy
from database_disaggregation.reconciliation.profiles import ProfileBuilder, balance_profile
from database_disaggregation.reconciliation.sources import Sources
from database_disaggregation.reconciliation.targets import prepare_outputs


def pair_clusters(sheet, start, stop=None, carry=True):
    result = defaultdict(list)
    current = None
    for row in sheet.iter_rows(min_row=start, max_row=stop, max_col=2, values_only=True):
        name, member = row
        if isinstance(name, str) and name.strip():
            current = name.strip()
        elif not carry:
            current = None
        if current and isinstance(member, str) and member.strip():
            result[current].append(member.strip())
    return dict(result)


def select_profile(region, profiles, members):
    """Prefer a country observation, then the smallest supported group."""
    candidates = [name for name in profiles if region in members[name]]
    if not candidates:
        return None
    candidates.sort(key=lambda n: (len(members[n]), n))
    best = candidates[0]
    tied = [name for name in candidates if len(members[name]) == len(members[best])]
    if any(profiles[name] != profiles[best] for name in tied):
        raise ValueError(f'Ambiguous equal-specificity technology profiles for {region}: {tied}')
    return best


class CountryComponentSources:
    """Retain country observations inside explicitly mapped GTAP residuals.

    Complete residual coverage is direct. Incomplete sums are low-confidence
    soft observations, never asserted to be a complete residual-region total.
    """
    def __init__(self, source, components, audit):
        self.source, self.components, self.audit = source, components, audit
        for mapping in components.values():
            for label, rule in mapping.items():
                if rule['target'] not in source.native.regions:
                    raise ValueError(f"Unknown native component target: {rule['target']}")
                source.region_lookup[normalise(label)] = rule['target']

    def __getattr__(self, name):
        return getattr(object.__getattribute__(self, 'source'), name)

    def observations(self, sector, parent):
        rows = self.source.observations(sector, parent)
        rules = self.components.get(sector, {})
        plain = [r for r in rows if r['identifier'] not in rules]
        authoritative = {r['members'][0] for r in plain if r['kind'] == 'direct'}
        grouped = defaultdict(list)
        for row in rows:
            if row['identifier'] in rules:
                grouped[rules[row['identifier']]['target']].append(row)
        for target, components in grouped.items():
            if target in authoritative:
                self.audit.record('component_covered_by_native_total',kind='geography',sector=sector,target=target)
                continue
            names = {rules[r['identifier']]['country'] for r in components}
            expected = set(rules[components[0]['identifier']]['all_members'])
            complete = names == expected
            result = dict(members=[target],value=sum(r['value'] for r in components),identifier=target,
                source=[r['source'] for r in components],state='complete_country_components' if complete else 'partial_country_components',
                kind='direct' if complete else 'cluster',confidence=1. if complete else .1)
            self.audit.record('country_components',kind='geography',sector=sector,target=target,
                countries=sorted(names),missing_countries=sorted(expected-names),complete=complete,
                original_identifiers=[r['identifier'] for r in components],value=result['value'],
                sources=result['source'],assumption='Complete source membership summed once; incomplete country sums are low-confidence soft observations.')
            plain.append(result)
        return plain


def read_cost_profiles(path, code, native, geography, existing, historical_parents, rules, audit):
    registry = Registry.load()
    sector_map, factor_map = load_legacy_gtap12_maps(rules['matching'])
    sector_map = {normalise(k): v for k, v in sector_map.items()}
    factor_map = {normalise(k): v for k, v in factor_map.items()}
    active_names = defaultdict(set)
    for record in registry.sectors.values():
        if record['id'] in existing:
            active_names[normalise(record['name'])].add(record['id'])
    active_names[normalise(rules['name'])].add(code)
    for new_code, new_name in rules.get('new_sector_names', {}).items():
        active_names[normalise(new_name)].add(new_code)
    book = audit.workbook(path, role='additional_activity_template', read_only=False)
    try:
        sector_clusters = pair_clusters(book['Sector'], 3, 185, carry=False)
        sector_clusters.update(pair_clusters(book['Sector'], 369))
        factor_clusters = pair_clusters(book['Primary input'], 17)
        table = list(book['Unit process'].values)
        native_lookup = {normalise(v): r['id'] for r in registry.regions() for v in [r['id'], r['name']]}
        region_helper = Sources({'partner_templates': path.parent, 'purdue_trade': None}, registry, native,
                                {'sectors': {}}, audit)
        clusters = region_helper._clusters(book)

        def resolve(item, kind, trail=()):
            item = str(item).strip()
            if item in trail:
                raise ValueError(f'Cyclic cost category: {item}')
            if kind == 'Sector':
                matched = active_names.get(normalise(item), set())
                if len(matched) == 1:
                    return list(matched)
                if len(matched) > 1:
                    raise ValueError(f'Ambiguous existing activity label {item}: {matched}')
                mapping, groups = sector_map, sector_clusters
            else:
                matched = {x for x in ['Capital', 'Labor', 'Tax', 'TTM'] if normalise(x) == normalise(item)}
                if matched:
                    return list(matched)
                mapping, groups = factor_map, factor_clusters
            if item in groups:
                return list(dict.fromkeys(x for member in groups[item]
                    for x in resolve(member, kind, (*trail, item))))
            result = mapping.get(normalise(item), item)
            if kind == 'Sector' and result in existing:
                # A GTAP-76 category denotes its whole family, not just the
                # residual parent left after the preceding 67-sector split.
                return [result, *sorted(s for s,p in historical_parents.items()
                                       if p == result and s in existing and s != result)]
            if kind == 'Factor of production' and result in ['Capital','Labor','Tax','TTM']:
                return [result]
            raise ValueError(f'Unmapped {kind} cost category {item!r}')

        profiles, membership, input_clusters, factor_groups = {}, {}, {}, {}
        for col in range(6, len(table[0]), 2):
            name = table[0][col]
            if not name or str(table[1][col]).strip().casefold() != 'monetary':
                continue
            if table[2][col] != 1 or str(table[2][col+1]).strip().upper() != 'USD':
                raise ValueError(f'{code}: expected coefficients per one USD for {name}.')
            profile = []
            for number, row in enumerate(table[5:], 6):
                if len(row) <= col or row[col] is None or row[0] in (None, 'Emissions', 'Energy'):
                    continue
                if row[0] not in ('Sector', 'Primary_input') or not row[2]:
                    raise ValueError(f'{code}: unmapped monetary row {number}.')
                value = float(row[col])
                if not np.isfinite(value):
                    raise ValueError(f'{code}: nonfinite monetary coefficient.')
                kind = 'Sector' if row[0] == 'Sector' else 'Factor of production'
                targets = resolve(row[2], kind)
                if len(targets) == 1:
                    item = targets[0]
                else:
                    item = 'Input_'+hashlib.sha256((kind+'|'+','.join(targets)).encode()).hexdigest()[:12]
                    (input_clusters if kind == 'Sector' else factor_groups)[item] = targets
                origin = row[3] or 'GLOBAL'
                if kind == 'Sector' and origin != 'GLOBAL':
                    source_region = native_lookup.get(normalise(origin))
                    if source_region is None:
                        raise ValueError(f'{code}: unsupported partial input-origin group {origin!r}.')
                    origin = geography.mapping[source_region]
                profile.append(dict(Quantity=value, Unit='M USD', Input=str(row[2]),
                    **{'Item type': kind, 'DB Item': item, 'DB Region': origin if kind == 'Sector' else None,
                       'Change type': 'Update'}))
                audit.record('additional_cost_observation', kind='profile_source', sector=code,
                    profile=str(name), source=str(path), row=number, column=col+1,
                    quantity=value, input_label=row[2], resolved_items=targets,
                    assumption='Monetary coefficients per one USD are dimensionless; explicit active activities retained, coarse GTAP categories cover their existing family.')
            if not profile:
                continue
            if name in profiles:
                raise ValueError(f'Duplicate monetary profile {name}')
            region = native_lookup.get(normalise(name))
            members = [region] if region else list(clusters.get(name, []))
            if not members:
                raise ValueError(f'{code}: unknown producing geography {name!r}')
            profiles[name], membership[name] = profile, members
        if not profiles:
            raise ValueError(f'{code}: no cost profile; an explicit proxy decision is required.')
        return profiles, membership, input_clusters, factor_groups
    finally:
        book.close()


def prepare_additional(root, data_root, baseline_run, sector_rules, *, matching, geography_file, rebuild_sectors=()):
    from mario.ops.add_sector_steps import load_checkpoint, _digest
    from mario.ops.add_sector_workbook import load_add_sector_workbook_input, merge_add_sector_workbooks
    from mario.ops.add_sector_steps import write_workbook_payload
    from dataclasses import replace
    root, data_root, baseline_run = map(Path, (root, data_root, baseline_run))
    root.mkdir(parents=True, exist_ok=False)
    audit = Audit(root/'audit')
    source_state = json.loads((baseline_run/'state.json').read_text())
    from database_disaggregation.core.residual_labels import load_checkpoint_with_codes
    database = load_checkpoint_with_codes(baseline_run)
    database.__dict__.pop('_intermediate_steps_state', None)
    collapsed = {s:source_state['sector_parents'][s] for s in rebuild_sectors}
    if collapsed:
        import mario
        from mario.ops.add_sector_steps import _collapse
        matrices = {name:_collapse(database.resolve(name),collapsed) for name in ['Z','Y','V','E','EY','VY']}
        target_x = _collapse(database.resolve('X'),collapsed)
        units = {k:v.copy() for k,v in database.units.items()}
        units['Sector'] = units['Sector'].drop(index=list(collapsed))
        database = mario.Database(name='ENTICE 13: additional collected activities',table='IOT',units=units,**matrices)
        database.reset_to_flows('baseline')
        database.matrices['baseline']['X'] = target_x.reindex(index=database.Z.index)
    geography = Geography.read(geography_file)
    x = pd.read_parquet(data_root/'Database/_GTAP Power 2023/Cache/X.parquet').iloc[:,0]
    x.index = _sector_index(x.index)
    native = SimpleNamespace(regions=list(x.index.get_level_values('Region').unique()),
                             budgets=SimpleNamespace(output=x))
    geography.validate(native.regions)
    assert set(geography.regions) == set(database.get_index('Region'))
    current = NativeBaseline(baseline_run/'flows', database=database)
    policy, _ = load_policy()
    policy = deepcopy(policy)
    policy.update(id='entice-additional-13-v1', require_all_sectors=False, overlap_groups=[])
    policy['sectors'] = {s: {k:v for k,v in rule.items() if k not in ['matching']}
                         for s,rule in sector_rules.items()}
    for s,rule in policy['sectors'].items():
        rule['output_source']['kind'] = 'template'
    sources = Sources({'partner_templates': data_root/'Data collection/Final', 'purdue_trade': None},
                      Registry.load(), native, policy, audit)
    sources = CountryComponentSources(sources, {s:r.get('country_components',{}) for s,r in sector_rules.items()}, audit)
    parents = {s: v['declared_parent'] for s,v in policy['sectors'].items()}
    targets = SimpleNamespace(output=pd.DataFrame(columns=['Sector','Region','Quantity']))
    native_output, outputs, _ = prepare_outputs(policy, sources, native, geography, targets,
        parents, parents, audit, selected_parent_budgets=current.budgets)
    identity = Geography({r:r for r in geography.regions}, 'existing_13')
    builder = ProfileBuilder(current, identity, parents, {}, policy, audit)
    inventory_dir = root/'inventories';inventory_dir.mkdir()
    all_trade = {}
    for sector, rule in sector_rules.items():
        local_rule = {**rule, 'matching': matching,
                      'new_sector_names': {s:r['name'] for s,r in sector_rules.items()}}
        profiles, membership, groups, factors = read_cost_profiles(
            data_root/'Data collection/Final'/rule['output_source']['file'], sector, native, geography,
            set(database.get_index('Sector')), source_state['sector_parents'], local_rule, audit)
        selected = {r:select_profile(r, profiles, membership) for r in native.regions}
        aggregated = {}
        for group in geography.regions:
            countries = [r for r,g in geography.mapping.items() if g == group]
            total = sum(native_output[(sector,r)] for r in countries)
            rows = defaultdict(float)
            for country in countries:
                weight = native_output[(sector,country)]/total if total else 1./len(countries)
                if not weight:
                    continue
                own = selected[country]
                donors = [country] if own else [r for r in countries if selected[r] and native_output[(sector,r)]>0]
                mode = 'own_or_group' if own else 'same_child_macroregion'
                if not donors:
                    donors = [r for r in native.regions if selected[r] and native_output[(sector,r)]>0]
                    mode = 'same_child_global'
                if not donors:
                    donors = [r for r in native.regions if selected[r]]
                    mode = 'same_child_unweighted'
                denominator = sum(native_output[(sector,r)] for r in donors)
                donor_weights = {r:native_output[(sector,r)]/denominator if denominator else 1./len(donors) for r in donors}
                audit.record('additional_profile_donor',kind='profile_lineage',sector=sector,
                    region=country,macroregion=group,profile=own,donors=donor_weights,mode=mode)
                for donor, donor_weight in donor_weights.items():
                    canonical = builder.canonical(profiles[selected[donor]], group, parents[sector], groups, factors, {})
                    for row in canonical:
                        key=(row['Item type'],row['DB Item'],row['DB Region'])
                        rows[key] += weight*donor_weight*row['Quantity']
            profile=[dict(Quantity=q,Unit='M USD',Input=k[1],**{'Item type':k[0],
                      'DB Item':k[1],'DB Region':k[2],'Change type':'Update'}) for k,q in rows.items()]
            aggregated[group] = balance_profile(profile, policy, audit, sector=sector, region=group)
            parent_x = float(current.budgets.output.loc[(group,parents[sector])])
            share = outputs[(sector,group)]/parent_x if parent_x>0 else 0.
            foreign = {d:max(0.,float(current.budgets.trade.loc[(group,parents[sector]),d]))*share
                       for d in geography.regions if d != group}
            gross = sum(foreign.values())
            scale = min(1.,outputs[(sector,group)]/gross) if gross else 1.
            for destination,value in foreign.items():
                all_trade[(sector,group,destination)] = value*scale
                audit.record('additional_parent_pattern_trade',kind='trade_prior',sector=sector,
                    origin=group,destination=destination,value=value*scale,
                    assumption='Estimated current parent trade pattern at the child output share; capped by child output, not an observed trade target.')
        builder.write(inventory_dir/f'{sector}.xlsx',sector,aggregated,{},outputs,all_trade,database)
    payloads = [load_add_sector_workbook_input(inventory_dir/f'{s}.xlsx',table='IOT',read_inventories=True,split=True)[0]
                for s in sector_rules]
    payload = merge_add_sector_workbooks(payloads)
    # Keep every estimated foreign route explicit, including zeros, so later
    # additions cannot consume budgets on omitted routes.
    support = dict(payload.split_info)
    support['Trades'] = pd.DataFrame([[s,o,d,q,'M USD',policy['id'],'Estimated parent-pattern prior']
        for (s,o,d),q in all_trade.items()], columns=['Sector_from','Region_from','Region_to','Quantity','Unit','Source','Notes'])
    payload = replace(payload, split_info=support, intermediate_steps={f'Additional {s}':[s] for s in sector_rules})
    write_workbook_payload(payload,root/'add_sectors.xlsx',instance=database)
    baseline=root/'baseline';database.to_parquet(path=baseline/'database',flows=True,coefficients=False,include_meta=True)
    # Independent X survives the generic flow export and the normal checkpoint loader.
    exported_x = pd.read_parquet(baseline/'database/flows/X.parquet')
    assert exported_x.index.equals(database.Z.index)
    assert np.isfinite(exported_x.to_numpy()).all() and (exported_x.to_numpy()>=0).all()
    provenance=dict(source_database=str(baseline_run),source_state_sha256=hashlib.sha256((baseline_run/'state.json').read_bytes()).hexdigest(),
        existing_completed_sectors=[s for s in source_state.get('all_completed_sectors', source_state['completed_sectors']) if s not in collapsed],
        rebuilt_sectors=collapsed,original_model_options=source_state['split_model_options'],
        source_inventory=str((baseline_run/json.loads((baseline_run/'run.json').read_text())['inventory_directory']).resolve()/'add_sectors.xlsx'),
        operation='existing_database_as_fresh_baseline_no_optimization')
    from mario.ops.split_model import normalize_options
    options=normalize_options(dict(model='Split_sectors_MRIO_quadratic',accounting='inherit',final_demand_weight=.1,
        supply_weight=1.,check_feasibility=True,feasibility_solver='GUROBI',compact_constraints=True,
        defer_satellite_recalculation=True,scale=1000.,require_finite_objective=True))
    state=dict(format='mario-sector-steps-v1',status='complete',step_index=0,step_name='Imported completed database',
        step_sectors=[],completed_sectors=[],split_model_options=options,baseline_provenance=provenance,
        files={str(p.relative_to(baseline)):_digest(p) for p in (baseline/'database').rglob('*') if p.is_file()})
    (baseline/'state.json').write_text(json.dumps(state,indent=2,allow_nan=False))
    (root/'model-options.json').write_text(json.dumps(options,indent=2))
    (root/'baseline-provenance.json').write_text(json.dumps(provenance,indent=2))
    audit.finish(dict(status='prepared',sectors=list(sector_rules),regions=13,baseline_provenance=provenance))
    audit.close()
    return root
