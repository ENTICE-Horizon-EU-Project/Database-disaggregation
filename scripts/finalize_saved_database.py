"""Create a separate modelling scenario from a saved disaggregated database."""
import argparse
from collections import Counter
from datetime import datetime,timezone
import gc
import json
import os
from pathlib import Path
import shutil
import time

import numpy as np
import pandas as pd

from database_disaggregation.core.benchmark import fingerprints,sha256
from database_disaggregation.core.residual_labels import load_checkpoint_with_codes
from database_disaggregation.reconciliation.zero_activity import ActivationPolicy,activate_inactive_accounts,inventory_fallbacks


def finalize(database,output,*,baseline,policy):
    import mario
    database,output,baseline=map(lambda p:Path(p).resolve(),[database,output,baseline])
    if output.exists():raise FileExistsError('Choose a new output directory; original databases are never overwritten.')
    if output.is_relative_to(database/'flows'):raise ValueError('Output cannot be inside source flows.')
    before=fingerprints(database);base_before=fingerprints(baseline)
    tick=time.monotonic();source_state=json.loads((database/'state.json').read_text())
    print('Load the accepted source checkpoint through MARIO.',flush=True)
    db=load_checkpoint_with_codes(database)
    bdb=mario.parse_from_parquet(str(baseline/'flows'),table='IOT',mode='flows')
    # Use the recorded baseline production vector for reference weights.
    bdb.set_block('X',pd.read_parquet(baseline/'flows/X.parquet').reindex(bdb.Z.index),scenario='baseline')
    parents={s:source_state['sector_parents'][s] for s in source_state['completed_sectors']}
    x=db.query('X').iloc[:,0];sectors=list(dict.fromkeys(x.index.get_level_values(-1)));factors=list(db.query('V').index)
    totals=x.where(x>policy.inactive_output_usd/1e6,0).groupby(level=-1).sum()
    missing=[s for s in sectors if totals[s]==0]
    weights={s:bdb.query('X').xs(parents.get(s,s),level='Item').iloc[:,0].droplevel('Level').to_dict() for s in missing}
    print('Read exact inventory recipes for globally inactive sectors: '+', '.join(missing),flush=True)
    recipes,recipe_evidence=inventory_fallbacks(database,missing,weights,sector_universe=sectors,factors=factors)
    summary,changes,targets,sourcing=activate_inactive_accounts(db,parents=parents,baseline=bdb,recipes=recipes,policy=policy)
    scenario=summary['final_scenario'];nr=len(db.get_index('Region'));ns=len(sectors)
    for name in ['Z','V','z','v','X','Y']:
        frame=db.query(name,scenarios=scenario)
        if not np.isfinite(frame.to_numpy()).all():raise ValueError(f'Non-finite finalized {name}.')
    for name in ['Z','z']:
        if (db.query(name,scenarios=scenario).to_numpy()<0).any():raise ValueError(f'Negative finalized {name}.')
    nonnegative=[f for f in factors if str(f).casefold() in {'capital','labor','labour'}]
    if (db.query('V',scenarios=scenario).loc[nonnegative].to_numpy()<0).any():raise ValueError('Negative Capital/Labor after finalization.')
    def deliveries(s):
        z=db.query('Z',scenarios=s).to_numpy().reshape(nr,ns,nr,ns).sum(axis=3)
        y=db.query('Y',scenarios=s)
        for j,r in enumerate(db.get_index('Region')):
            z[:,:,j]+=y.loc[:,y.columns.get_level_values('Region')==r].to_numpy().sum(axis=1).reshape(nr,ns)
        return z
    delta=deliveries(scenario)-deliveries('baseline');foreign=np.ones((nr,ns,nr),dtype=bool)
    for i in range(nr):foreign[i,:,i]=False
    summary.update(created_at=datetime.now(timezone.utc).isoformat(),format='entice-finalization-v1',regions=nr,sectors=ns,
        added_sectors=len(parents),source_database=str(database),source_baseline=str(baseline),
        source_sha256=before,baseline_sha256=base_before,
        foreign_trade_max_change_USD=float(np.abs(delta[foreign]).max()*1e6),
        foreign_trade_absolute_change_USD=float(np.abs(delta[foreign]).sum()*1e6),
        sourcing_rule_counts=dict(Counter(r['source'] for r in sourcing)),inventory_recipe_evidence=recipe_evidence,
        source_unchanged=fingerprints(database)==before and fingerprints(baseline)==base_before,
        elapsed_seconds=time.monotonic()-tick)
    if not summary['source_unchanged']:raise ValueError('A source database changed during finalization.')
    output.mkdir(parents=True)
    try:
        print('Export flows and coefficients through MARIO.',flush=True)
        db.add_note('Inactive accounts activated with explicit demand epsilon and regionalized global recipes; E remains deferred.')
        db.to_parquet(path=output,flows=True,coefficients=True,scenario=scenario,include_meta=True)
        # E is intentionally not recalculated or silently filled with zeros.
        shutil.copy2(database/'flows/E.parquet',output/'flows/E.parquet')
        (output/'coefficients/e.parquet').unlink(missing_ok=True)
        changes.to_csv(output/'production-changes.csv',index=False)
        pd.DataFrame(targets).to_parquet(output/'activated-accounts.parquet',index=False)
        pd.DataFrame(sourcing).to_parquet(output/'regional-sourcing.parquet',index=False)
        diagnostics=output/'diagnostics/provenance';diagnostics.mkdir(parents=True)
        for name in ['region-names.csv','geography.json','additional-sectors-13.json']:
            src=database/'diagnostics/provenance'/name
            if src.exists():shutil.copy2(src,diagnostics/name)
        shutil.copy2(Path(__file__),diagnostics/'finalize_saved_database.py')
        from database_disaggregation.reconciliation import zero_activity
        shutil.copy2(zero_activity.__file__,diagnostics/'zero_activity.py')
        (output/'activation-policy.json').write_text(json.dumps(summary['policy'],indent=2)+'\n')
        (output/'finalization-report.json').write_text(json.dumps(summary,indent=2,allow_nan=False)+'\n')
        keep=['sector_parents','completed_sectors','planned_sectors','residual_index_renames','split_model_options','tolerances','numerical_validation_policy']
        state={k:source_state[k] for k in keep if k in source_state}
        state.update(format='entice-finalized-database-v1',status='complete',database_directory='.',pending_recalculations=['E'],
            source_database_directory=os.path.relpath(database,output),source_sha256=before,
            finalization=dict(policy=summary['policy'],report='finalization-report.json',source='accepted disaggregation checkpoint'),
            coefficient_analysis_validated=False,files={str(f.relative_to(output)):sha256(f) for directory in ['flows','coefficients'] for f in sorted((output/directory).glob('*.parquet'))})
        (output/'state.json').write_text(json.dumps(state,indent=2)+'\n')
        run=dict(format='entice-finalized-run-v1',status='finalized_pending_economic_review',regions=nr,total_database_sectors=ns,
            disaggregated_sectors=len(parents),source_database_directory=os.path.relpath(database,output),model_rerun=False,
            io_system_recomputed=True,pending_recalculations=['E'],structural_zero_accounts_resolved=True,
            historical_constraints='Original split targets are reference observations, not constraints of IO finalization.')
        (output/'run.json').write_text(json.dumps(run,indent=2)+'\n')
        va_delta=(summary['final_value_added_MUSD']-summary['source_value_added_MUSD'])*1e6
        x_delta=(summary['final_output_MUSD']-summary['source_output_MUSD'])*1e6
        text=f'''# Finalized modelling database

{nr} regions, {ns} total sectors, {len(parents)} added activities. This is a separate
scenario derived from the accepted disaggregation, not a new optimisation run.
The source database remains unchanged.

## Activation

- {summary['activated_accounts']} accounts activated: {summary['exact_zero_accounts']} exact zeros and {summary['positive_dust_accounts']} positive values at or below {policy.inactive_output_usd:g} USD.
- Added domestic household demand: {policy.final_demand_usd:g} USD per account; {summary['total_added_final_demand_USD']:,.2f} USD in total.
- Existing productive technologies are retained. Inactive technologies use output-weighted global sector recipes, including signed value added. NMC and SDH use their exact original inventory recipes because there are no active observed producers; reference weights are baseline parent production.
- Sourcing follows active local buyer-family purchases, the input's local market, baseline parent buyer/market patterns, then global producer output. Origins with no active production are excluded where existing producers are available. Every choice and origin weight is recorded in `regional-sourcing.parquet`.
- MARIO APIs used: `clone_scenario`, `update_scenarios`, `reset_to_coefficients`, `calc_all` with sparse direct solve, `reset_to_flows`, `to_parquet`. No explicit Leontief inverse or CVXLab change.

## Measured effects

- Gross output change: {x_delta:,.2f} USD.
- Total value-added change: {va_delta:,.2f} USD.
- Minimum final production: {summary['minimum_final_output_USD']:,.6g} USD.
- Maximum row-accounting residual: {summary['row_balance_max_USD']:,.6g} USD.
- Maximum column-accounting residual: {summary['column_balance_max_USD']:,.6g} USD. Original inherited column imbalances are not forcibly rebalanced.
- Largest foreign bilateral trade change: {summary['foreign_trade_max_change_USD']:,.6g} USD.

Adding demand and recomputing quantities changes production and trade. Original
split targets remain historical references, not hard constraints on this scenario.
`production-changes.csv` and `finalization-report.json` retain the comparisons.

## Files and loading

`flows/` contains the monetary model and the unchanged, deferred E source file.
`coefficients/` contains finite `z` and `v`, plus Y/EY/VY and units. Environmental
coefficients e are omitted because E recalculation is pending.

```python
import mario
db = mario.parse_from_parquet('PATH/flows', table='IOT', mode='flows')
z = db.z
v = db.v
```

`state.json` identifies a finalized database, not a resumable sector-step checkpoint.
Use the original accepted checkpoint for resuming the disaggregation. Economic
validation and environmental recalculation remain pending; finite coefficients
and a successful IO solve do not establish the economic plausibility of recipes.
'''
        (output/'README.md').write_text(text)
    except Exception:
        (output/'INCOMPLETE.txt').write_text('Finalization export did not complete; inspect the task log. Source data are unchanged.\n')
        raise
    print(json.dumps({k:summary[k] for k in ['activated_accounts','exact_zero_accounts','positive_dust_accounts','minimum_final_output_USD','row_balance_max_USD','column_balance_max_USD','source_value_added_MUSD','final_value_added_MUSD','foreign_trade_max_change_USD','elapsed_seconds']},indent=2),flush=True)
    print('Saved '+str(output),flush=True)
    return summary


if __name__=='__main__':
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--database',type=Path,required=True)
    cli.add_argument('--output',type=Path,required=True)
    cli.add_argument('--baseline',type=Path,required=True)
    cli.add_argument('--policy',type=Path,required=True)
    args=cli.parse_args();policy=ActivationPolicy(**json.loads(args.policy.read_text()))
    finalize(args.database,args.output,baseline=args.baseline,policy=policy)
