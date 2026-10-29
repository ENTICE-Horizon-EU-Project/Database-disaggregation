"""Profile the unchanged MARIO pipeline through CVXLab graph construction only.

The observer replaces the solver boundary in this process. It builds the normal
CVXLab numerical problems, then stops deliberately, without feasibility/entropy
solves, result reconstruction, checkpoints or database publication.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import time
import traceback

import mario
import cvxlab
import database_disaggregation
from mario.ops import cvxlab_bridge as bridge
from database_disaggregation.core.parent_budgets import ParentBudgets, ChildTargets, require_parent_budgets
from run_model_trial import fingerprints, code_identity


class PreparationComplete(Exception):
    pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--options', type=Path, required=True)
    args = parser.parse_args()
    source, output = args.prepared.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    workbook = source / 'add_sectors.xlsx'
    baseline_hashes = fingerprints(source / 'baseline')
    workbook_hash = hashlib.sha256(workbook.read_bytes()).hexdigest()
    shutil.copytree(source / 'baseline', output / 'baseline')
    shutil.copy2(workbook, output / 'add_sectors.xlsx')
    options = json.loads(args.options.read_text())
    record = dict(status='running', started_at=datetime.now(timezone.utc).isoformat(),
        scope='MARIO engine, filtered bridge, CVXLab SQL and numerical graph; no solver/canonicalisation/reconstruction',
        source_preparation=str(source), source_workbook_sha256=workbook_hash,
        source_baseline_sha256=baseline_hashes, split_model_options=options,
        code={name: code_identity(module) for name, module in
              [('mario', mario), ('cvxlab', cvxlab), ('database_disaggregation', database_disaggregation)]},
        solver_called=False, database_accepted=False)
    path = output / 'preparation_profile.json'
    def save():
        path.write_text(json.dumps(record, indent=2, allow_nan=False) + '\n')
    save()
    started = time.monotonic()
    original = bridge._run_split_model
    def observe(model, *, dest_dir, **kwargs):
        record.update(phase='cvxlab_graph', model_directory=str(dest_dir))
        save()
        print('MEMORY PHASE: CVXLab numerical graph, solver disabled', flush=True)
        with bridge._model_workdir(dest_dir):
            model.refresh_database_and_initialize_problem(force_overwrite=True)
        record['problems'] = []
        for key, frame in model.core.problem.numerical_problems.items():
            for scenario, row in frame.iterrows():
                p = row['problem']
                record['problems'].append(dict(problem=str(key), scenario=str(scenario),
                    scalar_variables=sum(v.size for v in p.variables()),
                    explicit_scalar_constraints=sum(c.size for c in p.constraints)))
        raise PreparationComplete()
    bridge._run_split_model = observe
    code = 1
    try:
        db = mario.parse_from_parquet(str(output / 'baseline/flows'), table='IOT', mode='flows')
        db.read_add_sectors_excel(output / 'add_sectors.xlsx', read_inventories=True, split=True)
        require_parent_budgets(ParentBudgets.from_database(db), ChildTargets.from_workbook(db.add_sectors_workbook),
                              report_path=output / 'parent_budgets.json')
        db.add_sectors('inventories', split=True, intermediate_steps=True,
            save_intermediates=output / 'checkpoints', stop_after_step='Memory probe',
            split_model_options=options, solver='MOSEK')
        raise RuntimeError('The preparation observer did not stop before the solver.')
    except PreparationComplete:
        record.update(status='prepared_only', phase='complete_without_solver')
        code = 0
    except Exception as exc:
        record.update(status='failed', error=str(exc), traceback=traceback.format_exc())
        traceback.print_exc()
    finally:
        bridge._run_split_model = original
        record.update(elapsed_seconds=time.monotonic()-started,
            source_baseline_unchanged=fingerprints(source / 'baseline') == baseline_hashes,
            source_workbook_unchanged=hashlib.sha256(workbook.read_bytes()).hexdigest() == workbook_hash,
            working_baseline_unchanged=fingerprints(output / 'baseline') == baseline_hashes)
        if not all(record[k] for k in ('source_baseline_unchanged', 'source_workbook_unchanged', 'working_baseline_unchanged')):
            record.update(status='failed', integrity_error='Input hashes changed.')
            code = 1
        save()
    print(json.dumps({k:record.get(k) for k in ('status','elapsed_seconds','problems','solver_called','database_accepted')}, indent=2))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
