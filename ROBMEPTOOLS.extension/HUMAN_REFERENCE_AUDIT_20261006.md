# ROBMEPTOOLS Pipe Annotation - Human Reference Gap Audit

Date: 2026-10-06

Reference pair supplied by user:
- `autodim&autotag pipe run.pdf` - ROBMEPTOOLS output
- `human tag and dim example.pdf` - manually drafted example of the same floor/area

## Measured visual difference

The comparison is not mainly a "more vs. fewer dimensions" problem.

PDF text-geometry measurements from the two one-page plans:

| Metric | ROBMEPTOOLS | Human | Observation |
|---|---:|---:|---|
| BOP text instances | 277 | 145 | Automated run is about 1.9x denser in elevation tags |
| BOP text-box overlaps | 118 | 0 | Primary AutoTag cleanup target |
| Dimension-like value strings | 229 | 259 | Human drawing actually carries slightly MORE locating values |
| Dimension text-box overlaps | 122 | 10 | Primary AutoDim cleanup target |
| Close repeated dimension-value pairs | 16 | 3 | Automated result still has local duplicate/stack behavior |

The human plan therefore does not simply delete annotation. It is selective about
which *tags* are necessary, while retaining strong dimension coverage and arranging
both dimensions and tag leaders into readable drafting bands.

## Human patterns visible in the supplied plan

1. Turn-only pipe geometry is not normally tagged on both sides when size/service/
   elevation information has not changed. One tag often documents that stable run.
2. Elevation/size/profile changes remain information-changing events and need both
   sides represented.
3. Dense fixture/restroom groups use leader fans and local annotation lanes. Tags
   are moved into clear space rather than being allowed to pile directly on the MEP.
4. Dimension values are numerous, but their witness lines are pushed toward clean
   run ends / cluster edges and values are spaced so the dimension bank reads as a
   deliberate set.
5. Human dimensions remain run-owned. Fittings help identify branch intent but do
   not become arbitrary dimension hosts.

## Changes made in this candidate

### Pipe AutoTag Smart V1.1 - human density

- Turn-only events are condensed when both adjacent pipe straights are level,
  same-service, and carry unchanged annotation information.
- Information-changing elevation / size / shape events remain strict two-sided.
- Sloped pipe is NOT turn-condensed because BOP changes along slope.
- Existing required targets win; otherwise the longer straight owns the redundant
  turn tag.
- Micro-cluster coordination is widened moderately and tag safety spacing is
  increased so the reduced tag population can form cleaner local groups.
- Clean mode uses a wider micro group and enables the existing cleanup pass.

### Pipe AutoDim V5.2 - human text geometry

- Branch/run target detection and geometric certification from v5.1.6 are retained.
- Dimension text collision boxes now rotate with the actual dimension line. The
  old fixed horizontal rectangle severely underestimated vertical dimension text.
- Text halo is slightly increased to reflect what the PDF actually renders.
- Once hard annotation/text safety is satisfied, weighted readability score now
  outranks midpoint bias. This allows dimensions to move toward cleaner run-end /
  perimeter stations instead of staying at local midpoints by default.
- Final equivalent-dimension dedupe remains active.

## Deliberately not changed

- Duct AutoTag event detection.
- Duct AutoDim engine.
- Pipe branch discovery / straight-owned v5.1.6 coverage model.
- Pipe horizontal/vertical parallel-grid logic.
- HETO/takeoff transition hard exclusions.
- Fab Hover, Fab Ref Probe, Fab Ref Classifier.

## First field-test checks

1. Pipe AutoTag created count should drop materially, especially in elbow-heavy
   zones, without losing tags across size/elevation/profile changes.
2. The result dialog reports `Redundant turn-only pairs condensed`.
3. BOP labels should have visibly fewer tag-on-tag collisions in dense restroom
   groups.
4. Pipe AutoDim must preserve branch coverage and horizontal-grid use.
5. Vertical dimension values should no longer pack as tightly because collision
   footprints now match the orientation of the printed text.
6. Dimension banks should migrate toward cleaner stations when the midpoint is
   crowded instead of treating minimum shift as the dominant preference.


## Follow-up audit — marked Pipe field run

The later marked automated sheet shows the same pattern more clearly: local zones
contain repeated BOP callouts and stacked locating dimensions while other branch
stations are visually under-dimensioned. The human sheet is not simply "less
annotation"; it distributes dimensions around actual branch/turn stations and uses
fewer repeated unchanged BOP callouts.

Implementation response in Pipe AutoTag V1.2 / Pipe AutoDim V5.3:

1. Preserve strict annotation on size/elevation/profile changes.
2. Condense only direction-only, level, same-service turns. The direct two-port
   audit now follows the same rule instead of undoing it.
3. Keep branch/event target detection unchanged; fix duplicate accounting/layout
   after coverage rather than reopening topology.
4. Treat a true riser as needing two coordinates, not necessarily two NEW
   dimensions. An existing centerline dimension can satisfy one coordinate.
5. De-duplicate continuous straight coordinates even if two automated paths chose
   different parallel grids; keep the nearer/cleaner surviving dimension.
6. Give dimension text and witness lanes more paper-space breathing room.

Public-tool patterns reviewed for this pass: BIMLOGIQ Smart Annotation separates
selection/dimension rules from arrangement and dimensions ducts/pipes by overall
run; Bimrock uses direction/minimum-length/change triggers to suppress redundant
MEP tags; BIMrx/eVolve expose persistent tag placement/offset/leader rules. Autodesk
Revit API supports post-placement dimension text repositioning through
Dimension.TextPosition/DimensionSegment.TextPosition, which remains the basis of
our final text deconflict pass.
