"""Donor proposals preserve input composition and reveal their economic change."""
from copy import deepcopy
import math
import pytest
from database_disaggregation.reconciliation.prior_review import parent_factor_proposal


def profile():
    values=[('A','Sector',.7,'R1','M USD'),('B','Sector',.3,'R2','M USD'),
            ('Capital','Factor of production',-.06,None,'M USD'),
            ('Labor','Factor of production',-.02,None,'M USD'),
            ('TTM','Factor of production',.105,None,'M USD'),
            ('Tax','Factor of production',-.025,None,'M USD'),
            ('CO2','Satellite account',42.,None,'tonne')]
    return [dict(Quantity=q,Unit=unit,Input=item,**{'DB Item':item,'Item type':kind,'DB Region':origin,'Change type':'Update'})
            for item,kind,q,origin,unit in values]


PARENT={'Capital':.3,'Labor':.1,'TTM':.01,'Tax':.09}


def test_minimal_repair_changes_net_v_and_preserves_signed_child_priors_and_input_shape():
    original=profile();before=deepcopy(original)
    candidate,audit=parent_factor_proposal(original,PARENT)
    values={row['DB Item']:row['Quantity'] for row in candidate}
    assert values['Capital']==.3 and values['Labor']==.1
    assert values['Tax']==-.025 and values['TTM']==.105
    assert audit['net_v_after']==pytest.approx(.48)
    assert audit['net_v_before']==pytest.approx(0.)
    assert values['A']+values['B']==pytest.approx(.52)
    assert values['A']/values['B']==pytest.approx(.7/.3)
    assert candidate[0]['DB Region']=='R1' and candidate[1]['DB Region']=='R2'
    assert candidate[-1]==original[-1]
    assert original==before


def test_whole_block_inherits_parent_v_and_still_retains_child_input_composition():
    candidate,audit=parent_factor_proposal(profile(),PARENT,mode='all_factors')
    values={row['DB Item']:row['Quantity'] for row in candidate}
    assert {key:values[key] for key in PARENT}==PARENT
    assert audit['net_v_after']==pytest.approx(.5)
    assert values['A']+values['B']==pytest.approx(.5)
    assert values['A']/values['B']==pytest.approx(.7/.3)
    assert audit['monetary_total']==pytest.approx(1.)


def test_inadmissible_donor_is_rejected_without_clipping():
    with pytest.raises(ValueError,match='inadmissible'):
        parent_factor_proposal(profile(),{**PARENT,'Capital':-.1})
    with pytest.raises(ValueError,match='missing a factor'):
        parent_factor_proposal(profile(),{k:v for k,v in PARENT.items() if k!='Labor'})
    with pytest.raises(ValueError,match='negative inputs'):
        parent_factor_proposal(profile(),{**PARENT,'Capital':2.})


def test_bad_source_requires_explicit_decision():
    rows=profile();rows[0]['Quantity']=-1.
    with pytest.raises(ValueError,match='Negative intermediate'):
        parent_factor_proposal(rows,PARENT)
    rows=profile();rows[0]['Unit']='kg'
    with pytest.raises(ValueError,match='Monetary coefficient'):
        parent_factor_proposal(rows,PARENT)
    rows=profile();rows.append(dict(rows[2]))
    with pytest.raises(ValueError,match='duplicate factor'):
        parent_factor_proposal(rows,PARENT)
    with pytest.raises(ValueError,match='Unknown'):
        parent_factor_proposal(profile(),PARENT,mode='clip')
