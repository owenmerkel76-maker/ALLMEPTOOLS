# Windows / Revit acceptance record

Status: NOT RUN in this Linux environment. Record Revit build, pyRevit version,
IronPython engine, repository commit, fixture revision and result for each case.
Test on a detached model copy; keep baseline model and settings backups.

1. Close Revit; disable old `ROBMEPTOOLS Auto Update ...` scheduled tasks. Run
   `INSTALL_WINDOWS.ps1 -ExtensionsRoot <registered custom-extension parent>`.
   Keep standalone extensions outside scanned paths. Confirm backup and rollback.
2. Load Revit 2025 and Reload pyRevit. Confirm one ROBMEPTOOLS tab, ten panels,
   17 buttons, icons, tooltips, Shift-click settings and no import errors.
3. Confirm AutoDim, AutoTag and Organizer preferences survived; verify the explicit
   structure-source configuration and FabHover INI. Do not replace user settings.
4. AutoDim: duct and pipe, selected/all grids, rotated grids, distinct branches,
   real physical references, 64-bit IDs, no zero dimensions, reruns and undo.
5. AutoTag: duct/pipe profile transitions, risers, distinct element coverage,
   family/leader presets, no duplicate tags and mixed-view obstacle layouts.
6. Organizer: preserve meaning/coverage and manual placements; test tag/tag,
   tag/dimension, dimension/dimension conflicts, view scale and crop boundaries.
7. FabHover: hot-toggle repeatedly, Shift-click settings, reload and multiple
   documents; verify no duplicate handlers/windows, stale data or idle slowdown.
8. AutoHanger: start with a rolled-back one-duct/one-hanger diagnostic. Then test
   one 15-foot straight, five connected 3-foot pieces, branches, fittings, slope,
   parallel runs and existing/manual supports. An unchanged rerun creates zero
   new hangers. Check end/branch constraints against approved job rules.
9. Structural sources: rotated/transformed IFC/RVT, sloped joists, separate roof
   elevations and missing/unreadable geometry. Measure each rod independently.
   Missing hits remain unresolved; geometry contact is not native attachment.
10. Repair Draft Rods and Review Extra Hangers: operate only on intended scope;
    retain unrelated/manual items. Check rod host state and cancel/rollback.
11. Structural utilities: Joist Groups, Reconstruct Steel, Import Navis BOS and
    Probe NWD against a known geometry fixture and explicit units/transforms.
    Roof DXF/IFC tools create proxies; compare geometry, not assumed flute detail.
12. Schedule Number: duplicates, grouped schedules, selected scope, read-only
    parameters, deterministic rerun and undo. Verify no unintended renumbering.
13. Updates: informational button/startup perform no remote update. Confirm no
    legacy task can overwrite the unified extension.
14. Run commands in mixed order, particularly helpers with identical module
    names. Cancel dialogs and force controlled transaction failures; no model
    residue or stale persistent-engine state is acceptable.
15. Repeat independently in Revit 2027 once a supported runtime is available.
    AutoSleeve tests are pending actual source/implementation, not passed.

For failures capture command, source IDs, linked source/transform, actual vs expected
geometry, rule profile, created/skipped/unresolved counts and transaction result.
Remove private project names/paths from logs before committing fixtures.

Phase 1 addition: run the Auto Hanger Shift-click diagnostic cases in `REVIT_CONNECTOR_DIAGNOSTIC.md` before preview/apply migration. A passing offline double is not evidence that actual Revit connector semantics or engine loading have passed.
