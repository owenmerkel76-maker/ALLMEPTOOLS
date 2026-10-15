# Revit 2025 field-test plan

This plan covers the current working extension, including universal structural discovery/type approval in the existing Auto Hanger button and shared multi-source targeting/obstruction policy. The historical `v0.3.7-baseline` ZIP remains unchanged and does not contain these features. No replacement ZIP was generated for this iteration.

Offline regressions include metadata/discovery/preferences, simulated geometry and rod APIs, integration checks, and picker control doubles. They do not verify Autodesk Revit, rendered WPF, pyRevit, fabrication content, or real model geometry. Record results in Revit **2025**, the required host. Revit 2027 is mentioned by the supplied document and remains a separate unverified target. See [VALIDATION.md](VALIDATION.md) for current offline results.

## Preparation and evidence

Use a detached saved copy of a representative model and a small test area. Record the tested source revision or file manifest, Revit build, pyRevit version and engine, fabrication database/content version, selected services and hanger buttons, and every source/link instance transform. If testing a later authorized release ZIP, also record its checksum. Keep the original model and original extension installation available to compare behavior.

Install the complete current `extension/ROBMEPHANGERS.extension` folder in a configured pyRevit extension location, including all new helper files and `structure_picker.xaml`. Reload pyRevit and confirm the HANGERS tab still contains **Auto Hanger**, **Repair Draft Rods**, and **Review Extra Hangers**. Confirm Auto Hanger opens the new structural approval window; a source installation from the historical baseline ZIP will not. Avoid two active copies of the extension. Preserve prior pyRevit configuration for comparison without sharing secret values.

For each case, capture selected duct IDs; approved source/link instances, category/type groups and individual members; targeting mode and settings; preview/placement reports; created/repaired/unchanged hanger IDs; measured rod base/top coordinates and individual lengths; and a section or 3D image. Qualify structural member IDs by HOST or link instance, since equal numbers in different models are distinct. Compare preview stations to actual retained hangers after all rollbacks. Record whether each rod is natively attached or explicitly marked UNATTACHED. Report failures even when the tool gives a useful diagnostic.

The supplied README describes a prior v0.3.6 trial with 127 drafts; that count is historical context, not an expected count in a new model. Identify any existing tool-marked drafts before rerunning Auto Hanger. Repair and review them first where appropriate.

## Small-area test sequence

1. Confirm button loading, source discovery, structural approval tree, service inventory, and default Preview mode. Cancel each selection stage once to verify graceful cancellation and no model changes.
2. Run Preview on a short straight run with one service and uncomplicated native structure. Confirm Preview creates no elements or rod edits.
3. Place a small number of native hangers, inspect all rods, and rerun the same selection to check duplicate suppression.
4. Test multiple approved IFC/native/imported sources, Solid/Mesh geometry, transformed links, and clear versus obstructed fallback. Test measured unattached mode separately from native attachment.
5. Rerun the same project, open another project, unload/reload a source, and move a link to check restored preferences and mandatory review.
6. Test Repair Draft Rods on one or two selected drafts before a batch. Run Review Extra Hangers and inspect flagged and known unflagged pairs. Repair retains its original selection flow.
7. Add elbow, side-tap, accessory, branch, and diffuser-drop scenarios. Evaluate actual support gaps after rejected placements.

## Scenario matrix

Each expected result below is a field-validation goal. Offline checks do not establish that it passes in Revit. Discovery supports the host and any number of direct host links. Nested Revit model links are explicitly warned about and excluded; nested geometry instances within an element are a separate supported geometry case.

| ID | Scenario and settings | What to inspect / expected result |
| --- | --- | --- |
| HOST-01 | Revit 2025 with the team's actual pyRevit engine and fabrication content; all three buttons. | No load/import or WPF errors. Correct service rows, selected mappings, and usable commands. |
| UI-01 | New Auto Hanger session; cancel duct selection, structural approval, individual native/linked picks, main settings, and repair confirmation. | Preview starts enabled. Cancellation creates/edits no model elements. Cancelling individual picks retains prior approved selections and reopens the same tree. Real WPF events and rendering must work under the installed engine. |
| DISC-01 | Multiple direct links with arbitrary/renamed `.ifc` or cached `.rvt` filenames; Structural Framing, Generic Model, DirectShape, and host imported geometry. | Sources and supported candidates are listed without relying on filenames or one category. Unloaded links are visible warnings rather than usable sources. Generic/proxy discovery alone never approves a rod target. |
| DISC-02 | IfcBeam, IfcMember, exporter-specific/unknown IfcJoist, proxy joists, multi-component chords/webs/angles, W profiles, missing Revit types, no useful names, and Unicode metadata. | Type/profile/class evidence is shown where available; otherwise use Unclassified/Unnamed geometry. All component records remain available. Do not manufacture a useful profile from an arbitrary element name or silently lose components. Explicitly approve the intended groups/members. |
| DISC-03 | Model/category/type checkbox changes, Clear Selection, Select All Framing, individual member selection, and preferred/fallback role changes. | Tree parent/child states and counts match approved elements. Individual picks do not approve unrelated types; unchecking a type clears its direct picks. Deliberate framing bulk selection excludes columns, proxies, and ambiguous surface groups. Confirm the actual UI, not just offline control-double behavior. |
| PREF-01 | Confirm approved types/picks, priority, and rod maximum, then rerun the same saved project and open another or an unsaved project. Change the rod maximum again in main settings. | Every run displays the approval window. Same-project matching preferences are proposed for confirmation; final main-settings maximum is saved. Another project does not inherit approval or limits. Unsaved projects require session review. Original default is 20 ft; reject NaN/infinity and limits outside 1–60 ft. |
| PREF-02 | Rename/reload/change/unload/remove approved sources or types, reposition a link, and reopen Auto Hanger. Include equal runtime member IDs in different link instances. | Stable source/type/member identity avoids accidental cross-application. Missing, unloaded, changed, or unverifiable sources warn and require reselection instead of silently restoring approvals. Record fingerprint-related warnings and resulting tree selections. |
| SCOPE-01 | A structural Revit link nested inside another linked model, then that required model linked directly into the host. Also test nested GeometryInstance contents within a direct-source element. | Nested model link is warned about/excluded; its opaque box is not approved as structure. Direct host linking makes the supported source reviewable. Geometry instances still yield actual component intersections with correct transforms. |
| SVC-01 | Adjacent SA/RA/EA/TA or other distinct `ServiceId` runs. Include a service with no hanger palette. | Each created hanger comes from its host duct's own selected service. Missing mappings are reported and skipped. Different services remain separate in planning. |
| IFC-01 | Explicitly approved beam/joist solids directly above both rods, with a native deck also approved; preferred-first mode and a clear steel path. | Each rod targets approved preferred framing first. Native attachment reports the exact link/member IDs and measured height, or the measured draft is labeled UNATTACHED. Geometric contact alone is not attachment. |
| IFC-02 | Two different selected framing members above the two rods, at different elevations, plus a selected higher roof. | Different member IDs and distinct individual rod lengths where geometry requires them. No copying one rod's target elevation or length to the other. |
| IFC-03 | IFC represented by tessellated meshes, including double-sided open triangles, gaps between webs/flanges, closed shells, and concave/hollow geometry. | Native verification and draft sizing share the actual first usable intersection policy. A ray through a gap does not stop at a box face. Open double-sided surfaces remain measurable; closed-mesh containment is checked separately. |
| IFC-04 | Linked IFC translated, rotated about Z, and elevated; repeat with nested instance geometry and any supported nontrivial link transform. | Host XY/Z and member IDs remain correct after coordinate transforms. Check neither the link nor instance transform is omitted or applied twice. |
| IFC-05 | Approved framing with missing bounding boxes, unreadable Solid/Mesh/instance contents, and a distant element with readable bounds. | Missing boxes trigger actual geometry evaluation for both native verification and draft sizing. A real miss permits enabled fallback; unknown/partly unreadable relevant approved geometry holds it with diagnostics. Distant readable bounds exclude impossible rays. Unlocatable unreadable geometry cannot certify a clear miss. |
| IFC-06 | Deliberate Select All Framing versus explicit Generic Model/DirectShape/proxy type approval and individual picks. Include misleading names and a loaded/unloaded link. | Correct sources and reviewed groups/members are used. Classification is a review hint; proxies/ambiguous groups require deliberate approval. Unapproved geometry cannot become a target, though its body can still be an obstruction. |
| IFC-07 | Two direct links containing the same member element number; multiple instances of one linked document; native/imported preferred members; native and linked fallback decks. | Per-rod result retains source key, link instance, and member identity. Native attachment to the wrong link's same-numbered member is rejected. Each approved source uses its own transform. |
| ROOF-01 | One rod hits selected IFC; the other has no selected IFC hit but does hit selected native roof/deck. | Per-rod mixed IFC/roof targets, with correct individual lengths. The roof fallback must use selected geometry at each rod XY. |
| ROOF-02 | Sloped native roof/deck only; then sloped selected joists above it. | Rod lengths change across the hanger according to the actual underside/intersection. Sloped structure is distinct from sloped duct: intentionally sloped/vertical duct is currently withheld. |
| ROD-01 | No hit, below-base structure, an extremely close hit, above-limit structure, or one measurable and one unmeasurable rod. Include an IFC hit more than 0.02 ft but less than 0.10 ft above the base with another usable approved member or roof. | No guessed level, bounding-box-top target, or retained partly measurable new draft. A too-close first target does not suppress other usable approved hits or permitted fallback; placement still requires a clear rod path. If the too-close member obstructs that path, reject it with diagnostics. Repair leaves unmeasurable hangers unchanged. |
| ROD-03 | Rod base inside one closed Solid/Mesh shell, overlapping closed mesh components, or a closed mesh with each face repeated in reverse winding. Repeat from a base below the shell. | Do not interpret an exit/top face as an underside or escape containment uncertainty by falling back to a farther roof. Below-shell rays measure actual underside. Compare double-sided closed shells with open coplanar double-sided surfaces; the latter are not falsely treated as enclosed steel. |
| ROD-02 | Multiple hanger products and their free-rod API behavior; native attached and manually sized rods. | Confirm `GetRodEndPosition()` convention, support-base stability, XY alignment, and requested versus actual length after regeneration. Refused lengths roll back. Already attached rods are not resized by Repair. |
| RUN-01 | Collinear selected connected pieces of constant size/service, with a short run, a seam at its midpoint, and a longer run. | Plan across the run rather than independently at each shop-piece end. Inspect inboard seam adjustment, safe single-midpoint support where allowed, maximum spans, and end coverage. |
| RUN-02 | Rerun RUN-01 with existing native hangers and tool-marked unattached drafts, including supports hosted on different selected pieces. | Physical duplicate insertion is reduced across the selected run. Existing drafts remain visibly unapproved; draft counting must not be interpreted as approved anchorage. Existing hangers are not automatically moved or deleted. |
| RUN-03 | Same-service ducts close at endpoints but not connected; parallel nearby runs; real connection with a size/service change or elbow. | Detect false geometric grouping or missed desired continuity. The current grouping uses endpoint tolerances rather than a full connector graph. Inspect both proposal count and actual host choice. |
| SPAN-01 | Rectangular widths/heights around half-perimeter thresholds 72 and 120 in; round diameters around 24, 36, 60, and 96 in; oval. Repeat with overall caps 4 and 8 ft. Inspect any invalid or unreadable profile dimensions without changing valid model content to manufacture them. | Verify preliminary schedule boundaries and the smaller overall cap. Confirm dimensions are in feet internally and user entries use stated units. The offline spacing rule currently accepts some invalid rectangular dimensions, such as negative width with a positive summed half-perimeter; a characterization test preserves that known limitation. Future validation should reject invalid individual dimensions. |
| SPAN-02 | Half Strap and Trapeze choices, optional rectangular width threshold, insulation/loading, and the approved support schedule. | Verify selected product and threshold mapping. The retained spacing rules do not derive limits from support hardware or loads; record any required manual reductions and future schedule inputs. Do not treat current caps as certified SMACNA maxima. |
| CLASH-01 | Side tap, tee/branch, inline damper/accessory, adjacent duct/pipe, and an obstacle at a planned support station. | Stations move to legal clearance intervals or the run is withheld/reported partial. A relocation must retain actual maximum span, end/branch coverage, and correct hanger alignment. |
| CLASH-02 | Nearby native duct, pipe, accessories, mechanical equipment, and a rod-only overhead obstruction; repeat with multiple transformed direct MEP links and IFC MEP proxies. | Native and linked MEP box conflicts reject and roll back candidates with checks enabled. Separate broad-phase false positives from actual contact. Record unloaded-link warnings; absent geometry was not checked. Exact hardware-solid coordination remains a field review. |
| CLASH-03 | Higher approved steel above a lower native deck, then a lower linked deck; preferred-first mode with enabled rod checks. Repeat preferred-only, fallback-only, both paths blocked, and checks disabled. | A deck intersecting the steel rod path prevents that steel target. A clear approved fallback is used only when enabled. Preferred-only cannot silently change tiers; both blocked paths withhold the hanger. Disabling rod checks disables native and new linked/path checks together, so no clear-path claim should result. |
| CLASH-04 | Unapproved Generic/DirectShape/imported structure, a selected target's body before its endpoint, same-numbered targets in other links, or unreadable relevant obstacle geometry. | Structural paths use actual Solid/Mesh intersections rather than box-top targets. Only exact target endpoint contact is exempt. Body intersections and another link's matching ID still block. Unknown loaded geometry withholds clearance with diagnostics. Inventory is fresh per run. |
| TURN-01 | Real elbows/change of direction at one and both ends; short pieces with no legal station. Compare experimental fitting-extension option off/on. | Keep near-turn support checks. Fitting probes only survive valid host/rod checks; Preview does not prove a legal throat. Record any missing support after a probe fails. |
| DROP-01 | Connected horizontal duct to downturned elbow to air terminal; disconnected diffuser family; vertical drop and intervening accessories. | Horizontal support remains near the turn where possible. No hanger is placed on the vertical drop or diffuser by this path. Review independent diffuser/drop support and connector-heuristic warnings. |
| DRAFT-01 | Enable retained UNATTACHED mode under measurable approved sources when native attachment cannot be accepted. Then disable it and repeat; include preexisting notes and locked Comments with a writable Fabrication Notes field. | Kept drafts remain aligned to host duct, individually geometry-sized, and visibly marked with HOST/link-qualified targets while retaining unrelated notes. A writable supported notes field is required. Disabled mode retains no draft. Measured targets are required; arbitrary unmeasured rod heights are not added. |
| DRAFT-02 | Manually Attach to Structure after DRAFT-01 using recognized native host(s). | Confirm rods/anchors attach as intended and inspect lengths afterward. Subsequent Repair must not resize attached rods. Review the historical draft marker when classifying attachment status. |
| REPAIR-01 | Selected drafts and then a mixed batch containing valid, unmeasurable, attached, and read-only-comment examples. | Only accepted unattached drafts update in place; no creation/deletion or claimed automatic attachment. Failed per-hanger edits roll back. Verify rod-path clashes manually because Repair does not run Auto Hanger's clearance scan. |
| EXTRA-01 | Same-service parallel draft pairs at 6, 11, 12, and 13 in; different services, crossing axes, close supports on distinct runs, negative coordinates, and pairs spanning two 0.75-ft bucket indices. | Reports and optional selection create/delete nothing. Inspect threshold/bucket misses and false positives. Same-service parallel hosts within 1 ft do not alone establish redundant support. |
| TX-01 | API failure/refused rod length/invalid creation midway through a small batch. | Failed candidates roll back cleanly; retained IDs match reports; final gaps and remaining partial work are visible. Preserve a minimal model reproducer. |

## Result record

Copy the following into a field report for each scenario:

```text
Scenario ID:
Current source revision / file manifest (or authorized release ZIP and SHA256):
Revit 2025 build / pyRevit version / engine:
Fabrication content and service IDs:
Duct IDs / qualified structure IDs / every source/link instance and transform:
Approved model/category/type groups / direct picks / targeting mode:
Restored or invalidated preferences and warnings:
Settings, final maximum rod length, and selected hanger buttons:
Preview proposed count and reported issues:
Actual retained native / draft / failed count and hanger IDs:
Per-rod base XY/Z, target XY/Z, target member ID, actual length:
Measured spans, end/branch distances, and hardware clearance:
Expected result / observed result / pass or fail:
Screenshots, output log, and minimal detached reproducer:
```

Proceed to larger selections only after the small-area host, targeting, rod, and rollback cases are understood. The field report should distinguish geometric contact, native attachment, physical duplicate suppression, and project-approved support adequacy.


## Structure-aware station search follow-up

- Test one short crossing duct with the actual approved linked beam/joist types.
  Record probe count, adjusted/withheld stations and final attached/draft counts.
- Confirm every temporary hanger disappears and Preview creates no elements.
- Confirm both rods land on measured approved structure with individual lengths.
- Inspect end, branch and maximum-span coverage after final placement failures.
- Test a parallel-offset duct: no sideways hanger displacement or guessed rod
  connection is permitted. Review an approved fallback or separate support detail.
- Cancel during progress and confirm no probes or new hangers remain.
- Preserve original service mapping, existing hanger locations and fitting behavior.
  Native geometry/attachment, real API transactions and timing need Revit evidence.


## Reference-object clearance regression

- Keep rod clash checks enabled. Test a short duct near the previously measured
  linked-steel target and approve only the intended readable members.
- Record reference filter counts/examples and any unresolved Revit classes.
- Confirm a curve-only DWG/reference no longer globally blocks rod paths.
- Confirm an actual 3D solid or mesh still blocks, even in a file named "2D".
- Check native/linked MEP clashes, both independent rods, end/branch/span coverage
  and retained native versus explicitly marked unattached draft counts.
- Empty/missing geometry is unresolved, not a confirmed drawing. Return the
  class/ID and model inspection results for any such blocker instead of
  disabling clearance globally. Confirm all temporary probes were removed.


## Controlled validation before another layout run

Follow NEXT_TEST.md: one straight duct, the same intended native deck/steel,
Single hanger test enabled, explicit unreadable-reference review, one clicked
station. Return the SINGLE HANGER TEST stage table and every rod's results.
Every test hanger is removed, even on PASS. A >0.25-ft or unavailable along-duct
origin offset needs station/product-origin review. Do not infer a connector
reversal from a public source comment alone. Use the public comparison document
for the precise source references and verification limits.

After a reviewed PASS, test a small normal layout with desired measured
unattached drafts enabled. Inspect existing hanger occupancy before optimization,
actual retained rods, support coverage and remaining physical clashes. Do not
automatically classify uncertain coordination objects as references.
