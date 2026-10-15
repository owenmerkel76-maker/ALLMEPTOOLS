"""Regression checks for dimension layout decisions and certification metadata."""
import ast
import math
import pathlib
import types
import unittest
from unittest import mock

ENGINE = pathlib.Path(__file__).resolve().parents[1] / (
    'ROBMEPTOOLS.extension/ROBMEPTOOLS.tab/AutoDim.panel/'
    'AutoDim Smart.pushbutton/engines/duct_engine.py')


class XYZ:
    def __init__(self, x, y, z=0):
        self.X, self.Y, self.Z = x, y, z


def functions():
    tree = ast.parse(ENGINE.read_bytes())
    tree.body = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
    namespace = {
        'math': math, 'DB': types.SimpleNamespace(XYZ=XYZ),
        'DIM_TEXT_HALF_W_PAPER_IN': .54, 'DIM_TEXT_HALF_H_PAPER_IN': .16,
        'DIM_TEXT_HALO_PAPER_IN': .06, 'DIMENSION_LANE_HALO_PAPER_IN': .03,
        'MEP_COLLISION_KINDS': ('duct', 'fitting'),
        'W_EXISTING_DIM_LINE': 1, 'W_DIMENSION_LANE': 2, 'W_EXISTING_DIM': 3,
        '_CREATED_DIM_TARGETS': {}, '_CREATED_DIM_IDS': [],
        'view': types.SimpleNamespace(Scale=12),
    }
    namespace.setdefault('Int64', int)
    exec(compile(tree, str(ENGINE), 'exec'), namespace)
    # Model-coordinate primitives; paper-to-model exercises actual function.
    namespace['eid_int'] = int
    return namespace


class LayoutTests(unittest.TestCase):
    def test_score_can_outweigh_midpoint_preference(self):
        ns = functions()
        rank = ns['_layout_candidate_rank']
        clear_shift = rank(40, .3, {'dimension_lane': 0, '_line_mep': 0})
        crowded_midpoint = rank(600, 0, {'dimension_lane': 0, '_line_mep': 0})
        self.assertLess(clear_shift, crowded_midpoint)

    def test_lane_and_crossing_safety_remain_first(self):
        rank = functions()['_layout_candidate_rank']
        clean = rank(1000, .4, {'dimension_lane': 0, '_line_mep': 0})
        overlaps_lane = rank(0, 0, {'dimension_lane': 1, '_line_mep': 0})
        crosses_mep = rank(0, 0, {'dimension_lane': 0, '_line_mep': 1})
        self.assertLess(clean, overlaps_lane)
        self.assertLess(clean, crosses_mep)

    def test_text_bounds_protect_rotated_values(self):
        ns = functions()
        horizontal = ns['_text_rect_at_point'](XYZ(10, 20), XYZ(1, 0))
        vertical = ns['_text_rect_at_point'](XYZ(10, 20), XYZ(0, 1))
        self.assertAlmostEqual(horizontal[3] - horizontal[1], .44)
        self.assertAlmostEqual(vertical[3] - vertical[1], 1.20)
        self.assertEqual(horizontal[:1], vertical[:1])
        diagonal = ns['_text_rect_at_point'](XYZ(10, 20), XYZ(1, 1))
        self.assertGreater(diagonal[3] - diagonal[1], .44)
        self.assertTrue(ns['point_in_rect']((10, 20.5), vertical))
        self.assertFalse(ns['point_in_rect']((10, 20.5), horizontal))

    def test_paper_space_bounds_scale_with_view(self):
        ns = functions()
        r12 = ns['_text_rect_at_point'](XYZ(0, 0), XYZ(0, 1))
        ns['view'].Scale = 48
        r48 = ns['_text_rect_at_point'](XYZ(0, 0), XYZ(0, 1))
        self.assertAlmostEqual(r48[3], 4 * r12[3])
        self.assertAlmostEqual(r48[2], 4 * r12[2])

    def test_unknown_direction_is_conservative(self):
        ns = functions()
        for direction in (None, XYZ(0, 0)):
            with self.subTest(direction=direction):
                bounds = ns['_text_rect_at_point'](XYZ(0, 0), direction)
                self.assertAlmostEqual(bounds[2], .60)
                self.assertAlmostEqual(bounds[3], .60)

    def test_readability_cleanup_keeps_original_certified_target(self):
        ns = functions()
        target = XYZ(10, 20)
        ns['_CREATED_DIM_TARGETS'][7] = target
        dim = types.SimpleNamespace(Id=7, TextPosition=XYZ(1, 2),
                                    Curve=types.SimpleNamespace(Direction=XYZ(0, 1)))
        grid = mock.Mock()
        ns['reserve_created_dimension'](grid, dim, XYZ(0, 0), XYZ(99, 99),
                                        (0, 0, 1, 1), record_target=False)
        self.assertIs(ns['_CREATED_DIM_TARGETS'][7], target)
        grid.add_segment.assert_called_once()
        self.assertEqual(grid.add_rect.call_count, 2)
        self.assertEqual(ns['_CREATED_DIM_IDS'], [])

    def test_initial_creation_stores_target_for_certification(self):
        ns = functions()
        dim = types.SimpleNamespace(Id=7, TextPosition=XYZ(1, 2),
                                    Curve=types.SimpleNamespace(Direction=XYZ(1, 0)))
        ns['reserve_created_dimension'](mock.Mock(), dim, XYZ(0, 0), XYZ(10, 20),
                                        (0, 0, 1, 1))
        saved = ns['_CREATED_DIM_TARGETS'][7]
        self.assertEqual((saved.X, saved.Y), (10, 20))
        self.assertEqual(ns['_CREATED_DIM_IDS'], [])

    def test_nonadjustable_text_is_not_moved(self):
        ns = functions()
        dim = types.SimpleNamespace(TextPosition=XYZ(1, 2),
                                    IsTextPositionAdjustable=lambda: False,
                                    Curve=types.SimpleNamespace(Direction=XYZ(1, 0)))
        grid = mock.Mock()
        moved, bounds = ns['adjust_dimension_text'](dim, grid, XYZ(0, 0), XYZ(10, 0), 7)
        self.assertFalse(moved)
        self.assertIsNotNone(bounds)
        grid.score_rect.assert_not_called()
        self.assertEqual(dim.TextPosition.X, 1)

    def test_planning_uses_directional_text_bounds(self):
        ns = functions()
        horizontal = ns['dimension_text_rect'](XYZ(0, 0), XYZ(10, 0))
        vertical = ns['dimension_text_rect'](XYZ(0, 0), XYZ(0, 10))
        self.assertGreater(vertical[3] - vertical[1], horizontal[3] - horizontal[1])


if __name__ == '__main__':
    unittest.main()
