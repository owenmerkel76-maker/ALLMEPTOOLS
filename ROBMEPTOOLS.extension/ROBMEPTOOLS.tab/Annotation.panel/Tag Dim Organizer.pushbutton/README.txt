ROBMEPTOOLS Tag + Dim Organizer v0.4 HUMAN COMPACT DIMENSIONS BETA

Purpose
- Run after AutoTag Smart and/or AutoDim Smart.
- Cleans visible annotation conflicts in the active view without moving model MEP.
- Handles tag/tag, tag/dimension, dimension/dimension, tag/dim vs Fabrication duct/pipe,
  plus visible imported/linked DWG geometry in the active view.
- Adds guarded multi-leader consolidation for matching nearby duct/pipe tags.


Field visibility hotfix
- Annotation discovery now uses a view-scoped FilteredElementCollector for IndependentTag
  and Dimension elements visible in the active view, with OwnedByView only as fallback.
- This is specifically intended for copied/dependent-view cases where visible annotations may
  not be owned by the active view itself.
- The completion report now shows detected tags/dimensions, movable counts, and annotation/MEP/
  DWG conflict counts before and after cleanup.
- Multi-leader candidate discovery uses the same visible-in-view collector so consolidation and
  movement operate on the same annotation population.
- DWG weighting remains structural: wall/door/partition/shaft/column/beam/architectural linework
  is strong enough to cause local movement, while hatch/fill/pattern/insulation noise stays weak.

Human-reference behavior
- AutoTag remains the coverage engine. The Organizer is the global drafting/layout layer.
- Nearby single-host tags are eligible for consolidation only when they use the same tag
  type, same displayed TagText, same host category, and same Fabrication service.
- Groups are local and capped (3-4 hosts depending on cleanup strength) to avoid spider tags.
- The Organizer uses Revit's native IndependentTag.AddReferences API inside a guarded
  subtransaction. If the loaded tag type does not support UI multi-leader behavior, that
  merge is rolled back and the separate tags are preserved.
- Existing multi-leader tags are preserved and never re-built.
- Parallel dimensions receive a small alignment preference for repeatable paper-space banks,
  while collision avoidance and MEP safety still dominate.
- Tag heads receive a small row/column alignment preference after collision safety.

Human-compact dimension behavior
- The previous field build proved that conflict counts alone are not enough: a view can report
  zero annotation conflicts and still look unlike a human-drafted sheet.
- The organizer now resets dragged Dimension/DimensionSegment text positions before cleanup.
  This removes long dimension-text leaders created by aggressive text nudging.
- Dimension text cleanup is now inline-only and intentionally small. It no longer searches
  perpendicular positions that can create large text leaders.
- For dimensions whose MEP host can be resolved directly (or recovered locally from a managed
  AutoDim helper), the organizer scores witness-line locality and moves the WHOLE dimension
  line toward the referenced MEP. References and measured values do not change.
- Human-compact candidates target a few paper-space offsets just outside the MEP footprint.
  Collision avoidance, MEP safety, and DWG safety still override compactness.
- Vertical dimension text uses a vertical collision envelope instead of the old always-horizontal
  text box approximation.
- The report now includes long witness-line stations and dimension text leaders before/after.

Safety
- MEP Fabrication geometry is never moved.
- Pinned/unsupported annotations are left unchanged.
- Multi-leader consolidation never changes the tagged host elements.
- If a donor tag cannot be merged safely, it is restored automatically.
- Existing tag leaders remain tied to their Revit host references.
- DWG scan is limited to the annotation work zone and weights architectural layers higher
  than hatch/pattern noise.

Recommended first test
1. BALANCED.
2. ACTIVE VIEW.
3. Tags + Dimensions ON.
4. Consolidate matching nearby MEP tags ON.
5. Bank parallel dimensions + Compact witness lines + Reset dimension text ON.
6. Fab Duct + Fab Pipe + DWG ON.
7. Run on the same dense plumbing view used for the human-reference comparisons.

This is a field-test beta because final multi-leader behavior depends on whether the
specific loaded Revit tag family/type supports multiple references in the Revit UI.
