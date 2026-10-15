# Duct AutoDim 6.2 grid-axis review

This build includes the Duct AutoTag Review 1 changes and a targeted AutoDim grid discovery correction. Target: Revit 2025 / pyRevit IronPython 2. Actual model execution has not been performed.

## Correction

The inherited collector queried grids in the active view and queried the host document only when that operation threw an exception. A successful view collection that omitted an entire grid orientation could leave ducts on that orientation without the appropriate grid candidate.

The collector now inventories host-document straight grids as well as view grids. Eligible view grids retain priority, so a closer fallback grid does not change an already usable view-grid assignment. When no eligible view grid can locate a target, a host-document grid can supply the missing direction. Prefer-selected mode still prioritizes selected grids. Selected-only mode remains strict and never uses an unselected grid to pretend coverage is complete. Selected IDs can be resolved directly even when view collection omits them. Distance limits and parallel-reference rules remain enforced; linked and curved grids remain unsupported.

The JSON audit now includes usable grid names, IDs, axes, selection membership, view/fallback classification, rejected grid reasons, collection warnings, and each target's source direction and assigned grid direction. The completion report includes view and host-fallback candidate counts.

This addresses a demonstrated discovery failure in the source. It does not establish that this is the cause in the user's particular model; selected-grid restrictions, linked grids, missing references, nonparallel geometry, and placement/certification failures may also explain missing dimensions.

## Install and verify

1. Close Revit and back up the installed extension. Copy only the ZIP's ROBMEPTOOLS.extension folder into %APPDATA%\pyRevit\Extensions. Restart Revit 2025 with IronPython 2.
2. Test on a disposable model copy. Use All grids to check the entire host-grid inventory. If using Selected only, select eligible grids from both directions; the tool will not invent a missing selected direction.
3. Test one duct running along each direction. For a straight locator, AutoDim measures the offset normal to a grid parallel to the duct. It does not produce two arbitrary orthogonal dimensions from an incompatible rectangular-duct side reference.
4. Inspect grid fallback counts and missing/uncertified targets. Verify dimensions are visible, reference the intended named grid, show the correct edge or center value, survive commit, and Undo correctly.
5. If an axis remains absent, save the AutoDim target audit JSON shown by the completion report and a screenshot of the missing area, with the grid names and chosen grid mode visible. These distinguish missing inventory from failed reference creation and placement.

Existing user dimensions are not deleted by this discovery change. Host-grid fallback may use a datum omitted from the view collector; inspect whether its witness/reference is visible and appropriate in the plotted plan. Helper lifecycle and family/model behavior remain subject to the inherited acceptance requirements.

## Validation

141 host tests passed, including nine new grid-axis tests covering a successful partial view collection, both orthogonal assignments, preserved view priority, preferred/strict selection, direct selected-grid lookup, empty view inventory, distance limits and curved-grid rejection. Static validation passed for 17 extension Python files, 12 XAML files and six buttons. Tests simulate Revit API surfaces and do not certify Windows/Revit execution.

From the unpacked directory:

    python3 tools/validate_extension.py
    python3 -m unittest discover -s tests -v
    python3 tools/package_autodim_axis_review.py
