"""Offline control/binding contracts; actual WPF rendering needs Revit."""
import ast
from pathlib import Path
import re
import unittest
import xml.etree.ElementTree as E

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / 'ROBMEPTOOLS.extension/ROBMEPTOOLS.tab/Hangers.panel/Auto Hanger.pushbutton'
W = '{http://schemas.microsoft.com/winfx/2006/xaml/presentation}'
X = '{http://schemas.microsoft.com/winfx/2006/xaml}'


class HangerSettingsUITests(unittest.TestCase):
    def setUp(self):
        self.tree = E.parse(BUNDLE / 'settings.xaml').getroot()
        self.controls = {e.get(X + 'Name'): e for e in self.tree.iter() if e.get(X + 'Name')}

    def test_all_original_bound_controls_and_numeric_defaults_survive(self):
        expected = dict(serviceRows='StackPanel', largeRectCheck='CheckBox',
                        largeRectWidthBox='TextBox', spacingBox='TextBox', offsetBox='TextBox',
                        rodBox='TextBox', fittingCheck='CheckBox', sideTapCheck='CheckBox',
                        rodClashCheck='CheckBox', singleTestCheck='CheckBox',
                        referenceReviewCheck='CheckBox', draftCheck='CheckBox',
                        previewCheck='CheckBox', cancelButton='Button', placeButton='Button')
        self.assertEqual(expected, {k: e.tag[len(W):] for k, e in self.controls.items()})
        for name, value in [('spacingBox','8.0'), ('offsetBox','1.5'),
                            ('rodBox','20.0'), ('largeRectWidthBox','48')]:
            self.assertEqual(value, self.controls[name].get('Text'))
        # Default assignment code remains authoritative; XAML must not override it.
        self.assertTrue(all('IsChecked' not in e.attrib for e in self.controls.values()))

    def test_primary_modes_remain_visible_and_advanced_has_live_status(self):
        advanced = list(self.tree.iter(W + 'Expander'))
        self.assertEqual(1, len(advanced))
        self.assertEqual('False', advanced[0].get('IsExpanded'))
        hidden = {e.get(X + 'Name') for e in advanced[0].iter()}
        for name in ('previewCheck','singleTestCheck','draftCheck','serviceRows',
                     'spacingBox','offsetBox','rodBox','placeButton'):
            self.assertNotIn(name, hidden)
        for name in ('sideTapCheck','rodClashCheck','fittingCheck'):
            self.assertIn(name, hidden)
            triggers = [e for e in self.tree.iter(W + 'DataTrigger')
                        if 'ElementName=' + name in e.get('Binding', '')]
            self.assertEqual(1, len(triggers))
            self.assertEqual('True', triggers[0].get('Value'))

    def test_controller_defaults_and_safe_mode_overrides_unchanged(self):
        code = (BUNDLE / 'script.py').read_text()
        tree = ast.parse(code)
        settings = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'get_settings')
        assignments = {}
        for n in ast.walk(settings):
            if isinstance(n, ast.Assign):
                for target in n.targets:
                    if isinstance(target, ast.Attribute) and target.attr == 'IsChecked':
                        assignments[ast.unparse(target.value)] = ast.literal_eval(n.value)
        self.assertEqual({'self.largeRectCheck':False, 'self.previewCheck':True,
                          'self.sideTapCheck':True, 'self.rodClashCheck':True,
                          'self.fittingCheck':True, 'self.draftCheck':True}, assignments)
        bound = set(re.findall(r'self\.(\w+)(?:\.(?:IsChecked|Text|IsEnabled|Click|Children))',
                               ast.get_source_segment(code, settings)))
        self.assertTrue(bound <= set(self.controls), bound - set(self.controls))
