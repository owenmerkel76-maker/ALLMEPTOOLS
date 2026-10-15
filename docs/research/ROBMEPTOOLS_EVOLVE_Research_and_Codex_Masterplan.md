# ROBMEPTOOLS — EVOLVE Mechanical Feature Research and Codex Master Plan

**Date:** 2026-10-15  
**Target:** Revit 2025 first, Revit 2027 second (conditional API compatibility).  
**Implementation:** Maintain the existing ROBMEPTOOLS pyRevit extension and working commands; build interoperable new modules using original code and publicly documented functional requirements. Do not extract or reproduce proprietary EVOLVE code, families, symbols, configuration files, or assets.

## 1. Executive goal

The goal is not to imitate an EVOLVE ribbon. It is to build a reliable MEP fabrication detailing *platform* with a common document/geometry engine shared by automatic hangers, sleeves, annotation, fabrication metadata, QA, and eventual spooling/BOM. Avoid monolithic scripts, repeated geometry logic, and blanket project mutations. Each function must have a preview, clear rules, safe cancellation, idempotent rerun, explicit skipped reasons, and a generated report.

The current ROBMEPTOOLS work already includes AutoDim for fabrication MEP and grids, AutoTag for duct/pipe, Fab Hover, tag/dim organization, and hanger development, plus a separate sleeves tool project. Protect those investments; do not rewrite or silently replace verified behavior. Before any changes, examine the actual repository and document its baseline and untested areas. In the user's hanger field testing, fallback rod lengths were wrong and some runs received too many supports; preserving correct IFC detection and avoiding unverified rods is essential.

## 2. What EVOLVE Mechanical publicly documents

The feature inventory is divided into Locations, Prefabrication, Sleeves, Supports, Points, Annotation, Quick Tools, Utilities, Integrations, and Resources. Official reference: https://help-mechanical.evolvemep.com/getting-started/list-of-features

### Supports / Hangers
- Single-service ITM hangers: fabrication duct and pipe runs, rules by fabrication type/service/material/size and insulation, maximum spacing, end/joint/branch/tap offsets, selection of ITM hanger button; ITM Hanger Settings: https://help-mechanical.evolvemep.com/settings/hanger-specifications
- Fabrication hangers: official ITM Hangers workflow: https://help-mechanical.evolvemep.com/hangers/intro-to-hangers
- General Hanger Placement: profiles, ITM or RFA, single and trapeze styles, minimum/rounded bearer width, multi-tier spacing, rod and hardware choices, clash moves and bearer stretches; https://help-mechanical.evolvemep.com/hangers/msb-settings
- Placement scope: entire path, until direction change, or interactive single hanger; attachment targets include nearest overhead structure, link, plane, and level-offset methods but target choices differ by profile type; https://help-mechanical.evolvemep.com/hangers/multi-service-bearers
- ITM Rod Adjustments: by view/project/selection/run, extend to structure or plane, extension and rounding, bearer stretch, optional embeds; https://help-mechanical.evolvemep.com/hangers/hanger-rod-adjustments
- RFA Family Hanger Adjustments: recompute lengths, attachments, center rod, bearer; https://help-mechanical.evolvemep.com/hangers/family-rod-adjustments
- Seismic support, hanger clash checks, auto straps, and point load estimate. The point load tool uses total selected weight divided by selected hanger count and emphasizes that a licensed engineer must verify any values: https://help-mechanical.evolvemep.com/hangers/estimate-point-loads
- Auto Place Straps has a published limitation that it does not support fabrication ITM trapezes at that documentation version: https://help-mechanical.evolvemep.com/hangers/strap-settings

### Sleeves and Box-Outs
- Sleeve rules select MEP eligible parts and permissible wall/floor hosts via filters; sleeve family/type, fixed or catalog-index oversizing, insulation, extra length, primary vs linked models, and status; https://help-mechanical.evolvemep.com/sleeves/sleeve-settings
- Auto Place Sleeves identifies penetrations for eligible RFA and ITM elements and places sleeves/box-outs; https://help-mechanical.evolvemep.com/sleeves/auto-place-sleeves
- Place Sleeves permits manual placement, predefined settings, and without a host when selected; https://help-mechanical.evolvemep.com/sleeves/place-sleeves
- Convert to Box-Out clusters nearby individual sleeves by edge/center distance and replaces them with a rectangular box-out; https://help-mechanical.evolvemep.com/sleeves/convert-to-box-out
- Crucially, EVOLVE Mechanical 10.0 expanded AutoSleeve to ITM fittings, including elbows, tees, transitions, and dampers, sized from fitting geometry; https://help-mechanical.evolvemep.com/announcements-release-notes/evolve-mechanical-10-0

### Annotations, Dimensions, Prefab
- Annotation rules map category, fabrication service, and tag type to tag family, leader, placement and offsets; https://help-mechanical.evolvemep.com/settings/annotation-settings
- Project Tags and Tag All apply saved element-filter-based tag rules to an entire view or selected elements; https://help-mechanical.evolvemep.com/annotations-annotation/project-tags
- Arrange Tags recalculates positions of selected tags; 10.2 adds automatic arrangement on spool sheets; https://help-mechanical.evolvemep.com/annotations-annotation/auto-arrange-tags
- Quick Dimensions: selected *parallel* system elements; center-center, edge-edge, center-edge, linked-element selection, configurable handle; do not confuse this with the user's full-grid fabrication AutoDim goal; https://help-mechanical.evolvemep.com/quick-tools/quick-dimensions
- Prefab Manager / Spooling: group fabrication components into spool assemblies and packages; generate views, sheets, schedules, tags and dimensions; continuation tags, slope/point coordinates, hanger inclusion, renumbering and BOM; https://help-mechanical.evolvemep.com/spooling-prefabrication/prefab-manager and https://help-mechanical.evolvemep.com/spooling-prefabrication/prefabrication-settings

### Other noteworthy features
- Multi-Run Select, fabrication alignment/spacing, optimize fittings, insertion of offsets, connection/reconnection, slice/move straights, rotation, quick dimensions; https://help-mechanical.evolvemep.com/quick-tools
- Rule-based duct stiffener family placement to straight ITM duct by service, material, size and spacing; https://help-mechanical.evolvemep.com/quick-tools/itm-stiffener-settings
- Element Filter as a reusable AND/OR predicate system and selection palette: https://help-mechanical.evolvemep.com/element-filter/creating-element-filters
- Parameter Sync copies and computes fabrication fields to readable shared parameters with configurable run triggers; https://help-mechanical.evolvemep.com/advanced-utilities/parameter-sync
- Duct Gauge Manager maps ITM materials and thickness to a gauge parameter; https://help-mechanical.evolvemep.com/utilities/duct-gauge-manager
- Point tools for sleeve/hanger layout, status, and coordinate reports; reports for hangers, pipe cuts, BOMs, ancillary material, and spool sheets; https://help-mechanical.evolvemep.com/announcements-release-notes/evolve-mechanical-10-0

## 3. Gap evaluation — verify against repository

**Existing but needs reliability improvements:** AutoHanger spacing/grouping/rod length and IFC target validation; duct and pipe AutoDim; AutoTag placement; tag/dim Organizer; Fab Hover performance. Preserve existing successful modes and don't assume all are fully field proven.

**Prototype / separate development:** AutoSleeve for plumbing through concrete; ensure truly solid/linked model geometry detection beyond DWG hatch inference.

**High-value missing or not yet confirmed as production ready:** a shared fabrication/IFC model selector; rule editor and import/export; dedicated manual rod adjustment and validate/repair commands; single/multi-service trapeze; sleeve fitting intersections; box-out clustering; duplication audits; cut lists and layout points; reusable element-filter/connected-run picker; prefab metadata/part reports; safe project parameter mappings.

**Later phases:** automated shop spool and package sheets, annotation on spool views, stiffeners, seismic support workflows (for licensed engineering review), gauge and ancillary reporting, model utilities and office-wide settings.

## 4. Proposed core architecture

Keep the existing pyRevit extension and independent ribbon buttons. Add an internal shared library, for example:

```
ROBMEPTOOLS.extension/
  lib/robmep_core/
    compat/                 # Revit-version adapters and feature checks
    model_sources.py        # linked RVT, IFC, imported/DirectShape source enumeration
    transforms.py           # local/world/linked coordinate transforms
    geometry.py             # solids, intersections, ray hits, spatial indexing
    mep_parts.py            # ITM + RFA normalization
    connector_graph.py      # connected-run topology and fittings/branches
    rule_engine.py          # match by category, service, material, size, insulation
    host_resolver.py        # structural surfaces, BOS and penetrated walls/floors
    audit.py                # logs, reasons, placement registry, status
    transactions.py         # preview/apply, rollback, cancel, scoped failures
  lib/robmep_features/
    hangers/
    sleeves/
    annotation/
    data/
    prefab/
```

Paths are illustrative; inspect the existing repository before picking actual file layout. Reuse the Fab Hover WPF visual pattern as the design starting point, but avoid expensive continuous model event scanning.

### Shared element model
Normalize every candidate into a typed record:
- source model identity (host, Revit link, IFC link/import), project UniqueId, link instance identity, link transform;
- element UniqueId and category, fabrication service + button/condition/CID when accessible, material, shape, insulation, size, centerline/axis, physical envelope;
- connector graph neighbors, run ID and topology, reference level and actual world coordinates;
- geometry source quality: `ExactSolid`, `MeshValidated`, `ReferenceOnly`, `2DInferred`, `Missing`.

Support project-scoped source pickers for IFC steel, joists, deck, concrete hosts, and MEP. Never depend on hard-coded source filenames, category IDs, family names or the user's current project coordinates. Persist source selection with a stable identity and verify it on every rerun. Allow users to deliberately exclude other sources.

### Structural geometry
- Convert Revit link coordinates to host-world using the link instance transform. Do not assume untransformed Z or one constant BOS for all beams/joists.
- For each hanger rod anchor XY, query overhead structural candidates and intersect the upward ray with real underside geometry. Calculate left and right rods separately; sloped structure can produce unequal rod lengths.
- Treat Joist, Beam, Roof/Deck, Floor and Reference Plane as separate selectable priorities, but choose hits by actual geometry, not by a global level alone.
- Distinguish underside of beam versus top of beam, mesh triangles versus solid faces, and bounding-box prefilter versus verified hit. Reject a bounding box alone as a rod-end measurement.
- If an IFC element has no usable solids/mesh, log `NO_VERIFIED_HOST_GEOMETRY`, leave rod unverified, and permit explicitly approved free-ended rods. Do NOT fabricate lengths from another area of the project.
- An IFC link does not inherently become native hostable Revit structure; do not promise physical API association to it. Rods may be geometrically positioned against visible IFC even if truly attached is unsupported. Keep `geometric_contact` separate from `native_attached`.

### Hanger planning algorithm
1. Enumerate only eligible ITM/RFA duct and pipe elements under explicit selected scope; collect and inspect connectors, isolate connected straights, identify fittings/taps/equipment/terminal ends and service boundaries.
2. Form runs as a connected graph with explicit stop/split conditions. Compute cumulative path distance instead of restarting hanger spacing at every fabricated piece.
3. Apply prioritised rules by service, type, material, size band, insulation and configuration. Default to explicit company/engineer-approved SMACNA/contractor rules; never assert a universal spacing table from thin air.
4. Create support *stations* subject to maximum unsupported spans and end/joint/tap/branch keep-outs; choose as few stations as possible under constraints. Include short segments and adjacent branch continuity. If a rule needs extra support near a fitting, count it only once if a neighboring station qualifies.
5. Build and deduplicate a support-station registry keyed by run continuity, station projection, host IDs, support type and geometric tolerance. Account for already-existing hangers and user manual edits. Rerunning unchanged input must result in **zero new hangers**.
6. Generate rod start points from actual hanger geometry, not only duct center elevation. Determine support style (strap, clevis, trapeze), bearer footprint and orientation, insulation gap and hardware.
7. Resolve each rod's upward structural hit; choose a verified structure hit if possible; otherwise handle based on strict user fallback policy (`skip`, `free_end_review`, or `approved_elevation`). No silent reference-level fallback.
8. Evaluate clashes for rod, bearer, hanger body and attachment; attempt bounded move/width changes but revalidate maximum support span. If no viable placement, mark unresolved; never silently add a second support as an uncontrolled fallback.
9. Preview stations, rod hits, exceptions and counts; apply in a TransactionGroup with per-station SubTransactions and rollback on failure. Only create duplicates if user expressly requests them.
10. Record source IDs, rules, structural hit type, rod length by side, and all warnings; provide `Recalculate Rods`, `Remove Duplicate Hangers`, and `Validate Supports` commands.

### API trap: Revit Fabrication hangers
Revit 2025 supports `FabricationPart.CreateHanger(...)` with a host `FabricationPart` connector, distance along straight and `attachToStructure` flag. The hanger button must be valid for the loaded fabrication service. See Autodesk sample: https://github.com/jeremytammik/RevitSdkSamples/blob/master/SDK/Samples/FabricationPartLayout/CS/FabricationPartLayout.cs and Revit 2025 method: https://www.revitapidocs.com/2025.3/9e3e7333-0662-57d9-e6c9-4c477ff652bd.htm

`FabricationRodInfo.SetRodLength(index, length)` cannot modify auto-hosted hanger rods; first validate the API properties/hosting state and choose the correct operation. `GetRodLength` and structure extension semantics need checking rather than blindly adding extensions. Reference: https://rvtdocs.com/2025/Autodesk.Revit.DB.FabricationRodInfo.SetRodLength and https://rvtdocs.com/2025/b52fe314-2639-a697-cf97-b3e4824818f8

The generic `attachToStructure=True` does NOT promise that Revit will find or physically host to a user-selected IFC object. Geometry-based ray casts and explicit rod settings need their own implementation and validation.

## 5. AutoSleeve feature architecture

### Detection
1. User selects scope: selected MEP, active view, selected level, or project. Choose native/linked/IFC structure sources; classify concrete wall/floor only when actual semantic geometry supports that classification.
2. Collect centerline segments and real 3D envelopes of ITM/RFA straights and eligible fittings. Broad phase: transformed axis-aligned bounding boxes / spatial index. Narrow phase: actual 3D solid intersection, including wall/floor thickness and oblique penetration axis.
3. For fittings crossing hosts, derive minimum enclosing crossing envelope from *clipped fitting geometry* or conservative 3D projection, never merely the nominal size from an adjacent straight.
4. Determine sleeve shape, orientation, center, extents, host thickness, penetrated run/element IDs, shape clearances, insulation and firestopping allowance (configurable, no automatic code-compliance assumption). For an angled passage, ensure required length and width account for passage angle rather than only perpendicular host thickness.
5. Rules: service/material/host type/fire rating/insulation; fixed clearance or rounding to approved available catalog sleeves; sleeve offset past wall faces; permissible sleeve types and parameters.
6. Detect existing sleeves using stable source/host ID identity and geometric tolerance. Update eligible existing generated sleeves when selected, otherwise skip and report; never duplicate by default. Preserve manually placed or locked elements.
7. Group nearby sleeves by either edge-to-edge or center-to-center threshold; preview candidate box-out group and size using minimum bounding rectangle of all required clearances. Require explicit approval for replacement of existing sleeves.
8. Place independent sleeve families (RFA) in MEP model; when host is linked, do not imply that placing a sleeve edits/cuts linked concrete. Provide `coordination_only` versus `host_cut_authorized` states. A coordination-only sleeve needs a penetrations/openings schedule for structural approval.
9. Write sleeve parameters: source element IDs, host and link IDs, level, nominal size, actual opening dimensions, thickness, status, quality, and penetration group ID.
10. Provide a `DWG 2D Hatch Candidate` mode only when 3D host geometry is genuinely missing. Inferred wall thickness and penetration elevations are unverified and require review; don't classify any hatch as concrete without user mapping.

### Acceptance cases
- Native concrete wall, linked wall rotated/transformed, vertical slab, sloped floor, rectangular insulated duct, round pipe, oval duct, ITM tee/transition/damper/elbow, cluster of three adjacent pipes, wall with opening, linked wall moved after placement, sloping pipe, duplicate rerun.
- Output a diagnostics CSV showing `PLACED`, `EXISTING`, `SKIPPED`, `HOST_UNKNOWN`, `NEEDS_REVIEW`, `CANNOT_CUT_LINK`, `FAILED`.

## 6. AutoTag and AutoDim improvements

**AutoTag:** Preserve working duct/pipe coverage logic. Add shared service/element filter rules, per-tag family and leader preferences, Tag All by view/selection, user tag overrides, duplicate detection keyed by element+tag purpose+view, and an optimization pass with obstacles (MEP solids, dimensions, other tags, crops, view annotations). The rearranger should preserve manually locked positions and keep leaders compact. Measure overlaps in view/paper-space coordinates, not model-space only. Support BIM fab tags such as BOD/size, BOP/size, type and numbered parts. Existing Fab Hover lookup and annotation should share read-only part data but not the same live refresh event path.

**AutoDim:** Keep geometric-certification/grid coverage engine. Add an optional quick dim mode for parallel MEP center/edge reference combinations and linked references where Revit permits stable witness references. Pre-validate geometry/reference stability; never place zero or invalid dimensions. Plan, deduplicate and layout dimensions before a single apply transaction. Preserve existing dimensions unless explicit cleanup chosen. Show a diagnostic on missed targets and a benchmark against human-issued sheets.

**Organizer:** Extend conflict pairs to tag-tag, tag-dim, dim-dim, annotation-MEP, and optionally linked DWG background obstacles. Optimizer order: preserve annotation meaning > no duplicate > no overlap > compact leader > preferred tag side. Never regress good target coverage to get a pretty page.

## 7. Reusable downstream features

**P1:** Element Filter / Run Picker; new source model picker; hanger validation/rod recalculation; sleeve rule settings and box-outs; model QA dashboard and reports.

**P2:** AutoTag presets/Tag All, quick dimension; duct stiffener placement for selected ITM straights; gauges from catalog/material mapping; fabrication Part Properties and Parameter Sync to shared parameters; hanger rod/bearer cut list, estimated load summaries prominently labeled engineering-review-only; sleeve/opening schedules and CSV point exports.

**P3:** Prefab Spool manager: define connected ITM assembly, add/remove/merge spools; assign spool ID, package, parts, hanger association; sheet generation (plan/elevation/isometric), continuation tags, slope/elevation callouts, numbering, dimensioning and count/cut reports. Do not begin this until hanger/sleeve/annotation accuracy is established.

**P4 / later:** multi-tier hanger support, install points, selectable anchors/hardware/embeds, seismic support placement with mandatory engineering review, connected-run remodeling tools, advanced data profiles, optional export to shop process tools. These require reviewed structural/attachment rules and should not be marketed as safe structural design.

## 8. Reliability, testing and delivery requirements

- Use Revit API 2025 as the baseline; add guarded adapters for 2027. Never assume sample methods from 2026/27 exist in 2025 without verification.
- Keep units internally in Revit feet with explicit conversion at boundaries, and log all values with units. Match reference levels for displayed offsets but use absolute actual 3D geometry for intersections.
- Linked geometry trap: Revit's `ReferenceIntersector` has `FindReferencesInRevitLinks`, but geometric `ElementFilter` behavior across links has coordinate caveats. When uncertain, transform candidate geometry into a shared coordinate frame and do own narrow-phase hit verification. Official doc: https://help.autodesk.com/cloudhelp/2026/ENU/Revit-API-MainReference/files/html/027d8736-697e-ebe8-37d9-901f96713540.htm
- UI: Fab Hover-style reusable WPF dialog; scope picker; model/link chooser; service/type picker; rules grid; Dry Run, Apply, Diagnostics. No blind “Apply All”. Save project rules in JSON with versioned schema, export/import configurations, and validate on each run.
- No silent structural/elevation fallback. Every generated hanger or sleeve must have a calculated, reported confidence/geometry source; separate verified quantities from provisional estimates.
- Avoid DocumentChanged heavy processing. Prefer explicit commands, cached immutable element snapshots with invalidation, batch evaluation, and cancellation.
- Use bounded/filtered 3D geometry, spatial index and model scopes for performance; prioritize correctness over broad unverified coverage.
- QA tests: (1) 15' single straight, (2) 5 x 3' connected straights, (3) tapped HETO and tee near joint, (4) two parallel overlapping runs, (5) sloped IFC joist, (6) sloped roof/deck with different left/right rod heights, (7) two roof areas with different BOS, (8) absent IFC geometry, (9) rerun after existing/manual hangers, (10) MEP fitting through linked wall, (11) multiple adjacent sleeves requiring box out, (12) rotated/transformed links, (13) small pipe and oversized insulation, (14) faulty host and rollback, (15) unsupported fabrication button.
- Hard acceptance: zero duplicate hangers/sleeves on unchanged rerun; max support span compliant with selected approved rule set; support count explainable as minimal under constraints; every rod length is derived from tested 3D geometry or explicitly marked provisional; non-verified elements are never silently committed as verified; canceled commands leave the model unchanged; existing AutoDim/AutoTag/FabHover regressions are zero in their prior field-tested fixtures.

## 9. Codex directive — paste this into your existing tool development session

> Audit my existing ROBMEPTOOLS extension first, including AutoHanger, AutoDim, AutoTag, Tag + Dim Organizer, Fab Hover and any sleeve tool. Do not overwrite working code or create a new unrelated package. Reuse the existing repository, separate ribbon commands and WPF look-and-feel. Build the **shared MEP/IFC geometry and element/rule infrastructure** described in this master plan before expanding the menu. Implement only Phase 1 initially: (a) connector-based connected-run analysis that treats multiple fabrication straight pieces as one run, (b) rule-based minimal-support-station planner with end/joint/branch restrictions and idempotent de-duplication, (c) model/IFC source selector and accurate independent rod-to-structure intersection on sloped steel, joists, and roof/deck, (d) fail-safe rod-length modes with NO fabricated fallback, (e) dry-run diagnostics before commit, (f) AutoSleeve candidate intersection engine for native and linked solid walls/floors with selectable families and a dry-run view. Check methods against **Revit 2025** APIs and implement proper internal unit conversions and transactions. Write targeted automated tests for graph segmentation, support spacing, rod hits, transformations, deduplication, and sleeve intersection. Do not invent SMACNA spacing values; expose an editable company-approved table. Explicitly distinguish documented EVOLVE features from our original proposed implementation and from verified capabilities of the current repository. Return a concise change summary, test results, risk list, and Revit field-test instructions. Stop after Phase 1 and wait for my Revit test results before expanding to prefab/point loads/stiffeners.

## 10. Additional official evidence and limitations

- Current EVOLVE Mechanical feature release notes, including the 10.2.1 tag arranger and sleeve bug fixes: https://help-mechanical.evolvemep.com/announcements-release-notes/evolve-mechanical-10-2-0
- EVOLVE's published feature/bug list notes historically troublesome link moves and rod/slope interactions; code must treat geometry updates as invalidating prior calculations: https://help-mechanical.evolvemep.com/announcements-release-notes/known-limitations
- EVOLVE documentation describes *user-facing behavior*, not proprietary source-level algorithms. All implementation decisions above are original engineering recommendations to Codex and must be tested in the user's Revit environment.

## Public documentation refresh and current implementation

See [EVOLVE workflow findings](EVOLVE_WORKFLOW_FINDINGS_2026-10-15.md) and its source index for 17 directly retrieved official pages, version-specific caveats and prioritized requirements. Phase 1 now includes the pure graph foundation and a read-only host connector diagnostic; placement migration, per-rod/linked geometry verification and AutoSleeve remain unfinished.
