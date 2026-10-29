"""Prepare a shared geography and one editable MARIO split/step workbook."""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
from io import BytesIO
from pathlib import Path
import tempfile

from database_disaggregation.core.baseline import copy_database, load_baseline
from database_disaggregation.core.geography import Geography
from database_disaggregation.core.parent_budgets import ChildTargets, ParentBudgets, read_child_targets, require_parent_budgets
from database_disaggregation.inventory.regionalize import aggregate_inventory


@dataclass(frozen=True)
class PreprocessedData:
    """Matching regional database, MARIO input workbook and preparation audit."""

    database: object
    workbook: Path
    audit: Path


def prepare_inputs(source_dir=None, output_dir=None, *, database=None, data_root=None, geography=None, steps=None,
                   intermediate_steps=False, baseline_path=None, baseline_format=None,
                   output_reference_dir=None, cleaning_policy=None, source_paths=None,
                   missing_output="parent_share", missing_cost_structure="same_sector_then_parent",
                   inconsistent_targets="reconcile"):
    """Prepare without solving or altering the canonical native source files.

    Supply ``database`` and ``data_root`` for the full collected-data workflow.
    This returns :class:`PreprocessedData`: an aggregated database, the prepared
    workbook and its audit directory. The three missing/inconsistent-data
    options each accept the documented reconstruction strategy or ``"raise"``.

    The legacy ``source_dir`` workflow returns its output directory as before.
    ``source_dir`` contains resolved MARIO/D2.4 inventories (the same boundary
    used by Camilla's regional aggregation). The original generation pipeline
    can pass its freshly exported native inventory directory here.

    ``database`` accepts an already parsed MARIO IOT, at the source inventories'
    regional resolution. Its original file format is irrelevant. ``geography``
    aggregates a copy for the prepared workbook; the native object supplies
    reconciliation weights. The supplied database is neither mutated nor saved.
    ``baseline_path``/``baseline_format`` remain available for disk-based runs
    and must not be combined with ``database``.
    """
    if database is not None and (baseline_path is not None or baseline_format is not None):
        raise ValueError('Supply database or baseline_path/baseline_format, not both.')
    if output_dir is None:
        raise ValueError('Supply output_dir for the preparation results.')
    if data_root is not None:
        if database is None:
            raise ValueError('Supply the parsed MARIO database with data_root.')
        if cleaning_policy is not None or output_reference_dir is not None or intermediate_steps:
            raise ValueError('With data_root, use the explicit missing-data options and steps, '
                             'rather than legacy cleaning_policy/output_reference_dir/intermediate_steps.')
        from database_disaggregation.reconciliation.model_inputs import _prepare_model_inputs
        return _prepare_model_inputs(
            database, output_dir, data_root=data_root, geography=geography, steps=steps,
            source_dir=source_dir, source_paths=source_paths, missing_output=missing_output,
            missing_cost_structure=missing_cost_structure, inconsistent_targets=inconsistent_targets,
        )
    if source_dir is None:
        raise ValueError('Supply data_root for collected data, or source_dir for existing inventories.')
    if (missing_output, missing_cost_structure, inconsistent_targets) != (
            'parent_share', 'same_sector_then_parent', 'reconcile'):
        raise ValueError('Explicit missing-data options require the data_root workflow.')
    native_database = database
    from mario.ops.add_sector_steps import validate_plan, write_workbook_payload
    if steps is not None and (not isinstance(steps, dict) or any(
            not isinstance(name, str) or not name.strip() or not isinstance(values, list)
            or any(not isinstance(s, str) or not s.strip() for s in values)
            for name, values in steps.items())):
        raise ValueError('steps must map non-empty group names to sector-name lists.')
    source_dir, output_dir = Path(source_dir), Path(output_dir)
    if output_dir.exists():
        raise FileExistsError(f"Use a new preparation directory: {output_dir}")
    files = sorted(p for p in source_dir.glob('*.xlsx') if not p.name.startswith('~$'))
    if not files:
        raise FileNotFoundError(f"No resolved inventory workbooks found in {source_dir}")
    database = (copy_database(native_database, geography) if native_database is not None
                else load_baseline(baseline_path, baseline_format, geography=geography))
    if geography is None:
        geography = Geography({r: r for r in database.get_index('Region')}, 'native')
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f'.{output_dir.name}_', dir=output_dir.parent))
    inventories = staging / 'inventories'
    results = []
    try:
        budgets = ParentBudgets.from_database(database)
        reconciliation = None
        if cleaning_policy is not None and cleaning_policy is not False:
            from database_disaggregation.reconciliation import reconcile_inventories
            cleaned = reconcile_inventories(source_dir,staging/'reconciled',geography=geography,
                policy=cleaning_policy,baseline_path=baseline_path,baseline_format=baseline_format,
                output_reference_dir=output_reference_dir,source_paths=source_paths,selected_database=database,
                native_database=native_database)
            inventories = cleaned/'inventories'
            reconciliation = json.loads((cleaned/'complete.json').read_text())
            inputs = json.loads((cleaned/'audit/inputs.json').read_text())
            results = [{'sector':c,'source':path,'source_sha256':inputs[path]['sha256'],
                        'output_reference':None,'output_reference_sha256':None}
                       for c,path in reconciliation['inventory_sources'].items()]
        else:
            reference_dir = Path(output_reference_dir) if output_reference_dir else None
            references = None
            targets = read_child_targets(files)
            coverage = targets.output.groupby('Sector')['Region'].agg(set)
            missing_outputs = any(sector not in coverage or geography.mapping.keys() - coverage[sector]
                                  for sector in targets.master['Sector'].dropna().unique())
            if missing_outputs and reference_dir and reference_dir.is_dir():
                references = read_output_references(reference_dir)
                targets = read_child_targets(files, output_references=references)
            require_parent_budgets(budgets, targets.aggregate(geography), report_path=staging / 'parent_budgets.json')
            for source in files:
                from openpyxl import load_workbook
                book = load_workbook(BytesIO(source.read_bytes()), read_only=True, data_only=True)
                try:
                    sector = next(book['Master'].iter_rows(min_row=2, values_only=True))[1]
                finally:
                    book.close()
                results.append(aggregate_inventory(source, inventories / source.name, geography,
                                                   output_reference=(references or {}).get(sector)))
        database.read_add_sectors_excel(inventories, read_inventories=True, split=True)
        workbook = database.add_sectors_workbook
        expected = {r['sector'] for r in results}
        actual = set(workbook.master_sheet['Sector'])
        if expected != actual:
            raise ValueError(f"Native MARIO reader did not retain all inventories: expected={expected}, actual={actual}")
        budget_report = require_parent_budgets(budgets, ChildTargets.from_workbook(workbook),
                                               report_path=staging / 'parent_budgets.json')
        if intermediate_steps and steps is None:
            steps = {'Step 1': workbook.master_sheet['Sector'].drop_duplicates().tolist()}
        workbook = replace(workbook, intermediate_steps=steps)
        if steps is not None:
            validate_plan(workbook, database.get_index('Sector'))
        write_workbook_payload(workbook, staging / 'add_sectors.xlsx', instance=database)
        if native_database is None:
            database.to_parquet(path=staging / 'baseline', flows=True, coefficients=False, include_meta=True)
        manifest = {'baseline_kind': 'mario_database' if native_database is not None else 'files',
                    'baseline_exported': native_database is None, 'geography': {'name': geography.name, 'mapping': geography.mapping,
                                   'regions': geography.regions}, 'inventories': results,
                    'steps': steps, 'source_files': {r['source']: r['source_sha256'] for r in results},
                    'parent_budget_checks': budget_report['summary'],
                    'output_reference_files': {r['output_reference']: r['output_reference_sha256']
                                               for r in results if r['output_reference']},
                    'input_kind': 'reconciled_sources' if reconciliation else 'resolved_native_profiles', 'status': 'prepared',
                    'reconciliation':reconciliation,
                    'zero_output_profile_policy': ('logged_child_donor_then_parent_reference' if reconciliation
                                                   else 'unweighted_reference_with_warning'),
                    'support_defaults': 'Missing Exclusions empty; missing delta/eps zero. Existing values retained.'}
        (staging / 'preparation.json').write_text(json.dumps(manifest, indent=2, allow_nan=False))
        staging.rename(output_dir)
    except Exception as exc:
        (staging / 'failure.json').write_text(json.dumps({'status': 'failed', 'error': str(exc)}, indent=2))
        raise
    return output_dir


def read_output_references(directory, *, read_bytes=None):
    """Use explicitly stored native outputs to restore sparse export coverage.

    D2.4 export retains only countries with a rendered profile. Original MARIO
    inputs retain their separate output observations, including explicit zeros.
    No absent observation is converted to zero here.
    """
    from openpyxl import load_workbook
    references = {}
    for path in sorted(Path(directory).glob('*.xlsx')):
        if path.name.startswith('~$'):
            continue
        raw = read_bytes(path) if read_bytes is not None else path.read_bytes()
        book = load_workbook(BytesIO(raw), read_only=True, data_only=True)
        try:
            if 'Total outputs' not in book:
                continue
            header, *values = book['Total outputs'].values
            rows = [{k: v for k, v in dict(zip(header, row)).items() if k in ('Sector', 'Region', 'Quantity', 'Unit')}
                    for row in values if row[0] is not None]
            sectors = {row['Sector'] for row in rows}
            if len(sectors) != 1:
                raise ValueError(f'Expected one output-reference sector in {path}')
            sector = sectors.pop()
            if sector in references and references[sector]['rows'] != rows:
                raise ValueError(f'Conflicting native output reference files for {sector}')
            references[sector] = {'source': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'rows': rows}
        finally:
            book.close()
    return references
