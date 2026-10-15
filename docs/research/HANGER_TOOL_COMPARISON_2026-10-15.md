# Hanger workflow evaluation and focused improvement plan

Reviewed 2026-10-15 against the actual Auto Hanger source, master plan, user
transition feedback, 17 official EVOLVE articles, Autodesk Revit 2025 help and
Trimble's SysQue product page. This is a documentation/code comparison, not a
hands-on performance or accuracy test of commercial products. Source metadata
is in `HANGER_COMPARISON_SOURCES_2026-10-15.json` and the existing EVOLVE index.
No proprietary code, families or content were copied.

## Findings and comparison

| Area | Documented reference workflow | ROBMEPTOOLS finding | Decision |
|---|---|---|---|
| Connected routes | EVOLVE offers entire connected path, direction-change and single-hanger scope [1]. | Normal placement still uses `planner.group_runs` geometric grouping. The new physical connector graph is diagnostic only. Transitions belong to a network but are not uniform straight spans. | Highest priority: validate physical routes, then compare old/new station plans in preview before migrating placement. Do not just combine span lengths across fitting offsets. |
| Hostable locations | Autodesk allows straight segments, straight fitting extensions and sloped hosts [4]. | Normal hosting excludes sloped/vertical pieces; optional two-port fitting extension fallback is experimental. | Separate route membership from legal support stations. Add verified fitting geometry and slope fixtures before expanding placement eligibility. Do not place on a transition just because it connects the route. |
| Rule selection | EVOLVE ITM rules include service/material/size/insulation and end/joint/branch distances [2]. | Current size caps and overall cap are preliminary; service buttons are isolated correctly, but no reviewed company profile schema exists. | Add versioned approved profiles, explicit unmatched-rule reasons and a profile summary before placement. Keep present settings until a profile migration can preserve them. |
| Structural attachment | Autodesk defaults to nearest structure and falls back to the ITM rod length when none exists [4]. EVOLVE attachment targets vary by RFA/ITM profile [1,3]. | Per-rod geometry checks and UNATTACHED draft policy are essential for selected IFC targets. Geometry is not native attachment. | Preserve strict per-rod verification. Never copy the native default-length fallback into our verified-draft mode. |
| Collision handling | EVOLVE separates clearance settings, bounded movement/stretch and unresolved clash reporting [3]. Autodesk exposes manual bearer/rod controls; some controls are unavailable on fitting hosts [5]. | Current code has native/linked screens, rollback probes and bounded search, but final exact hardware clearance and fitting behavior need field tests. | Retain checks. Improve unresolved reasons and compare coverage after station moves; do not trade correctness for speed. |
| Everyday UI | EVOLVE separates profiles/settings from placement [1–3]; Autodesk begins with service and hanger choice [4]. | Long settings dialog interleaves common limits, experiments, diagnostics and explanatory paragraphs; service controls can be numerous. | First change: progressive disclosure while preserving controls/defaults. Next: approved profile + structural-source summary, with deliberate editing and invalidation. |
| Performance | Vendor pages do not provide a comparable reproducible model/time benchmark. | Repeated identity scans rescan every job per run; create/regenerate/rollback probes and per-rod geometry queries likely dominate actual Revit cost. | Remove proven repeated scans now. Profile Revit phases before attempting geometry caches or probe reduction. |
| Downstream workflow | SysQue documents hanger/support layout followed by export to Field Link [6]. | No verified hanger point-export workflow exists in this milestone. | Defer export until stations, source provenance and rerun behavior are reliable. The product page does not establish SysQue's internal placement/attachment algorithm. |

## What changed in this increment

- Settings: Preview and the rolled-back single-hanger mode appear first. Service
  mapping, three layout limits and explicit UNATTACHED policy remain exposed.
  Hardware override, detailed schedule, clearance controls and reference-review
  details move to one closed Advanced section. Live summaries show duct/rod
  clearance and experimental fitting fallback ON/OFF. Every original named
  control, numeric default and controller default is retained. Run is labeled
  **Run selected mode** because single-test mode overrides Preview.
- Task grouping: `group_station_jobs` groups by **context object identity**, keeps
  first-seen run order and stable ascending station order. It replaces repeated
  full-list scans in `align_structure_tasks`; rod calculations, geometry queries,
  probe budgets, rollback, collisions and coverage selection are unchanged.
- Preservation: the immutable import manifest is retained. An exact two-file
  change ledger records original/current hashes and reasons. Tests still check
  all 124 original runtime/assets: 122 unchanged, two intentional edits checked
  against exact documented hashes. This replaces a temporary blanket integration
  freeze without dropping source-preservation validation.

## Measured optimization and limits

Cloud CPython 3.12 synthetic batching benchmark: 10,000 jobs interleaved across
1,000 distinct context dictionaries, fixed seed 143, station values in range 100,
median of three calls. Legacy batching: **0.254356 s**. New batching:
**0.001701 s**. Four dedicated tests compare identity/order semantics, equal-valued
but separate runs, duplicate station stability, no mutation, missing metadata and
actual caller integration. `tools/benchmark_hanger_batches.py` reproduces this
microbenchmark; times vary by machine.

These numbers measure only Python job batching. They do not establish an
end-to-end hanger speedup, Revit API timing or a comparison against EVOLVE/SysQue.
The existing Revit search remains bounded to 600 total / 160 per-run probes and
24 candidate stations per job. A probe can create a temporary hanger, regenerate,
measure rods, query geometry/clearance and roll back. Keep those safeguards until
an equivalent cheaper candidate test is verified.

## Recommended pivot and acceptance gates

1. **Topology and legal stations.** Retest the same transition selection with
   Shift-click. Check readable parts, network membership, gap measurements and
   scope boundaries. Add branch, disconnected/coincident and sloped fixtures.
   Keep source IDs and separate connector offsets from part lengths.
2. **Read-only plan comparison.** Build fitting-aware route distance and approved
   rule matching, compare old/new stations without model changes, include existing
   hanger coverage and stable duplicate detection. Gate apply migration on a
   five-piece run, transitions, tee, short pieces and unchanged-input rerun.
3. **Profile-first UI.** Add reviewed company profiles and a concise active source /
   hardware / clearance summary. Keep advanced options available. Preserve current
   service isolation and revalidate saved choices when links/content change.
4. **Measure before caching.** Record phase times for selection/discovery, snapshot,
   grouping, candidate planning, each probe/regeneration, geometry, clearance and
   apply; include counts and failure reasons. Use the same detached fixture for
   baseline/candidate runs. Optimize the dominant phase, not assumed cost.
5. **Bounded geometric prefilter.** Investigate spatial indexing and per-command
   transformed-geometry reuse keyed by source, link instance/transform and document
   state. A bounding box can reject candidates; it cannot supply a rod length or
   prove attachment. Never persist stale geometry or exclude unclassified IFC
   merely to reduce collection time.
6. **Field gate before broader features.** Confirm rod hits on sloped structure,
   native-vs-UNATTACHED state, rollback/cancellation, fitting supports, linked MEP,
   no excess hangers and idempotent reruns. Then expand support styles and exports;
   AutoSleeve remains a separately gated new feature.

## Revit 2025 acceptance for this preview

Use a detached model copy and retain the prior installation backup. Reload pyRevit.
Confirm all 17 commands remain. Open Auto Hanger with the usual selections:
Preview starts checked; advanced status agrees with its controls; opening Advanced
retains values; resizing/scrolling works at normal and high DPI. Run Preview and
confirm no model changes, then single-test mode and confirm rollback/Undo behavior.
Compare planned station IDs/order/counts with the previous preview on identical
input. Only then test placement and confirm both rods and host state independently.
WPF rendering, IronPython imports and actual Revit timings are not verified by XML
or CPython tests. Revit 2027 remains unverified.

## Sources and retrieval limitations

1. [EVOLVE Hanger Placement](https://help-mechanical.evolvemep.com/hangers/multi-service-bearers)
2. [EVOLVE ITM Hanger Settings](https://help-mechanical.evolvemep.com/settings/hanger-specifications)
3. [EVOLVE Hanger Placement Settings](https://help-mechanical.evolvemep.com/hangers/msb-settings)
4. [Autodesk Revit 2025 — Place Fabrication Hangers](https://help.autodesk.com/cloudhelp/2025/ENU/Revit-MEPEng/files/GUID-B6858FBC-8007-402F-850D-F3728B2A64E3.htm)
5. [Autodesk Revit 2025 — Modify the Position of Hangers](https://help.autodesk.com/cloudhelp/2025/ENU/Revit-MEPEng/files/GUID-894D1B47-C363-4C61-9798-B270D8D41992.htm)
6. [Trimble SysQue product page](https://www.trimble.com/en/products/trimble-sysque)

AGACAD marketing pages returned HTTP 403 and its attempted helpdesk URL looped
redirects; no detailed capability claim is based on those pages. The older SysQue
support URLs failed; the current official Trimble product page was retrieved, but
contains only high-level hanger/export statements. Search-engine results were
irrelevant and excluded. EVOLVE documentation differences by version are discussed
in `EVOLVE_WORKFLOW_FINDINGS_2026-10-15.md`; public descriptions are not field proof.
