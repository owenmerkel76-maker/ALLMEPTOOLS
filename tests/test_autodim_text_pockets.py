"""Human-like text pockets must clear the source duct without fake geometry."""
from types import SimpleNamespace
import unittest
from unittest import mock
from test_autodim_layout import functions, XYZ

class Obstacle:
    def __init__(self):self.calls=[]
    def score_rect(self,r,ignore_source_ids):
        self.calls.append(set(ignore_source_ids))
        # Source duct occupies the entire short dimension string.
        overlap=not(r[2]<-.2 or r[0]>1.2 or r[3]<-.1 or r[1]>.1)
        hit=overlap and 10 not in ignore_source_ids
        return (1000 if hit else 0,{'duct':1}if hit else {})
    def score_segment(self,*args,**kw):return 0,{}


def ns():
    n=functions();n.update({'_RUN_MEMBER_IDS':{10:{10}},
        'HARD_COLLISION_KINDS':('dimension_text','tag','annotation'),
        'DIM_TEXT_POCKET_FRACTIONS':[.5,.4,.6,.3,.7,.2,.8,.1,.9],
        'DIM_TEXT_POCKET_PAPER_OFFSETS':[.18,-.18,.34,-.34,.52,-.52,.72,-.72],
        'DIM_TEXT_POCKET_MOVE_PENALTY':35,'MAX_TEXT_MEP_OVERLAPS':0,
        'PREFERRED_MEP_LINE_CROSSINGS':2,'MEP_CROSSING_EXTRA_PENALTY':9000,
        'MEP_CROSSING_QUADRATIC_PENALTY':2600,'DIM_SHIFT_PENALTY_PER_PAPER_IN':1})
    return n

class TextPocketTests(unittest.TestCase):
    def test_short_string_gets_a_pocket_beyond_its_witnesses(self):
        n=ns();g=Obstacle()
        p=n['_best_dimension_text_pocket'](g,XYZ(0,0),XYZ(1,0),10)
        self.assertEqual((0,0),p[:2])
        self.assertTrue(p[4].X<0 or p[4].X>1)
        self.assertTrue(all(10 not in ignored for ignored in g.calls))

    def test_candidate_scoring_does_not_hide_text_overlap_on_own_duct(self):
        n=ns();g=Obstacle()
        score,hits,r=n['score_dimension_candidate'](g,XYZ(0,0),XYZ(1,0),10,0)
        self.assertEqual(0,hits['_text_mep'])
        self.assertTrue(hits['_text_pocket_moved'])
        self.assertTrue(hits['_planned_text_point'].X<0 or hits['_planned_text_point'].X>1)
        self.assertTrue(all(not ignored for ignored in g.calls))

    def test_tags_are_not_sacrificed_to_clear_the_source(self):
        n=ns();g=Obstacle();original=g.score_rect
        def score(r,ignore_source_ids):
            cost,hits=original(r,ignore_source_ids)
            if not hits:hits={'tag':1};cost=500
            return cost,hits
        g.score_rect=score
        p=n['_best_dimension_text_pocket'](g,XYZ(0,0),XYZ(1,0),10)
        self.assertEqual((0,1),p[:2]) # remains blocked rather than covering a tag

    def test_postcreation_check_uses_actual_position_and_includes_own_duct(self):
        n=ns();dim=SimpleNamespace(Id=100,Value=1.,TextPosition=XYZ(.5,0),
                                 Curve=SimpleNamespace(Direction=XYZ(1,0)))
        g=Obstacle()
        self.assertFalse(n['_created_dimension_text_is_clear'](dim,g))
        self.assertEqual({100},g.calls[-1])
        dim.TextPosition=XYZ(-2,0)
        self.assertTrue(n['_created_dimension_text_is_clear'](dim,g))

    def test_unavailable_actual_text_position_cannot_claim_clearance(self):
        n=ns();dim=SimpleNamespace(Id=100,Value=1.,TextPosition=None)
        self.assertFalse(n['_created_dimension_text_is_clear'](dim,Obstacle()))

    def test_enabled_annotation_crop_keeps_external_text_inside_offsets(self):
        n=ns();n['DB'].BuiltInParameter=SimpleNamespace(VIEWER_ANNOTATION_CROP_ACTIVE='crop')
        n['view']=SimpleNamespace(CropBoxActive=True,Origin=XYZ(0,0),
           get_Parameter=lambda p:SimpleNamespace(AsInteger=lambda:1),
           CropBox=SimpleNamespace(Min=XYZ(-2,-2),Max=XYZ(2,2),Transform=SimpleNamespace(
               Inverse=SimpleNamespace(OfPoint=lambda p:p))),
           GetCropRegionShapeManager=lambda:SimpleNamespace(LeftAnnotationCropOffset=1.,RightAnnotationCropOffset=2.,
               BottomAnnotationCropOffset=.5,TopAnnotationCropOffset=.5))
        self.assertTrue(n['_text_bounds_visible']((-2.9,-2.4,-2.4,2.4)))
        self.assertFalse(n['_text_bounds_visible']((3.9,0,4.1,1)))

    def test_disabled_crop_does_not_artificially_block_external_labels(self):
        n=ns();n['view']=SimpleNamespace(CropBoxActive=False)
        self.assertTrue(n['_text_bounds_visible']((100,100,110,110)))

class TextMetricTests(unittest.TestCase):
    def fixture(self):
        n=ns()
        params={'size':SimpleNamespace(AsDouble=lambda:.125/12),
                'font':SimpleNamespace(AsString=lambda:'Arial'),
                'width':SimpleNamespace(AsDouble=lambda:1.)}
        typ=SimpleNamespace(get_Parameter=lambda key:params.get(key),
                            GetUnitsFormatOptions=lambda:SimpleNamespace(UseDefault=True))
        n['doc']=SimpleNamespace(GetDefaultElementTypeId=lambda group:22,GetElement=lambda eid:typ,
                                 GetUnits=lambda:'project-units')
        n['DB'].ElementTypeGroup=SimpleNamespace(LinearDimensionType='linear')
        n['DB'].BuiltInParameter=SimpleNamespace(TEXT_SIZE='size',TEXT_FONT='font',TEXT_WIDTH_SCALE='width')
        n['DB'].SpecTypeId=SimpleNamespace(Length='length')
        fmt=mock.Mock(side_effect=lambda units,spec,v,editing,*opts:'1\'-0"'if v<2 else'12\'-4 7/8"')
        n['DB'].UnitFormatUtils=SimpleNamespace(Format=fmt)
        return n,params,fmt,typ

    def test_style_font_size_and_formatted_value_drive_bounds(self):
        n,p,fmt,typ=self.fixture()
        short=n['_dimension_text_size'](1.);long=n['_dimension_text_size'](12.)
        self.assertGreater(long[0],short[0])
        self.assertAlmostEqual(.125,n['_dimension_text_profile']()['size_in'])
        self.assertLess(long[0],1.08) # old fixed full width before halo
        self.assertTrue(n['AUTODIM_TEXT_METRICS'])

    def test_repeated_candidate_value_reuses_format_and_font_measurement(self):
        n,p,fmt,typ=self.fixture()
        first=n['_dimension_text_size'](1.)
        self.assertEqual(first,n['_dimension_text_size'](1.+1e-10))
        fmt.assert_called_once()

    def test_project_unit_failure_uses_old_conservative_bounds(self):
        n,p,fmt,typ=self.fixture();fmt.side_effect=RuntimeError('units unavailable')
        self.assertIsNone(n['_dimension_text_size'](1.))
        box=n['_text_rect_at_point'](XYZ(0,0),XYZ(1,0),1.)
        self.assertAlmostEqual(1.2,box[2]-box[0])

    def test_dimension_style_unit_override_is_passed_to_formatter(self):
        n,p,fmt,typ=self.fixture();options=SimpleNamespace(UseDefault=False)
        typ.GetUnitsFormatOptions=lambda:options
        class ValueOptions:
            def SetFormatOptions(self,x):self.options=x
        n['DB'].FormatValueOptions=ValueOptions
        n['_dimension_text_size'](1.)
        self.assertIs(options,fmt.call_args.args[4].options)

    def test_invalid_text_size_does_not_reduce_clearance(self):
        n,p,fmt,typ=self.fixture();p['size'].AsDouble=lambda:0
        self.assertIsNone(n['_dimension_text_size'](1.))
        fmt.assert_not_called()
