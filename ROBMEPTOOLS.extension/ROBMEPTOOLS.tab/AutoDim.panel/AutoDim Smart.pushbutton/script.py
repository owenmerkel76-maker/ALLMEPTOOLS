# -*- coding: utf-8 -*-
"""
ROBMEPTOOLS AUTODIM SMART
Unified Duct + Pipe launcher.
"""

import clr
import imp
import os
import sys
import traceback

clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")

from pyrevit import forms, script, revit, DB, UI

BUNDLE_DIR = os.path.dirname(__file__)
ENGINES_DIR = os.path.join(BUNDLE_DIR, "engines")
if BUNDLE_DIR not in sys.path:
    sys.path.insert(0, BUNDLE_DIR)
if ENGINES_DIR not in sys.path:
    sys.path.insert(0, ENGINES_DIR)

output = script.get_output()
doc = revit.doc


class AutoDimWindow(forms.WPFWindow):
    resolve_theme = True

    def __init__(self):
        forms.WPFWindow.__init__(self, os.path.join(BUNDLE_DIR, "autodim.xaml"))
        self.run_requested = False
        self.discipline = "duct"
        self.scope = "view"
        self.detailed = True
        self.grid_mode = "all"
        self.selected_grid_ids = None
        self.selected_grid_names = []

        try:
            from System import Uri, UriKind
            from System.Windows.Media.Imaging import BitmapImage
            icon_path = os.path.join(BUNDLE_DIR, "icon.png")
            if os.path.isfile(icon_path):
                self.Icon = BitmapImage(Uri(icon_path, UriKind.Absolute))
        except Exception:
            pass

        self._load_saved()
        self._wire()
        self._refresh_badge()

    def _wire(self):
        for ctrl in (
            self.DisciplineDuct, self.DisciplinePipe, self.DisciplineBoth,
            self.ScopeView, self.ScopeSelection, self.ScopePick,
            self.GridAll, self.GridPrefer, self.GridStrict,
        ):
            try:
                ctrl.Checked += self._changed
            except Exception:
                pass
        try:
            self.DetailedResults.Checked += self._changed
            self.DetailedResults.Unchecked += self._changed
        except Exception:
            pass
        self.RunButton.Click += self._run
        self.CancelButton.Click += self._cancel

    def _load_saved(self):
        try:
            cfg = script.get_config()
            discipline = str(getattr(cfg, "discipline", "duct"))
            scope = str(getattr(cfg, "scope", "view"))
            detailed = bool(getattr(cfg, "detailed", True))
            grid_mode = str(getattr(cfg, "grid_mode", "all")).lower()
        except Exception:
            discipline = "duct"
            scope = "view"
            detailed = True
            grid_mode = "all"

        if discipline == "pipe":
            self.DisciplinePipe.IsChecked = True
        elif discipline == "both":
            self.DisciplineBoth.IsChecked = True
        else:
            self.DisciplineDuct.IsChecked = True

        if scope == "selection":
            self.ScopeSelection.IsChecked = True
        elif scope == "pick":
            self.ScopePick.IsChecked = True
        else:
            self.ScopeView.IsChecked = True

        # Legacy v2.3.2 "pick" is intentionally mapped to the new coverage-safe
        # preferred mode so an old saved setting can not silently reduce hits.
        if grid_mode in ("prefer", "pick"):
            self.GridPrefer.IsChecked = True
        elif grid_mode == "strict":
            self.GridStrict.IsChecked = True
        else:
            self.GridAll.IsChecked = True

        self.DetailedResults.IsChecked = detailed

    def _read(self):
        if bool(self.DisciplinePipe.IsChecked):
            discipline = "pipe"
        elif bool(self.DisciplineBoth.IsChecked):
            discipline = "both"
        else:
            discipline = "duct"

        if bool(self.ScopeSelection.IsChecked):
            scope = "selection"
        elif bool(self.ScopePick.IsChecked):
            scope = "pick"
        else:
            scope = "view"

        if bool(self.GridStrict.IsChecked):
            grid_mode = "strict"
        elif bool(self.GridPrefer.IsChecked):
            grid_mode = "prefer"
        else:
            grid_mode = "all"
        return discipline, scope, grid_mode, bool(self.DetailedResults.IsChecked)

    def _refresh_badge(self):
        discipline, scope, grid_mode, detailed = self._read()
        dlabel = {"duct": "DUCT", "pipe": "PIPE", "both": "DUCT + PIPE"}.get(discipline, "DUCT")
        slabel = {"view": "ACTIVE VIEW", "selection": "SELECTION", "pick": "PICK"}.get(scope, "ACTIVE VIEW")
        glabel = {"prefer": "PREFER GRIDS", "strict": "SELECTED ONLY"}.get(grid_mode, "ALL GRIDS")
        self.ModeBadge.Text = "{0} • {1} • {2}".format(dlabel, slabel, glabel)

        if grid_mode == "prefer":
            self.FooterHelp.Text = "Pick preferred grids. AutoDim uses them first, then falls back to the original v2.3 grid logic only where needed to preserve coverage."
        elif grid_mode == "strict":
            self.FooterHelp.Text = "Strict mode uses only the grids you pick. Targets with no compatible selected grid can be intentionally skipped."
        elif scope == "view":
            self.FooterHelp.Text = "Recommended: scan every visible straight target in the active plan."
        elif scope == "selection":
            self.FooterHelp.Text = "Only straight MEP already selected in Revit will be processed."
        else:
            self.FooterHelp.Text = "After this menu closes, Revit will ask you to pick the straight MEP."

    def _changed(self, sender, args):
        try:
            self._refresh_badge()
        except Exception:
            pass

    def _save(self):
        try:
            cfg = script.get_config()
            cfg.discipline = self.discipline
            cfg.scope = self.scope
            cfg.detailed = self.detailed
            cfg.grid_mode = self.grid_mode
            script.save_config()
        except Exception:
            pass

    def _run(self, sender, args):
        self.discipline, self.scope, self.grid_mode, self.detailed = self._read()
        self._save()
        self.run_requested = True
        self.Close()

    def _cancel(self, sender, args):
        self.run_requested = False
        self.Close()


class _StraightGridSelectionFilter(UI.Selection.ISelectionFilter):
    def AllowElement(self, elem):
        try:
            if not isinstance(elem, DB.Grid):
                return False
            return isinstance(elem.Curve, DB.Line)
        except Exception:
            return False

    def AllowReference(self, reference, point):
        return False


def _eid_value(eid):
    try:
        return int(eid.Value)
    except Exception:
        try:
            return int(eid.IntegerValue)
        except Exception:
            return int(str(eid))


def _pick_grid_ids():
    # Grid selection is intentionally run-local. ElementIds are not persisted
    # because the same ROBMEPTOOLS install is used across many Revit projects.
    try:
        original_ids = list(revit.uidoc.Selection.GetElementIds())
    except Exception:
        original_ids = []

    try:
        refs = revit.uidoc.Selection.PickObjects(
            UI.Selection.ObjectType.Element,
            _StraightGridSelectionFilter(),
            "Select straight host grids AutoDim may use, then click Finish."
        )
    except Exception:
        return None, []
    finally:
        # Preserve a Current Selection MEP scope if the Revit pick operation
        # changes the active selection set on a particular Revit build.
        try:
            from System.Collections.Generic import List
            restored = List[DB.ElementId]()
            for eid in original_ids:
                restored.Add(eid)
            revit.uidoc.Selection.SetElementIds(restored)
        except Exception:
            pass

    ids = []
    names = []
    seen = set()
    for ref in refs or []:
        try:
            elem = doc.GetElement(ref.ElementId)
            if elem is None or not isinstance(elem, DB.Grid) or not isinstance(elem.Curve, DB.Line):
                continue
            value = _eid_value(elem.Id)
            if value in seen:
                continue
            seen.add(value)
            ids.append(value)
            names.append(str(elem.Name))
        except Exception:
            pass
    return ids, names


def _load_engine(filename, module_name):
    # imp.load_source can reuse an existing module dictionary. Start fresh so
    # a previous run cannot retain document references or removed globals.
    sys.modules.pop(module_name, None)
    try:
        return imp.load_source(module_name, os.path.join(ENGINES_DIR, filename))
    except Exception:
        sys.modules.pop(module_name, None)
        raise


def _run_engine(filename, module_name, scope, grid_ids, grid_mode):
    try:
        module = _load_engine(filename, module_name)
        module.AUTODIM_SCOPE = scope
        module.AUTODIM_GRID_IDS = grid_ids
        module.AUTODIM_GRID_MODE = grid_mode
        module.AUTODIM_SUPPRESS_RESULT_DIALOG = True
        return module.main()
    finally:
        sys.modules.pop(module_name, None)


def _result_line(result, label):
    if not result:
        return "{0}: no result returned".format(label)
    return (
        "{0}: {1} certified dimension(s) | {2}/{3} locating target(s) certified | "
        "{4} run(s) + {5} branch axis/axes still uncertified | {6:.1f}s"
    ).format(
        label,
        result.get("created", 0),
        result.get("certified_targets", 0),
        result.get("cert_required", 0),
        result.get("uncertified_runs", 0),
        result.get("uncertified_branches", 0),
        result.get("runtime", 0.0),
    )


def _report_error(stage, exc, results):
    try:
        output.print_md("## AutoDim Smart {0} error".format(stage))
        output.print_md("```text\n{0}\n```".format(traceback.format_exc()))
    except Exception:
        pass
    message = "AutoDim Smart failed during {0}:\n\n{1}".format(stage, exc)
    if results:
        message += "\n\nCompleted before the error:\n" + "\n".join(
            _result_line(result, label) for label, result in results)
    if stage.endswith("engine"):
        message += ("\n\nThe interrupted run may have changed the model. "
                    "Review the view and Revit Undo history before running again.")
    message += "\n\nThe full error is in the pyRevit output window."
    forms.alert(message, title="AUTODIM SMART")


def main():
    if doc is None or doc.IsFamilyDocument:
        forms.alert("Open a Revit project before running AutoDim Smart.", title="AUTODIM SMART")
        return
    try:
        win = AutoDimWindow()
        win.ShowDialog()
    except Exception as exc:
        _report_error("menu", exc, [])
        return
    if not win.run_requested:
        return

    grid_ids = None
    grid_names = []
    if win.grid_mode in ("prefer", "strict"):
        grid_ids, grid_names = _pick_grid_ids()
        if grid_ids is None:
            return
        if not grid_ids:
            forms.alert(
                "No straight host grids were selected. AutoDim did not run.",
                title="AUTODIM SMART"
            )
            return
        win.selected_grid_ids = grid_ids
        win.selected_grid_names = grid_names

    results = []
    stage = "engine"
    try:
        if win.discipline in ("duct", "both"):
            stage = "DUCT engine"
            result = _run_engine("duct_engine.py", "robmep_autodim_duct_engine",
                                 win.scope, grid_ids, win.grid_mode)
            if result:
                results.append(("DUCT", result))

        if win.discipline in ("pipe", "both"):
            try:
                doc.Regenerate()
            except Exception:
                pass
            stage = "PIPE engine"
            result = _run_engine("pipe_engine.py", "robmep_autodim_pipe_engine",
                                 win.scope, grid_ids, win.grid_mode)
            if result:
                results.append(("PIPE", result))

    except Exception as exc:
        _report_error(stage, exc, results)
        return

    if not results:
        return

    summary = "AutoDim Smart complete.\n\n"
    summary += "\n".join(_result_line(result, label) for label, result in results)
    grid_summary = "All visible usable host grids"
    if win.grid_mode == "prefer":
        grid_summary = "Preferred ({0}) with v2.3 coverage fallback: {1}".format(
            len(grid_names), ", ".join(grid_names)
        )
    elif win.grid_mode == "strict":
        grid_summary = "Selected only / strict ({0}): {1}".format(
            len(grid_names), ", ".join(grid_names)
        )
    summary += (
        "\n\nScope: {0}\n"
        "Grid source: {1}\n"
        "Certification covers the defined target inventory. Review branch and terminal locations on the plotted sheet."
    ).format(win.scope.replace("_", " ").title(), grid_summary)

    if win.detailed and len(results) == 1:
        label, result = results[0]
        forms.alert(result.get("message", summary), title="{0} AUTODIM".format(label))
    else:
        forms.alert(summary, title="AUTODIM SMART")
        if win.detailed:
            try:
                for label, result in results:
                    output.print_md("## {0} AutoDim detailed result".format(label))
                    output.print_md("```text\n{0}\n```".format(result.get("message", "")))
            except Exception:
                pass


if __name__ == "__main__":
    main()
