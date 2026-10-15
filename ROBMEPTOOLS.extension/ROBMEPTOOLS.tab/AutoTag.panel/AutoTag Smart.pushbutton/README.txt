ROBMEPTOOLS AutoTag Smart v1.12 - DUCT CROSS-PROFILE TAG SUPPRESSION

- Direct duct Transition/Reducer component tags now skip ALL square/rect/oval <-> round profile-change fittings for the current office-style test.
- This includes horizontal/in-plane square-to-rounds like the field screenshot as well as vertical square-to-round drops.
- Adjacent Duct V9 straight-run event tags are unchanged, so size/BOD information can still be communicated before/after the profile change without another fitting tag.
- Same-profile duct reducers/transitions (rect->rect, round->round, oval->oval) remain eligible when the Transition/Reducer component option is enabled.
- HETO/takeoff/tap/tee/wye vetoes remain unchanged.
- Duct AutoDim, Pipe AutoTag v1.4, Pipe AutoDim v5.6, Organizer, Fab Hover, and all other package tools are unchanged.
- This intentionally supersedes the v1.10/v1.11 behavior that allowed horizontal square-to-round direct component tags.

ROBMEPTOOLS AutoTag Smart v1.11 - HUMAN PLAN TRANSITION FILTER

- Duct transition component tags are now view-aware: a transition whose axis is nearly perpendicular to the active view plane is skipped.
- In floor/RCP views this removes vertical square-to-round / round-to-square drop transitions such as diffuser connections.
- Horizontal/in-plane square-to-round transitions remain taggable using the v1.10 connector/attached-run profile proof.
- Only near-perpendicular transitions are suppressed (|axis dot view direction| >= 0.88), so ordinary sloped or offset in-plane transitions remain eligible.
- The filter is view-relative: the same fitting can still be transition-tagged in a section/elevation where it is actually visible in-plane.
- HETO/takeoff/tap/tee/wye vetoes remain unchanged.
- Duct V9 straight-run BOD event logic, Duct AutoDim, Pipe AutoTag v1.4, Pipe AutoDim v5.6, Organizer, and Fab Hover are unchanged.

ROBMEPTOOLS AutoTag Smart v1.10 - DUCT SQUARE-TO-ROUND TRANSITION FIX

- Duct direct transition detection now has a dedicated square/rect/oval <-> round proof path.
- Valid two-port Fabrication square-to-round transitions are accepted from their own connector profiles OR the profiles of the two attached straight duct runs.
- The old connector-BasisZ opposition test no longer rejects a proven cross-profile transition, which fixes catalogs that report inline transition connector axes inconsistently.
- HETO/takeoff/tap/tee/wye branch vetoes remain ahead of transition acceptance, including the connected-main alignment check.
- Same-shape reducers remain on the stricter identity + straight-through geometry path.
- Duct V9 straight-run event detection/placement is otherwise unchanged.
- Pipe AutoTag v1.4 and all AutoDim behavior are unchanged.

ROBMEPTOOLS AutoTag Smart v1.9 - PIPE HUMAN TAG DENSITY CANDIDATE

- Duct AutoTag is unchanged.
- Pipe AutoTag V1.4 keeps the v1.3 local Plumbing Fixture-tail BOP suppression.
- Repeated turn/branch-only BOP targets on the same local two-port pipe path are consolidated to one human-style callout.
- Tee/wye/takeoff fittings stop consolidation, so separate branches stay separate.
- Sloped runs are never consolidated because BOP changes continuously along slope.
- Elevation, size, shape/profile, and endcap events remain strict and are never removed by this density pass.
- Result diagnostics now report local human-density turn/branch suppressions.

ROBMEPTOOLS AutoTag Smart v1.8 - PIPE DWP FIXTURE-TAIL BOP CANDIDATE

- Duct AutoTag is unchanged.
- Pipe AutoTag V1.3 suppresses redundant BOP targets on short terminal Plumbing Fixture tails/drops (<= 6'-0").
- Suppression is local only: at most two fitting hops, never through another straight, tee, wye, tap, or takeoff.
- Existing human turn condensation, branch-start coverage, size/elevation/profile changes, endcaps, HETO exclusions, and duplicate protection remain.
- Result diagnostics report how many local fixture-tail BOP targets were suppressed.

ROBMEPTOOLS AutoTag Smart v1.7 - PIPE BOP COVERAGE / LAYOUT FIELD PATCH

- Keeps human-density suppression for unchanged turn-only events.
- Restores one BOP tag on true branch-start straights at tee/wye/takeoff/tap events.
- First-elbow turn condensation prefers the branch-start straight, preventing the branch audit from re-adding a second identical BOP tag.
- Local micro-cluster spacing/search is widened to reduce dense tag overlap.
- HETO/takeoff transition exclusions remain unchanged.

ROBMEPTOOLS AutoTag Smart v1.6 - HUMAN-REFERENCE RELEASE CANDIDATE

PIPE HUMAN-DENSITY PASS
- Turn-only events with unchanged level/size/service annotation state no longer
  force two identical tags. The longer/already-required straight owns the callout.
- Elevation, size and profile/shape changes remain strict two-sided event coverage.
- Sloped pipe is never turn-condensed because BOP changes along slope.
- Tag safety spacing and local micro-cluster coordination are moderately widened.
- Clean mode enables the existing leader cleanup pass.
- HETO/takeoff/tee/wye branch exclusions from transition tagging remain intact.
- Duct AutoTag engine is unchanged.

ROBMEPTOOLS AutoTag Smart v1.4.2 Release

- One AutoTag button for Duct, Pipe, or Both.
- No sample tag placement/pick is required to start event tagging.
- Duct straight-run events use the BOD event-tag selection on Tag Types.
- Pipe straight-run events use the BOP event-tag selection on Tag Types.
- Every event/component tag mapping includes NONE / SKIP.
- Enabled categories mapped to NONE are intentionally skipped rather than blocking the run.
- Duct and Pipe mappings persist independently.
- Duct event engine remains the established Duct V9 detection/placement engine.
- Pipe event engine remains the established Pipe V1 detection/placement engine.
- Pipe BOP contains a hard coupling/coupler/union fabrication-host exclusion so those fittings cannot be promoted to straight BOP targets.

- Fabrication transition tagging is strict: taps/takeoffs/tees/wyes are excluded.
- Direct transition tags are limited to true transition/reducer identities plus connector-proven rect/oval <-> round shape transitions.
- Event-tag family mapping is otherwise unchanged; use a Fabrication Ductwork/Pipework tag type for Fabrication straight-run BOD/BOP hosts.
- Direct component tags remain on-host/no-leader for this release.
- Duct + Pipe mode runs the two engines independently from one shared menu.


HETO hard-veto field patch:
- TapPerpendicular / TapAdjustable / HETO / takeoff / branch identity is rejected before profile-change logic.
- Two-port parts with non-opposing connector axes cannot be tagged as transitions even if they change rect/round shape.
