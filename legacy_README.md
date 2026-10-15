# MEPTOOLS

Live pyRevit source is in `ROBMEPTOOLS.extension`. The source includes Duct AutoDim 6.4, the prior AutoTag/Pipe corrections, and an installer/updater for your Windows extension folder, including an empty linked folder.

[Automatic update setup and your custom folder](AUTOUPDATE.md)

[Downloads and comparison reports](downloads/README.md)

Install the updater once using `Setup Auto Updates.cmd` from the setup ZIP. Scheduled updates check every 15 minutes while signed in and wait while Revit is open. The linked folder remains the same. The missing local Duct AutoDim dimensions documented in the comparison review remain unresolved.

With Revit closed, run `Check Auto Updates.cmd` to verify installed files, GitHub access and an actual scheduled update. It saves `MEPTOOLS-update-check.txt` on your Desktop and reports success only after a fresh completed update is verified.

For development, run `python3 tools/validate_extension.py` and `python3 -m unittest discover -s tests -v`. The Python tests use the standard library. Actual PowerShell tests require `pwsh` or `PWSH_TEST_PATH`. Update the source and release manifest together with `python3 tools/package_autoupdate.py` before publishing changes to `main`.
