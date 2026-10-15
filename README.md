# ROBMEPTOOLS — Unified Codex development workspace

**2026-10-15 integration build / not field certified.** This repository is the **authoritative source** for a single `ROBMEPTOOLS` pyRevit ribbon assembled from the five packages supplied in `NEW ALL ROB MEP TOOLS.zip`.

## Start here

- **`CODEX_START_HERE.md`** — pasteable Codex initialization prompt and architecture.
- **`AGENTS.md`** — development guardrails and test policy for Codex.
- **`ROBMEPTOOLS.extension/`** — the only extension folder to install/modify for this unified ribbon.
- **`INSTALL_WINDOWS.ps1`** — deploy to a specific pyRevit Custom Extensions parent folder with prior extension backup (Revit must be closed).
- **`tools/validate_extension.py`** and **`tests/`** — source-level tests (no Revit required).
- **`docs/research/ROBMEPTOOLS_EVOLVE_Research_and_Codex_Masterplan.md`** — longer EVOLVE-like functionality research (roadmap, **not implemented**).
- **`docs/original_tool_notes/`** — original notes and known limitations for hanger, steel and roof tools.
- **`docs/merge_sources.json`** — component provenance.

## Active tab and commands — 17 total (10 panels)

| Ribbon panel | Commands |
|---|---|
| AutoDim | AutoDim Smart |
| AutoTag | AutoTag Smart |
| Annotation | Tag Dim Organizer |
| Fab Hover | FabHover |
| Fabrication | Fab Ref Probe, Fab Ref Classifier |
| Hangers | Auto Hanger, Repair Draft Rods, Review Extra Hangers |
| Hanger Steel | Joist Groups (Slope Joists), Reconstruct Steel, Import Navis BOS, Probe NWD |
| Roof Deck | Roof Deck From IFC, Roof Deck From DXF |
| Schedules | ROBMEPTOOLS Schedule Number |
| Updates | Manual Update Info — intentionally non-networked |

**What was done:** Original modeling/annotation/hanger tool scripts were copied unchanged into the unified ribbon; tab/panel bundle layouts were updated; `startup.py` and the old update-button script were replaced with safe non-updating versions. This is a **ribbon/package integration**, not yet an implementation of a common MEP geometry engine, shared settings, AutoSleeve, or finished EVOLVE-equivalent behavior.

**AutoSleeve is not present in the supplied ZIP.** Do not claim it was merged. Add it only when its real code is provided or a new implementation has been built and tested. Neither hanger accuracy nor IFC/RVT structural attachment nor Revit 2027 has been verified in a running Revit instance.

## Installation (Windows, Revit closed)

1. Extract this project completely and open PowerShell in this directory.
2. Disable any old Windows Task Scheduler task named `ROBMEPTOOLS Auto Update ...`; this installer **blocks** when one is enabled. These old tasks can overwrite the new ribbon even though the extension startup updater is disabled.
3. Run `powershell -ExecutionPolicy Bypass -File .\INSTALL_WINDOWS.ps1 -ExtensionsRoot "C:\path\to\your\pyRevit\CustomExtensionsParent"` (use **your actual** path registered under pyRevit Settings > Custom Extensions). With no parameter, the installer prompts for the folder.
4. Keep original, standalone `ROBMEPHANGERS.extension`, `STEELTOOLS.extension`, `ROOFDECKTOOLS.extension`, `ScheduleNumber2025.extension` backups **outside pyRevit-scanned folders** before checking the one-ribbon layout, to avoid duplicate tabs/commands. Installer **does not delete** these.
5. Open Revit 2025, click pyRevit > Reload and verify the ten panels. Revit 2027 is only a target pending testing.

Do not work on a live job to verify destructive tools. Use a detached model copy and preview/rollback modes where available. Hangers can be geometry-sized but **unattached**; they do not certify structure, anchors or support loads. Roof Deck commands create host proxies, not flute-accurate deck.

## Codex environment setup

For a new Codex workspace, use `bash CODEX_SETUP.sh` as the **environment install/setup script**. It runs source validators and the unittest suite and does not attempt to install Revit/pyRevit in the cloud. Use `CODEX_START_HERE.md` for the first Codex instruction.

## Local offline validation

```text
python tools/validate_extension.py
python -m unittest discover -s tests -q
python tools/validate_unified.py
```

Old updater's release synchronization test is archived under `legacy/original_update_tests/`, because its published hash manifest and ZIP apply to an **older unmerged build**. Most existing updater unit tests are retained only to document legacy behavior; they do not enable that updater. Do not run `tools/package_autoupdate.py` or any old updater install CMD from the legacy files.

**Manual code review, test harnesses and static syntax tests do not prove Revit functionality.** The complete tool set needs Windows Revit 2025 testing, especially sleeve integration (not present), ITM creation and rod lengths, linked IFC ray casting, and diagnostics.

## Repository audit and next work

See [repository audit](docs/REPOSITORY_AUDIT.md), [validation results](docs/VALIDATION_RESULTS.md), [Revit checklist](docs/REVIT_VALIDATION.md), [roadmap](docs/ROADMAP.md), and [next task handoff](docs/NEXT_CODEX_TASK.md). All runtime code and settings defaults from the uploads are preserved; three bundles moved into dedicated panels. AutoSleeve source was not supplied.

Cloud development uses Python 3.12 with no pip dependencies. For PowerShell-backed tests on Linux x86_64, run `python3 tools/install_powershell.py` before `bash CODEX_SETUP.sh`; the pinned toolchain stays outside the repository. This does not install Revit. Use only `INSTALL_WINDOWS.ps1` for manual Windows deployment; the legacy installer directory is historical compatibility code.

Optional PDF comparison tools use `requirements-reports.txt` in a CPython virtual environment; NumPy/PyMuPDF are not pyRevit runtime dependencies. All five report CLIs import successfully here, but original comparison PDFs are absent.

Phase 1 has started with a tested, isolated connector-graph foundation in `lib/robmep_core`. See [implementation status](docs/PHASE1_CONNECTOR_GRAPH.md). Live AutoHanger integration awaits a verified Revit connector adapter.
