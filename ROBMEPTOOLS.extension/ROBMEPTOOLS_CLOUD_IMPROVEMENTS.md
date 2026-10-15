# Revit 2025 / IronPython 2: launcher reliability update

This update changes only the AutoDim Smart and AutoTag Smart launchers.
The duct/pipe geometry engines, menus, and fabrication tools are unchanged.

- AutoDim loads a fresh engine per discipline and removes it from the Python
  module cache after success or failure, matching AutoTag's run-local approach.
- Both tools remove partially imported engine modules after import failure.
- If Duct completes and Pipe fails, both launchers show the completed Duct
  result alongside the Pipe error. They stop at the failed discipline.
- Menu errors now write their full traceback to the pyRevit output window.
- Both tools check that a project document is open before showing their menu.
- Engine errors explain that the interrupted run may have changed the model;
  review the view and Undo history before rerunning. This update does not
  introduce a transaction group or automatic rollback of completed disciplines.

## Validation

All 17 Python files parse with the cloud Python 3 validator, all 12 XAML files
are well-formed XML, and six button packages have their required files. The
legacy grammar parser also accepts all 17 Python files; this is not a full
IronPython runtime compatibility check. Nine automated tests exercise the
actual launcher function definitions with simulated host dependencies.
No Revit runtime, WPF loading, API transaction, or geometry test has run here.

## Installation

Close Revit. Back up the installed ROBMEPTOOLS.extension. Extract this archive
and copy the complete ROBMEPTOOLS.extension into your pyRevit extensions folder,
normally %APPDATA%\pyRevit\Extensions, replacing the backed-up installation.
Keep IronPython 2 selected. Restart Revit 2025 and open a disposable model copy.

Verify both menus open and Cancel makes no changes. Test Duct and Pipe separately
with a small selection before trying Both or Active View. Check dimension
references, measured values, tag types, duplicate handling, and placement.
For any failure, capture the full pyRevit traceback, the tool/options used,
and the installed pyRevit release version. The engine number 2712 alone does
not identify the pyRevit release.
