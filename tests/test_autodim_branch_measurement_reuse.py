"""Reuse only a proved locating coordinate on the same physical inline run."""
import ast
from pathlib import Path
import unittest
from types import SimpleNamespace
import test_autodim_accounting as accounting
from test_autodim_accounting import Point,Reference

ENGINE=Path(__file__).resolve().parents[1]/'ROBMEPTOOLS.extension/ROBMEPTOOLS.tab/AutoDim.panel/AutoDim Smart.pushbutton/engines/duct_engine.py'

class BranchMeasurementReuseTests(unittest.TestCase):
    def setUp(self):
        f=accounting.AccountingTests();f.setUp();self.__dict__.update({k:v for k,v in f.__dict__.items() if not k.startswith('_')})
        self.element=f.element
        names={'_shared_run_branch_record_is_valid','_reuse_verified_run_for_branch'}
        for n in ast.parse(ENGINE.read_bytes()).body:
            if isinstance(n,ast.FunctionDef)and n.name in names:
                exec(compile(ast.Module(body=[n],type_ignores=[]),str(ENGINE),'exec'),self.ns)
        self.dim=f.created(source=10)
        self.dim.References.values[1]=self.member.reference
        self.leg={'key':'branch:10','branch_id':10}

    def reuse(self,source=None,target=None,mode='branch-round-center',grid=None):
        return self.ns['_reuse_verified_run_for_branch'](source or self.rep,self.leg,
            target or Point(5,5),mode,grid or self.grid_info)

    def test_member_reference_can_satisfy_same_run_and_branch_coordinate(self):
        self.assertTrue(self.reuse())
        self.assertEqual({'branch:10'},self.ns['_certified_branch_keys']({100}))
        self.assertEqual(100,self.ns['_BRANCH_RUN_REUSE']['branch:10']['dim_id'])

    def test_equal_distance_on_disconnected_parallel_part_is_not_reused(self):
        other=self.element(12,5)
        self.assertFalse(self.reuse(source=other))
        self.assertNotIn('_BRANCH_RUN_REUSE',self.ns)

    def test_different_branch_station_coordinate_stays_independent(self):
        self.assertFalse(self.reuse(target=Point(8,5)))

    def test_other_grid_direction_or_grid_id_is_not_equivalent(self):
        grid=dict(self.grid_info,element=SimpleNamespace(Id=21))
        self.assertFalse(self.reuse(grid=grid))

    def test_edge_measurement_cannot_be_replaced_by_center_measurement(self):
        self.assertFalse(self.reuse(mode='branch-edge'))

    def test_display_override_cannot_supply_reused_branch_coverage(self):
        self.dim.ValueOverride='5 feet'
        self.assertFalse(self.reuse())

    def test_deleted_parent_dimension_invalidates_branch_certificate(self):
        self.assertTrue(self.reuse())
        del self.doc.elements[100]
        self.assertEqual(set(),self.ns['_certified_branch_keys'](set()))

    def test_model_reference_from_unowned_helper_never_reuses(self):
        self.dim.References.values[1]=Reference(900,'helper:900')
        self.assertFalse(self.reuse())
