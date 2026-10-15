# Visual stations and one exact rolled-back hanger test

Revit 2025 field-test increment. Normal-click Auto Hanger remains the existing
placement tool. This feature is the third **Shift-click** menu choice:
**Visual stations + single test (rolled back)**. All 17 ribbon commands remain.

## User steps

1. Install with the existing manual installer, retain the previous backup and
   reload pyRevit. Use a detached model copy and a 3D view showing the selected
   fabrication duct and structural sources.
2. Select the same test route. Shift-click Auto Hanger, choose the new visual/test
   mode and enter the preview cap/end target (initially `8, 1.5`). The report shows
   the existing topology/station results and a marker-to-route/host table.
3. Blue numbered markers appear at proposed candidate coordinates in the active
   view. They are fixed-pixel images, not hanger geometry or clearance envelopes.
   Pan/zoom during the native pick step. Click the duct body beside a marker;
   choose the numbered station from the list. The marker image itself is not a
   custom clickable command. **Esc** ends review without a hanger test.
4. Markers are removed before the test. Confirm the exact candidate, select actual
   structural sources with the existing picker, then choose its service-specific
   hanger button and maximum rod limit. Settings are labeled for an exact station:
   single-test mode and rod clearance are locked on, spacing inputs are disabled,
   and **Test and roll back** cannot switch to retained placement.
5. Review unreadable coordination references using the existing explicit,
   unchecked-by-default workflow. Leave physical/unknown objects unexcluded.
6. Save the **SINGLE HANGER TEST** output. It includes marker/route/host identity,
   requested XYZ, actual temporary hanger origin and station offset, creation/host
   result, each rod's base, raw/validated target source/member, measured length,
   final rod clearance and cleanup result. A blocked result is useful evidence.
   Zero retained hangers is expected for success, failure and cancellation.

Start with one candidate. Check both rod tips independently against the selected
underside geometry; sloped structure can produce different lengths. A geometry
pass is not native anchorage, approved hardware capacity or whole-layout proof.
Do not manually adjust an unsupported station and present it as the same test.

## Scope and safeguards

- Rendering uses Revit 2025 `TemporaryGraphicsManager` / `InCanvasControlData`;
  markers create no model elements, sketches, detail lines or transactions.
  Revit's documented format is **BMP only**, with RGB(0,128,128) transparency.
  Numbered 64x64 BMP resources are drawn with Windows/.NET System.Drawing in a
  temporary directory; no pip package, downloaded asset or proprietary content.
- Up to 200 candidates are marked, with shown/total counts. Only displayed hosts
  can be selected for this diagnostic. View clipping, occlusion, graphics display
  behavior and image anchoring need field verification; a number is not evidence
  of a physical support fitting or successful clearance check.
- Cleanup removes only indices created by this command. It never calls global
  `Clear()` or deletes another add-in's controls. Cancel/error cleans prior
  markers and temporary files. Failed removal is reported, retains the necessary
  image resources, and prevents the hanger test. No model-line fallback is used
  when temporary graphics are unavailable.
- After review and again after target/settings selection, the original selected
  snapshot is recollected. Source identity, axes, port references/geometry and
  excluded selections must still match. Existing hanger data is refreshed and the
  candidate must still be proposed. Changed data stops the test.
- The actual source end connectors are matched by stable connector IDs. The
  requested world point must still lie on that exact host axis and inside the
  legal inboard range. There is no click-to-nearby adjustment, silent clamping,
  connector reversal or automatic relocation in this exact-station entry.
- The normal script is loaded with a guarded entrypoint so normal placement does
  not start during diagnostic loading. Its original normal command entry still
  invokes `run()`. The existing manually picked single-hanger test keeps its
  original pick/clamp behavior; only the new entry requires the exact candidate.
- The existing creation/rod/target/linked-clearance inspection runs inside nested
  rollback scopes. The exact entry requires a known successful outer rollback;
  cleanup failures do not receive a success/zero-retained claim. Native structural
  attachment is deliberately not claimed by this geometric rod test.
- No new structural preferences are saved by the diagnostic entry. Existing
  hangers are neither moved nor removed. Unsupported routes and unverified
  existing support warnings remain as reported by the route preview.

## Required Revit acceptance

- Confirm original normal-click Auto Hanger still launches, all other commands
  remain present and old settings/defaults retain their behavior.
- Confirm numbered markers match report host IDs/XYZ on the same route. Test
  normal/high DPI, zoom/3D orbit, obscured stations and a section box. Check that
  only our graphics disappear after Esc/choice/error; unrelated add-in overlays
  must remain. Pan/zoom may change the current view framing.
- Cancel marker review, station selection, confirmation, structural selection and
  settings separately. Verify no new model elements or retained hangers.
- Test one exact candidate with valid per-rod geometry, one with a blocked/missing
  target and one with an unreadable reference. Compare both rod measurements and
  actual hanger-origin offset with the reported requested station.
- Compare element inventory and Undo behavior before/after. No hanger should
  remain and the outer test transaction must report rollback. Do not count a
  temporary API creation as a placed/attached production support.

## Offline evidence limits

API doubles and extracted production functions cover graphics ownership/cleanup,
partial creation failure, resource retention after failed removal, cancellation,
changed snapshots, duplicate-avoidance revalidation, exact/reversed connector
axes, out-of-range/nonfinite rejection, guarded loading, forced diagnostic mode,
original manual test behavior, both-rod inspection, missing rod targets, creation/
sizing failures and inner/outer rollback failures. They cannot load actual Revit,
render WPF/System.Drawing/native controls, validate ITM creation or prove geometric
hits. Revit 2027 remains unverified. No end-to-end speed claim is made.

## API references

Retrieved 2026-10-15, API version 25.0.0.0:

- [InCanvasControlData](https://www.revitapidocs.com/2025/5fdf010d-7dbb-332d-4704-8e067f2338dc.htm)
- [Image/position constructor](https://www.revitapidocs.com/2025/f16cf225-d5a1-96e8-d036-bcda9f5dd8d1.htm)
- [AddControl](https://www.revitapidocs.com/2025/dbe10b60-8a28-50b9-c7d5-91628e8fe630.htm)
- [RemoveControl](https://www.revitapidocs.com/2025/3803b2b0-c688-faa3-ae1f-fdbd0135dd5a.htm)

The API reference mirror supplied the full signatures/format/cleanup contracts;
Autodesk help search listed the APIs but attempted direct help links returned
Page Not Found and were not used as full-page evidence. No vendor code was copied.
