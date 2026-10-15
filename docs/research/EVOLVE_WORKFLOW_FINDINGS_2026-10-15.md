# EVOLVE public-workflow research and implementation implications

Reviewed 2026-10-15. Seventeen official help articles were retrieved successfully;
URLs, page titles, publisher modification dates and body hashes are recorded in
`EVOLVE_PUBLIC_SOURCES_2026-10-15.json`. This report summarizes documented behavior,
not inspected proprietary algorithms, content or tested EVOLVE/Revit performance.
It does not establish the newest available EVOLVE product release.

## Evidence mapped to ROBMEPTOOLS

| Topic | Officially documented behavior | ROBMEPTOOLS implication and current status |
|---|---|---|
| Connected hanger placement | Entire connected path, stop at direction changes, and interactive single-hanger modes [1]. | Existing AutoHanger uses geometric grouping. The pure graph foundation exists; a verified physical-connector adapter is the next increment. Do not equate nearby endpoints with connected runs. |
| Hanger rule profiles | ITM rules vary by part type, service, material and size; separate end, joint and branch/tap distances; insulated hanger choice [2]. | Replace preliminary hardcoded caps gradually with reviewed, versioned company profiles. Do not claim EVOLVE's UI rules constitute universal SMACNA certification. |
| Placement versus attachment | RFA and ITM are distinct profiles; linked-model and distance-below-level choices on the placement page are specifically restricted to RFA profiles [1,3]. | Preserve native attachment versus geometric contact as separate states. Public EVOLVE docs do not prove arbitrary IFC geometry can natively host our ITM hangers. |
| Collision handling | Configurable placement view, visibility requirements, rod clearance tolerance, bounded movement/stretch and highlighted unresolved clashes [3]. | Log geometry/view scope explicitly. Later preview must show unresolved clashes and recheck support spacing after movement. Do not infer a cleared model from current-view visibility alone. |
| Rod adjustments | ITM and family hanger adjustments have separate workflows; rod rounding, embeds and bearer adjustments are configurable [4,5]. | Keep Repair Draft Rods separate from native-host adjustment. Verify each rod's geometry and host state before supported API operations. Cut-length rounding is not a new structural intersection. |
| Sleeves and box-outs | Separate MEP/host filters, link selection, families/types, insulation, numeric or catalog-index oversizing; center/edge association rules [6–8]. | AutoSleeve is absent. Build solid-intersection candidates and an explicit rule schema before a placement button. Linked-host coordination must not imply cutting a linked document. |
| Fittings in sleeves | Release 10.0 notes expand AutoSleeve to ITM fittings and geometry-based sizing [9]. | Future acceptance must include elbows, tees, transitions and dampers, not just nominal-size straight centerlines. This is a documented vendor capability, not implemented ROBMEPTOOLS functionality. |
| Tags and dimensions | Arrange Tags recalculates selected tags, with ignored-element settings; Quick Dimensions requires parallel elements and offers center/edge methods and linked selection [10,11]. | Preserve physical-reference and coverage guarantees. Optional quick dimensions are a distinct workflow from our full-grid AutoDim. Vendor tag arrangement is not evidence of complete annotation collision elimination. |
| Prefabrication and reports | Prefab Manager manages assemblies/packages, statuses, renumbering, views/sheets and exports; release 10.2 adds spool-sheet tag arrangement and report corrections [12,13]. | Keep prefab/BOM downstream of hanger/sleeve correctness. Schedule numbering alone does not implement a prefab manager. |

## Documentation conflicts and regression priorities

- The placement article still lists an unfiltered-view checkbox in the dialog,
  while the 10.0 release notes say the redundant dialog option was removed and
  retained in settings [1,9]. Treat visibility semantics as a requirement; do not
  reproduce one undocumented/version-ambiguous UI arrangement.
- Sleeve feature articles describe straights; the 10.0 release notes explicitly
  add ITM fitting coverage [6,7,9]. Record the product/version when comparing behavior.
- Known Limitations contains both unresolved and historically fixed issues. It
  describes insulation/placement-view sizing problems and moved/cloud-linked
  model failures; release 10.2 separately reports insulation and small-element
  sleeve fixes [13,14]. These are regression scenarios, not proof every version
  still has those defects. Some version lists also contain apparent duplicates;
  they are not a ROBMEPTOOLS compatibility declaration.
- Release 10.0 documents EVOLVE Revit 2027 support [9]. ROBMEPTOOLS 2027 support
  remains unverified; another vendor's support does not establish our API behavior.

Add acceptance fixtures for insulation, small diameters, moved/rotated links,
sloped structure and oblique penetrations. Compare calculated geometry and
created/skipped/unresolved counts; never accept visual similarity alone.

## Current implementation sequence

1. Read-only host-model FabricationPart connector snapshot and on-demand graph
   diagnostic, with physical/logical separation, reciprocal connection proof,
   service/size identity and explicit scope/unreadable reasons. No placement changes.
2. Field-check that diagnostic in Revit 2025 on five-piece, branched, sloped and
   disconnected/coincident fixtures. Linked-source collection is a separate adapter.
3. Compare graph-derived runs against existing AutoHanger preview. Add company
   rule profiles, station registry and rerun tests before migrating the apply path.
4. Independently verify per-rod structural hits, source transforms and host state;
   then add bounded collision resolution and attachment-safe repair workflows.
5. Integrate/build AutoSleeve only after its own solid-host/clearance/preview gates;
   then annotation/data improvements and, later, prefab/export milestones.

This sequence is ROBMEPTOOLS engineering judgment informed by the public sources;
it is not a claim that EVOLVE uses our graph, ray-cast or transaction algorithms.

## Sources

1. [Hanger Placement](https://help-mechanical.evolvemep.com/hangers/multi-service-bearers)
2. [ITM Hanger Settings](https://help-mechanical.evolvemep.com/settings/hanger-specifications)
3. [Hanger Placement Settings](https://help-mechanical.evolvemep.com/hangers/msb-settings)
4. [ITM Hanger Adjustments](https://help-mechanical.evolvemep.com/hangers/hanger-rod-adjustments)
5. [Family Hanger Adjustments](https://help-mechanical.evolvemep.com/hangers/family-rod-adjustments)
6. [Sleeve Settings](https://help-mechanical.evolvemep.com/sleeves/sleeve-settings)
7. [Auto Place Sleeves](https://help-mechanical.evolvemep.com/sleeves/auto-place-sleeves)
8. [Convert to Box-Out](https://help-mechanical.evolvemep.com/sleeves/convert-to-box-out)
9. [EVOLVE Mechanical 10.0.1 release notes](https://help-mechanical.evolvemep.com/announcements-release-notes/evolve-mechanical-10-0)
10. [Arrange Tags](https://help-mechanical.evolvemep.com/annotations-annotation/auto-arrange-tags)
11. [Quick Dimensions](https://help-mechanical.evolvemep.com/quick-tools/quick-dimensions)
12. [Prefab Manager](https://help-mechanical.evolvemep.com/spooling-prefabrication/prefab-manager)
13. [EVOLVE Mechanical 10.2.1 release notes](https://help-mechanical.evolvemep.com/announcements-release-notes/evolve-mechanical-10-2-0)
14. [Known Limitations](https://help-mechanical.evolvemep.com/announcements-release-notes/known-limitations)

The source index also includes the feature catalog, ITM Hangers overview and
Annotation Settings for the broader feature map.
