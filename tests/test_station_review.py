"""Temporary-graphics ownership, exact-station identity and rollback contracts."""
import ast
import copy
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]
BUNDLE=ROOT/'ROBMEPTOOLS.extension/ROBMEPTOOLS.tab/Hangers.panel/Auto Hanger.pushbutton'
sys.path[:0]=[str(ROOT/'ROBMEPTOOLS.extension/lib'),str(BUNDLE)]
import planner
from robmep_core.station_review import (review_records,exact_axis_distance,validate_snapshot,validate_candidate)
from robmep_core.revit_station_review import StationGraphics
from robmep_core.revit_station_probe import exact_probe_piece,load_probe_runtime
from robmep_core.hanger_route_preview import build_route_preview
from test_hanger_route_preview import fixture,empty_inventory
from test_revit_connector_snapshot import capture,API


def sample():
    doc,parts=fixture((6,6),())
    for p in parts:p.ServiceName='Synthetic duct service'
    snap=capture(doc,parts);result=build_route_preview(snap,empty_inventory(),planner)
    records,total=review_records(snap,result)
    return doc,parts,snap,result,records


def functions(*names):
    tree=ast.parse((BUNDLE/'script.py').read_bytes())
    tree.body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
    return compile(tree,'hanger_runtime.py','exec')


class StationRecordTests(unittest.TestCase):
    def test_limit_numbering_identity_and_no_input_mutation(self):
        doc,parts,snap,result,records=sample();before=copy.deepcopy((snap,result))
        limited,total=review_records(snap,result,limit=1)
        self.assertEqual(len(records),total);self.assertEqual(1,len(limited))
        self.assertEqual(1,limited[0]['number']);self.assertEqual(1,limited[0]['route_number'])
        self.assertEqual(before,(snap,result))
        for r in records:
            host=r['host_record']
            self.assertAlmostEqual(r['from_a_ft'],exact_axis_distance(host['axis_start_ft'],host['axis_end_ft'],r['point_ft']))

    def test_exact_distance_never_clamps_off_axis_out_of_range_or_nonfinite_points(self):
        self.assertEqual(8.5,exact_axis_distance((10,0,0),(0,0,0),(1.5,0,0)))
        for p in ((1.5,.01,0),(-1,0,0),(10,0,0),(float('nan'),0,0)):
            with self.assertRaises(ValueError):exact_axis_distance((0,0,0),(10,0,0),p)

    def test_stale_scope_connection_and_geometry_are_rejected(self):
        doc,parts,snap,result,records=sample();validate_snapshot(snap,copy.deepcopy(snap))
        for name in ('source','parts','connection_ports','route_geometry','excluded_parts'):
            other=copy.deepcopy(snap);other[name]=None
            with self.assertRaises(ValueError):validate_snapshot(snap,other)
        validate_candidate(result,records[0])
        changed=copy.deepcopy(result);changed['routes'][0]['stations']=[]
        with self.assertRaises(ValueError):validate_candidate(changed,records[0])

    def test_exact_native_connector_adapter_ignores_enumeration_order_and_rejects_changed_host(self):
        doc,parts,snap,result,records=sample();r=records[0];p=next(p for p in parts if p.Id.Value==r['element_id'])
        p.ConnectorManager.Connectors.reverse()
        piece,distance=exact_probe_piece(doc,p,r,API)
        self.assertEqual(r['host_record']['end_connector_ids'][0],piece['ca'].Id)
        self.assertEqual(r['from_a_ft'],distance)
        p.ConnectorManager.Connectors[0].Origin.X+=.1
        with self.assertRaises(ValueError):exact_probe_piece(doc,p,r,API)

    def test_guarded_loader_does_not_execute_normal_command(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'script.py'
            p.write_text("def run():\n    raise AssertionError('normal placement executed')\n"
                         "def run_route_station_probe():\n    return 'probe entry only'\n"
                         "if __name__ == '__main__':\n    run()\n")
            runtime=load_probe_runtime(str(p))
            self.assertEqual('probe entry only',runtime['run_route_station_probe']())


class FakeData:
    instances=[]
    def __init__(self,path,xyz):self.path,self.xyz,self.disposed=path,xyz,False;self.instances.append(self)
    def Dispose(self):self.disposed=True


class FakeManager:
    def __init__(self):self.controls={99:'another add-in'};self.next=1;self.fail_remove=set()
    def AddControl(self,data,view):
        assert Path(data.path).is_absolute() and Path(data.path).suffix=='.bmp'
        index=self.next;self.next+=1;self.controls[index]=(data.xyz,view);return index
    def RemoveControl(self,index):
        if index in self.fail_remove:raise RuntimeError('remove failed')
        del self.controls[index]


class TemporaryGraphicsTests(unittest.TestCase):
    def setUp(self):
        self.manager=FakeManager();FakeData.instances=[]
        self.api=NS(TemporaryGraphicsManager=NS(GetTemporaryGraphicsManager=lambda d:self.manager),
                    InCanvasControlData=FakeData,XYZ=lambda *p:p)
        self.records=[dict(number=i+1,point_ft=(i+1,0,0)) for i in range(3)]
        self.writer=lambda path,n:Path(path).write_bytes(b'BM-test-only')

    def test_only_owned_controls_removed_and_resources_deleted_after_review(self):
        graphics=StationGraphics(object(),7,self.records,self.api,self.writer)
        with graphics:
            folder=Path(graphics.directory)
            self.assertEqual(4,len(self.manager.controls));self.assertTrue(folder.exists())
            self.assertTrue(all(d.disposed for d in FakeData.instances))
        self.assertEqual({99:'another add-in'},self.manager.controls)
        self.assertFalse(folder.exists())

    def test_cancel_or_exception_always_cleans_owned_markers(self):
        with self.assertRaises(RuntimeError):
            with StationGraphics(object(),7,self.records,self.api,self.writer):raise RuntimeError('cancelled')
        self.assertEqual({99:'another add-in'},self.manager.controls)

    def test_partial_marker_creation_failure_cleans_preceding_controls(self):
        def writer(path,n):
            if n==2:raise RuntimeError('render failed')
            self.writer(path,n)
        graphics=StationGraphics(object(),7,self.records,self.api,writer)
        with self.assertRaises(RuntimeError):graphics.__enter__()
        self.assertIsNone(graphics.directory)
        self.assertEqual({99:'another add-in'},self.manager.controls)

    def test_cleanup_failure_is_explicit_preserves_resources_and_tries_every_control(self):
        graphics=StationGraphics(object(),7,self.records,self.api,self.writer);graphics.__enter__()
        folder=Path(graphics.directory);self.manager.fail_remove={2}
        try:
            with self.assertRaisesRegex(ValueError,'no hanger test started'):graphics.close()
            self.assertEqual({99,2},set(self.manager.controls));self.assertTrue(folder.exists())
        finally:
            self.manager.fail_remove.clear();graphics.close()
        self.assertFalse(folder.exists())


class FakeTransaction:
    instances=[]
    status='RolledBack'
    def __init__(self,*a):self.started=False;self.rolled=False;self.instances.append(self)
    def Start(self):self.started=True
    def RollBack(self):self.rolled=True;return self.status


class ExactRollbackTests(unittest.TestCase):
    def namespace(self):
        self.piece=dict(id=7,a=(0,0,0),b=(10,0,0),shape='rectangular',service_id=1,w=2,h=1)
        self.cfg=dict(buttons_by_service={1:{'rectangular':NS(Name='Synthetic hanger')}},large_threshold_ft=None)
        result=dict(origin=(1.5,0,0),created=True,hosted=True,rod_count=2,raw_targets=2,
                    validated_targets=2,lengths_verified=True,clearance=True,cleaned=True,rods=[],errors=[])
        ns=dict(DOC=object(),UIDOC=NS(Selection=NS(PickPoint=Mock(return_value=NS(X=20.,Y=0.,Z=0.)))),
                planner=planner,Transaction=FakeTransaction,extract_segment=lambda p:(self.piece,None),
                inspect_single_hanger=Mock(return_value=result),xyz_tuple=lambda p:(p.X,p.Y,p.Z),
                OUTPUT=NS(print_md=Mock()),forms=NS(alert=Mock()),_LINKED_CLEARANCE=None,
                OperationCanceledException=RuntimeError)
        FakeTransaction.instances=[];FakeTransaction.status='RolledBack'
        exec(functions('run_single_hanger_test'),ns)
        return ns

    def test_exact_point_skips_pick_and_clamp_and_outer_transaction_is_rolled_back(self):
        ns=self.namespace()
        with patch('robmep_core.revit_station_probe.exact_probe_piece',return_value=(self.piece,1.5)):
            ns['run_single_hanger_test'](object(),object(),self.cfg,station_request={'point_ft':(1.5,0,0)})
        ns['UIDOC'].Selection.PickPoint.assert_not_called()
        self.assertEqual(1.5,ns['inspect_single_hanger'].call_args.args[0]['from_a'])
        self.assertTrue(FakeTransaction.instances[0].rolled)

    def test_probe_failure_still_rolls_back_outer_transaction(self):
        ns=self.namespace();ns['inspect_single_hanger'].side_effect=ValueError('rod read failed')
        with patch('robmep_core.revit_station_probe.exact_probe_piece',return_value=(self.piece,1.5)):
            with self.assertRaisesRegex(ValueError,'rod read failed'):
                ns['run_single_hanger_test'](object(),object(),self.cfg,station_request={})
        self.assertTrue(FakeTransaction.instances[0].rolled)
        ns['forms'].alert.assert_not_called()

    def test_unknown_or_failed_outer_rollback_never_claims_clean_test(self):
        for status in (None,'Committed','Error'):
            ns=self.namespace();FakeTransaction.status=status
            with patch('robmep_core.revit_station_probe.exact_probe_piece',return_value=(self.piece,1.5)):
                with self.assertRaisesRegex(ValueError,'rollback did not complete'):
                    ns['run_single_hanger_test'](object(),object(),self.cfg,station_request={})
            ns['forms'].alert.assert_not_called()

    def test_invalid_exact_host_is_rejected_before_transaction(self):
        ns=self.namespace()
        with patch('robmep_core.revit_station_probe.exact_probe_piece',side_effect=ValueError('stale host')):
            with self.assertRaisesRegex(ValueError,'stale host'):
                ns['run_single_hanger_test'](object(),object(),self.cfg,station_request={})
        self.assertEqual([],FakeTransaction.instances)

    def test_original_manual_single_test_keeps_pick_and_clamp_behavior(self):
        ns=self.namespace();ns['run_single_hanger_test'](object(),object(),self.cfg)
        ns['UIDOC'].Selection.PickPoint.assert_called_once()
        self.assertEqual(9.745,ns['inspect_single_hanger'].call_args.args[0]['from_a'])
        self.assertTrue(FakeTransaction.instances[0].rolled)

    def test_actual_script_entrypoint_runs_only_for_normal_command(self):
        tree=ast.parse((BUNDLE/'script.py').read_bytes());guard=tree.body[-1]
        self.assertIsInstance(guard,ast.If)
        for name,expected in (('__main__',1),('robmep_station_probe_runtime',0)):
            ns={'__name__':name,'run':Mock()}
            exec(compile(ast.Module(body=[guard],type_ignores=[]),'entry.py','exec'),ns)
            self.assertEqual(expected,ns['run'].call_count)


class ProbeEntrySafetyTests(unittest.TestCase):
    def namespace(self):
        self.wnd=NS(singleTestCheck=NS(IsChecked=False),previewCheck=NS(),rodClashCheck=NS(),
                    spacingBox=NS(),offsetBox=NS(),placeButton=NS(),confirmed=True,
                    settings=dict(single_test=False,preview=False,reject_rod_clashes=False,
                                  review_references=False,max_rod=20.),ShowDialog=Mock())
        self.choice=NS(sources=[],preflight_unlocated=lambda:[],path_validator=None)
        self.checker=NS(failures=[],check=Mock(return_value=(True,'')))
        self.checker.prepare=Mock(return_value=self.checker)
        self.save=Mock()
        self.preflight=Mock()
        ns=dict(DOC=object(),UIDOC=object(),is_duct_straight=lambda p:True,
                structure_picker=NS(choose_structure=Mock(return_value=dict(sources=[],
                    priority_mode='preferred_first',max_rod=20.,save_preferences=self.save))),
                structure_priority=NS(StructureChoice=lambda **kw:self.choice),
                service_hanger_choices=lambda ids:{1:{'buttons':[('test',object())]}},
                get_settings=lambda:(lambda *a:self.wnd),
                linked_obstacles=NS(LinkedObstructionChecker=lambda *a,**k:self.checker),
                OUTPUT=NS(print_md=Mock()),review_clearance_references=Mock(),
                run_single_hanger_test=Mock(),XYZ=lambda *p:p)
        exec(functions('run_route_station_probe'),ns)
        return ns

    def test_probe_mode_cannot_be_changed_to_apply_or_clearance_disabled_by_settings(self):
        ns=self.namespace();request=dict(number=1,route_number=1,element_id=7,point_ft=(1.5,0,0))
        ns['run_route_station_probe'](NS(ServiceId=1),request,self.preflight)
        self.assertEqual(2,self.preflight.call_count)
        args=ns['run_single_hanger_test'].call_args
        cfg=args.args[2]
        self.assertTrue(cfg['single_test']);self.assertFalse(cfg['preview'])
        self.assertTrue(cfg['reject_rod_clashes']);self.assertTrue(cfg['review_references'])
        self.assertIs(request,args.kwargs['station_request'])
        ns['review_clearance_references'].assert_called_once_with(self.checker)
        self.assertFalse(self.wnd.singleTestCheck.IsEnabled)
        self.assertFalse(self.wnd.rodClashCheck.IsEnabled)
        self.assertEqual('Test and roll back',self.wnd.placeButton.Content)
        self.save.assert_not_called()

    def test_canceling_targets_or_settings_starts_no_probe(self):
        for stage in ('targets','settings'):
            ns=self.namespace()
            if stage=='targets':ns['structure_picker'].choose_structure.return_value=None
            else:self.wnd.confirmed=False
            ns['run_route_station_probe'](NS(ServiceId=1),{'number':1},self.preflight)
            ns['run_single_hanger_test'].assert_not_called()
            self.checker.prepare.assert_not_called()

    def test_changed_geometry_after_settings_starts_no_probe(self):
        ns=self.namespace();self.preflight.side_effect=[None,ValueError('geometry changed')]
        request=dict(number=1,route_number=1,element_id=7,point_ft=(1.5,0,0))
        with self.assertRaisesRegex(ValueError,'geometry changed'):
            ns['run_route_station_probe'](NS(ServiceId=1),request,self.preflight)
        ns['run_single_hanger_test'].assert_not_called()


class NativeProbeStageTests(unittest.TestCase):
    def namespace(self,fail_first=False):
        FakeTransaction.instances=[];FakeTransaction.status='RolledBack'
        info=NS(IsAttachedToStructure=False,CanRodsBeHosted=True,Dispose=Mock())
        hanger=NS(Origin=NS(X=1.5,Y=0,Z=0),GetRodInfo=lambda:info)
        choice=NS(path_validator=object(),target_diagnostic_text=lambda *a:'unreadable source')
        def target(base,maximum):
            if fail_first and base.X==0:return None
            return dict(tier='preferred',source_label='Synthetic source',id=30,
                        z=10.,length=10.,link_instance_id=4)
        choice.target_for_rod=target
        rods=[(i,NS(X=float(i),Y=0.,Z=0.),2.) for i in (0,1)]
        ns=dict(DOC=NS(Regenerate=Mock()),SubTransaction=FakeTransaction,
                FabricationPart=NS(CreateHanger=Mock(return_value=hanger)),
                attached_to_proposed_host=lambda h,p:True,
                rod_geometry=NS(read_rods=lambda h:rods,apply_lengths=Mock()),
                check_measured_draft_rod_clashes=Mock(return_value=(True,'')),
                xyz_tuple=lambda p:(p.X,p.Y,p.Z))
        exec(functions('inspect_single_hanger'),ns)
        job=dict(piece=dict(part=NS(Id=7),id=7,ca=object()),button=object(),from_a=1.5)
        return ns,choice,info,job

    def test_both_rods_measured_and_native_attachment_not_claimed(self):
        ns,choice,info,job=self.namespace()
        result=ns['inspect_single_hanger'](job,choice,{'max_rod':20.})
        self.assertEqual(2,result['validated_targets']);self.assertTrue(result['lengths_verified'])
        self.assertTrue(result['clearance']);self.assertTrue(result['cleaned'])
        self.assertFalse(ns['FabricationPart'].CreateHanger.call_args.args[-1])
        self.assertFalse(info.CanRodsBeHosted);info.Dispose.assert_called_once()
        self.assertTrue(FakeTransaction.instances[0].rolled)

    def test_unreadable_first_rod_does_not_hide_second_or_guess_lengths(self):
        ns,choice,info,job=self.namespace(fail_first=True);validator=choice.path_validator
        result=ns['inspect_single_hanger'](job,choice,{'max_rod':20.})
        self.assertEqual(2,len(result['rods']));self.assertIsNotNone(result['rods'][1]['validated'])
        self.assertEqual(1,result['validated_targets']);self.assertFalse(result['lengths_verified'])
        ns['rod_geometry'].apply_lengths.assert_not_called()
        self.assertIs(validator,choice.path_validator);self.assertTrue(result['cleaned'])

    def test_failed_creation_or_rod_sizing_always_rolls_back_inner_probe(self):
        for mode in ('creation','sizing'):
            ns,choice,info,job=self.namespace()
            if mode=='creation':ns['FabricationPart'].CreateHanger.return_value=None
            else:ns['rod_geometry'].apply_lengths.side_effect=ValueError('size failed')
            result=ns['inspect_single_hanger'](job,choice,{'max_rod':20.})
            self.assertTrue(result['errors']);self.assertTrue(result['cleaned'])
            self.assertTrue(FakeTransaction.instances[0].rolled)

    def test_failed_inner_rollback_escapes_to_outer_cleanup(self):
        ns,choice,info,job=self.namespace();FakeTransaction.status='Committed'
        with self.assertRaisesRegex(ValueError,'cleanup failed'):
            ns['inspect_single_hanger'](job,choice,{'max_rod':20.})


class ReviewHandoffTests(unittest.TestCase):
    def namespace(self):
        from test_revit_connector_snapshot import ElementId
        from types import ModuleType
        doc,parts,snap,result,records=sample()
        output=NS(print_md=Mock(),print_table=Mock())
        ns=dict(__file__=str(BUNDLE/'config.py'),revit=NS(doc=doc,uidoc=NS(RefreshActiveView=Mock())),
                forms=NS(alert=Mock(return_value=True)),
                script=NS(get_logger=lambda:NS(exception=Mock())),capture_selection=lambda d,els:capture(d,els))
        tree=ast.parse((BUNDLE/'config.py').read_bytes());tree.body=[n for n in tree.body if isinstance(n,ast.FunctionDef)]
        exec(compile(tree,'config.py','exec'),ns)
        parent=ModuleType('Autodesk');revit=ModuleType('Autodesk.Revit');db=ModuleType('Autodesk.Revit.DB')
        db.ElementId=ElementId;parent.Revit=revit;revit.DB=db
        modules={'Autodesk':parent,'Autodesk.Revit':revit,'Autodesk.Revit.DB':db}
        return ns,doc,parts,snap,result,records,output,modules

    def test_cancel_or_uncertain_graphics_cleanup_never_loads_probe_runtime(self):
        for cleanup_failure in (False,True):
            ns,doc,parts,snap,result,records,out,modules=self.namespace()
            with patch.dict(sys.modules,modules),patch('robmep_core.revit_station_review.choose_station') as choose,patch('robmep_core.revit_station_probe.load_probe_runtime') as load:
                if cleanup_failure:choose.side_effect=ValueError('marker cleanup failed')
                else:choose.return_value=None
                ns['review_and_test'](doc,snap,result,out,[8.,1.5])
                load.assert_not_called()
            if cleanup_failure:
                self.assertFalse(any('removed its temporary markers' in c.args[0] for c in out.print_md.call_args_list))

    def test_changed_model_after_marker_review_never_loads_probe_runtime(self):
        ns,doc,parts,snap,result,records,out,modules=self.namespace()
        def changed(*args):parts[0].ConnectorManager.Connectors[0].Origin.X+=.1;return records[0]
        with patch.dict(sys.modules,modules),patch('robmep_core.revit_station_review.choose_station',side_effect=changed),patch('robmep_core.revit_station_probe.load_probe_runtime') as load:
            ns['review_and_test'](doc,snap,result,out,[8.,1.5]);load.assert_not_called()
        self.assertTrue(any('data changed' in c.args[0] for c in out.print_md.call_args_list))

    def test_confirmed_fresh_station_passes_exact_record_and_revalidation_callback(self):
        ns,doc,parts,snap,result,records,out,modules=self.namespace();probe=Mock()
        with patch.dict(sys.modules,modules),patch('robmep_core.revit_station_review.choose_station',return_value=records[0]),patch('robmep_core.revit_existing_hangers.capture_existing_hangers',return_value=empty_inventory()),patch('robmep_core.revit_station_probe.load_probe_runtime',return_value={'run_route_station_probe':probe}):
            ns['review_and_test'](doc,snap,result,out,[8.,1.5])
            probe.assert_called_once();self.assertIs(records[0],probe.call_args.args[1])
            probe.call_args.args[2]()

    def test_third_menu_choice_selects_visual_mode_and_cancel_runs_nothing(self):
        tree=ast.parse((BUNDLE/'config.py').read_bytes());guard=tree.body[-1]
        for selection in ('Visual stations + single test (rolled back)',None):
            ns={'__name__':'__main__','forms':NS(CommandSwitchWindow=NS(show=lambda *a,**k:selection)),'main':Mock()}
            exec(compile(ast.Module(body=[guard],type_ignores=[]),'config.py','exec'),ns)
            if selection is None:ns['main'].assert_not_called()
            else:ns['main'].assert_called_once_with(preview=False,visual=True)
