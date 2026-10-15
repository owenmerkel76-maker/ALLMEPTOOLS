FAB REF CLASSIFIER v0.2 — ROBMEPTOOLS

PURPOSE
The first FAB REF PROBE proved that Revit 2025 exposes many dimensionable
references on both MEP Fabrication Ductwork and MEP Fabrication Pipework.

The remaining production question is not "does a reference work?" but:
"which working reference is the one we actually want to dimension to?"

THIS CLASSIFIER ANSWERS THAT.

CLASSIFICATION RULES
- Fabrication Pipework: verified CENTER reference -> nearest host grid.
- Round Fabrication Ductwork: verified CENTER reference -> nearest host grid.
- Rectangular/Oval Fabrication Ductwork: verified NEAR EDGE -> nearest host grid.
- Fittings, tees, elbows, wyes and other non-straights are skipped even though
  Revit may expose valid dimension references on them.

HOW IT CLASSIFIES
1. Builds the physical run centerline from the two farthest physical connector origins.
2. Harvests REAL referenced geometry from GeometryInstance.GetSymbolGeometry().
3. Transforms witness geometry into model coordinates.
4. Measures every usable reference's signed plan offset from the connector centerline.
5. ROUND/PIPE:
     chooses the parallel linear reference closest to zero centerline offset.
6. RECTANGULAR/OVAL:
     chooses the outermost parallel edge/curve on the side facing the selected grid.
     side-face and endpoint references are fallback tiers.
7. Verifies the production candidate with an actual NewDimension() call using
   Reference(grid), inside a rollback SubTransaction.
8. If the primary reference fails, it tries a short ranked alternate list.

SAFETY
- Parent transaction is rolled back.
- No trial dimensions remain.
- The command does not modify fabrication parts.

BEST TEST
DUCT VIEW:
- Select 2-4 rectangular fabrication straights.
- Select 1-2 round fabrication straights.

PLUMBING VIEW:
- Select 2-4 straight fabrication pipes.
- Include at least one sloped sanitary/condensate pipe if available.

A selected host Grid is optional. Otherwise the classifier chooses the nearest
parallel straight host grid, with nearest-any only when no parallel grid exists.

REPORT
The command writes:
  FAB_REF_CLASSIFIER_YYYYMMDD_HHMMSS.txt
to the Windows Desktop.

SEND BACK
Attach the report from:
- the sheet-metal/fabrication duct view
- the fabrication plumbing view

If the winner offsets look correct and the rollback trials pass, the next build
can move these exact adapters into DUCT AUTODIM and PIPE AUTODIM.
