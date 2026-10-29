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
