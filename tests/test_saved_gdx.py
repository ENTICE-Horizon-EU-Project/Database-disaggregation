"""GDX export preserves saved signed flows, tiny values and explicit zero output."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from test_benchmark import pair, update_hash
from database_disaggregation.core.benchmark import fingerprints
from database_disaggregation.reporting.saved_gdx import export_saved_gdx


def test_saved_gdx_roundtrip_preserves_signed_tiny_flows_and_pending_satellites(pair, tmp_path):
    gt=pytest.importorskip('gams.transfer')
    try:
        gt.Container()
    except Exception as error:
        pytest.skip(f'GAMS runtime is not available: {error}')
    _,root=pair
    y=pd.read_parquet(root/'flows/Y.parquet')
    y.iloc[0,0]=-1e-54
    y.to_parquet(root/'flows/Y.parquet')
    update_hash(root,'Y')
    x=pd.read_parquet(root/'flows/X.parquet')
    e=pd.DataFrame(np.arange(len(x),dtype=float).reshape(1,-1),index=['CO2'],columns=x.index)
    e.iloc[0,-1]=np.nan
    e.to_parquet(root/'flows/E.parquet')
    update_hash(root,'E')
    units=pd.read_parquet(root/'flows/units.parquet')
    units.loc[('Satellite account','CO2'),'unit']='kt'
    units.to_parquet(root/'flows/units.parquet')
    update_hash(root,'units')
    before=fingerprints(root)
    output=tmp_path/'saved.gdx'
    result=export_saved_gdx(root,output)
    assert all(s['roundtrip_exact'] for s in result['symbols'].values())
    assert result['source_sha256']==before==fingerprints(root)
    assert result['added_sectors']==1
    assert result['pending_recalculations']==['E']
    assert 'E' in result['omitted_symbols']
    assert 'E' not in result['symbols']
    loaded=gt.Container(load_from=output)
    assert loaded['satellite_recalculation_pending'].toValue()==1.
    assert loaded['new_sector'].toList()==['C']
    assert loaded['sector_parent'].toList()==[('C','P')]
    assert loaded['Y'].toDense()[0,0,0,0]==-1e-54
    assert loaded['V'].toDense().min()<0
    assert loaded['satellite_unit'].toList()==[('CO2','kt')]
    with pytest.raises(FileExistsError):
        export_saved_gdx(root,output)
