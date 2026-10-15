"""Physical-route preview regressions; synthetic geometry, never Revit proof."""
import ast
import copy
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / 'ROBMEPTOOLS.extension/ROBMEPTOOLS.tab/Hangers.panel/Auto Hanger.pushbutton'
sys.path[:0] = [str(ROOT / 'ROBMEPTOOLS.extension/lib'), str(BUNDLE)]
import planner
from robmep_core.hanger_route_preview import build_route_preview, ACCESSORY_TOKENS
from robmep_core.revit_existing_hangers import capture_existing_hangers
from test_revit_connector_snapshot import Document, Part, Connector, API, ElementId, connect, capture


def fixture(lengths=(6,2,6), fittings=(1,)):
    doc=Document(); parts=[]; start=0.
    for i,length in enumerate(lengths):
        p=Part(doc,i,start,straight=i not in fittings)
        ports=p.ConnectorManager.Connectors
        ports[1].Origin.X=start+length
        for j,c in enumerate(ports):
            c.CoordinateSystem=SimpleNamespace(BasisZ=SimpleNamespace(X=-1. if j==0 else 1.,Y=0.,Z=0.))
        if parts:connect(parts[-1].ConnectorManager.Connectors[1],ports[0])
        parts.append(p);start+=length
    return doc,parts


def empty_inventory():return dict(hangers=[],issues=[],global_issues=[])


def preview(parts,doc,inventory=None):
    return build_route_preview(capture(doc,parts),inventory or empty_inventory(),planner)


class RoutePreviewTests(unittest.TestCase):
    def test_transition_axis_included_without_hosting_on_fitting_or_resetting_spacing(self):
        doc,parts=fixture();result=preview(parts,doc)
        self.assertEqual(1,len(result['routes']))
        r=result['routes'][0]
        self.assertEqual(14.,r['length_ft'])
        self.assertEqual(3,len(r['keys']))
        self.assertTrue(r['stations'])
        self.assertTrue(all(j['element_id'] in (0,2) for j in r['stations']))
        self.assertTrue(all(not 6. <= j['station_ft'] <= 8. for j in r['stations']))
        self.assertTrue(r['coordination_coverage_complete'])
        self.assertFalse(r['apply_ready'])
        stations=[s['station_ft'] for s in r['stations']]
        self.assertLessEqual(max(b-a for a,b in zip(stations,stations[1:])),8.)

    def test_five_straights_form_one_route_and_size_changes_use_strictest_rule(self):
        doc,parts=fixture((3,3,3,3,3),())
        for c in parts[2].ConnectorManager.Connectors:c.Width=10.;c.Height=2.
        r=preview(parts,doc)['routes'][0]
        self.assertEqual(15.,r['length_ft']);self.assertEqual(4.,r['maximum_ft'])
        self.assertTrue(r['coordination_coverage_complete'])
        self.assertLess(len(r['stations']),5)

    def test_reverse_input_and_connector_order_leave_exact_stations_unchanged(self):
        doc,parts=fixture();before=capture(doc,parts);a=preview(parts,doc)
        for p in parts:p.ConnectorManager.Connectors.reverse()
        b=preview(list(reversed(parts)),doc)
        self.assertEqual(a,b);self.assertEqual(before,capture(doc,parts))

    def test_reversed_physical_axis_keeps_from_a_and_world_points_consistent(self):
        doc,parts=fixture((6,6),())
        # Swap IDs on the second part; its axis direction is now reversed.
        ports=parts[1].ConnectorManager.Connectors;ports[0].Id,ports[1].Id=1,0
        r=preview(parts,doc)['routes'][0]
        for j in r['stations']:
            self.assertAlmostEqual(j['station_ft'],j['point_ft'][0])
            if j['element_id']==1:self.assertAlmostEqual(12.-j['station_ft'],j['from_a_ft'])

    def test_coincident_unconnected_parts_never_join_and_scope_cuts_are_notes(self):
        doc,parts=fixture((6,6),())
        partial=preview(parts[:1],doc)['routes'][0]
        self.assertIn('SELECTED_SCOPE_OR_UNSUPPORTED_NEIGHBOR',partial['reasons'])
        for p in parts:
            for c in p.ConnectorManager.Connectors:c.refs=[];c.IsConnected=False
        self.assertEqual(2,len(preview(parts,doc)['routes']))

    def test_connected_gap_does_not_become_route_distance(self):
        doc,parts=fixture((6,6),());parts[1].ConnectorManager.Connectors[0].Origin.X+=.75
        result=preview(parts,doc)
        self.assertEqual(2,len(result['routes']))
        self.assertTrue(all('CONNECTED_ORIGIN_GAP_NOT_TRAVERSED' in r['reasons'] for r in result['routes']))

    def test_turn_eccentric_transition_missing_normals_and_slope_are_withheld(self):
        for mode,reason in [('turn','TURN_OR_OFFSET_FITTING_UNVERIFIED'),
                            ('normal','FITTING_NORMAL_UNREADABLE'),
                            ('slope','SLOPED_OR_VERTICAL_ROUTE_NOT_SUPPORTED')]:
            with self.subTest(mode=mode):
                doc,parts=fixture()
                if mode=='turn':parts[1].ConnectorManager.Connectors[1].Origin.Y=.5
                elif mode=='normal':del parts[1].ConnectorManager.Connectors[0].CoordinateSystem
                else:parts[0].ConnectorManager.Connectors[1].Origin.Z=1.
                result=preview(parts,doc)
                self.assertIn(reason,[i['reason'] for i in result['issues']])

    def test_service_boundary_and_pipe_are_explicit(self):
        doc,parts=fixture((6,6),());parts[1].ServiceId=2
        result=preview(parts,doc)
        self.assertEqual(2,len(result['routes']))
        self.assertTrue(all('SERVICE_BOUNDARY' in r['reasons'] for r in result['routes']))
        for p in parts:p.Category.Id=ElementId(11)
        result=preview(parts,doc)
        self.assertFalse(result['routes'])
        self.assertEqual({'PIPE_PLACEMENT_NOT_IN_THIS_PREVIEW'},{i['reason'] for i in result['issues']})

    def test_branch_curve_does_not_join_mainline_to_branch_and_keepout_is_respected(self):
        doc,parts=fixture((6,6),());branch=Part(doc,9,3.)
        c=Connector(parts[0],9,3.);c.ConnectorType=API.ConnectorType.Curve
        parts[0].ConnectorManager.Connectors.append(c)
        connect(c,branch.ConnectorManager.Connectors[0])
        result=preview(parts+[branch],doc)
        main=next(r for r in result['routes'] if len(r['keys'])==2)
        self.assertEqual([3.],main['branch_stations'])
        self.assertTrue(all(abs(j['station_ft']-3.) >= .5 for j in main['stations']))
        self.assertIn('BRANCH_CONNECTION',main['reasons'])

    def test_unselected_branch_still_gets_keepout_without_needing_entire_system(self):
        doc,parts=fixture((6,6),());other=Part(doc,9,3.)
        c=Connector(parts[0],9,3.);c.ConnectorType=API.ConnectorType.Curve
        parts[0].ConnectorManager.Connectors.append(c);connect(c,other.ConnectorManager.Connectors[0])
        r=preview(parts,doc)['routes'][0]
        self.assertEqual([3.],r['branch_stations'])
        self.assertTrue(all(abs(j['station_ft']-3.) >= .5 for j in r['stations']))

    def test_existing_hangers_count_once_and_rerun_adds_zero_coordination_candidates(self):
        doc,parts=fixture();snap=capture(doc,parts);a=preview(parts,doc)['routes'][0]
        rows=[dict(element_id=100+i,host_key=j['host_key'],point_ft=j['point_ft'],
                   structural_support_verified=False) for i,j in enumerate(a['stations'])]
        result=build_route_preview(snap,dict(hangers=rows,issues=[],global_issues=[]),planner)
        self.assertEqual([],result['routes'][0]['stations'])
        self.assertEqual(len(rows),len(result['routes'][0]['existing']))
        self.assertTrue(result['routes'][0]['coordination_coverage_complete'])
        self.assertFalse(result['routes'][0]['apply_ready'])

    def test_unknown_existing_hanger_data_withholds_new_candidates(self):
        doc,parts=fixture();snap=capture(doc,parts);key=snap['parts'][0]['key']
        for inv in (dict(hangers=[],issues=[],global_issues=['UNKNOWN_HOST']),
                    dict(hangers=[],issues=[dict(host_key=key,reason='ORIGIN_UNREADABLE')],global_issues=[]),
                    dict(hangers=[dict(host_key=key,point_ft=(1000,0,0),element_id=99)],issues=[],global_issues=[])):
            r=build_route_preview(snap,inv,planner)['routes'][0]
            self.assertEqual([],r['stations']);self.assertFalse(r['coordination_coverage_complete'])

    def test_all_fitting_and_accessory_only_routes_are_not_hosted(self):
        for accessory in (False,True):
            doc,parts=fixture((6,),() if accessory else (0,))
            if accessory:parts[0].ProductName='Fire smoke damper'
            result=preview(parts,doc)
            self.assertFalse(result['routes'])
            self.assertEqual('NO_ELIGIBLE_STRAIGHT_DUCT',result['issues'][0]['reason'])

    def test_inputs_not_mutated_and_invalid_limits_rejected(self):
        doc,parts=fixture();snap=capture(doc,parts);original=copy.deepcopy(snap)
        build_route_preview(snap,empty_inventory(),planner);self.assertEqual(original,snap)
        for cap,offset in ((0,1.5),(8,0),(float('nan'),1.5),(8,float('inf'))):
            with self.assertRaises(ValueError):build_route_preview(snap,empty_inventory(),planner,cap,offset)

    def short_branched_fixture(self, branch_station=1., length=4.7, stations=(.25,3.9)):
        doc,parts=fixture((length,),())
        neighbor=Part(doc,9,branch_station)
        branch=Connector(parts[0],9,branch_station);branch.ConnectorType=API.ConnectorType.Curve
        parts[0].ConnectorManager.Connectors.append(branch)
        connect(branch,neighbor.ConnectorManager.Connectors[0])
        snap=capture(doc,parts);key=snap['parts'][0]['key']
        inv=dict(hangers=[dict(element_id=100+i,host_key=key,point_ft=(s,0,0))
                          for i,s in enumerate(stations)],issues=[],global_issues=[])
        return snap,inv

    def test_existing_coverage_survives_from_scratch_branch_candidate_conflict(self):
        snap,inv=self.short_branched_fixture()
        with patch.object(planner,'plan_run',wraps=planner.plan_run) as plan:
            r=build_route_preview(snap,inv,planner)['routes'][0]
        self.assertEqual(8.,r['maximum_ft'])
        self.assertTrue(r['coordination_coverage_complete'])
        self.assertEqual([],r['stations'])
        self.assertIn('EXISTING_STATIONS_COVER_PRELIMINARY_DISTANCES',r['reasons'])
        # The separately labeled geometric baseline still runs. There is no
        # unnecessary new-candidate pass with the branch/keep-out arguments.
        self.assertFalse(any(len(c.args)>3 for c in plan.call_args_list))
        self.assertFalse(r['apply_ready'])

    def test_existing_near_branch_warning_survives_complete_distance_coverage(self):
        snap,inv=self.short_branched_fixture(branch_station=.3)
        r=build_route_preview(snap,inv,planner)['routes'][0]
        self.assertTrue(r['coordination_coverage_complete'])
        self.assertEqual([],r['stations'])
        self.assertIn('EXISTING_STATION_NEAR_BRANCH_CLEARANCE_UNVERIFIED',r['reasons'])
        self.assertEqual(100,r['existing_branch_conflicts'][0]['element_id'])
        self.assertAlmostEqual(.05,r['existing_branch_conflicts'][0]['separation_ft'])
        self.assertFalse(r['apply_ready'])

    def test_existing_stations_do_not_override_missing_spacing_rule_or_unknown_inventory(self):
        snap,inv=self.short_branched_fixture()
        snap['parts'][0]['size']=(100.,1.)
        r=build_route_preview(snap,inv,planner)['routes'][0]
        self.assertIsNone(r['maximum_ft'])
        self.assertFalse(r['coordination_coverage_complete'])
        self.assertEqual([],r['stations'])
        snap,inv=self.short_branched_fixture();inv['global_issues']=['EXISTING_HANGER_HOST_UNREADABLE']
        r=build_route_preview(snap,inv,planner)['routes'][0]
        self.assertFalse(r['coordination_coverage_complete'])
        self.assertEqual([],r['stations'])

    def test_existing_end_shortfall_does_not_bypass_candidate_branch_checks(self):
        snap,inv=self.short_branched_fixture(length=9.4,stations=(.25,5.2))
        with patch.object(planner,'plan_run',wraps=planner.plan_run) as plan:
            r=build_route_preview(snap,inv,planner)['routes'][0]
        self.assertEqual(8.,r['maximum_ft'])
        self.assertNotIn('EXISTING_STATIONS_COVER_PRELIMINARY_DISTANCES',r['reasons'])
        self.assertTrue(any(len(c.args)>3 for c in plan.call_args_list))
        if r['coordination_coverage_complete']:
            self.assertTrue(r['stations'])
        self.assertTrue(all(abs(j['station_ft']-1.) >= .75 for j in r['stations']))
        self.assertFalse(r['apply_ready'])

    def test_legacy_geometric_comparison_is_distinct_from_physical_routes(self):
        doc,parts=fixture((6,6),())
        for p in parts:
            for c in p.ConnectorManager.Connectors:c.refs=[];c.IsConnected=False
        result=preview(parts,doc)
        self.assertEqual(2,len(result['routes']))
        self.assertEqual(1,result['baseline_geometric_groups'])
        self.assertGreater(result['baseline_raw_station_count'],0)

    def test_shared_end_fork_is_withheld_without_erasing_neighbor_diagnostics(self):
        doc,parts=fixture((6,6),());extra=Part(doc,9,6.)
        connect(parts[0].ConnectorManager.Connectors[1],extra.ConnectorManager.Connectors[0])
        result=preview(parts+[extra],doc)
        self.assertIn('AMBIGUOUS_END_CONNECTIONS',[i['reason'] for i in result['issues']])
        self.assertTrue(all(j['element_id'] != 0 for r in result['routes'] for j in r['stations']))

    def test_partial_fitting_at_route_end_is_withheld_instead_of_inventing_endpoint(self):
        doc,parts=fixture((2,6),(0,))
        result=preview(parts,doc)
        self.assertFalse(result['routes'])
        self.assertIn('FITTING_OR_DEVICE_AT_ROUTE_END',[i['reason'] for i in result['issues']])

    def test_unknown_inventory_cannot_claim_coverage_even_with_dense_known_hangers(self):
        doc,parts=fixture();snap=capture(doc,parts);first=preview(parts,doc)['routes'][0]
        rows=[dict(element_id=i+100,host_key=j['host_key'],point_ft=j['point_ft'])
              for i,j in enumerate(first['stations'])]
        inventory=dict(hangers=rows,issues=[],global_issues=['EXISTING_HANGER_HOST_UNREADABLE'])
        result=build_route_preview(snap,inventory,planner)['routes'][0]
        self.assertFalse(result['coordination_coverage_complete'])
        self.assertEqual([],result['stations'])

    def test_accessory_exclusions_match_current_production_tokens(self):
        tree=ast.parse((BUNDLE/'script.py').read_bytes())
        original=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign)
                      and any(isinstance(t,ast.Name) and t.id=='ACCESSORY_TOKENS' for t in n.targets))
        self.assertEqual(original,ACCESSORY_TOKENS)


class ExistingHangerInventoryTests(unittest.TestCase):
    def hanger(self,doc,eid,host,point=(1.5,0,-.5)):
        p=Part(doc,eid,0);p.GetHostedInfo=lambda:SimpleNamespace(HostId=ElementId(host))
        p.Origin=SimpleNamespace(X=point[0],Y=point[1],Z=point[2]);return p

    def test_host_id_origin_and_dedup_without_attachment_or_bbox_fallback(self):
        doc,parts=fixture();snap=capture(doc,parts);h=self.hanger(doc,100,0)
        h.get_BoundingBox=Mock(side_effect=AssertionError('No guessed center'))
        r=capture_existing_hangers(doc,snap['parts'],API,[h,h,self.hanger(doc,101,999)])
        self.assertEqual(1,len(r['hangers']));self.assertFalse(r['hangers'][0]['structural_support_verified'])
        h.get_BoundingBox.assert_not_called()
        self.assertEqual([],r['global_issues'])

    def test_unreadable_origin_and_unknown_host_are_explicit_and_no_fallback(self):
        doc,parts=fixture();snap=capture(doc,parts);h=self.hanger(doc,100,0);del h.Origin
        r=capture_existing_hangers(doc,snap['parts'],API,[h])
        self.assertEqual('EXISTING_HANGER_ORIGIN_UNREADABLE',r['issues'][0]['reason'])
        h.GetHostedInfo=lambda:None
        r=capture_existing_hangers(doc,snap['parts'],API,[h])
        self.assertEqual(['EXISTING_HANGER_HOST_UNREADABLE'],r['global_issues'])

    def test_failed_collector_is_not_an_empty_successful_inventory(self):
        doc,parts=fixture();snap=capture(doc,parts)
        r=capture_existing_hangers(doc,snap['parts'],API)
        self.assertEqual(['EXISTING_HANGER_COLLECTION_UNREADABLE'],r['global_issues'])


class RoutePreviewLauncherTests(unittest.TestCase):
    def test_route_mode_uses_real_pure_planner_without_starting_placement(self):
        doc,parts=fixture();snap=capture(doc,parts)
        output=SimpleNamespace(print_md=Mock(),print_table=Mock())
        ns={'forms':SimpleNamespace(ask_for_string=lambda **kw:'8,1.5'), '__file__':str(BUNDLE/'config.py'),
            'script':SimpleNamespace(get_logger=lambda:SimpleNamespace(exception=Mock())), 'build_runs':lambda *a,**k:{'runs':[]}}
        tree=ast.parse((BUNDLE/'config.py').read_bytes());tree.body=[n for n in tree.body if isinstance(n,ast.FunctionDef)]
        exec(compile(tree,'config.py','exec'),ns)
        with patch('robmep_core.revit_existing_hangers.capture_existing_hangers',return_value=empty_inventory()):
            ns['show_route_preview'](doc,snap,output)
        columns=[c.kwargs['columns'] for c in output.print_table.call_args_list]
        self.assertTrue(any('Candidate host ID' in c for c in columns))
        self.assertTrue(any('NOT an apply-ready' in c.args[0] for c in output.print_md.call_args_list))

    def test_snapshot_includes_port_proof_and_missing_normals_do_not_erase_topology(self):
        doc,parts=fixture();snap=capture(doc,parts)
        self.assertEqual(2,len(snap['connection_ports']))
        self.assertEqual(3,len(snap['route_geometry']))
        del parts[1].ConnectorManager.Connectors[0].CoordinateSystem
        new=capture(doc,parts)
        self.assertEqual(snap['connections'],new['connections'])
        self.assertEqual([],new['diagnostics'])
