# Next field test — one hanger, always rolled back

Use this test to identify the failing stage before testing another full area.
It is part of the existing Auto Hanger button. It does not retain a hanger.

1. Replace the extension with this ZIP and reload pyRevit (restart Revit if
   helper modules remain cached). Work in a detached Revit 2025 test model.
2. Preselect **exactly one straight fabrication duct** below the native deck
   used in the last result. Open Auto Hanger.
3. Approve the intended readable steel and native roof/deck fallback. Use
   **Preferred framing first, then fallback**, matching the last roof-hit case.
   Leave unclassified target types unchecked.
4. Keep the correct hanger button for that duct's fabrication service. Enable
   **Single hanger test — choose one duct and click a station**. Run it.
   This mode overrides Preview for a temporary rolled-back test and keeps
   clash validation enabled. No spacing or duplicate optimizer runs.
5. If an unreadable-reference list appears, check ONLY background or duplicate
   drawing/coordination references you actually recognize. Checkboxes start
   empty. Physical/uncertain objects stay unchecked. Cancel excludes none.
   The classification is for this run only; it is not saved to other projects.
6. Click the desired station along the selected duct. The point is projected
   onto the duct axis and clamped inside its connector regions.
7. Send the **SINGLE HANGER TEST** output, including the stage table, both rod
   sections, any reference-scope notes and requested/actual origin coordinates.

Interpret the result:

- **PASS**: API creation, host, both/all rod targets, lengths, enabled clearance
  and tested along-duct origin passed. Every test hanger was removed.
- **STATION REVIEW**: geometry/clearance passed but the origin offset needs
  content/connector inspection. No automatic distance reversal was applied.
- **BLOCKED**: the stage table identifies creation, geometry or clearance
  failure, with every readable rod reported. Every test hanger was removed.
- **Zero retained is expected in this test mode**, including on PASS. This is
  not the normal layout's “no hangers kept” failure message.

After reviewing a PASS, disable Single hanger test and try one small normal
layout. For manual structural attachment, enable Keep UNATTACHED. Enable
Review unreadable drawing / coordination references again when needed; scopes
are not persisted. Confirm all retained rods, fitting/branch/end coverage and
actual physical clearances in Revit. A diagnostic PASS is not native anchorage
or full-layout certification.
