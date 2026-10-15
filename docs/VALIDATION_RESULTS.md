# Validation results — 2026-10-15 master baseline

- `bash CODEX_SETUP.sh`: PASS. Runs both validators and the full unit suite.
- Extension validator: 47 Python files, 16 XAML files, 17 buttons; PASS.
- Unified validator: 17 commands, 10 panels; PASS.
- Python 3.12.14, PowerShell 7.4.13: **348 tests, all passed, zero skips**, 52.385 seconds.
- Includes all legacy regression checks, two source-preservation checks and three
  supported manual-installer checks (fresh/repeat backup, updater refusal, rollback).
- Both archive extension trees: 149/149 identical file hashes.
- All 220 master source files retained; all 124 non-metadata extension files unchanged.
- Five `tools/build_*.py --help` commands: PASS imports and argument parsing with
  NumPy 2.3.5 / PyMuPDF 1.26.6. Actual report PDFs not generated (fixtures absent).
- Initial suite without PowerShell: 343 tests, 302 passed, 41 skipped. Installing
  checksum-verified PowerShell exposed stale legacy fixtures. Corrected them with
  disposable manifest objects/files and historical path expectations. No production
  update manifest was added and no real scheduled task was registered.
- One early overlapping PowerShell run had a native-process exit; final sequential
  run completed all cases successfully. No failing check is counted as a pass.
- Imported sources contain existing trailing whitespace (including Markdown line
  breaks). It is retained to preserve runtime/source hashes; generated inventory
  uses LF. No format-only rewrite was performed.

Not run: Windows PowerShell 5.1, Revit API, IronPython 2.7, WPF loading, actual
Windows task enumeration, live model mutations, fabrication services/ITM content,
IFC/native structural attachment, Revit 2027, GitHub-hosted CI. See
`REVIT_VALIDATION.md`. This is cloud development readiness, not field certification.
