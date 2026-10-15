"""Exercise actual launcher functions with a simulated Revit/pyRevit host.

These tests cover orchestration, not Revit API transactions or WPF loading.
"""
import ast
import pathlib
import sys
import types
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
TAB = ROOT / 'ROBMEPTOOLS.extension/ROBMEPTOOLS.tab'


def launcher(tool):
    path = TAB / (tool + '.panel') / (tool + ' Smart.pushbutton') / 'script.py'
    tree = ast.parse(path.read_bytes(), filename=str(path))
    # The host-only imports and WPF classes cannot execute on Linux. Compile
    # the original function definitions, so tests exercise production logic.
    tree.body = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    namespace = {
        'sys': sys, 'os': __import__('os'), 'ENGINES_DIR': '/engines',
        'traceback': __import__('traceback'), 'imp': types.SimpleNamespace(),
        'forms': types.SimpleNamespace(alert=mock.Mock()),
        'output': types.SimpleNamespace(print_md=mock.Mock()),
        'doc': types.SimpleNamespace(IsFamilyDocument=False, Regenerate=mock.Mock()),
    }
    namespace.setdefault('Int64', int)
    exec(compile(tree, str(path), 'exec'), namespace)
    return namespace


def run_engine(tool, ns):
    if tool == 'AutoDim':
        return ns['_run_engine']('duct_engine.py', 'test_robmep_engine', 'selection', [42], 'strict')
    return ns['_run_engine']('duct_engine.py', 'test_robmep_engine', {'scope': 'selection'})


def menu(tool, ns, cancelled=False):
    if tool == 'AutoDim':
        win = types.SimpleNamespace(
            ShowDialog=mock.Mock(), run_requested=not cancelled,
            discipline='both', scope='view', grid_mode='all', detailed=False)
        ns['AutoDimWindow'] = mock.Mock(return_value=win)
        return ns['AutoDimWindow']
    ns['show_autotag_menu'] = mock.Mock(return_value=None if cancelled else {
        'active_disciplines': ['duct', 'pipe'], 'duct': {}, 'pipe': {}, 'scope': 'view'})
    return ns['show_autotag_menu']


class LauncherTests(unittest.TestCase):
    def tearDown(self):
        sys.modules.pop('test_robmep_engine', None)

    def test_fresh_module_options_and_cleanup(self):
        for tool in ('AutoDim', 'AutoTag'):
            with self.subTest(tool=tool):
                ns = launcher(tool)
                sys.modules['test_robmep_engine'] = types.ModuleType('stale')
                module = types.ModuleType('test_robmep_engine')
                expected = {'created': 3}
                module.main = mock.Mock(return_value=expected)

                def load(name, path):
                    self.assertNotIn(name, sys.modules)
                    self.assertEqual(path, '/engines/duct_engine.py')
                    sys.modules[name] = module
                    return module

                ns['imp'].load_source = load
                self.assertIs(run_engine(tool, ns), expected)
                self.assertNotIn('test_robmep_engine', sys.modules)
                module.main.assert_called_once_with()
                if tool == 'AutoDim':
                    self.assertEqual(module.AUTODIM_SCOPE, 'selection')
                    self.assertEqual(module.AUTODIM_GRID_IDS, [42])
                    self.assertEqual(module.AUTODIM_GRID_MODE, 'strict')
                    self.assertTrue(module.AUTODIM_SUPPRESS_RESULT_DIALOG)
                else:
                    self.assertEqual(module.AUTOTAG_EXTERNAL_OPTIONS, {'scope': 'selection'})
                    self.assertTrue(module.AUTOTAG_SUPPRESS_RESULT_DIALOG)

    def test_import_failure_cleans_partial_module_and_preserves_error(self):
        for tool in ('AutoDim', 'AutoTag'):
            with self.subTest(tool=tool):
                ns = launcher(tool)
                failure = RuntimeError('import failed')

                def load(name, path):
                    sys.modules[name] = types.ModuleType(name)
                    raise failure

                ns['imp'].load_source = load
                with self.assertRaises(RuntimeError) as raised:
                    run_engine(tool, ns)
                self.assertIs(raised.exception, failure)
                self.assertNotIn('test_robmep_engine', sys.modules)

    def test_execution_failure_cleans_module(self):
        for tool in ('AutoDim', 'AutoTag'):
            with self.subTest(tool=tool):
                ns = launcher(tool)
                module = types.ModuleType('test_robmep_engine')
                module.main = mock.Mock(side_effect=RuntimeError('execution failed'))

                def load(name, path):
                    sys.modules[name] = module
                    return module

                ns['imp'].load_source = load
                with self.assertRaisesRegex(RuntimeError, 'execution failed'):
                    run_engine(tool, ns)
                self.assertNotIn('test_robmep_engine', sys.modules)

    def test_cancelled_menu_does_not_run(self):
        for tool in ('AutoDim', 'AutoTag'):
            with self.subTest(tool=tool):
                ns = launcher(tool)
                menu(tool, ns, cancelled=True)
                ns['_run_engine'] = mock.Mock()
                ns['main']()
                ns['_run_engine'].assert_not_called()
                ns['forms'].alert.assert_not_called()

    def test_menu_error_has_traceback_and_does_not_run(self):
        for tool in ('AutoDim', 'AutoTag'):
            with self.subTest(tool=tool):
                ns = launcher(tool)
                menu(tool, ns).side_effect = RuntimeError('XAML load failed')
                ns['_run_engine'] = mock.Mock()
                ns['main']()
                ns['_run_engine'].assert_not_called()
                message = ns['forms'].alert.call_args.args[0]
                self.assertIn('menu', message)
                self.assertIn('XAML load failed', message)
                self.assertTrue(any('Traceback' in c.args[0] for c in ns['output'].print_md.call_args_list))

    def test_both_mode_preserves_completed_result_on_pipe_failure(self):
        for tool in ('AutoDim', 'AutoTag'):
            with self.subTest(tool=tool):
                ns = launcher(tool)
                menu(tool, ns)
                ns['_run_engine'] = mock.Mock(side_effect=[{'created': 3}, RuntimeError('pipe failed')])
                ns['main']()
                self.assertEqual(ns['_run_engine'].call_count, 2)
                message = ns['forms'].alert.call_args.args[0]
                self.assertIn('PIPE engine', message)
                self.assertIn('Completed before the error:', message)
                self.assertIn('DUCT: 3', message)
                self.assertIn('Undo', message)
                self.assertNotIn('Smart complete.', message)

    def test_first_engine_failure_stops_pipe_and_does_not_claim_completion(self):
        for tool in ('AutoDim', 'AutoTag'):
            with self.subTest(tool=tool):
                ns = launcher(tool)
                menu(tool, ns)
                ns['_run_engine'] = mock.Mock(side_effect=RuntimeError('duct failed'))
                ns['main']()
                ns['_run_engine'].assert_called_once()
                message = ns['forms'].alert.call_args.args[0]
                self.assertIn('DUCT engine', message)
                self.assertNotIn('Completed before the error:', message)

    def test_both_mode_success_reports_both_results(self):
        for tool in ('AutoDim', 'AutoTag'):
            with self.subTest(tool=tool):
                ns = launcher(tool)
                menu(tool, ns)
                ns['_run_engine'] = mock.Mock(side_effect=[{'created': 3}, {'created': 4}])
                ns['main']()
                message = ns['forms'].alert.call_args.args[0]
                self.assertIn('Smart complete.', message)
                self.assertIn('DUCT: 3', message)
                self.assertIn('PIPE: 4', message)

    def test_missing_or_family_document_blocks_menu(self):
        for tool in ('AutoDim', 'AutoTag'):
            for doc in (None, types.SimpleNamespace(IsFamilyDocument=True)):
                with self.subTest(tool=tool, doc=doc):
                    ns = launcher(tool)
                    show = menu(tool, ns)
                    ns['doc'] = doc
                    ns['main']()
                    show.assert_not_called()
                    self.assertIn('Open a Revit project', ns['forms'].alert.call_args.args[0])


if __name__ == '__main__':
    unittest.main()
