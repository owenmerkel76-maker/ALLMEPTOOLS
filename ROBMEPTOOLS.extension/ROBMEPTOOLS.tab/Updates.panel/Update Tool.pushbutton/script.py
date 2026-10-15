# -*- coding: utf-8 -*-
"""Manual update instructions. Legacy auto-updater deliberately disabled."""
from pyrevit import forms
forms.alert(
    'This unified ROBMEPTOOLS development build does not auto-update from the '
    'older published GitHub release.\n\n'
    'To update, close Revit and deploy your reviewed Codex build using '
    'INSTALL_WINDOWS.ps1. The installer backs up the previous extension. '
    'Reopen Revit and select pyRevit > Reload.\n\n'
    'This prevents the legacy release channel from overwriting Hangers, '
    'Steel, Roof Deck, and Schedule tools.',
    title='ROBMEPTOOLS — Manual Updates', warn_icon=False
)
