"""Build internal, metadata-only HS–NACE and regional concordance audits."""
from __future__ import annotations
import argparse
import copy
import csv
import datetime
import io
import json
import os
import re
import shutil
import sys
import tempfile
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

from database_disaggregation.core import reference_mapping as mapping_engine
from database_disaggregation.core.reference_mapping import (
    digest, csv_rows, official_hs_routes, nace_hierarchy, leaves,
    comparison_envelope, partition_audit, whole_region_selection,
    footprint_from_explorer, xlsx_records, hs_code, write_csv, verify_artifacts,
)
from database_disaggregation.core.paths import PROJECT_ROOT, local_config, project_data_root


def read(path):
    return json.loads(Path(path).read_text())


def metadata_strings(file, name):
    import h5py
    with h5py.File(file) as handle:
        return [''.join(chr(int(v)) for v in handle[r][()].ravel()).strip()
                for r in handle[name][()].ravel()]


def normalized(value):
    return ' '.join(value.split()).casefold()


def profile_for(scope, family, release, system=None):
    found = [p for p in scope['profiles'] if p['family'] == family and p['release'] == release
             and 2023 in p.get('years', []) and (not system or p['system'] == system)]
    if len(found) != 1:
        raise ValueError(f'Expected one 2023 profile for {family}/{release}/{system}')
    return found[0]


def build(mario, ssd, sources, output, rules_path, repo=PROJECT_ROOT, *, allow_explorer_cache=False):
    output.mkdir(parents=True, exist_ok=True)
    snapshots=mario/'doc/classifications/sectoral';webdata=mario/'doc/source/_static/data'
    scope_path=webdata/'economy/country-scope.json';scope=read(scope_path)
    online=ssd.is_dir()
    if not online and not allow_explorer_cache:
        raise FileNotFoundError('Reference SSD is unavailable. Reconnect it, or explicitly use --allow-explorer-cache for a provisional metadata-only build.')
    registry=read(repo/'data/registry/sectors.json')
    rules=read(rules_path)
    bridge=official_hs_routes(sources)
    official=read(snapshots/'official-activity-bridges.json')
    nodes=nace_hierarchy(sources, official['node_names'])
    by_hs=defaultdict(set)
    for r in bridge:by_hs[r['hs_edition'],r['hs6']].add(r['nace2'])
    revisions=defaultdict(list)
    for e in official['edges']:
        if e['right'][0]=='NACE2.1' and re.fullmatch(r'\d\d\.\d\d',e['left'][1]):
            revisions[e['right'][1]].append(e)
    inventories=[];native=[];regions={}; input_paths=[scope_path,repo/'data/registry/sectors.json',rules_path,
        snapshots/'official-activity-bridges.json',Path(__file__).resolve(),Path(mapping_engine.__file__).resolve(),webdata/'geography-concordances.json',
        webdata/'external_profiles/gtap-12-power-scope.json']
    def add_record(dataset, code, name, classes, paths, qualification='', origin='explorer', basis='activity'):
        if any(c not in nodes for c in classes):raise ValueError('Invalid class in native scope')
        native.append(dict(dataset=dataset, native_code=code, native_name=name,
            nace2_classes=sorted(set(classes)), reference='NACE Rev. 2', basis=basis,
            mapping_origin=origin, qualification=qualification, evidence_routes=paths,
            status='linked_footprint' if classes else 'unresolved', allocation_weight=None))
    # EXIOBASE: verify the complete actual archive vocabularies before reuse.
    exio_profile=profile_for(scope,'EXIOBASE','3.11.2','ixi')
    for system, ns in [('ixi','EXIO3I'),('pxp','EXIO3P')]:
        dataset=f'EXIOBASE_3.11.2_{system}_2023'
        archive=ssd/f'EXIOBASE/3.11.2/IOT_2023_{system}.zip'
        if online:
            with zipfile.ZipFile(archive) as z:
                unit_bytes=z.read('unit.txt');rows=list(csv.DictReader(io.StringIO(unit_bytes.decode('utf-8-sig')),delimiter='\t'))
        else:
            p=profile_for(scope,'EXIOBASE','3.11.2',system)
            unit_bytes=json.dumps(dict(sectors=p['sets']['Sector'],regions=p['regions'])).encode()
            rows=[dict(sector=s,region=r['label']) for s in p['sets']['Sector'] for r in p['regions']]
        raw_sectors=list(dict.fromkeys(r['sector'] for r in rows));raw_regions=list(dict.fromkeys(r['region'] for r in rows))
        if set(raw_regions)!=set(r['label'] for r in exio_profile['regions']):raise ValueError('EXIO region inventory mismatch')
        if system=='ixi':
            file=snapshots/'nxbase-reviewed-activities.json';items=read(webdata/'economy/sectoral-scope.json')['columns']['activity']
            items=next(c['native'] for c in items if c['family']=='EXIOBASE' and c['units']=='Monetary')
            input_paths.extend([file,webdata/'economy/sectoral-scope.json'])
        else:
            file=snapshots/'nxbase-products.json';items=[r for r in read(file)['items'] if r['namespace']==ns];input_paths.append(file)
        by_name={normalized(r['name']):r for r in items}
        if set(map(normalized,raw_sectors))!=set(by_name):raise ValueError(f'EXIO {system} native sector identity mismatch')
        for name in raw_sectors:
            item=by_name[normalized(name)];classes,paths,q=footprint_from_explorer(item,revisions,nodes,product=system=='pxp')
            add_record(dataset,item['code'],name,classes,paths,q,basis='product_origin' if system=='pxp' else 'activity')
        inventories.append(dict(dataset=dataset,family='EXIOBASE',release='3.11.2',year=2023,
            representation=system,sectors=len(raw_sectors),regions=len(raw_regions),source=str(archive),
            source_size_bytes=archive.stat().st_size if online else None,native_metadata_sha256=__import__('hashlib').sha256(unit_bytes).hexdigest(),
            fingerprint_scope='unit.txt verified; no full matrix read or archive hash' if online else 'Cached Explorer vocabulary only; direct SSD verification pending'))
    # EMERGING raw MATLAB metadata only: the transaction datasets are not read.
    em_file=ssd/'EMERGING/2.2/EMERGING_V2_2023_m.mat'
    emp=profile_for(scope,'EMERGING','2.2')
    em_labels=metadata_strings(em_file,'sector_list') if online else [f'{i:02} {name}' for i,name in enumerate(emp['sets']['Sector'],1)]
    em_regions=metadata_strings(em_file,'country_list') if online else [r['label'] for r in emp['regions']]
    cleaned=[re.sub(r'^\d+\s+','',s) for s in em_labels]
    if set(em_regions)!=set(r['label'] for r in emp['regions']) or set(map(normalized,cleaned))!=set(map(normalized,emp['sets']['Sector'])):
        raise ValueError('EMERGING 2.2 source/Explorer vocabulary mismatch')
    dataset='EMERGING_2.2_2023';hs_vocabulary=read(sources/'hs2002.json')['results']
    for r in rules['emerging_goods']:
        index=r['native_index'];raw=em_labels[index-1]
        if raw!=r['expected_raw_label']:raise ValueError('EMERGING reviewed descriptor changed')
        chapter=r['hs_chapter'];codes=[x['id'] for x in hs_vocabulary if len(x['id'])==6 and x['id'].startswith(chapter)]
        classes=sorted({n for code in codes for n in by_hs['H2',code]})
        missing=[code for code in codes if not by_hs['H2',code]]
        add_record(dataset,f'{index:03}',cleaned[index-1],classes,
            [dict(raw_label=raw,hs_edition='H2',hs_chapter=chapter,hs6_count=len(codes),unmapped_hs6=missing,
                  evidence='emerging-scope-review.json; hs_nace_routes.csv')],
            'Editorial chapter identity; product-origin footprint; version-2 publisher scope not independently certified.'
                + (' Incomplete HS coverage.' if missing else ''),origin=r['scope_status'],basis='product_origin')
    for r in rules['emerging_services_and_energy']:
        index=r['native_index']
        if em_labels[index-1]!=r['expected_raw_label']:raise ValueError('EMERGING service descriptor changed')
        add_record(dataset,f'{index:03}',cleaned[index-1],sorted(leaves(r['nace2_scope'],nodes)),
            [dict(raw_label=em_labels[index-1],declared_nace_scope=r['nace2_scope'],note=r['note'])],
            r['scope_status']+'; not a publisher-issued detailed concordance',origin=r['scope_status'],basis='service_or_energy_descriptor')
    add_record(dataset,'096',cleaned[95],[],[dict(raw_label=em_labels[95])],
               'Commodities not specified by kind cannot be allocated to a producer activity.')
    inventories.append(dict(dataset=dataset,family='EMERGING',release='2.2',year=2023,representation='product/service IOT',
        sectors=len(em_labels),regions=len(em_regions),source=str(em_file),source_size_bytes=em_file.stat().st_size if online else None,
        native_metadata_sha256=__import__('hashlib').sha256(json.dumps([em_labels,em_regions]).encode()).hexdigest(),
        fingerprint_scope='sector_list/country_list only; X,z,f,va not read' if online else 'Cached Explorer vocabulary only; direct SSD verification pending'))
    # GLORIA metadata and editorial detailed scope; publisher sheet is section-level.
    gp=profile_for(scope,'GLORIA','060');gloria_readme=ssd/'GLORIA/060/GLORIA_ReadMe_060.xlsx'
    raw_gloria=xlsx_records(gloria_readme,'Sectors')[1:] if online else list(enumerate(gp['sets']['Activity'],1))
    raw_gloria=[r for r in raw_gloria if r[0] is not None]
    g_regions=xlsx_records(gloria_readme,'Regions')[1:] if online else [(i,r['label'],r['name']) for i,r in enumerate(gp['regions'],1)]
    g_regions=[r for r in g_regions if r[0] is not None]
    if [r[1] for r in raw_gloria]!=gp['sets']['Activity'] or set(r[1] for r in g_regions)!=set(r['label'] for r in gp['regions']):
        raise ValueError('GLORIA source/Explorer native inventory mismatch')
    gfile=snapshots/'nxbase-gloria-icio.json';gitems={r['code']:r for r in read(gfile)['items'] if r['namespace']=='GLORIA060'};input_paths.append(gfile)
    publisher_sections={r[0]:[str(c) for c,v in zip('ABCDEFGHIJKLMNOPQRST',r[1:]) if v==1]
        for r in xlsx_records(gloria_readme,'GLORIA to ISIC concordance')[2:] if r[0]} if online else {}
    for index,name in raw_gloria:
        item=gitems[str(index)]
        if item['name']!=name:raise ValueError('GLORIA native sector identity mismatch')
        classes,paths,q=footprint_from_explorer(item,revisions,nodes)
        add_record('GLORIA_060_activity_2023',str(index),name,classes,
            [dict(publisher_isic_sections=publisher_sections.get(name),publisher_direct_verification=online),*paths],
            '; '.join(filter(None,['Detailed links are editorial; publisher concordance is section-level',q])))
    archive=ssd/'GLORIA/060/GLORIA_MRIO_Loop060_part_I_MRIOdatabase/GLORIA_MRIOs_60_2023.zip'
    members=[]
    if online:
        with zipfile.ZipFile(archive) as z:members=[dict(name=i.filename,size=i.file_size,crc=i.CRC) for i in z.infolist() if not i.is_dir()]
        if not any('_2023_060_' in i['name'] for i in members):raise ValueError('GLORIA archive year/release mismatch')
    inventories.append(dict(dataset='GLORIA_060_activity_2023',family='GLORIA',release='060',year=2023,
        representation='native SUT activities',sectors=len(raw_gloria),regions=len(g_regions),source=str(archive),
        source_size_bytes=archive.stat().st_size if online else None,readme_sha256=digest(gloria_readme) if online else None,archive_members=members,
        fingerprint_scope='2023 archive central directory and release metadata; no matrices read' if online else 'Cached Explorer vocabulary only; direct SSD verification pending'))
    if online:input_paths.append(gloria_readme)
    # Region identity and membership: retain historical codes, never silently merge them.
    georef=read(webdata/'geography-concordances.json')['exiobase']
    def profile_regions(profile, family):
        result=[]
        for r in profile['regions']:
            code=r['label'];members=[];complete=False;note=''
            if r.get('kind')=='country' and r.get('iso3'):
                members=[r['iso3']];complete=True;note='Published native code / governed ISO3 identity; territorial coverage requires valuation/source review.'
            elif family=='EXIOBASE' and code in georef['members']:
                members=georef['members'][code];complete=True;note='Explicit EXIOBASE region-classification.xlsx membership.'
            else:note='Historical or rest-of-world membership unresolved; no inference from label.'
            result.append(dict(native_code=code,native_name=r['name'],members=members,
                membership_complete=complete,scope_note=note))
        return result
    regions['EXIOBASE']=profile_regions(exio_profile,'EXIOBASE')
    regions['EMERGING']=profile_regions(emp,'EMERGING')
    regions['GLORIA']=profile_regions(gp,'GLORIA')
    # Country regions can include dependencies in GTAP's own published geography.
    gtap=read(webdata/'external_profiles/gtap-12-power-scope.json')
    dependencies={'AUS':['CXR','CCK','HMD','NFK'],'FIN':['ALA'],'FRA':['GLP','MTQ','REU'],'NOR':['SJM']}
    expected_dependency_names={'AUS':{'-','Australia','Christmas Island','Cocos (Keeling) Islands','Heard Island and McDonald Islands','Norfolk Island'},
        'FIN':{'-','Finland','Åland Islands'},'FRA':{'-','France','Guadeloupe','Martinique','Réunion'},
        'NOR':{'-','Norway','Svalbard and Jan Mayen Islands'}}
    regions['GTAP12']=[]
    for r in gtap['geography']['regions']:
        code=r['label'];members=list(r.get('members',[]));complete=r.get('membership_status')=='source_mapped' and not r.get('unresolved_members')
        if r.get('kind')=='country':
            members=[r['iso3']];complete=True
            if r.get('source_members'):
                if set(r['source_members'])!=expected_dependency_names.get(code):raise ValueError('GTAP dependency definition changed')
                members+=dependencies[code]
        regions['GTAP12'].append(dict(native_code=code,native_name=r['name'],members=sorted(set(members)),
            membership_complete=complete,scope_note='GTAP12 published region scope, including explicitly listed dependencies.',
            source_members=r.get('source_members',[])))
    audits={family:partition_audit(items) for family,items in regions.items()}
    if any(a['overlaps'] for a in audits.values()):raise ValueError(f'Overlapping declared region memberships: {audits}')
    geography_rows=[]
    for family,items in regions.items():
        for r in items:
            for member in r['members'] or [None]:geography_rows.append(dict(dataset=family,native_code=r['native_code'],
                native_name=r['native_name'],iso3_member=member,membership_complete=r['membership_complete'],scope_note=r['scope_note']))
    native_common=set.intersection(*[{r['members'][0] for r in regions[f] if r['membership_complete'] and len(r['members'])==1}
                                   for f in ['EXIOBASE','EMERGING','GLORIA']])
    common_countries={code:{f:whole_region_selection([code],regions[f]) for f in regions} for code in sorted(native_common)}
    mapping=read(repo/'data/geographies/gtap13.json');input_paths.append(repo/'data/geographies/gtap13.json')
    grouped=defaultdict(set);incomplete_targets=set()
    for r in regions['GTAP12']:
        target=mapping[r['native_code']];grouped[target].update(r['members'])
        if not r['membership_complete']:incomplete_targets.add(target)
    regional_comparison=[]
    for target,memberset in grouped.items():
        for family in ['EXIOBASE','EMERGING','GLORIA']:
            result=whole_region_selection(memberset,regions[family])
            regional_comparison.append(dict(target_geography='ENTICE13',target_region=target,source_family=family,
                target_members=sorted(memberset),target_membership_complete=target not in incomplete_targets,**result))
    # Read new-sector HS assignments as evidence, not as an allocation.
    hsbook=project_data_root()/'Classifications/_sources/New sectors classification.xlsx'
    hsrows=xlsx_records(hsbook,'New GTAP - HS concordance');input_paths.append(hsbook)
    assignments=defaultdict(list)
    for number,row in enumerate(hsrows[1:],2):
        for pos in [5,7,8]:
            if len(row)<=pos or not row[pos]:continue
            sector=str(row[pos]).strip().upper()
            if sector not in {s['id'] for s in registry['sectors']}:continue
            for edition,col in [('H6',0),('H5',1)]:
                try:code=hs_code(row[col])
                except ValueError:continue
                assignments[sector].append(dict(hs_edition=edition,hs6=code,source_row=number,assignment_source_column=pos+1,hs_source_column=col+1,
                    candidate_nace2=sorted(by_hs[edition,code]),
                    source_single_sector_assignment=sum(bool(row[c]) for c in [5,7,8] if len(row)>c)==1,
                    assignment_relation='declared_candidate_not_economic_weight',
                    source='New sectors classification.xlsx / New GTAP - HS concordance'))
    target_rows=[];comparisons=[];package_targets=[]
    fine_reviews=defaultdict(list)
    native_index={(r['dataset'],r['native_code']):r for r in native}
    for review in rules.get('specific_native_reviews',[]):
        row=native_index[review['dataset'],review['native_code']]
        if row['native_name']!=review['expected_native_name']:raise ValueError('Reviewed specific native identity changed')
        fine_reviews[review['entice_code'],review['dataset']].append(review)
    reg_by_id={s['id']:s for s in registry['sectors'] if s['lifecycle']=='published_d24'}
    for rule in rules['entice']:
        sector=rule['entice_code'];canonical=reg_by_id[sector]
        if canonical['name']!=rule['expected_name']:raise ValueError('ENTICE scope identity changed')
        classes=leaves(rule['nace2_scope'],nodes);hs_evidence=assignments[sector]
        incompatible=[r for r in hs_evidence if r['candidate_nace2'] and not set(r['candidate_nace2'])&classes]
        target_rows.append(dict(entice_code=sector,entice_name=canonical['name'],nace2_scopes=rule['nace2_scope'],
            nace2_classes=sorted(classes),scope_origin=rule['origin'],scope_status=rule['scope_status'],
            hs_assignments=len(hs_evidence),hs_incompatible_rows=sorted({r['source_row'] for r in incompatible}),note=rule['note']))
        package_targets.append({**target_rows[-1],'hs_evidence':hs_evidence,'evidence':rule['evidence']})
        for dataset in [r['dataset'] for r in inventories]:
            records=[r for r in native if r['dataset']==dataset]
            candidates=[r for r in records if classes&set(r['nace2_classes'])]
            envelope=comparison_envelope(classes,records,nodes)
            fine=fine_reviews[sector,dataset]
            comparisons.append(dict(entice_code=sector,entice_name=canonical['name'],dataset=dataset,
                entice_scope_status=rule['scope_status'],target_nace2=rule['nace2_scope'],
                fine_scope_status='; '.join(sorted({r['specificity'] for r in fine})) if fine else 'broader_native_scope_or_review_required',
                specific_native_codes=[r['native_code'] for r in fine],
                specific_native_names=[r['expected_native_name'] for r in fine],
                intersecting_native_codes=[r['native_code'] for r in candidates],
                intersecting_native_names=[r['native_name'] for r in candidates],
                **envelope,entice_specific_equivalence='not_established_by_NACE_membership',
                note='A common NACE footprint is not proof that a native sector equals the fine ENTICE technology/product.'))
    vocab_coverage=[]
    for edition,filename in [('H2','hs2002.json'),('H4','hs2012.json'),('H5','hs2017.json'),('H6','hs2022.json')]:
        for row in read(sources/filename)['results']:
            if not re.fullmatch(r'\d{6}',row['id']):continue
            classes=sorted(by_hs[edition,row['id']])
            vocab_coverage.append(dict(hs_edition=edition,hs6=row['id'],description=row['text'],
                nace2_classes=classes,status='unmapped' if not classes else 'unique_producer_class' if len(classes)==1 else 'multiple_producer_classes',
                allocation_weight=None))
    native_summary=[{k:v for k,v in r.items() if k!='evidence_routes'} for r in native]
    # Product paths use compact step identifiers in Explorer. Freeze their
    # definitions so evidence stays usable after the Explorer changes branch.
    product_snapshot=read(snapshots/'nxbase-products.json')
    step_ids={step for r in native for route in r['evidence_routes'] for step in route.get('steps',[]) if isinstance(step,str)}
    all_steps={**product_snapshot['route_steps'],**read(webdata/'economy/sectoral-scope.json')['route_steps']}
    product_steps={key:all_steps[key] for key in sorted(step_ids)}
    source_metadata={}
    for path in [snapshots/'nxbase-products.json',snapshots/'nxbase-reviewed-activities.json',snapshots/'nxbase-gloria-icio.json',snapshots/'official-activity-bridges.json']:
        source_metadata[str(path.relative_to(mario))]=read(path).get('sources',[])
    write_csv(output/'hs_nace_routes.csv',bridge)
    write_csv(output/'hs_nace_coverage.csv',vocab_coverage)
    write_csv(output/'native_sector_nace.csv',native_summary)
    write_csv(output/'entice_sector_scopes.csv',target_rows)
    write_csv(output/'entice_comparability.csv',comparisons)
    write_csv(output/'entice_hs_scope_conflicts.csv',[
        dict(entice_code=r['entice_code'],entice_nace2_scope=r['nace2_scopes'],**a)
        for r in package_targets for a in r['hs_evidence']
        if a['candidate_nace2'] and not set(a['candidate_nace2'])&set(r['nace2_classes'])],
        fields=['entice_code','entice_nace2_scope','hs_edition','hs6','source_row','assignment_source_column','hs_source_column',
                'candidate_nace2','source_single_sector_assignment','assignment_relation','source'])
    write_csv(output/'region_membership.csv',geography_rows)
    write_csv(output/'entice13_geography_compatibility.csv',regional_comparison)
    write_csv(output/'common_individual_geography.csv',[
        dict(iso3=code,**{family:selection['native_regions'] for family,selection in sources.items()},
             gtap_exact_on_declared_membership=sources['GTAP12']['exact_on_declared_membership'])
        for code,sources in common_countries.items()])
    metadata_dir=output/'sources';metadata_dir.mkdir(exist_ok=True)
    for f in sources.iterdir():
        if f.is_file() and f.resolve().parent!=metadata_dir.resolve():shutil.copy2(f,metadata_dir/f.name)
    shutil.copy2(rules_path,metadata_dir/'scope-review.json')
    fingerprints=[dict(path=str(p),sha256=digest(p)) for p in dict.fromkeys(input_paths)]
    for p in metadata_dir.iterdir():
        if p.is_file():fingerprints.append(dict(path=str(p),sha256=digest(p)))
    package=dict(schema_version=1,year=2023,reference='NACE Rev. 2',internal_only=True,
        direct_ssd_verification=online,
        generated_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        scope='Metadata-only concordance audit. No economic matrices parsed, allocated or optimised.',
        sources=fingerprints,source_urls=read(sources/'urls.json'),inventories=inventories,
        nace2_nodes=nodes,native_sectors=native,entice_sectors=package_targets,
        explorer_route_steps=product_steps,explorer_source_metadata=source_metadata,
        specific_native_reviews=rules.get('specific_native_reviews',[]),
        geography=regions,geography_audit=audits,common_individual_countries=common_countries,
        entice13_compatibility=regional_comparison,comparability=comparisons,
        hs_coverage_summary={ed:dict(Counter(r['status'] for r in vocab_coverage if r['hs_edition']==ed)) for ed in ['H2','H4','H5','H6']},
        allocation_policy='No economic weights. Many-to-many footprints cannot be multiplied into flows.',
        unresolved_policy='Missing and partial scopes stay explicit. No default equal allocation or fuzzy joins.')
    (output/'mapping-package.json').write_text(json.dumps(package,ensure_ascii=False,indent=2)+'\n')
    write_summary(output,package,target_rows)
    # Recheck all relatively small metadata sources, not large numerical archives.
    for r in fingerprints:
        if digest(r['path'])!=r['sha256']:raise ValueError('Mapping source changed during build')
    package['artifacts']={str(p.relative_to(output)):digest(p) for p in sorted(output.rglob('*'))
        if p.is_file() and p.name!='mapping-package.json'}
    (output/'mapping-package.json').write_text(json.dumps(package,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(output=str(output),native_scope_counts=dict(Counter(r['dataset'] for r in native)),
        common_individual_countries=len(native_common),hs_coverage=package['hs_coverage_summary'],
        exact_entice13={f:[r['target_region'] for r in regional_comparison if r['source_family']==f and r['exact_on_declared_membership']]
                         for f in ['EXIOBASE','EMERGING','GLORIA']}),ensure_ascii=False,indent=2))
    return package


def write_summary(output,package,target_rows):
    lines=['# Raccordi per i benchmark ENTICE 2023','',
        'Uso interno. Riferimento comune: **NACE Rev. 2**. Questa analisi legge classificazioni e metadati delle versioni 2023; non ricalcola il database e non esegue allocazioni economiche.',
        '', '## Copertura delle classificazioni', '',
        '| Fonte | Settori presenti | Con un raccordo NACE | Qualifica |', '| --- | ---: | ---: | --- |']
    if not package['direct_ssd_verification']:
        lines[2:2]=['**Verifica diretta dei file SSD in sospeso:** l’unità esterna è stata scollegata durante il lavoro. Questa generazione usa i vocabolari 2023 già documentati nell’Explorer. Ricollegare l’SSD e rigenerare senza `--allow-explorer-cache` per verificare nuovamente le identità native.', '']
    for inv in package['inventories']:
        rows=[r for r in package['native_sectors'] if r['dataset']==inv['dataset']]
        lines.append(f"| {inv['dataset']} | {len(rows)} | {sum(bool(r['nace2_classes']) for r in rows)} | Impronta di appartenenza; nessun peso economico |")
    lines+=['','Il percorso è HS → CPC 2.1 → ISIC Rev. 4 → NACE Rev. 2. HS 2002 e HS 2022 passano per le correlazioni ufficiali con HS 2017; HS 2012 e 2017 hanno tabelle CPC dirette. Sono mantenuti tutti i percorsi e i flag parziali. Una classe di origine unica non implica identità fra prodotto e industria.',
        '', 'EMERGING: i progressivi dei 133 settori non sono codici HS. La metodologia originale indica HS 2002 ed EBOPS 2010; le identità della versione 2.2 sono verificate sul MATLAB 2023. Le attribuzioni di capitolo e le proposte sui servizi sono revisioni esplicite del benchmark, non una concordanza dettagliata emessa dagli autori. I servizi trasversali restano qualificati o irrisolti.',
        '', 'GLORIA: la concordanza ufficiale del ReadMe è per sezioni ISIC. I raccordi più dettagliati riutilizzano la revisione editoriale nxbase/Explorer, mantenendo tale provenienza. EXIOBASE distingue il riferimento per attività (ixi) da quello per prodotti (pxp).',
        '', '## Quanto dettaglio ENTICE possiamo confrontare?', '',
        'Tutti i 67 settori hanno una scheda in `entice_sector_scopes.csv`. Le scope esistenti nel registro non vengono modificate. Quelle aggiunte per il benchmark sono dichiarate editoriali; gli scope alternativi per processo restano aperti. `entice_comparability.csv` distingue i candidati specifici per descrittore dalle sole appartenenze NACE e riporta anche il più piccolo nodo NACE chiuso rispetto alle impronte note.',
        '', '**Un raccordo alla stessa classe NACE non certifica un confronto del settore ENTICE isolato.** Le classi possono contenere più metalli o tecnologie. Le chiusure sono limiti di classificazione candidati: `quantitative_ready=false` fino alla verifica del perimetro e delle definizioni contabili. Gli insiemi che attraversano sezioni non sono forzati in un aggregato fittizio.',
        '', 'Il requisito di chiusura su tutte le categorie native può produrre un inviluppo molto ampio o attraversare più sezioni. Questo non cancella un confronto specifico supportato separatamente dai descrittori: MCU, MAO, MIO e NIK hanno candidati specifici in EXIOBASE e GLORIA, mentre EMERGING li raggruppa nel capitolo dei minerali. Le tipologie di batteria restano dentro categorie più ampie.',
        '', '| Settore ENTICE | Scope NACE | Fonte | Candidato specifico o categoria più ampia | Stato |', '| --- | --- | --- | --- | --- |']
    for code in ['MCU','CHR','APP','APS','NMC','SOP','BVL','RAL','LIT']:
        for row in package['comparability']:
            if row['entice_code']==code:
                values=row['specific_native_names'] or row['intersecting_native_names']
                labels='; '.join(values[:3])+(' …' if len(values)>3 else '')
                lines.append(f"| {code} | {', '.join(row['target_nace2'])} | {row['dataset']} | {labels or 'Non disponibile'} | {row['fine_scope_status']} |")
    conflict_codes=[r['entice_code'] for r in target_rows if r['hs_incompatible_rows']]
    lines+=['','## Geografia', '',f"Le tre fonti condividono **{len(package['common_individual_countries'])} identificativi di paesi individuali**. L’elenco completo, con la possibilità di selezionarli anche in GTAP, è nel pacchetto JSON. Questo insieme non è automaticamente ricostruibile dal database già aggregato a 13 regioni.",
        '', 'La selezione degli aggregati ENTICE13 richiede coincidenza dei membri, usando soltanto regioni sorgente intere. Si includono i territori dichiarati nelle regioni GTAP: Australia comprende CXR/CCK/HMD/NFK; Finlandia ALA; Francia GLP/MTQ/REU; Norvegia SJM. Non si sommano ingenuamente i 27 paesi EXIOBASE per chiamarli lo stesso EU27 di GTAP.',
        '', '| Fonte | Aggregati ENTICE13 riproducibili con i membri dichiarati |', '| --- | --- |']
    for family in ['EXIOBASE','EMERGING','GLORIA']:
        ready=[r['target_region'] for r in package['entice13_compatibility'] if r['source_family']==family and r['exact_on_declared_membership']]
        lines.append(f"| {family} | {', '.join(ready) or 'Nessuno'} |")
    lines+=['', 'Gli altri aggregati non sono approvati: `entice13_geography_compatibility.csv` espone i membri mancanti e le regioni che richiederebbero uno split. Questo criterio è rigoroso sulle appartenenze dichiarate; non certifica ulteriori differenze di confine economico o residenza.',
        '', 'Codici da non fondere automaticamente: ANT e SER in EMERGING; DYE in GLORIA. SDS in GLORIA è identificato come SSD dal nome pubblicato South Sudan. I quattro blocchi XAM/XEU/XAF/XAS di GLORIA restano senza enumerazione completa finché non troviamo una concordanza esplicita.',
        '', '## Incongruenze nel raccordo HS ENTICE esistente', '',
        'La verifica segnala incompatibilità tra i codici HS assegnati e lo scope NACE per: '+(', '.join(conflict_codes) or 'nessun settore')+'. Sono casi da riesaminare, non correzioni applicate agli input. Le celle originali e tutti i percorsi sono in `entice_hs_scope_conflicts.csv`.',
        '', '## File e riproducibilità', '',
        '- `hs_nace_routes.csv`: tutti i percorsi, comprese corrispondenze parziali e revisioni.',
        '- `hs_nace_coverage.csv`: vocabolari HS completi, compresi i codici non raccordati.',
        '- `native_sector_nace.csv`: ogni settore nativo, con base attività/prodotto e qualifica.',
        '- `entice_sector_scopes.csv` e `entice_comparability.csv`: dettaglio dei 67 settori e limiti del confronto.',
        '- `entice_hs_scope_conflicts.csv`: assegnazioni HS da riesaminare, con riga e colonne sorgente.',
        '- `region_membership.csv` e `entice13_geography_compatibility.csv`: membri e aggregazioni utilizzabili.',
        '- `common_individual_geography.csv`: paesi individuali condivisi e selezionabilità in GTAP.',
        '- `mapping-package.json`: metadati, percorsi, fonti e checksum.',
        '- `sources/`: copia delle piccole concordanze ufficiali e della revisione usata.',
        '', 'I risultati non sono pubblicati online. Non contengono matrici monetarie. MARIO e CVXLab non vengono modificati. Il prossimo uso quantitativo deve verificare scope, prezzi, valute e indipendenza delle fonti prima di confrontare i KPI.',
        '', 'I codici HS sono stringhe a sei cifre nel JSON e nei CSV. In Excel importare quelle colonne come testo per conservarne gli zeri iniziali.',
        '', 'Fonti: [UNSD](https://unstats.un.org/unsd/classifications/econ/), [EMERGING: metodologia](https://doi.org/10.1111/jiec.13264), [EMERGING 2.2](https://zenodo.org/records/19461860), [EXIOBASE 3.11.2](https://zenodo.org/records/23039074), [GLORIA](https://ielab.info/resources/gloria). I singoli file e le celle dei raccordi sono tracciati nel pacchetto.','']
    (output/'README.md').write_text('\n'.join(lines))


if __name__=='__main__':
    config=local_config();settings=config.get('benchmarking',{})
    def configured_path(key):
        value=settings.get(key)
        if value is None:return None
        path=Path(value).expanduser()
        return path if path.is_absolute() else project_data_root()/path
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mario-source',type=Path,default=config.get('mario_source'))
    parser.add_argument('--reference-root',type=Path,default=configured_path('reference_root'))
    parser.add_argument('--source-dir',type=Path,default=configured_path('source_dir'))
    parser.add_argument('--output',type=Path,default=configured_path('mapping_output'))
    parser.add_argument('--scope-review',type=Path,default=PROJECT_ROOT/'data/benchmarking/sector_scopes.json')
    parser.add_argument('--allow-explorer-cache',action='store_true',help='Explicit provisional build from cached Explorer metadata if SSD is offline.')
    parser.add_argument('--overwrite',action='store_true',help='Replace generated mapping files after validation; preserve unrelated files.')
    args=parser.parse_args()
    if any(v is None for v in [args.mario_source,args.reference_root,args.source_dir,args.output]):
        parser.error('Set benchmarking reference_root/source_dir/mapping_output in paths.local.json, or pass explicit paths.')
    for name in ['mario_source','reference_root','source_dir','output','scope_review']:
        setattr(args,name,getattr(args,name).expanduser().resolve())
    if (args.output/'mapping-package.json').exists() and not args.overwrite:
        parser.error('Mapping bundle exists; pass --overwrite to replace generated outputs.')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.mapping-build-',dir=args.output.parent) as temporary:
        stage=Path(temporary)/'package'
        package=build(args.mario_source,args.reference_root,args.source_dir,stage,args.scope_review,allow_explorer_cache=args.allow_explorer_cache)
        for source in package['sources']:
            path=Path(source['path'])
            if path.is_relative_to(stage):source['path']=str(args.output/path.relative_to(stage))
        (stage/'mapping-package.json').write_text(json.dumps(package,ensure_ascii=False,indent=2)+'\n')
        verify_artifacts(stage)
        args.output.mkdir(parents=True,exist_ok=True)
        for path in stage.iterdir():
            if path.name=='mapping-package.json':continue
            target=args.output/path.name
            if path.is_dir():shutil.copytree(path,target,dirs_exist_ok=True)
            else:os.replace(path,target)
        os.replace(stage/'mapping-package.json',args.output/'mapping-package.json')
        verify_artifacts(args.output)
        print('Validated internal mapping bundle:',args.output)
