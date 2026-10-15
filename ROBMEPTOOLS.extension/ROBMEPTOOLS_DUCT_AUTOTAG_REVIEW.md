# Duct AutoTag comparison review - updated 2026-10-15

Target: Revit 2025 / pyRevit IronPython 2 (2712). Review build; Windows/Revit execution has not been performed.

## Evidence

The latest rerun is confirmed Review 4. Its `AUTOTAG.pdf` has 80 BOD and 31 CFM spans, compared with Review 3's 79 and 39. The human PDF is byte-identical to the prior benchmark (68 BOD / 35 CFM spans). External component boxes are visibly improved; office branch omissions and other printed differences remain. See `downloads/Human-vs-AutoTag-Review-4-Rerun-Comparison.pdf` and its Evidence JSON/CSV for the latest nine-page review and 12 marked printed-callout differences. Some human callouts refer to fittings or different values; the PDF alone cannot classify each remaining straight-duct failure.

The user then specified that every straight duct must be a target and explicitly deferred elbow/angled-fitting BOD tags until a compatible family is created. Matching the human's smaller tag count is therefore not a target-selection rule.

The current benchmark is the October 15 same-area `AUTOTAG.pdf` and `HUMANTAG.pdf`; the user confirmed the automatic sheet used Review 3. The first 150 room/background text spans match in content and coordinates within 0.001 PDF point. AutoTag has 79 BOD spans (45 distinct printed signatures); the human sheet has 68 (50 distinct signatures). There are 39 versus 35 CFM spans. These are PDF text inventories, not certified Revit tag or source counts. Twelve human callouts have no remaining equal-label match after inventory matching, including two extra office-branch 6x4 OA / BOD 11 ft 2 in callouts. Several other differences involve size/BOD values and cannot be resolved from PDF text alone.

See `downloads/Human-vs-AutoTag-October-15-Comparison.pdf` for seven aligned zoom pairs, red callout markers, and the difference register. Component boxes in the automatic export overlap their own terminal symbols; the human boxes are outside those symbols with compact leaders. Repeated main callouts remain visible in the automatic sheet. Equal printed values alone do not identify redundant connected targets or authorize rewriting model data.

Compared SECOND FLOOR AREA A.pdf (human) with duct autotag run.pdf (original automatic output). Both are single pages, 792 x 612 PDF points. Matching background and duct paths permit identical-coordinate crops. There are 191 versus 251 extracted text spans containing BOD, approximately 31% more in automatic output. These are text spans, not verified Revit tag counts. Some callouts and source geometry/values differ; the sheets are not proof of identical model state, element IDs, family parameters, or authoring intent.

Automatic output crowds additional labels into corridor and branch bands; boxed component labels also add clutter. Human labels commonly use compact leaders into open space. See research/Human-vs-Duct-AutoTag-Comparison.pdf and comparison-metrics.json for matching crops and exact count regions. These PDFs show supplied output, not revised-tool output.

The October 12 Revit 2025 audit `d49e44bd5d0c43b3a280a2aad104d716` ran Review 2 and reported 106 missing targets, all with the same unavailable-bounding-box failure after transaction commit. The placement pass created 106 tags; final clearance removed all of them. Direct component tagging followed its separate successful path. This audit does not contain the failed API exceptions or actual duct tag text, so it cannot establish whether the missing boxes came from Python binding, family graphics, visibility, or another Revit condition.

## Changes

- Review 5 adds `All visible straight ducts (BOD)` to the duct target options. It is enabled by normal event profiles/defaults and can be switched off for a custom event-only run. An independent source inventory adds unchanged straights, diagonal straights, sloped straights and vertical straights to the same source-ID target set. Existing selected-type tags still suppress duplicate creation. Scope and the chosen native/fabrication tag category still apply. Native arcs and fittings are excluded; unreadable straight geometry remains an explicit required target/failure.
- Vertical straights whose plan axis degenerates to a point use an external text/leader candidate tied to their real source, with the same crop and collision checks. Every all-straight source ID, added ID, unreadable geometry ID and excluded nonstraight ID is recorded under `all_straight_target_audit`.
- The branch audit now follows bounded physical paths through two-port inline fittings and duct accessories, stopping at other straights, equipment, terminals, flex and junctions. It records the exact path IDs. Same-sign fabrication connector frames can prove a main only when the physical port positions are also collinear; ambiguous junctions and query failures remain explicit.
- Component search adds farther diagonal pockets while keeping the 1.10-inch paper leader limit and all text/MEP/crop protections. The component JSON now records actual text, source bounds, metrics, candidate count and placement status, including failed searches. This is diagnostic evidence for the next model run, not proof that every missing CFM callout is restored.
- Elbow and angled-fitting BOD targets remain excluded at the user's request. No fitting-family support or numeric substitution is introduced. Inline transition/accessory component tags remain a separate mapped feature.

- Review 4 adds a saved Duct `Branch takeoffs` target option, included in normal event profiles. A local physical port audit finds the horizontal straight attached to a proved tee/wye branch, or an API-identified tap. Unique opposed main ports are excluded; ambiguous crosses and connector-query failures are recorded. Branch reasons merge into an existing event target rather than creating a second tag on the same source. Selection-only scope and existing selected-type tag handling apply after this audit.
- Duct terminal/equipment tags now search outside the visible symbol on all four sides. Text footprints, crop, protected geometry, existing annotations, and short leader routes are checked. A real attached leader is applied, Revit is regenerated, and the retained head is checked. Failed placement rolls back its new tag. The existing inline transition/accessory paths and pipe placement do not use this handler.
- Existing unmeasurable IndependentTags reserve an estimated footprint in the obstacle grid; the new component pass also reserves the actual event records from the preceding placement pass. It therefore protects existing/current event text even when Revit returns no family box. The JSON includes physical branch-port/source evidence and component source/type/head/layout records, counts and failures. Actual attached leader shape and family label offsets still require Revit inspection.

- Emergency tag heads reject other tag/annotation text, rather than assigning a penalty that permits overlap.
- No unchecked forced last-resort placement when all searches fail; the source is reported as missing for manual placement.
- Every selected event-tag layout is checked against protected text and crop bounds.
- Temporary family measurements distinguish host axis, slope, and endpoint elevations.
- Final event-tag family bounds are measured on-host with leaders hidden after a full transaction commit and view refresh, inside a rollback-only probe group. Temporary head and leader edits are restored before clearance cleanup. Placement and cleanup share an enclosing transaction group, providing one Undo operation and rollback of the whole event batch on failure. Actual boxes remain conservative family bounds, not glyph outlines.
- Review 3 tries the Python getter, indexed property, and base Element getter in both active-view and model scopes. Every result distinguishes null geometry, invalid bounds, and binding exceptions, including for tags subsequently rejected.
- If all actual bounds queries fail, a genuine readable tag of the selected type and intended source can use an estimated text footprint. Planning and final checks use the actual `TagText`, generous character widths, multiline height, rotation, and any larger exposed type text size/width. The footprint never shrinks the solver's existing reservation. Crop and protected-geometry checks still reject overlaps; no unchecked forced placement is added. The dialog and JSON count these as estimated clearance checks, never measured family bounds. Unknown nested label justification, offsets, and actual visibility still need a plotted inspection.
- Fallback creation verifies view, source, selected type, and nonorphan identity; resolves replacement IDs from ChangeTypeId; deletes rejected tags before trying another overload.
- Existing duplicates require the selected type, local source, valid view, nonorphan state, and nonempty text.
- Final counts use source/type-verified tags that survive a committed transaction. Invisible/unresolved or wrong-source tags are not claimed as successful.
- Fatal regeneration/modification errors propagate through duct helper catches to transaction rollback instead of triggering another creation attempt. The shared component path and external host remain separate.
- Unique duct JSON diagnostics report source IDs, connector sizes, centerline elevations, reference-level data, event reasons, created tag IDs, actual text, and missing/failed targets.

No BOD or size values are rewritten from the human PDF. Event detection is retained, including both sides of real size/elevation/shape changes and endcaps. This review does not add arbitrary suppression of connected event tags. Automatic density may remain higher than human drafting; conservative run grouping needs model-level evidence and a separate refinement.

## Install

1. Close Revit. Back up your current ROBMEPTOOLS.extension.
2. Extract the current `downloads/ROBMEPTOOLS-AutoUpdate.zip` from GitHub `main`. If updates are already configured, keep Revit closed and run `Check Auto Updates.cmd` to trigger and verify a fresh update. Otherwise, run `Setup Auto Updates.cmd` and keep Revit closed for the initial scheduled check (approximately one minute), then run `Check Auto Updates.cmd`. The linked root is `C:\Users\owenm\Desktop\PY REVIT`; setup identifies the existing extension there. Require a fresh successful update before reopening Revit. Existing installations initially receive updater/bootstrap files from setup; the scheduled update then deploys current tool source from `main`. Do not assume that running setup alone replaced the duct engine.
3. Restart Revit 2025 with the IronPython 2 engine and a disposable model copy.
4. Choose the intended native or fabrication BOD tag family/type. Begin with a selected corridor/branch sample. For comparison of linear labels alone, disable direct component categories; boxed component tags follow a separate path.
5. Confirm real size/elevation/shape changes and endcaps remain tagged. Check both sides of transitions and separate branches. Inspect every missing source ID before treating annotation as complete.
6. Confirm the result says `Duct AutoTag Review 5 - all straight duct targets` and the JSON engine is `duct-autotag-review-5-all-straights`. A `review-1`, `review-2`, `review-3` or `review-4` report means a previous engine is still running. The October 12 audit actually loaded `C:\Users\r.merkel\Desktop\ROB\ROBMEPTOOLSPUBLSIHEDV.1\ROBMEPTOOLS.extension`, which differs from the earlier configured Owen desktop folder. Update the copy reported by `engine_path`; updating another linked folder will not change this run. Enable `All visible straight ducts (BOD)`, check actual family bounds, BOD semantics, leaders, visible readability, and Revit Undo. Save the resulting PDF and duct JSON audit shown in the completion message for follow-up.
7. Rerun on the same selection to check duplicate handling. Confirm the selected family/type is used for every created event tag.

Existing original AutoTag labels are preserved; the tool does not rearrange or delete user annotations. Test on a clean model copy or remove only the previous automatic run using Revit Undo before comparing a revised run. It may skip existing valid selected-type tags.

## Host validation

From the unpacked package directory:

    python3 tools/validate_extension.py
    python3 -m unittest discover -s tests -v

The recovery regressions cover all 106 readable nonoverlapping tags with absent boxes, alternate API bindings, estimated-head collisions/crop failures, source/type/unreadable-text rejection, larger planning footprints, rotation, audit distinction, and retained rollback behavior. Human-plan regressions cover proved tee/tap branches, disconnected or ambiguous ports, the disabled option, merging event reasons, external component heads/routes, crop failures, retained Revit head constraints, callback rollback, and real leader retention. Host tests use simulated APIs and do not certify actual IronPython, Revit API overloads, WPF, family bindings, or placement. Shared direct component placement and family-specific plotted appearance remain model acceptance work.
