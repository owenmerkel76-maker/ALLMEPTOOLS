# ROB MEP Auto Hanger v0.3.7 — IFC Picker Upgrade

## Focused selection and field-result correction

Choose the IFC structural link(s) before loading type information. Only those
links are inventoried; the default host contribution is native roof/deck and
reviewable imported IFC. The support window normally shows only **Beams /
joists** and **Roof / deck fallback**. Categories, classifications and sample
names are available in tooltips. Custom/unclassified IFC types remain behind
an explicit manual-review checkbox; bulk model/section selection cannot approve
them. Duct selection and hanger mappings remain in the existing service workflow.

Type metadata is reused per type. Instance descriptions no longer produce a
separate type row for every beam. Offline regression with 250 same-type members
checks one type lookup and one grouped row. This is operation-count evidence,
not a measured Revit speedup.

Your field report showed 123 planned stations, 122 rejected draft attempts and
zero retained hangers. The same first five unreadable host objects repeatedly
blocked measurement. Broad host/custom approvals are now excluded by default;
unlocatable/unreadable approved objects are reported once before placement.
Readable primitive extents can index unboxed members for broad-phase screening,
but rod elevations still require actual intersections. Unrelated native Generic
Model helpers and view-only annotations are not global rod-obstruction vetoes;
approved objects and identified IFC structure still receive fail-closed checks.

261 offline tests pass. Retest a small detached area with the actual IFC link
and optional native deck, then inspect both rod targets and lengths before a
large run. The field model is unavailable here; successful placement and actual
menu timings still need your Revit test.

This complete package replaces the previous preserved-baseline download.
Install the entire `ROBMEPHANGERS.extension` directory in the configured pyRevit
extension search path and reload pyRevit. Replace the previous installation
rather than loading two active copies. All three buttons are included.

Auto Hanger now provides a Structural Target Selection window with multiple
model, category and type checkboxes, preferred/fallback roles, element counts,
IFC classifications, structural profile hints and direct member selection.
Generic Models and proxies require review and explicit approval. Confirmed
preferences are remembered per project and checked against current sources.

Individual rods use actual transformed Solid/Mesh intersections. Approved
fallback can be used when the preferred rod path is obstructed. Unreadable
geometry and rods starting inside closed steel meshes are rejected. Existing
duct spacing/planning, service mappings, preview, unattached draft placement
and rollback safeguards are retained. Shared geometry helpers in Repair Draft
Rods are synchronized; Review Extra Hangers remains unchanged.

261 offline tests passed before packaging. Revit 2025 WPF interaction, real IFC
geometry, fabrication rod APIs, native attachment and actual model transactions
remain field-test requirements. Structural models nested inside another linked
model must currently be linked directly into the host. MEP envelopes remain
conservative screening, not exact hanger-hardware clearance certification.

Read `IFC_STRUCTURE_SELECTION.md` and `FIELD_TESTING.md` before using a detached
test model. `README_FIRST.md` is the preserved original v0.3.7 documentation;
its older structural-selection instructions are superseded by these notes and
the picker guide. The historical download filename is retained so existing
GitHub links retrieve this updated package.


### Field targeting diagnostics and discovery progress

The next field run followed preferred-only targeting: 579 preferred members,
48 planned stations, 47 rejected attempts and no retained hangers. Every attempt
reported no measurable target at rod 0. The 146 fallback members were inventory
counts, not evidence of active fallback targeting. These results do not identify
a transform, geometry, maximum-length or physical alignment defect by themselves.

Target misses now report host and source-local rod base coordinates in feet,
active priority, rod limit, selected count, transformed XY overlap, below-base
and beyond-limit screening, actual intersection tests, misses, unreadable
geometry and hits. Bounds remain screening only; lengths require actual hits.
This diagnostic update does not invent targets or retain unmeasured drafts.
The per-source counters describe each lookup, not unique objects across a run.

Discovery now reads classifier/profile parameters in one pass instead of
repeated named searches, retaining exporter-specific fields. The menu transition
has a per-model progress indicator. Real Revit discovery timing is unmeasured.

265 offline tests passed; original archive verification passed. Field testing
is still required for actual Revit geometry, rod endpoint conventions, link
transforms and UI performance. Test a small detached-model area first and return
the new diagnostics, a section view through one failed station and the chosen
maximum rod length. This package does not claim successful field placement.


### Small-selection geometry verification after zero-overlap field results

A second field run approved six IFC members and no fallback, with 15 attempted
stations across 14 duct pieces. Every rod-0 lookup reported zero screen-box XY
overlap and zero actual geometry tests. No hangers were retained. The supplied
plan shows duct routes crossing linked steel, but does not identify rod locations
or establish vertical separation. No transform or station-placement defect has
yet been established.

Auto Hanger now performs actual intersections for all approved members of an
active role when that role has at most 12 members across its selected sources,
even when element boxes exclude the rod. This bounded check includes transformed
link geometry. Larger inventories retain the existing screening behavior.
Actual hits remain required for each rod, and path validation, finite length
limits, unknown-geometry rejection and rollback remain in force. Repair retains
its existing screen policy; the synchronized helper defaults to that policy.

Miss diagnostics report whether the small-selection check was active, box
exclusions actually tested, and the nearest supplied host box with plan gap.
Those boxes/gaps are diagnostic screening information, not steel contact or
rod lengths. Actual hits rejected by the screen also produce a bounds-mismatch
note. These changes do not shift duct stations or broaden structural approval.

271 offline tests passed; the original supplied archive was verified. Tests
cover wrong-box actual hits, six-member actual misses, large-inventory screening,
link transforms, blocked paths and unreadable-geometry fallback rejection.
Real Revit placement is still unverified.

Next field check: clear approvals, directly select the same six readable linked
steel members, select only one duct below them, use preferred-only, and inspect
each rod's results. If actual tests hit, review retained rods and mismatch notes.
If actual tests miss, compare rod coordinates and nearest box bounds to plan
and section alignment before changing the spacing planner. Do not increase rod
length to solve a plan-coordinate miss.


### Structure-aware station adjustment

The latest field report tested five readable IFC members at eight planned
stations across six duct segments. Each rod-0 lookup performed five actual
geometry tests and found five misses. The nearest supplied boxes showed plan
gaps from about 4.2 inches to over 2 feet. No native or draft hangers were kept.
The plan identifies the white lines as linked steel. This evidence establishes
that exact checks ran; it does not independently verify host-model coordinates
or actual fabrication rod endpoint semantics.

Auto Hanger now checks candidate stations using the selected service's actual
fabrication hanger. Each temporary hanger is created unattached, hosted to the
correct duct, and measured for every rod. Independent actual structural targets
and rod lengths must be accepted after regeneration, and enabled rod/MEP clash
checks must pass. Every probe is rolled back; rollback failure stops the enclosing
transaction. The final placement still uses the original native attachment,
retry, explicitly marked draft option and per-candidate rollback workflow, and
rechecks the actual final rods. Existing hangers are never moved or deleted.

Candidates move only along the same duct piece, at most the smaller of 4 feet
and half the run's allowed spacing. Transformed approved-member boxes seed
common possible positions for all rods; they never grant approval or lengths.
The search also uses bounded nearby samples for box inaccuracies. It excludes
connector regions, blocked side-tap intervals, branch exclusion zones and
occupied stations. It retains the original service-specific hanger selection.

A run-wide selection minimizes movement while enforcing maximum spans, existing
end-support limits, branch proximity, ordering and duplicate separation. Every
new station in the selected layout must pass its probe. If no complete measured
layout is found, new straight-hanger tasks for that run are withheld and logged.
This can withhold a formerly partial proposed layout instead of adding misleading
partial support. Existing station occupancy retains the original duplicate
policy; it is not evidence of approved structural attachment. Final placement
failures can still leave incomplete support and require the existing field review.

Limits are 24 candidate positions per original job, 160 probes per run and
600 per execution. A cancellable progress display updates at each probe. A
budget-limited miss does not prove there is no possible support arrangement.
Parallel-offset steel can remain unreachable by an along-duct shift; approve
a suitable fallback or use an approved support detail instead of fabricating
rod contact. Different hanger hardware is never selected automatically.

Preview remains read-only and preliminary: no probe hangers are created in
Preview. Structure-aware adjustment runs in placement mode before any final
straight placement. Reported counts distinguish rolled-back probes, adjusted
stations, withheld tasks and actual retained hangers. A new helper
`structure_stations.py` is packaged inside the existing Auto Hanger button.

301 offline tests passed, including real simulated Solid intersections for
independent two-rod targets at narrow steel crossings, partial-rod rejection,
clearance/endpoint/branch/span rules, reversed duct direction, whole-run search,
probe cleanup and cancellation. Original archive verification passed. This
does not establish successful Revit fabrication creation, actual WPF/progress
behavior, exporter coordinates, rod semantics or field timing.

Next field check: use a detached Revit 2025 model, select a short duct area
crossing approved linked steel and a small readable beam/joist selection, use
preferred-only and the measured unattached-draft option if native IFC attachment
is unavailable. Inspect every retained rod, nearby fittings and run-end/branch
support distances. Return the new probe/adjustment/withholding metrics and logs.
For a parallel run, a withheld result is expected if neither rod arrangement can
reach the selected steel. Native roof/deck fallback remains available when
approved and readable; no unclassified objects are automatically approved.


### Physical clearance versus drawing/reference objects

The latest supplied field report ran 161 rolled-back probes for 15 planned
stations across 14 duct segments. No hangers were retained. Rod 0 on one duct
returned a measured approved steel hit, then the clearance checker rejected
a DWG and several uncategorized objects with unreadable geometry or no bounds.
This proves a hit was measured in that case, not that both rods or a complete
run layout were valid. A filename containing "2D" does not establish geometry.

Clearance inventory now excludes positively identified Revit references:
view-specific objects, annotation/analytical categories, datum/curve/sketch/view
objects, project/material/parameter storage, and group/assembly/link containers
whose physical members or loaded documents are inventoried separately. Type
resolution is cached; physical elements retain the existing checks.

For otherwise ambiguous imports or uncategorized geometry, an unreadable path
can trigger a once-per-object, per-run reference audit. Only a fully readable,
nonempty curve/polyline/point-only representation (including readable nested
instances) qualifies. Fine detail is requested when available. A Solid, even
a zero-volume sheet, Mesh, unknown object, failed read or empty/missing geometry
does not qualify. Known physical categories, classified IFC structure/MEP and
source-qualified approved targets do not use this curve-only bypass. A DWG with
a real 3D intersection remains an obstruction regardless of its filename.
Uncategorized or unlocated objects are not excluded merely for lacking bounds.

Output includes counts/reasons for excluded references and up to eight audited
examples. Unresolved blockers include their Revit runtime class. Station search
also preserves informative nearby-candidate obstruction or later-rod failures
next to original misses. The no-hangers popup points to those search/clearance
sections and reports rolled-back probes/withheld stations. A missing Generic
Model category identifier cannot accidentally classify all uncategorized objects
as Generic Models. Reference decisions are not reused across executions.

321 offline tests passed; original archive verification passed. Added tests
exercise readable nested curves, actual two-rod steel targets, 3D obstructions
in misleadingly named drawings, remaining MEP clashes, known/approved unreadable
structure, empty/failed/unknown geometry, source qualification, run-scoped
reference audits and nearby-candidate diagnostics. Duct spacing/planning,
service mapping, all-rod checks, station search limits, native verification,
measured draft marking and transaction rollback safeguards are retained.

The actual field DWG and uncategorized objects cannot be inspected offline, so
their exclusions are not yet verified. Run a small detached-model test around
the previously measured steel hit. Keep rod clash checks enabled and return
Clearance reference filter/example notes, DRAFT TARGET SEARCH/CANDIDATE rows,
remaining blocker classes and retained hanger metrics. Inspect both rods and
physical clearances. Readable drawing curves do not certify that all real-world
obstacles are modeled. Revit attachment, UI, exporter data and timing remain
field-validation requirements.


### Public implementation review and single-station diagnostic

The latest field report still retained no hangers, despite measured native
roof/deck targets. It ran 28 temporary probes for four proposed stations.
Blockers included a drawing ImportInstance, a no-location coordination
DirectShape, an uncategorized Element and linked GraphicsStyle definitions.

We reviewed pinned public Murray-Tools and Hanger Layout source plus mirrored
Autodesk SDK 2025 FabricationPartLayout samples. The hosted CreateHanger and
detach/resize patterns match ours. Public creation counts can include unattached
hangers; our retained counts require expanded checks. This source comparison
does not establish that public binaries were executed or that Revit behavior
has been verified. The source links, versions, licensing and concrete comparison
are in PUBLIC_TOOL_COMPARISON.md. No third-party runtime code was copied.

Changes directly addressing the evidence:

- GraphicsStyle and pattern-definition records are filtered as nonphysical
  definitions before metadata-based obstacle classification.
- Optional reference review offers only ambiguous unreadable CAD/coordination
  candidates. Nothing is checked automatically. Known physical solids/meshes,
  MEP, physical classifications and approved targets cannot be excluded through
  this review. Opening the unreadable list does not classify those objects.
  Deliberate source-qualified exclusions apply only to the current execution,
  are reported by source/class/ID and never persist to another project/run.
- Single hanger test is integrated in the existing settings: exactly one
  straight duct, then a clicked inboard station. It reports API creation/host,
  requested and actual origin, every rod's raw and validated targets, verified
  individual lengths, clearance and rollback. Rod 0 failures no longer hide
  evidence for later rods. Raw target inspection cannot authorize sizing.
- This mode explicitly overrides Preview to run a temporary, always-rolled-back
  test with clearance enabled. It bypasses full-run optimization and placement.
  Its PASS/BLOCKED/STATION REVIEW popup makes zero retention expected. A large
  or unavailable origin offset requires review; no speculative connector
  reversal was applied based only on public comments.
- Existing hanger occupancy is now counted before normal optimization to
  investigate the unexplained drop from 15 to 4 proposals. Existing hangers are
  never deleted or moved; no redundancy rule changed on an unproven diagnosis.
- Reference notes are summarized instead of listing every metadata class.

347 offline tests passed and original archive verification passed. The original
ZIP/manifest were not edited. Eleven original assets remain byte-identical;
the additive diagnostic settings block is checked against the original XML
with every original control and attribute preserved. Regression tests cover
the latest field blocker pattern, real simulated two-rod deck hits, forbidden
physical/approved exclusions, run/source isolation, per-rod stage reporting,
position offsets, forced clearance, cancellation and successful/failed rollback.

These results do not establish Revit API/runtime, actual geometry export,
WPF, native attachment or field timing success. NEXT_TEST.md describes the
controlled next test. A diagnostic PASS is not retained native attachment or
proof of complete run support. A normal field run remains necessary afterward.


### Single-station extractor return-contract fix

The diagnostic previously treated extract_segment(part) as a segment dictionary,
but the unchanged deployed extractor returns (segment, issue). This caused
TypeError before any test hanger was created. The caller now unpacks the pair
and reports invalid extraction before station picking or opening a transaction.
The original extractor, service mapping and placement routines are unchanged.

The wrapper tests previously mocked the wrong return format. They now execute
the actual deployed extractor, profile reader and element-ID adapter with
connector-shaped doubles. They cover a valid two-rod diagnostic, cancellation,
origin mismatch, missing connectors, sloped duct and invalid fabrication service.
350 offline tests passed; the original archive and release package were verified.
Actual Revit field behavior remains unverified. Install this corrected package
and repeat the same one-duct SINGLE HANGER TEST; its successful test hanger is
still always rolled back.
