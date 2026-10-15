ROBMEPTOOLS AUTODIM SMART v2.3
DUCT v6.0 / PIPE v5.0 - ACTUAL GEOMETRIC COVERAGE CERTIFICATION

WHY THIS BUILD EXISTS

v2.2 could report DUCT branch legs still uncovered = 0 while the PDF still
showed obvious locating misses. PIPE improved to 2 reported branch misses but
still had visible drafting gaps.

That proves topology ownership / source bookkeeping is not enough to certify
that a drafting target is actually located.

NEW COVERAGE TRUTH

Every dimension created by AutoDim records:
- source element / branch key
- intended host grid
- intended edge/center target point
- dimension mode

After Revit commits, every surviving dimension is CERTIFIED using the actual
Revit Dimension object. It must pass all of these checks:

1. The actual Dimension.References include the intended Grid ElementId.
2. The actual Dimension.Value matches the recorded target-to-grid distance
   within 1/8 inch.
3. The actual dimension line remains geometrically normal to the intended grid.

If a surviving dimension fails certification, it is deleted. It does not count
as coverage and cannot block the correct dimension.

CERTIFICATION RESCUE

After false coverage is removed, the engine recomputes required targets and
rescues only geometrically uncertified:
- logical straight legs
- drafting-intent branch connector axes

Those rescue dimensions are certified AGAIN. Any rescue that still does not
measure the intended geometry is deleted.

FINAL COUNTS

The result window now reports:
- Required locating targets
- Certified targets
- False coverage rejected
- Certification-rescued logical legs
- Certification-rescued branch axes
- FINAL UNCERTIFIED LOGICAL LEGS
- FINAL UNCERTIFIED BRANCH AXES

Remaining misses are printed to pyRevit output by element ID / branch key.

PRESERVED
- single AutoDim Smart button
- Fab Hover-style WPF menu
- Duct / Pipe / Both
- Active View / Selection / Pick
- drafting-intent takeoff -> elbow/offset logic
- verified logical-leg grouping
- hybrid Revit AllRefs + strict Fabrication connector fallback
- mandatory collision rescue for genuinely difficult targets


v2.3.3 SELECTED GRID COVERAGE SAFETY
- ALL USABLE GRIDS = exact v2.3 grid choice behavior.
- PREFER SELECTED GRIDS = chosen grids win whenever geometrically compatible and within range; otherwise the original v2.3 search is allowed to recover the target.
- SELECTED GRIDS ONLY = strict filter; misses are expected if no chosen grid can serve a target.
- Legacy saved grid_mode=pick is mapped to PREFER SELECTED GRIDS.
