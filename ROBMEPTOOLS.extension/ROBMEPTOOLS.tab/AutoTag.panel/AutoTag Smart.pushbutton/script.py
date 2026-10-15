# -*- coding: utf-8 -*-
"""ROBMEPTOOLS AutoTag Smart - unified Duct + Pipe launcher."""
import clr
import imp
import os
import sys
import traceback

clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')

from pyrevit import revit, forms, script

BUNDLE_DIR = os.path.dirname(__file__)
ENGINES_DIR = os.path.join(BUNDLE_DIR, 'engines')
if BUNDLE_DIR not in sys.path:
    sys.path.insert(0, BUNDLE_DIR)
if ENGINES_DIR not in sys.path:
    sys.path.insert(0, ENGINES_DIR)

from autotag_menu import show_autotag_menu

output = script.get_output()
doc = revit.doc


def _load_engine(filename, module_name):
    sys.modules.pop(module_name, None)
    try:
        return imp.load_source(module_name, os.path.join(ENGINES_DIR, filename))
    except Exception:
        sys.modules.pop(module_name, None)
        raise


def _run_engine(filename, module_name, options):
    module = None
    try:
        module = _load_engine(filename, module_name)
        module.AUTOTAG_EXTERNAL_OPTIONS = options
        module.AUTOTAG_SUPPRESS_RESULT_DIALOG = True
        return module.main()
    finally:
        # Both AutoTag engines build sizeable per-run caches. Drop the module
        # after each discipline so Revit/pyRevit does not retain stale geometry.
        try:
            if module_name in sys.modules:
                del sys.modules[module_name]
        except Exception:
            pass
        module = None


def _compact_line(label, result):
    if not result:
        return '{0}: no completed result'.format(label)
    event_created = int(result.get('created', 0) or 0)
    comp_created = int(result.get('component_created', 0) or 0)
    failed = int(result.get('failed', 0) or 0) + int(result.get('component_failed', 0) or 0)
    runtime = float(result.get('runtime', 0.0) or 0.0)
    return '{0}: {1} event + {2} component tag(s) | {3} failed | {4:.1f}s'.format(
        label, event_created, comp_created, failed, runtime)


def _report_error(stage, exc, results):
    try:
        output.print_md('## AutoTag Smart {0} error'.format(stage))
        output.print_md('```text\n{0}\n```'.format(traceback.format_exc()))
    except Exception:
        pass
    message = 'AutoTag Smart failed during {0}:\n\n{1}'.format(stage, exc)
    if results:
        message += '\n\nCompleted before the error:\n' + '\n'.join(
            _compact_line(label, result) for label, result in results)
    if stage.endswith('engine'):
        message += ('\n\nThe interrupted run may have changed the model. '
                    'Review the view and Revit Undo history before running again.')
    message += '\n\nThe full error is in the pyRevit output window.'
    forms.alert(message, title='AUTOTAG SMART')


def main():
    if doc is None or doc.IsFamilyDocument:
        forms.alert('Open a Revit project before running AutoTag Smart.', title='AUTOTAG SMART')
        return
    try:
        settings = show_autotag_menu(doc)
    except Exception as ex:
        _report_error('menu', ex, [])
        return
    if not settings:
        return

    results = []
    stage = 'engine'
    try:
        if 'duct' in settings.get('active_disciplines', []):
            stage = 'DUCT engine'
            result = _run_engine('duct_engine.py', 'robmep_autotag_duct_engine', settings.get('duct', {}))
            if result:
                results.append(('DUCT', result))

        if 'pipe' in settings.get('active_disciplines', []):
            stage = 'PIPE engine'
            result = _run_engine('pipe_engine.py', 'robmep_autotag_pipe_engine', settings.get('pipe', {}))
            if result:
                results.append(('PIPE', result))
    except Exception as ex:
        _report_error(stage, ex, results)
        return

    if not results:
        return

    if len(results) == 1:
        label, result = results[0]
        forms.alert(result.get('message', _compact_line(label, result)), title='{0} AUTOTAG'.format(label))
        return

    summary = 'AutoTag Smart complete.\n\n' + '\n'.join(_compact_line(label, result) for label, result in results)
    summary += '\n\nScope: {0}\nDuct V9 and Pipe V1 detection/placement engines were run independently from the shared menu.'.format(
        str(settings.get('scope', 'view')).replace('_', ' ').title())
    forms.alert(summary, title='AUTOTAG SMART')

    try:
        if bool(settings.get('duct', {}).get('switches', {}).get('Detailed console report', False)) or bool(settings.get('pipe', {}).get('switches', {}).get('Detailed console report', False)):
            for label, result in results:
                output.print_md('## {0} AutoTag detailed result'.format(label))
                output.print_md('```text\n{0}\n```'.format(result.get('message', '')))
    except Exception:
        pass


if __name__ == '__main__':
    main()
