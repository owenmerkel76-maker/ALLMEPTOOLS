# ROBMEPTOOLS v2.4 — Duct Complete Annotation / Dimension Research Pass

## Basis reviewed

1. User human reference: `SECOND FLOOR AREA C.pdf`.
   - Tags are attached to straight duct, not fittings.
   - The useful annotation is size/system + BOD on the straight segment.
   - Tags repeat around real routing/size/elevation changes, but one straight piece does not receive multiple tags merely because two events touch it.
   - Leaders are short and local. The head stays visually owned by its duct.
   - Rectangular-to-round geometry is explained by the adjacent straight tags and the fitting/routing graphic; a separate transition component tag is not required for the current office style.

2. User AutoDim markup: `DUCT MARK UP 1(1).pdf`.
   - The historical failure mode was event-heavy dimension density around fitting/takeoff clusters.
   - Duct v7.4 already corrected the major issue by making fittings discovery topology and straight duct the dimension owner.

3. SMACNA CAD Standard (public reference):
   https://www.smacna.org/resource/smacna-cad-standard
   - Duct symbols distinguish flat/set and rise/drop conditions from ordinary duct labeling.
   - This supports keeping plan annotation semantic: routing/elevation change is communicated without needing a redundant generic fitting tag on every transition.

4. Autodesk Revit fabrication annotation documentation:
   https://help.autodesk.com/cloudhelp/2019/ENU/Revit-Model/files/GUID-E93B9DFF-E828-4F65-B0EB-7D5FFF049789.htm
   - Fabrication duct has dedicated Size, Bottom Of Duct Elevation, Top Of Duct Elevation, Flat/Set and Slope tags.
   - Size/elevation information belongs in duct annotation; plan dimensions should concentrate on locating geometry.

5. Autodesk fabrication rise/drop symbols:
   https://help.autodesk.com/cloudhelp/2027/ENU/Revit-MEPEng/files/GUID-7DD57A79-E578-4F75-B40D-D2404B95E4BC.htm
   - Revit/Fabrication have explicit rise/drop graphics for rectangular, round and oval duct.

6. Published AutoDim implementation patterns reviewed:
   - Collision-safe dimension lanes, occupied-zone tracking and final text movement are common successful patterns.
   - The important extra lesson for this release is to deduplicate by geometric locating obligation, not by the identity of the event that discovered it.

## Human drafting contract used for v2.4

### AutoTag Duct
No new detection rewrite in this pass. v2.3 is intentionally preserved because it is already close to the human reference and the user is happy with the duct side overall.

- Tag straight horizontal duct around direction, elevation, size and shape changes.
- Do not tag vertical/sloped transition duct.
- Do not tag fittings as BOD event targets.
- Do not place direct square/rect/oval <-> round transition component tags for now.
- One physical straight duct owns one event tag even if several reasons touch it.
- Keep tags local; short straight leaders are preferred and doglegs remain exceptional.

### AutoDim Duct v7.5
The new rule is: **plan dimensions locate X/Y; BOD/size tags communicate Z and section change.**

A final geometric consolidation pass now removes only local dimensions that prove they locate the same actual plan coordinate.

- edge dimensions only merge with edge dimensions;
- centerline dimensions only merge with centerline dimensions;
- dimensions must be on parallel grid axes;
- actual target coordinate must agree within 1/8 in model-space;
- targets must be local to each other using a scale-aware 0.90 in paper-space station window;
- the keeper is biased toward the normal straight-owned dimension rather than an event/branch helper;
- removed source, branch and event obligations are transferred to the keeper;
- certification is rerun before deletion is accepted;
- if required coverage would change, the entire proposed consolidation group is rejected.

This means a size/elevation/transition event cannot create another locating dimension solely because it is a different event identity when the physical duct edge/center remains at the same X/Y coordinate.

## What was deliberately NOT changed

- Pipe AutoDim v5.6.0.
- Pipe AutoTag v1.4.
- Duct AutoTag event detection/placement from v2.3.
- Square-to-round direct component-tag suppression from v2.3.
- Duct edge-vs-round-center dimension rules.
- True-riser dual-axis locating.
- Organizer and Fab Hover.

## Field-test goal for tonight

Run Duct AutoTag + Duct AutoDim on a clean copy of the same area and compare to the human completed sheet. The key signal is not maximum annotation count. It is whether every distinct duct location/change is understandable while repeated same-coordinate dimensions disappear and the BOD/size tags remain the primary description of the duct itself.
