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

## Subsequent Phase 1 connector foundation

`bash CODEX_SETUP.sh`: PASS, **362 tests, zero skips**, 54.916 seconds.
Extension validator now checks 49 Python files, 16 XAML files and the same 17
buttons. Fourteen new connector-graph tests pass. All 124 original non-metadata
extension files still match their imported hashes. See `PHASE1_CONNECTOR_GRAPH.md`;
the analyzer has no live Revit adapter or model-mutation integration yet.

## Clean Python 3.12 CI investigation

The original Actions run at commit `d4c3380` failed with one error among 362 tests.
A diagnostic run, https://github.com/owenmerkel76-maker/ALLMEPTOOLS/actions/runs/38792013872,
exposed the complete traceback: `test_reload_updater.py` attempted to patch
`distutils.spawn.find_executable`, which requires importing a module removed from
CPython 3.12. The cloud Python had setuptools' distutils shim installed, masking
this undeclared test dependency. This was not a missing extension path, a Revit
runtime failure, a PowerShell-version failure or a failed ribbon validator.

`robmep_updater.find_git` is legacy IronPython 2.7 host code, where distutils is
available. The test already mocked its executable lookup; the corrected fixture
explicitly supplies the mocked host modules via `types.ModuleType` and
`unittest.mock.patch.dict`. The real rediscovery/deployment code still runs and
all prior assertions remain, with an additional assertion for both Git lookups.
No setuptools dependency or production runtime modification is necessary.

Reproduced before the fix in a fresh `python3 -m venv` (no system packages or
setuptools): the single targeted test failed with the exact ModuleNotFoundError.
The same targeted test passes after correction. The workflow still uses Python
3.12 and the same `bash CODEX_SETUP.sh` entrypoint. Its logging uses pipefail and
annotates failures; an intentional exit-7 probe verified failure propagation.

Complete corrected setup in that clean Python 3.12 environment with PowerShell
7.6.6: **362 tests passed, zero skips**, 49.887 seconds. Both validators pass:
49 Python files, 16 XAML files, 17 commands across 10 panels. `bash -n
CODEX_SETUP.sh` also passes. All original runtime source-preservation checks pass.
