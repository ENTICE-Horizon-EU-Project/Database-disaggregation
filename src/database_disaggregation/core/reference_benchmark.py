"""Internal, read-only cross-database profiles. No optimisation or balancing.

Canonical IOT orientation is supplying rows / purchasing columns, including
EMERGING's transposed MATLAB storage. GLORIA uses Zp = U diag(Xa)^-1 S
(industry technology), evaluated as aggregate sparse products in two CSV passes.
"""
from __future__ import annotations
import io
import json
import time
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import sparse

from .benchmark import Flows, fingerprints, sha256, sector_axis

GROUPS=['Agriculture','Mining','Manufacturing','Energy','Water and waste','Construction','Trade','Transport','Other services','Mixed / unmapped']

def group_for(classes, nodes):
    sections={nodes[c]['section'] for c in classes if c in nodes}
    def group(s):
        if s in 'ABCDEFGH':return 'ABCDEFGH'.index(s)
        return 8
    groups={group(s) for s in sections}
    return next(iter(groups)) if len(groups)==1 else 9


def profiles_from_iot(x, regions, sector_codes, target_regions, supplier_groups, z_batches, y_batches):
    """Reduce canonical source blocks once; aggregate geography before ratios.

    z/y_batches yield (first supplying row, dense rows). All destinations and
    origins remain present, including unmatched source ROW regions.
    """
    ns=len(sector_codes); nr=len(regions); n=ns*nr
    if np.shape(x)!=(n,):raise ValueError('Source X dimensions disagree with native sets')
    x=np.asarray(x,dtype=float)
    masks={r:np.repeat(np.isin(regions,codes),ns) for r,codes in target_regions.items()}
    for r,codes in target_regions.items():
        if not codes or not set(codes)<=set(regions):raise ValueError(f'Unknown source geography: {r}')
    owners = [code for codes in target_regions.values() for code in codes]
    if len(set(owners)) != len(owners):
        raise ValueError('Overlapping target geographies would double count domestic flows')
    inp=np.zeros(n); imported=np.zeros(n); outgoing=np.zeros(n); exports_z=np.zeros(n)
    group_in=np.zeros((n,len(GROUPS))); domestic_in=np.zeros(n)
    sg=np.tile(supplier_groups,nr); rows_seen=0; negative_z=0; min_z=0.
    for start,a in z_batches:
        if start!=rows_seen or a.shape[1]!=n or not np.isfinite(a).all():raise ValueError('Invalid canonical Z block')
        end=start+len(a);rows_seen=end
        negative_z+=int((a < -1e-9).sum());min_z=min(min_z,float(a.min()))
        inp+=a.sum(axis=0);outgoing[start:end]=a.sum(axis=1)
        for k in range(len(GROUPS)):
            take=sg[start:end]==k
            if take.any():group_in[:,k]+=a[take].sum(axis=0)
        for mask in masks.values():
            local=mask[start:end]
            if local.any():
                domestic=a[np.ix_(local,mask)]
                domestic_in[mask]+=domestic.sum(axis=0)
                pos=np.flatnonzero(local)+start
                exports_z[pos]=outgoing[pos]-domestic.sum(axis=1)
    if rows_seen!=n:raise ValueError('Incomplete Z source')
    imported=inp-domestic_in
    yy=np.zeros(n); ey=np.zeros(n); rows_seen=0
    fd_count=None
    for start,a in y_batches:
        if a.shape[1]%nr or start!=rows_seen or not np.isfinite(a).all():raise ValueError('Invalid canonical Y block')
        fd_count=a.shape[1]//nr;end=start+len(a);rows_seen=end;yy[start:end]=a.sum(axis=1)
        for r,codes in target_regions.items():
            mask=masks[r];local=mask[start:end]
            if local.any():
                dest=np.repeat(np.isin(regions,codes),fd_count)
                pos=np.flatnonzero(local)+start
                ey[pos]=yy[pos]-a[np.ix_(local,dest)].sum(axis=1)
    if rows_seen!=n:raise ValueError('Incomplete Y source')
    result={}
    for name,mask in masks.items():
        def agg(v):return v[mask].reshape(-1,ns,*v.shape[1:]).sum(axis=0)
        result[name]=dict(output=agg(x).tolist(),intermediate_inputs=agg(inp).tolist(),imported_inputs=agg(imported).tolist(),net_final_demand=agg(yy).tolist(),exports=agg(exports_z+ey).tolist(),input_groups=agg(group_in).tolist(),deliveries=agg(outgoing+yy).tolist())
    return result,dict(canonical_rows=n,negative_z_cells=negative_z,minimum_z=min_z,source_output_demand_relative_L1=float(np.abs(outgoing+yy-x).sum()/max(1.,np.abs(x).sum())),native_final_demand_categories=fd_count)


def exio_profiles(path, native, geography, groups):
    with zipfile.ZipFile(path) as z:
        x=pd.read_csv(z.open('x.txt'),sep='\t',index_col=[0,1])
        axis=x.index;regions=list(dict.fromkeys(axis.get_level_values(0)));names=list(dict.fromkeys(axis.get_level_values(1)))
        by_name={r['native_name']:r['native_code'] for r in native}
        if set(names)!=set(by_name) or len(x)!=len(regions)*len(names):raise ValueError('EXIO native sector inventory changed')
        codes=[by_name[n] for n in names]; supplier_groups=[groups[c] for c in codes]
        unit=pd.read_csv(z.open('unit.txt'),sep='\t')
        if set(unit['unit'])!={'M.EUR'}:raise ValueError('EXIO currency changed')
        def batches(member):
            offset=0
            with z.open(member) as stream:
                header=pd.read_csv(stream,sep='\t',header=[0,1],index_col=[0,1],nrows=0)
            expected_cols=header.columns
            expected_rows=axis
            with z.open(member) as stream:
                for frame in pd.read_csv(stream,sep='\t',header=[0,1],index_col=[0,1],chunksize=128):
                    if not frame.index.equals(expected_rows[offset:offset+len(frame)]) or not frame.columns.equals(expected_cols):raise ValueError('EXIO source axes changed')
                    if member=='Z.txt' and not frame.columns.equals(axis):raise ValueError('EXIO Z column orientation changed')
                    if member=='Y.txt' and list(dict.fromkeys(frame.columns.get_level_values(0)))!=regions:raise ValueError('EXIO Y geography changed')
                    yield offset,frame.to_numpy(dtype=float);offset+=len(frame)
        result,audit=profiles_from_iot(x.iloc[:,0].to_numpy(),regions,codes,geography,supplier_groups,batches('Z.txt'),batches('Y.txt'))
    return dict(regions=result,sector_codes=codes,audit=audit,native_unit='M EUR',representation='industry IOT, supplying rows / purchasing columns')


def emerging_profiles(path,native,geography,groups):
    import h5py
    with h5py.File(path,'r') as h:
        def labels(key):return [''.join(chr(int(v)) for v in h[r][()].ravel()).strip() for r in h[key][()].ravel()]
        regions=labels('country_list');names=labels('sector_list')
        # Serial identifiers are in the raw labels: mapping inventories retain
        # descriptors only. Compare position and name after removing that prefix.
        import re
        names=[re.sub(r'^\s*\d+[.\s_-]*','',n).strip() for n in names]
        expected={r['native_name']:r['native_code'] for r in native}
        # Some raw labels have an underscore between serial and descriptor.
        normalized=lambda s:' '.join(s.replace('_',' ').split()).casefold()
        by_name={normalized(k):v for k,v in expected.items()}
        if {normalized(s) for s in names}!=set(by_name):raise ValueError('EMERGING native sector descriptors changed')
        codes=[by_name[normalized(s)] for s in names]
        ns=len(codes);n=len(regions)*ns
        if h['z'].shape!=(n,n) or h['f'].shape[1]!=n:raise ValueError('EMERGING source axes changed')
        def batches(key):
            # MATLAB z is transposed; HDF5 chunks are column-oriented. Read each
            # whole supplying-column strip once, then expose canonical rows.
            for start in range(0,n,64):yield start,np.asarray(h[key][:,start:start+64],dtype=float).T
        result,audit=profiles_from_iot(np.asarray(h['X'][()]).ravel(),regions,codes,geography,[groups[c] for c in codes],batches('z'),batches('f'))
    return dict(regions=result,sector_codes=codes,audit=audit,native_unit='M USD',representation='product/service IOT; canonical Z = MATLAB z transpose')


def gloria_profiles(path,native,geography,groups,*,mario_source):
    """Industry-technology product IOT profiles; no dense global IOT is built."""
    import sys
    sys.path.insert(0,str(mario_source))
    from mario.parsers.gloria import detect_gloria_layout, _activity_positions, _commodity_positions
    layout,meta=detect_gloria_layout(path,year=2023)
    ns=len(meta.sector_names); nr=len(meta.region_codes);na=nr*ns
    if ns!=120 or layout.release!='060':raise ValueError('Unexpected GLORIA layout')
    by_code={r['native_code']:r['native_name'] for r in native}
    if [by_code[str(i+1)] for i in range(ns)]!=list(meta.sector_names):raise ValueError('GLORIA sector inventory changed')
    names=list(geography);nt=len(names);codes=list(meta.region_codes)
    rp={name:np.flatnonzero(np.isin(codes,geography[name])) for name in names}
    for name,pos in rp.items():
        if len(pos)!=len(geography[name]):raise ValueError('GLORIA geography changed')
    acts=_activity_positions(list(range(nr)),ns);comms=_commodity_positions(list(range(nr)),ns)
    xa=np.zeros(na);supply_rows=[];supply_cols=[];supply_values=[]
    geo_region=np.full(nr,-1,dtype=int)
    for i,name in enumerate(names):geo_region[rp[name]]=i
    with zipfile.ZipFile(path) as z:
        t=layout.T_path.member;y=layout.Y_path.member
        if t is None or y is None:raise ValueError('Expected zipped GLORIA source')
        def rows(member):
            with z.open(member) as stream:
                for k,line in enumerate(stream):
                    a=np.fromstring(line.decode('ascii'),sep=',',dtype=float)
                    width=2*na if member==t else nr*len(meta.final_demand_names)
                    if len(a)!=width or not np.isfinite(a).all():raise ValueError('GLORIA source width or finite-value check failed')
                    yield k,a
                    if k and k%8000==0:print('GLORIA',member.split('_')[3],k,'rows',flush=True)
                if k+1!=2*na:raise ValueError('Incomplete GLORIA source rows')
        unwanted=0.
        print('GLORIA supply pass',flush=True)
        for k,a in rows(t):
            region=k//(2*ns);sec=k%ns
            if k%(2*ns)<ns:
                ar=region*ns+sec; xa[ar]=a[comms].sum();unwanted+=np.abs(a[acts]).sum()
                for gi,name in enumerate(names):
                    block=a[np.concatenate([np.arange(r*2*ns+ns,r*2*ns+2*ns) for r in rp[name]])].reshape(-1,ns).sum(axis=0)
                    nz=np.flatnonzero(block)
                    supply_rows.extend([ar]*len(nz));supply_cols.extend((gi*ns+nz).tolist());supply_values.extend(block[nz].tolist())
            else:unwanted+=np.abs(a[comms]).sum()
        if unwanted>1e-6:raise ValueError(f'GLORIA T has unsupported same-type flows: {unwanted}')
        numerator=sparse.csr_matrix((supply_values,(supply_rows,supply_cols)),shape=(na,nt*ns))
        if np.any(xa<0):raise ValueError('GLORIA negative activity production')
        inv=np.divide(1.,xa,out=np.zeros_like(xa),where=xa>0)
        weights=(sparse.diags(inv)@numerator).T.tocsr()
        xc=np.asarray(numerator.sum(axis=0)).ravel().reshape(nt,ns)
        inp=np.zeros((nt,ns)); imp=np.zeros_like(inp);net_y=np.zeros_like(inp);out=np.zeros_like(inp);exp=np.zeros_like(inp)
        gi_values=np.zeros((nt,ns,len(GROUPS)));zero_activity_input=0.;negative_u=0
        group_vector=np.array([groups[str(i+1)] for i in range(ns)])
        print('GLORIA use pass',flush=True)
        for k,a in rows(t):
            if k%(2*ns)<ns:continue
            region=k//(2*ns);sec=k%ns;u=a[acts];source_geo=geo_region[region]
            incoming=(weights@u).reshape(nt,ns);inp+=incoming
            gi_values[:,:,group_vector[sec]]+=incoming
            for i in range(nt):
                if i!=source_geo:imp[i]+=incoming[i]
            zero_activity_input+=np.abs(u[xa==0]).sum();negative_u+=int((u < -1e-9).sum())
            if source_geo>=0:
                out[source_geo,sec]+=u.sum()
                exp[source_geo,sec]+=u.sum()-incoming[source_geo].sum()
        ya_abs=0.;nf=len(meta.final_demand_names)
        print('GLORIA final demand',flush=True)
        for k,a in rows(y):
            if k%(2*ns)<ns:ya_abs+=np.abs(a).sum();continue
            region=k//(2*ns);source_geo=geo_region[region]
            if source_geo<0:continue
            sec=k%ns;net_y[source_geo,sec]+=a.sum()
            exp[source_geo,sec]+=a.sum()-a.reshape(nr,nf)[rp[names[source_geo]]].sum()
        if ya_abs>1e-6:raise ValueError('Non-zero GLORIA activity final demand requires a separate transformation')
    result={name:dict(output=xc[i].tolist(),intermediate_inputs=inp[i].tolist(),imported_inputs=imp[i].tolist(),net_final_demand=net_y[i].tolist(),exports=exp[i].tolist(),input_groups=gi_values[i].tolist(),deliveries=(out[i]+net_y[i]).tolist()) for i,name in enumerate(names)}
    return dict(regions=result,sector_codes=list(map(str,range(1,ns+1))),native_unit='000 USD',representation='product IOT derived from native MR-SUT, industry technology: Zp = U diag(Xa)^-1 S',audit=dict(native_activity_count=na,selected_commodity_profiles=nt*ns,zero_output_activity_gross_inputs=zero_activity_input,unsupported_same_type_T_absolute=unwanted,activity_final_demand_absolute=ya_abs,negative_u_cells=negative_u,supply_weights_nnz=weights.nnz,source_output_demand_relative_L1_selected=float(np.abs(out+net_y-xc).sum()/max(1.,np.abs(xc).sum()))))


def money_metrics(data,indices,scale=1.):
    indices=list(indices)
    def total(k):return float(np.asarray(data[k])[indices].sum()*scale)
    x=total('output');inp=total('intermediate_inputs');imports=total('imported_inputs');y=total('net_final_demand');exports=total('exports')
    def ratio(a,b):return a/b if b>1e-6 else None
    groups=np.asarray(data['input_groups'])[indices].sum(axis=0)*scale
    return dict(output=x,intermediate_inputs=inp,imported_inputs=imports,net_final_demand=y,exports=exports,intermediate_input_ratio=ratio(inp,x),imported_input_share=ratio(imports,inp),final_demand_ratio=ratio(y,x),export_ratio=ratio(exports,x),input_coefficients=[ratio(float(v),x) for v in groups],mixed_input_share=ratio(float(groups[-1]),inp),output_demand_residual=total('deliveries')-x)


def saved_profiles(root,group_by_sector):
    db=Flows.read(root);z=db['Z'];y=db['Y'];x=db['X'].iloc[:,0]
    regions=list(dict.fromkeys(z.index.get_level_values(0)));sectors=list(dict.fromkeys(z.index.get_level_values(1)))
    # Axes need not be sorted region-major; reorder explicitly for the reducer.
    axis=pd.MultiIndex.from_product([regions,sectors],names=z.index.names)
    za=z.reindex(index=axis,columns=axis).to_numpy();ya=y.reindex(index=axis)
    yreg=ya.columns.get_level_values('Region');cols=np.concatenate([np.flatnonzero(yreg==r) for r in regions])
    result,audit=profiles_from_iot(x.reindex(axis).to_numpy(),regions,sectors,{r:[r] for r in regions},[group_by_sector[s] for s in sectors],[(0,za)],[(0,ya.iloc[:,cols].to_numpy())])
    return dict(regions=result,sector_codes=sectors,audit=audit),db.hashes


def atomic_json(path,value):
    import os,tempfile
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w',dir=path.parent,delete=False) as f:
        temp=Path(f.name);json.dump(value,f,allow_nan=False,separators=(',',':'))
    os.replace(temp,path)


def build_comparisons(report,mapping,baskets,*,reference_root,cache,mario_source,engine_identity,geography=None,cache_only=False,cache_provenance=None):
    from .reference_mapping import footprint_from_explorer
    native={family:[r for r in mapping['native_sectors'] if r['dataset']==dataset] for family,dataset in {'EXIOBASE':'EXIOBASE_3.11.2_ixi_2023','EMERGING':'EMERGING_2.2_2023','GLORIA':'GLORIA_060_activity_2023'}.items()}
    nodes=mapping['nace2_nodes']
    groups={f:{r['native_code']:group_for(r['nace2_classes'],nodes) for r in rows} for f,rows in native.items()}
    # GTAP parents use the reviewed producing-activity routes already in MARIO.
    gtap_file=Path(mario_source)/'doc/classifications/sectoral/nxbase-gtap.json'
    gtap=json.loads(gtap_file.read_text());gtap_groups={}
    for item in gtap['items']:
        if item['namespace']!='GTAP12I':continue
        classes=set()
        for route in item.get('links',{}).values():
            for n in route['nodes']:
                if n[0]=='NACE2' and n[1] in nodes:
                    classes.update(c for c in nodes if c.startswith(n[1]) and len(c)==5)
        gtap_groups[item['code'].upper()]=group_for(classes,nodes)
    base_sectors=sorted({r['sector'] for r in report['baseline_sectors']})
    for s in base_sectors:
        if s not in gtap_groups:
            if s in {'CoalBL','GasBL','GasP','HydroBL','HydroP','NuclearBL','OilBL','OilP','OtherBL','SolarP','TnD','WindBL'}:gtap_groups[s]=3
            else:raise ValueError(f'Unmapped original GTAP sector: {s}')
    parents={r['sector']:r['parent'] for r in report['sectors'] if r['is_child']}
    child_groups={r['entice_code']:group_for(r['nace2_classes'],nodes) for r in mapping['entice_sectors']}
    # New activities outside the frozen mapping package remain explicitly mixed.
    unmapped_children = sorted(set(parents) - set(child_groups))
    final_groups={r['sector']:child_groups.get(r['sector'],9) if r['is_child'] else gtap_groups[r['sector']] for r in report['sectors']}
    geography = geography if geography is not None else mapping['entice13_compatibility']
    if {r['target_region'] for r in geography} != set(report['dimensions']['regions']):
        raise ValueError('Reference geography does not match the saved benchmark regions')
    final,final_hashes=saved_profiles(report['provenance']['database'],final_groups)
    baseline,base_hashes=saved_profiles(report['provenance']['baseline'],gtap_groups)
    if final_hashes!=report['provenance']['database_sha256'] or base_hashes!=report['provenance']['baseline_sha256']:raise ValueError('Saved baseline/final no longer matches the accepted benchmark')
    paths={'EXIOBASE':Path(reference_root)/'EXIOBASE/3.11.2/IOT_2023_ixi.zip','EMERGING':Path(reference_root)/'EMERGING/2.2/EMERGING_V2_2023_m.mat','GLORIA':Path(reference_root)/'GLORIA/060/GLORIA_MRIO_Loop060_part_I_MRIOdatabase/GLORIA_MRIOs_60_2023.zip'}
    rows=[];source_records=[];unavailable_baskets=[]
    for family,path in paths.items():
        geos={r['target_region']:r['native_regions'] for r in geography if r['source_family']==family and r['exact_on_declared_membership'] and r['target_membership_complete']}
        cache_path=Path(cache)/(family.lower()+'-2023-profiles.json')
        cached=json.loads(cache_path.read_text()) if cache_path.exists() else None
        if cache_only:
            cached=verified_profile_cache(cache_path,family=family,recorded=(cache_provenance or {}).get(family),groups=groups[family],geography=geos)
            identity=cached['identity']
            profiles=cached['profiles'];source_hash=cached['source_sha256']
            source_size,source_mtime=identity['size'],identity['mtime_ns']
            print(f'{family}: reuse checksum-verified offline profile cache; native source not reread',flush=True)
        else:
            stat=path.stat();identity=dict(path=str(path),size=stat.st_size,mtime_ns=stat.st_mtime_ns,engine=engine_identity,groups=groups[family],geography=geos)
            if cached and cached.get('identity')==identity:
                profiles=cached['profiles'];source_hash=cached['source_sha256'];print(f'{family}: reuse verified profile cache',flush=True)
            else:
                print(f'{family}: hashing and extracting 2023 native flows',flush=True);start=time.monotonic();source_hash=sha256(path)
                if family=='EXIOBASE':profiles=exio_profiles(path,native[family],geos,groups[family])
                elif family=='EMERGING':profiles=emerging_profiles(path,native[family],geos,groups[family])
                else:profiles=gloria_profiles(path,native[family],geos,groups[family],mario_source=mario_source)
                profiles['extraction_seconds']=time.monotonic()-start
                after=path.stat()
                if after.st_size!=stat.st_size or after.st_mtime_ns!=stat.st_mtime_ns:raise ValueError('Reference source changed during extraction')
                atomic_json(cache_path,dict(identity=identity,source_sha256=source_hash,profiles=profiles))
            source_size,source_mtime=stat.st_size,stat.st_mtime_ns
        if set(profiles['sector_codes'])!={r['native_code'] for r in native[family]}:
            raise ValueError(f'{family}: cached sector universe differs from the audited mapping')
        source_records.append(dict(family=family,year=2023,path=str(path),sha256=source_hash,size=source_size,mtime_ns=source_mtime,profile_sha256=sha256(cache_path),profile_cache=str(cache_path),native_unit=profiles['native_unit'],representation=profiles['representation'],geography=geos,audit=profiles['audit'],extraction_seconds=profiles['extraction_seconds'],cache_only=cache_only,native_source_reverified=False if cache_only else None,extraction_engine_sha256=identity['engine']))
        scale=baskets['currency']['exiobase_EUR_to_USD'] if family=='EXIOBASE' else .001 if family=='GLORIA' else 1.
        for basket in baskets['baskets']:
            if basket['family']!=family:continue
            fsectors,bsectors,missing = basket_sector_selection(basket,final['sector_codes'],baseline['sector_codes'],parents)
            if missing:
                unavailable_baskets.append(dict(family=family,basket=basket['id'],label=basket['label'],missing_entice_children=missing,reason='Activity not separated in this checkpoint; retained in its parent.'))
                continue
            if set(fsectors)-set(final['sector_codes']):raise ValueError('Unknown ENTICE basket child')
            native_names={r['native_code']:r['native_name'] for r in native[family]}
            for c,label in zip(basket['native_codes'],basket['native_names'],strict=True):
                if native_names.get(c)!=label:raise ValueError('Basket expected native descriptor changed')
            fi=[final['sector_codes'].index(s) for s in fsectors];bi=[baseline['sector_codes'].index(s) for s in bsectors];ri=[profiles['sector_codes'].index(s) for s in basket['native_codes']]
            for region in geos:
                rows.append(dict(family=family,region=region,basket=basket['id'],label=basket['label'],nace_reference=basket['nace_reference'],comparison_basis=basket['comparison_basis'],qualification=basket['qualification'],entice_sectors=fsectors,baseline_sectors=bsectors,baseline_scope='same aggregate families' if basket['entice_parents'] or basket['id']=='all' else 'broader original parent; contextual only',native_codes=basket['native_codes'],native_names=basket['native_names'],entice=money_metrics(final['regions'][region],fi),baseline=money_metrics(baseline['regions'][region],bi),reference=money_metrics(profiles['regions'][region],ri,scale)))
    if fingerprints(report['provenance']['database'])!=final_hashes or fingerprints(report['provenance']['baseline'])!=base_hashes:raise ValueError('Saved flows changed during benchmarking')
    return dict(schema_version=1,year=2023,internal_only=True,reference='NACE Rev. 2',input_groups=GROUPS,rows=rows,sources=source_records,gtap_scope_source=dict(path=str(gtap_file),sha256=sha256(gtap_file)),currency=baskets['currency'],geography_exclusions=[r for r in geography if not r['exact_on_declared_membership']],unavailable_baskets=unavailable_baskets,unmapped_input_children=unmapped_children,policy=dict(model_rerun=False,source_data_adjusted=False,scope='Whole native sectors, aggregate ENTICE residuals plus all children; fine descriptor matches shown separately. Overlapping baskets are never added together.',valuation='Native source valuation retained. Currency conversion does not harmonise prices, production accounting, or product/activity boundaries. Differences are review signals, not pass/fail or model errors.',ratios='Sum numerators and denominators before dividing; signed flows retained. Ratios with denominator <= 1 USD are unavailable.',trade='Foreign Z + Y after common-region aggregation; all source counterpart regions retained. IO database comparisons are not observed customs trade or Comtrade validation.',value_added='No cross-database V indicator: accounting components are not yet harmonised.',gloria='Native SUT to product IOT using industry technology; sparse aggregate algebra, no balancing or optimisation. Native thousands of USD multiplied by 0.001.',baseline='Baseline uses identical aggregate families for broad baskets; a fine child has only its wider baseline parent as context.'))



def basket_sector_selection(basket, final_sectors, baseline_sectors, parents):
    """Never substitute the parent for an unavailable fine child."""
    if basket['id'] == 'all':
        return list(final_sectors), list(baseline_sectors), []
    if basket['entice_parents']:
        base = basket['entice_parents']
        return [s for s in final_sectors if s in base or parents.get(s) in base], base, []
    fine = basket['entice_children']
    missing = sorted(set(fine) - set(parents))
    return fine, sorted({parents[s] for s in fine if s in parents}), missing



def verified_profile_cache(path, *, family, recorded, groups, geography):
    """Validate an offline extraction against its previously recorded audit.

    This never stats or opens the native reference source. The extraction engine
    hash remains recorded as history; current geography and supplier groups must
    still match exactly. No cache is accepted from filename or existence alone.
    """
    path=Path(path)
    if not path.is_file() or not recorded:
        raise ValueError(f'{family}: cache-only mode requires an audited profile cache and recorded provenance')
    cached=json.loads(path.read_text());identity=cached['identity']
    expected={key:recorded[key] for key in ('path','size','mtime_ns')}
    if any(identity.get(key)!=value for key,value in expected.items()):
        raise ValueError(f'{family}: cache source identity differs from recorded provenance')
    if sha256(path)!=recorded['profile_sha256'] or cached['source_sha256']!=recorded['sha256']:
        raise ValueError(f'{family}: audited profile cache checksum mismatch')
    if identity['groups']!=groups or identity['geography']!=geography:
        raise ValueError(f'{family}: cached geography or supplier mapping differs from the current comparison')
    return cached
