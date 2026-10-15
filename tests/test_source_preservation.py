"""Protect original assets and require exact provenance for intentional edits."""
import hashlib
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SourcePreservationTests(unittest.TestCase):
    def test_imported_runtime_matches_baseline_or_exact_reviewed_change(self):
        manifest = json.loads((ROOT / 'docs/import_provenance.json').read_text())
        changes = json.loads((ROOT / 'docs/runtime_change_log.json').read_text())['changes']
        allowed = {row['path']: row for row in changes}
        self.assertEqual(len(changes), len(allowed), 'Duplicate change records')
        expected_paths = {
            'ROBMEPTOOLS.extension/ROBMEPTOOLS.tab/Hangers.panel/Auto Hanger.pushbutton/' + name
            for name in ('script.py', 'settings.xaml')}
        self.assertEqual(expected_paths, set(allowed))
        checked = 0
        edited = set()
        for row in manifest['original_files']:
            name = row['source_path']
            if not name.startswith('ROBMEPTOOLS.extension/') or name.endswith('bundle.yaml'):
                continue
            with self.subTest(path=name):
                actual = ROOT / row['repository_path']
                expected = row['sha256']
                if row['repository_path'] in allowed:
                    change = allowed[row['repository_path']]
                    self.assertEqual(expected, change['baseline_sha256'])
                    self.assertTrue(change['reason'].strip())
                    self.assertNotEqual(expected, change['current_sha256'])
                    expected = change['current_sha256']
                    edited.add(row['repository_path'])
                self.assertEqual(expected, hashlib.sha256(actual.read_bytes()).hexdigest())
            checked += 1
        self.assertEqual(124, checked)
        self.assertEqual(set(allowed), edited)

    def test_no_archives_or_duplicate_extension_trees_ship(self):
        self.assertEqual([], list(ROOT.rglob('*.zip')))
        self.assertEqual([ROOT / 'ROBMEPTOOLS.extension'], list(ROOT.glob('*.extension')))
