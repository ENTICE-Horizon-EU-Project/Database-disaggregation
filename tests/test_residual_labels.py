"""Names remain readable while stable codes and independent X round-trip."""
import json

import pandas as pd
import pytest

from database_disaggregation.core.residual_labels import (
    load_checkpoint_with_codes, rename_in_memory, residual_names, restore_frame_codes,
)


def test_residual_names_distinguish_petroleum_products_from_crude_oil():
    mapping = residual_names({'PCP':'P_C', 'BAR':'GRO'},
        {'P_C':'Petroleum and coal products', 'GRO':'Cereal grains nec', 'OIL':'Oil extraction'},
        ['PCP','P_C','GRO','BAR','OIL'])
    assert mapping == {'GRO':'Rest of Cereal grains nec', 'P_C':'Petroleum products'}
    assert 'OIL' not in mapping
    assert residual_names({'CHILD':'EEQ'}, {'EEQ':'Rest of Electrical equipment'}, ['EEQ']) == {'EEQ':'Rest of Electrical equipment'}
    with pytest.raises(ValueError, match='collide'):
        residual_names({'BAR':'GRO'}, {'GRO':'Grains'}, ['GRO','Rest of Grains'])


def test_named_checkpoint_preserves_independent_output_and_restores_exact_values(tmp_path):
    from test_parent_budgets import _baseline
    from mario.ops.add_sector_steps import _digest, load_checkpoint
    import mario
    source = _baseline(tmp_path)
    db = mario.parse_from_parquet(str(source), table='IOT', mode='flows')
    db.reset_to_flows('baseline')
    db.matrices['baseline']['X'] = pd.DataFrame([100.,200.,300.], index=db.Z.index, columns=['production'])
    raw = {name:db.resolve(name).copy() for name in ['Z','Y','V','E','X','EY','VY']}
    names = {'Parent':'Rest of Parent'}
    rename_in_memory(db, names)
    for name, expected in raw.items():
        pd.testing.assert_frame_equal(restore_frame_codes(db.resolve(name), names), expected, check_exact=True)
    # The parquet parser sorts sector axes, including after a name change.
    db.matrices['baseline']['X'] = db.X.sort_index(axis=0, level=1)
    out = tmp_path/'named'
    db.to_parquet(path=out, flows=True, coefficients=False)
    state = dict(format='mario-sector-steps-v1', status='complete', database_directory='.',
        split_model_options={'accounting':'inherit'}, residual_index_renames=names,
        files={str(p.relative_to(out)):_digest(p) for p in out.rglob('*') if p.is_file()})
    (out/'state.json').write_text(json.dumps(state))
    assert load_checkpoint(out).get_index('Sector') == ['Rest of Parent']
    coded = load_checkpoint_with_codes(out)
    for name, expected in raw.items():
        actual = coded.resolve(name).reindex(index=expected.index, columns=expected.columns)
        pd.testing.assert_frame_equal(actual, expected, check_exact=True)
