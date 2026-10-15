# ROBMEPTOOLS Human Dimension / Organizer Audit - 2026-10-06

## Field-test result that triggered this pass
The v1.7.1 organizer correctly found visible annotation (11 tags, 284 dimensions) and
reduced counted annotation conflicts, but it moved 0 whole dimensions and nudged 157
dimension text positions. Visually, this is the wrong success metric: many dimension text
leaders/witness tails remained long and the sheet still did not read like the human reference.

## What the PDF comparison shows
- The human sheet does not simply have fewer dimensions. It has many local dimensions, but
  they are concentrated around the pipe they explain and form compact local banks.
- The automated/cleaned sheet has dimensions whose stations are often much farther from the
  referenced pipe. It also has more dragged dimension text, producing long text leaders.
- A text-collision-only optimizer can report nearly zero annotation overlap while still looking
  unlike a human-drafted sheet.
- The human examples also use shorter locating references more often. A separate completed
  human sheet in this test set explicitly states that dimensions are taken from grid lines or
  finish walls. The current ROBMEPTOOLS AutoDim remains grid-based; the organizer cannot change
  dimension references without changing measured values.

## v0.4 organizer strategy
1. Reset dragged dimension text to Revit's default position before layout.
2. Keep subsequent text nudges inline with the dimension and small; do not drag text
   perpendicular to the dimension line.
3. Resolve the referenced MEP host from dimension references when possible.
4. If AutoDim used a managed helper reference, recover the physical MEP host only when a
   dimension endpoint is locally adjacent to visible fabrication geometry.
5. Score dimension-line station distance from the MEP host and move the WHOLE dimension line
   toward a few paper-space lanes immediately outside the host footprint.
6. Keep collision avoidance, MEP avoidance, and DWG avoidance stronger than compactness.
7. Preserve references and values. This is layout cleanup only.
8. Retain local dimension-bank rewards and guarded multi-leader tag consolidation.

## Deliberately not changed in this candidate
- AutoTag Smart engines.
- AutoDim Smart engines and coverage/detection logic.
- Pipe branch recovery.
- HETO rules.
- True-riser logic.
- Fab Hover / Fab Ref tools.
- Dimension reference selection (still AutoDim's existing references).

## Next research branch after field confirmation
If the compact organizer works but dimension VALUES are still much longer than the human
reference, the remaining gap is reference selection rather than layout. The next AutoDim
prototype should add an optional human-reference strategy such as:
- nearest valid grid OR host-model finish wall / linked-RVT wall face;
- preserve grid-only as the safe/default office profile;
- treat linked/imported DWG wall graphics as collision context unless a stable dimensionable
  geometric reference can be proven in Revit 2025.
