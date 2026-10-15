"""Exercise the supported manual installer without Revit or scheduled tasks."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PWSH = os.environ.get('PWSH_TEST_PATH') or shutil.which('pwsh')


@unittest.skipUnless(PWSH, 'PowerShell required for manual installer integration checks')
class ManualInstallTests(unittest.TestCase):
    def install(self, package, target, active_task=False, fail_copy=False):
        wrapper = package / 'test-wrapper.ps1'
        wrapper.write_text('''param($Installer, $Destination, [switch]$ActiveTask, [switch]$FailCopy)
$ErrorActionPreference = 'Stop'
function Get-Process { [CmdletBinding()]param($Name) }
function Get-ScheduledTask { [CmdletBinding()]param()
    if ($ActiveTask) { [PSCustomObject]@{TaskName='ROBMEPTOOLS Auto Update test'; State='Ready'} }
}
if ($FailCopy) { function Copy-Item { [CmdletBinding()]param($LiteralPath,$Destination,[switch]$Recurse,[switch]$Force) throw 'simulated copy failure' } }
& $Installer -ExtensionsRoot $Destination
''')
        args = [PWSH, '-NoProfile', '-File', str(wrapper), '-Installer', str(package / 'INSTALL_WINDOWS.ps1'), '-Destination', str(target)]
        if active_task: args.append('-ActiveTask')
        if fail_copy: args.append('-FailCopy')
        environment = os.environ.copy()
        environment.update(XDG_CACHE_HOME='/tmp/robmep-ps-cache', XDG_CONFIG_HOME='/tmp/robmep-ps-config', XDG_DATA_HOME='/tmp/robmep-ps-data')
        return subprocess.run(args, capture_output=True, text=True, timeout=30, env=environment)

    def fixture(self, directory):
        package = Path(directory) / 'source'
        package.mkdir()
        shutil.copy2(ROOT / 'INSTALL_WINDOWS.ps1', package)
        shutil.copytree(ROOT / 'ROBMEPTOOLS.extension', package / 'ROBMEPTOOLS.extension', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        return package, Path(directory) / 'custom extensions'

    def test_install_and_repeat_preserves_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            package, target = self.fixture(directory)
            for iteration in range(2):
                result = self.install(package, target)
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                self.assertEqual(17, len(list((target / 'ROBMEPTOOLS.extension').rglob('*.pushbutton'))))
                if iteration == 0:
                    (target / 'ROBMEPTOOLS.extension/local-settings.txt').write_text('preserve me')
            backups = list(target.glob('ROBMEPTOOLS_BACKUP_*'))
            self.assertEqual(1, len(backups))
            self.assertEqual('preserve me', (backups[0] / 'local-settings.txt').read_text())

    def test_active_legacy_task_blocks_before_destination_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            package, target = self.fixture(directory)
            result = self.install(package, target, active_task=True)
            self.assertNotEqual(0, result.returncode)
            self.assertIn('still active', result.stderr)
            self.assertFalse(target.exists())

    def test_copy_failure_restores_original(self):
        with tempfile.TemporaryDirectory() as directory:
            package, target = self.fixture(directory)
            old = target / 'ROBMEPTOOLS.extension'
            old.mkdir(parents=True)
            (old / 'settings.txt').write_text('original')
            result = self.install(package, target, fail_copy=True)
            self.assertNotEqual(0, result.returncode)
            self.assertIn('simulated copy failure', result.stderr)
            self.assertEqual('original', (old / 'settings.txt').read_text())
            self.assertEqual([], list(target.glob('ROBMEPTOOLS_BACKUP_*')))
