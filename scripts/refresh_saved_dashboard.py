"""Refresh a saved result and 2023 reference comparisons from audited caches only.

No MARIO model construction, preparation, optimisation or native-source reads.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil

import numpy as np
import pandas as pd

from database_disaggregation.core.benchmark import Flows, build_report, fingerprints, sha256, write_report
from database_disaggregation.core.paths import PROJECT_ROOT
from database_disaggregation.core import reference_benchmark as reference
from database_disaggregation.core.reference_mapping import verify_artifacts, checkpoint_geography
from database_disaggregation.reporting.constraints import archived_constraints


def refresh(database, cached_references, geography_path, mario_source, baskets_path, *, backup_dir=None, region_names_path=None):
    database, cached_references = Path(database).resolve(), Path(cached_references).resolve()
    before = fingerprints(database)
    baseline = database / 'baseline'
    baseline_before = fingerprints(baseline)
    state = json.loads((database / 'state.json').read_text())
    if backup_dir is not None:
        backup_dir = Path(backup_dir)
        backup_dir.mkdir(parents=True, exist_ok=False)
        for name in ['benchmarking.html', 'benchmarking.json', 'benchmarking-sectors.csv', 'README.md']:
            if (database / name).exists():
                shutil.copy2(database / name, backup_dir / name)

    old_comparisons_path = cached_references / 'comparisons.json'
    old_comparisons = json.loads(old_comparisons_path.read_text())
    provenance = {row['family']: row for row in old_comparisons['sources']}
    source_hashes = {str(old_comparisons_path): sha256(old_comparisons_path)}
    mapping_source = cached_references / 'mapping-snapshot'
    mapping = verify_artifacts(mapping_source)
    if not mapping.get('direct_ssd_verification') or mapping['year'] != 2023:
        raise ValueError('Require the previously verified 2023 reference mapping.')
    cache = database / 'reference-benchmarks'
    cache.mkdir(exist_ok=True)
    for family in ['exiobase', 'emerging', 'gloria']:
        source = cached_references / f'{family}-2023-profiles.json'
        if sha256(source) != provenance[family.upper()]['profile_sha256']:
            raise ValueError(f'Original audited cache changed: {family}')
        source_hashes[str(source)] = sha256(source)
        shutil.copy2(source, cache / source.name)
    if (cache / 'mapping-snapshot').exists():
        if sha256(cache / 'mapping-snapshot/mapping-package.json') != sha256(mapping_source / 'mapping-package.json'):
            raise ValueError('Existing mapping snapshot differs from the audited source.')
        verify_artifacts(cache / 'mapping-snapshot')
    else:
        shutil.copytree(mapping_source, cache / 'mapping-snapshot')
    shutil.copy2(baskets_path, cache / 'comparison-baskets.json')

    # Keep explicit display metadata with the result, including activities that
    # have collected inputs but are not yet in the canonical registry.
    metadata = database / 'diagnostics/provenance'
    metadata.mkdir(parents=True, exist_ok=True)
    additional = PROJECT_ROOT / 'config/additional-sectors-13.json'
    if additional.exists() and not (metadata / additional.name).exists():
        shutil.copy2(additional, metadata / additional.name)
    if region_names_path is not None:
        from database_disaggregation.analysis.labels import read_region_names
        geography_map = json.loads(Path(geography_path).read_text())
        read_region_names(region_names_path, regions=set(geography_map.values()), geography=geography_map)
        shutil.copy2(region_names_path, metadata / 'region-names.csv')

    print('Build numerical report from saved baseline and final flows; Leontief calculations disabled.', flush=True)
    report = build_report(baseline, database, system=False)
    constraints, rows = archived_constraints(database, export_inputs=database / 'inputs/steps')
    for sector, values in constraints.items():
        report['targets']['by_sector'][sector].update(values)

    # Recompute final values independently of old reports and join to exact
    # effective step constraints; no threshold rejects a saved optimal point.
    flows = Flows.read(database)
    output = flows['X'].iloc[:, 0]
    deliveries = flows['Z'].T.groupby(level='Region').sum().T.add(
        flows['Y'].T.groupby(level='Region').sum().T, fill_value=0)
    values = [float(output.at[(row.origin, row.product)]) if row.kind == 'Output'
              else float(deliveries.at[(row.origin, row.product), row.destination])
              for row in rows.itertuples()]
    rows['result'] = values
    rows['difference_MUSD'] = rows.result - rows.constraint
    rows['difference_USD'] = rows.difference_MUSD * 1e6
    rows.to_csv(database / 'constraints.csv', index=False)
    (database / 'constraints.json').write_text(json.dumps({'by_sector': constraints}, indent=2, allow_nan=False))
    del flows, deliveries, output

    baskets = json.loads(Path(baskets_path).read_text())
    if baskets.get('year') != 2023 or not baskets.get('internal_only'):
        raise ValueError('Require internal 2023 comparison baskets.')
    if sha256(baskets_path) != old_comparisons['basket_definitions_sha256']:
        raise ValueError('Comparison baskets differ from the audited reference extraction.')
    geography = checkpoint_geography(mapping, json.loads(Path(geography_path).read_text()), report['dimensions']['regions'])
    print('Recompute ENTICE metrics and reuse only checksum-verified external profiles.', flush=True)
    comparisons = reference.build_comparisons(report, mapping, baskets,
        reference_root=Path('/Volumes/SanDisk SSD/Work/IO databases'), cache=cache,
        mario_source=Path(mario_source), engine_identity=sha256(reference.__file__),
        geography=geography, cache_only=True, cache_provenance=provenance)
    comparisons.update(
        generated_at=datetime.now(timezone.utc).isoformat(),
        mapping_package_sha256=sha256(mapping_source / 'mapping-package.json'),
        basket_definitions_sha256=sha256(baskets_path), engine_sha256=sha256(reference.__file__),
        region_memberships={row['target_region']: row['target_members'] for row in geography},
        geography_source=dict(path=str(Path(geography_path).resolve()), sha256=sha256(geography_path)),
        geography_audit=geography,
        entice_scope_warnings=[{key: row[key] for key in ('entice_code', 'entice_name', 'hs_incompatible_rows', 'note')}
                               for row in mapping['entice_sectors'] if row.get('hs_incompatible_rows')],
    )
    reference.atomic_json(cache / 'geography-compatibility.json',
                          dict(source=comparisons['geography_source'], rows=geography))
    reference.atomic_json(cache / 'comparisons.json', comparisons)
    flat = []
    for row in comparisons['rows']:
        for dataset in ['entice', 'baseline', 'reference']:
            flat.append({**{key: row[key] for key in ['family', 'region', 'basket', 'label', 'nace_reference', 'comparison_basis', 'qualification', 'baseline_scope']},
                'year': 2023, 'monetary_unit': 'M USD', 'dataset': dataset,
                'entice_sectors': ';'.join(row['entice_sectors']), 'native_codes': ';'.join(row['native_codes']),
                **{key: value for key, value in row[dataset].items() if not isinstance(value, list)}})
    pd.DataFrame(flat).to_csv(cache / 'comparisons.csv', index=False)
    report['external_comparisons'] = comparisons
    report['provenance'].update(reference_cache_mode='offline_verified_cache',
        reference_sources_reread=False, reference_cache_source_report=str(old_comparisons_path),
        reference_cache_source_report_sha256=sha256(old_comparisons_path),
        effective_constraints=dict(path='constraints.csv', sha256=sha256(database / 'constraints.csv'),
                                   archive_sha256=sha256(database / 'diagnostics/step-artifacts.zip')))
    if fingerprints(database) != before or fingerprints(baseline) != baseline_before:
        raise ValueError('Saved database changed during read-only benchmarking.')
    for path, digest in source_hashes.items():
        if sha256(path) != digest:
            raise ValueError('An archived reference artifact changed during refresh.')
    write_report(report, database / 'benchmarking.html', overwrite=True)
    verification = dict(generated_at=datetime.now(timezone.utc).isoformat(),
        model_rerun=False, preprocessing_rerun=False, native_sources_reread=False,
        internal_only=True, regions=report['summary']['regions'],
        added_activities=len(state['completed_sectors']), final_sectors=report['summary']['final_sectors'],
        skipped_activities=report['summary']['skipped_sectors'],
        source_flows_unchanged=fingerprints(database) == before and fingerprints(baseline) == baseline_before,
        effective_constraint_records=len(rows), exported_effective_step_workbooks=len(constraints),
        geographic_coverage={row['family']: len(row['geography']) for row in comparisons['sources']},
        unique_reference_comparisons=len(comparisons['rows']), csv_records=len(flat),
        source_cache_hashes=source_hashes,
        outputs={name: sha256(database / name) for name in ['benchmarking.html', 'benchmarking.json', 'constraints.csv', 'constraints.json']})
    reference.atomic_json(cache / 'verification.json', verification)
    print(json.dumps(verification, indent=2), flush=True)
    return report


if __name__ == '__main__':
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--database', type=Path, required=True)
    cli.add_argument('--cached-references', type=Path, required=True)
    cli.add_argument('--geography', type=Path, required=True)
    cli.add_argument('--mario-source', type=Path, required=True)
    cli.add_argument('--baskets', type=Path, default=PROJECT_ROOT / 'data/benchmarking/comparison_baskets.json')
    cli.add_argument('--backup-dir', type=Path)
    cli.add_argument('--region-names', type=Path, help='Reviewed code/name/native_regions CSV for this exact geography.')
    args = cli.parse_args()
    refresh(args.database, args.cached_references, args.geography, args.mario_source, args.baskets,
            backup_dir=args.backup_dir, region_names_path=args.region_names)
