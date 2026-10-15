# ROB MEP Auto Hanger v0.3.7 — IFC Geometry + Lean Layout (TEST BUILD)

**Revit 2025 and Revit 2027 target; pyRevit / IronPython compatible source.** This is a bench-tested **field test**, not a verified production release. Test first on a DETACHED COPY of the Revit model. No access to Revit was available during development.

## Why v0.3.6 looked wrong

Your last test reported **133 proposed hanger stations**, **127 DRAFT / unattached hangers** and **4 native IFC connections**, with **0 native roof connections**. A draft hanger's rod length in v0.3.6 did not correspond to a measured selected steel/deck hit. The new code does not assume two rods have the same end elevation. One unreadable IFC bbox previously could block the entire roof fallback. The latter is no longer a global veto.

## Three buttons — standalone HANGERS tab

1. **Auto Hanger** — normal tool with selected duct, IFC preferred beams/joists, native selected roof/deck fallback, separate fabrication-service hanger selection, size-dependent preliminary spacing caps, conservative side-tap/accessory and rod-envelope clearance. It minimizes redundant planned supports against existing hangers across each grouped duct run and uses a short open-run midpoint where safe. Actual elbows/changes of direction retain close-support checks. `Preview` is still ON by default. `Keep DRAFT` defaults ON in this test build and only keeps geometrically measured rods.
2. **Repair Draft Rods** — for the **127 existing v0.3.6 drafts**. Choose selected or all tool-marked DRAFT hangers, choose IFC framing and optional roof deck. It computes EACH rod's target using actual linked IFC solid or tessellated mesh ray intersections first, native selected roof/deck second. Reports unmeasurable members, requests confirmation, and repairs in place. Does **not** create, delete or attach hangers.
3. **Review Extra Hangers** — safe read-only check of tool-marked DRAFTs. Flags pairs on parallel/same-service ductwork within **12 inches** of each other and can select them in Revit. Does not delete them; not every extra hanger is within 12 inches, and not every nearby pair is unnecessary.

## Rod target hierarchy for each individual rod

* **Priority 1 — the selected IFC beam/joist geometry.** If a vertical ray from the hanger rod encounters a selected IFC member, the first actual surface hit is the target. Correct placement is calculated even if Revit cannot natively attach to the linked IFC element.
* **Priority 2 — selected native roof/deck geometry.** If there is **no selected IFC hit** at that rod, measure the roof at that rod's own world XY. Supports sloped roof surfaces via solid/mesh intersections.
* **No intersection / invalid API length / failed re-check / optional MEP envelope conflict — reject the hanger or leave the original DRAFT unchanged.** Never guess a level, bbox top, default rod length or structural attachment.

The per-rod target, linked member ID and type are appended to new Draft hanger `Comments` as `AUTO HANGER DRAFT / GEOMETRY-SIZED / UNATTACHED ...`. Repair Draft Rods appends a separate repair marker. These rod targets are geometry-based only; **they are not structural connections**. Verify rods, hanger hardware, flange/strap, top anchors, insulation and the required load capacity before using them in construction. You can use Revit's Attach to Structure later when a host is recognized.

## Spacing and extras

* Existing mapping is preserved: **EA, SA, RA, TA and other service IDs each select hanger buttons only from their own fabrication service**. Default rectangular hanger: Half Strap, with optional user-configured Trapeze selection.
* Existing preliminary caps remain 8 ft for smaller rectangular ducts, 5 ft and 4 ft for larger rectangles; round 10/8/6/4 ft depending on diameter, oval 4 ft, all reduced by a user-defined overall cap (default 8 ft). **These are planning caps, not certified SMACNA table maximums.** Actual allowable spacing depends on strap/rod hardware, construction, loading and project spec.
* The new planner reviews an entire collinear connected run before keeping planned stations, accounts for existing hangers and removes redundant supports only if end and branch coverage and maximum support span are retained. Short open runs with no turning fittings may get one midpoint support rather than a hanger at every fabrication piece end.
* Support within 2 ft of an **identified elbow/fitting run end** is kept; unrelated straight-end locations use a 3 ft preliminary open-end cap. The planner can still withhold conflicted stations, and fitting throat use is experimental. A nearby MEP obstruction may still need coordination.
* No existing hangers are automatically deleted or moved by the Auto Hanger tool. Use Review Extra Hangers to highlight close pairs; manually inspect before deleting any support. Existing unanchored DRAFTs are counted to prevent **physical duplicate model hangers**, but they are **not credited as structurally compliant supports**.

## Installation

**Standalone**: close Revit or remove old `ROBMEPHANGERS.extension` folder, extract the complete `ROBMEPHANGERS.extension` directory to your pyRevit extension search path. Reload pyRevit. The HANGERS tab contains all three pushbuttons.

**Existing ROBMEPTOOLS panel**: extract the three `*.pushbutton` folders into your actual `ROBMEPTOOLS.extension/<your tab>/<your panel>/` folder, replacing only the existing `Auto Hanger.pushbutton` folder; add the two new buttons. If your panel bundle.yaml has an explicit `layout`, append exact names `Repair Draft Rods` and `Review Extra Hangers`.

## Suggested test order

1. Make a detached model copy and save it. **Do not rerun Auto Hanger over the v0.3.6 trial area immediately**; all 127 previous DRAFT hangers may remain in the file.
2. Run **Repair Draft Rods**, first on two selected DRAFT hangers under two different IFC joist elevations, then on one under deck only. Inspect rods in 3D. Test whole-batch repair only after these pass.
3. Run **Review Extra Hangers** to identify close pairs; remove any unwanted extras **manually** after checking elbows, load and branch support needs.
4. In a clean area, run **Auto Hanger / Preview**. Check the planned and redundant-removed counts. Then uncheck Preview and test a short run, an elbow, a side tap and a sloped joist.
5. Return the new Auto Hanger results and a 3D screenshot; focus on any `DRAFT FAILURE`, unmeasurable IFC geometry or rod gaps. If IFC member geometry is neither Revit Solid nor Mesh, the tool will not fabricate a rod length.

## Testing and limitations

* Automated compilation, XAML parsing, deterministic spacing/optimization tests, per-rod priority and slope tests, and ray-to-mesh triangle tests pass offline.
* **Actual Revit 2025/2027 fabrication-service selection, creation, mesh transforms, rod length updates, linked IFC member geometry and collision clearance are not field-verified in this build.** Some Fabrication parts may refuse manual rod lengths; those candidates are rolled back or left unchanged.
* Clash check is conservative against *native* MEP envelopes, not exact solid-to-solid clash certification. Linked MEP models are not fully checked.
* SMACNA Chapter 5 placement requires confirmation of the approved hanger schedule, hanger type and real anchors. Do not assume draft hangers are approved supports.
