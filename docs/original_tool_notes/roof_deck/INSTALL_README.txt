ROOFDECKTOOLS v0.3.1 — standalone pyRevit ribbon tab for Revit 2025
===============================================================

PURPOSE
-------
The new "Roof Deck From IFC" button reads a roof-only IFC2x3 file DIRECTLY.
Revit 2025 does NOT need to open or link the IFC first. The tool recognizes
IfcRoof faceted-BRep geometry and reconstructs EACH large planar roof
UNDERSIDE as a native Revit STRUCTURAL FLOOR hanger-host proxy.

This release was authored against the uploaded IFC:
  25014 - Warehime School of Business_R26_20260728_detached.ifc

Pure-Python IFC extraction tests recovered:
  TYPE 1B: 3,841.36 sqft, FLAT underside, no openings, BOS ~29'-4".
  TYPE 1A: 4,231.22 sqft NET, 1/4"/ft sloped underside, one 20 sqft opening.
No Revit 2025 runtime or actual fabrication-hanger tests were possible here.

INSTALL
-------
1) BACK UP your existing ROOFDECKTOOLS.extension folder.
2) Extract this ZIP and COPY the entire ROOFDECKTOOLS.extension folder
   alongside ROBMEPTOOLS.extension (NOT inside it), in a pyRevit extension
   folder which is already registered in pyRevit Settings.
3) Replace the previous ROOFDECKTOOLS.extension folder.
4) In Revit 2025 click pyRevit > Reload.
5) Look for ROOFDECKTOOLS tab, Roof Deck panel, Roof Deck From IFC button.
   The older Roof Deck From DXF button is retained for comparison.

TEST THE NEW IFC BUTTON
-----------------------
1) Open the Revit 2025 MEP project and save a backup copy.
2) Click ROOFDECKTOOLS > Roof Deck From IFC.
3) Browse to the ORIGINAL roof-only .ifc file (no Link IFC required).
4) Enter hanger-host proxy thickness (default 1.50 inches).
5) Read the preview. You should see exactly 2 roof sections with the
   areas shown above and one opening in the second roof.
6) Click Yes to construct NATIVE STRUCTURAL FLOORS.
7) The script automatically checks the resultant Floor UNDERSIDE planes
   against the source IFC within 1/8 inch at detected profile vertices.
   If ANY native floor fails, the entire transaction rolls back.
8) In an elevation/section, VERIFY positioning, dimensions, and underside
   elevations against the existing project grids and construction plans.
9) Test ONE MEP Fabrication hanger using Attach to Structure and check
   rod endpoints. Verify attachment suitability with the design team.

COORDINATE WARNING
------------------
The original IFC had the site placement at approximately
X=1,575,898 ft, Y=566,523 ft, and Z=72.25 ft. This is outside the
practical origin range for a native Revit 2025 model.

The DIRECT importer purposely skips ONLY the root IFC site coordinate
transform, while keeping the IFC building/storey/roof placements. New floors
are generated relative to the SOURCE project's internal coordinates.
This makes the geometry constructible near Revit's origin, but does NOT
establish that the 2025 MEP project uses the same internal origin/rotation.
Verify alignment with known architectural grids BEFORE using for hangers.

ROOF HOST LIMITS
----------------
- Native Revit STRUCTURAL FLOORS, not DirectShapes, meshes, or CAD.
- Preserves planar UNDERSIDE at source exported IfcRoof face.
- NOT an exact profiled/corrugated metal roof deck; cannot represent flutes.
- Host thickness is a uniform editable proxy; not automatically sourced
  from the IFC compound material assembly.
- Does not attach rods automatically; use Revit Attach to Structure and test.
- Large stepped underfaces (>5% of the dominant face area) are rejected,
  rather than reconstructed inaccurately.
- Supports IFC2X3 faceted-BRep IfcRoof only in this first version.
- Checks current Revit Floor underside geometry; can't guarantee fabrication
  hanger families/services accept attachment until tested inside Revit.
- Old native floors tagged with this source IFC name are replaced after
  explicit preview approval; external/copy floors are NOT touched.

OPTIONAL DIAGNOSTIC IFC
-----------------------
The separately supplied ROOF_ONLY_TEST_LOCAL_ORIGIN.ifc only zeroes the
site placement. It can be used for a separate Revit 2025 LINK IFC test;
there is NO guarantee the IFC linker will accept it. If it links, the roof
may not align with your project without manual coordination.

To check the built-in IFC linker instead, in Revit 2026 re-export IFC with
Export only elements visible in view and use Internal Origin / Project
Base Point (NOT shared survey coordinates). If both exports fail to link,
check Revit 2025 IFC import options/logs and IFC2025 add-in updates.

TO REPORT REVT ERRORS
---------------------
Send screenshot and COMPLETE pyRevit traceback. If no native floors were
created, report whether the failure happened during IFC parse, preview,
Floor.Create, or underside validation. Do not assume the geometry is correct
until verified in section against actual structure.

V0.3.1 FIX (2026-10-13)
-----------------------
- Fixes the Revit 2025 / IronPython "AttributeError: Name" failure when
  reading FloorType.Name. Direct FloorType.Name is not reliably readable in
  pyRevit's IronPython engine even though it exists in the Revit C# API.
- Both IFC and DXF buttons now read the parameter SYMBOL_NAME_PARAM or use
  Element.Name.__get__(floor_type) instead.
- IFC rollback alerts now report the failing STEP (floor type, roof 1/2,
  or commit) and the Python exception type. The full traceback is in the
  pyRevit output panel. Transaction rollback is preserved.
- This is a code fix; full Revit 2025 creation and hanger attachment
  still REQUIRE field testing. Do not assume success from a preview.

V0.3.2 FIX (2026-10-13)
-----------------------
- Fixes Revit 2025 exception at FloorType.SetCompoundStructure:
  "Input compound structure has wrong EndCap condition for this element type".
- Explicitly sets CompoundStructure.EndCap = EndCapCondition.NoEndCap
  before applying the single-layer compound structure to a new floor type.
- Checks the created FloorType retained both NoEndCap and requested thickness.
- Applies the same fix to the DXF button's native Floor Type creation code.
- Does not change the IFC parsing, two-roof geometry, openings or
  underside-verification algorithm; creation in Revit 2025 still needs testing.
- Rollback remains enabled; no model elements are kept if any step fails.
