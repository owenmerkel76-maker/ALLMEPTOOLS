import hashlib
import importlib.util
from pathlib import Path
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]


class LiveReleaseTests(unittest.TestCase):
    def test_published_manifest_matches_extension_and_has_both_update_modes(self):
        source = ROOT / 'ROBMEPTOOLS.extension'
        spec = importlib.util.spec_from_file_location('release_updater', source / 'lib/robmep_updater.py')
        updater = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(updater)
        manifest = updater.validate_payload(str(source))
        self.assertIn('updater/Update-Background.ps1', manifest['bootstrap_files'])
        self.assertIn('updater/Update-Core.psm1', manifest['bootstrap_files'])
        self.assertIn('updater/Git-Location.psm1', manifest['bootstrap_files'])
        self.assertIn('startup.py', manifest['bootstrap_files'])
        actual = {p.relative_to(source).as_posix() for p in source.rglob('*')
                  if p.is_file() and '__pycache__' not in p.parts and p.suffix not in ('.pyc', '.pyo')
                  and p.name != 'update-manifest.json'}
        self.assertEqual(set(manifest['files']), actual)

    def test_setup_zip_matches_current_source_and_installer_bytes(self):
        with zipfile.ZipFile(ROOT / 'downloads/ROBMEPTOOLS-AutoUpdate.zip') as bundle:
            self.assertIsNone(bundle.testzip())
            self.assertIn('Setup Auto Updates.cmd', bundle.namelist())
            self.assertIn('Check Auto Updates.cmd', bundle.namelist())
            self.assertIn('installer/Check-Updater.ps1', bundle.namelist())
            self.assertIn('installer/Scheduled-Task.psm1', bundle.namelist())
            self.assertIn('installer/Install-Updater.ps1', bundle.namelist())
            self.assertIn('installer/Install-Location.psm1', bundle.namelist())
            self.assertIn('ROBMEPTOOLS.extension/updater/Git-Location.psm1', bundle.namelist())
            for name in bundle.namelist():
                self.assertEqual(hashlib.sha256(bundle.read(name)).digest(),
                                 hashlib.sha256((ROOT / name).read_bytes()).digest(), name)


if __name__ == '__main__': unittest.main()
