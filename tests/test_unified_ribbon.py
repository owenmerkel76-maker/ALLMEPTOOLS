"""Verify the single-ribbon merge and disabled obsolete update entrypoint."""
from pathlib import Path
import unittest
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from validate_unified import validate, EXPECTED
class UnifiedRibbonTests(unittest.TestCase):
 def test_merge_layout_and_source(self):self.assertEqual([],validate())
 def test_count(self):self.assertEqual(17,sum(map(len,EXPECTED.values())))
 def test_autosleeve_not_falsely_installed(self):
  self.assertFalse(any('sleeve' in p.name.lower() for p in (ROOT/'ROBMEPTOOLS.extension').rglob('*.pushbutton')))
 if __name__=='__main__': unittest.main()
