"""Pure-host regressions for the real Revit-facing accounting functions.

Revit API surfaces are small mocks; AST extraction executes the shipped
functions without importing pyRevit or claiming an in-Revit integration test.
"""
import ast
import math
import os
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "ROBMEPTOOLS.extension/ROBMEPTOOLS.tab/AutoDim.panel/AutoDim Smart.pushbutton/engines/duct_engine.py"


class Point:
    def __init__(self, x, y, z=0.0):
        self.X, self.Y, self.Z = x, y, z


class Line:
    def __init__(self, origin, direction, length=10.0):
        self.Origin, self.Direction, self.Length = origin, direction, length


class Reference:
    def __init__(self, element_id, key):
        self.ElementId, self.key = element_id, key

    def ConvertToStableRepresentation(self, doc):
        return self.key


class References:
    def __init__(self, values):
        self.values, self.Size = values, len(values)

    def get_Item(self, index):
        return self.values[index]


class Dimension:
    def __init__(self, dim_id, refs, value=5.0, direction=None):
        self.Id = dim_id
        self.References = References(refs)
        self.Value = value
        self.ValueOverride = None
        self.NumberOfSegments = 0
        self.Curve = Line(Point(0, 0), direction or Point(1, 0))


class Collector:
    def __init__(self, doc):
        self.doc = doc

    def OfClass(self, cls):
        return self

    def WhereElementIsNotElementType(self):
        return [e for e in self.doc.elements.values() if isinstance(e, Dimension)]


class AccountingTests(unittest.TestCase):
    def setUp(self):
        self.doc = SimpleNamespace(elements={})
        self.doc.GetElement = self.doc.elements.get
        self.grid = SimpleNamespace(Id=20, Curve=Line(Point(0, 0), Point(0, 1)))
        self.grid_info = {"element": self.grid, "axis": Point(0, 1), "origin": Point(0, 0),
                          "reference": Reference(20, "grid:20")}
        self.doc.elements[20] = self.grid
        self.rep = self.element(10, 5)
        self.member = self.element(11, 5)
        self.gdata = (self.grid_info, 5, 5, Point(0, 1), Point(-1, 0), Point(5, 5))
        self.resolved = [(self.rep, self.gdata)]
        self.ns = {
            "math": math, "doc": self.doc, "view": SimpleNamespace(Id=1), "eid_int": int,
            "DB": SimpleNamespace(Line=Line, ElementId=int, Dimension=Dimension,
                                  FilteredElementCollector=lambda doc, vid: Collector(doc)),
            "plan_vec": lambda p: p if p is not None and math.hypot(p.X, p.Y) else None,
            "perp_xy": lambda p: Point(-p.Y, p.X),
            "dot_xy": lambda a, b: a.X * b.X + a.Y * b.Y,
            "vector_xy": lambda a, b: Point(b.X-a.X, b.Y-a.Y),
            "duct_centerline": lambda e: e.line,
            "line_midpoint": lambda line: line.Origin,
            "duct_shape": lambda e: e.shape,
            "center_plan_point": lambda p: Point(p.X, p.Y),
            "target_plan_point": lambda mid, normal, target: Point(target.X, target.Y),
            "center_reference_candidates": lambda e, line, grid: [(e.reference, "model-center")],
            "edge_candidates_toward_grid": lambda e, line, grid: e.edge_candidates,
            "_source_target_for_element": lambda e, grid: (None, None),
            "CERT_VALUE_TOL_FT": 1.0/96.0, "CERT_DIM_GRID_PERP_DOT_MAX": 0.08,
            "_RUN_MEMBER_IDS": {10: {10, 11}},
            "_RUN_MEMBER_RECORDS": {10: [(self.rep, self.gdata), (self.member, self.gdata)]},
            "_CREATED_DIM_IDS": set(), "_CREATED_DIM_SOURCE": {}, "_CREATED_DIM_TARGETS": {},
            "_CREATED_DIM_MODE": {}, "_CREATED_DIM_GRID": {}, "_CREATED_DIM_BRANCH_KEY": {},
            "_BRANCH_LEG_RECORDS": [], "_EXISTING_DIRECT_DIM_RECORDS": {},
            "_RUN_EXPECTED_TARGET_CACHE": {},
        }
        names = {
            "_member_to_rep_map", "_covered_run_rep_ids", "_raw_target_final_coverage",
            "_raw_piece_coverage", "_certification_snapshot", "_certified_branch_keys",
            "_dimension_reference_element_ids", "_expected_target_to_grid_value",
            "_dimension_direction_is_grid_normal", "_single_dimension_references",
            "_certify_dimension_against_target", "_certify_created_dimension",
            "_stable_reference_key", "_expected_run_target", "_record_matches_run_target",
            "_existing_direct_record_is_valid", "_audited_existing_direct_source_ids",
            "_audit_existing_direct_dimensions",
        }
        path = Path(os.environ.get("AUTODIM_ENGINE_PATH", str(ENGINE)))
        tree = ast.parse(path.read_text(encoding="utf-8"))
        found = set()
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name in names:
                self.ns.setdefault('Int64', int)
                exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), self.ns)
                found.add(node.name)
        self.assertEqual(names, found, "Accounting functions must come from the engine source")

    def element(self, element_id, x):
        e = SimpleNamespace(Id=element_id, shape="round", line=Line(Point(x, 5), Point(0, 1)),
                            reference=Reference(element_id, "duct:{0}:center".format(element_id)),
                            edge_candidates=[])
        self.doc.elements[element_id] = e
        return e

    def created(self, dim_id=100, source=11, x=5, grid_id=20, mode="round-center", branch=False):
        dim = Dimension(dim_id, [Reference(20, "grid:20"), Reference(source, "duct:{0}:center".format(source))], value=x)
        self.doc.elements[dim_id] = dim
        self.ns["_CREATED_DIM_IDS"].add(dim_id)
        self.ns["_CREATED_DIM_SOURCE"][dim_id] = source
        self.ns["_CREATED_DIM_TARGETS"][dim_id] = Point(x, 5)
        self.ns["_CREATED_DIM_MODE"][dim_id] = mode
        self.ns["_CREATED_DIM_GRID"][dim_id] = grid_id
        if branch:
            self.ns["_CREATED_DIM_BRANCH_KEY"][dim_id] = "branch:1"
        return dim

    def audit(self, dim):
        self.doc.elements[dim.Id] = dim
        records = self.ns["_audit_existing_direct_dimensions"](self.resolved)
        self.ns["_EXISTING_DIRECT_DIM_RECORDS"].update(records)
        return records

    def test_alternate_member_reference_covers_all_physical_run_members(self):
        self.created()
        self.assertEqual(({10, 11}, {10, 11}, set()),
                         self.ns["_raw_target_final_coverage"](self.resolved, [], {100}))

    def test_no_grid_target_is_in_certification_denominator_and_missing_list(self):
        self.created()
        no_grid = self.element(12, 7)
        result = self.ns["_certification_snapshot"](self.resolved, {100}, [no_grid])
        self.assertEqual(2, result["required_total"])
        self.assertEqual(1, result["certified_total"])
        self.assertEqual([12], result["missing_run_ids"])

    def test_no_grid_direct_reference_covers_target_and_raw_piece(self):
        self.created()
        no_grid = self.element(12, 7)
        self.created(101, source=12, x=7)
        result = self.ns["_certification_snapshot"](self.resolved, {100, 101}, [no_grid])
        self.assertEqual(2, result["certified_total"])
        self.assertEqual([], result["missing_run_ids"])
        self.assertEqual(({10, 11, 12}, {10, 11, 12}, set()),
                         self.ns["_raw_piece_coverage"](self.resolved, [no_grid], {100, 101}))

    def test_wrong_source_straight_dimension_is_rejected_not_retained_as_clutter(self):
        self.created(x=8)
        result = self.ns["_certification_snapshot"](self.resolved, {100}, [])
        self.assertEqual(set(), result["certified_ids"])
        self.assertEqual("source-target-mismatch", result["rejected"][0][1])
        self.assertEqual([10], result["missing_run_ids"])

    def test_independent_branch_dimension_remains_but_does_not_cover_wrong_run(self):
        self.created(x=8, branch=True)
        result = self.ns["_certification_snapshot"](self.resolved, {100}, [])
        self.assertEqual({100}, result["certified_ids"])
        self.assertEqual([10], result["missing_run_ids"])
        self.assertEqual([], result["rejected"])

    def test_valid_chosen_point_cannot_cover_different_source_offset(self):
        self.created(x=8)
        self.assertTrue(self.ns["_certify_created_dimension"](100)[0])
        self.assertEqual(set(), self.ns["_covered_run_rep_ids"](self.resolved, {100}))

    def test_wrong_grid_cannot_cover_source_run(self):
        self.created(grid_id=21)
        self.assertEqual(set(), self.ns["_covered_run_rep_ids"](self.resolved, {100}))

    def test_edge_mode_cannot_cover_round_center_target(self):
        self.created(mode="branch-edge")
        self.assertEqual(set(), self.ns["_covered_run_rep_ids"](self.resolved, {100}))

    def test_branch_reference_can_cover_run_when_geometry_independently_matches(self):
        self.created(branch=True)
        self.assertEqual({10}, self.ns["_covered_run_rep_ids"](self.resolved, {100}))

    def test_wrong_axis_branch_reference_does_not_cover_run(self):
        dim = self.created(branch=True)
        dim.Curve.Direction = Point(0, 1)
        self.assertEqual(set(), self.ns["_covered_run_rep_ids"](self.resolved, {100}))

    def test_existing_direct_model_dimension_covers_run_without_entering_delete_set(self):
        dim = Dimension(200, [Reference(20, "grid:20"), self.member.reference])
        self.assertEqual({200}, set(self.audit(dim)))
        self.assertEqual({10}, self.ns["_covered_run_rep_ids"](self.resolved, set()))
        result = self.ns["_certification_snapshot"](self.resolved, set())
        self.assertEqual(1, result["certified_total"])
        self.assertEqual([], result["rejected"])
        self.assertEqual(set(), self.ns["_CREATED_DIM_IDS"])
        self.assertEqual(({10, 11}, {10, 11}, set()),
                         self.ns["_raw_piece_coverage"](self.resolved, [], set()))

    def test_matching_value_on_new_helper_cannot_certify_source_coverage(self):
        dim = self.created()
        dim.References.values[1] = Reference(900, "helper:900")
        self.assertEqual('source-reference-mismatch', self.ns['_certify_created_dimension'](100)[1])
        self.assertEqual(set(), self.ns['_covered_run_rep_ids'](self.resolved, {100}))

    def test_new_display_override_cannot_certify_source_coverage(self):
        dim = self.created()
        dim.ValueOverride = "5 feet"
        self.assertEqual('display-override', self.ns['_certify_created_dimension'](100)[1])

    def test_unknown_existing_helper_does_not_cover_any_source(self):
        dim = Dimension(200, [Reference(20, "grid:20"), Reference(900, "helper:900")])
        self.assertEqual({}, self.audit(dim))
        self.assertEqual(set(), self.ns["_covered_run_rep_ids"](self.resolved, set()))

    def test_existing_wrong_model_reference_cannot_pass_on_matching_value_alone(self):
        dim = Dimension(200, [Reference(20, "grid:20"), Reference(11, "duct:11:wrong-face")])
        self.assertEqual({}, self.audit(dim))

    def test_existing_display_override_does_not_supply_certified_coverage(self):
        dim = Dimension(200, [Reference(20, "grid:20"), self.member.reference])
        dim.ValueOverride = "6'-0\""
        self.assertEqual({}, self.audit(dim))

    def test_changed_existing_value_loses_coverage(self):
        dim = Dimension(200, [Reference(20, "grid:20"), self.member.reference])
        self.audit(dim)
        dim.Value = 8
        self.assertEqual(set(), self.ns["_covered_run_rep_ids"](self.resolved, set()))

    def test_dimension_chain_is_not_certified_as_single_length(self):
        dim = self.created()
        dim.NumberOfSegments = 2
        self.assertFalse(self.ns["_certify_created_dimension"](100)[0])

    def test_direction_check_fails_closed_for_non_line_and_bad_grid(self):
        dim = self.created()
        dim.Curve = object()
        self.assertFalse(self.ns["_dimension_direction_is_grid_normal"](dim, self.grid))
        dim.Curve = Line(Point(0, 0), Point(1, 0))
        self.assertFalse(self.ns["_dimension_direction_is_grid_normal"](dim, object()))

    def test_nonfinite_dimension_value_is_not_certified(self):
        dim = self.created()
        dim.Value = float("nan")
        self.assertFalse(self.ns["_certify_created_dimension"](100)[0])


if __name__ == "__main__":
    unittest.main()
