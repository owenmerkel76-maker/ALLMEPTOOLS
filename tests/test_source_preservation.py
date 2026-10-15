"""Protect the imported runtime code and settings during repository integration."""
import hashlib
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SourcePreservationTests(unittest.TestCase):
    def test_all_imported_runtime_and_assets_are_unchanged(self):
        manifest = json.loads((ROOT / 'docs/import_provenance.json').read_text())
        checked = 0
        for row in manifest['original_files']:
            name = row['source_path']
            if not name.startswith('ROBMEPTOOLS.extension/') or name.endswith('bundle.yaml'):
                continue
            with self.subTest(path=name):
                actual = ROOT / row['repository_path']
                self.assertEqual(row['sha256'], hashlib.sha256(actual.read_bytes()).hexdigest())
            checked += 1
        self.assertEqual(124, checked)

    def test_no_archives_or_duplicate_extension_trees_ship(self):
        self.assertEqual([], list(ROOT.rglob('*.zip')))
        self.assertEqual([ROOT / 'ROBMEPTOOLS.extension'], list(ROOT.glob('*.extension')))
