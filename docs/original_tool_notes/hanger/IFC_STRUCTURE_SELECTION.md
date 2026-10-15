# Universal IFC discovery and structural selection

This feature is integrated into the existing Auto Hanger button. The original
duct planner, service-specific hanger mappings and placement transactions remain
in place. The pasted broader SMACNA upgrade document is background; this change
implements the user's structural discovery/picker request.

## Discovery and explicit approval

The current default is a focused two-stage selection: choose the IFC link(s)
from a lightweight link list, then approve beam/joist and roof/deck types. Only
chosen links are scanned. Unrelated host model objects are omitted; unknown
imports remain behind **Show custom / unclassified IFC types**. Bulk approval
does not include ambiguous proxies, even when the advanced list is visible.
Category/class/sample details are in row tooltips rather than a wide explorer.
The existing duct picker and per-service hanger choices are unchanged.

Metadata is reused per Revit type; free-text instance descriptions are not
type/profile identities. A missing bounding box is not a rejection if actual
Solid/Mesh geometry is readable. Unlocated unreadable selections are identified
before placement instead of repeating the same error at every hanger. Primitive
extents may supply broad-phase bounds, never final rod elevations. The field
report and focused-menu regression results are recorded in `VALIDATION.md`.

The focused inventory visits relevant host geometry and selected direct Revit links,
including renamed cached IFC/RVT sources with no useful filename or type names.
IFC external-reference signatures and instance/type IFC parameters provide
evidence, but are not the only way to expose a source for review. Structural
Framing, Generic Models, DirectShapes, ImportInstances, roofs, slabs and other
model categories with suitable evidence/geometry can be reviewed.

The catalog normalizes IFC classes such as IfcBeam, IfcMember, IfcColumn,
IfcSlab, IfcRoof and IfcBuildingElementProxy. Native category hints, exporter
type/profile fields and recognizable W/HSS/channel/angle/joist profile tokens
help organize rows. Names and classifications are descriptive evidence, not
structural approval or capacity certification. Unnamed objects remain explicit
unclassified review groups; individual member picking remains available.

Model, category and type checkboxes control approval. Type roles distinguish
preferred framing from fallback surfaces. Individual picks retain stable
member tokens and can override a type role. Clearing a category/model also
clears its direct picks. Counts show approved sources, preferred members and
fallback objects before running the hanger tool. Columns and ambiguous proxies
are excluded from automatic framing bulk hints; they remain explicitly
reviewable when the user approves them.

Direct member selection temporarily hides the picker, invokes Revit selection,
then restores the window. Cancelling a pick keeps existing approvals. Cancelling
the picker or the existing service/settings window makes no hanger changes and
does not save a newly confirmed structural preference set.

## Project preferences

pyRevit configuration section `universal_ifc_structure` stores JSON preferences
per stable project identity. Saved cloud/central identifiers are preferred;
saved project paths distinguish other documents. Unsaved documents use session
identities and require confirmation rather than sharing a title-based profile.

Model keys include the source identity and link instance identity. Type keys
use category/class/type/family/profile descriptors rather than runtime type IDs.
Individual picks use IFC GUID or Revit UniqueId tokens. Source fingerprints
include structural metadata/member identities, geometry bounds and link
transforms; linked document version data is included when available.

Preferences are restored only for matching projects and verified source
fingerprints. Missing/unloaded sources, changed geometry/transforms or unavailable
types/picks produce review warnings. The picker opens for confirmation every
run, including a new project. Settings are saved after **Run Auto Hanger** is
confirmed, using the final maximum rod length from the existing settings window.
The original default is 20 feet; both windows enforce 1–60 feet.

## Per-rod priority and geometry

Preferred-first is the default. Preferred-only and fallback-only are explicit
alternative targeting modes. Every rod gets its own host-world XY/base and
actual intersection. Each source ray is transformed into that model's
coordinates; measured hits are transformed back to host elevation.

Actual Solid or Mesh intersections provide underside elevations, including
slopes and multi-component joists. Bounding boxes only narrow candidates and
fingerprint geometry changes. Members with no readable box are still tested
through actual geometry; boxes never supply rod lengths. Unsupported/unreadable
geometry cannot certify a miss. Locally relevant unknown geometry withholds
the candidate instead of silently claiming a safe fallback.

When clearance checks are enabled, a preferred target whose path is blocked
can yield to an approved reachable fallback. A blocked fallback or unreadable
path remains unresolved. Closed mesh shells containing the rod base are rejected
instead of treating an exit/top face as a valid underside. Open surface meshes
remain supported. Native attachment is accepted only when every rod reports
the measured source/member and target height; matching element numbers from
different links do not count as the same attachment.

Geometry-sized DRAFTs keep their original host/alignment checks, independent
length updates, post-regeneration checks, rollback and UNATTACHED markings.
Target labels now include host/link identity. They remain geometric contacts,
not native structural attachment or approved anchors.

## Clearance and supported boundaries

The existing native MEP screening remains. The per-run obstruction inventory
also screens linked MEP through transformed conservative bounding boxes, and
checks native/linked structural or imported obstacles against the actual rod
segment. The chosen structural target exempts only its endpoint; an obstructing
part of the same object below that endpoint still rejects the path. Inventories
are refreshed for each run and failures are reported before placement.

Bounding-box MEP results are potential clashes, with possible false positives.
These checks do not certify full hanger hardware clearance or structural
capacity. The existing user option to disable rod clash checks is retained.
Repair Draft Rods retains its original selection workflow and now shares the
updated geometry helpers; it still requires manual clash review.

Nested RevitLinkInstances inside another linked document are currently warned
about and excluded because their transform and native attachment chain is not
implemented. Link those structural models directly into the host. Nested
GeometryInstances within supported element Solid/Mesh geometry are evaluated.
Imports containing only curves or unavailable geometry cannot provide measured
rod targets. Unloaded models cannot be evaluated.

Offline tests include actual triangle/solid calculations with boundary doubles,
catalog/persistence logic and WPF control-event doubles. Revit 2025 must still
verify real WPF interaction, direct selection, loaded IFC geometry, rod endpoint
semantics, native attachment/embedding, fabrication products and transactions.
See `FIELD_TESTING.md` and `VALIDATION.md`; the latest integrated changes are included in the existing GitHub field-test ZIP.


For a preferred-only run, fallback inventory counts are inactive. On a miss,
report host/source-local rod-base coordinates and the XY/elevation/intersection
counts from the output. A screen-box overlap is not a measured hit. Discovery
shows per-model progress and reads IFC fields in a single parameter pass.


Auto Hanger tests actual geometry without excluding members by their boxes for
small selections (at most 12 approved members per active role across all sources).
Larger inventories retain screening. Miss diagnostics include nearest host box
and plan gap, which are not measured contacts. A true hit excluded by a supplied
box is recorded as a bounds mismatch; each rod still needs its own valid measured
hit and clear path. This update does not relocate planned hanger stations.


## Structure-aware station adjustment

During placement, temporary unattached fabrication hangers test the original
and nearby same-piece stations. Every rod must have a measured approved target,
accept its individual length and pass enabled clearance checks. Probes are always
rolled back; final native/draft placement is independently verified.

The run-wide layout preserves spacing/end/branch requirements and avoids
duplicates. A search without a complete measured layout withholds that run's
new straight hangers. Movement is limited to 4 feet (or half the allowed spacing),
with at most 24 candidate positions/job, 160 probes/run and 600 total. Progress
is cancellable. Bounds suggest positions only. Existing hanger occupancy does
not prove structural attachment; final failures still require support review.

A parallel duct offset from steel may have no reachable station along its axis.
The tool reports that result instead of shifting hanger hardware sideways or
guessing connections. Preview remains preliminary and performs no model writes
or probes. Use the new probe and adjusted/withheld metrics for field feedback.


## Drawing and reference clearance filtering

Positive Revit annotation/reference/storage/container classes are not physical
rod obstacles; model members and direct linked documents are still inventoried.
An ambiguous imported/uncategorized obstruction can be excluded only after a
complete, nonempty geometry read proves it contains curves/polylines/points only.
Readable nested instances are supported. Missing or failed geometry, any Solid
or Mesh, physical categories/classifications and approved targets keep their
existing conservative treatment. Names, "2D" labels and missing boxes never
justify exclusion by themselves.

Results now include excluded-reference counts/examples and Revit classes for
unresolved blockers. These notes are diagnostic evidence, not certification
that the project models every physical obstacle. Keep clash checks enabled
for the next field test and inspect both rods at each retained hanger.


## Controlled single-station test and reference scope

Single hanger test is part of the normal Auto Hanger settings. Select one duct,
approve intended structure and enable the test. A clicked station is projected
inboard on that duct. The test explicitly overrides Preview for temporary
creation and rollback; it keeps clearance enabled and creates no retained
hanger. It reports creation, both/all rods, raw versus validated targets,
independent sizing, final clearance and actual-versus-requested origin.

The test includes an unchecked reference-review list when needed. Normal runs
can opt in with Review unreadable drawing / coordination references. Only
ambiguous unreadable candidates are offered; any known Solid/Mesh, MEP or
approved target is ineligible. Exclusions require explicit classification as
background or duplicate reference and apply only this run. Unchecked/uncertain
objects remain blocking. Source-qualified keys and scope notes prevent cross-link
ID collisions; exclusions are not stored in project preferences.

GraphicsStyle records are definitions, not collision geometry. The test logs
these exclusions and remaining unresolved classes. See NEXT_TEST.md and
PUBLIC_TOOL_COMPARISON.md in the existing release ZIP.
