# ROBMEPTOOLS v2.0 — Pipe AutoDim centerline-only riser fix

## Field issue
A true vertical pipe/riser could receive both an ordinary centerline locating dimension and a second dimension to the physical pipe edge.

## Root cause
The normal Pipe AutoDim path was already centerline-only, but the dedicated dual-axis up/down/riser pass called `_riser_edge_point()` and created helper targets at the nearest physical edge. That made the riser pass semantically different from the rest of Pipe AutoDim.

## Fix
Pipe AutoDim v5.6 targets the true riser **center point** for both horizontal-grid and vertical-grid locating. The mode is now `updown-point-*`, and the deterministic helper token is generated from the center point.

## Preserved behavior
- True risers still receive dual-axis X/Y locating when needed.
- Existing coordinate-based duplicate suppression remains active.
- Bathroom fixture-tail suppression remains active.
- Duct AutoDim and Duct AutoTag are unchanged.
- Pipe AutoTag v1.4 is unchanged.
