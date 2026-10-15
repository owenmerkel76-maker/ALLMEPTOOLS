"""Direct recovery preserves failures and never substitutes an independent datum."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock

ENGINE = Path(__file__).resolve().parents[1] / 'ROBMEPTOOLS.extension/ROBMEPTOOLS.tab/AutoDim.panel/AutoDim Smart.pushbutton/engines/duct_engine.py'

class AttemptDiagnosticsTests(unittest.TestCase):
    def namespace(self):
        tree = ast.parse(ENGINE.read_bytes())
        tree.body = [n for n in tree.body if isinstance(n, ast.FunctionDef)
                     and n.name in ('_record_dimension_attempt', 'try_dimension_direct_recovery',
                                    '_recover_branch_leg_without_helpers', 'try_dimension_round_branch_anchor')]
        ns = {'eid_int': int, 'duct_centerline': lambda e: 'actual-line',
              'duct_shape': lambda e: 'edge',
              'nearest_parallel_grid': lambda line, grids: ('actual-grid-data',),
              '_branch_grid_for_leg': lambda *a, **k: {'name':'D'},
              'Int64':int, 'DB':SimpleNamespace(ElementId=int),
              'doc':SimpleNamespace(GetElement=lambda eid:SimpleNamespace(Id=eid)),
              '_branch_source_reference_candidates':lambda *args:(None, 'branch', [])}
        exec(compile(tree, str(ENGINE), 'exec'), ns)
        return ns

    def run_recovery(self, ns):
        return ns['try_dimension_direct_recovery'](SimpleNamespace(Id=10), {'name':'D'},
                                                   set(), None, {}, token='MR')

    def test_blocked_actual_reference_keeps_phase_grid_and_reason(self):
        ns = self.namespace()
        outcome = ('blocked', 'edge', 'D', 'Actual duct text pocket remains congested.')
        ns['try_dimension_duct'] = mock.Mock(return_value=outcome)
        self.assertEqual(outcome, self.run_recovery(ns))
        ns['try_dimension_duct'].assert_called_once()
        self.assertEqual([{'source_id':10, 'phase':'direct:MR', 'status':'blocked',
                           'mode':'edge', 'grid_name':'D', 'detail':outcome[3]}], ns['AUTODIM_ATTEMPTS'])

    def test_api_exception_is_saved_and_propagated(self):
        ns = self.namespace()
        ns['try_dimension_duct'] = mock.Mock(side_effect=RuntimeError('Revit rejected actual reference'))
        with self.assertRaisesRegex(RuntimeError, 'Revit rejected actual reference'):
            self.run_recovery(ns)
        self.assertEqual('exception', ns['AUTODIM_ATTEMPTS'][0]['status'])
        self.assertEqual('D', ns['AUTODIM_ATTEMPTS'][0]['grid_name'])

    def test_nonparallel_target_cannot_fall_back_to_coordinate_plane(self):
        ns = self.namespace()
        ns['nearest_parallel_grid'] = lambda *args: None
        ns['try_dimension_duct'] = mock.Mock(side_effect=AssertionError('must not place'))
        outcome = self.run_recovery(ns)
        self.assertEqual('no-grid', outcome[0])
        self.assertIn('No helper datum created', outcome[3])
        ns['try_dimension_duct'].assert_not_called()

    def test_connector_coordinate_stays_unresolved_without_physical_reference(self):
        ns = self.namespace()
        outcome = ns['_recover_branch_leg_without_helpers'](
            {'branch_id':12, 'key':'branch-12', 'point':object()}, [], set(), None, {})
        self.assertEqual('unsupported', outcome[0])
        self.assertEqual('direct-branch:branch-12', ns['AUTODIM_ATTEMPTS'][0]['phase'])
        self.assertIn('actual source edge/center reference', outcome[3])

    def test_matching_physical_branch_reference_delegates_to_direct_placement(self):
        ns = self.namespace()
        refs = [{'ref':object()}]
        ns['_branch_source_reference_candidates'] = lambda *args:(object(), 'branch-edge', refs)
        ns['_place_branch_source_dimension'] = mock.Mock(return_value=('created', 'branch-edge', 'D', 'actual source'))
        outcome = ns['_recover_branch_leg_without_helpers'](
            {'branch_id':12, 'key':'branch-12'}, [], set(), None, {})
        self.assertEqual('created', outcome[0])
        ns['_place_branch_source_dimension'].assert_called_once()

    def test_round_connector_anchor_cannot_invoke_removed_helper_path(self):
        ns = self.namespace()
        outcome = ns['try_dimension_round_branch_anchor'](
            {'element':SimpleNamespace(Id=12), 'point':object()}, [], set(), None, {})
        self.assertEqual('unsupported', outcome[0])
        self.assertEqual('direct-round-branch', ns['AUTODIM_ATTEMPTS'][0]['phase'])

    def test_engine_contains_no_reference_datum_creation_or_movement(self):
        tree = ast.parse(ENGINE.read_bytes())
        forbidden = {'NewReferencePlane', 'NewReferencePlane2', 'NewModelCurve',
                     'NewDetailCurve', '_get_or_create_helper', '_move_helper_to_target', '_try_helper_target'}
        calls = {n.func.attr if isinstance(n.func, ast.Attribute) else n.func.id
                 for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and isinstance(n.func, (ast.Attribute, ast.Name))}
        self.assertFalse(calls & forbidden)
