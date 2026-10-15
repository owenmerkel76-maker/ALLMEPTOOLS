"""Regression checks for the saved per-run target inventory."""
import ast
import json
import math
import pathlib
import tempfile
import types
import unittest
import uuid
from unittest import mock

ENGINE = pathlib.Path(__file__).resolve().parents[1] / (
    'ROBMEPTOOLS.extension/ROBMEPTOOLS.tab/AutoDim.panel/'
    'AutoDim Smart.pushbutton/engines/duct_engine.py')


def point(x, y, z=0):
    return types.SimpleNamespace(X=x, Y=y, Z=z)


def audit_functions():
    tree = ast.parse(ENGINE.read_bytes())
    wanted = {'_audit_point', '_build_run_audit', '_write_run_audit'}
    tree.body = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in wanted]
    ns = {'json': json, 'math': math, 'uuid': uuid, 'eid_int': int}
    ns.setdefault('Int64', int)
    exec(compile(tree, str(ENGINE), 'exec'), ns)
    return ns


class AuditTests(unittest.TestCase):
    def test_missing_or_nonfinite_point_is_explicit(self):
        ns = audit_functions()
        self.assertIsNone(ns['_audit_point'](None))
        self.assertIsNone(ns['_audit_point'](point(float('nan'), 1)))
        self.assertEqual(ns['_audit_point'](point(1, 2, 3)), [1., 2., 3.])

    def test_each_run_saves_a_unique_valid_json_file(self):
        ns = audit_functions()
        with tempfile.TemporaryDirectory() as directory:
            ns['script'] = types.SimpleNamespace(get_data_file=lambda name, ext: str(
                pathlib.Path(directory) / (name + '.' + ext)))
            payload = {'document': 'Area A – étage 2', 'targets': [{'source_id': 42}]}
            a = ns['_write_run_audit'](payload)
            b = ns['_write_run_audit'](payload)
            self.assertNotEqual(a, b)
            self.assertEqual(json.loads(pathlib.Path(a).read_text()), payload)
            self.assertEqual(json.loads(pathlib.Path(b).read_text()), payload)

    def test_inventory_keeps_branch_station_and_no_grid_target_separate(self):
        ns = audit_functions()
        grid = {'element': types.SimpleNamespace(Id=10)}
        normal = types.SimpleNamespace(Id=1)
        no_grid = types.SimpleNamespace(Id=2)
        ns.update({
            '_covered_run_rep_ids': mock.Mock(return_value={1}),
            '_certified_branch_keys': mock.Mock(return_value=set()),
            '_expected_run_target': mock.Mock(return_value=(point(3, 4), 'round-center')),
            '_RUN_MEMBER_IDS': {1: {1, 3}},
            'duct_centerline': mock.Mock(return_value='line'),
            'line_midpoint': mock.Mock(return_value=point(3, 4)),
            '_BRANCH_LEG_RECORDS': [{'requires_connector_target': True, 'key': 'b7',
                                    'branch_id': 7, 'point': point(5, 6),
                                    'axis': point(0, 1), 'rep_ids': [1]}],
            '_EXISTING_DIRECT_DIM_RECORDS': {},
            'doc': types.SimpleNamespace(Title='Area A', Application=types.SimpleNamespace(VersionNumber='2025')),
            'view': types.SimpleNamespace(Name='Second Floor', Id=20, Scale=48),
        })
        result = {'created': 1, 'message': 'large dialog text'}
        audit = ns['_build_run_audit']([(normal, (grid,))], [no_grid], set(), result)
        self.assertEqual(len(audit['targets']), 3)
        main, missing, branch = audit['targets']
        self.assertEqual(main['physical_member_ids'], [1, 3])
        self.assertTrue(main['covered'])
        self.assertTrue(missing['no_parallel_grid'])
        self.assertIsNone(missing['assigned_grid_id'])
        self.assertFalse(missing['covered'])
        self.assertEqual(branch['role'], 'branch_connector')
        self.assertFalse(branch['covered'])  # covered main is not branch-station proof
        self.assertNotIn('message', audit['summary'])
        self.assertEqual(audit['revit_version'], '2025')
        json.dumps(audit, allow_nan=False)


if __name__ == '__main__':
    unittest.main()
