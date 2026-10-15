# AutoDim Duct v6.1 review — Revit 2025 / IronPython 2

This is a candidate development build informed by the supplied Area A PDFs.
It has not run inside Revit. Keep IronPython 2 selected and use a model copy.
The Pipe engine and AutoTag geometry engines are unchanged.

## Findings from the drawings

The human sheet locates main runs and separate branch stations. AutoDim's PDF
omits three upper branch offsets in room 6-2012 and branch/terminal offsets in
room 6-2008. Room 6-2002 has a candidate repeated main measurement; connectivity
and elevation must be checked in Revit before that measurement is merged.
Human tags are mostly absent from the automatic export, so overall annotation
density is not a fair measure of dimension quality. Screenshots and exports
have not been established as outputs of the same exact build/run.

## Implemented changes

- Physical-piece totals expand every member of verified logical runs. No-grid
  targets now participate in certification and rescue rather than disappearing
  from the denominator. Totals are refreshed after final text cleanup.
- Run coverage requires the intended grid, edge/center mode, and projected
  current source coordinate. Matching a recorded helper value alone is
  insufficient. This run's wrong-source straight dimensions are rejected.
- Existing direct model-to-grid dimensions are accepted only after exact stable
  reference, source geometry, value, and direction checks. They remain outside
  all created-dimension cleanup sets. Unknown existing helper ownership is
  not guessed, so full rerun idempotence is not yet established.
- Layout preserves collision tiers, then ranks the weighted clearance score
  before the additional midpoint preference. Paper-space text bounds include
  horizontal and line-aligned text. They are conservative estimates, not
  measurements of rendered glyphs. Nonadjustable text remains in place.
- Final text cleanup preserves the original intended certification coordinate.
- A unique per-run JSON audit records the document/view, target roles, source
  and physical-member IDs, grid/mode, expected points, created/existing
  dimensions, numeric checks, and missing-target state. Its path appears in the
  result dialog and pyRevit output. Send this audit with the new PDF when
  investigating gaps; it contains model/view names and coordinates.

## Validation completed here

39 host-independent regression tests pass. All 17 extension Python files parse
with the cloud syntax and legacy grammar checks, 12 XAML files are well-formed,
and six button packages contain their required files. These checks do not
execute IronPython, WPF, Revit transactions, or dimension references.

## Further work required for human drafting quality

1. Explicitly inventory main offsets, takeoff stations, turned/offset branches,
   flex/terminal locations, and the installation coordinates each needs.
   Source-proof fixes do not alone establish that every human locator is now
   produced. Branch certificates still depend on recorded connector targets.
2. Share a main locator only after datum, side, axis, size, elevation, physical
   continuity, and intended target equivalence are proved. Current connector
   proximity fallback is not sufficient evidence of physical connection.
3. Select a stable dimension type and local datum family, then place related
   dimensions in consistent bands. Chain dimensions need per-segment reference,
   value, and text certification; they are not enabled by this review.
4. Persist helper ownership and manage updates/orphans/dependents. Reference
   planes are independent model datums, not constrained duct references.
5. Correct the inherited regeneration-failure propagation/rollback chain.
   The baseline catches some regeneration failures and continues; Autodesk's
   RegenerationFailedException contract requires aborting before document reads.
   The coordinated correction is documented in the API research and remains
   unresolved in this review build.

## Revit acceptance checklist

Back up the current extension, close Revit, and replace its extension folder
with the extracted review build. Restart Revit 2025 with IronPython 2.

- Use a clean model/view copy with the same grids, annotation visibility,
  dimension type, and view scale as the human comparison. Avoid old AutoDim
  helpers when establishing the first clean benchmark; preserve the original
  model rather than deleting helper planes blindly.
- Start with a small Duct selection. Inspect each grid/model or grid/helper
  reference and actual value; compare edge versus center intent.
- Check rooms 6-2012, 6-2008, and 6-2002 in the exported PDF. Inventory branch
  offsets separately from main offsets. Do not require a predetermined total.
- Inspect the JSON audit for every missing target. Compare the physical-piece
  denominator with inputs and verify no-grid targets remain visible.
- Repeat with existing human direct dimensions and verify that no duplicate
  run dimensions are added and no manual dimensions are altered. Test existing
  managed helpers separately; that behavior remains a known limitation.
- Check readable text at plot scale, witness paths, tag clearance, rotated
  views, Undo, post-commit survival, and source move/resize behavior. A controlled
  regeneration-failure test is needed before a production readiness claim.

The three-page comparison and detailed research accompany this package in
GitHub downloads. Original source/audit manifests are retained for history;
older manifests may describe behavior absent from their actual shipped source.
