# AutoDim comparison and code audit — initial findings

Active focus: AutoDim. Auto Hanger is paused at `f98a2f8` / visual preview 6;
no hanger code changes are part of this audit. Research branch:
`feat/autodim-comparison-audit`, based on that preserved ribbon snapshot.

**Paired drawing comparison is pending.** The user will provide human dimensions
and AutoDim output for the same area. No new drawings or AutoDim audit JSON have
been supplied for this phase. Findings below come from current source, existing
regressions, host-double reproductions and retrieved public documentation. They
are not conclusions about the missing drawings or hands-on vendor benchmarks.

## Current source baseline

- Unified AutoDim launcher: 395 lines; Duct engine: 6,669 lines; Pipe: 6,484 lines.
  Duct audit identifies itself as `duct-6.8-text-pockets`; Pipe as
  `pipe-5.1-review`. Historical review documents describe earlier stages and must
  not be treated as proof of the current engine's model behavior.
- Existing AutoDim-specific regression suite: **150 tests passed**, 9.393 seconds,
  using `python3 -m unittest discover -s tests -p 'test_*autodim*.py' -q`.
- PDF tooling is available in `/workspace/robmep-toolchains/reports` with pinned
  PyMuPDF/NumPy, separate from IronPython. No new dependencies are needed to begin
  paired PDF registration/text/vector analysis.
- Current runtime remains Revit 2025 / IronPython 2.7. Revit 2027 is unverified.
  No production extension code or settings were edited for this initial audit.

## Documented comparison workflows

| Reference | Retrieved documented behavior | Useful comparison | Scope limit |
|---|---|---|---|
| EVOLVE Quick Dimensions [1] | Selected elements must be parallel; center-to-center, edge-to-edge and mixed center/edge methods; dimension family/type; optional modeled edges, linked selection, handle position, element limit and continuous operation. | Make reference intent and style explicit; consider an optional manually positioned, small-scope workflow for difficult areas. | This is not documented full-area automatic grid/branch drafting. Do not infer arbitrary fabrication-reference compatibility, universal clash freedom or runtime speed. |
| Naviate Accelerate Dimension Grids [2] | Adds a grid dimension string at the top and right of the view, dimensioning grids in the view. | Consistent perimeter bands and grid-string organization can inform presentation. | Grid-to-grid automation is different from locating each duct/branch relative to a grid. The retrieved feature page does not prove fabrication MEP target coverage. |
| Revit 2025 aligned dimensions [3] | Uses two or more parallel references or points; references are picked before placing the dimension line. | Preserve real source/grid references and distinguish a valid measurement from readable placement. | Native interactive workflow does not supply AutoDim's whole-area target inventory or text-layout optimization. |
| Revit 2025 baseline/ordinate dimensions [4,5] | Multiple reference points share an origin; baseline display supports direction/stacking changes. | Explore common datum/bands or chains only after each reference/segment is independently valid. | Display similarity is not proof that a particular fabrication edge supports a stable Revit dimension. |
| Revit 2025 wall auto-dimensioning [6] | Entire-wall references can include openings, intersections and grids; linked walls require individual references. | Explicit target categories and reference selection matter; avoid assuming one-click rules generalize. | Architectural wall dimensioning is not fabrication duct/pipe dimensioning. |
| EVOLVE Arrange Tags / Annotation Settings [7,8] | Separate tag arrangement and configurable tag-family/category/service rules. | Separate geometry coverage, visual organization and configuration into reviewable stages. | These pages describe tags; they do not establish a dimension collision solver or prove all targets are located. |

Sources are public functional references, not code/assets to copy. No vendor was
executed in Revit here. In particular, the user’s human drawing remains the main
local drafting benchmark, not a product marketing feature list.

## Reproduced source defects / risks to prioritize

### A. Duct connectivity can authorize unproved owners

`engines/duct_engine.py`:
`_strict_allrefs_other_owners` (line 2857), `_connector_other_owners` (3041),
`_strict_reached_straights` (3116). Function names/locations may move later.

The AllRefs reader accepts the other owner without checking reference connector
type, domain, connected flags or reciprocal `IsConnectedTo`. The owner merger
also adds spatial matches as owners. Despite its comment, the fallback does not
require physical connection proof. `_strict_reached_straights` can then accept a
matched target before further traversal checks. Matching size/axis/coordinate
cannot prove that two parts physically connect.

Host-double reproduction executed the actual extracted source functions:

| Input | Actual result | Consequence |
|---|---|---|
| Connector has no AllRefs, `IsConnected=False`, spatial matcher returns owner 2; traversal targets `{2}`. | `_strict_reached_straights` returns `{2}`. | An inferred neighbor can be treated as reached, despite being disconnected in the fixture. |
| AllRefs includes owner 2 through a logical/disconnected reference. | Strict reader returns owner 2. | The name “strict” does not itself establish physical proof. |

This proves the function-level acceptance behavior. A full missing-dimension
reproduction still needs target equivalence/grouping conditions and the paired
model/audit. Do not assert this caused a particular human/automatic difference.
A likely correction is to separate candidate discovery from proved connectivity;
only proof should authorize target suppression/reuse. Require regressions for
coincident disconnected parts, logical references, reciprocal physical edges,
branches, size/service/elevation changes and already-valid grouping. Do not
blindly import paused hanger code or replace all annotation topology at once.

### B. Pipe survival checks can silently report a lookup failure as deletion

`engines/pipe_engine.py`: `_surviving_created_dim_ids` (4739) and numeric
`DB.ElementId(...)` sites. The Duct engine already uses explicit `Int64` and logs/
stops unknown survival lookup errors. Pipe still has unqualified numeric calls
and catches survival exceptions with `pass`.

Host-double reproduction: supply a known existing dimension ID above 2^33, a
working GetElement implementation, and an ElementId factory requiring explicit
Int64 (simulating unavailable/misbound legacy overload). The actual Pipe survival
function returns an empty set after swallowing the constructor error. The error
can therefore masquerade as missing output and allow unnecessary recovery.

This is a confirmed error-handling/binding risk, not proof every Revit 2025
installation lacks the legacy constructor. Also test ordinary API lookup errors,
actual deletion, reference certification and 64-bit IDs before aligning the Pipe
path with the already-tested Duct correction. Preserve the category enum overload.

### C. Regeneration errors are caught and document work continues

The launcher catches and ignores `doc.Regenerate()` before the Pipe stage
(`script.py`, lines 345–349). The Duct direct-reference candidate loop catches
regeneration failure, tries deletion and continues (`duct_engine.py`, 3646–3654).
Other broad exception handlers and transaction layers require a coordinated audit.
The imported runtime review already flags this as unresolved. The Revit 2025
Regenerate contract explicitly forbids continuing document reads after
RegenerationFailedException and requires aborting the active scope [9].

A fatal regeneration failure must not be reclassified as an ordinary rejected
reference followed by further document reads. Fixing one local catch is
insufficient if a caller swallows the abort. Map the active transaction chain,
propagate fatal failure to the responsible rollback, and test that no later
candidate/recovery/document read runs. This is a source-level safety finding;
no actual Revit corruption was triggered here. Do not weaken collision checks or
claim a complete fix from a single exception-type check.

## Optimizations to investigate, without losing safeguards

- **Use existing evidence first.** Verify already-correct source/grid dimensions
  before proposing recovery output. Keep exact grid/mode/current coordinate and
  source ownership checks; never deduplicate by equal printed value alone.
- **Separate planning from mutation.** Validate/rank physical references, target
  intent and paper-space pockets before NewDimension/Regenerate. Keep mandatory
  final reference/value/direction and retained-text checks.
- **Profile existing caches before adding more.** Duct already caches rectangles,
  connectors, centerlines, fabrication references, expected targets, formatted
  labels and font metrics, and uses a spatial obstacle grid. Duplicate function
  names include deliberate cached wrappers; removing them mechanically is unsafe.
- **Measure rescue amplification.** Trace the number of candidates, Revit creation/
  regeneration attempts, deletions, commit losses and repeated recovery visits per
  source. A high attempt cap is not a useful speed guarantee. Existing phase
  timings provide a starting point; avoid overlapping phase totals or treating
  Python-only measurements as Revit benchmarks.
- **Find the dominant phase on the same fixture.** Compare branch inventory,
  grid discovery, background/linked/CAD collection, reference extraction, layout,
  mutation, recovery and certification. Retain visibility/extent provenance and
  report capped or unreadable collections rather than certifying a clean sheet.
- **Simplify routine UI later.** A reviewed preset should summarize source scope,
  grid policy, edge/center intent and dimension style. Advanced limits belong in
  settings. Preserve strict selected-grid semantics and saved settings during any
  migration. Use the paired benchmark to choose useful defaults.

No runtime speed improvement is claimed; no profiling data for the new area has
been provided. Do not make the tool faster by skipping source certification,
reducing the target denominator or deleting existing human annotations.

## Paired drawing review protocol

Preferred inputs: human and AutoDim PDFs of the same area/view/scale, plus the
AutoDim JSON audit from that exact run. Screenshots are usable for visual review
but do not establish source IDs, physical reference validity or exact coordinates.
The audit may contain private model/view names and coordinates; keep originals
outside Git and use anonymized fixtures in public code/tests.

1. Confirm page/view extents, scale, crop, grid names, dimension type/units, selected
   scope, grid mode, source model revision and output/audit run identity. Different
   revisions/visibility/settings must not be scored as an algorithm defect.
2. Register the images using shared grids/geometry. For PDFs, inspect text and
   vector coordinates alongside rendered overlays; handle crop/rotation/scale
   differences explicitly. Preserve an unaltered comparison copy.
3. Inventory human drafting intent: main offsets, individual branch stations,
   turned/offset branches, terminals/flex, edge vs center and datum origin.
   A meaningful target count is not simply the number of visible dimension texts.
4. Match each human locator to source IDs/reference intent from the audit where
   possible. Classify missing target, wrong datum/edge/center, wrong value,
   duplicate/unnecessary locator, legitimate shared locator, unsupported reference,
   or visually blocked/unreadable output. Equal displayed values on distinct
   branches do not prove equivalent targets.
5. Score coverage and presentation separately: target coverage, correct-source
   measurements, unresolved cases, duplicates, text/MEP/tag overlap, witness-line
   congestion, lane consistency, typography at plot scale and manual adjustment
   burden. Unknown reference truth stays unknown without model evidence.
6. Produce a marked comparison artifact and defect matrix linking each actionable
   case to the PDF location, source/audit reason, likely function, evidence level,
   proposed correction and regression/field acceptance. Rank by consequence and
   frequency before changing placement heuristics.
7. Implement one bounded issue at a time, rerun full offline checks, and field-test
   the same fixture with stable settings. Test reruns and source move/resize
   behavior; retain manual annotations. Preserve the human benchmark and first
   automatic baseline so changed counts remain explainable.

## What is ready and what remains pending

Research and initial code audit are complete enough to begin the paired review.
The three source findings above are candidates for focused regression/fixes, not
an instruction to change production behavior before checking benchmark relevance.
The actual paired drawings, their audit linkage, visual defect matrix, measured
optimization and prioritized implementation remain pending those inputs.

## Sources

1. [EVOLVE Quick Dimensions](https://help-mechanical.evolvemep.com/quick-tools/quick-dimensions)
2. [Naviate Accelerate features — Dimension Grids](https://www.naviate.com/naviate-for-revit/naviate-accelerate/features/)
3. [Revit 2025 — Add an Aligned Dimension](https://help.autodesk.com/cloudhelp/2025/ENU/Revit-DocumentPresent/files/GUID-E0FB313E-CE57-4741-9EF5-6747BBA3BDDB.htm)
4. [Revit 2025 — Add Baseline Dimensions](https://help.autodesk.com/cloudhelp/2025/ENU/Revit-DocumentPresent/files/GUID-37564A00-E6B1-4100-B222-1F674EB27895.htm)
5. [Revit 2025 — Add Ordinate Dimensions](https://help.autodesk.com/cloudhelp/2025/ENU/Revit-DocumentPresent/files/GUID-D1DAC441-1CB0-4FC1-9BC5-645B620A9F8D.htm)
6. [Revit 2025 — Automatic aligned wall dimensions](https://help.autodesk.com/cloudhelp/2025/ENU/Revit-DocumentPresent/files/GUID-C26D95E4-F272-4C67-8C1D-BC26C0493B75.htm)
7. [EVOLVE Arrange Tags](https://help-mechanical.evolvemep.com/annotations-annotation/auto-arrange-tags)
8. [EVOLVE Annotation Settings](https://help-mechanical.evolvemep.com/settings/annotation-settings)
9. [Revit 2025 API — Regenerate failure contract](https://www.revitapidocs.com/2025/22468e2c-9772-8478-0816-c9759aa43428.htm)

Retrieval limits: MagiCAD and GRAITEC pages returned HTTP 403; AGACAD's help URL
looped redirects; the attempted Naviate help endpoint was blocked. The Naviate
feature page itself was retrieved successfully. Autodesk Marketplace redirected
to a JavaScript search shell without inspectable product results; it was excluded
as product evidence. Kobi's current product page was retrieved but did not establish a relevant
automatic-dimension contract in the inspected content; its help endpoint returned
503. These retrieval limits do not establish that vendor features are absent. No access bypass, proprietary implementation or vendor speed claim is used.
