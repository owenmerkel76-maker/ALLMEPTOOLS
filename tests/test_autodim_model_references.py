"""Exercise transformed source geometry and real fitting branch references."""
import ast
import math
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock

ENGINE=Path(__file__).resolve().parents[1]/'ROBMEPTOOLS.extension/ROBMEPTOOLS.tab/AutoDim.panel/AutoDim Smart.pushbutton/engines/duct_engine.py'

class XYZ:
    def __init__(self,x,y,z=0):self.X,self.Y,self.Z=x,y,z
    def Normalize(self):
        n=math.sqrt(self.X**2+self.Y**2+self.Z**2)
        return XYZ(self.X/n,self.Y/n,self.Z/n)

class Ref:
    def __init__(self,key,owner=10):self.key,self.ElementId=key,owner
    def ConvertToStableRepresentation(self,doc):return self.key

class Curve:pass
class Line(Curve):
    def __init__(self,a,b,ref=None):
        self.a,self.b,self.Reference=a,b,ref
        self.Direction=XYZ(b.X-a.X,b.Y-a.Y,b.Z-a.Z).Normalize()
        self.Length=math.sqrt((b.X-a.X)**2+(b.Y-a.Y)**2+(b.Z-a.Z)**2)
    def GetEndPoint(self,i):return self.a if i==0 else self.b
    def CreateTransformed(self,t):return Line(t.OfPoint(self.a),t.OfPoint(self.b),self.Reference)
    @staticmethod
    def CreateBound(a,b):return Line(a,b)

class Transform:
    def __init__(self,angle=0,dx=0,dy=0):self.angle,self.dx,self.dy=angle,dx,dy
    def OfVector(self,v):
        c,s=math.cos(self.angle),math.sin(self.angle)
        return XYZ(c*v.X-s*v.Y,s*v.X+c*v.Y,v.Z)
    def OfPoint(self,p):
        v=self.OfVector(p);return XYZ(v.X+self.dx,v.Y+self.dy,v.Z)
    def Multiply(self,t):
        p=self.OfPoint(XYZ(t.dx,t.dy));return Transform(self.angle+t.angle,p.X,p.Y)

class Instance:
    def __init__(self,t,geo):self.Transform,self.geo=t,geo
    def GetSymbolGeometry(self):return self.geo

class Face:
    def __init__(self,origin,normal,ref):
        self.Origin,self.FaceNormal,self.Reference=origin,normal,ref
        self.EdgeLoops=[]
class Solid:
    def __init__(self,faces):self.Faces=Faces(faces)
class Faces(list):
    @property
    def Size(self):return len(self)
class Edge:
    def __init__(self,line):
        self.line=line
        self.Reference=line.Reference
        self.ends=[Ref(line.Reference.key+':endpoint:'+str(i),line.Reference.ElementId) for i in (0,1)] if line.Reference else []
    def AsCurve(self):return self.line
    def GetEndPointReference(self,i):return self.ends[i]


def namespace():
    ns={'math':math,'DB':SimpleNamespace(XYZ=XYZ,Line=Line,Curve=Curve,Edge=Edge,PlanarFace=Face,
                                       Solid=Solid,GeometryInstance=Instance,Transform=SimpleNamespace(Identity=Transform())),
        'doc':object(),'view':SimpleNamespace(Origin=XYZ(0,0)),'Int64':int,
        'STRICT_REF_PARALLEL_DEG':.20,'STRICT_REF_MAX_Z':.0025,
        'FAB_SIDE_MIN_OFFSET_FT':.02,'FAB_MAX_REFERENCE_CANDIDATES':6,
        'CERT_VALUE_TOL_FT':1/96.,'_FAB_REF_CACHE':{},'_STABILITY_STATS':{'direct_refs_rejected':0}}
    for n in ast.parse(ENGINE.read_bytes()).body:
        if not isinstance(n,ast.FunctionDef):continue
        exec(compile(ast.Module(body=[n],type_ignores=[]),str(ENGINE),'exec'),ns)
        aliases={'_fab_reference_candidates':'_fab_reference_candidates_uncached',
                 'fabrication_edge_candidates_toward_grid':'_fab_edge_candidates_unfiltered',
                 'fabrication_center_reference_candidates':'_fab_center_candidates_unfiltered'}
        if n.name in aliases and aliases[n.name]not in ns:ns[aliases[n.name]]=ns[n.name]
    ns['eid_int']=int
    ns['_reference_geometry_options']=lambda *a:None
    ns['is_fabrication_duct_part']=lambda e:e is not None
    return ns

class ModelReferenceTests(unittest.TestCase):
    def setUp(self):
        self.ns=namespace()
        self.ref=Ref('source:edge')
        # Raw symbol geometry runs Y. Model instance rotates it to X at y=5.
        self.symbol=Line(XYZ(.5,-2),XYZ(.5,2),self.ref)
        self.elem=SimpleNamespace(Id=10,get_Geometry=lambda opt:[Instance(Transform(-math.pi/2,10,5),[self.symbol])],
                                  GetGeometryObjectFromReference=lambda ref:self.symbol)
        self.run=Line(XYZ(8,5),XYZ(12,5))
        self.grid={'axis':XYZ(1,0),'origin':XYZ(0,0),'name':'4','element':SimpleNamespace(Id=20),'reference':Ref('grid',20)}

    def candidates(self):return self.ns['_fab_reference_candidates'](self.elem,self.run)

    def test_harvester_preserves_original_reference_and_transforms_direction(self):
        c=self.candidates()[0]
        self.assertIs(self.ref,c['ref'])
        self.assertAlmostEqual(1,c['model_direction'].X)
        self.assertAlmostEqual(0,c['model_direction'].Y)
        self.assertAlmostEqual(4.5,c['witness'].Y)

    def test_rotated_symbol_is_accepted_on_correct_model_grid_axis(self):
        c=self.candidates()[0]
        self.assertFalse(self.ns['_stable_fabrication_reference_to_grid'](self.elem,self.ref,self.grid))
        self.assertTrue(self.ns['_stable_fabrication_reference_to_grid'](self.elem,self.ref,self.grid,c))
        refs=self.ns['fabrication_edge_candidates_toward_grid'](self.elem,self.run,self.grid)
        self.assertEqual(1,len(refs));self.assertIs(self.ref,refs[0][1])

    def test_matching_local_axis_cannot_certify_wrong_model_axis(self):
        c=self.candidates()[0];wrong=dict(self.grid,axis=XYZ(0,1))
        self.assertFalse(self.ns['_stable_fabrication_reference_to_grid'](self.elem,self.ref,wrong,c))

    def test_nested_rotations_compose_before_comparison(self):
        self.elem.get_Geometry=lambda opt:[Instance(Transform(-math.pi/4,10,5),[
            Instance(Transform(-math.pi/4),[self.symbol])])]
        c=self.candidates()[0]
        self.assertAlmostEqual(1,c['model_direction'].X)
        self.assertTrue(self.ns['_stable_fabrication_reference_to_grid'](self.elem,self.ref,self.grid,c))

    def test_face_normal_is_transformed_with_its_instance(self):
        face=Face(XYZ(.5,0),XYZ(1,0),self.ref)
        self.elem.get_Geometry=lambda opt:[Instance(Transform(-math.pi/2,10,5),[Solid([face])])]
        self.elem.GetGeometryObjectFromReference=lambda ref:face
        c=self.candidates()[0]
        self.assertAlmostEqual(-1,c['model_normal'].Y)
        self.assertTrue(self.ns['_stable_fabrication_reference_to_grid'](self.elem,self.ref,self.grid,c))

    def test_slope_still_rejected_after_world_transformation(self):
        c=self.candidates()[0];c['model_direction']=XYZ(1,0,.1)
        self.assertEqual('sloped-source-edge',self.ns['_fabrication_reference_check'](self.elem,self.ref,self.grid,c)[1])

    def test_changed_reference_evidence_cannot_validate_another_edge(self):
        c=self.candidates()[0]
        self.assertEqual('reference-evidence-mismatch',self.ns['_fabrication_reference_check'](self.elem,Ref('other'),self.grid,c)[1])

    def test_another_part_reference_is_not_a_source_reference(self):
        c=self.candidates()[0];c['ref']=Ref('source:edge',11)
        self.assertEqual('reference-owner-mismatch',self.ns['_fabrication_reference_check'](self.elem,c['ref'],self.grid,c)[1])

    def test_missing_transform_proof_is_rejected(self):
        c=self.candidates()[0];c['model_direction']=None
        self.assertEqual('missing-model-geometry-proof',self.ns['_fabrication_reference_check'](self.elem,self.ref,self.grid,c)[1])

    def test_valid_reference_after_first_six_is_not_lost(self):
        cs=self.candidates();good=cs[0];bad=[]
        for i in range(8):
            bad.append(dict(good,ref=Ref('bad'+str(i)),source='bad'+str(i),model_direction=XYZ(0,1)))
        self.ns['_fab_reference_candidates']=lambda *args:bad+[good]
        refs=self.ns['fabrication_edge_candidates_toward_grid'](self.elem,self.run,self.grid)
        self.assertEqual([self.ref],[r[1]for r in refs])

    def test_failed_nested_transform_is_skipped(self):
        broken=Transform();broken.Multiply=mock.Mock(side_effect=RuntimeError('invalid transform'))
        records=[]
        self.ns['_fab_harvest_geometry']([Instance(Transform(),[self.symbol])],broken,'test',XYZ(1,0),XYZ(0,0),XYZ(0,1),records,set())
        self.assertEqual([],records)

    def test_diagnostics_explain_model_axis_rejection(self):
        self.ns['_validated_fabrication_candidates'](self.elem,self.run,dict(self.grid,axis=XYZ(0,1)))
        d=list(self.ns['AUTODIM_REFERENCE_DIAGNOSTICS'].values())[0]
        self.assertEqual('model-edge-not-parallel',d['reason'])
        self.assertAlmostEqual(1,d['model_direction'][0])

    def branch_leg(self):
        return {'point':XYZ(10,5),'axis':XYZ(1,0),'shape':'Rectangular','width':1.,'height':1.,
                'basis_x':XYZ(0,1),'basis_y':XYZ(0,0,1),'branch_id':10,'key':'branch:10'}

    def test_branch_uses_physical_reference_at_connector_edge(self):
        target,mode,cs=self.ns['_branch_source_reference_candidates'](self.elem,self.branch_leg(),self.grid)
        self.assertAlmostEqual(4.5,target.Y);self.assertEqual('branch-edge',mode)
        self.assertEqual([self.ref],[c['ref']for c in cs])

    def test_branch_cannot_borrow_parallel_geometry_at_other_offset(self):
        leg=self.branch_leg();leg['point']=XYZ(10,8)
        target,mode,cs=self.ns['_branch_source_reference_candidates'](self.elem,leg,self.grid)
        self.assertEqual([],cs)

    def test_branch_creation_receives_actual_ref_and_records_source_associativity(self):
        leg=self.branch_leg();target,mode,cs=self.ns['_branch_source_reference_candidates'](self.elem,leg,self.grid)
        doc=SimpleNamespace(Regenerate=mock.Mock(),Delete=mock.Mock())
        create=mock.Mock(return_value=SimpleNamespace(Id=100,TextPosition=XYZ(2,-2),Value=3.5,Curve=SimpleNamespace(Direction=XYZ(0,1))))
        ns=self.ns;ns.update({'doc':doc,'create_dim':create,'_EXISTING_DIRECT_DIM_RECORDS':{},
            '_existing_branch_source_dimension':lambda *args:False,
            'candidate_axis_shifts':lambda *args:[(0,0,False)],
            'make_dimension_line':lambda *args:'dimension-line',
            'score_dimension_candidate':lambda *args:(0,{},(0,0,1,1)),
            '_layout_candidate_rank':lambda *args:0,'hard_collision_count':lambda *args:0,
            'text_mep_collision_count':lambda *args:0,'line_mep_collision_count':lambda *args:0,
            '_certify_created_dimension':lambda *args:(True,'certified',4.5,4.5),
            'adjust_dimension_text':lambda *args:(False,None),'reserve_created_dimension':mock.Mock(),'_created_dimension_text_is_clear':lambda *args:True,
            'MAX_TEXT_MEP_OVERLAPS':0,'MAX_MEP_LINE_CROSSINGS_RESCUE':12,'DIM_MAX_LAYOUT_ATTEMPTS':10,
            '_CREATED_DIM_SOURCE':{},'_CREATED_DIM_GRID':{},'_CREATED_DIM_MODE':{},
            '_CREATED_DIM_BRANCH_KEY':{},'_CREATED_DIM_TARGETS':{}})
        outcome=ns['_place_branch_source_dimension'](self.elem,leg,target,mode,self.grid,cs,set(),None,{'candidates':0})
        self.assertEqual('created',outcome[0])
        self.assertIs(self.ref,create.call_args.args[1])
        self.assertEqual(10,ns['_CREATED_DIM_SOURCE'][100])
        self.assertEqual('branch:10',ns['_CREATED_DIM_BRANCH_KEY'][100])
        doc.Delete.assert_not_called()
        # A matching reference object is insufficient if Revit measures the
        # wrong geometry. Reject and delete instead of claiming coverage.
        ns['_certify_created_dimension']=lambda *args:(False,'value-mismatch',4.5,7)
        outcome=ns['_place_branch_source_dimension'](self.elem,leg,target,mode,self.grid,cs,set(),None,{'candidates':0})
        self.assertEqual('failed',outcome[0])
        doc.Delete.assert_called_once_with(100)
        # Crowded branch text must not result in a dimension even with good refs.
        create.reset_mock();ns['text_mep_collision_count']=lambda *args:1
        outcome=ns['_place_branch_source_dimension'](self.elem,leg,target,mode,self.grid,cs,set(),None,{'candidates':0})
        self.assertEqual('blocked',outcome[0]);create.assert_not_called()

    def test_branch_cannot_extend_a_bounded_edge_to_another_station(self):
        leg=self.branch_leg();leg['point']=XYZ(100,5)
        target,mode,cs=self.ns['_branch_source_reference_candidates'](self.elem,leg,self.grid)
        self.ns['_existing_branch_source_dimension']=lambda *args:False
        self.ns['_layout_candidate_rank']=lambda *args:0
        self.ns['DIM_MAX_LAYOUT_ATTEMPTS']=10
        self.ns['create_dim']=mock.Mock()
        outcome=self.ns['_place_branch_source_dimension'](self.elem,leg,target,mode,self.grid,cs,set(),None,{'candidates':0})
        self.assertEqual('blocked',outcome[0]);self.ns['create_dim'].assert_not_called()

class ExistingBranchReferenceTests(unittest.TestCase):
    def setUp(self):
        import test_autodim_accounting as accounting
        self.accounting=accounting
        f=accounting.AccountingTests();f.setUp();self.__dict__.update(f.__dict__)
        n=next(n for n in ast.parse(ENGINE.read_bytes()).body if isinstance(n,ast.FunctionDef)and n.name=='_existing_branch_source_dimension')
        exec(compile(ast.Module(body=[n],type_ignores=[]),str(ENGINE),'exec'),self.ns)
        self.dim=accounting.Dimension(200,[accounting.Reference(20,'grid:20'),self.rep.reference],value=5)
        self.doc.elements[200]=self.dim

    def register(self):
        return self.ns['_existing_branch_source_dimension'](self.rep,self.accounting.Point(5,5),
            'branch-round-center',self.grid_info,{'ref':self.rep.reference},'branch:10')

    def test_exact_source_branch_reference_is_reused_and_counts_on_rerun(self):
        self.assertTrue(self.register())
        self.assertEqual({'branch:10'},self.ns['_certified_branch_keys'](set()))
        self.assertEqual(set(),self.ns['_CREATED_DIM_IDS'])

    def test_equal_value_helper_never_reuses_for_branch(self):
        self.dim.References.values[1]=self.accounting.Reference(900,'helper:900')
        self.assertFalse(self.register())

    def test_changed_branch_coordinate_cannot_reuse_matching_reference_only(self):
        self.dim.Value=6
        self.assertFalse(self.register())

    def test_overridden_label_cannot_certify_branch(self):
        self.dim.ValueOverride='5 feet'
        self.assertFalse(self.register())

class FabricationCornerTests(unittest.TestCase):
    """The uploaded zero-dimension run had center curves and transverse corners."""
    def setUp(self):
        self.ns=namespace()
        self.center_ref=Ref('part:center')
        self.center=Line(XYZ(0,0,8),XYZ(4,0,8),self.center_ref)
        self.width_edge=Edge(Line(XYZ(2,-.5,8),XYZ(2,.5,8),Ref('part:end:width')))
        self.height_edge=Edge(Line(XYZ(2,-.5,8),XYZ(2,-.5,10),Ref('part:end:height')))
        self.face=Face(XYZ(2,0,8),XYZ(1,0),Ref('part:end:face'))
        self.face.EdgeLoops=[[self.width_edge,self.height_edge]]
        self.geo=[Solid([self.face]),self.center]
        self.elem=SimpleNamespace(Id=10,get_Geometry=lambda opt:self.geo)
        self.run=Line(XYZ(0,0),XYZ(4,0))
        self.grid={'axis':XYZ(1,0),'origin':XYZ(0,-4),'name':'4','element':SimpleNamespace(Id=20),'reference':Ref('grid',20)}

    def candidates(self):return self.ns['_fab_reference_candidates'](self.elem,self.run)

    def test_transverse_edge_corner_is_valid_without_parallel_parent_edge(self):
        c=next(c for c in self.candidates()if c['ref']is self.width_edge.ends[0])
        self.assertAlmostEqual(0,c['model_direction'].X)
        self.assertEqual((True,'verified-source-corner-point'),self.ns['_fabrication_reference_check'](self.elem,c['ref'],self.grid,c))

    def test_vertical_edge_corner_is_valid_without_horizontal_parent_edge(self):
        c=next(c for c in self.candidates()if c['ref']is self.height_edge.ends[0])
        self.assertAlmostEqual(1,c['model_direction'].Z)
        self.assertTrue(self.ns['_fabrication_reference_check'](self.elem,c['ref'],self.grid,c)[0])

    def test_end_cap_fixture_reaches_real_near_side_endpoint_references(self):
        refs=self.ns['fabrication_edge_candidates_toward_grid'](self.elem,self.run,self.grid)
        self.assertTrue(refs,'6.6 returned no edge refs for this geometry')
        self.assertNotIn(self.center_ref,[r[1]for r in refs])
        self.assertTrue(all(abs(r[2].Y+.5)<1e-9 for r in refs))
        self.assertIn(self.width_edge.ends[0],[r[1]for r in refs])

    def test_other_grid_direction_also_keeps_transverse_corner_refs(self):
        t=Transform(math.pi/2)
        self.elem.get_Geometry=lambda opt:[Instance(t,self.geo)]
        self.run=Line(XYZ(0,0),XYZ(0,4))
        self.grid.update(axis=XYZ(0,1),origin=XYZ(4,0),name='B')
        refs=self.ns['fabrication_edge_candidates_toward_grid'](self.elem,self.run,self.grid)
        self.assertTrue(refs)
        self.assertTrue(all(abs(r[2].X-.5)<1e-9 for r in refs))
        self.assertIn(self.width_edge.ends[0],[r[1]for r in refs])

    def test_raw_transverse_edge_itself_is_still_rejected(self):
        c=next(c for c in self.candidates()if c['ref']is self.width_edge.Reference)
        self.assertEqual('model-edge-not-parallel',self.ns['_fabrication_reference_check'](self.elem,c['ref'],self.grid,c)[1])

    def test_corner_requires_proof_from_actual_endpoint_api(self):
        c=next(c for c in self.candidates()if c['ref']is self.width_edge.ends[0]);c['endpoint_index']=None
        self.assertEqual('missing-source-endpoint-proof',self.ns['_fabrication_reference_check'](self.elem,c['ref'],self.grid,c)[1])

    def test_floating_or_wrong_corner_coordinate_is_rejected(self):
        c=next(c for c in self.candidates()if c['ref']is self.width_edge.ends[0]);c['witness']=XYZ(2,-.6,8)
        self.assertEqual('source-endpoint-position-mismatch',self.ns['_fabrication_reference_check'](self.elem,c['ref'],self.grid,c)[1])

    def test_display_prefix_does_not_lose_refs_without_stable_string(self):
        refs=[self.center_ref,self.face.Reference,self.width_edge.Reference,self.height_edge.Reference]+self.width_edge.ends+self.height_edge.ends
        for r in refs:r.ConvertToStableRepresentation=mock.Mock(side_effect=RuntimeError('not available'))
        out=self.ns['fabrication_edge_candidates_toward_grid'](self.elem,self.run,self.grid)
        self.assertTrue(out)
        self.assertIn(self.width_edge.ends[0],[r[1]for r in out])

    def test_missing_stable_identity_does_not_allow_another_reference_object(self):
        c=next(c for c in self.candidates()if c['ref']is self.width_edge.ends[0])
        c['ref'].ConvertToStableRepresentation=mock.Mock(side_effect=RuntimeError('not available'))
        other=Ref('different');other.ConvertToStableRepresentation=mock.Mock(side_effect=RuntimeError('not available'))
        self.assertEqual('reference-evidence-mismatch',self.ns['_fabrication_reference_check'](self.elem,other,self.grid,c)[1])

    def test_transverse_corner_reaches_branch_placement_at_actual_point(self):
        leg={'point':XYZ(2,0,8),'axis':XYZ(1,0),'shape':'Rectangular','width':1.,'height':1.,
             'basis_x':XYZ(0,1),'basis_y':XYZ(0,0,1),'branch_id':10,'key':'branch:corner'}
        target,mode,refs=self.ns['_branch_source_reference_candidates'](self.elem,leg,self.grid)
        self.assertTrue(refs)
        doc=SimpleNamespace(Regenerate=mock.Mock(),Delete=mock.Mock())
        create=mock.Mock(return_value=SimpleNamespace(Id=100,TextPosition=XYZ(2,-2),Value=3.5,Curve=SimpleNamespace(Direction=XYZ(0,1))))
        self.ns.update({'doc':doc,'create_dim':create,
            '_existing_branch_source_dimension':lambda *args:False,
            'candidate_axis_shifts':mock.Mock(side_effect=AssertionError('point must not borrow a parent-line station')),
            'make_dimension_line':lambda *args:'actual-point-to-grid',
            'score_dimension_candidate':lambda *args:(0,{},(0,0,1,1)),
            '_layout_candidate_rank':lambda *args:0,'hard_collision_count':lambda *args:0,
            'text_mep_collision_count':lambda *args:0,'line_mep_collision_count':lambda *args:0,
            '_certify_created_dimension':lambda *args:(True,'certified',3.5,3.5),
            'adjust_dimension_text':lambda *args:(False,None),'reserve_created_dimension':mock.Mock(),'_created_dimension_text_is_clear':lambda *args:True,
            'MAX_TEXT_MEP_OVERLAPS':0,'MAX_MEP_LINE_CROSSINGS_RESCUE':12,'DIM_MAX_LAYOUT_ATTEMPTS':10,
            '_CREATED_DIM_SOURCE':{},'_CREATED_DIM_GRID':{},'_CREATED_DIM_MODE':{},
            '_CREATED_DIM_BRANCH_KEY':{},'_CREATED_DIM_TARGETS':{}})
        status=self.ns['_place_branch_source_dimension'](self.elem,leg,target,mode,self.grid,refs,set(),None,{'candidates':0})
        self.assertEqual('created',status[0])
        self.assertIs(self.width_edge.ends[0],create.call_args.args[1])
        self.assertAlmostEqual(2,self.ns['_CREATED_DIM_TARGETS'][100].X)
        self.assertAlmostEqual(-.5,self.ns['_CREATED_DIM_TARGETS'][100].Y)
        self.ns['candidate_axis_shifts'].assert_not_called()
        doc.Delete.assert_not_called()
