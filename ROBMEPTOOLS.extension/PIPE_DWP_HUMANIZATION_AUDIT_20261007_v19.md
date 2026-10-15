# ROBMEPTOOLS Pipe Humanization Audit - 2026-10-07 v1.9

## Field feedback folded into this build

The current pipe AutoDim field test still produced visually duplicated locating dimensions in dense bathroom groups. The prior final dedupe protected separate branch-event keys even when those events resolved to the same actual X/Y pipe coordinate. This release changes the final cleanup rule to geometry-first human drafting intent: one nearby locating dimension per actual coordinate, with all removed branch/run coverage identities aliased to the keeper before certification.

The current pipe AutoTag result was useful but too dense compared with the supplied human-tagged plumbing PDFs. The PDFs show repeated BOP information being communicated selectively rather than at every unchanged local elbow. This release therefore consolidates repeated turn/branch-only tags along the same local two-port path, while preserving all information-changing events and separate branches.

## Preserved behavior

- Duct AutoDim unchanged.
- Duct AutoTag unchanged.
- True-riser dual-axis locating retained.
- Short terminal Plumbing Fixture tail suppression retained for both pipe AutoDim and pipe AutoTag.
- Pipe size/elevation/profile/endcap tag events remain strict.
- Branch/takeoff discovery remains active.
- Revit 2025 remains the production compatibility target.

## Test focus

1. Dense bathroom groups: repeated dimensions with the same displayed locating value/axis should collapse materially.
2. Verify separate nearby branches are still located when their actual X/Y coordinates differ.
3. Verify true risers still receive required X and Y locating dimensions.
4. Pipe AutoTag should look less busy at repeated unchanged elbows while retaining BOP callouts at branch starts and information changes.
