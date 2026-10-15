# ROBMEPTOOLS v2.1 — Duct AutoTag square-to-round transition fix

## Field issue
Fabrication square/rectangular-to-round transitions could be attached inline between straight duct runs but receive no direct transition tag.

## Root cause
The direct component detector required the two fitting connector `BasisZ` vectors to be strongly opposing. Some Fabrication databases/catalog parts report those connector axes inconsistently even when the part is a legitimate inline square-to-round transition. The hard geometry veto therefore rejected a valid cross-profile transition before tagging.

## Fix
Duct direct transition tagging now treats a proven cross-profile fitting as its own special case:

- two-port, non-straight Fabrication part;
- branch/tap/HETO/tee/wye identity vetoes still run first;
- connected-main alignment veto still runs first;
- square/rect/oval <-> round can be proven by the fitting connector profiles;
- if fitting connector profile metadata is weak, the profiles of the two attached straight duct runs are used as a fallback;
- once cross-profile geometry is proven, the unreliable connector-axis-opposition gate is not used to reject it.

Same-shape reducers continue to use the stricter straight-through axis and transition/reducer identity checks, so this patch is narrow rather than a general loosening of component classification.

## Preserved behavior
- Duct V9 straight-run event detection and placement unchanged.
- HETO/takeoff transition false-positive protections preserved.
- Pipe AutoTag v1.4 unchanged.
- Pipe AutoDim v5.6 unchanged.
- Duct AutoDim unchanged.
- Organizer/Fab Hover/Fabrication utilities unchanged.
