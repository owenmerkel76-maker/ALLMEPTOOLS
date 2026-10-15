# Phase 1, first increment: connector graph foundation

Started after the master baseline was committed, pushed and verified at `0ccfd42`.
The master plan's connected-run analysis is the first implementation milestone.

`ROBMEPTOOLS.extension/lib/robmep_core/connector_graph.py` accepts immutable-in-use
part snapshots and explicit physical connector edges. It groups compatible straight
parts and exposes cumulative lengths in host-world feet. Five connected three-foot
pieces form one fifteen-foot run; nearby disconnected parts never join. It stops
at fittings/equipment, branches, unknown scope, source/service/profile changes and
direction changes. Duplicate/reversed edges are deduplicated. Closed loops and
self-connections are diagnosed; invalid metadata fails explicitly. Ordering is
stable under reordered input and repeat analysis, and inputs are not mutated.

Fourteen new tests cover these behaviors, including sloped/reversed direction,
malformed metadata, invalid dimensions, loops and scope boundaries. The new module
uses Python 2.7-compatible syntax and no Autodesk/CPython-only dependency, but an
actual IronPython runtime test has not been performed.

## Intentional integration boundary

No original tool script, helper or settings file has changed. This analyzer is not
yet called by the live AutoHanger. Existing placement behavior is therefore unchanged.
This is a topology foundation, not a claim of corrected rod placement, hanger
idempotence, minimal supports or a complete Phase 1 implementation. Input snapshots
are synthetic test fixtures; no Revit connectors were read here.

Next: add a read-only Revit 2025 adapter for physical connector ownership, source
identity and transformed axes, excluding logical-system links. Validate reciprocal
connections and selection scope against a detached field fixture. Then feed the
analyzer into a preview-only hanger path, compare with the existing planner, and
add approved rule/station/deduplication tests before any apply-path migration.
Per-rod structural intersections and native attachment checks remain separate gates.

## Next increment implemented

A read-only host FabricationPart snapshot adapter and Auto Hanger Shift-click diagnostic are now implemented for field verification. See `REVIT_CONNECTOR_DIAGNOSTIC.md`. They do not change the original placement path, implement linked geometry, or complete Phase 1.
