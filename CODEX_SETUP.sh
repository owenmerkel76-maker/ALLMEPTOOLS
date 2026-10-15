#!/usr/bin/env bash
# Offline development checks; Revit/pyRevit run on Windows, not in this shell.
set -eu
cd "$(dirname "$0")"
if [ -z "${PWSH_TEST_PATH:-}" ] && [ -x /workspace/robmep-toolchains/powershell-7.4.13/pwsh ]; then
    export PWSH_TEST_PATH=/workspace/robmep-toolchains/powershell-7.4.13/pwsh
fi
python3 tools/validate_extension.py
python3 tools/validate_unified.py
python3 -m unittest discover -s tests -q
