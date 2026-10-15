# Public hanger tool comparison and controlled next test

This is a source review, not a claim that another tool was executed or validated
in this user's Revit model. Reviewed public source was fetched on 2026-10-15.
No third-party runtime code or binaries were copied into this extension.
Murray-Tools is GPL-3.0; Hanger Layout is MIT with an evaluation disclaimer.
The Autodesk SDK examples below are available through Jeremy Tammik's mirror.
These sources provide API and workflow evidence, not field validation for ROB MEP.

| Public reference | Observed behavior | HANGERTOOL implication |
| --- | --- | --- |
| [Murray-Tools duct placement](https://github.com/mitchoatman/Murray-Tools/blob/f4eee896643bf21129cf5e1d7c06a50beae3bbdd/MC%20Tools.tab/Fabrication%20Hanger.panel/Hangers.splitpushbutton/PlaceDuctHangers.pushbutton/PlaceDuctHangers_script.py#L413) | Uses the hosted `FabricationPart.CreateHanger` overload with a host connector, distance and attach option. Counts successful creation. | Our hosted call is the same API pattern. Creation and accepted structural placement must be reported separately. |
| [Murray-Tools rod extension](https://github.com/mitchoatman/Murray-Tools/blob/f4eee896643bf21129cf5e1d7c06a50beae3bbdd/MC%20Tools.tab/Fabrication%20Hanger.panel/Hanger%20Tools.pulldown/ExtendHangerRod.pushbutton/ExtendFabricationHangerRod_script.py#L166) | Disables rod hosting and adjusts each rod length from its current end point to a reference plane. | Supports our tip-minus-length base calculation. No evidence to reverse that convention based solely on previous misses. |
| [Hanger Layout placement](https://github.com/sbuchanan01/hanger-layout-for-revit/blob/66e4914febf01c39693d7cdeefae3e03478118c0/src/Revit/HangerPlacer.cs#L315) and [attach option](https://github.com/sbuchanan01/hanger-layout-for-revit/blob/66e4914febf01c39693d7cdeefae3e03478118c0/src/UI/HangerLayoutDialog.xaml.cs#L1722) | Public add-in for Revit 2025/2026. Has explicit attach/unattached placement and counts API-created hangers. | Public creation counts are not equivalent to our retained, measured, path-checked counts. An unattached API creation test should be isolated first. |
| [Hanger Layout connector normalization](https://github.com/sbuchanan01/hanger-layout-for-revit/blob/66e4914febf01c39693d7cdeefae3e03478118c0/src/Revit/HangerPlacer.cs#L1190) | Normalizes connector and distance against the host LocationCurve start to address opposite drawing direction. | A plausible content/API-sensitive difference, not proven in our field results. Log requested versus actual along-duct origin before applying an unproven universal reversal. |
| [Autodesk SDK 2025 creation](https://github.com/jeremytammik/RevitSdkSamples/blob/4ca6a3d6f0ae6e166b514e8324f65f057da27b64/snapshot/2025/Samples/FabricationPartLayout/CS/FabricationPartLayout.cs#L193) and [rod handling](https://github.com/jeremytammik/RevitSdkSamples/blob/4ca6a3d6f0ae6e166b514e8324f65f057da27b64/snapshot/2025/Samples/FabricationPartLayout/CS/HangerRods.cs#L78) | Demonstrates the six-argument hosted call and detaching rods before resizing. | Preserve our working creation/detach path. Test actual behavior on the user's service button rather than replacing it speculatively. |

Hanger Layout's published source also deletes existing hosted hangers before
reapplying a layout. We deliberately do not adopt that behavior: this project
requires preservation of existing hangers. Murray's placement path is not a
universal IFC type-approved rod targeting or exact clash-validation engine.
The public Hanger Layout README explicitly describes evaluation code. Neither
comparison establishes that our expanded checks are correct or that a public
tool guarantees the user's structural attachment requirements.

## What the supplied field results actually establish

- Latest run: 14 straight segments, 10 grouped runs, 4 planned stations,
  28 rolled-back probes, zero retained hangers.
- Selected native deck geometry produced actual rod-0 hits; the tested raw
  target path was available in those cases.
- Clearance then rejected a DWG, an unreadable coordination DirectShape,
  an uncategorized Element, and GraphicsStyle records in the link.
- GraphicsStyle is a display definition, not a physical obstruction. This is
  a verified classification defect. GraphicsStyle definitions are now excluded
  before metadata/name-based obstacle classification.
- A drawing filename or an unreadable DirectShape cannot prove that the object
  is only a reference. Ambiguous unreadable references now require deliberate,
  unchecked-by-default, run-only review. Known physical geometry, MEP and
  approved targets are ineligible for this exclusion.
- We cannot yet explain the reduction from 15 to 4 planned stations. Existing
  hanger occupancy can remove proposals before the old near-station count is
  evaluated; the next normal output now reports occupancy before optimization.
  No reduction algorithm was changed on an unproven diagnosis.

## Why the next test changes

Previous runs combined layout, redundancy removal, structural relocation,
geometry, native attachment, drafts and broad obstruction discovery. Reporting
zero retained did not distinguish basic API creation from validation failure.
The new **Single hanger test** is integrated into Auto Hanger, uses one selected
straight duct and a clicked station, and bypasses run optimization. It reports:

1. API creation and correct duct host.
2. Requested axis point and actual hanger origin, with along-axis offset.
3. Every rod's base coordinates and initial length.
4. Raw approved geometry targets independently for every rod.
5. Targets passing normal enabled path validation, including permitted fallback.
6. Accepted independent lengths after regeneration and final rod clearance.
7. Confirmed rollback. No test hanger is retained, even on PASS.

Raw geometry inspection temporarily omits the path validator only to expose
measurement evidence; the validator is restored in `finally`, and raw targets
never authorize resizing/retention. Sizing requires validated targets for all
rods and final clearance. Cancellation before station selection creates nothing.
A cleanup failure aborts; it cannot be reported as a successful test.

A geometry/clearance success with an unavailable or >0.25-ft origin offset is
labeled **STATION REVIEW**, not PASS. Product insertion-point offsets also need
inspection; that observation alone does not prove an API connector reversal.
The test does not prove native structural attachment, hanger hardware capacity,
or complete run support coverage.

350 offline tests passed. Added regression cases use the supplied failure
pattern (GraphicsStyle + unreadable CAD/coordination references + a valid native
deck hit), verify both rods, enforce review scope/source qualification, preserve
all original setting controls, and test cancellation/rollback and origin-offset
reporting. Offline API doubles do not verify actual Revit engine/content behavior.

Read [NEXT_TEST.md](NEXT_TEST.md) before the next field run. Send that single
stage-by-stage result first. A PASS is evidence to proceed to one small normal
layout with **Keep UNATTACHED** enabled when manual attachment is intended.

The single-station wrapper now exercises the actual extractor/profile functions
in regression tests. Its (segment, issue) return is unpacked, and invalid ducts
exit before station picking or transactions. This corrects the reported
TypeError; it does not establish successful live Revit placement.
