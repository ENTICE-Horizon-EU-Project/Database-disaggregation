import numpy as np
import pandas as pd
import pytest
from database_disaggregation.reconciliation.row_trade import fit_row_trade
from database_disaggregation.core.parent_budgets import ChildTargets


def test_gurobi_joint_fit_fills_a_missing_route_without_open_solver_fallback():
    prior=np.array([[0.,0.],[0.,0.]])
    result,report=fit_row_trade([4.,8.],[0.,0.],[0.,6.,6.],[0.,6.,6.],prior,
                                [[1.,1.],[.1,.1]],0,observed=np.ones((2,2),bool),solver='GUROBI')
    assert report['solver']=='GUROBI'
    assert [a['solver']for a in report['attempts']]==['GUROBI']
    assert result[:,1].sum()==pytest.approx(8.,abs=1e-6)
    assert (result[:,1]<=6.+1e-6).all()
    np.testing.assert_array_equal(prior,[[0.,0.],[0.,0.]])


def test_select_excludes_future_sectors_but_preserves_missing_output_evidence():
    t=ChildTargets(pd.DataFrame({'Sector':['A','B']}),pd.DataFrame({'Sector':['A','B']}),
                   pd.DataFrame({'Sector_from':['A','B']}),incomplete_output={('A','R'):['x'],('B','R'):['y']})
    selected=t.select(['A'])
    assert selected.master.Sector.tolist()==['A']
    assert selected.output.Sector.tolist()==['A']
    assert selected.trade.Sector_from.tolist()==['A']
    assert selected.incomplete_output=={('A','R'):['x']}
    assert len(t.master)==2
    with pytest.raises(ValueError,match='Unknown child'):
        t.select(['C'])


def test_gurobi_fit_preserves_a_positive_inherited_row_discrepancy():
    # A fixed 12.5 USD row discrepancy must not conflict with an export cap at
    # production: all deliveries in this example are foreign.
    outputs=np.array([0.,10.])
    prior=np.array([[0.,10.]])
    result,report=fit_row_trade([0.,10.0000125],[0.,0.],[0.,10.0000125],outputs,prior,
                                [[1.,1.]],0,observed=np.ones((1,2),bool),solver='GUROBI')
    assert result[0,1]==pytest.approx(10.0000125,abs=1e-7)
    assert report['positive_inherited_row_allowance_MUSD'][0]==pytest.approx(12.5e-6)
    assert report['max_constraint_violation_MUSD']<=1e-6
    np.testing.assert_array_equal(outputs,[0.,10.])
    np.testing.assert_array_equal(prior,[[0.,10.]])


def test_small_row_is_scaled_to_its_budget_and_keeps_fixed_output():
    outputs=np.array([0.,0.2993970716678475])
    positive=np.array([9.649673929924824e-7,0.29940957079532016])
    target=float(positive.sum())
    result,report=fit_row_trade(positive,[0.,0.],[0.,target],outputs,
                               [[0.,outputs[1]]],[[1.,1.]],0,solver='GUROBI')
    assert report['status']=='optimal'
    assert report['numerical_scale_MUSD']==pytest.approx(target)
    assert result[0,1]==pytest.approx(positive[1],abs=1e-7)
    assert report['max_constraint_violation_MUSD']<=1e-6
    np.testing.assert_array_equal(outputs,[0.,0.2993970716678475])


def test_structurally_empty_row_does_not_magnify_a_generated_subprecision_target():
    tiny=1.2975009e-39
    outputs=np.array([0.,tiny])
    result,report=fit_row_trade([0.,0.],[0.,0.],[-tiny,tiny],outputs,
                               [[0.,0.]],[[1.,1.]],0,solver='GUROBI')
    assert report['status']=='already_row_feasible'
    assert report['numerical_scale_MUSD']==1e-6
    np.testing.assert_array_equal(result,[[0.,0.]])
    np.testing.assert_array_equal(outputs,[0.,tiny])


@pytest.mark.parametrize('quantity',[1.2975009e-39,2e-6])
def test_zero_parent_cleanup_preserves_real_targets_completed_rows_and_source(quantity):
    from pathlib import Path
    from types import SimpleNamespace
    import sys
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
    from reconcile_checkpoint_trade import normalize_zero_parent_outputs
    x=pd.DataFrame({'production':[0.,2.]},index=pd.MultiIndex.from_tuples(
        [('R1','Sector','Parent'),('R2','Sector','Parent')]))
    db=SimpleNamespace(X=x,units={'Sector':pd.DataFrame({'unit':['M USD']},index=['Parent'])},
                       get_index=lambda name:['Parent','Completed'])
    outputs=pd.DataFrame([['A','R1',quantity,'M USD'],['B','R1',0.,'M USD'],
                          ['A','R2',quantity,'M USD'],['Completed','R1',quantity,'M USD']],
                         columns=['Sector','Region','Quantity','Unit'])
    original=outputs.copy(deep=True)
    original_x=x.copy(deep=True)
    result,changes=normalize_zero_parent_outputs(db,outputs,{'A':'Parent','B':'Parent'})
    expected=0. if quantity<1e-6 else quantity
    assert result.loc[0,'Quantity']==expected
    assert result.loc[2,'Quantity']==quantity
    assert result.loc[3,'Quantity']==quantity
    assert bool(changes)==(quantity<1e-6)
    if changes:
        assert changes[0]['quantity_before']==quantity and changes[0]['quantity_after']==0.
    pd.testing.assert_frame_equal(outputs,original)
    pd.testing.assert_frame_equal(db.X,original_x)
    with pytest.raises(ValueError,match='pending sectors'):
        normalize_zero_parent_outputs(db,outputs,{'Completed':'Parent'})


@pytest.mark.parametrize('prior_foreign',[4.,0.])
@pytest.mark.parametrize('zero_route_prior',[1e-39,1.])
def test_zero_capacity_trade_is_exact_zero_without_changing_source_prior(prior_foreign,zero_route_prior):
    prior=np.array([[0.,prior_foreign,zero_route_prior]])
    original=prior.copy()
    result,report=fit_row_trade([6.,4.,0.],[0.,0.,0.],[0.,10.],[0.,10.],prior,
                               np.ones_like(prior),0,solver='GUROBI')
    assert result[0,1]==pytest.approx(4.,abs=1e-6)
    assert result[0,2]==0.
    assert report['structural_zero_trade_cells']==1
    np.testing.assert_array_equal(prior,original)


def test_fully_allocated_single_child_copies_exact_foreign_budgets():
    positive=np.array([2.,3.00000000000001,4.00000000000003])
    total=float(positive.sum())
    prior=np.array([[0.,positive[1]+0.099/1e6,positive[2]-0.001/1e6]])
    original=prior.copy()
    outputs=np.array([0.,total])
    result,report=fit_row_trade(positive,np.zeros(3),[0.,total],outputs,prior,
                               np.array([[1.,.1,9.]]),0,solver='GUROBI')
    np.testing.assert_array_equal(result[0,1:],positive[1:])
    np.testing.assert_array_equal(prior,original)
    np.testing.assert_array_equal(outputs,[0.,total])
    assert report['solver']=='analytical_unique_row'
    assert report['status']=='optimal' and report['max_constraint_violation_MUSD']==0.


@pytest.mark.parametrize('excess',[4.938556230627e-10,-4.938556230627e-10,2e-6])
def test_only_subprecision_single_child_output_excess_is_normalized(excess):
    from pathlib import Path
    from types import SimpleNamespace
    import sys
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
    from reconcile_checkpoint_trade import normalize_zero_parent_outputs
    capacity=5885.63589437044
    x=pd.DataFrame({'production':[capacity]},index=pd.MultiIndex.from_tuples([('R','Sector','Parent')]))
    db=SimpleNamespace(X=x,units={'Sector':pd.DataFrame({'unit':['M USD']},index=['Parent'])},
                       get_index=lambda name:['Parent'])
    outputs=pd.DataFrame([['A','R',capacity+excess,'M USD']],columns=['Sector','Region','Quantity','Unit'])
    original=outputs.copy(deep=True)
    result,changes=normalize_zero_parent_outputs(db,outputs,{'A':'Parent'})
    expected=capacity if 0<excess<1e-6 else capacity+excess
    assert result.loc[0,'Quantity']==expected
    assert bool(changes)==(0<excess<1e-6)
    pd.testing.assert_frame_equal(outputs,original)
    assert db.X.iloc[0,0]==capacity
