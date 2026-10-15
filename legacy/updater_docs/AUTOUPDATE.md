# MEPTOOLS: install automatic updates once

Your linked folder is `C:\Users\owenm\Desktop\PY REVIT`. If it is empty, setup installs the complete tool into `C:\Users\owenm\Desktop\PY REVIT\ROBMEPTOOLS.extension`. If an extension containing `ROBMEPTOOLS.tab` already exists inside the linked folder, setup uses that copy. If it finds more than one copy, select the actual extension folder linked in pyRevit. It does not assume `%APPDATA%\pyRevit\Extensions` or change your folder link.

1. Download and extract **ROBMEPTOOLS-AutoUpdate.zip** completely.
2. Close Revit.
3. Double-click **Setup Auto Updates.cmd** in the extracted folder. Setup installs the tool into an empty `Desktop\PY REVIT`, or finds the existing extension there. After success, reopen Revit. If this root is not already linked in pyRevit, add `C:\Users\owenm\Desktop\PY REVIT` under its custom extension directories once.
4. Setup looks for Git on PATH, in its Windows installation records, in standard folders on local disks (including D:), and inside GitHub Desktop under `%LOCALAPPDATA%\GitHubDesktop\app-*\resources\app\git`. Your `C:\Users\owenm\AppData\Local\GitHubDesktop\GitHubDesktop.exe` is the Desktop app; setup uses its bundled `git.exe`. If automatic detection fails, select **git.exe** in the file picker (for standalone Git, usually `D:\Git\cmd\git.exe` or `D:\Program Files\Git\cmd\git.exe`). Setup remembers the executable path for automatic updates; you do not need to move or reinstall Git. If Git is not installed, install [Git for Windows](https://git-scm.com/download/win), keeping Git Credential Manager enabled, then rerun setup. Sign into the GitHub account with access to `owenmerkel76-maker/MEPTOOL` if prompted. GitHub Desktop sign-in alone may not authenticate command-line Git; if it cannot access this repository, setup stops before tool installation.

After setup, a per-user Windows scheduled task checks for published tool changes **every 15 minutes while you are signed in**, and at sign-in. It **waits while any Revit instance is open**. Keep Revit closed for the first scheduled check (starts approximately one minute after setup), then reopen it. Subsequent changes appear when you open Revit after an update; you do not download, delete or replace the extension again.

To check that it works on your computer, keep Revit closed and double-click **Check Auto Updates.cmd** in the extracted setup folder. It verifies installed file checksums, finds the real Git executable, checks GitHub access without sign-in prompts, checks the Windows task configuration, then starts that actual task. It waits up to 90 seconds for a new completed result and verifies the installed files again. **ALL CHECKS PASSED** means that this scheduled update worked on this computer. Red failures or yellow waiting messages mean it has not yet been verified. The report is saved as **MEPTOOLS-update-check.txt** on your Desktop; it does not include Git credential-helper output. Send that report when troubleshooting. Open Revit afterwards to check the ROBMEPTOOLS ribbon; this does not verify dimension placement in a model.

Scheduled checks now save `last-check.json` alongside `updates.log`, distinguishing successful deployment, deferred checks while Revit is open, disabled updates and failures. Failed updates return a failing process exit code, so Task Scheduler no longer reports a failed Git fetch as a successful run.

The checker finds the task by its registered name and actual folder, with an enumeration fallback if the exact Windows query fails. If the task is missing, **Check Auto Updates.cmd** recreates it for your account after the installed files and GitHub access pass, then runs the actual task. Revit must be closed for repair. Setup now also reads back the task after registering it, so it does not claim success if Windows cannot find the registration. Existing tasks that point at a different tool folder are left unchanged and reported as failures.

If PowerShell cannot read Task Scheduler at all, setup and the checker use Windows' native `Schedule.Service` COM interface to read, register and start the same task. The report identifies which interface was used. Both methods keep the same 15-minute timer, sign-in trigger, current-user interactive login, limited privileges, battery settings and open-Revit guard. The fallback does not change Windows services or require an administrator password. If both interfaces fail, the report includes both errors and does not claim automatic updates work. COM behavior is tested with interface fixtures here; actual Windows COM execution still needs the result from your computer.

The task name is `ROBMEPTOOLS Auto Update <installation-id>`. It runs as your account with limited privileges, without storing an account password in the task. It does not modify a Revit model or rerun AutoDim. If Revit starts during deployment, the pre-write guard stops and rolls back the update. Source-only updates are supported; compiled DLL updates are rejected and need a separate installation with Revit closed.

The setup installs every published tool file when the destination is empty; existing extensions receive updater files first. Later updates affect only files owned by the published manifest. Unknown files and pyRevit user settings are preserved. Unrecognized local edits stop deployment before modifications are made. Known hashes from earlier releases permit the initial migration. An obsolete file is removed only if the previous installed state owns it and its checksum still matches.

Changed files are backed up under `%LOCALAPPDATA%\ROBMEPTOOLS\updates\<installation-id>\backups`, with `restore.json` and copies of replaced files. The initial setup has a separate `installer-backups` directory. Failed deployments restore their changes; if Windows blocks restoration, the error names the files and backup. Network/sign-in failures keep the current tool. See `updates.log` in the same directory for scheduled update results. A stale lock from a terminated background process is recovered only after checking that its owning process is gone.

The updater uses an HTTPS Git sparse checkout of the live `ROBMEPTOOLS.extension` source, with Git Credential Manager handling sign-in. Background checks suppress credential prompts; rerun setup if authentication must be renewed. Each source file is checked against SHA-256, the cache repository and cleanliness are verified, and an exclusive lock prevents concurrent deployments. Custom folder locations are supported; the folder must be writable by your Windows account.

For a manual update while using Revit, the new **ROBMEPTOOLS → Updates → Update Tool** button fetches and applies source changes, then reloads pyRevit. Hold Shift while clicking it to see the exact active folder and select scheduled, Reload-time, or manual updates. The default is the scheduled mode described above. Enabling updates on Reload is optional and applies source files while Revit is open; the scheduled task is disabled in that mode.

This adds automatic distribution of future tool changes to Duct AutoDim 6.4. **The remaining missing branch/terminal dimensions are not fixed by this updater.**

## Publishing future tool changes

Edit the live source in `ROBMEPTOOLS.extension`, then run:

```sh
python3 tools/package_autoupdate.py
python3 tools/validate_extension.py
python3 -m unittest discover -s tests -v
```

Commit and publish the changed source and `update-manifest.json` together to `main`. The background task reads the Git checkout, not report ZIPs. A change without a matching manifest is rejected and leaves the installed tool unchanged. Rebuilding unchanged source preserves manifest and archive bytes. The setup ZIP is required only for first installation or repairing the updater.

Tests cover empty-folder installation of every tool file, existing installation discovery, ambiguous or conflicting destinations, deployment, backups, rollback, local edits, settings, path validation, locking, credential-safe process handling, Git synchronization and the open-Revit background guard. Actual PowerShell deployment tests run when `pwsh` is available, or `PWSH_TEST_PATH` points to it. Installer integration tests stub Windows UI, task registration and Git sign-in while exercising actual installation and rollback code. They can run on Linux; Windows Task Scheduler registration, Git Credential Manager sign-in, Windows permissions and Revit ribbon/reload integration still require checking when setup runs on your computer.
