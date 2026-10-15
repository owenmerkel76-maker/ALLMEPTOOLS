# Master repository audit — 2026-10-15

This is a source integration and development baseline, not a Revit-certified release.
The current user request takes precedence over the implementation directives embedded
in the supplied development plan: no major tool rewrites were started.

## Archive coverage and preservation

The master archive contains 220 files; the extension archive contains 149 files.
All 149 extension files are identical between the two uploads, so the master is
sufficient and no second extension tree is needed. Every master file was imported.
`import_provenance.json` records archive SHA-256 hashes and all original file paths,
sizes and hashes. `ribbon_path_migrations.json` maps the three relocated bundles.
All 124 extension files other than ribbon metadata remain byte-for-byte identical,
including Python, XAML, icons, settings defaults, startup and updater modules.
`source_inventory.csv` inventories the imported files and Python imports; the
machine-generated inventory is a baseline, not an assertion of live API correctness.
No ZIP files are included in the repository. Original uploads remain outside it.
The earlier five-package provenance in `merge_sources.json` is supplied history;
those five original archives were not separately provided or independently verified.

## Complete ribbon inventory

| Panel | Commands | Status |
|---|---|---|
| Hangers | Auto Hanger; Repair Draft Rods; Review Extra Hangers | Existing, needs Revit acceptance |
| AutoDim | AutoDim Smart | Existing duct/pipe engines |
| AutoTag | AutoTag Smart | Existing duct/pipe engines |
| Fab Hover | FabHover | Existing persistent engine and Shift-click configuration |
| Annotation | Tag Dim Organizer | Existing |
| Fabrication | Fab Ref Probe; Fab Ref Classifier | Existing diagnostics |
| Hanger Steel | Import Navis BOS; Joist Groups; Probe NWD; Reconstruct Steel | Existing structural utilities |
| Roof Deck | Roof Deck From DXF; Roof Deck From IFC | Existing host-proxy workflows |
| Schedules | ROBMEPTOOLS Schedule Number | Existing |
| Updates | Update Tool | Informational only; no automatic updates |

AutoSleeve is absent from BOTH archives. No fake working button or empty panel was
added: integrate the real implementation later into its own AutoSleeve panel.
The import has one production extension, one tab, 17 buttons, 47 Python files and 16 XAML files. The subsequent isolated connector foundation adds two Python files (49 total), without changing existing tool code.

## Findings and priorities

| Priority | Finding and evidence | Disposition |
|---|---|---|
| P0 | No Windows/Revit runtime is available here. CPython parsing is not IronPython 2.7/API/WPF verification. | Mandatory field gate in `REVIT_VALIDATION.md`; 2027 remains unverified. |
| P0 | Supplied field notes report wrong rods and excess supports. These were not reproduced in Revit here. | Preserve baseline; reproduce with source IDs, per-rod hits and rollback before fixes. |
| P1 | `Auto Hanger/planner.py:contiguous` joins by geometry, service and size; `group_runs` unions endpoint neighbors. This is not a connector graph, despite branch-stop wording. | Add connector fixtures and explicit topology stops before claiming graph correctness. |
| P1 | `planner.py:rule_spacing` embeds preliminary size-based caps; this is not a validated company rule profile or engineering certification. | Introduce reviewed profiles in a later focused change. |
| P1 | `Auto Hanger/script.py` reports `ifc_attached` / `roof_attached` counters. Geometry contact and native attachment semantics need API/field verification. | Audit actual host state before interpreting counts as physical structural attachment. |
| P1 | AutoSleeve and shared geometry/rule infrastructure were absent in the import. A later isolated connector-graph foundation now starts `robmep_core`. | Future features, not failed extraction. |
| P1 | Enabling PowerShell exposed legacy tests that depended on a deliberately removed production update manifest and old Annotation paths. | Corrected disposable fixtures only; no production manifest or updater activation. |
| P2 | FabHover launcher swallows broad exceptions in fallback paths. | Preserve hot-toggle behavior; later add bounded diagnostics without heavier event scanning. |
| P2 | Eight exact duplicate Python/XAML groups exist (`duplicate_sources.json`). Rod geometry, structural priority, roof geometry/surface helpers and WPF icons/themes are repeated. | Retain bundled copies until import isolation, WPF loading and persistent engines are tested. |
| P2 | Shared filenames such as `duct_engine`, `pipe_engine`, `geometry_utils`, `structure_priority` invite persistent-engine module collisions. Existing launcher tests cover some cleanup only. | Audit multi-command execution order in Revit before extracting libraries. |
| P2 | Legacy installers and updater libraries still reference the old MEPTOOL repository. | Historical compatibility source only. Use `INSTALL_WINDOWS.ps1`; never legacy install/package commands. |
| P2 | Supplied `unified_source_hashes.json` covers only a subset and historical paths. The original validator did not verify those hashes. | Retained historical manifest; added full import manifest and enforced runtime-preservation tests. |

No claim is made that all possible application bugs have been found. Automated
inventory, source review, existing behavioral tests and packaging validation support
this baseline; model-specific geometry and UI defects require Revit reproduction.

## Settings and dependencies

Cloud checks use Python 3.12 standard library, Git and optional PowerShell; no pip
packages are required. A checksum-verified PowerShell 7.4.13 bootstrap is supplied
for Linux x86_64 and kept outside the checkout. Revit 2025, its .NET APIs, WPF and a
compatible pyRevit IronPython 2.7 engine are Windows runtime prerequisites. They
cannot be installed as Python packages. No credentials, model paths, network
services or API keys are required for offline testing or manual deployment.

Button names are unchanged. pyRevit's documented `script.get_config()` defaults to
`command_name + '_config'`, so panel moves keep those section names. AutoHanger's
explicit `universal_ifc_structure` section is unchanged. FabHover retains
`%APPDATA%/FabHover/display_options.ini`. Back up pyRevit configuration and this INI
before deployment; user-specific settings were not supplied and cannot be field
verified here. Installer backups retain extension-local custom files but do not
merge them automatically into a newly installed extension.
Reference reviewed: https://github.com/pyrevitlabs/pyRevit/blob/master/pyrevitlib/pyrevit/script.py

## Delivery and verification

Use `bash CODEX_SETUP.sh` for both validators and the full discovered unit suite.
See `VALIDATION_RESULTS.md` for actual outcomes, including legacy test fixes.
CI runs the same entrypoint. The supported manual install is tested for fresh
install, repeat-install backup, active updater refusal and copy-failure restoration.
Those tests stub Windows process/task discovery; they are not Windows/Revit proof.
No old scheduled task is registered by the actual setup. No old updater packaging
command was executed. Source is ready for a controlled Revit field test, not broad
production rollout. See `ROADMAP.md` and `NEXT_CODEX_TASK.md` for next work.
