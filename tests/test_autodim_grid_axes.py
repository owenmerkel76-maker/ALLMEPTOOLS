"""Exercise grid inventory and assignment with actual engine functions."""
import ast
import math
from pathlib import Path
from types import SimpleNamespace
import unittest

ENGINE = Path(__file__).resolve().parents[1] / 'ROBMEPTOOLS.extension/ROBMEPTOOLS.tab/AutoDim.panel/AutoDim Smart.pushbutton/engines/duct_engine.py'

class Point:
    def __init__(self, x, y, z=0):
        self.X, self.Y, self.Z = x, y, z

class Line:
    def __init__(self, x, y, dx, dy):
        self.Origin = Point(x, y)
        self.Direction = Point(dx, dy)

class Grid:
    def __init__(self, element_id, name, line):
        self.Id, self.Name, self.Curve = element_id, name, line

class Collector:
    def __init__(self, items):
        self.items = items
    def OfClass(self, cls):
        return self
    def WhereElementIsNotElementType(self):
        return self
    def __iter__(self):
        return iter(self.items)

def namespace(view_grids, host_grids, lookup=None):
    tree = ast.parse(ENGINE.read_bytes())
    tree.body = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
    doc = SimpleNamespace(GetElement=lambda eid: (lookup or {}).get(eid))
    ns = {'math': math, 'doc': doc, 'view': SimpleNamespace(Id=100),
          'DB': SimpleNamespace(Line=Line, Grid=Grid, ElementId=int,
                                FilteredElementCollector=lambda doc, *view: Collector(view_grids if view else host_grids))}
    ns.setdefault('Int64', int)
    exec(compile(tree, str(ENGINE), 'exec'), ns)
    ns.update({'eid_int': int, 'plan_vec': lambda p: p, 'grid_reference': lambda g: 'ref-'+str(g.Id),
               'perp_xy': lambda p: Point(-p.Y, p.X), 'dot_xy': lambda a, b: a.X*b.X+a.Y*b.Y,
               'vector_xy': lambda a, b: Point(b.X-a.X, b.Y-a.Y), 'line_midpoint': lambda line: line.Origin,
               'PARALLEL_TOL_DEG': 5, 'MAX_GRID_DISTANCE_FT': 150})
    return ns

class GridAxisTests(unittest.TestCase):
    def setUp(self):
        self.x = Grid(1, 'A', Line(0, 0, 1, 0))
        self.y = Grid(2, '1', Line(0, 0, 0, 1))

    def test_successful_partial_view_collector_recovers_other_axis(self):
        ns = namespace([self.x], [self.x, self.y])
        grids = ns['collect_straight_grids']()
        self.assertEqual([1, 2], [g['element'].Id for g in grids])
        result = ns['nearest_parallel_grid'](Line(5, 5, 0, 1), grids)
        self.assertEqual(2, result[0]['element'].Id)
        self.assertEqual([2], ns['AUTODIM_GRID_INVENTORY']['fallback_grid_ids'])

    def test_both_axis_assignments_survive_one_missing_view_direction(self):
        ns = namespace([self.x], [self.x, self.y])
        grids = ns['collect_straight_grids']()
        self.assertEqual([1, 2], [ns['nearest_parallel_grid'](line, grids)[0]['element'].Id
                                for line in [Line(5, 5, 1, 0), Line(5, 5, 0, 1)]])

    def test_closer_host_fallback_does_not_replace_eligible_view_grid(self):
        fallback = Grid(3, 'B', Line(0, 4, 1, 0))
        ns = namespace([self.x], [self.x, fallback])
        self.assertEqual(1, ns['nearest_parallel_grid'](Line(5, 5, 1, 0), ns['collect_straight_grids']())[0]['element'].Id)

    def test_preferred_selected_grid_wins_even_if_omitted_from_view(self):
        ns = namespace([self.x], [self.x, self.y])
        ns.update({'AUTODIM_GRID_MODE': 'prefer', 'AUTODIM_GRID_IDS': [2]})
        result = ns['nearest_parallel_grid'](Line(5, 5, 0, 1), ns['collect_straight_grids']())
        self.assertEqual(2, result[0]['element'].Id)

    def test_strict_mode_does_not_invent_unselected_axis_coverage(self):
        ns = namespace([self.x], [self.x, self.y])
        ns.update({'AUTODIM_GRID_MODE': 'strict', 'AUTODIM_GRID_IDS': [1]})
        self.assertIsNone(ns['nearest_parallel_grid'](Line(5, 5, 0, 1), ns['collect_straight_grids']()))

    def test_explicit_selected_host_grid_can_be_resolved_directly(self):
        ns = namespace([self.x], [self.x], {2: self.y})
        ns.update({'AUTODIM_GRID_MODE': 'strict', 'AUTODIM_GRID_IDS': [2]})
        self.assertEqual(2, ns['nearest_parallel_grid'](Line(5, 5, 0, 1), ns['collect_straight_grids']())[0]['element'].Id)

    def test_empty_view_collector_uses_both_host_axes(self):
        ns = namespace([], [self.x, self.y])
        grids = ns['collect_straight_grids']()
        self.assertEqual([1, 2], [g['element'].Id for g in grids])
        self.assertEqual([1, 2], ns['AUTODIM_GRID_INVENTORY']['fallback_grid_ids'])

    def test_distance_limit_still_applies_to_fallback(self):
        ns = namespace([], [self.y])
        self.assertIsNone(ns['nearest_parallel_grid'](Line(200, 5, 0, 1), ns['collect_straight_grids']()))

    def test_curved_grid_remains_unsupported_and_is_reported(self):
        ns = namespace([], [Grid(3, 'Arc', object())])
        self.assertEqual([], ns['collect_straight_grids']())
        self.assertEqual('curved-or-nonlinear-grid', ns['AUTODIM_GRID_INVENTORY']['rejected'][0]['reason'])
