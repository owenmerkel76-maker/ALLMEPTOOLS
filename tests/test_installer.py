"""Exercise real installer logic; Windows UI, task registration and Git sign-in are stubbed."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PWSH = os.environ.get('PWSH_TEST_PATH') or shutil.which('pwsh')


@unittest.skipUnless(PWSH, 'Set PWSH_TEST_PATH to test installer PowerShell logic')
class InstallerTests(unittest.TestCase):
    def run_ps(self, script, *arguments):
        environment = os.environ.copy()
        environment.update(XDG_CACHE_HOME='/tmp/robmep-ps-cache', XDG_CONFIG_HOME='/tmp/robmep-ps-config',
                           XDG_DATA_HOME='/tmp/robmep-ps-data')
        return subprocess.run([PWSH, '-NoLogo', '-NoProfile', '-File', str(script), *arguments],
                              capture_output=True, text=True, env=environment, timeout=30)

    def check_location(self, case):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_ps(ROOT / 'tests/run_install_location.ps1', '-Root', directory, '-Case', case)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def check_git_location(self, case):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_ps(ROOT / 'tests/run_git_location.ps1', '-Root', directory, '-Case', case)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_git_on_other_drive_is_found_from_install_registry(self): self.check_git_location('registry')
    def test_git_on_other_drive_is_found_from_per_user_uninstall_record(self): self.check_git_location('uninstall-record')
    def test_git_on_other_drive_is_found_without_path_or_registry(self): self.check_git_location('disk')
    def test_git_file_picker_path_and_install_folder_with_spaces(self): self.check_git_location('explicit')
    def test_git_missing_returns_control_for_file_picker(self): self.check_git_location('missing')
    def test_github_desktop_executable_resolves_to_its_bundled_git(self): self.check_git_location('desktop')

    @unittest.skipUnless(shutil.which('git'), 'Native Git required for background Desktop recovery test')
    @unittest.skipIf(os.name == 'nt', 'Local network fixture uses a POSIX executable shim')
    def test_scheduled_update_recovers_after_desktop_changes_git_version_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_ps(ROOT / 'tests/run_git_location.ps1', '-Root', directory,
                                 '-Case', 'background-desktop', '-NativeGit', shutil.which('git'))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_empty_linked_parent_installs_every_tool_file(self): self.check_location('empty')
    def test_existing_parent_and_direct_extension_keep_the_active_copy(self): self.check_location('existing')
    def test_multiple_extensions_require_specific_selection(self): self.check_location('ambiguous')
    def test_unrecognized_destination_files_are_preserved(self): self.check_location('conflict')
    def test_empty_extension_folder_is_used_without_nesting(self): self.check_location('empty-extension')

    def execute_installer(self, root, task_failure=False, task_disappears=False):
        package = root / 'package'
        shutil.copytree(ROOT / 'installer', package / 'installer')
        shutil.copytree(ROOT / 'ROBMEPTOOLS.extension', package / 'ROBMEPTOOLS.extension',
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        # The obsolete installer requires its old manifest contract. Build it
        # only in the disposable fixture; never re-enable production updates.
        payload = package / 'ROBMEPTOOLS.extension'
        import hashlib
        files = {p.relative_to(payload).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in payload.rglob('*') if p.is_file()}
        (payload / 'update-manifest.json').write_text(json.dumps({
            'schema': 1, 'build': 'isolated legacy test fixture', 'files': files,
            'bootstrap_files': ['startup.py']}))
        script = package / 'installer/Install-Updater.ps1'
        source = script.read_text().replace('Add-Type -AssemblyName System.Windows.Forms', '')
        source = source.replace('[Security.Principal.WindowsIdentity]::GetCurrent().Name', "'test-user'")
        # Substitute only platform entry points; execute production discovery,
        # checksums, file copying, settings, lock handling and rollback unchanged.
        source = source.replace('[Windows.Forms.MessageBox]::Show(', 'Show-TestMessage(')
        script.write_text(source)
        task_module = package / 'installer/Scheduled-Task.psm1'
        task_module.write_text(task_module.read_text().replace('[Security.Principal.WindowsIdentity]::GetCurrent().Name', "'test-user'"))
        wrapper = root / 'run.ps1'
        wrapper.write_text("""
param([string]$Root, [string]$Installer, [switch]$FailTask, [switch]$HideRegisteredTask)
$ErrorActionPreference = 'Stop'
$env:USERPROFILE = $Root
$env:LOCALAPPDATA = Join-Path $Root 'localappdata'
function Get-Process { [CmdletBinding()]param([string]$Name) }
function Get-Command { [CmdletBinding()]param([string]$Name, [string]$CommandType) return [PSCustomObject]@{ Source = 'Mock-Git' } }
function Mock-Git {
    if ($args[0] -eq 'clone') { [IO.Directory]::CreateDirectory((Join-Path $args[-1] '.git')) | Out-Null }
    $global:LASTEXITCODE = 0
}
function New-ScheduledTaskAction { param($Execute, $Argument) return @{ Execute = $Execute; Argument = $Argument } }
function New-ScheduledTaskTrigger { param([switch]$Once, $At, $RepetitionInterval, [switch]$AtLogOn, $User) return @{} }
function New-ScheduledTaskPrincipal { param($UserId, $LogonType, $RunLevel) return @{} }
function New-ScheduledTaskSettingsSet { param([switch]$StartWhenAvailable, $MultipleInstances, $ExecutionTimeLimit,
    [switch]$AllowStartIfOnBatteries, [switch]$DontStopIfGoingOnBatteries) return @{} }
function Register-ScheduledTask {
    [CmdletBinding()]param($TaskName, $TaskPath, $Action, $Trigger, $Principal, $Settings, $Description, [switch]$Force)
    if ($FailTask) { throw 'simulated task registration failure' }
    if ($TaskPath -ne [string][char]92) { throw 'Registration did not use the root task folder' }
    [IO.File]::WriteAllText((Join-Path $Root 'task.json'), ($Action | ConvertTo-Json))
}
function Get-ScheduledTask {
    [CmdletBinding()]param($TaskName)
    if ($HideRegisteredTask) { return }
    if (Test-Path (Join-Path $Root 'task.json')) { [PSCustomObject]@{ TaskName = $TaskName; TaskPath = [string][char]92 } }
}
function Show-TestMessage { param($Message, $Title, $Buttons, $Icon) Write-Output $Message }
& $Installer
exit $LASTEXITCODE
""")
        args = ['-Root', str(root), '-Installer', str(script)]
        if task_failure: args.append('-FailTask')
        if task_disappears: args.append('-HideRegisteredTask')
        return self.run_ps(wrapper, *args)

    def test_setup_installs_complete_extension_and_points_task_at_child(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            linked = root / 'Desktop/PY REVIT'
            linked.mkdir(parents=True)
            result = self.execute_installer(root)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            installed = linked / 'ROBMEPTOOLS.extension'
            payload = root / 'package/ROBMEPTOOLS.extension'
            manifest = json.loads((payload / 'update-manifest.json').read_text())
            for relative in [*manifest['files'], 'update-manifest.json']:
                self.assertEqual((installed / relative).read_bytes(),
                                 (payload / relative).read_bytes(), relative)
            task = json.loads((root / 'task.json').read_text())
            self.assertIn(str(installed), task['Argument'])
            self.assertTrue(list((root / 'localappdata').rglob('settings.json')))
            self.assertFalse(list((root / 'localappdata').rglob('update.lock')))

    def test_failed_task_registration_removes_new_files_and_allows_full_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            linked = root / 'Desktop/PY REVIT'
            linked.mkdir(parents=True)
            result = self.execute_installer(root, task_failure=True)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn('simulated task registration failure', result.stdout)
            self.assertEqual(list(linked.iterdir()), [])
            self.assertFalse(list((root / 'localappdata').rglob('settings.json')))
            self.assertFalse(list((root / 'localappdata').rglob('update.lock')))
            # The actual resolver must still choose a full install after rollback.
            retry = self.run_ps(ROOT / 'tests/run_install_location.ps1', '-Root', str(root), '-Case', 'empty')
            self.assertEqual(retry.returncode, 0, retry.stdout + retry.stderr)

    def test_setup_does_not_claim_success_when_registered_task_cannot_be_found(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            linked = root / 'Desktop/PY REVIT'
            linked.mkdir(parents=True)
            result = self.execute_installer(root, task_disappears=True)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn('Windows did not retain task', result.stdout)
            self.assertEqual(list(linked.iterdir()), [])


if __name__ == '__main__': unittest.main()
