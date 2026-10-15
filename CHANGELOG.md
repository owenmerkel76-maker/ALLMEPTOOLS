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

## 2026-10-15 — Clean Python 3.12 CI fixture correction

- Fixed the legacy Git-rediscovery test's implicit dependency on a setuptools-provided distutils shim. The test now supplies its mocked IronPython dependency through standard-library module fixtures and verifies both PATH lookups before checking actual rediscovery/deployment.
- Kept every offline check and all 362 tests enabled; no production extension files, settings or ribbon layouts changed.
- Added Actions failure annotations while preserving pipeline exit status, so failing tracebacks remain available through the Checks API.

## 2026-10-15 — EVOLVE research and read-only connector diagnostic

- Reviewed 17 official EVOLVE help/release pages and recorded source metadata, version conflicts and requirements mapped to ROBMEPTOOLS.
- Added a host-model FabricationPart snapshot adapter with reciprocal physical connection proof, scope/error diagnostics, stable axes and 64-bit source IDs.
- Added Auto Hanger Shift-click topology output without changing the normal-click placement script or adding ribbon commands.
- Added 24 API-double/launcher tests and a detailed Revit 2025 field gate. Live Revit/IronPython and linked geometry remain unverified.

## 2026-10-15 — Connector diagnostic field feedback

- Retain reciprocal physical API connectivity when connector origins differ; show deduplicated measured gap warnings with numeric element/connector IDs and units. No geometry is moved or declared continuous.
- Distinguish selected-but-rejected and unsupported selected parts from genuinely unselected OUTSIDE_SCOPE references. All incomplete data still blocks uniform-span planning across that boundary.
- Report connected selected networks through transitions/fittings separately from uniform straight spans. Display summed part lengths as such, excluding fitting/connection offsets.
- Add eight regression tests for gap proof, units/identity display, selection state, and transition network continuity. Normal-click placement and original tool files remain unchanged.

## 2026-10-15 — Hanger workflow evaluation, simpler settings and stable batching

- Compared official EVOLVE, Autodesk Revit 2025 and Trimble SysQue public workflows with actual hanger code; recorded evidence, retrieval limits and prioritized topology/rule/UI/profiling gates.
- Simplified Auto Hanger settings using a closed Advanced section. Kept all named controls, service mapping, numeric/controller defaults, visible safe modes and explicit UNATTACHED policy. Live summaries expose hidden clearance/fitting option states.
- Replaced repeated full-task identity scans with one stable identity-preserving batching pass. Geometry, rod verification, probe budgets, transactions and clearance checks are unchanged.
- Added seven focused regressions and a reproducible optional Python batching benchmark. No Revit speedup or WPF runtime result is claimed.
- Preserved the import manifest and continued checking all 124 original assets with an exact two-file change ledger (122 unchanged). No validation was disabled.

## 2026-10-15 — Read-only fitting-aware route station preview

- Added a Shift-click mode for horizontal straight-through route station previews, reusing the existing size/spacing and support-count planner. No normal-click placement changes or new ribbon commands.
- Retained connector port identities and optional fitting normals for verified aligned transitions; gaps, turns, offsets, ambiguous ends, unsupported geometry and source/service changes remain boundaries. Fitting bodies never host candidates.
- Added read-only existing-hanger host/Origin inventory, exact ID deduplication, conservative unknown-data handling and coordination-only coverage checks. No bbox, rod or structural-attachment fallback.
- Added candidate ID/station/XYZ and unresolved-reason tables plus a clearly scoped geometric baseline. All results remain non-apply-ready; approved profiles and Revit field gates are documented.

## 2026-10-15 — Existing-first read-only distance coverage

- Fixed a reproduced preview defect where a new-candidate branch conflict erased the size-based spacing limit and falsely prevented evaluating existing distance coverage.
- Resolve spacing independently and evaluate known existing end/span/branch distances before requesting new candidates. Already distance-covered routes propose zero additions.
- Keep near-branch existing hangers explicitly clearance-unverified, with source IDs/separations. Unknown inventory, unsupported rules and incomplete coverage retain conservative handling; candidate branch checks are unchanged.
- Changed report wording to distinguish covered distances from unverified clearance. Normal-click placement, rods, transactions and all 17 commands are unchanged.

## 2026-10-15 — Visual station review and exact rolled-back diagnostic

- Added a third Shift-click mode with bounded, numbered temporary graphics and a candidate-host/station chooser. Removes only owned controls; no model marker elements or global graphics clearing.
- Revalidates original geometry/ports and refreshed existing-hanger occupancy before a candidate test. Uses actual end connector identities and the exact preview coordinate; rejects stale/off-axis/inboard-range failures instead of relocating.
- Reuses the original structural selector, service hanger chooser and both-rod inspection inside rollback scopes. New diagnostic settings cannot enable apply mode or disable rod clearance. Original normal-click and manually picked single-test behavior are retained.
- Guarded the normal script entrypoint for diagnostic loading and updated its exact provenance hash/reason. Added focused API-double cleanup, identity, cancellation, measurement and rollback regressions; native graphics/ITM behavior still requires Revit 2025 field verification.
