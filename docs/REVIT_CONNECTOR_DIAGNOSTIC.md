# Phase 1: read-only FabricationPart connector diagnostic

## What is implemented

Shift-click **Auto Hanger** after selecting host-model fabrication duct/pipe parts,
including fittings. The new `config.py` reads the selection, captures connector
metadata and prints run lengths, source element IDs, boundaries and unresolved
reason codes in the pyRevit output pane. Normal-click Auto Hanger remains unchanged.
No new ribbon button, transaction, hanger placement, parameter edit, preference
save, persistent event handler or automatic file export is introduced.

The adapter verifies physical connector type/domain, owner identity, reciprocal
`IsConnectedTo` proof and connector-origin agreement (default tolerance 0.0001 feet).
Logical references are excluded. Merely coincident endpoints do not establish an
edge. Unselected connected owners remain explicit scope cuts. Unreadable selected
records are omitted with source IDs and reasons; existing verified edges to an
omitted record remain scope cuts. Multiple physical connections between the same
two parts are reported rather than collapsed into a false linear run.

Straight metadata comes from the API's `IsAStraight()` / `IsATap()` classification,
service ID and actual end-connector profiles/origins. Connector IDs define a stable
endpoint ordering; direction and axis endpoints therefore survive enumeration-order
changes. Lengths and coordinates are host-world feet. Sloped/vertical axes can be
reported, but this does NOT authorize the existing hanger placement engine to
support those routes. A topology-straight classification is not approval to place
hangers on an inline accessory. Hanger eligibility and company rules remain separate.

## Current limits

- Host-model FabricationPart duct/pipe only. Selected native RFA/MEP curves and
  hangers are explicitly skipped; foreign documents are rejected. No linked-model
  coordinate transform or IFC-host intersection is inferred.
- A straight requires exactly two readable End connectors with matching profiles.
  Ambiguous end geometry is unresolved; no bbox, name or guessed size fallback.
- This captures a selected scope. It does not auto-expand through the project,
  propose support stations, check existing hanger coverage, calculate rods or
  certify native structural attachment.
- Offline API doubles validate our control flow and data contracts. Actual Revit
  2025/IronPython loading, pyRevit Shift-click behavior and model data remain UNRUN.
  Revit 2027 remains independently unverified.

## Revit 2025 field gate

1. Use a detached model copy with a reviewed installation of this branch and the
   existing company pyRevit configuration. Keep the prior extension backup.
2. Select five physically connected three-foot fabrication straights, then
   Shift-click Auto Hanger. Expect one 15-foot run if service/profile/direction
   match. Capture the reported source element IDs and counts.
3. Repeat with disconnected but coincident parts. They must remain separate.
4. Include a tee/elbow/tap and all relevant branches. Confirm explicit fitting/
   branch boundaries; a partially selected continuation must report OUTSIDE_SCOPE.
5. Check round pipe, rectangular/oval duct, different services and sizes, and a
   sloped run. Verify the reported length against model connector coordinates.
6. Include a hanger, a native RFA and an unsupported/foreign selection. Expect
   explicit skips/unresolved reasons; no guessed geometry or attachment result.
7. Repeat after pyRevit reload and in mixed command order. Confirm unchanged
   output, no event subscriptions, no model-modified flag and no new Undo item.
8. Normal-click Auto Hanger and confirm its original menu/preview behavior is
   unchanged. Do not apply a placement merely to test this read-only diagnostic.

Record Revit/pyRevit/engine versions, commit and source IDs. Remove private project
names and paths before committing logs. Investigate discrepancies before feeding
these snapshots into any placement path.

## API evidence reviewed

- [Revit 2025 Connector reference](https://www.revitapidocs.com/2025/11e07082-b3f2-26a1-de79-16535f44716c.htm): AllRefs, ConnectorType, Domain, Id, IsConnected, IsConnectedTo, Origin, Owner and Shape.
- [Revit 2025 FabricationPart reference](https://www.revitapidocs.com/2025/c9b86162-c105-696a-a919-49a7a7938cc4.htm): ConnectorManager, ServiceId, IsAHanger, IsAStraight and IsATap.
- [Autodesk FabricationPartLayout SDK sample mirror](https://github.com/jeremytammik/RevitSdkSamples/blob/master/SDK/Samples/FabricationPartLayout/CS/FabricationPartLayout.cs): FabricationPart connector-manager usage. This mirror is supporting sample evidence, not a live Revit 2025 runtime test. No vendor algorithm or asset was copied.

## Next increment

After field verification, add a preview-only comparison against the existing
geometric planner. Introduce approved rule profiles and existing-station accounting
with regression tests before changing apply behavior. Per-rod hit/host validation
and linked geometry adapters remain separate milestones. See the EVOLVE research
findings for version-specific public behavior and the original master plan for the
remaining Phase 1 requirements.
