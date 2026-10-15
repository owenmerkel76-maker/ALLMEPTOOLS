# WASC Human Drafting Reference Audit — 2026-10-06

Reference: `WASC_26_P202_SECOND_FLOOR_DWP_FLOOR_PLAN 1.pdf`

## What is materially different from the ROBMEPTOOLS field runs

The strongest pattern is not simply "fewer annotations."  It is consolidation and
hierarchy.

1. **Repeated equal pipe information is consolidated.**
   Similar nearby pipe conditions can share one visible tag head with multiple leaders
   rather than carrying a separate identical BOP/size head on every local straight.
2. **Tag heads form local drafting bands.**
   Text is pulled into readable pockets beside the pipe group; leaders fan back to
   nearby hosts instead of letting text sit on top of the piping.
3. **Dimensions read as local banks rather than independent objects.**
   Parallel locating dimensions occupy repeatable offsets and nearby dimension strings
   visually belong together.
4. **Tags and dimensions occupy different visual layers.**
   Tags identify size/elevation/service.  Dimensions locate the run.  The two systems
   are not allowed to fight for the same exact pocket.
5. **Reference policy is intentional.**
   The sheet's general notes state that dimensions are taken from grid line or finish
   wall.  That means human drafting intent includes the choice of reference, not merely
   the placement of the final dimension string.

## Comparison to earlier ROBMEPTOOLS PDFs

A text-pattern audit found:
- previous ROBMEPTOOLS auto example: ~277 `BOP=` occurrences;
- previous human comparison example: ~145 `BOP=` occurrences;
- this WASC human reference: ~40 `BOP=` occurrences.

Those counts are **not apples-to-apples** because the sheets cover different geometry
and scales.  They are still directionally useful: the WASC reference achieves coverage
with much less repeated visible tag text and more deliberate grouping.

## Architecture decision

### AutoTag stays a coverage engine

AutoTag should decide **what must be identified**.  It should not be responsible for
global multi-host grouping because that requires knowledge of all neighboring tags,
dimensions, DWG geometry, and available annotation lanes after the complete run.

### AutoDim stays a certified locating engine

AutoDim should continue to guarantee the needed run/branch/riser coordinates.  The
current branch coverage has taken substantial field iteration to stabilize.  This pass
therefore does not rewrite target detection or grid-reference selection.

### Organizer becomes the drafting-intelligence layer

The Organizer sees the complete annotation field and can safely:
- consolidate identical nearby tag heads,
- use native Revit multi-leader behavior when the loaded tag type supports it,
- fall back without data loss when it does not,
- bank parallel dimensions,
- align local tag rows/columns,
- continue obstacle/DWG avoidance.

That separation lets detection improve independently from drafting style.

## Multi-leader safety rules

Only single-host tags are considered.  A candidate group must have:
- identical tag type,
- identical displayed `TagText`,
- identical host category,
- identical Fabrication service key where available,
- local host proximity,
- local existing head proximity,
- no pinned tags,
- no pre-existing multi-leader tags.

Groups are capped to 3-4 hosts depending on cleanup strength.

The merge is transactional:
1. capture the donor host reference;
2. remove the donor tag inside a subtransaction;
3. call native `IndependentTag.AddReferences` on the keeper;
4. verify that the tag now owns multiple references;
5. commit only on success.

If the family/type does not support multiple references, the subtransaction is rolled
back and the separate tags remain exactly as they were.

## Dimension banking

This pass adds a **soft** preference, not a hard snap.  Parallel dimension candidates
receive a small score benefit when they land near repeatable .18-inch paper-space lane
increments from another nearby parallel dimension.  Hard collisions, annotation text,
MEP, and DWG obstacles remain more important than lane alignment.

## Deferred intentionally

The WASC note explicitly allows dimensioning from a finish wall as well as a grid.
ROBMEPTOOLS currently focuses on certified grid references.  Adding finish-wall
references—especially through linked/imported architectural backgrounds—deserves its
own reference-quality test and should not be mixed into this multi-leader/layout pass.
