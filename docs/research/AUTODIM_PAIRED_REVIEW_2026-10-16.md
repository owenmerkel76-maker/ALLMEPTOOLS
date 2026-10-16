# AutoDim paired drawing review — 2026-10-16

The supplied human/AutoDim PDFs and matching Duct 6.8 audit have now been
reviewed. Auto Hanger remains paused at `f98a2f8`. This increment adds an
offline comparison tool and anonymous regressions; it does not change ribbon
commands, settings, source references or dimension placement.

Original PDFs, model names/coordinates, source-ID registers, review configuration
and generated comparison reports stay outside the public repository. The private
report has ten pages, aligned vector crops and a register of all 15 uncovered
required target rows. Public findings below use aggregate results only.

## Evidence and registration

- Both exports have one page with equal media extents and **190 identical
  background text spans**, including positions and reading directions. Grid
  anchors register without a drawing-to-drawing shift. Independent model-to-PDF
  fits use three lettered and six numbered grid anchors; maximum residual is
  below **0.0001 PDF points**. The registered paper scale is approximately
  72 PDF points per paper inch at the audit's 1:48 view scale.
- **31,746 vector paths** are common. Human-only/AutoDim-only paths are 776/742,
  mostly changed dimension strokes. Twenty additional nonblack orange strokes
  occur in the human export. Matching architectural anchors do not certify an
  identical model revision or every visibility setting; those stroke differences
  must not be reported as an AutoDim geometry mutation.
- Human: **85** dimension-value text spans, **42 horizontal / 43 vertical**.
  AutoDim: **80**, **46 horizontal / 34 vertical**. Both directions are present.
  These counts are neither physical target counts nor a completeness score.
- All 80 AutoDim labels agree, in export order, with the audit's 80 values to the
  plotted 1/8-inch rounding tolerance and with their grid-normal directions.
  This corroborates the supplied run linkage. PDFs contain no native dimension
  IDs, so order/value agreement does not certify each exported object's identity.
- The audit reports 80 surviving certified direct-model-reference dimensions,
  no helper creations, no commit-pruned dimensions and no lookup errors. There
  is no evidence here for the historical hidden-helper disappearance failure.

## Coverage accounting: target coverage is separate from readable output

| Audit category | Required rows | Covered | Uncovered |
|---|---:|---:|---:|
| Straight-run locators | 83 | 79 | 4 |
| Separate branch-connector targets | 39 | 28 | 11 |
| Total reported required rows | 122 | 107 | 15 |

The other 32 inventory rows describe downstream-straight branch context and do
not add independent required targets. Their three uncovered rows overlap missing
straight coverage. Raw straight coverage is 121/126 (five uncovered physical
members, because one missing run has two members); that larger percentage must
not replace the 107/122 required-target result or imply human-sheet equivalence.

One covered branch key appears twice with identical serialized fields. Therefore
the reported denominator/numerator contain a repeated projected key. The audit
omits native connector IDs and original connector Z: **do not simply deduplicate
by key/point**. Distinct physical connectors can share an XY projection. Add
owner/connector identity, retain genuinely distinct obligations and only suppress
duplicate enumeration after native identity is established. The comparison tool
keeps the raw totals and reports this warning explicitly.

Recorded blockers: three missing run locators have MEP-blocked text pockets; one
diagonal run has no parallel physical-reference grid. All eleven missing required
connector targets report real references found but no readable bounded corridor.
That separates reference discovery from layout failure. Enlarging the font bounds
alone may make more corridors fail; coverage needs better lanes/pockets and
explicit intent, not smaller invented text boxes or removal of target checks.

## Confirmed presentation defect and contributing metric mismatch

The AutoDim export has **three positive-area intersections between dimension
text bounding boxes**; the human export has zero. They occur in the central
offset/cafe/green-branch region and are marked in the private report. These are
font-box intersections, not measured glyph-silhouette intersection areas.

All 80 AutoDim labels match saved SimSun metrics. Their plotted reading-axis
widths are **1.57–1.68 times** the saved widths (median **1.59**), and their PDF
box heights are approximately **1.48 times** the saved heights. The geometric
grid registration establishes paper scale independently. This is direct evidence
that these saved bounds underestimate this export; it is not proof of a universal
font multiplier or the only cause of the final layout failure.

Inspect `_measure_dimension_label`, `_dimension_text_profile`,
`_text_rect_at_point`, `adjust_dimension_text`, `reserve_created_dimension` and
the final deconflict transaction in `engines/duct_engine.py`. The next runtime
increment should establish the Revit/style glyph-height convention, width factor,
dimension text anchor/offset and retained text position; then preserve conservative
bounds and validate plotted output. Avoid a blanket 1.6 multiplier across fonts,
styles, paper scales and projects. Current audit records omit final text positions,
dimension-line endpoints, actual type ID and per-dimension formatted labels, so
those native facts need to be recorded for exact reproduction.

## Human intent that the current target model misses

1. **Primary versus intermediate datum.** The upper west branch's human locator
   uses a primary grid; AutoDim uses a tiny offset from an intermediate grid.
   These can be valid measurements of the same edge through different datums.
   Add an explicit reviewed primary-grid preference; preserve strict selected-grid
   behavior and current saved defaults. Do not call different values wrong solely
   because they differ.
2. **Branch, terminal and local-detail coordinates.** The human sheet locates
   individual turned terminals and includes short branch/drop chains and local
   installation details. AutoDim's main/straight-locator model does not represent
   every such obligation. A longer horizontal straight's measured edge cannot
   automatically satisfy a lower turned terminal's station. Inventory these intents
   explicitly before claiming full human coverage.
3. **Repeated mains versus useful branch stations.** Several main-run offsets
   repeat while separate branch/drop stations remain missing. Some same-valued
   records belong to distinct source IDs. Reuse requires actual connected-run,
   source/grid/mode/coordinate proof. The initial source audit's unproved connector
   membership risk remains relevant, but these PDFs do not establish it caused
   any particular missing or repeated measurement.
4. **Lanes and witness readability.** Human branch offsets and short chains use
   more deliberate lanes near their source. AutoDim scatters some text into room
   areas and crowded intersections. Optimize coverage and readability separately;
   a source-certified dimension can still be poorly placed on the plotted sheet.

## Public-tool comparison and prioritized development

The retrieved official sources and scope limits remain in
[the initial audit](AUTODIM_COMPARISON_2026-10-16.md). EVOLVE Quick Dimensions
documents selected parallel references, center/edge intent, type selection and
handle placement. Naviate's documented grid-string tool addresses grid-to-grid
dimensions. Revit's native baseline/ordinate tools expose a deliberate origin and
placement intent. Those are useful UI/placement benchmarks; none demonstrates
that a commercial tool automatically solves this complete fabrication sheet.
No proprietary implementation or hands-on commercial performance is claimed.

Recommended implementation order:

1. **Text geometry and truthful readability diagnostics.** Capture actual type,
   format, line/text positions and metric provenance; correct the native font/
   anchor convention with focused tests. Gate final retained layout separately
   from physical-source certification. Test this exact export and additional font,
   width-factor, unit and scale cases in Revit.
2. **Missing branch/terminal coverage.** Resolve the eleven bounded-corridor
   blockers and three run text-pocket failures with genuine references and
   coordinated lanes. Establish a separate reviewed diagonal/endpoint strategy.
   Add measured, anonymous regressions; do not manufacture parallel references.
3. **Connector identity and safe reuse.** Introduce native connector identities in
   inventory/audit, detect duplicate enumeration, reject logical/proximity-only
   membership as source proof and preserve distinct branches at coincident XY.
4. **Simpler settings.** Present scope, grid policy, edge/center intent and style
   in a small summary; show coverage, unresolved causes and readability warnings
   separately. Keep advanced limits in settings and retain saved behavior.
5. **Measured optimization.** The supplied engine interval is **6.60 seconds**,
   126 input straights, 80 new dimensions, 6,542 candidate scores and 0.31 seconds
   reported mandatory rescue. Existing phase windows overlap; do not add them or
   claim a speed gain. Instrument non-overlapping phase/API attempt counts before
   pruning equivalent candidate work. Preserve source certification and coverage.

## Repeatable offline comparison

Install `requirements-reports.txt` into a separate CPython reporting environment.
Run `tools/compare_autodim_evidence.py --help` for the five required arguments:
human PDF, AutoDim PDF, audit JSON, private JSON config and output directory.
The config supplies `anchors.x/y` (each with `model` and `pdf` values), `summary`,
`findings` (title/body) and `zones` (title/clip/notes). It is data only.

The tool checks page extents, identical background text anchors, grid-fit residual
and paper-scale consistency; it rejects shifted/unregistered inputs. It generates
an annotated PDF, evidence JSON and unresolved-target CSV outside the repository.
Nine anonymous regressions cover denominator handling, duplicate-key warnings,
axis/value linkage, text-box intersections, vertical font metrics, registration
and invalid inputs. They require no PDF dependency or Revit host.

No production fix, runtime speed improvement, native Revit acceptance or new
installable extension is claimed for this review increment. The first runtime
gate is the text-geometry/retained-readability work above; Auto Hanger stays paused.
