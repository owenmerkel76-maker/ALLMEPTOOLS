import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PWSH = os.environ.get('PWSH_TEST_PATH') or shutil.which('pwsh')


@unittest.skipUnless(PWSH, 'Set PWSH_TEST_PATH to run actual PowerShell deployment checks')
class PowerShellDeploymentTests(unittest.TestCase):
    def run_case(self, case, directory):
        environment = os.environ.copy()
        environment.update(XDG_CACHE_HOME='/tmp/robmep-ps-cache', XDG_CONFIG_HOME='/tmp/robmep-ps-config',
                           XDG_DATA_HOME='/tmp/robmep-ps-data')
        result = subprocess.run([PWSH, '-NoLogo', '-NoProfile', '-File',
                                 str(ROOT / 'tests/run_updater_powershell.ps1'), '-Root', directory, '-Case', case],
                                capture_output=True, text=True, env=environment, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('PASS: PowerShell ' + case, result.stdout)

    def test_actual_powershell_deployment_noop_settings_and_backup(self):
        with tempfile.TemporaryDirectory() as directory: self.run_case('update', directory)

    def test_actual_powershell_preserves_local_edits_before_mutation(self):
        with tempfile.TemporaryDirectory() as directory: self.run_case('local-edit', directory)

    def test_actual_powershell_first_migration_and_corrupt_payload(self):
        with tempfile.TemporaryDirectory() as directory: self.run_case('migration', directory)

    def test_actual_powershell_removes_only_owned_obsolete_files(self):
        with tempfile.TemporaryDirectory() as directory: self.run_case('obsolete', directory)

    def test_actual_powershell_rolls_back_after_mid_update_interruption(self):
        with tempfile.TemporaryDirectory() as directory: self.run_case('rollback', directory)

    def test_actual_powershell_rejects_unsafe_paths(self):
        with tempfile.TemporaryDirectory() as directory: self.run_case('paths', directory)

    def test_background_job_defers_before_git_or_mutation_while_revit_is_open(self):
        with tempfile.TemporaryDirectory() as directory: self.run_case('revit-open', directory)

    def test_powershell_state_is_compatible_with_manual_revit_updater(self):
        with tempfile.TemporaryDirectory() as directory:
            self.run_case('initialize', directory)
            root = Path(directory)
            source, installed, work = root / 'source', root / 'Desktop/PY REVIT/CustomName.extension', root / 'work'
            (source / 'engine.py').write_bytes(b'two')
            (source / 'update-manifest.json').write_text(json.dumps({
                'schema': 1, 'build': 'two', 'files': {'engine.py': hashlib.sha256(b'two').hexdigest()}}))
            spec = importlib.util.spec_from_file_location('updater_ps_interop', ROOT / 'ROBMEPTOOLS.extension/lib/robmep_updater.py')
            updater = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(updater)
            updater.deploy(str(installed), str(source), str(work))
            self.assertEqual((installed / 'engine.py').read_bytes(), b'two')


if __name__ == '__main__': unittest.main()
