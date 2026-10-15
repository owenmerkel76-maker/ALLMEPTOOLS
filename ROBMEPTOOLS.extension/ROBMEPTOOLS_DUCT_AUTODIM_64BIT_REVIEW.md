# Duct AutoDim 6.4 - 64-bit ElementId review

The supplied Revit 2027 / 6.3 audit reported 235 helper creations during mandatory recovery and a further 235 during final coverage rescue, yet its final lookup found zero surviving dimensions. The screenshot showed dimensions on both axes. The previous diagnosis of only grid discovery or placement blockage was incomplete: the survival and certification lookup path also needs correction.

## Correction

Duct AutoDim reconstructed numeric IDs with DB.ElementId(int(...)) throughout survival checks, reference certification, existing-dimension validation, deletion, source lookup and recovery. These calls rely on numeric overload selection and can fail when the legacy Int32 constructor is unavailable or incorrectly selected. The exception was silently converted into missing-element evidence; repeated rescue passes could then recreate dimensions whose IDs were not read successfully.

All numeric ElementId reconstruction sites in the Duct AutoDim engine now use DB.ElementId(Int64(int(...))). The BuiltInCategory enum overload remains unchanged. No 32-bit truncation is used, including for IDs above 2^31. A survival lookup failure is recorded and stops further recovery, writing a partial diagnostic JSON instead of pretending that an element was deleted and creating another batch.

This fixes a demonstrated compatibility-sensitive lookup defect and guards against repeated creation on unknown lookup failures. The uploaded 6.3 audit omitted the swallowed exception itself, so it cannot prove the exact API exception in that run. Revit 2027 model verification remains required. Coverage still depends on actual source/grid references, measured values and dimension direction. Text and witness collision checks remain enabled; genuine blocked targets are still reported.

## Install and model check

Back up the installed extension. Close Revit, copy only ROBMEPTOOLS.extension from this ZIP into the pyRevit extensions directory, and restart Revit 2027 with IronPython 2. Use a disposable model copy and All grids. Existing verified dimensions should be counted correctly, and recovery should not repeat merely because an ID was constructed with the wrong numeric overload.

If prior runs left repeated automatic dimensions, first test on a copy made before those runs or use Revit Undo where available. This update does not bulk-delete previous output or user annotations. Compare the certified-target, existing-dimension, created and missing-target counts with what is visible. Upload the new robmep_autodim_duct_*.json if an axis or target remains missing. On a lookup failure, the command stops with the saved lookup-audit path; upload that file rather than rerunning repeatedly.

## Validation

158 host tests passed, including five new tests covering a simulated unavailable Int32 constructor, surviving/certified dimensions, IDs above the 32-bit range, deleted-element versus lookup-error distinction, saved failure diagnostics and stopping redundant recovery. Static validation passed for 17 extension Python files, 12 XAML files and six buttons. Actual Windows/Revit 2027 execution has not been performed here.

The full extension includes the previous Duct AutoTag, grid inventory, helper rerun and rejection-audit changes. This correction is scoped to the Duct AutoDim engine's numeric ID reconstruction; it does not certify other engines or unrelated Revit 2027 APIs.

    python3 tools/validate_extension.py
    python3 -m unittest discover -s tests -v
    python3 tools/package_autodim_64bit_review.py
