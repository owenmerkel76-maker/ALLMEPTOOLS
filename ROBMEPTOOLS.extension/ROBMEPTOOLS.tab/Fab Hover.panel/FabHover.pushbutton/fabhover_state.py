# -*- coding: utf-8 -*-
"""Persistent singleton state for Fab Hover.

Normal shortcut presses only import this already-cached module and flip the
existing window state. Heavy WPF/Revit imports are cold-start/recovery only.
"""
BUILD_ID = "2026.10-ui-system-v7.2"
TITLE = "Fab Hover - Revit 2025"
_window = None
_toggle = None


def _valid(w):
    try:
        return (w is not None
                and not bool(getattr(w, "_is_closed", False))
                and getattr(w, "build_id", None) == BUILD_ID
                and hasattr(w, "toggle_active"))
    except:
        return False


def _recover_window():
    # Recovery runs only after reload/state loss, never on the normal hot path.
    try:
        import clr
        clr.AddReference("PresentationFramework")
        from System.Windows import Application
        app = Application.Current
        if app is None:
            return None
        for candidate in list(app.Windows):
            try:
                if candidate.Title != TITLE:
                    continue
                if _valid(candidate):
                    return candidate
                try:
                    candidate.Close()
                except:
                    pass
            except:
                pass
    except:
        pass
    return None


def run(revit):
    global _window, _toggle

    # HOT PATH: one cached bound-method call. No clr/WPF/pyRevit imports, file I/O,
    # settings reads, window enumeration, or filter/cache work.
    if _toggle is not None:
        try:
            _toggle()
            return
        except:
            _toggle = None
            _window = None

    _window = _recover_window()
    if _valid(_window):
        try:
            _toggle = _window.toggle_active
            _toggle()
            return
        except:
            _toggle = None
            _window = None

    # COLD START only.
    try:
        import fabhover_core as core
        _window = core.start(revit)
        if _valid(_window):
            _toggle = _window.toggle_active
    except Exception as ex:
        _window = None
        _toggle = None
        from pyrevit import forms
        forms.alert("Fab Hover could not start:\n\n{0}".format(ex), title="Fab Hover")
