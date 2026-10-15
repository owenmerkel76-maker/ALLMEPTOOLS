# Unified ROBMEPTOOLS changelog

## 2026-10-15 — Integration baseline

- Consolidated the five provided tool groups into a single `ROBMEPTOOLS.extension/ROBMEPTOOLS.tab`: 17 pushbuttons, 7 panels.
- Added Hangers (3), Hanger Steel (4), Roof Deck (2), and Schedules (1) to pre-existing Annotation (3), Fabrication (3), Updates (1) panels.
- Copied all functional command scripts and their local helpers without rewriting logic. Replaced obsolete startup and old remote update button with safe manual-update behavior, archived originals.
- Added Codex guidance, install script with backup, current capability/status manifest, EVOLVE research reference, unified validators, and explicit disclosure that AutoSleeve is NOT in supplied source.
- Excluded archived PDFs and old release ZIPs from this lean Codex source package; originals remain in user's uploaded archive.
- No live Revit 2025/2027 run or physical IFC test was performed here.

## 2026-10-15 — GitHub master import

- Imported all 220 master files; verified all 149 extension files match both uploads.
- Split AutoDim, AutoTag and Fab Hover into dedicated panels, preserving all 17 commands and all 124 non-metadata extension files byte-for-byte.
- Updated test paths; isolated legacy manifest fixtures without enabling remote updates.
- Added runtime preservation checks, manual installer integration tests, CI and checksum-verified optional PowerShell bootstrap.
- Added complete source/archive inventory, duplicate report, audit, roadmap and Revit acceptance checklist. No AutoSleeve code was supplied; no model-tool rewrites were made.

## 2026-10-15 — Phase 1 connector foundation

- Added a pure connector-snapshot graph analyzer with cumulative run lengths and explicit topology boundaries.
- Added 14 tests for connected runs, branches, source/service/profile boundaries, invalid input, scope, cycles and deterministic reruns.
- Existing ribbon logic remains byte-identical to the import. Live Revit connector collection and AutoHanger integration are pending separate validation.
