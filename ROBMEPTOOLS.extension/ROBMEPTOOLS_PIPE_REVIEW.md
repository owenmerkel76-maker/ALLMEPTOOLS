# Pipe AutoDim / AutoTag review — Revit 2025, IronPython 2

This candidate build revises **both Pipe AutoDim and Pipe AutoTag** from the
comparison of the user's pipe PDFs. The earlier Duct review and launcher fixes
remain included. Keep the pyRevit IronPython 2 engine selected.

## What the comparison showed

The original automatic export contains 277 BOP text spans versus 145 on the human
sheet. On the gym main, the exact BOP=30'-3 3/8\" string repeats 22 times versus 3.
These are PDF text-density observations, not live Revit tag counts. Matching crops
also show superimposed heads in G103/G104 and congested shower annotations.
Long grid strings near PS Office differ from the human's local offsets.

The new comparison PDF shows the **original supplied exports**, not an export
from this revision. It supports the changes but cannot verify the revised result.
The sheets cannot prove the source element of a BOP discrepancy or which Revit
references a dimension uses. No BOP or dimension value is rewritten from a PDF.

## Pipe AutoDim v5.1

- Requires the intended source centerline, assigned grid, direction and actual
  surviving measured value before awarding coverage. Pipe centerline semantics
  remain separate from Duct's edge rules.
- Includes no-grid targets and verified physical members in final counts; an
  alternate member can host the dimension for its proven logical run.
- Audits existing direct model dimensions and protects human dimensions from
  cleanup. Unknown helper planes and display overrides cannot prove coverage.
- Ranks clear stations before midpoint preference, protects horizontal/rotated
  text bounds, and preserves intended target coordinates through final cleanup.
- Saves source/grid IDs and actual witness spans in feet and paper inches. Long
  locators receive a diagnostic review flag; valid measurements remain required.

## Pipe AutoTag v1.5

- Applies connected-run equivalence and bounded local routing-event grouping;
  proximity, matching text or service alone cannot justify merging unrelated runs.
- Keeps different or unproved reference-level datums separate, even when two
  pipes have the same physical elevation and size.
- Protects true size/elevation changes and branch requirements while removing
  proven redundant routing events near fixture tails.
- Rejects occupied tag/dimension text and out-of-crop fallback candidates instead
  of counting a forced collision as a successful placement.
- Rolls back failed raw-tag creation/type changes and verifies the actual source,
  selected family type, view and nonorphan status after commit.
- Records required targets, blocked source IDs, actual tag text and model/level
  data so suspected BOP discrepancies can be investigated.

Direct Pipe component tags also require the requested type/source/view when
checking duplicates, isolate rejected creations in subtransactions and report
only post-commit survivors. Component records are included in the Pipe AutoTag
audit. Their on-host placement path remains separate from the event collision
solver. Duct component duplicate behavior is preserved.
An unexpected surviving component tag with mismatched identity is reported as
failed and excluded from totals; it can remain in the view for manual review.

## Install and compare in Revit

1. Close Revit and back up the installed extension. Extract the review ZIP and
   copy only its `ROBMEPTOOLS.extension` folder into
   `%APPDATA%\pyRevit\Extensions`. Restart Revit 2025 with IronPython 2.
2. Use a disposable copy of the same model and the same view, crop, scale and
   loaded families as the supplied exports. Review existing annotations before
   rerunning; this build does not delete old automatic output by provenance alone.
3. Test Pipe AutoDim and Pipe AutoTag separately on a small selection. Verify
   source elements, grids, measured values, selected family labels and Undo.
4. Review the gym, G103/G104 and Home/Away showers. Confirm fewer equivalent
   repeats, distinct overhead/drop elevations, readable heads and preserved real
   branch, size and elevation events. Inspect every missing/blocked source ID.
5. Inspect the reported long-locator grid assignments. Where intended, use the
   existing selected-grid mode to choose appropriate nearby host datums. Do not
   erase true obligations just to match the human's annotation count.
6. Rerun in the same view to check duplicate behavior, source coverage and helper
   stability. Export the resulting PDF and keep both JSON audits for comparison.

Audit files are saved via pyRevit's per-user data-file directory with unique
names `robmep_autodim_pipe_<uuid>.json` and
`robmep_autotag_pipe_<uuid>.json`. The result message provides the path.

## Verification and limits

Run `python3 tools/validate_extension.py` and
`python3 -m unittest discover -s tests -v` in the cloud checkout. The focused
tests execute the shipped functions through AST extraction with small Revit API
mocks. All 115 host tests passed, along with static checks for 17 extension Python
files, 12 XAML files and six button packages. They do not execute IronPython,
WPF or Revit transactions.

The full inherited fatal-regeneration abort chain, helper ownership/update
lifecycle, complete riser/fixture inventory and human-style local dimension
chains remain unfinished. Helper-plane geometry is independent of the source
and refreshed when rerun; geometric certification does not prove associativity.
The selected tag family and model parameters determine BOP semantics. A combined
CW/HW human callout requires a compatible family; this build does not manufacture
combined label text. Final geometry, family bindings, commit behavior and plotted
readability require testing in Revit on the model copy.

Detailed evidence and implementation notes are included in
`research/pipe_human_vs_auto_visual_audit.md`, `research/pipe_autodim_revision.md`
and `research/pipe_autotag_revision.md` outside the installed extension folder.
