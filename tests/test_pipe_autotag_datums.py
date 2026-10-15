"""BOP routing equivalence must preserve different or unproved level datums."""
import unittest
from types import SimpleNamespace

from test_pipe_autotag import namespace, Point


class PipeDatumTests(unittest.TestCase):
    def setUp(self):
        self.ns = namespace()
        self.ns.update({'SMART_HUMAN_TURN_DENSITY': True,
                        'duct_direction': lambda source: Point(1, 0, 0),
                        'duct_shape_and_size': lambda source: ('round', (.5,)),
                        'centerline_elevation': lambda source: 8.,
                        '_layout_service_key': lambda source: 'CW'})

    def test_equal_geometry_different_or_unknown_datums_do_not_collapse_turn_pair(self):
        a = SimpleNamespace(LevelId=100)
        self.assertTrue(self.ns['_turn_density_can_collapse'](a, SimpleNamespace(LevelId=100)))
        self.assertFalse(self.ns['_turn_density_can_collapse'](a, SimpleNamespace(LevelId=200)))
        self.assertFalse(self.ns['_turn_density_can_collapse'](a, SimpleNamespace()))
        self.assertFalse(self.ns['_turn_density_can_collapse'](SimpleNamespace(), SimpleNamespace()))

    def test_routing_state_includes_datum_even_when_world_height_and_service_match(self):
        key = self.ns['_human_turn_state_key']
        self.assertEqual(key(SimpleNamespace(LevelId=100)), key(SimpleNamespace(LevelId=100)))
        self.assertNotEqual(key(SimpleNamespace(LevelId=100)), key(SimpleNamespace(LevelId=200)))
        self.assertIsNone(key(SimpleNamespace(LevelId=-1)))

    def test_native_and_fabrication_parameter_sources_prove_same_or_conflicting_levels(self):
        self.ns['DB'].BuiltInParameter = SimpleNamespace(
            RBS_START_LEVEL_PARAM='start', INSTANCE_REFERENCE_LEVEL_PARAM='reference',
            FABRICATION_LEVEL_PARAM='fabrication')
        source = SimpleNamespace(LevelId=-1, get_Parameter=lambda name: (
            SimpleNamespace(AsElementId=lambda: 100) if name == 'fabrication' else None))
        self.assertEqual((100,), self.ns['_pipe_reference_level_key'](source))
        source.LevelId = 100
        self.assertEqual((100,), self.ns['_pipe_reference_level_key'](source))
        source.LevelId = 200
        self.assertEqual((100, 200), self.ns['_pipe_reference_level_key'](source))


if __name__ == '__main__':
    unittest.main()
