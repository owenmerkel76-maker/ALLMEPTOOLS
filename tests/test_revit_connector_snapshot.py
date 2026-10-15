"""Read-only API-double fixtures; live Revit 2025 remains a separate field gate."""
import ast
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'ROBMEPTOOLS.extension/lib'))
from robmep_core.connector_graph import build_runs
from robmep_core.revit_connector_snapshot import capture_selection


class ElementId:
    def __init__(self, value): self.Value = value


class Document:
    IsFamilyDocument = False
    ProjectInformation = SimpleNamespace(UniqueId='project-guid')

    def __init__(self): self.elements = {}
    def GetElement(self, eid): return self.elements[eid.Value]


class Connector:
    def __init__(self, owner, cid, x):
        self.Owner, self.Id = owner, cid
        self.Origin = SimpleNamespace(X=x, Y=0., Z=0.)
        self.ConnectorType, self.Domain, self.Shape = 1, 1, 1
        self.Width, self.Height, self.Radius = 2., 1., .5
        self.IsConnected = False
        self.refs, self.proof, self.unreadable = [], True, False

    @property
    def AllRefs(self):
        if self.unreadable: raise RuntimeError('unreadable API object')
        return self.refs

    def IsConnectedTo(self, other):
        return self.proof and other in self.refs


class Part:
    def __init__(self, document, eid, start, straight=True, category=10):
        self.Document, self.Id, self.UniqueId = document, ElementId(eid), 'uid-' + str(eid)
        self.Category, self.ServiceId = SimpleNamespace(Id=ElementId(category)), 1
        self.straight, self.hanger, self.tap = straight, False, False
        self.ConnectorManager = SimpleNamespace(Connectors=[Connector(self,0,start),Connector(self,1,start+3.)])
        document.elements[eid] = self

    def IsAStraight(self): return self.straight
    def IsAHanger(self): return self.hanger
    def IsATap(self): return self.tap


API = SimpleNamespace(
    ElementId=ElementId, FabricationPart=Part,
    BuiltInCategory=SimpleNamespace(OST_FabricationDuctwork=10, OST_FabricationPipework=11),
    ConnectorType=SimpleNamespace(Logical=0, End=1, Curve=2, Physical=3),
    Domain=SimpleNamespace(DomainHvac=1, DomainPiping=2),
    ConnectorProfileType=SimpleNamespace(Rectangular=1, Round=2, Oval=3))


def connect(a,b):
    a.refs.append(b); b.refs.append(a)
    a.IsConnected = b.IsConnected = True


def chain(count=5):
    doc=Document(); parts=[Part(doc,i,i*3.) for i in range(count)]
    for a,b in zip(parts,parts[1:]):connect(a.ConnectorManager.Connectors[1],b.ConnectorManager.Connectors[0])
    return doc,parts


def capture(doc,parts):return capture_selection(doc,parts,API)


class SnapshotTests(unittest.TestCase):
    def test_five_real_connector_owners_form_one_fifteen_foot_snapshot(self):
        doc,parts=chain()
        snapshot=capture(doc,parts); result=build_runs(snapshot['parts'],snapshot['connections'])
        self.assertEqual([],snapshot['diagnostics'])
        self.assertEqual(4,len(snapshot['connections']))
        self.assertEqual(5,len(result['runs'][0]['keys']))
        self.assertEqual(15.,result['runs'][0]['length_ft'])
        self.assertEqual({},result['boundaries'])

    def test_coincident_but_unconnected_parts_do_not_join(self):
        doc=Document();parts=[Part(doc,1,0),Part(doc,2,3)]
        result=capture(doc,parts)
        self.assertEqual([],result['connections'])
        self.assertEqual(2,len(build_runs(result['parts'],[])['runs']))

    def test_logical_connections_are_not_physical_edges(self):
        doc=Document();a,b=Part(doc,1,0),Part(doc,2,3)
        logical=Connector(b,9,3);logical.ConnectorType=0
        a.ConnectorManager.Connectors[1].refs.append(logical)
        result=capture(doc,[a,b])
        self.assertEqual([],result['connections']);self.assertEqual([],result['diagnostics'])

    def test_one_way_connection_is_unresolved(self):
        doc,parts=chain(2);parts[1].ConnectorManager.Connectors[0].proof=False
        result=capture(doc,parts)
        self.assertEqual([],result['parts'])
        self.assertEqual({'UNVERIFIED_CONNECTION'},{d['reason'] for d in result['diagnostics']})

    def test_unselected_continuation_remains_explicit_scope_cut(self):
        doc,parts=chain(3);result=capture(doc,parts[:2])
        analysis=build_runs(result['parts'],result['connections'])
        self.assertEqual(2,len(result['parts']))
        self.assertTrue(any(row[0]=='OUTSIDE_SCOPE' for row in analysis['unresolved']))
        self.assertEqual(2,len(analysis['runs']))

    def test_unreadable_connectors_do_not_become_open_ends(self):
        doc,parts=chain(2);parts[1].ConnectorManager.Connectors[1].unreadable=True
        result=capture(doc,parts);analysis=build_runs(result['parts'],result['connections'])
        self.assertEqual(1,len(result['parts']))
        self.assertIn('UNREADABLE_CONNECTION',[d['reason'] for d in result['diagnostics']])
        self.assertTrue(analysis['unresolved'])

    def test_connector_owner_mismatch_is_rejected(self):
        doc,parts=chain(2);parts[0].ConnectorManager.Connectors[0].Owner=parts[1]
        result=capture(doc,parts)
        self.assertIn('CONNECTOR_OWNER_MISMATCH',[d['reason'] for d in result['diagnostics']])

    def test_missing_service_profile_nonfinite_axis_and_end_count_are_reported(self):
        def bad_service(p):p.ServiceId=-1
        def bad_size(p):p.ConnectorManager.Connectors[0].Width=0
        def bad_axis(p):p.ConnectorManager.Connectors[0].Origin.Z=float('nan')
        def bad_shape(p):p.ConnectorManager.Connectors[1].Shape=2
        def bad_ends(p):p.ConnectorManager.Connectors.append(Connector(p,2,1))
        for mutate,reason in [(bad_service,'MISSING_SERVICE'),(bad_size,'INVALID_SIZE'),
                              (bad_axis,'NONFINITE_GEOMETRY'),(bad_shape,'END_PROFILE_MISMATCH'),
                              (bad_ends,'AMBIGUOUS_END_CONNECTORS')]:
            with self.subTest(reason=reason):
                doc,parts=chain(1);mutate(parts[0]);result=capture(doc,parts)
                self.assertEqual([],result['parts'])
                self.assertEqual(reason,result['diagnostics'][0]['reason'])

    def test_tee_and_tap_remain_boundaries(self):
        for tap in (False,True):
            doc,parts=chain(3);parts[1].straight=tap;parts[1].tap=tap
            result=capture(doc,parts);analysis=build_runs(result['parts'],result['connections'])
            self.assertEqual('fitting',result['parts'][1]['kind'])
            self.assertEqual(2,len(analysis['runs']))
            self.assertTrue(all('NON_STRAIGHT' in r for r in analysis['boundaries'].values()))

    def test_round_pipe_and_sloped_axis(self):
        doc=Document();p=Part(doc,1,0,category=11)
        for c in p.ConnectorManager.Connectors:c.Shape=2;c.Domain=2
        p.ConnectorManager.Connectors[1].Origin.Z=4.
        result=capture(doc,[p]);record=result['parts'][0]
        self.assertEqual('round',record['shape']);self.assertEqual((1.,),record['size'])
        self.assertEqual(5.,record['length_ft']);self.assertEqual((.6,0.,.8),record['direction'])
        self.assertEqual((0.,0.,0.),record['axis_start_ft'])
        self.assertEqual((3.,0.,4.),record['axis_end_ft'])
        self.assertEqual((0,1),record['end_connector_ids'])

    def test_foreign_selected_document_and_foreign_reference_are_rejected(self):
        doc,parts=chain(2);foreign=Document();parts[1].Document=foreign
        result=capture(doc,parts)
        self.assertEqual([],result['parts'])
        self.assertEqual({'FOREIGN_DOCUMENT'},{d['reason'] for d in result['diagnostics']})

    def test_true_connected_flag_without_physical_references_is_not_success(self):
        doc,parts=chain(1);parts[0].ConnectorManager.Connectors[0].IsConnected=True
        result=capture(doc,parts)
        self.assertEqual([],result['parts'])
        self.assertEqual('CONNECTED_WITHOUT_PHYSICAL_REFERENCE',result['diagnostics'][0]['reason'])

    def test_physical_origin_gap_is_reported_without_snapping_geometry(self):
        doc,parts=chain(2);parts[1].ConnectorManager.Connectors[0].Origin.X+=.01
        result=capture(doc,parts)
        self.assertEqual([],result['parts'])
        self.assertEqual({'CONNECTED_ORIGIN_GAP'},{d['reason'] for d in result['diagnostics']})
        self.assertEqual(3.01,parts[1].ConnectorManager.Connectors[0].Origin.X)

    def test_two_part_double_connection_is_not_collapsed_into_a_linear_run(self):
        doc=Document();a,b=Part(doc,1,0),Part(doc,2,0)
        for x,y in zip(a.ConnectorManager.Connectors,b.ConnectorManager.Connectors):connect(x,y)
        result=capture(doc,[a,b])
        self.assertEqual([],result['parts'])
        self.assertEqual({'MULTIPLE_PART_CONNECTIONS'},{d['reason'] for d in result['diagnostics']})

    def test_distinct_element_ids_keep_64_bit_identity(self):
        doc=Document();p=Part(doc,2**40,0)
        result=capture(doc,[p]);self.assertEqual(2**40,result['parts'][0]['element_id'])
        self.assertIn(str(2**40),result['parts'][0]['key'])

    def test_hangers_wrong_categories_and_nonfabrication_elements_are_explicitly_skipped(self):
        doc=Document();hanger=Part(doc,1,0);hanger.hanger=True
        wrong=Part(doc,2,0,category=20)
        other=SimpleNamespace(Document=doc,UniqueId='other',Id=ElementId(3))
        result=capture(doc,[hanger,wrong,other])
        self.assertEqual([],result['parts']);self.assertEqual(3,len(result['diagnostics']))
        self.assertEqual({'UNSUPPORTED_SELECTION'},{d['reason'] for d in result['diagnostics']})

    def test_order_duplicates_and_snapshot_serialization_are_stable(self):
        doc,parts=chain();expected=capture(doc,parts)
        self.assertEqual(expected,capture(doc,list(reversed(parts))))
        duplicate=capture(doc,parts+[parts[0]])
        self.assertEqual(expected['parts'],duplicate['parts'])
        self.assertEqual(expected['connections'],duplicate['connections'])
        self.assertEqual(6,duplicate['selected_count'])
        json.dumps(expected)
        self.assertEqual(expected,capture(doc,parts))

    def test_connector_enumeration_order_does_not_flip_snapshot_axes(self):
        doc,parts=chain();expected=capture(doc,parts)
        for part in parts:part.ConnectorManager.Connectors.reverse()
        self.assertEqual(expected,capture(doc,parts))

    def test_service_and_profile_boundaries_use_actual_snapshot_metadata(self):
        for field in ('service','profile'):
            doc,parts=chain(2)
            if field=='service':parts[1].ServiceId=99
            else:
                for connector in parts[1].ConnectorManager.Connectors:connector.Width=4.
            result=capture(doc,parts);analysis=build_runs(result['parts'],result['connections'])
            self.assertEqual([],result['diagnostics'])
            self.assertEqual(2,len(analysis['runs']))
            reason='SERVICE_BOUNDARY' if field=='service' else 'PROFILE_BOUNDARY'
            self.assertTrue(all(reason in reasons for reasons in analysis['boundaries'].values()))

    def test_oval_and_unsupported_connector_types(self):
        doc,parts=chain(1)
        for connector in parts[0].ConnectorManager.Connectors:connector.Shape=3
        self.assertEqual('oval',capture(doc,parts)['parts'][0]['shape'])
        parts[0].ConnectorManager.Connectors[0].ConnectorType=999
        result=capture(doc,parts)
        self.assertEqual([],result['parts'])
        self.assertEqual('UNSUPPORTED_CONNECTOR',result['diagnostics'][0]['reason'])

    def test_invalid_document_identity_and_tolerances_fail_explicitly(self):
        doc,parts=chain(1)
        for tolerance in (0,-1,float('nan'),float('inf')):
            with self.assertRaises(ValueError):capture_selection(doc,parts,API,tolerance)
        with self.assertRaises(ValueError):capture(None,parts)
        doc.IsFamilyDocument=True
        with self.assertRaises(ValueError):capture(doc,parts)
        doc.IsFamilyDocument=False;doc.ProjectInformation=SimpleNamespace(UniqueId='')
        with self.assertRaises(ValueError):capture(doc,parts)


CONFIG = ROOT / 'ROBMEPTOOLS.extension/ROBMEPTOOLS.tab/Hangers.panel/Auto Hanger.pushbutton/config.py'


class DiagnosticLauncherTests(unittest.TestCase):
    def namespace(self, doc, ids):
        output=SimpleNamespace(print_md=Mock(),print_table=Mock())
        namespace={'forms':SimpleNamespace(alert=Mock()),
                   'revit':SimpleNamespace(doc=doc,uidoc=SimpleNamespace(Selection=SimpleNamespace(GetElementIds=lambda:ids))),
                   'script':SimpleNamespace(get_output=lambda:output,get_logger=lambda:SimpleNamespace(exception=Mock())),
                   'capture_selection':lambda d,els:capture(d,els),'build_runs':build_runs}
        tree=ast.parse(CONFIG.read_bytes());tree.body=[n for n in tree.body if isinstance(n,ast.FunctionDef)]
        exec(compile(tree,str(CONFIG),'exec'),namespace)
        return namespace,output

    def test_launcher_renders_topology_without_placement(self):
        doc,parts=chain();ns,out=self.namespace(doc,[p.Id for p in parts]);ns['main']()
        self.assertFalse(ns['forms'].alert.called)
        table=out.print_table.call_args_list[0].kwargs['table_data']
        self.assertEqual([['0, 1, 2, 3, 4','15.000000']],table)
        self.assertTrue(any('no hangers placed' in c.args[0] for c in out.print_md.call_args_list))

    def test_no_document_or_selection_does_not_capture(self):
        for doc in (None,Document()):
            ns,out=self.namespace(doc,[]);ns['capture_selection']=Mock();ns['main']()
            ns['capture_selection'].assert_not_called();ns['forms'].alert.assert_called_once()

    def test_unreadable_selection_does_not_claim_success(self):
        doc,parts=chain(1);ns,out=self.namespace(doc,[parts[0].Id])
        ns['capture_selection']=Mock(side_effect=RuntimeError('host unavailable'));ns['main']()
        out.print_table.assert_not_called()
        self.assertIn('could not read',out.print_md.call_args.args[0])
