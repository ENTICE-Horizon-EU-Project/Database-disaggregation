"""Attach private 2023 reference comparisons to an existing saved benchmark.

No optimisation, database balancing, or model execution. Source databases remain
read-only; small derived profile caches live beside the benchmark outputs.
"""
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path

for variable in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','VECLIB_MAXIMUM_THREADS'):
    os.environ.setdefault(variable,'2')
from database_disaggregation.core.paths import PROJECT_ROOT,local_config,project_data_root
from database_disaggregation.core import reference_benchmark as engine
from database_disaggregation.core.benchmark import sha256,write_report
from database_disaggregation.core.reference_mapping import verify_artifacts, checkpoint_geography


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--database',type=Path,required=True,help='Completed checkpoint with benchmarking.json; absolute or relative to Data split.')
    cli.add_argument('--reference-root',type=Path)
    cli.add_argument('--region-map',type=Path,help='Native GTAP to saved region JSON; required for geographies other than the reviewed ENTICE13.')
    cli.add_argument('--mapping-dir',type=Path)
    cli.add_argument('--mario-source',type=Path)
    cli.add_argument('--baskets',type=Path,default=PROJECT_ROOT/'data/benchmarking/comparison_baskets.json')
    cli.add_argument('--output',type=Path,help='Defaults to DATABASE/benchmarking.html.')
    cli.add_argument('--overwrite',action='store_true')
    args=cli.parse_args();config=local_config();settings=config.get('benchmarking',{})
    def resolve(p):return p.resolve() if p.is_absolute() else (project_data_root()/p).resolve()
    database=resolve(args.database);saved=database/'benchmarking.json'
    report=json.loads(saved.read_text());old_sha=sha256(saved)
    if Path(report['provenance']['database']).resolve()!=database:raise ValueError('Saved report points to another database')
    output=resolve(args.output) if args.output else database/'benchmarking.html'
    if output.exists() and not args.overwrite:raise FileExistsError('Pass --overwrite to refresh the existing benchmark report')
    mapping_dir=resolve(args.mapping_dir or Path(settings.get('mapping_output','Classifications/Benchmark mappings/2023')))
    mapping=verify_artifacts(mapping_dir)
    if not mapping.get('direct_ssd_verification') or mapping['year']!=2023:raise ValueError('Reference comparisons require verified 2023 native classifications')
    reference=args.reference_root or settings.get('reference_root');mario=args.mario_source or config.get('mario_source')
    if not reference or not mario:raise ValueError('Configure benchmarking.reference_root and mario_source in paths.local.json')
    baskets=json.loads(args.baskets.read_text())
    if baskets['year']!=2023 or not baskets['internal_only']:raise ValueError('Unexpected comparison basket configuration')
    geography = mapping['entice13_compatibility']
    geography_source = None
    if args.region_map:
        region_map = resolve(args.region_map)
        geography = checkpoint_geography(mapping,json.loads(region_map.read_text()),report['dimensions']['regions'])
        geography_source = dict(path=str(region_map),sha256=sha256(region_map))
    profiles=engine.build_comparisons(report,mapping,baskets,reference_root=Path(reference).expanduser(),cache=database/'reference-benchmarks',mario_source=Path(mario).expanduser(),engine_identity=sha256(engine.__file__),geography=geography)
    profiles['region_memberships']={r['target_region']:r['target_members'] for r in geography}
    profiles['geography_source']=geography_source
    profiles['geography_audit']=geography
    engine.atomic_json(database/'reference-benchmarks/geography-compatibility.json',dict(source=geography_source,rows=geography))
    profiles['entice_scope_warnings']=[{k:r[k] for k in ('entice_code','entice_name','hs_incompatible_rows','note')} for r in mapping['entice_sectors'] if r.get('hs_incompatible_rows')]
    profiles.update(generated_at=datetime.now(timezone.utc).isoformat(),mapping_package_sha256=sha256(mapping_dir/'mapping-package.json'),basket_definitions_sha256=sha256(args.baskets),engine_sha256=sha256(engine.__file__))
    atomic=engine.atomic_json
    atomic(database/'reference-benchmarks/comparisons.json',profiles)
    flat=[]
    for r in profiles['rows']:
        for dataset in ['entice','baseline','reference']:
            flat.append({**{k:r[k] for k in ['family','region','basket','label','nace_reference','comparison_basis','qualification','baseline_scope']},'year':2023,'monetary_unit':'M USD','entice_sectors':';'.join(r['entice_sectors']),'baseline_sectors':';'.join(r['baseline_sectors']),'native_codes':';'.join(r['native_codes']),'dataset':dataset,**{k:v for k,v in r[dataset].items() if not isinstance(v,list)}})
    import pandas as pd
    csv=database/'reference-benchmarks/comparisons.csv';pd.DataFrame(flat).to_csv(csv,index=False)
    report['external_comparisons']=profiles
    report['provenance'].update(reference_comparisons_source_report_sha256=old_sha,presentation_refreshed_at=datetime.now(timezone.utc).isoformat())
    for path in write_report(report,output,overwrite=args.overwrite):print(path,flush=True)
    print(f"Reference comparison rows: {len(profiles['rows'])}; no model rerun",flush=True)
    return 0

if __name__=='__main__':raise SystemExit(main())
