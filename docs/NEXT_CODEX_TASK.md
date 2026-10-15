# Next Codex task: audit and improve the complete ROBMEPTOOLS ribbon

Use repository `owenmerkel76-maker/ALLMEPTOOLS`, branch `main`.
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
