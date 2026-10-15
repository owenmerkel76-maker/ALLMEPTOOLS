# 2026-10-07 v1.9 - PIPE HUMAN COORDINATE DEDUPE + TAG DENSITY

- Duct AutoDim / AutoTag behavior intentionally unchanged.
- Pipe AutoDim v5.5: nearby dimensions that locate the same actual X/Y pipe coordinate collapse to one best dimension even when different branch events discovered them. Coverage aliases are transferred before certification.
- Pipe AutoTag v1.4: repeated unchanged turn/branch-only BOP callouts along the same local two-port path consolidate to one tag.
- Plumbing Fixture-tail BOP/dimension suppression remains enabled.
- True-riser dual-axis locating remains enabled.

# ROBMEPTOOLS Release — 2026-10-06

Production target: Revit 2025  
Home test target: Revit 2027

## v1.3 human-reference field candidate

This pass was tuned against two one-page PDFs of the same floor: the current
ROBMEPTOOLS Pipe AutoTag/AutoDim result and a human-drafted reference. The audit
found the automated drawing had almost twice as many BOP text instances and far
more annotation-text overlaps, while the human drawing actually retained more
dimension values overall. The goal is therefore selective tag density + better
annotation organization, not blanket deletion of dimensions.

- Pipe AutoTag Smart V1.1 condenses redundant **turn-only** pairs when BOP/size/
  service information is unchanged. Elevation/size/shape events remain two-sided.
  Sloped pipe is never condensed by this rule.
- Pipe AutoTag micro-cluster spacing/grouping is moderately widened to turn the
  lower tag population into cleaner local lanes. Clean mode enables the existing
  repair pass.
- Pipe AutoDim V5.2 retains v5.1.6 straight-owned/event-guided certified coverage.
- AutoDim dimension-text collision boxes now follow the dimension-line rotation;
  vertical values no longer use a horizontal footprint.
- AutoDim readability/collision score now outranks midpoint bias after hard safety
  checks, allowing cleaner run-end/perimeter stations.
- HETO/takeoff transition rejection is hardened again with PartType, connected-owner geometry and connector-axis vetoes.
- Duct and Pipe AutoDim now add dual-axis grid locating at true vertical/up/down points; Fab Hover and fabrication utilities remain unchanged.

See `HUMAN_REFERENCE_AUDIT_20261006.md` for the measured comparison and field-test
checklist.

## Ribbon

- **Annotation**
  - AutoTag Smart
  - AutoDim Smart
  - Tag + Dim Organizer
- **Fabrication**
  - Fab Hover (pulldown)
    - Fab Hover Toggle
    - Fab Hover Settings
  - Fab Ref Probe
  - Fab Ref Classifier

The old separate Duct AutoTag and Pipe AutoTag ribbon buttons remain removed.

## AutoDim Smart v2.9.4

- Duct v7.4.1 preserves the v7.4 straight-owned model and adds dual-axis up/down point locating.
- Pipe v5.2.1 preserves the human-layout/branch-coverage candidate and adds the same dual-axis up/down point locating.
- Pipe uses the improved Duct-style straight-owned / event-guided branch model.
- Branch-event straights are protected from run-collapse suppression.
- Horizontal and vertical host-grid candidates remain available; pipe legs use only compatible parallel grids.

## AutoTag Smart v1.4.2

- One shared Duct / Pipe / Both workflow.
- Duct event tags now use a **BOD event tag** selected directly in the menu.
- Pipe event tags now use a **BOP event tag** selected directly in the menu.
- Event runs no longer require placing/selecting a sample tag before execution.
- Every event/component tag dropdown includes **NONE / SKIP**.
- Enabled targets mapped to NONE are intentionally skipped instead of blocking the run.
- Duct and Pipe mappings persist independently.
- Pipe BOP hard-excludes fabrication coupling/coupler/union hosts so those fittings cannot be promoted to straight BOP targets.
- Fabrication transition tagging now hard-excludes taps/takeoffs/tees/wyes/branch fittings.
- Direct transition tags are limited to true transition/reducer identities and connector-proven rect/oval ↔ round shape transitions.
- For Fabrication straight-run BOD/BOP event tags, select a Fabrication Ductwork/Pipework tag type; the event-tag mapping logic itself is otherwise unchanged.
- Existing Duct V9 / Pipe V1 event detection and placement engines remain the basis of AutoTag.

## Fab Hover

The pyRevit 5.1-incompatible split-button implementation is not used.
Fab Hover is a standard pulldown containing two real commands:

- Fab Hover Toggle — fast persistent ON/OFF command
- Fab Hover Settings — full settings UI

This restores one clean ribbon control while keeping both commands independently assignable in native Revit KS.

## Native KS

Suggested mappings:

- QAT — AutoTag Smart
- QAD — AutoDim Smart
- QTO — Tag + Dim Organizer
- QHT — Fab Hover Toggle
- QHS — Fab Hover Settings
- QRP — Fab Ref Probe
- QRC — Fab Ref Classifier

See `ROBMEPTOOLS_NATIVE_KS.txt`.

## v1.2 field hotfix
- Pipe AutoDim v5.1.6: keeps v5.1.4 straight-owned/event-guided branch detection unchanged, but final certified dedupe can collapse nearby collinear targets with the same grid/measurement while carrying explicit coverage aliases. This targets the remaining duplicate dimensions without sacrificing branch coverage.
- AutoTag component classifier v1.4.2: HETO / high-efficiency takeoff / spin-in / start-collar identities are hard branch exclusions before any connector shape-change test, so rect-to-round HETO takeoffs cannot be tagged as transitions.


## v1.4 field patch — HETO hard veto + dual-axis rise/drop locating
- AutoTag transition classification now rejects HETO / TapPerpendicular / TapAdjustable / non-opposing two-port branch geometry BEFORE rect-to-round shape-change acceptance.
- Duct AutoDim v7.4.1 and Pipe AutoDim v5.2.1 locate true vertical/rise/drop connector stations as plan points.
- Each detected up/down point requires both a horizontal-grid and vertical-grid coordinate when both grid orientations are available.
- A nearby certified straight dimension may satisfy one axis to avoid a redundant graphic dimension; the missing axis is still created with a stable managed helper.


## v1.4.1 field patch — true-riser dual-axis filter

- Duct AutoDim v7.4.2 and Pipe AutoDim v5.2.2 no longer interpret every Z-facing connector as an up/down point.
- Two-axis grid locating now requires a real near-vertical straight element (within about 10° of vertical).
- Duct vertical straights that terminate directly at an Air Terminal are treated as local diffuser drops and are excluded.
- Pipe vertical straights that terminate directly at a Plumbing Fixture are treated as local fixture drops and are excluded.
- True risers remain two-axis locating targets; ordinary horizontal/branch logic is unchanged.


## v1.5 full-package human-reference consolidation

Field reference: `PIPE AUTO TAG EXAMPLE 1.pdf` vs `human tag and dim example pipe.pdf`.

- Pipe AutoTag V1.2 now applies the human turn-only condensation rule inside the
  conservative two-port audit too. The earlier audit could re-add both sides of a
  direction-only turn after the main detector had intentionally kept one, which
  explains much of the excessive repeated BOP density. Size/elevation/profile
  changes remain strict two-sided coverage; sloped pipe is still never condensed.
- Pipe tag micro-clusters get a slightly larger hard air gap and a slightly wider
  local coordination radius. This is intentionally modest so dense plans do not
  fall into long-leader emergency placement.
- Pipe AutoDim V5.3 keeps the Duct-style straight-owned/event-guided branch model.
  No branch detection/topology rewrite was made.
- True-riser dual-axis locating is coordinate-based: if an ordinary centerline
  dimension already locates the riser coordinate to ANY parallel grid, that axis
  is reused instead of stacking a second helper dimension. Existing pre-run
  dimensions count as coverage.
- Final semantic dedupe now recognizes one continuous straight coordinate even
  when separate internal paths selected different parallel grids, preferring an
  existing/ordinary dimension and the nearer grid. Coverage aliases remain in use.
- Dimension candidate lanes and text pockets are slightly wider so dense values
  can bank apart rather than stack at mid-run. Tags/text stay hard blockers.
- Duct AutoDim v7.4.2, HETO hard veto, Fab Hover, Ref Probe and Ref Classifier are
  carried through unchanged.


## v1.6.1 full-package integration — Tag + Dim Organizer

- Added **Tag + Dim Organizer v0.1 Beta** to the Annotation panel after AutoTag Smart and AutoDim Smart.
- Organizer post-processes visible tags and dimensions without moving Fabrication model parts.
- Handles tag/tag, tag/dimension, dimension/dimension, annotation vs Fabrication duct/pipe, and visible DWG conflicts.
- Dimensions are organized first to establish readable lanes; tags are then moved around those lanes.
- Balanced/Clean can perform a second cleanup pass; pinned or unsupported annotations remain unchanged.
- The organizer remains a standalone native pyRevit command and can be assigned in Revit KS. Suggested shortcut: **QTO**.
- AutoTag Smart, AutoDim Smart, HETO behavior, riser-edge logic, Fab Hover, Ref Probe, and Ref Classifier are unchanged from v1.6.

## v1.6 consolidated field patch — riser edges + diffuser suppression + Pipe BOP rebalance

- Duct AutoDim v7.4.3 and Pipe AutoDim v5.3.1 now locate true vertical risers from the physical plan edge nearest each selected grid, not from the riser centerline. Both X/Y locating axes use edge coordinates.
- Diffuser/terminal and plumbing-fixture drop suppression is strengthened with a local geometric fallback when Fabrication AllRefs do not expose the end device. This remains local-only and does not reintroduce topology-first dimension targeting.
- Pipe existing centerline dimensions no longer satisfy a true-riser edge requirement merely because they touch the same pipe; the measured Revit value must match the requested edge-to-grid distance.
- Pipe AutoTag keeps unchanged-turn condensation, but restores one BOP callout on a true branch-start straight at tee/wye/takeoff/tap events. At the first elbow after a branch, the branch-start straight is preferred so the branch audit does not create a second identical tag.
- Pipe tag micro-cluster spacing/search is widened modestly to reduce tag/tag overlap without forcing long leaders.
- HETO/takeoff transition exclusions are unchanged from v1.5.

## v1.7 human-drafting organizer candidate — guarded multi-leader + dimension banks

Reference reviewed: `WASC_26_P202_SECOND_FLOOR_DWP_FLOOR_PLAN 1.pdf`.

The new human reference confirms that the next quality jump is primarily a layout/
consolidation problem rather than another AutoTag/AutoDim detection rewrite.

- **AutoTag and AutoDim engines are intentionally unchanged from v1.6.1.**
  Their job remains coverage and certified locating geometry.
- Tag + Dim Organizer advances to **v0.2 Human Drafting Beta** and becomes the
  global annotation-layout layer.
- Nearby single-host duct/pipe tags may consolidate into one native Revit
  multi-leader tag only when all of the following match: tag type, displayed
  TagText, host category, Fabrication service, and local spatial cluster.
- Consolidation is capped to 3-4 hosts so the result stays readable rather than
  becoming a spider tag.
- Revit's `IndependentTag.AddReferences` is attempted inside a guarded
  subtransaction. If the loaded tag family/type does not support multi-reference
  tagging in the Revit UI, the donor tag is restored automatically and the
  organizer falls back to ordinary separate-tag cleanup.
- Existing multi-leader tags are preserved.
- Parallel dimensions receive a small repeatable paper-space bank preference
  (.18/.36/.54/.72/.90 inch lane families). Collision safety, tags, MEP geometry
  and DWG obstacles still outrank the bank preference.
- Tag heads receive a small row/column alignment preference after collision safety,
  helping dense areas form readable local annotation bands.
- The WASC example's general note says dimensions are taken from **grid line or
  finish wall**. This release does not yet change AutoDim's reference-generation
  policy; wall-reference generation is intentionally deferred to a separate field
  test so the now-working grid/branch coverage is not destabilized.

See `WASC_HUMAN_DRAFTING_AUDIT_20261006.md`.



## v1.7.1 organizer field-visibility merge — copied/dependent view reliability

This candidate merges the field hotfix learned from the separate Auto Organize test into
the v1.7 Human Drafting + Multi-Leader Organizer without changing AutoTag or AutoDim engines.

- Tag + Dim Organizer advances to **v0.3 Field Visibility + Human Drafting Beta**.
- Annotation discovery now uses a view-scoped `FilteredElementCollector(doc, view.Id)` for
  `IndependentTag` and `Dimension` graphics visible in the active view, with `OwnedByView` only
  as a compatibility fallback. This addresses copied/dependent views where visible annotations
  are not necessarily owned by the active view.
- Multi-leader consolidation uses the same visible-in-view collector so its candidate set matches
  the annotation set used by the organizer.
- Completion diagnostics now report detected tags, detected dimensions, movable counts,
  annotation conflicts, MEP conflicts, and DWG conflicts before/after, in addition to the
  existing multi-leader, banking, move, and DWG-index statistics.
- Strong DWG architectural/structural layers remain meaningful local-move drivers while
  hatch/fill/pattern noise remains weak.
- v1.7 guarded multi-leader consolidation, dimension banking, tag row/column alignment,
  MEP immobility, and rollback safety are preserved.
- This is a **candidate**, not the canonical ROBMEPTOOLS baseline, until the user confirms the
  Auto Organize field test behaves correctly.


## v1.7.2 Organizer Human Compact Dimensions candidate
- Based on v1.7.1 field-visibility package. AutoTag and AutoDim engines are unchanged.
- Organizer v0.4 resets dragged dimension text before cleanup to remove long text leaders.
- Dimension text nudging is inline-only and limited to small paper-space moves.
- Adds referenced-MEP/local-helper host recovery and a whole-dimension compactness objective.
- Adds compact witness-line candidate stations near the host while preserving dimension references/values.
- Adds orientation-aware dimension text collision footprints and long-station/leader diagnostics.
- Multi-leader grouping, active-view visibility collection, DWG weighting, and all previous safety rules remain.

## v1.8 Pipe DWP humanization candidate — 2026-10-07

Reference reviewed: `WASC_26_P202_SECOND_FLOOR_DWP_FLOOR_PLAN 1(1).pdf`.

- **Duct AutoTag and Duct AutoDim are unchanged** from v1.7.2.
- Pipe AutoTag advances to **V1.3** with a conservative local plumbing-fixture-tail suppressor so short bathroom fixture drops/tails do not receive redundant BOP tags.
- Pipe AutoDim advances to **V5.4** and suppresses the same short local fixture-tail straights *after* branch discovery, allowing the branch/takeoff or first meaningful run to remain the locating target instead of dimensioning every final fixture connection.
- True vertical riser dual-axis locating remains enabled; direct/local Plumbing Fixture drops remain excluded.
- The suppression rule is local only: max 6'-0" straight, max two fitting hops, never walking through another straight or across a branch fitting.
- Result dialogs report the number of fixture-tail BOP targets and fixture-tail dimension targets suppressed for field verification.
- Finish-wall reference generation is still deferred; grid references remain the certified AutoDim source in this build.

See `PIPE_DWP_HUMANIZATION_AUDIT_20261007.md`.
