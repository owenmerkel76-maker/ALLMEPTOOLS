# Duct AutoDim 6.3 runtime review

The supplied 6.2 audit reported Revit 2027, All grids, 15 usable host grids, 236 straight targets, 60 targets assigned to lettered grids, 148 blocked targets, and zero surviving new dimensions / zero certified targets. Both grid directions were present; the earlier grid-discovery correction did not resolve this model's placement problem. The audit did not preserve detailed placement and recovery messages. No model/project JSON is included in this distribution.

## Corrections

The existing managed-helper reuse path returned duplicate without registering the dimension as an existing verified locator. The resolved-target duplicate branch also rolled back the helper refresh. This build verifies exact current helper/grid references, measured value, direction and lack of value override before registering the existing locator. The duplicate branch retains its helper refresh. Existing verified dimensions are kept separate from newly created dimensions, so they are not accidentally deleted as new artifacts. Coverage is still revalidated against the current source target.

The saved audit now retains attempt counts, placement statistics, recovery statistics, stability/pruning statistics, initial per-source rejection details, and helper-attempt results/exceptions including the helper phase, grid name, status and reason. Mandatory recovery exceptions are also recorded. This distinguishes false rerun accounting from annotation blockage, witness-line congestion, rejected Revit references, and commit pruning.

Collision restrictions have not been disabled. The uploaded audit does not identify the precise obstacle/reference failure for the 148 blocked targets; this build does not claim that those targets are now placed. The update addresses a demonstrated rerun accounting/refresh defect and adds the runtime evidence needed to resolve remaining model-specific misses.

## Revit check

Back up your installed extension, install only ROBMEPTOOLS.extension from this ZIP, and restart Revit/pyRevit. Run AutoDim with All grids on a disposable model copy. Keep your current dimensions; valid known helper dimensions should now be verified as existing coverage rather than silently omitted. Examine the completion counts and upload the new robmep_autodim_duct_*.json if the lettered-grid axis remains missing. That file now contains the actual blocked/recovery reason and phase per source.

The package remains IronPython 2 source with a Revit 2025 minimum. Your audit indicates execution on Revit 2027; no Windows/Revit 2027 runtime validation has been performed here. Do not interpret host tests as model-placement certification. Previous Duct AutoTag and grid-axis discovery corrections remain included.

## Host validation

153 host tests passed (141 inherited plus ten helper-reuse/placement regressions and two attempt-log regressions). Static checks passed for 17 extension Python files, 12 XAML files and six buttons. The tests verify known-helper rerun coverage, exact reference association, measured value/direction, override rejection, source-offset changes, separation from newly created dimensions, and preservation of rejection/exception messages.

    python3 tools/validate_extension.py
    python3 -m unittest discover -s tests -v
    python3 tools/package_autodim_runtime_review.py
