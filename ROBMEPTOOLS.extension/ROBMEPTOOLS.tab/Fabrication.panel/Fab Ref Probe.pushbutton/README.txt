FAB REF PROBE v0.1 — ROBMEPTOOLS

WHY THIS BUTTON EXISTS
The AutoDim layout engine is already finding runs, grids, corridors, collisions,
and same-run groups correctly. The current work-model failures are dominated by
MEP FabricationPart reference behavior:
  - "The references are not geometric references"
  - "No dimensionable plan edge/side face reference was found"

This probe isolates that layer instead of changing the production AutoDim tool.

WHAT TO TEST
Best first pass at work:
  1. Select one rectangular MEP Fabrication duct straight.
  2. Select one round MEP Fabrication duct straight.
  3. If available, select one MEP Fabrication pipe straight for the plumbing team.
  4. Optionally also select the Grid you want used for the tests.
  5. Run FAB REF PROBE.

If no Grid is selected, the probe automatically chooses the nearest parallel
straight host-model grid for each part, or the nearest straight grid when no
parallel grid is available.

WHAT IT DOES
For each selected FabricationPart, it records:
  - Revit version/build
  - fabrication category/domain/service/product/size/slope
  - connector shape and connector-based centerline
  - FabricationPart.GetDimensions() names/values
  - Grid element reference vs Grid.Curve reference
  - element-level FabricationPart reference
  - direct Solid face/edge references
  - GeometryInstance SymbolGeometry references
  - GeometryInstance InstanceGeometry COPY references for comparison
  - edge endpoint references
  - ElementReferenceType
  - stable representation
  - stable-reference parse/round-trip result
  - Element.GetGeometryObjectFromReference() result

Then it attempts real NewDimension() calls with each candidate reference inside
rollback SubTransactions.

IMPORTANT
- The parent transaction is ROLLED BACK.
- No test dimensions are retained.
- The model should be unchanged after the command completes.
- To keep the diagnostic bounded, it tests at most 8 selected fabrication parts
  and up to 28 reference candidates per part.

REPORT
A timestamped FAB_REF_PROBE_YYYYMMDD_HHMMSS.txt report is written to the Windows
Desktop (TEMP is used only if Desktop cannot be resolved).

WHAT TO SEND BACK
Attach the generated .txt report from:
  - Revit 2025 work / MEP Fabrication duct
and, when convenient:
  - Revit 2027 home / any Fabrication duct or pipe test model

The successful-reference matrix will tell us exactly which Fabrication adapter
to use for DUCT AUTODIM and future PIPE AUTODIM instead of guessing.
