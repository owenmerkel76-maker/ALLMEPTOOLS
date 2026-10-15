# Read-only route station preview — Revit 2025 field gate

Shift-click **Auto Hanger**, then choose **Route layout preview (read-only)**.
The original connector diagnostic is still a separate menu choice. Normal-click
Auto Hanger is unchanged. No new ribbon command, transaction, temporary hanger,
model marker, rod adjustment or settings save is introduced by this preview.

## Inputs and output

Select host-model fabrication duct and its connecting fittings. Enter two values
in feet, separated by a comma: maximum spacing cap and end target (default
`8, 1.5`; allowed ranges 2–12 ft and 0.5–2 ft). Cancel leaves the diagnostic only.
The unchanged planner's preliminary size limits also apply, using the strictest
eligible size on each route. End acceptance remains 2 ft; branch proximity is
4 ft and the branch-station keep-out is 0.5 ft. These are disclosed preliminary
planning settings, not an approved company/hardware/load/SMACNA profile.

The report shows ordered source IDs, route axis length, spacing cap, existing
hanger IDs and projected stations, new candidate host IDs, host-axis distance,
host-world XYZ and unresolved reasons. All routes have `apply_ready=False`.
Only host-model fabrication hangers are inventoried; RFA/manual support families and linked hangers are not collected. Existing records are counted for **coordination and duplicate avoidance only**;
host identity and an Origin do not verify rods, attachment or structural capacity.
An unverified draft is not certified support.

A separate legacy geometric baseline reports group/raw station counts using the
same two numeric limits. It excludes existing-hanger pruning, branch keep-outs,
structure selection and collision checks. It isolates grouping differences and
must not be presented as the full normal-click result or an equal-scope speed test.

## Geometry and support policy

- Physical reciprocal connector proof comes from the existing snapshot. The
  snapshot now retains port identities/coordinates and optional fitting normals;
  unavailable preview metadata does not erase readable diagnostic topology.
- Only horizontal straight-through routes are supported in this first increment.
  Two-end fittings can carry route distance when both end connector normals align
  with their end-to-end axis and the neighboring axes align. This includes aligned
  transitions; it does not assume eccentric transitions or elbow chord lengths
  represent the traveled path. Accepted fitting bodies never host candidates.
- Candidate hosts are straight duct sections, excluding the same recognizable
  accessory descriptions as the production tool. Actual ITM/hardware eligibility,
  end extensions, clearance, rod geometry and structural hosting are unverified.
- Service/source changes, turns, origin differences beyond 0.0001 ft, unreadable
  normals, unsupported branches/fittings and ambiguous end connections stop a
  route. Coincident unconnected pieces never join. Profile changes alone do not
  restart spacing; the smallest preliminary spacing limit wins.
- Curve/side connections do not join the mainline to a branch. Their axis
  projections create branch keep-outs when readable, including unselected branch
  neighbors. Invalid branch projections withhold new candidates. Whole tee/turn
  traversal and oblique/sloped routes remain later geometry milestones.
- Outside-selection neighbors bound partial routes and stay visible as warnings;
  users need not select an entire system to obtain a local preview. A fitting or
  device at the route endpoint is withheld instead of inventing a terminal axis.
- Existing hangers are collected once from the host hanger category. Their actual
  host ID and Origin are read; no bbox center or arbitrary station fallback is
  used. Duplicate IDs count once. An unreadable host identity/collector withholds
  all new candidates; an unreadable selected-host Origin withholds its route.
- Known existing stations enter the original count optimizer. Candidates within
  0.25 ft of them are suppressed, then end/span/branch coordination coverage is
  rechecked. Any resulting coverage gap is explicit. This is not an apply-path
  idempotence or structural-support guarantee.

## Field-test sequence

1. Retain the previous extension backup; install this preview with the existing
   manual installer, then reload pyRevit in Revit 2025. Use a detached model copy.
2. Reuse the 24-part transition selection. The supplied field report established
   24 readable parts, one selected network and 13 uniform spans, with scope cuts
   and origin differences; it did not establish continuous support distances.
   Review the new route reasons rather than expecting a particular route count.
3. Choose route preview, retain `8, 1.5` initially, and save its report. Check that
   aligned transitions contribute their measured axis length, receive no candidate
   hosts, and do not independently restart spacing. Eccentric/turning fittings
   should be withheld explicitly, not silently bridged.
4. Compare station source IDs, host offsets and world XYZ with tape/dimensions and
   a manually approved layout. Check original Preview on the same selection and
   settings separately; its structure/collision pipeline adds other constraints.
5. Test a five-piece straight run, a size transition, a tee/side tap, an incomplete
   selection, coincident disconnected pieces, a long fitting with no legal station,
   and an intentionally unreadable/unsupported case. No model edits/Undo entry
   should result from the read-only preview; rod attachment is not tested here.
6. On a known fixture with existing hangers, confirm each ID is counted once and
   candidate stations avoid existing positions. Rerun unchanged input and verify
   identical IDs/order/coordinates. Existing drafts must remain marked unverified.
7. Provide the report and any incorrect route/host offsets before apply migration.
   Approved company rule profiles, structure and hardware clearance remain gates.

## Offline evidence and remaining limits

The regression fixtures exercise aligned transition distance and no fitting-host
stations, physical-vs-geometric grouping, strict size limits, reversed axes and
stable enumeration, branches and scope cuts, origin-gap boundaries, unknown
normals, slopes, pipes, accessories, ambiguous ends, input preservation, unknown
existing records and zero additional coordination candidates on a simulated rerun.
They use API doubles; they do not reproduce the private project or demonstrate
actual Revit WPF/connector semantics, ITM placement, rod attachment, collision
clearance or end-to-end speed. Revit 2027 remains unverified.
