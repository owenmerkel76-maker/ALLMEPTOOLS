"""Reject legacy helper dimensions even when their numeric geometry matches."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock
import test_autodim_accounting as accounting
from test_autodim_accounting import Dimension, Reference, Point

ENGINE = Path(__file__).resolve().parents[1] / 'ROBMEPTOOLS.extension/ROBMEPTOOLS.tab/AutoDim.panel/AutoDim Smart.pushbutton/engines/duct_engine.py'

class ReusedHelperTests(unittest.TestCase):
    def setUp(self):
        fixture = accounting.AccountingTests()
        fixture.setUp()
        self.__dict__.update(fixture.__dict__)
        self.helper = SimpleNamespace(Id=900, GetReference=lambda: Reference(900, 'helper:900'))
        self.dimension = Dimension(100, [Reference(20, 'grid:20'), Reference(900, 'helper:900')], value=5)
        self.doc.elements[100] = self.dimension
        self.doc.elements[900] = self.helper
        self.helper.Name = 'ROBMEP_AD_D_legacy_known_plane'

    def register(self):
        records = self.ns['_audit_existing_direct_dimensions'](self.resolved)
        self.ns['_EXISTING_DIRECT_DIM_RECORDS'].update(records)
        return bool(records)

    def test_even_known_owned_helper_never_counts_on_rerun(self):
        self.assertFalse(self.register())
        self.assertEqual(set(), self.ns['_covered_run_rep_ids'](self.resolved, set()))
        self.assertEqual({}, self.ns['_EXISTING_DIRECT_DIM_RECORDS'])

    def test_different_helper_cannot_satisfy_current_source(self):
        self.dimension.References.values[1] = Reference(901, 'helper:901')
        self.assertFalse(self.register())
        self.assertEqual({}, self.ns['_EXISTING_DIRECT_DIM_RECORDS'])

    def test_wrong_measured_value_is_not_registered(self):
        self.dimension.Value = 8
        self.assertFalse(self.register())

    def test_display_override_is_not_coverage(self):
        self.dimension.ValueOverride = '5 feet'
        self.assertFalse(self.register())

    def test_wrong_axis_is_not_registered(self):
        self.dimension.Curve.Direction = Point(0, 1)
        self.assertFalse(self.register())

    def test_changed_stable_reference_is_rejected(self):
        self.dimension.References.values[1] = Reference(900, 'different-face')
        self.assertFalse(self.register())

    def placement_loop(self, outcome):
        main = next(n for n in ast.parse(ENGINE.read_bytes()).body
                    if isinstance(n, ast.FunctionDef) and n.name == 'main')
        loop = next(n for n in ast.walk(main) if isinstance(n, ast.For)
                    and isinstance(n.iter, ast.Name) and n.iter.id == 'resolved'
                    and any(isinstance(x, ast.Call) and isinstance(x.func, ast.Name)
                            and x.func.id == 'try_dimension_duct' for x in ast.walk(n)))
        transaction = SimpleNamespace(Start=mock.Mock(), Commit=mock.Mock(), RollBack=mock.Mock())
        ns = {'resolved':[(self.rep, self.gdata)], 'eid_int':int, 'doc':self.doc,
              'DB':SimpleNamespace(SubTransaction=lambda doc:transaction),
              'try_dimension_duct':lambda *args:outcome,
              'existing_pairs':set(), 'obstacle_grid':None, 'placement_stats':{},
              'counts':{'created':0, 'duplicate':0, 'blocked':0, 'failed':0},
              'failures':[], 'angled_round_rescued_ids':set()}
        ns.setdefault('Int64', int)
        exec(compile(ast.Module(body=[loop], type_ignores=[]), str(ENGINE), 'exec'), ns)
        return transaction, ns

    def test_actual_direct_duplicate_placement_path_commits(self):
        transaction, ns = self.placement_loop(('duplicate', 'round-center', 'A', 'Verified actual source'))
        transaction.Commit.assert_called_once()
        transaction.RollBack.assert_not_called()
        self.assertEqual(1, ns['counts']['duplicate'])
        self.assertEqual(0, ns['counts']['created'])

    def test_actual_blocked_placement_path_still_rolls_back(self):
        transaction, ns = self.placement_loop(('blocked', 'round-center', 'A', 'Occupied text'))
        transaction.RollBack.assert_called_once()
        transaction.Commit.assert_not_called()
        self.assertEqual(1, ns['counts']['blocked'])
        self.assertIn('Occupied text', ns['failures'][0][1])
