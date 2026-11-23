"""Reconcile explicitly selected pending siblings on an immutable checkpoint copy.

This opt-in data transformation retains the existing signed-row projection and
source weights. It writes a dense foreign-trade table for selected siblings so
that fitted zeros survive MARIO's presence-based trade selector. It does not
certify full MRIO feasibility or modify the MRIO model or baseline. Only
sub-precision prepared output targets in exactly empty parents are normalized
to zero on copies, with an explicit per-cell audit; other outputs are retained.
"""
import argparse
import csv
from datetime import datetime, timezone
from dataclasses import replace
import hashlib
import json
import math
from pathlib import Path
import shutil

import numpy as np
import pandas as pd

from database_disaggregation.reconciliation.row_trade import fit_row_trade
from database_disaggregation.core.parent_budgets import ATOL, RTOL, ChildTargets, ParentBudgets, require_parent_budgets, diagnose_trial_parent_budgets
from reconcile_model_trade import rewrite_sheets
from run_model_trial import fingerprints



def normalize_zero_parent_outputs(database, outputs, parents, *, tolerance=ATOL):
    """Normalize only sub-precision pending output support and budget excess.

    Original observations and completed sectors are never edited. Other
    positive targets are retained; this is not a general output rescaling.
    """
    if set(parents) & set(database.get_index('Sector')):
        raise ValueError('Output-support cleanup is only for pending sectors.')
    selected = outputs.loc[outputs.Sector.isin(parents)]
    if selected.duplicated(['Sector','Region']).any():
        raise ValueError('Duplicate output targets before zero-support cleanup.')
    quantities = pd.to_numeric(selected.Quantity, errors='raise')
    if not np.isfinite(quantities).all() or (quantities < 0).any():
        raise ValueError('Output targets must be finite and nonnegative.')
    result, changes = outputs.copy(deep=True), []
    for parent in sorted(set(parents.values())):
        children = {s for s,p in parents.items() if p == parent}
        rows = selected.loc[selected.Sector.isin(children)]
        expected_unit = database.units['Sector'].loc[parent,'unit']
        if not rows.Unit.eq(expected_unit).all():
            raise ValueError(f'Output target units differ from parent {parent}.')
        for region, group in rows.groupby('Region',sort=False):
            capacity = float(database.X.loc[(region,'Sector',parent)].iloc[0])
            total = math.fsum(float(q) for q in group.Quantity)
            if set(group.Sector) != children:
                continue  # Missing observations must not become zero targets.
            if capacity == 0 and 0 < total <= tolerance:
                replacement, reason = 0., 'sub-precision target in an exactly zero parent budget'
            elif (len(children) == 1 and capacity >= 0 and total > capacity
                  and total-capacity <= tolerance):
                replacement, reason = capacity, 'sub-precision excess above the remaining parent output'
            else:
                continue
            for i,row in group.iterrows():
                value = float(row.Quantity)
                if value != replacement:
                    result.loc[i,'Quantity'] = replacement
                    changes.append(dict(sector=str(row.Sector),parent=str(parent),region=str(region),
                                        quantity_before=value,quantity_after=replacement,unit=str(expected_unit),
                                        parent_output=capacity,absolute_tolerance=tolerance,reason=reason))
    return result, changes


def reconcile(checkpoint, workbook, sectors, output, trade_audit, policy, *, prepared=None,
              database=None, workbook_payload=None):
    if (checkpoint is None) == (prepared is None):
        raise ValueError('Select exactly one checkpoint or prepared baseline.')
    source = Path(checkpoint or prepared).resolve()
    checkpoint, workbook, output = source, Path(workbook).resolve(), Path(output).resolve()
    if output == checkpoint or checkpoint in output.parents:
        raise ValueError('Output must be separate from the immutable checkpoint.')
    output.mkdir(parents=True, exist_ok=False)
    before = fingerprints(checkpoint)
    workbook_hash = hashlib.sha256(workbook.read_bytes()).hexdigest()
    if prepared is None:
        from mario.ops.add_sector_steps import load_checkpoint
        db = database if database is not None else load_checkpoint(checkpoint)
        if db._intermediate_steps_state['split_model_options']['accounting'] != 'inherit':
            raise ValueError('This projection requires inherited accounting.')
    else:
        import mario
        db = database if database is not None else mario.parse_from_parquet(str(source/'baseline/flows'), table='IOT', mode='flows')
    frames = ({s:pd.read_excel(workbook,sheet_name=s) for s in ['Master','Total outputs','Trades']}
              if workbook_payload is None else {'Master':workbook_payload.master_sheet.copy(),
                  'Total outputs':workbook_payload.split_info['Total outputs'].copy(),
                  'Trades':workbook_payload.split_info['Trades'].copy()})
    master, outputs, trades = (frames[s] for s in ['Master','Total outputs','Trades'])
    targets = ChildTargets(master,outputs,trades).pending(db).select(sectors)
    parents = targets.master.set_index('Sector')['Parent Sector'].to_dict()
    if len(parents)!=len(sectors):
        raise ValueError('Expected unique pending sector identities.')
    if set(parents)&set(db.get_index('Sector')):
        raise ValueError('Only pending sectors can be reconciled.')
    for parent in set(parents.values()):
        siblings=set(master.loc[master['Parent Sector'].eq(parent),'Sector'])-set(db.get_index('Sector'))
        if siblings-set(parents):
            raise ValueError(f'All pending siblings of {parent} must be reconciled together: {siblings-set(parents)}')
    outputs, output_adjustments = normalize_zero_parent_outputs(db, outputs, parents)
    q=outputs.set_index(['Sector','Region']).Quantity
    original=trades.set_index(['Sector_from','Region_from','Region_to'])
    if original.index.has_duplicates or q.index.has_duplicates:
        raise ValueError('Duplicate output or trade targets.')
    with Path(trade_audit).open() as handle:
        audit={(r['sector'],r['origin'],r['destination']):r for r in csv.DictReader(handle)}
    policy_data=json.loads(Path(policy).read_text())
    source_weights=policy_data['trade']['weights']
    regions=db.get_index('Region')
    new_rows,changes,records=[],[],[]
    for parent in sorted(set(parents.values())):
        children=sorted(s for s in parents if parents[s]==parent)
        for origin in regions:
            positive,negative=np.zeros(len(regions)),np.zeros(len(regions))
            for table in [db.Z,db.Y]:
                row=table.loc[(origin,'Sector',parent)]
                positive+=row.clip(lower=0).groupby(level='Region').sum().reindex(regions).to_numpy()
                negative+=(-row.clip(upper=0)).groupby(level='Region').sum().reindex(regions).to_numpy()
            parent_x=float(db.X.loc[(origin,'Sector',parent)].iloc[0])
            child_x=np.array([q.loc[(c,origin)] for c in children],dtype=float)
            residual_x=parent_x-math.fsum(child_x)
            rounding=(len(children)+1)*np.finfo(float).eps*(abs(parent_x)+abs(math.fsum(child_x)))
            # The workbook round-trip must use the same admissible budget band
            # as the preparation check; do not reject sub-cent serialization noise.
            rounding=max(rounding,ATOL+RTOL*max(abs(parent_x),abs(math.fsum(child_x))))
            if residual_x < -rounding:
                raise ValueError(f'Output excess for {parent}/{origin}: {residual_x}')
            xs=np.r_[max(residual_x,0.),child_x]
            discrepancy=math.fsum(positive-negative)-parent_x
            row_targets=xs*(1+discrepancy/parent_x) if parent_x>0 else xs.copy()
            row_targets[0]+=math.fsum(positive-negative)-math.fsum(row_targets)
            prior=np.zeros((len(children),len(regions)))
            weights=np.full(prior.shape,.1)
            for i,child in enumerate(children):
                for j,destination in enumerate(regions):
                    if destination==origin:continue
                    key=(child,origin,destination)
                    if key in original.index: prior[i,j]=float(original.loc[key,'Quantity'])
                    if key in audit: weights[i,j]=source_weights[audit[key]['source_kind']]
            # Include every foreign route in the feasibility probe. Previously
            # absent routes are zero references, allowed to change in the fit.
            try:
                fitted,record=fit_row_trade(positive,negative,row_targets,xs,prior,weights,
                                           regions.index(origin),observed=np.ones_like(prior,dtype=bool),solver='GUROBI')
            except RuntimeError as exc:
                # Retain one exact, small reproducible failing row problem.
                np.savez_compressed(output/'row_trade_failure.npz', positive=positive, negative=negative,
                                    row_targets=row_targets, outputs=xs, priors=prior, weights=weights,
                                    origin=np.array(regions.index(origin)), observed=np.ones_like(prior,dtype=bool))
                (output/'row_trade_failure.json').write_text(json.dumps(dict(
                    parent=parent, origin=origin, children=children, regions=regions,
                    error=str(exc), source_checkpoint=str(checkpoint)), indent=2)+'\n')
                raise RuntimeError(f'{parent}/{origin}: {exc}') from exc
            record.update(parent=parent,origin=origin,children=children)
            records.append(record)
            for i,child in enumerate(children):
                for j,destination in enumerate(regions):
                    if destination==origin:continue
                    key=(child,origin,destination)
                    value=float(fitted[i,j])
                    old=float(prior[i,j]);present=key in original.index
                    kind=audit.get(key,{}).get('source_kind','imputed')
                    changes.append(dict(sector=child,parent=parent,origin=origin,destination=destination,
                                        prior=old,reconciled=value,delta=value-old,source_kind=kind,
                                        previously_present=present,explicit_zero_target=value==0.))
                    new_rows.append(dict(Sector_from=child,Region_from=origin,Region_to=destination,Quantity=value,
                                         Unit=db.units['Sector'].loc[parent,'unit'],Source='checkpoint-signed-row-projection-dense-v1',
                                         Notes='Prepared scenario target, including fitted zeros; see reconciliation audit.'))
            print(f'{parent}/{origin}: {record["status"]}',flush=True)
    untouched=trades.loc[~trades.Sector_from.isin(sectors)]
    result=pd.concat([untouched,pd.DataFrame(new_rows).reindex(columns=trades.columns)],ignore_index=True)
    destination=output/'add_sectors.xlsx'
    replacements={'Trades':result}
    if output_adjustments:
        replacements['Total outputs']=outputs
        pd.DataFrame(output_adjustments).to_csv(output/'output_support_cleanup.csv',index=False)
    changed_members=rewrite_sheets(workbook,destination,replacements)
    checked=ChildTargets(targets.master,outputs.loc[outputs.Sector.isin(sectors)],result.loc[result.Sector_from.isin(sectors)])
    # Checkpoint accounting discrepancies are inherited by the MRIO model.
    # Keep the existing strict curation check for fresh inputs, but apply the
    # previously agreed monetary-reporting policy to resumed model trials.
    budget_check = diagnose_trial_parent_budgets if prepared is None else require_parent_budgets
    budget_report=budget_check(ParentBudgets.from_database(db),checked,report_path=output/'parent_budgets.json')
    expected=len(sectors)*len(regions)*(len(regions)-1)
    if len(new_rows)!=expected or len(result.loc[result.Sector_from.isin(sectors)])!=expected:
        raise ValueError('Incomplete dense foreign-trade table.')
    assert fingerprints(checkpoint)==before,'Checkpoint changed'
    assert hashlib.sha256(workbook.read_bytes()).hexdigest()==workbook_hash,'Source workbook changed'
    pd.DataFrame(changes).to_csv(output/'trade_changes.csv',index=False)
    absolute=sum(abs(r['delta']) for r in changes)
    changed=[r for r in changes if abs(r['delta'])>1e-6]
    report=dict(format='checkpoint-signed-row-projection-dense-v1',created_at=datetime.now(timezone.utc).isoformat(),
                status='projected',full_mrio_certified=False,source_checkpoint=str(checkpoint),source_checkpoint_sha256=before,
                source_checkpoint_unchanged=True,source_workbook=str(workbook),source_workbook_sha256=workbook_hash,
                workbook_sha256=hashlib.sha256(destination.read_bytes()).hexdigest(),selected_sectors=list(sectors),
                outputs_unchanged=not output_adjustments,output_support_cleanup=output_adjustments,
                output_support_cleanup_policy='Pending sub-precision empty-parent outputs and single-child budget excesses <=1e-6 original units; originals preserved.',
                baseline_unchanged=True,other_sectors_trade_unchanged=True,
                only_changed_zip_members=changed_members,all_other_workbook_members_byte_identical=True,
                source_trade_audit=str(Path(trade_audit).resolve()),source_policy=str(Path(policy).resolve()),
                source_weights=source_weights,solver='GUROBI',fallback=False,
                analytic_unique_rows=sum(g.get('solver')=='analytical_unique_row' for g in records),
                objective='Existing weighted squared trade deviations divided by max(prior, 1% route capacity, 1 USD); this is input reconciliation, not the MRIO KL objective.',
                dense_foreign_target_count=expected,explicit_zero_targets=sum(r['explicit_zero_target']for r in changes),
                newly_explicit_routes=sum(not r['previously_present']for r in changes),
                missing_route_semantics='Missing routes have zero weak priors in joint fitting; all fitted routes then become explicit scenario targets, not certified empirical zeros.',
                changed_routes_over_1USD=len(changed),absolute_trade_change_MUSD=absolute,
                largest_increase_MUSD=max((r['delta']for r in changes),default=0.),
                largest_decrease_MUSD=-min((r['delta']for r in changes),default=0.),
                parent_budget_summary=budget_report['summary'],groups=records)
    if prepared is not None:
        report['source_preparation'] = report.pop('source_checkpoint')
        report['source_preparation_sha256'] = report.pop('source_checkpoint_sha256')
        report['source_preparation_unchanged'] = report.pop('source_checkpoint_unchanged')
    (output/'reconciliation.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    shutil.copy2(__file__,output/'reconcile_checkpoint_trade.py')
    print(json.dumps({k:report[k]for k in ['status','selected_sectors','changed_routes_over_1USD','absolute_trade_change_MUSD','explicit_zero_targets']},indent=2),flush=True)
    if workbook_payload is not None:
        updated = replace(workbook_payload, split_info={**workbook_payload.split_info, 'Trades':result, 'Total outputs':outputs})
        return report, updated
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    source_group=parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument('--checkpoint',type=Path)
    source_group.add_argument('--prepared',type=Path)
    parser.add_argument('--workbook',type=Path,required=True)
    parser.add_argument('--sectors',nargs='+',required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--trade-audit',type=Path,required=True)
    parser.add_argument('--policy',type=Path,required=True)
    args=parser.parse_args()
    reconcile(args.checkpoint,args.workbook,args.sectors,args.output,args.trade_audit,args.policy,prepared=args.prepared)
