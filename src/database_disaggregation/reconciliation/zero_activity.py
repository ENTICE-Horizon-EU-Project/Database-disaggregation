"""Prepare inactive monetary IOT accounts for modelling through MARIO scenarios.

No disaggregation optimisation is rerun. Positive-output technologies are kept;
inactive technologies are assigned global output-weighted recipes and explicit
regional sourcing. E is carried unchanged and remains pending.
"""
from dataclasses import dataclass, asdict
from pathlib import Path
from io import BytesIO
from zipfile import ZipFile
from hashlib import sha256
import json

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class ActivationPolicy:
    final_demand_usd: float = 10.
    inactive_output_usd: float = 1.
    final_demand_category: str = 'hhd'

    def validate(self):
        if not np.isfinite(self.final_demand_usd) or self.final_demand_usd <= 0:
            raise ValueError('final_demand_usd must be finite and positive.')
        if not np.isfinite(self.inactive_output_usd) or self.inactive_output_usd < 0:
            raise ValueError('inactive_output_usd must be finite and nonnegative.')
        if self.final_demand_usd <= self.inactive_output_usd:
            raise ValueError('Demand epsilon must exceed the inactive-output threshold.')


def _layout(database):
    axis = database.query('X').index
    if not isinstance(axis,pd.MultiIndex) or list(axis.names) != ['Region','Level','Item']:
        raise ValueError('Expected MARIO IOT Region/Level/Item coordinates.')
    regions = list(dict.fromkeys(axis.get_level_values('Region')))
    sectors = list(dict.fromkeys(axis.get_level_values('Item')))
    expected = pd.MultiIndex.from_product([regions,['Sector'],sectors],names=axis.names)
    if not axis.equals(expected):
        raise ValueError('Regularization requires a complete region-major IOT axis.')
    for group in ['Sector','Factor of production']:
        if set(database.units[group].iloc[:,0]) != {'M USD'}:
            raise ValueError('Activation thresholds currently require M USD monetary units.')
    return axis,regions,sectors


def inventory_fallbacks(database_path, sectors, parent_output, *, sector_universe, factors):
    """Read exact accepted inventories only for globally unobserved activities.

    Reference coefficients are averaged using original baseline parent output.
    The complete source inventory retains links to later-added suppliers, unlike
    a step's dynamically aggregated compiled snapshot. No parent recipe is used.
    """
    archive=Path(database_path)/'reproducibility/accepted-history.zip'
    recipes,provenance={},{}
    with ZipFile(archive) as bundle:
        manifest=json.loads(bundle.read('MANIFEST.json'))
        for sector in sectors:
            step=next(row for row in manifest['completed_steps'] if sector in row['sectors'])
            member=step['exact_source'];payload=bundle.read(member);digest=sha256(payload).hexdigest()
            if digest != manifest['files'][member]['archived_sha256']:
                raise ValueError(f'Exact inventory checksum failed: {sector}')
            a=np.zeros(len(sector_universe));v=np.zeros(len(factors));weight_sum=0.
            with pd.ExcelFile(BytesIO(payload)) as book:
                master=pd.read_excel(book,sheet_name='Master');master=master[master.Sector.eq(sector)]
                for row in master.to_dict('records'):
                    region=str(row['Region']);weight=float(parent_output[sector].get(region,0.))
                    if weight <= 0:continue
                    if row['Unit']!='M USD' or not np.isfinite(row['Quantity']) or row['Quantity']<=0:
                        raise ValueError('Inventory recipe requires a positive M USD reference quantity.')
                    table=pd.read_excel(book,sheet_name=row['Inventory sheet'])
                    for item in table.to_dict('records'):
                        group=item['Item type']
                        if group not in ['Sector','Factor of production']:continue
                        if item['Change type']!='Update' or item['Unit']!='M USD' or not np.isfinite(item['Quantity']):
                            raise ValueError('Unsupported monetary inventory recipe row.')
                        quantity=float(item['Quantity'])/float(row['Quantity'])*weight
                        code=str(item['DB Item'])
                        if group=='Sector':
                            if item['DB Region']!='GLOBAL' or code not in sector_universe:
                                raise ValueError(f'Inventory fallback needs explicit GLOBAL supplier sectors: {code}')
                            a[sector_universe.index(code)]+=quantity
                        else:
                            if code not in factors:raise ValueError(f'Unknown inventory factor: {code}')
                            v[factors.index(code)]+=quantity
                    weight_sum+=weight
            if weight_sum<=0:raise ValueError(f'No reference weights for inventory recipe: {sector}')
            recipes[sector]={'a':a/weight_sum,'v':v/weight_sum}
            provenance[sector]={'source':'exact accepted source inventory','archive':str(archive),
                'member':member,'sha256':digest,'averaging':'original baseline parent production',
                'reference_output_MUSD':weight_sum}
    return recipes,provenance


def activate_inactive_accounts(database, *, parents, baseline=None, recipes=None,
                               policy=ActivationPolicy(), scenario='model_ready'):
    """Clone and finalize a scenario using public MARIO matrix/compute APIs.

    Sourcing priority: the input's use by the local active buyer family; its
    local market; the original input-parent/buyer-parent pattern; the original
    input-parent local market; global production. Existing supplier locations
    are used where available. Globally inactive inputs use their baseline
    parent's producer locations. Every fallback is recorded.
    """
    import mario
    from mario.compute.types import ComputeOptions

    policy.validate();axis,regions,sectors=_layout(database)
    nr,ns=len(regions),len(sectors);pos={s:i for i,s in enumerate(sectors)}
    factors=list(database.query('V').index)
    x=database.query('X').iloc[:,0].to_numpy().copy()
    if not np.isfinite(x).all() or (x<0).any():raise ValueError('Source production must be finite and nonnegative.')
    threshold=policy.inactive_output_usd/1e6;inactive=x<=threshold;donors=(~inactive).reshape(nr,ns)
    quantities=x.reshape(nr,ns);world_output=np.where(donors,quantities,0).sum(axis=0)
    source_z=database.query('Z');source_v=database.query('V');source_y=database.query('Y')
    if not source_z.index.equals(axis) or not source_z.columns.equals(axis):raise ValueError('Z coordinates differ from X.')
    z4=source_z.to_numpy().reshape(nr,ns,nr,ns)
    global_a=np.einsum('aibj,bj->ij',z4,donors.astype(float),optimize=True)
    global_v=(source_v.to_numpy().reshape(len(factors),nr,ns)*donors[None,:,:]).sum(axis=1)
    np.divide(global_a,world_output[None,:],out=global_a,where=world_output[None,:]>0)
    np.divide(global_v,world_output[None,:],out=global_v,where=world_output[None,:]>0)
    recipe_source={s:'output-weighted active producers' for s in sectors}
    for j,sector in enumerate(sectors):
        if world_output[j]>0:continue
        if sector not in (recipes or {}):raise ValueError(f'No global observed recipe for {sector}; provide an explicit inventory recipe.')
        global_a[:,j]=recipes[sector]['a'];global_v[:,j]=recipes[sector]['v'];recipe_source[sector]='exact source inventories, baseline-parent-output weighted'
    if not np.isfinite(global_a).all() or (global_a<0).any() or not np.isfinite(global_v).all():
        raise ValueError('Global monetary recipes must be finite, with nonnegative intermediate coefficients.')
    for f,label in enumerate(factors):
        if str(label).casefold() in {'capital','labor','labour'} and (global_v[f]<0).any():
            raise ValueError(f'Negative {label} in a global recipe; source reconciliation is required.')
    # Build coefficient matrices through MARIO primitives, with harmless scratch
    # denominators for columns that are replaced completely below.
    safe_output=database.query('X').copy();safe_output.iloc[inactive,0]=1.
    a=mario.calc_z(source_z,safe_output);v=mario.calc_v(source_v,safe_output)
    aa=a.to_numpy(copy=True);vv=v.to_numpy(copy=True)
    market=np.einsum('aibj,bj->aib',z4,donors.astype(float),optimize=True)
    for destination in range(nr):
        ycols=source_y.columns.get_level_values('Region')==regions[destination]
        market[:,:,destination]+=np.maximum(source_y.iloc[:,ycols].to_numpy(),0).sum(axis=1).reshape(nr,ns)
    family={s:[pos[t] for t in sectors if parents.get(t,t)==parents.get(s,s)] for s in sectors}
    baseline=baseline or database
    bx=baseline.query('X').iloc[:,0];bz=baseline.query('Z')
    bregions=list(dict.fromkeys(bx.index.get_level_values('Region')));bsectors=list(dict.fromkeys(bx.index.get_level_values(-1)))
    if regions!=bregions:raise ValueError('Baseline regional coordinates differ.')
    br={s:i for i,s in enumerate(bsectors)}
    base4=bz.to_numpy().reshape(nr,len(bsectors),nr,len(bsectors))
    base_market=base4.sum(axis=3)
    baseline_y=baseline.query('Y')
    for destination,region in enumerate(regions):
        cols=baseline_y.columns.get_level_values('Region')==region
        base_market[:,:,destination]+=np.maximum(baseline_y.iloc[:,cols].to_numpy(),0).sum(axis=1).reshape(nr,len(bsectors))
    base_x=bx.to_numpy().reshape(nr,len(bsectors))
    sourcing=[];targets=[]
    for k in np.flatnonzero(inactive):
        destination,j=divmod(int(k),ns);sector=sectors[j];region=regions[destination]
        buyer_parent=parents.get(sector,sector)
        for i in np.flatnonzero(global_a[:,j]>0):
            product=sectors[i];input_parent=parents.get(product,product)
            available=donors[:,i]
            output_weights=np.where(available,quantities[:,i],0.)
            if not available.any():
                if input_parent not in br:raise ValueError(f'No supplier-location reference for {product}.')
                output_weights=np.maximum(base_x[:,br[input_parent]],0.)
                available=output_weights>threshold
            candidates=[('active local buyer family',z4[:,i,destination,:][:,family[sector]][:,donors[destination,family[sector]]].sum(axis=1)),
                        ('local input market',market[:,i,destination])]
            if input_parent in br and buyer_parent in br:
                candidates.append(('baseline parent buyer',base4[:,br[input_parent],destination,br[buyer_parent]]))
            if input_parent in br:candidates.append(('baseline parent market',base_market[:,br[input_parent],destination]))
            candidates.append(('global producer output',output_weights))
            for source,observations in candidates:
                weights=np.where(available,np.maximum(observations,0),0.)
                if weights.sum()>0:break
            else:raise ValueError(f'No sourcing weights for {region}/{sector}/{product}')
            weights=weights/weights.sum();aa[np.arange(nr)*ns+i,k]=global_a[i,j]*weights
            sourcing.append(dict(region=region,sector=sector,input_sector=product,source=source,
                coefficient=float(global_a[i,j]),origins=[{'region':regions[o],'share':float(weights[o])} for o in np.flatnonzero(weights)]))
        # Explicitly clear every old coefficient before installing the recipe.
        rows_for_zero=np.flatnonzero(np.tile(global_a[:,j]==0,nr));aa[rows_for_zero,k]=0.
        vv[:,k]=global_v[:,j]
        targets.append(dict(region=region,sector=sector,source_X_MUSD=float(x[k]),
                            recipe_source=recipe_source[sector],world_donor_output_MUSD=float(world_output[j])))
    a=pd.DataFrame(aa,index=axis,columns=axis);v=pd.DataFrame(vv,index=source_v.index,columns=axis)
    y=source_y.copy();epsilon=policy.final_demand_usd/1e6
    for k in np.flatnonzero(inactive):
        region=axis[k][0];columns=[c for c in y.columns if c[0]==region and c[-1]==policy.final_demand_category]
        if len(columns)!=1:raise ValueError('Final-demand category must occur once per destination region.')
        y.loc[axis[k],columns[0]]+=epsilon
    print(f'Activate {int(inactive.sum())} accounts: clone scenario and install recipes/demand through MARIO.',flush=True)
    database.clone_scenario('baseline',scenario)
    database.update_scenarios(scenario,z=a,v=v,Y=y)
    database.reset_to_coefficients(scenario)
    print('Recalculate production and monetary flows through MARIO sparse direct solve; no inverse or split optimiser.',flush=True)
    database.calc_all(['X','Z','V'],scenario=scenario,compute_options=ComputeOptions(backend_override='sparse_direct'))
    solved_x=database.query('X',scenarios=scenario).iloc[:,0]
    if not np.isfinite(solved_x).all() or (solved_x<0).any():
        raise ValueError('The regularized IO system returned non-finite or negative production; scenario not exported.')
    # Carry E unchanged: its delayed recalculation is a separate task.
    database.update_scenarios(scenario,E=database.query('E').copy())
    database.reset_to_flows(scenario)
    database.calc_all(['X','z','v'],scenario=scenario)
    final_x=database.query('X',scenarios=scenario).iloc[:,0]
    if not (final_x.iloc[np.flatnonzero(inactive)]>threshold).all():
        raise ValueError('Some seeded accounts remain at or below the inactive-output threshold.')
    final_z=database.query('Z',scenarios=scenario);final_v=database.query('V',scenarios=scenario)
    row=final_z.sum(axis=1)+y.sum(axis=1)-final_x
    column=final_z.sum(axis=0)+final_v.sum(axis=0)-final_x
    changes=[]
    for k,key in enumerate(axis):
        changes.append(dict(region=key[0],sector=key[-1],activated=bool(inactive[k]),
            source_X_MUSD=float(x[k]),final_X_MUSD=float(final_x.iloc[k]),difference_USD=float((final_x.iloc[k]-x[k])*1e6)))
    summary=dict(policy=asdict(policy),activated_accounts=int(inactive.sum()),
        exact_zero_accounts=int((x==0).sum()),positive_dust_accounts=int(((x>0)&inactive).sum()),
        total_added_final_demand_USD=float(inactive.sum()*policy.final_demand_usd),
        source_output_MUSD=float(x.sum()),final_output_MUSD=float(final_x.sum()),
        source_value_added_MUSD=float(source_v.to_numpy().sum()),final_value_added_MUSD=float(final_v.to_numpy().sum()),
        source_final_demand_MUSD=float(source_y.to_numpy().sum()),final_final_demand_MUSD=float(y.to_numpy().sum()),
        row_balance_max_USD=float(row.abs().max()*1e6),column_balance_max_USD=float(column.abs().max()*1e6),
        minimum_final_output_USD=float(final_x.min()*1e6),model_rerun=False,io_system_recomputed=True,
        E_recalculated=False,pending_recalculations=['E'],
        observed_recipes_changed=False,source_scenario='baseline',final_scenario=scenario,
        recipe_sources=recipe_source)
    return summary,pd.DataFrame(changes),targets,sourcing
