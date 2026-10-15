# -*- coding: utf-8 -*-
"""Fetch approved tool source on startup/Reload, then refresh changed bundles."""
import imp
import os

__persistentengine__ = True

from pyrevit import HOST_APP
from pyrevit.coreutils.logger import get_logger

root = os.path.dirname(os.path.abspath(__file__))
logger = get_logger('ROBMEPTOOLS updater')
try:
    updater = imp.load_source('_robmep_updater_startup',
                              os.path.join(root, 'lib', 'robmep_updater.py'))
    result = updater.update_installed(root)
    if result.get('changed'):
        from pyrevit.loader import sessionmgr
        logger.info('ROBMEPTOOLS updated %s files in %s. Refreshing the ribbon.',
                    result['file_count'], root)
        updater.queue_reload(HOST_APP.uiapp, sessionmgr.reload_pyrevit, logger.warning)
except Exception as error:
    logger.warning('ROBMEPTOOLS update skipped: %s', error)
