"""Native output estimates, final-geography budgets and bounded trade fitting."""
from collections import defaultdict
import math

import numpy as np
import pandas as pd
from scipy.optimize import lsq_linear

from database_disaggregation.core.parent_budgets import ATOL, RTOL


def resolve_parents(policy, targets, registry, native, audit):
    codes = set(targets.master['Sector'])
    if codes-policy['sectors'].keys() or (policy.get('require_all_sectors') and codes!=policy['sectors'].keys()):
        raise ValueError('Inventory sector identities do not match the explicit cleaning policy.')
    parents, old = {}, {}
    for sector in sorted(codes):
        declared = targets.master.loc[targets.master.Sector.eq(sector),'Parent Sector'].dropna().unique()
        if len(declared)!=1:
            raise ValueError(f'{sector}: ambiguous source parent.')
        old[sector] = declared[0]
        record = policy['sectors'][sector]
        if declared[0] != record['declared_parent']:
            raise ValueError(f'{sector}: source parent changed; revise the versioned cleaning policy.')
        resolution = registry.parent(sector, scope=record.get('scope')) if sector in registry.sectors else {'parent':None,'status':'unreviewed'}
        parents[sector] = resolution.get('parent') or declared[0]
        if parents[sector] not in native.sectors:
            raise ValueError(f'{sector}: parent {parents[sector]} not in native baseline.')
        audit.record('working_classification',kind='identity',sector=sector,before=declared[0],
            after=parents[sector],scope=record.get('scope'),classification_status=resolution['status'],
            assumption='Selected reviewed/scope parent; otherwise explicit inherited working classification')
    return parents, old


def prepare_outputs(policy, sources, native, geography, targets, parents, old_parents, audit):
    legacy = {(r.Sector,r.Region):float(r.Quantity) for r in targets.output.itertuples()}
    values, confidence = {}, {}
    for sector,parent in parents.items():
        observations = sources.observations(sector,parent)
        direct = {o['members'][0]:o for o in observations if o['kind']=='direct'}
        if len(direct)!=sum(o['kind']=='direct' for o in observations):
            raise ValueError(f'{sector}: repeated direct country observation under different identifiers.')
        parent_x = {r:max(0.,float(native.budgets.output.loc[(r,parent)])) for r in native.regions}
        reference = [o for o in observations if len(o['members'])==1]
        def share(members):
            known = [o for o in reference if o['members'][0] in members]
            denom = sum(parent_x[o['members'][0]] for o in known)
            if denom>0:
                return min(1.,sum(o['value'] for o in known)/denom)
            return None
        global_share = share(native.regions)
        if global_share is None and observations:
            broad = max(observations,key=lambda o:len(o['members']))
            denominator = sum(parent_x[r] for r in broad['members'])
            global_share = min(1.,broad['value']/denominator) if denominator>0 else 0.
        if global_share is None:
            known = [r for r in native.regions if (sector,r) in legacy]
            denominator = sum(max(0.,float(native.budgets.output.loc[(r,old_parents[sector])])) for r in known)
            global_share = min(1.,sum(legacy[(sector,r)] for r in known)/denominator) if denominator>0 else 0.
        seed = {}
        for group in geography.regions:
            members = [r for r in native.regions if geography.mapping[r]==group]
            local_share = share(members)
            ratio = global_share if local_share is None else local_share
            for region in members:
                if region in direct:
                    seed[region] = direct[region]['value']
                    confidence[(sector,region)] = direct[region]['confidence']
                else:
                    seed[region] = ratio*parent_x[region]
                    confidence[(sector,region)] = 0.1
                    audit.record('missing_output_parent_share',kind='output',sector=sector,region=region,
                        before=legacy.get((sector,region)),after=seed[region],share=ratio,
                        donor_group=group if local_share is not None else 'GLOBAL',confidence=0.1,
                        assumption='Transfer child/parent share; all-missing case uses historical global share, including a zero prior')
        cluster_rows = [o for o in observations if o['kind']=='cluster']
        if cluster_rows:
            configured = policy['geography'].get('cluster_modes',{}).get(sector,{})
            explicit = {r for r,o in direct.items() if o['value']>0}
            explicit |= set().union(*(set(o['members']) for o in cluster_rows
                                     if set(o['members'])!=set(native.regions)))
            prepared=[]
            for observation in observations:
                observation = dict(observation)
                override = configured.get(observation['identifier'],{})
                members = set(observation['members'])-set(override.get('exclude',[]))
                if override.get('mode')=='residual':
                    members -= explicit
                observation['members'] = sorted(members)
                observation['override'] = override
                prepared.append(observation)
            available = [r for r in native.regions if parent_x[r]>0]
            scales = np.array([max(parent_x[r],1e-6) for r in available])
            a,b = [],[]
            for o in prepared:
                cap = sum(parent_x[r] for r in o['members'])
                denominator = max(abs(o['value']),0.01*cap,1e-6)
                weight_key = 'direct_weight' if o['kind']=='direct' else 'world_weight' if set(o['members'])==set(native.regions) else 'cluster_weight'
                weight = float(o['override'].get('weight',policy['geography'][weight_key]))
                weight *= o['confidence']*(0.1 if o['value']==0 and o['kind']=='direct' else 1.)
                a.append([math.sqrt(weight)*scales[i]/denominator if r in o['members'] else 0.
                          for i,r in enumerate(available)])
                b.append(math.sqrt(weight)*o['value']/denominator)
            prior_weight = math.sqrt(policy['geography']['prior_weight'])
            for i,r in enumerate(available):
                denominator=max(seed[r],0.01*parent_x[r],1e-6)
                row=np.zeros(len(available));row[i]=prior_weight*scales[i]/denominator
                a.append(row);b.append(prior_weight*seed[r]/denominator)
            fit = lsq_linear(np.asarray(a),np.asarray(b),bounds=(0,np.inf),tol=1e-10,max_iter=1000) if available else None
            if fit is not None and not fit.success:
                raise RuntimeError(f'{sector}: cluster reconciliation failed: {fit.message}')
            for i,r in enumerate(available):
                seed[r] = max(0.,float(fit.x[i]*scales[i]))
            for o in prepared:
                achieved=sum(seed[r] if parent_x[r]>0 else 0. for r in o['members'])
                audit.record('joint_geographic_fit',kind='output_observation',sector=sector,
                    identifier=o['identifier'],members=o['members'],source=o['source'],before=o['value'],after=achieved,
                    residual=achieved-o['value'],semantics=o['override'].get('mode','inclusive'),
                    assumption='Weighted soft totals; contradictory observations remain visible as residuals')
        for region in native.regions:
            value = seed[region] if parent_x[region]>0 else 0.
            if not np.isfinite(value) or value<0:
                raise ValueError(f'Invalid estimated output {sector}/{region}')
            values[(sector,region)] = value
            audit.record('native_output_prior',kind='output',sector=sector,region=region,
                         before=legacy.get((sector,region)),after=value,confidence=confidence[(sector,region)],
                         structural_parent_zero=parent_x[region]==0)
    for group in policy.get('overlap_groups',[]):
        if not set(group['members']) <= parents.keys():
            continue
        for region in native.regions:
            total=values[(group['reference'],region)]
            for sector,weight in zip(group['members'],group['weights']):
                before=values[(sector,region)]
                values[(sector,region)]=total*weight
                confidence[(sector,region)] = min(confidence[(sector,region)],0.2)
                audit.record('shared_observation_allocation',kind='output',sector=sector,region=region,
                    before=before,after=values[(sector,region)],group=group['id'],total=total,weight=weight,
                    assumption=group['assumption'])
    final = {(c,g):sum(values[(c,r)] for r in native.regions if geography.mapping[r]==g)
             for c in parents for g in geography.regions}
    budgets = native.budgets.aggregate(geography)
    children=defaultdict(list)
    for c,p in parents.items():children[p].append(c)
    for parent,codes in children.items():
        for group in geography.regions:
            total=sum(final[(c,group)] for c in codes)
            cap=max(0.,float(budgets.output.loc[(group,parent)]))
            factor=min(1.,cap/total) if total>0 else 1.
            for code in codes:
                before=final[(code,group)]
                final[(code,group)]*=factor
                for r in native.regions:
                    if geography.mapping[r]==group:values[(code,r)]*=factor
                audit.record('joint_parent_output_cap',kind='output',sector=code,region=group,parent=parent,
                    before=before,after=final[(code,group)],factor=factor,parent_capacity=cap,
                    assumption='Common factor preserves relative child composition within the selected parent/region')
    return values, final, confidence


def prepare_trade(policy,sources,native,geography,parents,native_output,final_output,audit):
    selected, labels = {}, {}
    for sector in parents:
        if sector in policy['trade'].get('parent_pattern_only',[]):
            continue
        if policy['sectors'][sector]['output_source']['kind']=='purdue' and sector in sources.domain_sectors:
            selected[sector]=sources.paired_trade.get(sector,{})
            labels[sector]='paired'
        elif any(v>0 for v in sources.customs_trade.get(sector,{}).values()):
            selected[sector]=sources.customs_trade[sector]
            labels[sector]='direct'
        if sector in selected:
            audit.record('trade_source_choice',kind='trade_source',sector=sector,selected=labels[sector],
                source='BLTTRD' if labels[sector]=='paired' else 'NTSCIF',
                positive_routes=sum(v>0 for v in selected[sector].values()),
                assumption='Paired release takes precedence by declared source domain; empty paired tables retain source parameter zeros')
    assigned=set()
    for composite,members in policy['trade'].get('composites',{}).items():
        codes=[c for c in members if c in parents and c not in selected
               and c not in policy['trade'].get('parent_pattern_only',[])]
        if set(codes)&assigned:
            raise ValueError('A missing child is assigned to more than one composite source.')
        if not codes or not any(v>0 for v in sources.customs_trade.get(composite,{}).values()):
            continue
        assigned.update(codes)
        for c in codes:selected[c]={};labels[c]='composite'
        for (origin,destination),value in sources.customs_trade[composite].items():
            if value<=0 or origin==destination:continue
            known=sum(selected[c].get((origin,destination),0.) for c in members if c in selected and c not in codes)
            remaining=max(0.,value-known)
            weight=sum(native_output[(c,origin)] for c in codes)
            for c in codes:
                q=remaining*native_output[(c,origin)]/weight if weight>0 else 0.
                if q:selected[c][(origin,destination)]=q
            audit.record('composite_once',kind='trade_source',composite=composite,origin=origin,destination=destination,
                before=value,after=remaining,direct_member_prior=known,members=codes,
                assumption='Allocate residual composite observation once, using producer output shares; its level remains a weak prior')
    priors=defaultdict(float);kinds={}
    for sector,rows in selected.items():
        for (origin,destination),value in rows.items():
            if origin==destination or value<=0:continue
            a,b=geography.mapping[origin],geography.mapping[destination]
            audit.record('geographic_trade',kind='trade',sector=sector,origin=origin,destination=destination,
                before=value,after=value if a!=b else 0.,selected_origin=a,selected_destination=b,
                source_kind=labels[sector],internalized=a==b)
            if a!=b:
                priors[(sector,a,b)]+=value;kinds[(sector,a,b)]=labels[sector]
    budgets=native.budgets.aggregate(geography)
    for sector,parent in parents.items():
        if sector in selected:continue
        for origin in geography.regions:
            capacity=float(budgets.output.loc[(origin,parent)])
            share=final_output[(sector,origin)]/capacity if capacity>0 else 0.
            for destination in geography.regions:
                if origin==destination:continue
                q=max(0.,float(budgets.trade.loc[(origin,parent),destination]))*share
                if q:
                    priors[(sector,origin,destination)]=q;kinds[(sector,origin,destination)]='imputed'
            audit.record('parent_trade_pattern',kind='trade_source',sector=sector,origin=origin,share=share,
                assumption='Unobserved child inherits parent export propensity and destination pattern')
    return dict(priors),kinds


def reconcile_trade(priors,kinds,parents,outputs,budgets,policy,audit):
    """Independent parent/origin QPs, with all children and destinations together."""
    import cvxpy as cp
    from scipy.sparse import coo_matrix
    groups=defaultdict(list)
    for key,value in priors.items():
        sector,origin,destination=key
        if not np.isfinite(value) or value<0:raise ValueError('Invalid trade prior.')
        if value>0:groups[(parents[sector],origin)].append((key,value))
    result={};solver_records=[]
    for (parent,origin),rows in sorted(groups.items()):
        positive=[]
        for key,value in rows:
            cap=float(budgets.trade.loc[(origin,parent),key[2]])
            if cap<=0 or outputs[(key[0],origin)]<=0:
                result[key]=0.
                audit.record('structural_trade_capacity',kind='trade',sector=key[0],origin=origin,destination=key[2],
                             before=value,after=0.,source_kind=kinds[key])
            else:positive.append((key,value))
        if not positive:continue
        sectors=list(dict.fromkeys(k[0] for k,v in positive));destinations=list(dict.fromkeys(k[2] for k,v in positive))
        si={s:i for i,s in enumerate(sectors)};di={d:i+len(sectors) for i,d in enumerate(destinations)}
        q=np.array([v for _,v in positive]);n=len(q)
        row_idx=[si[k[0]] for k,v in positive]+[di[k[2]] for k,v in positive]
        col_idx=list(range(n))*2
        matrix=coo_matrix((np.r_[q,q],(row_idx,col_idx)),shape=(len(sectors)+len(destinations),n)).tocsr()
        caps=np.array([outputs[(s,origin)] for s in sectors]+[float(budgets.trade.loc[(origin,parent),d]) for d in destinations])
        sums=np.asarray(matrix@np.ones(n)).ravel()
        fractions=np.ones(n);status='already_feasible'
        if (sums>caps+ATOL+RTOL*np.abs(caps)).any():
            scales=np.maximum(np.maximum(sums,caps),1e-6)
            z=cp.Variable(n)
            weights=np.array([policy['trade']['weights'][kinds[k]] for k,v in positive])*q
            weights/=max(float(weights.max()),1e-30)
            problem=cp.Problem(cp.Minimize(cp.sum(cp.multiply(weights,cp.square(z-1)))),
                               [z>=0,z<=1,matrix.multiply(1/scales[:,None])@z<=caps/scales])
            solver_options=policy['trade'].get('solver_parameters',{})
            if policy['trade']['solver']=='CLARABEL' and not solver_options:
                solver_options={'tol_gap_abs':1e-10,'tol_gap_rel':1e-10,'tol_feas':1e-10,'max_iter':500}
            problem.solve(solver=policy['trade']['solver'],**solver_options)
            status=problem.status
            if status not in ('optimal','optimal_inaccurate') or z.value is None or not np.isfinite(z.value).all():
                raise RuntimeError(f'Trade reconciliation failed for {parent}/{origin}: {status}')
            fractions=np.clip(np.asarray(z.value).ravel(),0.,1.)
            raw_residual=np.asarray(matrix@fractions).ravel()-caps
            audit.record('trade_solver_diagnostics',kind='solver',parent=parent,origin=origin,status=status,
                         max_capacity_excess=float(raw_residual.max(initial=0.)),objective=float(problem.value))
            # Downward numerical polishing cannot break any upper-bound constraint.
            for j in range(matrix.shape[0]):
                positions_in_group=matrix.indices[matrix.indptr[j]:matrix.indptr[j+1]]
                total=(matrix.getrow(j)@fractions).item()
                if total>caps[j]:fractions[positions_in_group]*=caps[j]/total
        if (np.asarray(matrix@fractions).ravel()>caps+ATOL+RTOL*np.abs(caps)).any():
            raise RuntimeError('Reconciled trade fails independent capacity checks.')
        solver_records.append({'parent':parent,'origin':origin,'status':status,'variables':n})
        for (key,before),fraction in zip(positive,fractions):
            result[key]=float(before*fraction)
            audit.record('bounded_trade_fit',kind='trade',sector=key[0],origin=origin,destination=key[2],
                         before=before,after=result[key],source_kind=kinds[key],status=status)
    return result,solver_records
