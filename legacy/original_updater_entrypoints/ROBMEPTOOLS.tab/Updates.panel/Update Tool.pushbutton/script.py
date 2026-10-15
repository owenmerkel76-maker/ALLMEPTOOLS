# -*- coding: utf-8 -*-
import imp
import os

from pyrevit import forms, script

root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
updater = imp.load_source('_robmep_updater_command',
                          os.path.join(root, 'lib', 'robmep_updater.py'))
try:
    result = updater.update_installed(root, force=True)
    output = script.get_output()
    output.print_md('**ROBMEPTOOLS installed folder:** `{0}`'.format(root))
    if result.get('changed'):
        output.print_md('Updated {0} files. Backup: `{1}`'.format(
            result['file_count'], result['backup']))
    else:
        output.print_md('The installed tool is up to date.')
    from pyrevit.loader import sessionmgr
    sessionmgr.reload_pyrevit()
except Exception as error:
    forms.alert(str(error), title='ROBMEPTOOLS update', warn_icon=True)
