# Recommended development roadmap

1. **Baseline acceptance (next):** deploy this exact commit to a detached Revit 2025 model; verify all 17 commands, settings and reload behavior using `REVIT_VALIDATION.md`. Capture defects with model-independent diagnostics. Preserve a known-good installation. Gate: no unexplained installation/import/UI regressions.
2. **AutoHanger reliability:** test five-piece connected runs, branches, reruns, existing/manual supports, sloped IFC links and roof fallback. Add connector-aware planning and reviewed spacing profiles in small changes. Separate geometric contact from native attachment; never fabricate rod lengths. Gate: no duplicates on unchanged rerun, explainable spacing and per-rod verified hits, cancel/rollback without side effects.
3. **Shared foundations, incrementally:** extract compatibility, units, coordinate transforms, source identity, read-only MEP inventory, connector graph and diagnostics behind adapters. Migrate one caller at a time; retain bundle compatibility and FabHover performance. Gate: existing annotation and hanger regression fixtures plus Revit import-order tests remain passing.
4. **AutoSleeve:** obtain the missing source or build a separately scoped feature. Use real native/linked wall/floor solids, transformed fitting envelopes, configurable clearance, preview, duplicate detection and coordination-only status for linked hosts. Give it a dedicated panel only when implemented. Gate: rotated links, fittings, oblique/sloped penetrations, box-outs, moved links and idempotent reruns.
5. **Annotation and data:** protect coverage, stable real references and manual overrides; expand clash/layout fixtures, shared part properties, schedule/parameter mapping and diagnostics. Keep duct/pipe engines independently testable.
6. **Revit 2027 compatibility:** add capability/version adapters only after API verification; run the same field matrix independently on a supported pyRevit/Revit 2027 combination. Passing 2025 is not evidence for 2027.
7. **Later product features:** trapezes, points/CSV, cut lists, stiffeners, prefab/spool/BOM and engineering-reviewed load/seismic workflows. Do not expand until the earlier accuracy gates pass.

EVOLVE public behavior is a benchmark only. The supplied research plan is retained
in `research/`; neither its directives nor its feature list imply implementation.

Progress: Phase 1 connector graph foundation and 14 synthetic regression fixtures are implemented; see `PHASE1_CONNECTOR_GRAPH.md`. This does not complete the live AutoHanger milestone.

Research update: [17 current public EVOLVE sources and implementation implications](research/EVOLVE_WORKFLOW_FINDINGS_2026-10-15.md) were reviewed. The next read-only host connector adapter and Auto Hanger Shift-click diagnostic are implemented; [Revit field verification](REVIT_CONNECTOR_DIAGNOSTIC.md) is the next gate before placement integration.
