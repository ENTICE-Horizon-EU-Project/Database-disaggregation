"""A common economic-data layer built from the repository's selected inputs."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import pandas as pd

from database_disaggregation.core.parent_budgets import _sector_index
from database_disaggregation.core.paths import data_path, find_data_file
from database_disaggregation.core.registry import Registry
from database_disaggregation.export.build_d24_inventories import read_sector_templates
from database_disaggregation.reconciliation.audit import Audit
from database_disaggregation.reconciliation.policy import load_policy
from database_disaggregation.reconciliation.profiles import rows, clusters, expand
from database_disaggregation.reconciliation.sources import Sources, observation_geographies, selected_trade_observations


def _key(prefix, values):
    return prefix + hashlib.sha256(json.dumps(sorted(values)).encode()).hexdigest()[:16]


def _collector(value):
    value = str(value or '').strip()
    if value in {'EXIOIOT pipeline', 'COPCOSTS pipeline', 'PURDUE'}:
        return 'Purdue'
    return value.replace('ENEXTGEN', 'eNextGen') or 'Not recorded'


def select_trade(sector, policy, sources):
    """Follow the source precedence in prepare_trade, without allocating groups.

    Composite observations stay group observations. Inventing a child split or
    copying a parent trade pattern would turn this collected-data view into an
    additional estimation model.
    """
    rows, product, kind = selected_trade_observations(sector, policy, sources, include_composites=True)
    return rows, product, 'product_group' if kind=='composite' else 'unavailable' if kind=='unavailable' else 'sector'


@dataclass
class SourceCollection:
    metadata: dict
    sectors: dict
    evidence: dict

    @classmethod
    def from_pipeline(cls, *, inventory_dir=None, baseline_path=None,
                      source_paths=None, policy=True, registry=None, progress=None):
        """Read the complete active policy through existing repository readers.

        This uses the standardised pre-database inventory boundary, explicit
        output-column/unit/geography decisions and the trade-selection policy.
        It does not load a solved database, balance inputs, impute missing
        observations, or regenerate a source workbook.
        """
        policy, policy_hash = load_policy(policy)
        registry = registry or Registry.load()
        inventory_dir = Path(inventory_dir) if inventory_dir else data_path('mario_inventories', required=True)
        baseline_path = Path(baseline_path) if baseline_path else data_path('baseline', required=True)
        paths = {name: Path(source_paths[name]) if source_paths and name in source_paths else data_path(name, required=True)
                 for name in ('partner_templates', 'purdue_split_targets', 'purdue_trade')}
        regions = {r['id']: r['name'] for r in registry.regions()}
        baseline_x = pd.read_parquet(baseline_path/'X.parquet').iloc[:, 0]
        baseline_x.index = _sector_index(baseline_x.index)
        native = SimpleNamespace(regions=list(regions), budgets=SimpleNamespace(output=baseline_x))
        templates, skipped = read_sector_templates(inventory_dir, sector_codes=policy['sectors'])
        if skipped:
            raise ValueError(f'Incomplete source inventories: {skipped}')
        by_code = defaultdict(list)
        for template in templates:
            by_code[template.sector_code].append(template)
        if set(by_code) != set(policy['sectors']):
            raise ValueError(f'Active input coverage differs from the policy: missing={set(policy["sectors"])-set(by_code)}')
        parents = {r['id']: r.get('name', r['id']) for r in registry.adapters['GTAP12']['parent_catalogue']}
        sector_names = {**parents, **{s: rule['name'] for s, rule in policy['sectors'].items()}}
        items, geographies, payloads, sector_records = {}, {}, {}, []

        def geography(label, members, *, estimated=False):
            members = sorted(set(members))
            if set(members)-regions.keys():
                raise ValueError(f'Unknown geography members: {label}: {set(members)-regions.keys()}')
            if label in regions and members == [label]:
                key, name = label, regions[label]
            else:
                key = _key('g:', [label, *members])
                name = label.removeprefix('X_').replace('_', ' ').title()
                if estimated:
                    name = 'Estimated · ' + name
                elif label in {'GLOBAL', 'GLOBAL_ROW', 'GLOBAL_ROW2'}:
                    name = 'Remaining regions' if len(members) < len(regions) else 'All regions'
            geographies.setdefault(key, {'id': key, 'name': name, 'members': members,
                'is_group': key not in regions, 'estimated': estimated})
            return key

        def item(kind, code, definitions, universe):
            members = sorted(expand(code, definitions, universe))
            is_group = code not in universe
            key = _key('i:'+kind+':', members)
            if is_group:
                name = 'Other inputs' if str(code).startswith('ALL_OTHER') else str(code).replace('_', ' ').title()
                name += ' · ' + str(len(members)) + (' factors' if kind == 'Factor of production' else ' sectors')
            else:
                name = sector_names.get(code, {'Labor':'Labour','TTM':'Trade and transport margins','Tax':'Taxes'}.get(code,code))
            items.setdefault(key, {'id': key, 'name': name, 'kind': kind,
                'is_group': is_group, 'members': [{'code': m, 'name': sector_names.get(m,m)} for m in members]})
            return key

        with TemporaryDirectory(prefix='entice-collection-') as tmp:
            audit = Audit(Path(tmp))
            try:
                audit.read(baseline_path/'X.parquet', role='baseline_output_reference')
                matching = find_data_file('GTAP12_matching.xlsx')
                if matching.is_file():
                    audit.read(matching, role='pipeline_classification')
                sources = Sources(paths, registry, native, policy, audit)
                for sector, rule in policy['sectors'].items():
                    if progress:
                        progress(sector)
                    template = by_code[sector][0]
                    lead = _collector(template.data_collection_lead)
                    observations = sources.observations(sector, rule['declared_parent'])
                    if any(o['kind']=='cluster' for o in observations):
                        observations = observation_geographies(observations, policy, sector, native.regions)
                    production = []
                    for observation in observations:
                        geo = geography(observation['members'][0] if observation['kind']=='direct' else observation['identifier'], observation['members'])
                        production.append({'geo':geo, 'value':observation['value'],
                            'status':'Estimated from a reported share' if rule['output_source']['kind']=='template_share' else 'Reported',
                            'source':observation['source'], 'state':observation['state']})
                    profiles = []
                    signatures = []
                    for source_template in by_code[sector]:
                        book = audit.workbook(source_template.source_path, role='standardised_collection')
                        try:
                            master = rows(book, 'Master')
                            region_groups = clusters(book, 'Regions Clusters')
                            item_groups = clusters(book, 'Sectors Clusters')
                            factor_groups = clusters(book, 'Factors Clusters')
                            units = rows(book, 'DB units')
                            factor_universe = {r['Item'] for r in units if r.get('Level')=='Factor of production'} if units and 'Level' in units[0] else set()
                            factor_universe |= {'Capital','Labor','Land','NatRes','Tax','TTM'}
                            candidate = []
                            for record in master:
                                if record['Sector'] != sector:
                                    raise ValueError('Inventory contains a different activity identity.')
                                label = record['Region']
                                members = [label] if label in regions else region_groups.get(label)
                                if not members:
                                    raise ValueError(f'Unresolved producing geography: {sector}/{label}')
                                geo = geography(label, members, estimated=str(label).startswith('X_'))
                                amount = record.get('Quantity')
                                amount = 1.0 if amount is None else float(amount)
                                if amount <= 0:
                                    raise ValueError('Nonpositive inventory functional amount.')
                                values, origins = defaultdict(float), defaultdict(set)
                                for row in rows(book, record['Inventory sheet']):
                                    kind = row['Item type']
                                    if kind not in ('Sector','Factor of production'):
                                        continue
                                    quantity = float(row['Quantity'])/amount
                                    if not math.isfinite(quantity):
                                        raise ValueError('Non-finite cost coefficient.')
                                    key = item(kind,row['DB Item'],item_groups if kind=='Sector' else factor_groups,
                                               set(sector_names) if kind=='Sector' else factor_universe)
                                    values[key] += quantity
                                    origins[key].add(str(row.get('DB Region') or 'All origins'))
                                candidate.append({'geo':geo,'values':dict(values),
                                    'origins':{k:sorted(v) for k,v in origins.items()},
                                    'status':'Estimated profile' if str(label).startswith('X_') else 'Region-group recipe' if label not in regions else 'Country recipe'})
                            candidate.sort(key=lambda p:p['geo'])
                            signatures.append(json.dumps(candidate,sort_keys=True))
                            if not profiles:
                                profiles = candidate
                        finally:
                            book.close()
                    if len(set(signatures)) != 1:
                        raise ValueError(f'Conflicting duplicate inventories for {sector}')
                    trade, trade_product, trade_scope = select_trade(sector, policy, sources)
                    edges = [[o,d,float(q)] for (o,d),q in trade.items() if o!=d and q!=0]
                    output_lead = 'Purdue' if rule['output_source']['kind']=='purdue' else lead
                    production_note = 'Selected monetary observations, expressed in million USD using the adopted collection rules.'
                    if not production:
                        production_note = 'No direct monetary production observation is selected for this activity. The pipeline uses an estimate; no estimate is presented as collected data here.'
                    references = []
                    for label, url in template.summary_sources:
                        label = str(label or '').strip()
                        if not label or 'integrate with your' in label.lower():
                            continue
                        if label.upper() in {'COPCOSTS','EXIOIOT','SPLTTARGS / REPOUT'}:
                            label = 'Purdue sector estimates'
                        if label not in references:
                            references.append(label)
                    payloads[sector] = {'production':production,'profiles':profiles,
                        'trade':{'edges':edges,'product':trade_product,'scope':trade_scope,
                            'members':policy['trade'].get('composites',{}).get(trade_product,[sector]) if trade_product else []}}
                    sector_records.append({'id':sector,'name':rule['name'],'parent':rule['declared_parent'],
                        'production':{'collector':output_lead,'reference':'Purdue sector production estimates' if output_lead=='Purdue' else ' · '.join(references) or 'Sector collection references','note':production_note},
                        'costs':{'collector':lead,'reference':' · '.join(references) or 'Sector collection references',
                            'note':'Monetary input coefficients before database construction. Group definitions and existing estimated profiles are retained; inputs are summed across origins.'},
                        'trades':{'collector':'Purdue' if trade_scope!='unavailable' else 'Not available',
                            'reference':'Bilateral trade observations','note':'International flows, in million USD. A product-group total is kept as a group total and is not attributed to an individual member.' if trade_scope=='product_group' else 'International trade observations, in million USD. Unreported routes within a selected sparse source parameter are zero; domestic flows are outside this view.' if trade_scope!='unavailable' else 'No directly collected trade series is selected for this activity. A parent-based estimate is not shown as an observation.'}})
                evidence = {'policy_sha256':policy_hash,'inputs':audit.files.copy(),
                    'registry':registry.fingerprints,'sector_ids':sorted(policy['sectors'])}
            finally:
                audit.close()
        return cls({'sectors':sector_records,'regions':regions,'geographies':geographies,
            'items':items,'year':policy['target_year'],'unit':'million USD'}, payloads,evidence)
