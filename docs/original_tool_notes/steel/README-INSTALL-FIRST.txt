STEELTOOLS v0.5.1 - Slope-aware joist supports for Revit 2025
==============================================================

INSTALL (complete standalone extension)
1. Close or reload Revit. Move your OLD STEELTOOLS.extension folder entirely
   OUTSIDE any folder that pyRevit scans for extensions. Do not leave two copies.
2. Unzip this package. Copy the complete STEELTOOLS.extension directory into
   the same pyRevit extensions parent directory as the prior one.
3. Click pyRevit > Reload; open a PLAN or ORTHOGRAPHIC 3D view.
4. Select STEELTOOLS tab > Hanger Steel > Slope Joists.

INCLUDED BUTTONS
- Slope Joists [NEW] - group/array support proxies; level/sloped members;
  BOS start/end or verified roof rise; cross-row elevation step; physical
  underside intersection checks; no member changes without confirmation.
- Reconstruct Steel - retained from previous version (manual)
- Import Navis BOS - retained from previous version (CSV)
- Probe NWD - retained from previous version (diagnostic)

FIRST TEST
Try 2 joists in a COPY of your RVT with a loaded physical Structural Framing
family, ideally a rectangular beam with a continuous underside. Verify one BOS
reference and a roof rise or a second BOS. Pick first joist START, first joist
END, then the next joist point to establish spacing. Preview and confirm.
In section, compare the proxy bottom surfaces at several stations with the
actual steel reference or verified elevations before connecting hangers.

ELEVATION MODES
- BOS START entered as offset from selected Level, or project internal Z.
- BOS END optional (same datum as start), OR signed roof rise in inches per
  horizontal foot (+2 = joist rises 2 inches per horizontal foot from start).
- Blank BOS END and blank rise = level member.
- Cross-row change at START and END can differ, yielding varying joist slopes.
- A new area always requires a NEW BOS START; this value is not reused.
- All elevation information is USER SUPPLIED; the NWD is NOT measured.

SAFETY & LIMITATIONS
- The tool cannot read member geometry from the published/locked NWD.
- Selecting/picking in Revit is used for plan XY, not exact NWD steel geometry.
- Native Revit Structural Framing proxy geometry is measured along a vertical
  line through the beam at 20%, 50%, and 80% of its span. A member that cannot
  be measured to within 1/16 inch of input linear BOS is not kept.
- This DOES NOT validate input BOS against the NWD. Do not use assumed elevations
  to calculate production hanger rods. Check sloped roof top chord vs the actual
  JOIST BOTTOM CHORD; they can have different slopes.
- For tapered, curved, kinked, variable-section or split joists, create smaller
  segments/areas and verify separately. One straight framing proxy cannot fit
  a non-linear bottom chord.
- Testing with MEP FABRICATION hanger attachment is still required: real joist
  chords, embed/clip rules and engineering approval are out of scope.
- Built-in Revit model transactions create/edit proxy framing and may set a
  horizontal pick work plane in the active orthographic 3D view.
- A physical Structural Framing family MUST be loaded in your Revit 2025 project.
- This build is STATICALLY VALIDATED ONLY, not tested inside Revit 2025.

TOOLPACK: STEELTOOLS / Revit 2025 / IronPython 2.7
