> Current onboarding handoff: the master import is complete. Read `docs/NEXT_CODEX_TASK.md` and `docs/REPOSITORY_AUDIT.md` before the historical sprint instructions below. The ribbon now has ten panels; no tool rewrites were performed.

# Paste this into the NEW Codex project's first message

You are the lead developer of **ROBMEPTOOLS**, one unified pyRevit Revit MEP Fabrication extension. The repository root contains `ROBMEPTOOLS.extension`, which is the single authoritative ribbon; `AGENTS.md` is mandatory. **Do not start a new extension from scratch.** The 17 existing commands across Annotation, Fabrication, Hangers, Hanger Steel, Roof Deck, Schedules and Updates are the preserved user baseline. Read `README.md`, `AGENTS.md`, `docs/merge_sources.json`, the existing code and tests, and `docs/research/ROBMEPTOOLS_EVOLVE_Research_and_Codex_Masterplan.md` before altering code.

**Immediate goal:** make the existing AutoHanger production-reliable for Revit 2025 Fabrication duct/pipe, using user-selected IFC framing/joists as preferred geometry and selected native roof/deck as fallback, without invalid rods or excess supports. User accepts geometrically terminating but UNATTACHED rods as long as they are accurately measured and labeled. Keep Revit 2027 in mind, but validate Revit 2025 first.

## First sprint: analysis, not mass rewrite

1. Inventory current hanger modules, inspector, candidate spacing behavior, collision layers, geometry picker and test-output reason codes. Present a concise defect matrix for wrong rods, duplicate supports, and unmatched IFC geometry.
2. Add regression tests for connected runs spanning many fabrication pieces, branch topology, repeated hanger runs, sloped joist BOS per rod, IFC link transforms, and mixed unreadable IFC/native deck fallback. Do not fake successful geometry hits or source coverage.
3. Fix hanger placement problems in small changes. Preserve the preview-first/rolled-back single-hanger probe, Repair Draft Rods and Review Extra Hangers tools.
4. Design a shared `lib` framework gradually, with small adapters and backwards compatibility, to eventually serve AutoSleeve, AutoDim, AutoTag, FabHover and schedule numbering. Do not move all files before verifying that runtime imports, persistent state and WPF menus still work.
5. Once AutoHanger is stabilized, implement or integrate **AutoSleeve**; no sleeve code was present in the supplied ZIP. Start from verified 3D host solids (native and linked concrete walls/floors) rather than relying on DWG hatch alone. Add fitting-aware wall intersections, clearance rules, sizing, previews, and adjacent box-out merging.
6. Later priorities: ITM/RFA hanger types and trapezes; shared structure/rule chooser; automatic tag/dim organizer and part-number management; stiffeners, layout points, spool/BOM exports. EVOLVE is a functional benchmark only; use public documentation and Autodesk-supported APIs, not private code.

## Non-negotiable field-test acceptance

- A selected fabrication duct on a sloped joist: every rod has an individually confirmed geometric ray hit and measured length matching the underside; missing hit is flagged and unplaced/unmodified, not assumed from reference level.
- A 5-piece connected run: hanger stations respect run-wide spacing and avoid one hanger per short segment. Existing valid hangers counted once; rerun is idempotent.
- Structural source picker reliably identifies IFC linked instances by category/class/name/project and allows job-specific selection. Link and host coordinates agree; unclassified geometry is not silently accepted.
- No unexpected edits to duct/pipe geometry, tags, dimensions, roof/steel proxies, or unrelated existing hangers.
- Clear dry-run preview with placements, skipped candidates, uncertainty, and created/unattached counts. Test changes first in a detached Revit model copy.
- `python tools/validate_extension.py`, `python tools/validate_unified.py`, and `python -m unittest discover -s tests -q` pass; explicitly disclose live-Revit limitations.

**Do not turn on the old remote GitHub updater.** The old release channel would overwrite this unified ribbon. `INSTALL_WINDOWS.ps1` handles manually reviewed deployment with backup and a check for old scheduled update tasks. Preserve the last known good ZIP before proposing changes.
