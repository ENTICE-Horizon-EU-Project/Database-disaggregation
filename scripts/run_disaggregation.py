"""Prepare regional inputs, optionally solve, or resume a committed step.

No model is solved unless --solve is supplied. Paths/configuration remain in
the existing ENTICE_CONFIG/data_root mechanism.
"""
import argparse
import json
from pathlib import Path

from database_disaggregation.core.paths import local_config, project_data_root, data_path
from database_disaggregation.core.geography import Geography, configured_geography
from database_disaggregation.core.disaggregation import prepare_inputs
from database_disaggregation.core.parent_budgets import ChildTargets, ParentBudgets, require_parent_budgets
from database_disaggregation.core.shared_runs import remaining_workbook


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    existing = parser.add_mutually_exclusive_group()
    parser.add_argument('--inventories', type=Path)
    parser.add_argument('--mapping', type=Path, help='Two-column regional partition; overrides geography in config.')
    parser.add_argument('--output-references', type=Path, help='Original MARIO inventories with complete native output observations.')
    parser.add_argument('--steps', type=Path, help='JSON object: named groups in execution order; omit for oneshot.')
    parser.add_argument('--output', type=Path, help='New preparation directory, or checkpoint root when resuming.')
    parser.add_argument('--intermediate-steps', action='store_true', help='Generate an editable initial group when no --steps JSON is supplied.')
    cleaning=parser.add_mutually_exclusive_group()
    cleaning.add_argument('--cleaning-policy',type=Path,help='Versioned reconciliation assumptions JSON; requires the existing source datasets.')
    cleaning.add_argument('--no-cleaning',action='store_true',help='Skip reconciliation; original cumulative budget checks remain blocking.')
    existing.add_argument('--prepared', type=Path, help='Solve a previously prepared directory after editing its workbook.')
    parser.add_argument('--solve', action='store_true')
    parser.add_argument('--solver', default='CLARABEL')
    parser.add_argument('--model-options',type=Path,help='Opt-in experimental MARIO IOT split model settings JSON.')
    parser.add_argument('--stop-after-step',help='Save and return after this named pending group; requires --solve and Intermediate steps.')
    existing.add_argument('--resume', type=Path, help='Committed MARIO step directory.')
    parser.add_argument('--workbook', type=Path, help='Edited remaining or full source workbook when resuming.')
    args = parser.parse_args()
    if args.model_options and not args.solve:
        parser.error('--model-options requires --solve')
    model_options = json.loads(args.model_options.read_text()) if args.model_options else None
    if args.stop_after_step and not args.solve:
        parser.error('--stop-after-step requires --solve')
    if (args.resume or args.prepared) and any((args.mapping, args.inventories, args.steps,
                                              args.output_references, args.intermediate_steps,args.cleaning_policy,args.no_cleaning)):
        parser.error('Existing runs retain their geography; edit the workbook for group changes, or prepare a new run.')
    if args.resume:
        if not args.solve:
            parser.error('--resume requires --solve')
        if not args.output:
            parser.error('--resume requires --output for the checkpoint root')
        from mario.ops.add_sector_steps import load_checkpoint
        from mario.ops.add_sector_workbook import load_add_sector_workbook_input
        db = load_checkpoint(args.resume)
        workbook = args.workbook or remaining_workbook(args.resume)
        payload, _ = load_add_sector_workbook_input(workbook, table='IOT', read_inventories=True, split=True)
        require_parent_budgets(ParentBudgets.from_database(db),
                               ChildTargets.from_workbook(payload).pending(db),
                               report_path=args.output / 'parent_budgets_resume.json')
        db.add_sectors(workbook, split=True, intermediate_steps=True, save_intermediates=args.output,
                       solver=args.solver,stop_after_step=args.stop_after_step,
                       **({'split_model_options':model_options} if model_options is not None else {}))
        return
    if args.prepared:
        if not args.solve:
            parser.error('--prepared requires --solve')
        destination = args.prepared
    elif args.workbook:
        parser.error('--workbook requires --resume or --prepared')
    elif not args.output:
        parser.error('--output is required for input preparation')
    config = local_config().get('disaggregation', {})
    source = args.inventories
    if source is None and not args.prepared:
        if not config.get('inventories'):
            parser.error('Supply --inventories or disaggregation.inventories in the local config.')
        source = Path(config['inventories']).expanduser()
        if not source.is_absolute():
            source = project_data_root(required=True) / source
    if not args.prepared:
        geography = Geography.read(args.mapping) if args.mapping else configured_geography()
        steps = json.loads(args.steps.read_text()) if args.steps else config.get('steps')
        policy=None if args.no_cleaning else args.cleaning_policy or config.get('cleaning_policy')
        if isinstance(policy,str):
            policy=Path(policy).expanduser()
            if not policy.is_absolute():policy=project_data_root(required=True)/policy
        destination = prepare_inputs(source, args.output, geography=geography, steps=steps,
                                     intermediate_steps=args.intermediate_steps,
                                     output_reference_dir=args.output_references or data_path('mario_inventories'),
                                     cleaning_policy=policy)
        print(f'Prepared inputs: {destination}')
    if args.solve:
        import mario
        db = mario.parse_from_parquet(str(destination / 'baseline' / 'flows'), table='IOT', mode='flows')
        workbook = args.workbook or destination / 'add_sectors.xlsx'
        db.read_add_sectors_excel(workbook, read_inventories=True, split=True)
        require_parent_budgets(ParentBudgets.from_database(db), ChildTargets.from_workbook(db.add_sectors_workbook),
                               report_path=destination / 'parent_budgets_solve.json')
        steps = db.add_sectors_workbook.intermediate_steps
        planned_sectors=set(db.add_sectors_workbook.master_sheet['Sector'])
        if args.stop_after_step and steps is None:
            parser.error('--stop-after-step requires an Intermediate steps plan')
        options = dict(split=True, solver=args.solver,stop_after_step=args.stop_after_step)
        if model_options is not None:
            options['split_model_options'] = model_options
        if steps is not None:
            options.update(intermediate_steps=True, save_intermediates=args.output if args.prepared and args.output else destination / 'checkpoints')
        else:
            options['cvxlab_path'] = destination / 'cvxlab'
            options['cvxlab_path'].mkdir()
        if (destination / 'final').exists():
            raise FileExistsError('A final database already exists in this preparation directory.')
        db.add_sectors('inventories', **options)
        if planned_sectors-set(db.get_index('Sector')):
            print(f'Stopped after {args.stop_after_step}; intermediate database and remaining workbook saved in checkpoints.')
            return
        db.to_parquet(path=destination / 'final', flows=True, coefficients=False, include_meta=True)


if __name__ == '__main__':
    main()
