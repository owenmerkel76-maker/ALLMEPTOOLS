# Active focus — AutoDim comparison and development (2026-10-16)

The user paused Auto Hanger and shifted to AutoDim. Preserve the hanger snapshot
at `f98a2f8` / visual preview 6; do not continue hanger changes while this focus
is active. Work in the existing checkout on `feat/autodim-comparison-audit`.

The user will supply human dimensions and AutoDim output for the same area.
Compare those drawings and the matching AutoDim audit JSON, research documented
working dimensioning tools, then identify omissions, errors, layout improvements
and measured optimization opportunities. Initial evidence and the comparison
protocol are in `research/AUTODIM_COMPARISON_2026-10-16.md`. Actual paired-drawing
findings are pending; do not invent a benchmark or attribute source risks to an
unseen model. Preserve true source/grid references, manual annotations, Duct/Pipe
behavior, saved settings and all 17 ribbon commands. No AutoDim production code
has been changed in the initial research/audit increment.

---

# Continuing development: audit and improve the complete ROBMEPTOOLS ribbon

Work continues in the existing conversation at the user's request; no separate task was launched. The connector-graph foundation is implemented; read `PHASE1_CONNECTOR_GRAPH.md` before choosing the next increment.

Use repository `owenmerkel76-maker/ALLMEPTOOLS`; current review branch is `feat/read-only-connector-diagnostics` (PR #1), based on `main`.
Read AGENTS.md, README.md, docs/REPOSITORY_AUDIT.md, docs/VALIDATION_RESULTS.md,
docs/ROADMAP.md and docs/research/ROBMEPTOOLS_EVOLVE_Research_and_Codex_Masterplan.md.
Use the existing isolated checkout; do not create a worktree unless requested.

Audit all 17 commands and shared helpers before changes. Run bash CODEX_SETUP.sh.
Review Revit field-test results if supplied; otherwise distinguish static evidence
from unverified behavior. Start with connector-topology and rod-hit regression
fixtures for AutoHanger, plus cross-command import/settings checks. Pick one small,
well-supported defect, explain its root cause, add a meaningful regression test and
fix it without rewriting stable tools. Preserve command names, settings, true
physical annotation references and FabHover's persistent hot-toggle performance.
Keep AutoDim, AutoTag, Fab Hover, hangers, structure and schedules separate.
AutoSleeve is absent; do not claim it exists or implement it without a separately
scoped milestone. Do not enable legacy updates. Keep Revit 2025/IronPython 2.7 as
baseline; Revit 2027 requires independent verification. Document exact checks and
remaining Revit acceptance steps. Commit the focused change and open a PR.

Current next gate: field-verify the new Auto Hanger Shift-click connector diagnostic using `REVIT_CONNECTOR_DIAGNOSTIC.md`. The read-only adapter exists; do not duplicate it or migrate the apply path before its model/API assumptions are verified.

Read `research/HANGER_TOOL_COMPARISON_2026-10-15.md` for the latest benchmark and pivot priorities. UI disclosure and identity-preserving station batches are implemented. Retest their WPF/placement equivalence before broader changes; do not repeat completed research or replace per-rod safeguards with guessed geometry.

Read-only route station preview is now implemented; see `HANGER_ROUTE_PREVIEW.md`. Next gate: field-check the 24-part transition selection, candidate source IDs/axis offsets, existing-hanger coordination, scope and unsupported fitting reasons. Normal-click remains the original placement path; do not migrate it before reviewed profiles, structure and clearance gates.

Latest field feedback exposed existing-coverage evaluation after a failed hypothetical branch layout. Existing-first distance evaluation is corrected; see `HANGER_ROUTE_PREVIEW.md`. Retest the previously withheld routes. Distance-covered existing hangers can still have clearance warnings; do not treat the correction as structural certification or a general existing-aware candidate solver.

Visual station review plus exact rolled-back testing is implemented in the third Shift-click mode. Read `VISUAL_STATION_TEST.md`; next field gate is numbered marker alignment/cleanup and one exact candidate with both-rod evidence. Do not migrate route candidates into retained placement based on a temporary geometric pass.
