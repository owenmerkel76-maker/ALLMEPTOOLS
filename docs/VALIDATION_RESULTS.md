# Validation results — 2026-10-15 master baseline

- `bash CODEX_SETUP.sh`: PASS. Runs both validators and the full unit suite.
- Extension validator: 47 Python files, 16 XAML files, 17 buttons; PASS.
- Unified validator: 17 commands, 10 panels; PASS.
- Python 3.12.14, PowerShell 7.4.13: **348 tests, all passed, zero skips**, 52.385 seconds.
- Includes all legacy regression checks, two source-preservation checks and three
  supported manual-installer checks (fresh/repeat backup, updater refusal, rollback).
- Both archive extension trees: 149/149 identical file hashes.
- All 220 master source files retained; all 124 non-metadata extension files unchanged.
- Five `tools/build_*.py --help` commands: PASS imports and argument parsing with
  NumPy 2.3.5 / PyMuPDF 1.26.6. Actual report PDFs not generated (fixtures absent).
- Initial suite without PowerShell: 343 tests, 302 passed, 41 skipped. Installing
  checksum-verified PowerShell exposed stale legacy fixtures. Corrected them with
  disposable manifest objects/files and historical path expectations. No production
  update manifest was added and no real scheduled task was registered.
- One early overlapping PowerShell run had a native-process exit; final sequential
  run completed all cases successfully. No failing check is counted as a pass.
- Imported sources contain existing trailing whitespace (including Markdown line
  breaks). It is retained to preserve runtime/source hashes; generated inventory
  uses LF. No format-only rewrite was performed.

Not run: Windows PowerShell 5.1, Revit API, IronPython 2.7, WPF loading, actual
Windows task enumeration, live model mutations, fabrication services/ITM content,
IFC/native structural attachment, Revit 2027, GitHub-hosted CI. See
`REVIT_VALIDATION.md`. This is cloud development readiness, not field certification.

## Subsequent Phase 1 connector foundation

`bash CODEX_SETUP.sh`: PASS, **362 tests, zero skips**, 54.916 seconds.
Extension validator now checks 49 Python files, 16 XAML files and the same 17
buttons. Fourteen new connector-graph tests pass. All 124 original non-metadata
extension files still match their imported hashes. See `PHASE1_CONNECTOR_GRAPH.md`;
the analyzer has no live Revit adapter or model-mutation integration yet.

## Clean Python 3.12 CI investigation

The original Actions run at commit `d4c3380` failed with one error among 362 tests.
A diagnostic run, https://github.com/owenmerkel76-maker/ALLMEPTOOLS/actions/runs/38792013872,
exposed the complete traceback: `test_reload_updater.py` attempted to patch
`distutils.spawn.find_executable`, which requires importing a module removed from
CPython 3.12. The cloud Python had setuptools' distutils shim installed, masking
this undeclared test dependency. This was not a missing extension path, a Revit
runtime failure, a PowerShell-version failure or a failed ribbon validator.

`robmep_updater.find_git` is legacy IronPython 2.7 host code, where distutils is
available. The test already mocked its executable lookup; the corrected fixture
explicitly supplies the mocked host modules via `types.ModuleType` and
`unittest.mock.patch.dict`. The real rediscovery/deployment code still runs and
all prior assertions remain, with an additional assertion for both Git lookups.
No setuptools dependency or production runtime modification is necessary.

Reproduced before the fix in a fresh `python3 -m venv` (no system packages or
setuptools): the single targeted test failed with the exact ModuleNotFoundError.
The same targeted test passes after correction. The workflow still uses Python
3.12 and the same `bash CODEX_SETUP.sh` entrypoint. Its logging uses pipefail and
annotates failures; an intentional exit-7 probe verified failure propagation.

Complete corrected setup in that clean Python 3.12 environment with PowerShell
7.6.6: **362 tests passed, zero skips**, 49.887 seconds. Both validators pass:
49 Python files, 16 XAML files, 17 commands across 10 panels. `bash -n
CODEX_SETUP.sh` also passes. All original runtime source-preservation checks pass.

## EVOLVE research and read-only Revit connector snapshot increment

- Retrieved 17 official EVOLVE help/release articles successfully; public-source
  metadata and implementation implications are saved under `docs/research/`.
- Added 24 adapter/launcher tests. An enumeration-order regression first reproduced
  an axis-direction flip, then passed after sorting end connectors by stable ID.
- Final `bash CODEX_SETUP.sh` in a clean CPython 3.12 venv with PowerShell 7.6.6:
  **386 tests passed, zero skips**, 48.521 seconds.
- Both validators pass: 51 runtime Python files, 16 XAML files, 17 commands and
  10 panels. Existing 124 non-metadata import hashes remain unchanged.
- Live Revit 2025/IronPython loading, actual connector semantics, pyRevit Shift-click
  dispatch and document-modified/Undo checks are NOT RUN. Revit 2027 is unverified.
  Follow `REVIT_CONNECTOR_DIAGNOSTIC.md` before any placement-path integration.

## First Revit field feedback: transitions and origin gaps

The user ran the initial diagnostic in Revit 2025.4 and reported eight selected
parts, five readable parts and three CONNECTED_ORIGIN_GAP rejections on a route
containing transitions. The original 0.0001-foot coincidence requirement was an
extra geometric assumption, not the reciprocal physical-connection API proof.
It also caused selected rejected owners to be mislabeled OUTSIDE_SCOPE.

The revised diagnostic preserves reciprocal API topology, reports measured origin
gaps without moving/repairing geometry, and separates connected selected networks
from uniform straight spans through fittings and transitions. Actual owner IDs
are retained for both selected and referenced parts; rejected selections have
explicit rejection boundaries. Incomplete records still block uniform spans.

Eight added regressions cover reciprocal-proof preservation, warning measurements
and units, stable deduplication, selected-rejection labeling, and transition
network connectivity. `bash CODEX_SETUP.sh`: **394 tests passed, zero skips**,
43.840 seconds; both validators pass (51 Python files, 16 XAML files, 17 commands).
Original tool source-preservation checks pass. The revised code requires a retest
on the same selection; synthetic gap fixtures are not a reproduction of the
actual model's offsets, and no geometry/spacing/rod claim has been verified.

## Hanger UI and batching evaluation increment

`bash CODEX_SETUP.sh`: **401 tests passed, zero skips**, 47.077 seconds,
with cloud CPython 3.12 and PowerShell 7.4.13. Both validators pass: 52 Python
files, 16 XAML files, 17 commands across 10 panels. Seven added regressions cover
legacy-equivalent identity batching, ordering, input preservation, malformed jobs,
caller integration, all 15 named XAML controls, numeric/controller defaults,
primary-mode visibility and advanced-state bindings. Original import manifest
unchanged; all 124 original files checked (122 baseline matches, two exact
intentional changes documented in `runtime_change_log.json`).

Official-source evaluation and scoped microbenchmark results are in
`research/HANGER_TOOL_COMPARISON_2026-10-15.md`. XML parsing/control contracts do
not verify actual WPF rendering/NameScope behavior, IronPython execution, Revit
probe timing, real hanger placement/attachment, or model rollback. Those remain
field-test gates. No geometry, attachment or collision check was removed.

## Read-only route station preview increment

`bash CODEX_SETUP.sh`: **425 tests passed, zero skips**, 66.841 seconds,
CPython 3.12 / retained PowerShell 7.4.13. Both validators pass: 54 runtime
Python files, 16 XAML files, 17 commands across 10 panels. Added 24 focused
regressions for aligned fitting distances, no fitting-host candidates, strict
size caps, reversed axes, stable ordering, physical-vs-geometric groups, scope,
branch keep-outs, gap/service/unsupported boundaries, ambiguous ends, existing
host/Origin inventory, unreadable data and zero additional coordination candidates
on a simulated rerun. All source-preservation checks pass; original normal-click
script/planner/settings hashes are unchanged from the previous preview.

Four changed/new runtime modules also parsed with the available legacy grammar;
this is a syntax screen, not an IronPython execution test. Live pyRevit menu,
connector normals, candidate offsets/XYZ, actual existing hanger Origins and
Revit no-edit/Undo behavior remain unverified. No rods, structural attachment or
hardware clearance is certified. See `HANGER_ROUTE_PREVIEW.md` for the field gate.

## Existing-first distance coverage correction

A later field report contained 17 readable parts, 13 existing hangers, six partial
routes and four candidates. A synthetic 4.7-ft route with a branch and two
existing stations reproduced a false unresolved result: the from-scratch branch
candidate pass failed and the preview assigned maximum_ft=None. Two new tests
failed before correction. Spacing resolution and existing distance coverage are
now evaluated before requesting new candidates; existing near-branch clearance
warnings remain independent. Actual private-model branch coordinates were not
available offline, so the synthetic case establishes the code defect, not a
complete reproduction of the model.

`bash CODEX_SETUP.sh`: **429 tests passed, zero skips**, 44.165 seconds,
CPython 3.12 / PowerShell 7.4.13. Both validators pass (54 Python files, 16 XAML,
17 commands / 10 panels). Four additional regressions cover the reproduced
withholding defect, retained existing-branch warnings, unsupported rules/unknown
inventory and genuine end shortfalls retaining candidate branch checks. A manual
API-double launcher smoke verified branch positions, nearest existing IDs and
axial-separation warning rows in the actual report function. Source-preservation
checks pass; normal-click script, planner and settings are unchanged.

Live Revit retest, structural support/clearance/attachment and the remaining
incomplete existing-aware branch candidate solver are not verified or resolved by
this focused reporting/planning-order correction. All routes remain non-apply-ready.
