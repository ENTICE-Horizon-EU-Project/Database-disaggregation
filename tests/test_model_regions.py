"""The executable geography merges incompatible groups and never splits GTAP."""
import json
from pathlib import Path

import pytest

from database_disaggregation.core.model_regions import coarsen_model_regions
from database_disaggregation.core.geography import Geography


def test_merges_are_transitive_and_independent_of_input_order():
    desired={'a':'A','b':'B','c':'B','d':'C','e':'D'}
    native={'R1':['a','b'],'R2':['c','d'],'R3':['e']}
    result=coarsen_model_regions(desired,native)
    assert result['mapping']=={'R1':'A_B_C','R2':'A_B_C','R3':'D'}
    assert result['target_regions']==2
    reversed_result=coarsen_model_regions(dict(reversed(list(desired.items()))),dict(reversed(list(native.items()))))
    assert result['mapping']==reversed_result['mapping']
    assert result['desired_to_effective']==reversed_result['desired_to_effective']


def test_unrepresented_native_region_requires_an_explicit_destination():
    with pytest.raises(ValueError,match='Explicit assignments'):
        coarsen_model_regions({'a':'A'},{'R':['a'],'REST':['x']})
    result=coarsen_model_regions({'a':'A'},{'R':['a'],'REST':['x']},unrepresented={'REST':'REST'})
    assert result['mapping']=={'R':'A','REST':'REST'}
    assert result['target_regions']==2


@pytest.mark.parametrize('native',[{'R':['a']},{'R':['a','b'],'OTHER':['b']}])
def test_missing_and_ambiguous_country_ownership_are_not_guessed(native):
    with pytest.raises(ValueError,match='incomplete or ambiguous'):
        coarsen_model_regions({'a':'A','b':'B'},native)


def test_generated_partition_covers_the_actual_native_universe():
    from database_disaggregation.core.registry import Registry
    root=Path(__file__).resolve().parents[1]
    geo=Geography.read(root/'data/geographies/gtap-models-compatible.json')
    geo.validate(Registry.load().members('GLOBAL',geography='GTAP12'))
    assert len(geo.mapping)==163 and len(geo.regions)==61
    assert geo.mapping['XOC']==geo.mapping['XEA']==geo.mapping['TWN']==geo.mapping['AFG']
    assert geo.mapping['XNA']==geo.mapping['ALB']==geo.mapping['SRB']
    assert geo.mapping['XER']==geo.mapping['XEF']==geo.mapping['NOR']==geo.mapping['CHE']
    assert geo.mapping['XTW']=='XTW'
    assert geo.mapping['USA']=='USA' and geo.mapping['CHN']=='CHN' and geo.mapping['ITA']=='ITA'
    metadata=json.loads((root/'data/geographies/gtap-models-compatible.source.json').read_text())
    assert metadata['target_regions']==61 and metadata['geographic_disaggregation'] is False
