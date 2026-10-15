# ROBMEPTOOLS Duct AutoTag v1.11 — Human Plan Annotation Audit

## Field issue addressed
A vertical square-to-round transition at a diffuser/drop was receiving the same direct Transition/Reducer tag as a horizontal in-plan square-to-round fitting. In a floor-plan drafting context that adds annotation without improving the field-readable routing information.

## Research basis
- SMACNA HVAC drawing symbol guidance treats **duct transitions** and **rise/drop conditions** as separate communication devices: transitions communicate changed sizes, while rise/drop symbols communicate out-of-plane routing.
- Autodesk Revit/Fabrication documentation likewise provides dedicated rise/drop graphics for rectangular, round, and oval fabrication ductwork in plan views.
- Fabrication/shop-drawing guidance emphasizes communicating duct sizes, routing, fittings, levels and offsets clearly; this supports avoiding a redundant fitting tag when the change happens essentially perpendicular to the plan view.
- The project reference drawings supplied during development favor run-based size/elevation information and selective annotation rather than a label on every fitting.

Important: the standards do **not** state a blanket rule that vertical square-to-round fittings must never be tagged. The no-tag behavior here is a deliberate ROBMEPTOOLS human-drafting rule for plan/RCP views, based on the user's office-style preference and on the fact that rise/drop + adjoining run/terminal information already communicates the condition.

## Implementation
- Preserve v1.10 square/rect/oval <-> round detection for legitimate horizontal transitions.
- Compute a best-effort transition axis from the two physical connector origins; fall back to agreeing connector BasisZ axes only when required.
- Before direct Duct Transition tagging, compare that axis to the active view direction.
- Suppress only near-perpendicular transitions: `abs(axis · viewDirection) >= 0.88`.
  - Floor/RCP: vertical drops/rises are suppressed.
  - Section/elevation: that same vertical fitting is in-plane and remains eligible.
  - Sloped/offset fittings are retained unless they are genuinely near-perpendicular to the view.
- Apply this view-plane filter to Duct transitions only. Pipe transition behavior is unchanged.

## Preserved behavior
- Duct V9 straight-run event/BOD detection and placement: unchanged.
- HETO/takeoff/tap/tee/wye/branch vetoes: unchanged.
- Horizontal square-to-round direct transition tags: preserved.
- Duct AutoDim: unchanged.
- Pipe AutoTag v1.4: unchanged.
- Pipe AutoDim v5.6: unchanged.
- Organizer/Fab Hover/other package tools: unchanged.

## Sources reviewed
- SMACNA HVAC Duct Construction Standards, Symbols for Ventilation & Air Conditioning: transition sizing and rise/drop are distinct plan symbols.
- Autodesk Revit Help, Rise Drop Symbols for Revit Fabrication Detailing.
- Autodesk Revit Help, Rise Drop Symbols.
- Autodesk Support, modeling duct transitions with vertical/horizontal offset.
- User-provided project duct plan and field screenshot used as office-style reference.
