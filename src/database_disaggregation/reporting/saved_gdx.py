"""Lossless GDX export of saved monetary MRIO flows; no model or recalculation."""
from datetime import datetime, timezone
import gc
import json
from importlib.metadata import version
import os
from pathlib import Path
import tempfile

import numpy as np
import pandas as pd

from database_disaggregation.core.benchmark import fingerprints, sha256


def _coordinates(axis):
    if isinstance(axis, pd.MultiIndex):
        if 'Level' in axis.names:
            if axis.get_level_values('Level').nunique() != 1:
                raise ValueError('Mixed MARIO levels cannot be flattened into a GDX domain.')
            axis = axis.droplevel('Level')
        return [axis.get_level_values(i).astype(str).to_numpy() for i in range(axis.nlevels)]
    return [axis.astype(str).to_numpy()]


def _records(frame, domains, axis_sets):
    values = frame.to_numpy(dtype=float, copy=False)
    if not np.isfinite(values).all():
        raise ValueError('Non-finite flows cannot be exported.')
    i, j = np.nonzero(values)  # Omit exact zero only; retain negative and tiny flows.
    rows, columns = _coordinates(frame.index), _coordinates(frame.columns)
    if len(domains) == len(rows):  # X has a single, non-domain production column.
        if frame.shape[1] != 1:
            raise ValueError('Expected one production column.')
        columns = []
    if len(rows) + len(columns) != len(domains):
        raise ValueError('Flow axes differ from the declared GDX dimensions.')
    records = {}
    for position, (coordinates, offsets) in enumerate([(c, i) for c in rows] + [(c, j) for c in columns]):
        domain = domains[position]
        categories = axis_sets[domain]
        codes = pd.Index(categories).get_indexer(coordinates)
        if (codes < 0).any():
            raise ValueError(f'Unknown coordinate in {domain}.')
        records[f'd{position}'] = pd.Categorical.from_codes(codes[offsets], categories=categories)
    records['value'] = values[i, j]
    return pd.DataFrame(records, copy=False)


def export_saved_gdx(database, output=None, *, system_directory=None, overwrite=False):
    """Export and read back every saved cell exactly before publishing the GDX.

    GDX uses the MARIO flow schema, not the original GTAP tax/valuation schema.
    Completed satellite flows are exported as stored. Pending E is omitted.
    """
    import gams.transfer as gt

    database = Path(database).resolve()
    output = Path(output or database / 'database.gdx').resolve()
    if output.suffix.lower() != '.gdx' or output.is_relative_to(database / 'flows'):
        raise ValueError('Choose a .gdx destination outside the source flows directory.')
    output.parent.mkdir(parents=True, exist_ok=True)
    sidecar = output.with_suffix('.gdx.json')
    if not overwrite and (output.exists() or sidecar.exists()):
        raise FileExistsError('GDX export exists; pass --overwrite to replace it.')
    if not overwrite and (output.exists() or sidecar.exists()):
        raise FileExistsError('GDX export exists; use --overwrite explicitly.')
    before = fingerprints(database)
    state = json.loads((database / 'state.json').read_text())
    for relative, digest in state.get('files', {}).items():
        source = (database / relative).resolve()
        if not source.is_relative_to(database) or sha256(source) != digest:
            raise ValueError(f'Checkpoint checksum failed: {relative}')
    x = pd.read_parquet(database / 'flows/X.parquet')
    y = pd.read_parquet(database / 'flows/Y.parquet')
    v = pd.read_parquet(database / 'flows/V.parquet')
    units = pd.read_parquet(database / 'flows/units.parquet')
    options = {'system_directory': str(system_directory)} if system_directory else {}
    container = gt.Container(**options)
    sets = dict(r=list(dict.fromkeys(_coordinates(x.index)[0])),
                s=list(dict.fromkeys(_coordinates(x.index)[1])),
                d=list(dict.fromkeys(_coordinates(y.columns)[1])),
                f=list(v.index.astype(str)))
    ep = database / 'flows/E.parquet'
    if ep.exists():
        e = pd.read_parquet(ep)
        sets['sat'] = list(e.index.astype(str))
        del e
    elif (database / 'flows/EY.parquet').exists():
        sets['sat'] = list(pd.read_parquet(database / 'flows/EY.parquet').index.astype(str))
    from database_disaggregation.analysis.labels import sector_labels, read_region_names
    names = dict(s=sector_labels())
    region_names = database / 'diagnostics/provenance/region-names.csv'
    if region_names.exists():
        names['r'] = read_region_names(region_names, regions=sets['r'])
    additions = database / 'diagnostics/provenance/additional-sectors-13.json'
    if additions.exists():
        for code, item in json.loads(additions.read_text()).get('sectors', {}).items():
            names['s'].setdefault(code, item['name'])
    benchmark = database / 'benchmarking.json'
    if benchmark.exists():
        dimensions = json.loads(benchmark.read_text())['dimensions']
        names = dict(r=dimensions.get('region_names', {}), s=dimensions.get('sector_names', {}))
    from database_disaggregation.core.residual_labels import post_split_display_names
    names['s']=post_split_display_names(names.get('s',{}),state['sector_parents'],state['completed_sectors'])
    for key, labels in sets.items():
        if any(not label or len(label.encode('utf-8')) > 63 for label in labels):
            raise ValueError(f'GDX domain {key} contains empty or overlong labels.')
        container.addSet(key, records=[(label, names.get(key, {}).get(label, label)[:255]) for label in labels])
    container.addAlias('rr', container['r'])
    container.addAlias('ss', container['s'])
    axis_sets = {**sets, 'rr': sets['r'], 'ss': sets['s']}
    completed = state['completed_sectors']
    if len(set(completed)) != len(completed) or set(completed) - set(sets['s']):
        raise ValueError('Completed sectors differ from the saved sector universe.')
    parents = {s: state['sector_parents'][s] for s in completed}
    container.addSet('new_sector', domain=[container['s']], records=completed)
    container.addSet('residual_parent', domain=[container['s']], records=list(dict.fromkeys(parents.values())))
    container.addSet('sector_parent', domain=[container['s'],container['ss']], records=list(parents.items()))
    container.addSet('export_schema', records=['entice_mrio_flows_v1'])
    container.addSet('monetary_unit', records=['M USD'])
    all_units = list(dict.fromkeys(units.iloc[:, 0].astype(str)))
    container.addSet('u', records=all_units)
    for group, symbol, domain in [('Sector','sector_unit','s'),('Factor of production','factor_unit','f'),('Satellite account','satellite_unit','sat')]:
        if domain in sets and group in units.index.get_level_values(0):
            values = units.xs(group, level=0).iloc[:, 0]
            if set(sets[domain]) - set(values.index.astype(str)):
                raise ValueError(f'Missing units for domain {domain}.')
            records = [(label, str(values.loc[label])) for label in sets[domain]]
            container.addSet(symbol, domain=[container[domain],container['u']], records=records)
    container.addParameter('satellite_recalculation_pending', records=float('E' in state.get('pending_recalculations', [])))
    container.addParameter('coefficient_analysis_validated', records=0.)
    specs = dict(Z=['r','s','rr','ss'], Y=['r','s','rr','d'], V=['f','rr','ss'], X=['r','s'],
                 E=['sat','rr','ss'], EY=['sat','rr','d'], VY=['f','rr','d'])
    summaries, omitted = {}, {}
    del x,y,v
    for name, domains in specs.items():
        path = database / 'flows' / f'{name}.parquet'
        if name == 'E' and name in state.get('pending_recalculations', []):
            omitted[name] = 'Pending satellite recalculation; saved E is not a completed result.'
            continue
        if not path.exists():
            continue
        print(f'Export {name}: read saved flows.', flush=True)
        frame = pd.read_parquet(path)
        records = _records(frame, domains, axis_sets)
        container.addParameter(name, domain=[container[d] for d in domains], records=records,
                               description='Saved MARIO flow; M USD' if name not in ('E','EY') else 'Saved satellite flow; see satellite_unit')
        summaries[name] = dict(domains=domains, source_shape=list(frame.shape),
            nonzero_records=len(records), source_sha256=sha256(path), roundtrip_exact=False)
        del frame,records
        gc.collect()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.gdx-export-', dir=output.parent) as temporary:
        temp = Path(temporary) / output.name
        print('Write compressed GDX.', flush=True)
        container.write(temp, compress=True, mode='category')
        del container
        gc.collect()
        for name, summary in summaries.items():
            print(f'Verify {name}: read back every cell.', flush=True)
            loaded = gt.Container(**options)
            loaded.read(temp, symbols=list(sets) + ['rr','ss',name])
            for key, labels in sets.items():
                if loaded[key].toList() != labels:
                    raise ValueError(f'GDX domain order changed: {key}')
            actual = loaded[name].toDense()
            if actual is None:
                actual = np.zeros(tuple(len(axis_sets[d]) for d in summary['domains']))
            expected = pd.read_parquet(database / 'flows' / f'{name}.parquet')
            row_coordinates = _coordinates(expected.index)
            col_coordinates = [] if name == 'X' else _coordinates(expected.columns)
            offsets = [pd.Index(axis_sets[d]).get_indexer(c) for d,c in zip(summary['domains'],row_coordinates+col_coordinates)]
            if len(offsets) == len(row_coordinates):
                result = actual[tuple(offsets)].reshape(-1,1)
            else:
                result = actual[tuple([a[:,None] for a in offsets[:len(row_coordinates)]] +
                                      [a[None,:] for a in offsets[len(row_coordinates):]])]
            if not np.array_equal(result, expected.to_numpy()):
                raise ValueError(f'GDX round-trip differs from source: {name}')
            summary['roundtrip_exact'] = True
            del actual,expected,result,loaded
            gc.collect()
        if fingerprints(database) != before:
            raise ValueError('Source database changed during GDX export.')
        report = dict(format='entice-gdx-export-v1',generated_at=datetime.now(timezone.utc).isoformat(),
            database=str(database),output=output.name,output_sha256=sha256(temp),
            exporter_sha256=sha256(__file__),gams_api_version=version('gamsapi'),
            dimensions={k:len(v) for k,v in sets.items()},added_sectors=len(completed),
            source_sha256=before,source_flows_unchanged=True,model_rerun=False,preprocessing_rerun=False,
            monetary_unit='M USD',schema='MARIO flows (not original GTAP valuation/tax symbols)',
            pending_recalculations=state.get('pending_recalculations',[]),satellites_exported='available completed satellite flows as stored; no recalculation',
            omitted_symbols=omitted,
            structural_validation_status='review_required',coefficient_analysis_validated=False,
            symbols=summaries)
        metadata = Path(temporary) / sidecar.name
        metadata.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
        os.replace(temp,output)
        os.replace(metadata,sidecar)
    print(json.dumps({k:report[k] for k in ['output','output_sha256','dimensions','added_sectors','source_flows_unchanged']},indent=2),flush=True)
    return report
