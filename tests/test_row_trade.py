import numpy as np
import pytest

pytest.importorskip('cvxpy')
from database_disaggregation.reconciliation.row_trade import fit_row_trade


def test_row_trade_increases_a_zero_prior_when_the_residual_has_no_output():
    # Parent exports 4 and delivers 6 domestically. All output is allocated to
    # the child: reducing its exports cannot make its zero-output parent feasible.
    result, report = fit_row_trade([6.,4.], [0.,0.], [0.,10.], [0.,10.],
                                   [[0.,0.]], [[1.,1.]], 0)
    assert result[0,1] == pytest.approx(4.,abs=1e-6)
    assert report['status'] in ('optimal','optimal_inaccurate')
    assert report['max_constraint_violation_MUSD'] <= 1e-6


def test_row_trade_retains_feasible_signed_demand_and_original_targets():
    prior = np.array([[0.,1.]])
    result, report = fit_row_trade([6.,4.], [0.,2.], [4.,4.], [4.,4.], prior, [[1.,1.]], 0)
    assert report['status'] == 'already_row_feasible'
    np.testing.assert_array_equal(result,prior)
    np.testing.assert_array_equal(prior,[[0.,1.]])


def test_row_trade_enforces_export_output_cap_with_negative_final_demand():
    result, report = fit_row_trade([6.,4.], [0.,2.], [7.,1.], [7.,1.],
                                   [[0.,2.]], [[1.,1.]], 0)
    assert result[0,1] <= 1.+1e-6
    assert report['status'] in ('optimal','optimal_inaccurate')


def test_row_trade_rejects_nonconserving_outputs():
    with pytest.raises(ValueError,match='do not conserve'):
        fit_row_trade([6.,4.], [0.,0.], [0.,11.], [0.,11.], [[0.,4.]], [[1.,1.]], 0)


def test_unobserved_trade_is_free_in_the_feasibility_probe():
    result, report = fit_row_trade([6.,4.],[0.,0.],[0.,10.],[0.,10.],[[0.,0.]],[[1.,1.]],0,
                                   observed=[[False,False]])
    assert report['status']=='already_row_feasible'
    np.testing.assert_array_equal(result,[[0.,0.]])


def test_siblings_are_fitted_jointly_with_source_weights():
    result, report = fit_row_trade([4.,8.],[0.,0.],[0.,6.,6.],[0.,6.,6.],
                                   [[0.,2.],[0.,2.]],[[1.,1.],[.1,.1]],0)
    assert result[:,1].sum()==pytest.approx(8.,abs=1e-6)
    assert result[0,1]==pytest.approx(2.+4./11.,abs=1e-5)
    assert result[1,1]>result[0,1]


def test_tiny_route_does_not_flatten_the_objective_on_major_routes():
    result, report = fit_row_trade([60000.,4000.,1e-9],[0.,0.,0.],
                                   [0.,40000.,24000.],[0.,40000.,24000.],
                                   [[0.,1000.,0.],[0.,1000.,0.]],np.ones((2,3)),0)
    np.testing.assert_allclose(result[:,1],[2000.,2000.],atol=1e-5,rtol=0.)
    assert report['max_constraint_violation_MUSD']<=1e-6


def test_projected_workbook_preserves_all_other_zip_members(tmp_path,monkeypatch):
    from pathlib import Path
    from zipfile import ZipFile
    import pandas as pd
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1]/'scripts'))
    from reconcile_model_trade import rewrite_sheets
    source,destination = tmp_path/'original.xlsx',tmp_path/'projected.xlsx'
    original = pd.DataFrame({'Sector_from':['A'],'Quantity':[2.]})
    fixed_outputs = pd.DataFrame({'Sector':['A'],'Quantity':[10.]})
    with pd.ExcelWriter(source) as writer:
        original.to_excel(writer,sheet_name='Trades',index=False)
        fixed_outputs.to_excel(writer,sheet_name='Total outputs',index=False)
    changed = rewrite_sheets(source,destination,{'Trades':original.assign(Quantity=4.)})
    with ZipFile(source) as before,ZipFile(destination) as after:
        assert set(before.namelist())==set(after.namelist())
        assert all(before.read(n)==after.read(n) for n in before.namelist() if n not in changed)
    assert pd.read_excel(destination,sheet_name='Trades').Quantity.tolist()==[4.]
    pd.testing.assert_frame_equal(pd.read_excel(source,sheet_name='Total outputs'),
                                  pd.read_excel(destination,sheet_name='Total outputs'))
