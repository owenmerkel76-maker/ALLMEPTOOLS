import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PWSH = os.environ.get('PWSH_TEST_PATH') or shutil.which('pwsh')


@unittest.skipUnless(PWSH and shutil.which('git') and os.name != 'nt', 'Checker fixtures require PowerShell and native Git on POSIX')
class UpdaterCheckTests(unittest.TestCase):
    def check(self, case):
        with tempfile.TemporaryDirectory() as directory:
            environment = os.environ.copy()
            environment.update(XDG_CACHE_HOME='/tmp/robmep-ps-cache', XDG_CONFIG_HOME='/tmp/robmep-ps-config',
                               XDG_DATA_HOME='/tmp/robmep-ps-data')
            result = subprocess.run([PWSH, '-NoLogo', '-NoProfile', '-File', str(ROOT / 'tests/run_check_updater.ps1'),
                                     '-Root', directory, '-Case', case, '-NativeGit', shutil.which('git')],
                                    capture_output=True, text=True, env=environment, timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('PASS: checker ' + case, result.stdout)

    def test_success_requires_fresh_scheduled_task_result_and_verified_files(self): self.check('success')
    def test_missing_task_is_not_reported_as_working(self): self.check('missing-task')
    def test_wrong_task_target_is_not_run(self): self.check('wrong-folder')
    def test_authentication_failure_does_not_leak_credentials_or_run_update(self): self.check('auth')
    def test_local_changes_stop_check_before_update(self): self.check('changed-file')
    def test_open_revit_defers_task_without_claiming_verification(self): self.check('revit-open')
    def test_failed_update_result_is_not_reported_as_success(self): self.check('failed-update')
    def test_stale_success_result_cannot_pass_new_check(self): self.check('stale')
    def test_result_for_different_manifest_cannot_pass(self): self.check('bad-proof')
    def test_task_with_no_new_result_is_not_reported_as_working(self): self.check('timeout')
    def test_exact_lookup_failure_uses_enumerated_task_and_its_actual_folder(self): self.check('lookup-fallback')
    def test_missing_task_can_be_repaired_and_then_run(self): self.check('repair')
    def test_failed_task_repair_is_not_reported_as_working(self): self.check('repair-failed')
    def test_broken_powershell_provider_uses_com_to_read_and_run_task(self): self.check('com-read')
    def test_broken_provider_uses_com_to_recreate_missing_task(self): self.check('com-repair')
    def test_both_windows_interfaces_unavailable_is_a_failure(self): self.check('com-unavailable')
    def test_com_task_for_wrong_folder_is_not_run(self): self.check('com-wrong-folder')
    def test_disabled_com_task_is_not_run(self): self.check('com-disabled')


if __name__ == '__main__': unittest.main()
