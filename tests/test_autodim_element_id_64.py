"""Exercise the missing legacy integer constructor with actual lookup functions."""
import ast
from pathlib import Path
from unittest import mock
import unittest
import test_autodim_accounting as accounting

ENGINE = Path(__file__).resolve().parents[1] / 'ROBMEPTOOLS.extension/ROBMEPTOOLS.tab/AutoDim.panel/AutoDim Smart.pushbutton/engines/duct_engine.py'

class Int64(int):
    pass

def new_element_id(value):
    if type(value) is not Int64:
        raise TypeError('Legacy Int32 ElementId constructor unavailable')
    return int(value)

class ElementId64Tests(unittest.TestCase):
    def setUp(self):
        fixture = accounting.AccountingTests()
        fixture.setUp()
        self.fixture = fixture
        self.ns = fixture.ns
        self.ns['Int64'] = Int64
        self.ns['DB'].ElementId = new_element_id
        self.ns['_write_run_audit'] = mock.Mock(return_value='lookup-audit.json')
        node = next(n for n in ast.parse(ENGINE.read_bytes()).body
                    if isinstance(n, ast.FunctionDef) and n.name == '_surviving_created_dim_ids')
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(ENGINE), 'exec'), self.ns)

    def test_committed_dimension_survives_without_legacy_int32_constructor(self):
        self.fixture.created()
        self.assertEqual({100}, self.ns['_surviving_created_dim_ids']())
        self.assertTrue(self.ns['_certify_created_dimension'](100)[0])
        self.assertEqual({10}, self.ns['_covered_run_rep_ids'](self.fixture.resolved, {100}))

    def test_large_element_id_round_trips_without_truncation(self):
        identifier = 2**33 + 100
        self.fixture.created(dim_id=identifier)
        self.assertEqual({identifier}, self.ns['_surviving_created_dim_ids']())
        self.assertTrue(self.ns['_certify_created_dimension'](identifier)[0])

    def test_actual_deleted_element_remains_distinct_from_lookup_error(self):
        self.ns['_CREATED_DIM_IDS'].add(100)
        self.assertEqual(set(), self.ns['_surviving_created_dim_ids']())
        self.ns['_write_run_audit'].assert_not_called()

    def test_lookup_error_is_logged_and_stops_repeated_recovery(self):
        self.ns['_CREATED_DIM_IDS'].add(100)
        self.fixture.doc.GetElement = mock.Mock(side_effect=RuntimeError('API lookup unavailable'))
        with self.assertRaisesRegex(RuntimeError, 'recovery stopped'):
            self.ns['_surviving_created_dim_ids']()
        self.assertEqual('API lookup unavailable', self.ns['AUTODIM_LOOKUP_ERRORS'][0]['error'])
        saved = self.ns['_write_run_audit'].call_args.args[0]
        self.assertTrue(saved['recovery_stopped'])
        self.assertEqual('survival-lookup-failed', saved['phase'])

    def test_numeric_constructor_sites_use_explicit_int64_but_keep_enum_overload(self):
        calls = [n for n in ast.walk(ast.parse(ENGINE.read_bytes()))
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                 and n.func.attr == 'ElementId' and isinstance(n.func.value, ast.Name)
                 and n.func.value.id == 'DB']
        for call in calls:
            arg = call.args[0]
            if isinstance(arg, ast.Name) and arg.id == 'bic':
                continue
            self.assertIsInstance(arg, ast.Call)
            self.assertEqual('Int64', arg.func.id)
