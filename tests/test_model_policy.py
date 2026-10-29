"""Model/solver order and failure isolation; no large model or shared publication."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from database_disaggregation.core.model_policy import (
    INITIAL, SUBSEQUENT, QUADRATIC, attempt_order, try_stage, validate_policy,
)


class NumericalFailure(Exception):
    pass


class ModelPolicyTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1]
        self.policy = validate_policy(json.loads((root/'config/model-trials/entropy-first.json').read_text()))

    def test_initial_and_subsequent_models_precede_all_quadratic_attempts(self):
        for subsequent, preferred in [(False, INITIAL), (True, SUBSEQUENT)]:
            order = list(attempt_order(self.policy, subsequent=subsequent))
            self.assertEqual([(s['model'], s['solver']) for s in order[:3]],
                             [(preferred, s) for s in ['MOSEK', 'CLARABEL', 'SCS']])
            self.assertEqual((order[3]['model'], order[3]['solver']), (QUADRATIC, 'GUROBI'))

    def test_missing_commercial_solver_uses_open_solver_without_changing_objective(self):
        events, calls = [], []
        result = try_stage(self.policy, subsequent=False, installed={'CLARABEL', 'GUROBI'},
                           solve=lambda s: calls.append(s) or 'accepted', record=lambda s: events.append(deepcopy(s)))
        self.assertEqual(result, 'accepted')
        self.assertEqual([(s['model'], s['solver']) for s in calls], [(INITIAL, 'CLARABEL')])
        self.assertEqual([s['status'] for s in events], ['not_installed', 'running', 'accepted'])

    def test_quadratic_is_only_tried_after_all_entropy_solvers_fail(self):
        calls, events = [], []
        original = deepcopy(self.policy)
        def solve(spec):
            calls.append((spec['model'], spec['solver']))
            if spec['model'] != QUADRATIC:
                raise NumericalFailure('Unacceptable residuals')
            return 'quadratic result'
        result = try_stage(self.policy, subsequent=True, installed={'MOSEK', 'CLARABEL', 'SCS', 'GUROBI'},
                           solve=solve, record=lambda s: events.append(deepcopy(s)),
                           retryable=lambda e: isinstance(e, NumericalFailure))
        self.assertEqual(result, 'quadratic result')
        self.assertEqual(calls, [(SUBSEQUENT, s) for s in ['MOSEK', 'CLARABEL', 'SCS']] + [(QUADRATIC, 'GUROBI')])
        self.assertEqual(len([e for e in events if e['status'] == 'failed']), 3)
        self.assertEqual(self.policy, original)

    def test_programming_or_invalid_input_errors_abort_instead_of_triggering_fallback(self):
        calls = []
        def solve(spec):
            calls.append(spec)
            raise ValueError('Broken coordinate schema')
        with self.assertRaisesRegex(ValueError, 'Broken coordinate'):
            try_stage(self.policy, subsequent=False, installed={'MOSEK', 'CLARABEL', 'GUROBI'},
                      solve=solve, record=lambda s: None, retryable=lambda e: False)
        self.assertEqual(len(calls), 1)

    def test_exhausted_solvers_do_not_create_an_accepted_result(self):
        events = []
        with self.assertRaisesRegex(RuntimeError, 'No model/solver attempt was accepted'):
            try_stage(self.policy, subsequent=False, installed=set(), solve=lambda s: self.fail('unavailable solver called'),
                      record=lambda s: events.append(deepcopy(s)))
        self.assertTrue(all(s['status'] == 'not_installed' for s in events))

    def test_shared_options_cannot_hide_a_different_objective(self):
        self.policy['split_model_options']['flow_loss'] = 'quadratic'
        with self.assertRaisesRegex(ValueError, 'named policy models'):
            validate_policy(self.policy)
