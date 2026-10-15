# ROBMEPTOOLS Duct AutoTag v1.12 — Cross-Profile Transition Tag Suppression

## Field decision
The user does not want square/rectangular/oval-to-round transition fittings directly tagged for now, including the horizontal/in-plan examples shown in the 2026-10-07 field screenshot.

## Behavior
- Duct direct Transition/Reducer component tagging excludes any two-port fitting proven to be a cross-profile change: square/rectangular/oval <-> round.
- The exclusion applies regardless of whether the fitting is horizontal, vertical, sloped, or offset in the active view.
- The fitting detector itself is retained; only the direct component-tag candidate list is filtered. This makes the rule easy to reverse later without losing the v1.10 detection improvements.
- Same-profile reducers/transitions remain eligible: rectangular->rectangular, round->round, oval->oval.
- HETO/takeoff/tap/tee/wye/branch vetoes remain unchanged.
- The v1.11 out-of-view-plane filter remains in place for the remaining transition candidates.

## Preserved behavior
- Duct V9 straight-run size/BOD event detection and placement: unchanged.
- Duct AutoDim: unchanged.
- Pipe AutoTag v1.4: unchanged.
- Pipe AutoDim v5.6: unchanged.
- Organizer, Fab Hover, and all other package tools: unchanged.

## Intent
Communicate the profile/size change through the adjacent straight-run annotations rather than adding an extra fitting tag at every square-to-round connection. This is a temporary office-style rule and can be exposed as a menu option later if desired.
