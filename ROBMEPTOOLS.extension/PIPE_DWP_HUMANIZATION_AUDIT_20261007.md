# ROBMEPTOOLS Pipe DWP Humanization Audit — 2026-10-07

Reference reviewed: `WASC_26_P202_SECOND_FLOOR_DWP_FLOOR_PLAN 1(1).pdf`

## Drafting patterns carried into this candidate

The DWP uses a much more selective plumbing annotation hierarchy than the earlier automated field runs:

- distribution / meaningful branch runs carry the useful size-service-BOP information;
- short local fixture tails in restroom groups are not treated like full distribution runs that each need another BOP callout;
- locating dimensions are intended to read as deliberate branch/run locations instead of dimensioning every last fixture connection;
- true risers remain a separate locating problem from local fixture drops;
- the drawing note explicitly permits dimensions from grid line or finish wall.

## v1.8 changes

### Pipe AutoTag Smart V1.3

A new **local fixture-tail BOP suppressor** runs after the existing event detector and safety audits.

A candidate is suppressed only when:

1. it is a straight pipe target;
2. the straight is 6'-0" or shorter;
3. one end reaches a Revit Plumbing Fixture through at most two compact local fitting hops;
4. the local walk does **not** cross another straight pipe or a tee/wye/takeoff/branch fitting.

This is deliberately not a network-wide bathroom detector. It only removes the final local tail/drop annotation while preserving upstream branch/trunk information. Existing turn condensation, size/elevation/profile detection, end-cap logic, and duplicate-tag protection remain in place.

The AutoTag result dialog now reports:

`Local plumbing-fixture tail BOP targets suppressed`

### Pipe AutoDim V5.4

The same local fixture-tail concept is applied after branch discovery and before straight-run placement.

This ordering matters: branch/takeoff discovery still sees the full plumbing topology, but the final short fixture tail is not treated as another mandatory straight dimension. The branch connector / first meaningful run can still carry the locating dimension.

The existing true-riser rule remains intact, including the plumbing-fixture-drop exclusion. The result dialog now reports:

`Short local plumbing-fixture tails suppressed before placement`

### Duct protection

No duct AutoTag or duct AutoDim code was modified in this candidate.

## Intentionally deferred

The DWP general note allows dimensions from **grid line or finish wall**. This candidate remains grid-reference-first. Finish-wall dimension references should be introduced as a separate controlled field test because host walls, linked Revit walls, and DWG linework have very different reference stability in Revit.

## First field test

Focus on the restroom / bathroom groups:

- BOP callouts should stay on useful distribution and branch runs but disappear from the short fixture tails/drops.
- Pipe AutoDim should stop producing a dimension for every final fixture tail while keeping the branch/takeoff location.
- True floor risers that are not fixture drops should still receive their required locating coordinates.
- Duct output should match the previous v1.7.2 package.

If 6'-0" proves too aggressive or too conservative, `FIXTURE_TAIL_MAX_LENGTH_FT` and `FIXTURE_TAIL_DIM_MAX_LENGTH_FT` are isolated tuning values and can be adjusted without reopening event detection.
