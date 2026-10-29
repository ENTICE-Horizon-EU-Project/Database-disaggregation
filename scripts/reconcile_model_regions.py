"""Build an aggregation compatible with native GTAP, without splitting regions."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import shutil

from database_disaggregation.core.model_regions import coarsen_model_regions, read_model_region_inputs
from database_disaggregation.core.paths import data_path
from database_disaggregation.core.geography import Geography
from database_disaggregation.core.registry import Registry


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False)+'\n')


def table(path, rows, fields):
    with path.open('w', newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader();writer.writerows(rows)


def main():
    source_folder = data_path('classifications').parent/'GTAP model regions'
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workbook', type=Path, default=source_folder/'Region clusters for models.xlsx')
    parser.add_argument('--gtap-scope', type=Path, default=source_folder/'GTAP12 region scope.json')
    parser.add_argument('--output', type=Path, required=True, help='New directory; existing outputs are never overwritten.')
    args=parser.parse_args()
    if args.output.exists():
        parser.error('Use a fresh output directory.')
    hashes=dict(workbook=sha(args.workbook), native_scope=sha(args.gtap_scope))
    inputs=read_model_region_inputs(args.workbook,args.gtap_scope, missing_groups={'FRO':'NAI','IMN':'NAI'})
    result=coarsen_model_regions(inputs['country_groups'],inputs['native_members'], unrepresented={'XTW':'XTW'})
    geography=Geography(result['mapping'],'GTAP models compatible')
    geography.validate(Registry.load().members('GLOBAL',geography='GTAP12'))
    merged={code:sorted(group for group,target in result['desired_to_effective'].items() if target==code)
            for code in set(result['desired_to_effective'].values())}
    region_rows=[]
    for code in sorted(set(result['mapping'].values())):
        groups=merged.get(code,[])
        native=sorted(r for r,t in result['mapping'].items() if t==code)
        countries=sorted(c for c,t in result['country_mapping'].items() if t==code)
        name='; '.join(inputs['desired_names'][g] for g in groups) if groups else inputs['native_names'][code]
        row=dict(code=code,name=name,desired_groups=' | '.join(groups),
                 native_regions=' | '.join(native),listed_countries=' | '.join(countries))
        for model in ['GEM-E3','OPEN-PROM','GEMINI-E3','SORMAC-25']:
            codes=sorted({inputs['model_regions'].get(c,{}).get(model) or 'UNASSIGNED' for c in countries})
            row[model]=' | '.join(codes) if codes else 'NOT COVERED BY COUNTRY SHEET'
        region_rows.append(row)
    country_rows=[dict(**r,native_gtap=result['country_native'][r['iso3']],effective_region=result['country_mapping'][r['iso3']])
                  for r in inputs['country_rows']]
    report=dict(format='entice-native-compatible-geography-v1', sources_sha256=hashes,
        method='Finest common coarsening of desired model groups and native GTAP regions; merge connected groups transitively. No geographic disaggregation or GDP allocation.',
        source_regions=result['source_regions'],desired_regions=result['desired_regions'],target_regions=result['target_regions'],
        country_rows=len(country_rows),corrections=inputs['corrections'],
        merged_groups=[g for g in result['components'] if len(g)>1],native_conflicts=result['native_conflicts'],
        unrepresented_native=result['unrepresented_native'],
        model_aggregation_limit='Where a final region contains several codes of one model, the original model partition cannot be recovered exactly by further aggregation.',
        members_outside_country_sheet=sorted(set().union(*(set(v) for v in inputs['native_members'].values()))-inputs['country_groups'].keys()),
        monetary_data_used=False,model_run=False)
    args.output.mkdir(parents=True,exist_ok=False)
    shutil.copy2(args.workbook,args.output/'Region clusters for models.xlsx')
    shutil.copy2(args.gtap_scope,args.output/'GTAP12 region scope.json')
    save(args.output/'gtap-models-compatible.json',result['mapping'])
    save(args.output/'reconciliation.json',report)
    table(args.output/'gtap-to-model-regions.csv',[dict(source=r,target=t) for r,t in sorted(result['mapping'].items())],['source','target'])
    table(args.output/'countries.csv',country_rows,['iso3','country','desired_group','desired_name','native_gtap','effective_region'])
    table(args.output/'regions.csv',region_rows,list(region_rows[0]))
    assert sha(args.workbook)==hashes['workbook'] and sha(args.gtap_scope)==hashes['native_scope']
    assert sha(args.output/'Region clusters for models.xlsx')==hashes['workbook']
    save(args.output/'checksums.json',{p.name:sha(p) for p in args.output.iterdir() if p.is_file()})
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    main()
