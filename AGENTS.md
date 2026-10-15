# Codex agent instructions — ROBMEPTOOLS master workspace

You are editing the **entire ROBMEPTOOLS pyRevit ribbon**, primarily targeting Revit 2025 and IronPython 2.7 (Revit 2027 is a future compatibility target). This repository's only production-source tree is `ROBMEPTOOLS.extension`.

## Absolute rules

1. **Never destroy stable tool behavior to refactor architecture.** First read actual scripts, XAML, bundled helpers, original-tool notes, tests, and previous release feedback. Prefer small, independently testable changes with a concise changelog.
2. **Revit 2025 + IronPython 2.7 compatibility.** Don't introduce Python 3 syntax, CPython-only packages, or unsupported Autodesk APIs into pyRevit runtime scripts. Use WPF/.NET via supported Revit/pyRevit interfaces. Revit 2027 support requires separate verification.
3. **User-facing ribbon remains ROBMEPTOOLS.tab.** Retain all 17 existing commands and avoid duplicate extension tabs. Preserve FabHover's hot-toggle/persistent-engine performance.
4. **No legacy auto-update.** `startup.py` deliberately does not invoke the older remote updater; `Updates` is informational only. The old Windows Scheduled Task must be disabled before installing. Do **not** run `tools/package_autoupdate.py`, install the legacy updater task, reactivate startup updater, or publish to the old release channel unless explicitly authorized and migration-safe.
5. **Do not assume ifc geometry is native hosting.** Transform all linked geometry into the correct host coordinates. Distinguish solid/mesh geometric ray hits from real Revit host relationships. Keep rods explicitly UNATTACHED when they have geometry only; don't claim attachment.
6. **Never guess rod lengths**, target elevations, reference levels or structural BOS. Per-rod ray-hit results take precedence. For failure/unreadable geometry, report unresolved and do not silently use bbox, global level, fabricated elevation or arbitrary fallback.
7. **Hanger layout must be run-level, not every independent duct segment**; verify connector-based topology, end/branch offsets, conservative spacing by size/service/installation configuration, existing hanger coverage, collision envelopes, and nonduplicate planned stations. SMACNA or code spacing rules must be user-configurable, documented and verified, not blanket universal certification.
8. **AutoSleeve has NOT been supplied or merged.** Treat it as a new feature; implement with verified native/linked wall & floor solids, per-service/rule clearance, fitting-aware intersections, box-out consolidation and non-destructive preview. DWG hatches alone are not proof of solid-wall penetrations.
9. **Annotation:** preserve true physical duct/pipe references and distinct IDs. No fake helper references as source-coverage proof, no invented BOD/BOP values, no collapse of distinct branches just because values match. Protect annotations from clashes with MEP and each other. Retain the latest human-plan benchmark expectations from the source reviews.
10. **Diagnostics and safety:** preview by default for major model mutations, include explicit transaction rollback on error, actionable counts (created/skipped/unresolved), source element IDs, reason codes, model/reference provenance. Do not silently delete existing hangers or overwrite tags.
11. **Source provenance and clean builds:** keep `docs/merge_sources.json` and new `CHANGELOG.md` accurate; no copy-paste of proprietary EVOLVE source. Its public behavior is a functional benchmark, not code to copy.

## Shared framework roadmap (no premature mass rewrite)

- Central MEP element inventory supporting FabricationPart duct/pipe, straight/fittings, connected run graphs, category/service/material filters, visibility and linked model picker.
- Structure picker and geometry adapters (RVT/IFC linked solids, sloped/tapered members, roof deck host proxies), coordinate transforms, per-rod hit confidence, collision queries.
- Validated rule profiles for spacing/sizing, hanger ITM service/button selection, hanger instance idempotence, draft-vs-native attachment, and isolated transaction-safe preview.
- Sleeve geometric intersection engine and box-out selection; shared parameter mappings; annotation layout and schedule data; spooling and point export in later milestones.

## Master repository integration notes

The current ribbon has 10 panels: AutoDim, AutoTag and Fab Hover have dedicated panels. All 17 original button names are preserved. Intentional runtime edits require exact baseline/current hashes and reasons in docs/runtime_change_log.json; source-preservation checks continue to cover every imported asset. AutoSleeve remains absent. See docs/REPOSITORY_AUDIT.md and docs/NEXT_CODEX_TASK.md. Existing tasks are isolated: use the existing checkout and do not create a worktree unless the user asks.

## Tests required with each change

```text
python tools/validate_extension.py
python tools/validate_unified.py
python -m unittest discover -s tests -q
```

Add focused pure-logic tests for planner/rules, dimensions and dependency isolation. No CPython test can simulate live Revit API, WPF engine behavior, native ITM hangers or full model geometry, so report those as untested until real Revit field tests. Prefer one-duct single-hanger rolled-back diagnostic, then 1 short run, then branched/sloped/full-area stress cases.

## Working expectations

- Keep single clear issue/milestone in progress; use `CODEX_START_HERE.md` for priorities.
- Preserve field-test diagnostics and resolve root causes instead of piling fallback guesses onto unreliable results.
- No secrets or project model paths in public commits; no silent internet downloads or scheduled tasks.
- On completion, list changed files, exact tests and results, anything not tested in Revit, and install/update steps.
