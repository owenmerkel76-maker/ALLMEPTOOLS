# -*- coding: utf-8 -*-
"""Fab Hover hot toggle entry point.

After the first start, the persistent pyRevit engine keeps _fab_toggle bound to
FabHover.toggle_active(). Normal shortcut presses therefore execute one Python
function call and return. Recovery/cold-start work is only used if that delegate
is missing or stale.
"""
__persistentengine__ = True
__cleanengine__ = False

# Absolute hot path: no imports, file IO, settings reads, window enumeration,
# filter rebuilding, or module calls after the first successful start.
try:
    _fab_toggle()
except NameError:
    import os
    import sys
    _bundle = os.path.dirname(__file__)
    if _bundle not in sys.path:
        sys.path.insert(0, _bundle)
    import fabhover_state as _fab_state
    _fab_state.run(__revit__)
    try:
        _fab_toggle = _fab_state._toggle
    except:
        _fab_toggle = None
except Exception:
    # Stale delegate/window: recover through the persistent singleton state.
    try:
        _fab_toggle = None
    except:
        pass
    try:
        import os
        import sys
        _bundle = os.path.dirname(__file__)
        if _bundle not in sys.path:
            sys.path.insert(0, _bundle)
        import fabhover_state as _fab_state
        _fab_state.run(__revit__)
        try:
            _fab_toggle = _fab_state._toggle
        except:
            _fab_toggle = None
    except:
        pass
