# -*- coding: utf-8 -*-
import imp
import os

from pyrevit import forms, script

root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
updater = imp.load_source('_robmep_updater_settings',
                          os.path.join(root, 'lib', 'robmep_updater.py'))
work = updater.work_directory(root)
path = os.path.join(work, 'settings.json')
settings = updater.read_json(path) if os.path.isfile(path) else {}
output = script.get_output()
output.print_md('**Folder Revit is loading:** `{0}`'.format(root))
output.print_md('**Backups and updater settings:** `{0}`'.format(work))
output.print_md('**GitHub repository:** {0}'.format(updater.REPOSITORY))
choice = forms.CommandSwitchWindow.show(
    ['Scheduled updates (wait for Revit to close)', 'Enable updates on Reload',
     'Use Update Tool button only', 'Show folder only'],
    message='Installed folder: {0}'.format(root))
if choice and choice != 'Show folder only':
    settings['auto_update'] = choice == 'Enable updates on Reload'
    settings['scheduled_updates'] = choice == 'Scheduled updates (wait for Revit to close)'
    updater.write_json(path, settings)
