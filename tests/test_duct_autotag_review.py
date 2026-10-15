import ast

import json

import math

import os

import time

import unittest

from pathlib import Path

from types import SimpleNamespace

from unittest import mock

ROOT = Path(__file__).resolve().parents[1]

ENGINE = ROOT / ('ROBMEPTOOLS.extension/ROBMEPTOOLS.tab/AutoTag.panel/'
                 'AutoTag Smart.pushbutton/engines/duct_engine.py')

class ElementId(int):
    InvalidElementId = -1

class Tag:
    def __init__(self, tag_id=100, source_id=10, tag_type=20, text='1/2 CW BOP=8 ft'):
        self.Id = tag_id
        self.source_id = source_id
        self.tag_type = tag_type
        self.IsValidObject = True
        self.IsOrphaned = False
        self.OwnerViewId = 1
        self.TagText = text
        self.HasLeader = True
        self.TagHeadPosition = Point(5, 5)

    def GetTypeId(self):
        return self.tag_type

    def GetTaggedLocalElementIds(self):
        return [self.source_id]

    def ChangeTypeId(self, tag_type):
        self.tag_type = tag_type
        return ElementId.InvalidElementId

class Point:
    def __init__(self, x, y=0, z=0):
        self.X, self.Y, self.Z = x, y, z

    def DistanceTo(self, point):
        return math.sqrt((self.X-point.X)**2 + (self.Y-point.Y)**2 + (self.Z-point.Z)**2)

    def __add__(self, point):
        return Point(self.X+point.X, self.Y+point.Y, self.Z+point.Z)

    def Multiply(self, value):
        return Point(self.X*value, self.Y*value, self.Z*value)

def namespace():
    path = Path(os.environ.get('DUCT_AUTOTAG_ENGINE_PATH', str(ENGINE)))
    tree = ast.parse(path.read_text(encoding='utf-8'))
    tree.body = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    ns = {'math': math, 'System': SimpleNamespace(Int64=int),
          'DB': SimpleNamespace(IndependentTag=Tag, ElementId=ElementId),
          'view': SimpleNamespace(Id=1), 'eid_int': int}
    ns.setdefault('Int64', int)
    exec(compile(tree, str(path), 'exec'), ns)
    ns['eid_int'] = int
    return ns

class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.ns = namespace()
        self.tag = Tag()

    def test_tag_identity_proves_selected_type_source_and_nonempty_text(self):
        self.assertEqual((True, None, [10]), self.ns['_tag_identity_check'](self.tag, 20, 10))

    def test_existing_orphan_wrong_type_view_source_and_empty_tags_do_not_count(self):
        for field, value, expected in [('IsOrphaned', True, 'orphaned-tag'),
                                       ('IsValidObject', False, 'invalid-tag'),
                                       ('tag_type', 21, 'wrong-tag-type'),
                                       ('OwnerViewId', 2, 'wrong-view'),
                                       ('source_id', 11, 'wrong-source'),
                                       ('TagText', '?', 'empty-or-unresolved-tag-text'),
                                       ('TagText', '', 'empty-or-unresolved-tag-text')]:
            with self.subTest(field=field, value=value):
                tag = Tag()
                setattr(tag, field, value)
                valid, reason, _ids = self.ns['_tag_identity_check'](tag, 20, 10)
                self.assertFalse(valid)
                self.assertEqual(expected, reason)

    def test_surviving_accounting_rejects_deleted_and_retargeted_tags(self):
        good = Tag()
        good.HasLeader = False
        wrong = Tag(101, source_id=11)
        self.ns['doc'] = SimpleNamespace(GetElement={100: good, 101: wrong}.get)
        records = [{'tag_id': tag_id, 'target': {'duct': SimpleNamespace(Id=10)},
                    'leader_applied': True, 'leader_mode': 'attached_straight'}
                   for tag_id in (100, 101, 102)]
        survivors, rejected = self.ns['_surviving_tag_records'](records, 20)
        self.assertEqual([100], [record['tag_id'] for record in survivors])
        self.assertFalse(survivors[0]['leader_applied'])
        self.assertEqual(good.TagText, survivors[0]['actual_text'])
        self.assertEqual([(10, 'wrong-source', 101), (10, 'missing-tag', 102)], rejected)

    def test_actual_unfamiliar_bod_text_is_kept_without_numeric_rewriting(self):
        self.tag.TagText = 'BOD=19 feet 2 3/8 inches'
        self.assertTrue(self.ns['_tag_identity_check'](self.tag, 20, 10)[0])
        self.assertEqual('BOD=19 feet 2 3/8 inches', self.tag.TagText)

class CreationTests(unittest.TestCase):
    def setUp(self):
        self.ns = namespace()
        self.created = []
        self.deleted = []
        self.ns['doc'] = SimpleNamespace(Delete=self.deleted.append, GetElement=lambda eid: None)
        self.ns['DB'].Reference = lambda host: host.Id
        self.ns['DB'].TagMode = SimpleNamespace(TM_ADDBY_CATEGORY=1, TM_ADDBY_MULTICATEGORY=2)
        self.host = SimpleNamespace(Id=10)

    def test_rejected_overloads_do_not_leak_wrong_type_tags(self):
        def create(*args):
            tag = Tag(100+len(self.created), tag_type=21)
            tag.ChangeTypeId = mock.Mock(side_effect=RuntimeError('incompatible type'))
            self.created.append(tag)
            return tag
        with mock.patch.object(Tag, 'Create', create=True, new=staticmethod(create)):
            with self.assertRaisesRegex(RuntimeError, 'incompatible type'):
                self.ns['create_raw_tag'](self.host, Point(0), 20, 0)
        self.assertEqual([100, 101, 102], self.deleted)

    def test_type_replacement_is_the_tag_returned_and_verified(self):
        replacement = Tag(200)
        old_tag = Tag(100, tag_type=21)
        old_tag.ChangeTypeId = lambda tag_type: 200
        self.ns['doc'].GetElement = lambda eid: replacement
        create = mock.Mock(side_effect=[RuntimeError('typed overload unavailable'), old_tag])
        with mock.patch.object(Tag, 'Create', create=True, new=staticmethod(create)):
            tag, _ref = self.ns['create_raw_tag'](self.host, Point(0), 20, 0)
        self.assertIs(replacement, tag)

    def test_fatal_regeneration_does_not_retry_or_touch_failed_document(self):
        class RegenerationFailedException(Exception):
            pass
        create = mock.Mock(side_effect=RegenerationFailedException('document corrupt until rollback'))
        with mock.patch.object(Tag, 'Create', create=True, new=staticmethod(create)):
            with self.assertRaises(RegenerationFailedException):
                self.ns['create_raw_tag'](self.host, Point(0), 20, 0)
        self.assertEqual(1, create.call_count)
        self.assertEqual([], self.deleted)

    def test_hidden_or_unsupported_straight_leader_is_not_reported_attached(self):
        class NoLeaderTag:
            @property
            def HasLeader(self):
                return False
            @HasLeader.setter
            def HasLeader(self, value):
                raise RuntimeError('family has no leader')
        self.assertFalse(self.ns['apply_leader'](NoLeaderTag(), None, Point(0), None))

class LayoutReviewTests(unittest.TestCase):
    def setUp(self):
        self.ns = namespace()
        self.layout = (1, Point(.5, .5), None, (.4, .4, .6, .6), True, Point(0), Point(0))
        self.grid = mock.Mock()
        self.grid.rect_hits_kinds.return_value = False

    def test_clean_head_inside_crop_passes(self):
        self.assertTrue(self.ns['_review_layout_text_clear'](self.layout, self.grid, (0, 0, 1, 1)))

    def test_text_collision_is_rejected_even_for_emergency_score(self):
        self.grid.rect_hits_kinds.return_value = True
        emergency = (900000,) + self.layout[1:]
        self.assertFalse(self.ns['_review_layout_text_clear'](emergency, self.grid, None))
        self.grid.rect_hits_kinds.assert_called_with(self.layout[3], {'tag', 'annotation'})

    def test_crop_rejects_partly_outside_head(self):
        self.assertFalse(self.ns['_review_layout_text_clear'](self.layout, self.grid, (0, 0, .5, 1)))

    def test_no_candidate_reports_blocked_without_forced_placement(self):
        for name in ['generate_ranked_layout_pool', 'generate_v6_reuse_layout_candidates',
                     'generate_v9_escape_layout_candidates', 'generate_emergency_layout_candidates']:
            self.ns[name] = mock.Mock(return_value=[])
        self.ns['SMART_V6_ACTIVE'] = True
        forced = mock.Mock()
        self.ns['_deterministic_last_resort'] = forced
        self.assertIsNone(self.ns['choose_layout']({'duct': SimpleNamespace(Id=10)}, self.grid, (1, 1, 1, 1), None))
        forced.assert_not_called()

    def test_diagnostic_distinguishes_existing_missing_and_outside_scope(self):
        self.ns.update({'doc': SimpleNamespace(Title='Review'), 'view': SimpleNamespace(Id=1),
                        '_duct_source_audit': lambda d: {'source_id': d.Id}})
        raw = {i: {'duct': SimpleNamespace(Id=i), 'reasons': {'turn'}} for i in [10, 11, 12, 13]}
        record = {'tag_id': 100, 'target': raw[10], 'actual_text': 'BOD:9 ft',
                  'head': Point(1), 'leader_applied': True, 'head_clearance_verified': True}
        audit = self.ns['_review_run_audit'](raw, [raw[10], raw[12]], [record], 20, {11},
                                            [(12, 'blocked')], {'created': 1, 'missing_source_ids': [12]})
        self.assertEqual({10: 'created-source-type-verified', 11: 'existing-source-type-verified',
                          12: 'missing-required-tag', 13: 'outside-selection'},
                         {s['source_id']: s['status'] for s in audit['sources']})
        self.assertEqual('BOD:9 ft', audit['tags'][0]['text'])
        self.assertEqual('duct-autotag-review-5-all-straights', audit['engine'])
        json.dumps(audit, allow_nan=False)

    def test_family_measurements_do_not_share_different_host_orientations(self):
        self.ns.update({'_TAG_MEASURE_KEY_CACHE': {}, 'duct_shape_and_size': lambda d: ('round', (1,)),
                        'centerline_elevation': lambda d: 10, 'is_fabrication_duct_part': lambda d: False,
                        'horizontal_axis_uv': lambda d: (1, 0) if d.Id == 1 else (0, 1),
                        'duct_direction': lambda d: Point(1, 0, 0), 'duct_line': lambda d: None})
        self.assertNotEqual(self.ns['_tag_measure_key'](SimpleNamespace(Id=1)),
                            self.ns['_tag_measure_key'](SimpleNamespace(Id=2)))

    def test_audit_distinguishes_estimates_and_keeps_failed_bounds_attempts(self):
        self.ns.update({'doc': SimpleNamespace(Title='Review'), 'view': SimpleNamespace(Id=1),
                        '_duct_source_audit': lambda d: {'source_id': d.Id}})
        raw = {i: {'duct': SimpleNamespace(Id=i), 'reasons': {'turn'}} for i in [10, 11]}
        kept = {'tag_id': 100, 'target': raw[10], 'actual_text': 'BOD:9 ft',
                'head_bounds_phase': 'estimated-text-footprint',
                'head_clearance_verified': False, 'estimated_head_clearance_checked': True,
                'head_bounds_diagnostics': [{'status': 'null', 'scope': 'active-view'}]}
        failed = {'tag_id': 101, 'target': raw[11],
                  'head_bounds_diagnostics': [{'status': 'error', 'error': 'getter failed'}]}
        audit = self.ns['_review_run_audit'](raw, list(raw.values()), [kept], 20, set(),
                                            [(11, 'blocked')], {'created': 1, 'missing_source_ids': [11]},
                                            [kept, failed])
        self.assertEqual(0, audit['measured_clearance_count'])
        self.assertEqual(1, audit['estimated_clearance_count'])
        self.assertFalse(audit['tags'][0]['measured_head_clearance_verified'])
        self.assertEqual([100, 101], [entry['tag_id'] for entry in audit['head_bounds_attempts']])
        self.assertEqual('getter failed', audit['head_bounds_attempts'][1]['queries'][0]['error'])
        json.dumps(audit, allow_nan=False)


class TagBoundingBoxTests(unittest.TestCase):
    def setUp(self):
        self.ns = namespace()
        self.tag = Tag()
        self.box = object()
        self.rect = (4.8, 4.9, 5.2, 5.1)
        self.ns['bbox_to_rect'] = lambda box: self.rect if box is self.box else None

    def test_missing_view_bounds_use_actual_model_bounds(self):
        self.tag.get_BoundingBox = mock.Mock(side_effect=[None, self.box])
        self.assertEqual(self.rect, self.ns['element_rect'](self.tag))
        self.assertEqual([mock.call(self.ns['view']), mock.call(None)],
                         self.tag.get_BoundingBox.call_args_list)

    def test_view_bounds_are_preferred_without_model_query(self):
        self.tag.get_BoundingBox = mock.Mock(return_value=self.box)
        self.assertEqual(self.rect, self.ns['element_rect'](self.tag))
        self.tag.get_BoundingBox.assert_called_once_with(self.ns['view'])

    def test_ordinary_view_query_error_can_use_model_bounds(self):
        self.tag.get_BoundingBox = mock.Mock(side_effect=[RuntimeError('view bounds unavailable'), self.box])
        self.assertEqual(self.rect, self.ns['element_rect'](self.tag))

    def test_neither_bounds_available_remains_unmeasurable(self):
        self.tag.get_BoundingBox = mock.Mock(return_value=None)
        self.assertIsNone(self.ns['element_rect'](self.tag))
        self.assertEqual(2, self.tag.get_BoundingBox.call_count)

    def test_model_bounds_do_not_replace_non_tag_visibility_bounds(self):
        duct = SimpleNamespace(get_BoundingBox=mock.Mock(return_value=None))
        self.assertIsNone(self.ns['element_rect'](duct))
        duct.get_BoundingBox.assert_called_once_with(self.ns['view'])

    def test_fatal_query_failure_never_attempts_fallback(self):
        class RegenerationFailedException(Exception):
            pass
        self.tag.get_BoundingBox = mock.Mock(side_effect=RegenerationFailedException('rollback required'))
        with self.assertRaises(RegenerationFailedException):
            self.ns['element_rect'](self.tag)
        self.assertEqual(1, self.tag.get_BoundingBox.call_count)

    def test_indexed_property_recovers_python_getter_failure(self):
        self.tag.get_BoundingBox = mock.Mock(side_effect=RuntimeError('Python getter binding failed'))
        indexer = mock.Mock()
        indexer.__getitem__ = mock.Mock(return_value=self.box)
        self.tag.BoundingBox = indexer
        diagnostics = []
        self.assertEqual(self.rect, self.ns['element_rect'](self.tag, diagnostics))
        self.assertEqual(['error', 'measured'], [entry['status'] for entry in diagnostics])
        self.assertIn('binding failed', diagnostics[0]['error'])

    def test_base_element_accessor_recovers_missing_tag_binding(self):
        self.tag.get_BoundingBox = mock.Mock(return_value=None)
        getter = mock.Mock(return_value=self.box)
        self.ns['DB'].Element = SimpleNamespace(get_BoundingBox=getter)
        self.assertEqual(self.rect, self.ns['element_rect'](self.tag))
        getter.assert_called_once_with(self.tag, self.ns['view'])

    def test_null_and_exception_results_are_retained_for_both_scopes(self):
        self.tag.get_BoundingBox = mock.Mock(return_value=None)
        diagnostics = []
        self.assertIsNone(self.ns['element_rect'](self.tag, diagnostics))
        self.assertEqual(6, len(diagnostics))
        self.assertEqual({'active-view', 'model'}, {entry['scope'] for entry in diagnostics})
        self.assertEqual(2, sum(entry['status'] == 'null' for entry in diagnostics))
        json.dumps(diagnostics, allow_nan=False)

    def test_invalid_zero_size_and_nonfinite_bounds_are_not_certified(self):
        self.tag.get_BoundingBox = mock.Mock(return_value=self.box)
        for rect in [(0, 0, 0, 1), (0, 0, 1, float('nan')), (0, 0, float('inf'), 1)]:
            self.ns['bbox_to_rect'] = lambda box: rect
            self.assertIsNone(self.ns['element_rect'](self.tag))


class GeometryFixture:
    """Annotation bounds exist only after a full commit and view refresh."""
    def __init__(self, ns, tags):
        self.ns, self.tags = ns, tags
        self.modifiable = False
        self.committed = False
        self.refreshed = False
        self.events = []
        self.transactions = []
        self.groups = []
        self.document = SimpleNamespace(GetElement=mock.Mock(side_effect=tags.get),
                                        Delete=mock.Mock(side_effect=lambda eid: tags.pop(eid, None)),
                                        Regenerate=mock.Mock())
        fixture = self

        class Transaction:
            def __init__(self, doc, name):
                self.status = 'uninitialized'
                fixture.transactions.append(self)
            def Start(self):
                if fixture.modifiable:
                    raise RuntimeError('Cannot nest transactions')
                self.status = 'started'
                fixture.modifiable = True
                fixture.committed = fixture.refreshed = False
                fixture.events.append('start')
            def GetStatus(self):
                return self.status
            def Commit(self):
                self.status = 'committed'
                fixture.modifiable = False
                fixture.committed = True
                fixture.events.append('commit')
                return self.status
            def RollBack(self):
                self.status = 'rolledback'
                fixture.modifiable = False
                fixture.events.append('transaction-rollback')

        class Group:
            def __init__(self, doc, name):
                self.status = 'uninitialized'
                fixture.groups.append(self)
            def Start(self):
                if fixture.modifiable:
                    raise RuntimeError('Cannot start group inside transaction')
                self.snapshot = {eid: (tag, tag.TagHeadPosition, tag.HasLeader)
                                 for eid, tag in tags.items()}
                self.status = 'started'
            def GetStatus(self):
                return self.status
            def RollBack(self):
                if fixture.modifiable:
                    raise RuntimeError('Must close transaction before group rollback')
                tags.clear()
                for eid, (tag, head, leader) in self.snapshot.items():
                    tags[eid] = tag
                    tag.TagHeadPosition, tag.HasLeader = head, leader
                self.status = 'rolledback'
                fixture.events.append('group-rollback')
            def Assimilate(self):
                if fixture.modifiable:
                    raise RuntimeError('Must close transaction before group assimilation')
                self.status = 'committed'
                fixture.events.append('assimilate')
                return self.status

        def refresh():
            if fixture.modifiable:
                raise RuntimeError('Refresh called inside transaction')
            fixture.refreshed = True
            fixture.events.append('refresh')

        def bounds(tag, diagnostics=None):
            fixture.events.append('bounds')
            if fixture.modifiable or not fixture.committed or not fixture.refreshed:
                return None
            return (tag.TagHeadPosition.X-.2, tag.TagHeadPosition.Y-.1,
                    tag.TagHeadPosition.X+.2, tag.TagHeadPosition.Y+.1)

        ns['DB'].Transaction = Transaction
        ns['DB'].TransactionGroup = Group
        ns['DB'].TransactionStatus = SimpleNamespace(Started='started', Committed='committed')
        ns.update({'doc': self.document, 'uidoc': SimpleNamespace(RefreshActiveView=refresh),
                   'element_rect': bounds, 'uv_of_point': lambda p: (p.X, p.Y),
                   'paper_to_model': lambda value: value, 'TAG_CLEARANCE_PAPER_IN': 0,
                   'SMART_V8_RESERVE_PAD_PAPER_IN': 0, 'W_TAG': 1, 'W_LEADER': 1,
                   'CAD_EXTREME_BLOCK_THRESHOLD': 1000})


def head_record(tag_id=100, source_id=10):
    return {'tag_id': tag_id, 'anchor': Point(0), 'target': {'duct': SimpleNamespace(Id=source_id)},
            'leader_applied': False, 'rect': (0, 0, .01, .01)}


class RectGrid:
    def __init__(self, ns):
        self.ns = ns
        self.rects = {}

    def remove_source(self, source):
        self.rects.pop(source, None)

    def add_rect(self, kind, rect, weight, source):
        self.rects[source] = rect

    def add_segment(self, *args):
        pass

    def score_rect_components(self, rect, ignore_source_id=None):
        return (sum(self.ns['rect_intersects'](rect, other)
                    for source, other in self.rects.items() if source != ignore_source_id), 0)


class MeasuredHeadTests(unittest.TestCase):
    def setUp(self):
        self.ns = namespace()
        self.actual_element_rect = self.ns['element_rect']
        self.actual_reserve = self.ns['_reserve_record_geometry']
        self.tag = Tag()
        self.fixture = GeometryFixture(self.ns, {100: self.tag})
        self.grid = mock.Mock()
        self.grid.score_rect_components.return_value = (0, 0)
        self.ns['_reserve_record_geometry'] = mock.Mock()

    def verify(self, records, crop=None):
        measured, errors = self.ns['_measure_created_tag_heads'](records)
        return self.ns['_verify_created_tag_head_clearance'](records, self.grid, crop, measured, errors)

    def test_bounds_deferred_until_commit_are_measured_and_tag_survives(self):
        record = head_record()
        survivors, rejected = self.verify([record])
        self.assertEqual([record], survivors)
        self.assertEqual([], rejected)
        self.assertEqual((4.8, 4.9, 5.2, 5.1), record['rect'])
        self.assertEqual(['start', 'commit', 'refresh', 'bounds', 'group-rollback'], self.fixture.events)
        self.assertTrue(record['head_clearance_verified'])
        self.assertEqual('committed-transaction', record['head_bounds_phase'])
        self.assertEqual(5, self.tag.TagHeadPosition.X)
        self.assertTrue(self.tag.HasLeader)
        self.grid.score_rect_components.assert_called_once_with(record['rect'], ignore_source_id=10)
        self.fixture.document.Delete.assert_not_called()

    def test_final_clearance_keeps_tag_with_measured_model_bounds(self):
        record = head_record()
        self.tag.get_BoundingBox = mock.Mock(side_effect=[None, 'model-box'])
        self.ns['element_rect'] = self.actual_element_rect
        self.ns['bbox_to_rect'] = lambda box: (-.2, -.1, .2, .1) if box == 'model-box' else None
        survivors, rejected = self.verify([record])
        self.assertEqual([record], survivors)
        self.assertEqual([], rejected)
        self.assertEqual((4.8, 4.9, 5.2, 5.1), record['rect'])
        self.assertEqual([mock.call(self.ns['view']), mock.call(None)],
                         self.tag.get_BoundingBox.call_args_list)

    def test_failed_final_regeneration_rolls_back_before_any_more_model_reads(self):
        class RegenerationFailedException(Exception):
            pass
        self.fixture.document.Regenerate.side_effect = RegenerationFailedException('failed')
        self.ns['element_rect'] = mock.Mock()
        with self.assertRaises(RegenerationFailedException):
            self.ns['_measure_created_tag_heads']([head_record()])
        self.assertEqual(['start', 'transaction-rollback', 'group-rollback'], self.fixture.events)
        self.ns['element_rect'].assert_not_called()
        self.assertEqual(1, self.fixture.document.GetElement.call_count)
        self.grid.remove_source.assert_not_called()
        self.fixture.document.Delete.assert_not_called()
        self.assertTrue(self.tag.HasLeader)
        self.assertEqual(5, self.tag.TagHeadPosition.X)

    def test_missing_family_bbox_keeps_source_verified_tag_with_checked_estimate(self):
        self.ns['element_rect'] = lambda tag, diagnostics=None: None
        record = head_record()
        survivors, rejected = self.verify([record])
        self.assertEqual([record], survivors)
        self.assertEqual([], rejected)
        self.assertFalse(record['head_clearance_verified'])
        self.assertTrue(record['estimated_head_clearance_checked'])
        self.assertEqual('estimated-text-footprint', record['head_bounds_phase'])
        self.fixture.document.Delete.assert_not_called()
        self.assertTrue(self.tag.HasLeader)

    def test_all_106_missing_boxes_do_not_erase_readable_nonoverlapping_tags(self):
        self.fixture.tags.clear()
        records = []
        for index in range(106):
            tag_id, source_id = 100 + index, 1000 + index
            tag = Tag(tag_id, source_id)
            tag.HasLeader = False
            tag.TagHeadPosition = Point(index * 10, 5)
            self.fixture.tags[tag_id] = tag
            record = head_record(tag_id, source_id)
            record['rect'] = (index * 10 - .3, 4.9, index * 10 + .3, 5.1)
            record['tag_type_id'] = 20
            records.append(record)
        self.ns['element_rect'] = lambda tag, diagnostics=None: None
        self.ns['_reserve_record_geometry'] = self.actual_reserve
        self.grid = RectGrid(self.ns)
        survivors, rejected = self.verify(records)
        self.assertEqual(106, len(survivors))
        self.assertEqual([], rejected)
        self.assertEqual(106, sum(r['estimated_head_clearance_checked'] for r in survivors))
        self.assertFalse(any(r['head_clearance_verified'] for r in survivors))
        self.fixture.document.Delete.assert_not_called()

    def test_missing_box_fallback_still_rejects_overlapping_heads(self):
        self.fixture.tags[101] = Tag(101, 11)
        self.fixture.tags[101].TagHeadPosition = Point(5.15, 5)
        self.ns['element_rect'] = lambda tag, diagnostics=None: None
        self.ns['_reserve_record_geometry'] = self.actual_reserve
        self.grid = RectGrid(self.ns)
        survivors, rejected = self.verify([head_record(), head_record(101, 11)])
        self.assertEqual([100], [r['tag_id'] for r in survivors])
        self.assertEqual([(11, 'Estimated tag family head overlaps protected geometry.')], rejected)
        self.assertFalse(survivors[0]['head_clearance_verified'])

    def test_missing_box_fallback_rejects_crop_and_protected_geometry(self):
        self.ns['element_rect'] = lambda tag, diagnostics=None: None
        survivors, rejected = self.verify([head_record()], (0, 0, 5, 5))
        self.assertEqual([], survivors)
        self.assertEqual('Estimated tag head extends outside the crop.', rejected[0][1])
        self.fixture.tags[100] = self.tag
        self.grid.score_rect_components.return_value = (1, 0)
        survivors, rejected = self.verify([head_record()])
        self.assertEqual([], survivors)
        self.assertEqual('Estimated tag family head overlaps protected geometry.', rejected[0][1])

    def test_missing_box_fallback_never_accepts_wrong_source_type_or_unreadable_text(self):
        self.ns['element_rect'] = lambda tag, diagnostics=None: None
        for field, value, reason in [('source_id', 11, 'wrong-source'),
                                     ('tag_type', 21, 'wrong-tag-type'),
                                     ('TagText', '?', 'empty-or-unresolved-tag-text')]:
            tag = Tag()
            setattr(tag, field, value)
            self.fixture.tags[100] = tag
            record = head_record()
            record['tag_type_id'] = 20
            survivors, rejected = self.verify([record])
            self.assertEqual([], survivors)
            self.assertIn(reason, rejected[0][1])

    def test_estimate_uses_committed_head_and_cannot_shrink_planned_footprint(self):
        self.ns['element_rect'] = lambda tag, diagnostics=None: None
        record = head_record()
        record['head'] = Point(100, 100)
        record['rect'] = (3, 3, 7, 7)
        survivors, rejected = self.verify([record])
        self.assertEqual([record], survivors)
        self.assertEqual([], rejected)
        self.assertEqual((3, 3, 7, 7), record['rect'])
        self.assertEqual((5, 5), (record['head'].X, record['head'].Y))

    def test_unmeasured_record_cannot_use_estimated_layout_as_verified(self):
        survivors, rejected = self.ns['_verify_created_tag_head_clearance'](
            [head_record()], self.grid, None, {}, {})
        self.assertEqual([], survivors)
        self.assertEqual([(10, 'No committed tag family measurement was recorded.')], rejected)
        self.fixture.document.Delete.assert_called_once_with(100)

    def test_committed_head_outside_crop_is_removed(self):
        survivors, rejected = self.verify([head_record()], (0, 0, 5, 5))
        self.assertEqual([], survivors)
        self.assertEqual([(10, 'Actual tag head extends outside the crop.')], rejected)

    def test_empty_batch_never_starts_probe_transactions(self):
        self.assertEqual(({}, {}), self.ns['_measure_created_tag_heads']([]))
        self.assertEqual([], self.fixture.transactions)
        self.assertEqual([], self.fixture.groups)

    def test_noncommitted_probe_never_reads_bounds(self):
        transaction = SimpleNamespace(Start=mock.Mock(), Commit=mock.Mock(return_value='rolledback'),
                                      GetStatus=lambda: 'rolledback')
        self.ns['DB'].Transaction = lambda doc, name: transaction
        self.ns['element_rect'] = mock.Mock()
        with self.assertRaisesRegex(RuntimeError, 'did not commit'):
            self.ns['_measure_created_tag_heads']([head_record()])
        self.ns['element_rect'].assert_not_called()
        self.assertEqual('rolledback', self.fixture.groups[0].status)

    def test_fatal_probe_error_rolls_back_committed_batch_and_preserves_existing_tags(self):
        class RegenerationFailedException(Exception):
            pass
        outer = self.ns['DB'].TransactionGroup(self.fixture.document, 'AutoTag batch')
        outer.Start()
        placement = self.ns['DB'].Transaction(self.fixture.document, 'Place tags')
        placement.Start()
        new_tag = Tag(101, 11)
        self.fixture.tags[101] = new_tag
        self.fixture.document.Regenerate.side_effect = RegenerationFailedException('failed')
        with self.assertRaises(RegenerationFailedException):
            self.ns['_finish_created_tag_batch'](placement, outer, [head_record(101, 11)], self.grid, None)
        self.assertEqual({100: self.tag}, self.fixture.tags)
        self.assertEqual('rolledback', outer.status)
        self.assertTrue(self.tag.HasLeader)

    def test_cleanup_failure_rolls_back_committed_batch(self):
        outer = self.ns['DB'].TransactionGroup(self.fixture.document, 'AutoTag batch')
        outer.Start()
        placement = self.ns['DB'].Transaction(self.fixture.document, 'Place tags')
        placement.Start()
        self.fixture.tags[101] = Tag(101, 11)
        self.fixture.document.Delete.side_effect = RuntimeError('delete failed')
        with self.assertRaisesRegex(RuntimeError, 'delete failed'):
            self.ns['_finish_created_tag_batch'](
                placement, outer, [head_record(101, 11)], self.grid, (0, 0, 1, 1))
        self.assertEqual({100: self.tag}, self.fixture.tags)
        self.assertEqual('rolledback', outer.status)
        self.assertFalse(self.fixture.modifiable)

    def test_successful_batch_assimilates_once_and_keeps_original_head_and_leader(self):
        outer = self.ns['DB'].TransactionGroup(self.fixture.document, 'AutoTag batch')
        outer.Start()
        placement = self.ns['DB'].Transaction(self.fixture.document, 'Place tags')
        placement.Start()
        new_tag = Tag(101, 11)
        self.fixture.tags[101] = new_tag
        survivors, rejected = self.ns['_finish_created_tag_batch'](
            placement, outer, [head_record(101, 11)], self.grid, None)
        self.assertEqual([101], [record['tag_id'] for record in survivors])
        self.assertEqual([], rejected)
        self.assertEqual('committed', outer.status)
        self.assertEqual(1, self.fixture.events.count('assimilate'))
        self.assertEqual(5, new_tag.TagHeadPosition.X)
        self.assertTrue(new_tag.HasLeader)
        self.assertEqual({100: self.tag, 101: new_tag}, self.fixture.tags)

    def test_zero_survivors_roll_back_the_whole_batch(self):
        outer = self.ns['DB'].TransactionGroup(self.fixture.document, 'AutoTag batch')
        outer.Start()
        placement = self.ns['DB'].Transaction(self.fixture.document, 'Place tags')
        placement.Start()
        self.fixture.tags[101] = Tag(101, 11)
        self.ns['element_rect'] = lambda tag, diagnostics=None: None
        self.fixture.tags[101].TagText = '?'
        survivors, rejected = self.ns['_finish_created_tag_batch'](
            placement, outer, [head_record(101, 11)], self.grid, None)
        self.assertEqual([], survivors)
        self.assertEqual(11, rejected[0][0])
        self.assertEqual('rolledback', outer.status)
        self.assertNotIn('assimilate', self.fixture.events)
        self.assertEqual({100: self.tag}, self.fixture.tags)

    def test_real_family_extents_prune_newest_overlapping_head_and_restore_tag_state(self):
        self.fixture.tags[101] = Tag(101, 11)
        self.fixture.tags[101].TagHeadPosition = Point(5.15, 5)
        second_tag = self.fixture.tags[101]
        ns = self.ns
        class Grid:
            def __init__(self):
                self.rects = {}
            def remove_source(self, source):
                self.rects.pop(source, None)
            def add_rect(self, kind, rect, weight, source):
                self.rects[source] = rect
            def add_segment(self, *args):
                pass
            def score_rect_components(self, rect, ignore_source_id=None):
                return (sum(ns['rect_intersects'](rect, other) for source, other in self.rects.items()
                            if source != ignore_source_id), 0)
        self.grid = Grid()
        self.ns['_reserve_record_geometry'] = self.actual_reserve
        records = [head_record(100, 10), head_record(101, 11)]
        survivors, rejected = self.verify(records)
        self.assertEqual([100], [record['tag_id'] for record in survivors])
        self.fixture.document.Delete.assert_called_once_with(101)
        self.assertEqual(11, rejected[0][0])
        self.assertEqual(5, self.tag.TagHeadPosition.X)
        self.assertEqual(5.15, second_tag.TagHeadPosition.X)
        self.assertTrue(self.tag.HasLeader)
        self.fixture.document.Regenerate.assert_called_once()


class CommittedSizeProbeTests(unittest.TestCase):
    def test_layout_metrics_read_committed_bounds_and_do_not_leak_probe_tags(self):
        ns = namespace()
        fixture = GeometryFixture(ns, {})
        ns['_tag_measure_key'] = lambda duct: duct.Id
        ns['_fallback_tag_metrics'] = lambda sample: (1, 1, 1, 1)
        ns['duct_line'] = lambda duct: SimpleNamespace(Evaluate=lambda *args: Point(0))
        ns['TAG_SIZE_SAFETY_PAPER_IN'] = 0
        def create(duct, point, *args):
            tag = Tag()
            tag.TagHeadPosition = point
            fixture.tags[100] = tag
            return tag, None
        ns['create_raw_tag'] = create
        cache, fallback = ns['build_tag_size_cache']([{'duct': SimpleNamespace(Id=10)}], 20, 0, None)
        self.assertEqual((.2, .2, .1, .1), cache[10])
        self.assertEqual({}, fixture.tags)
        self.assertEqual(['start', 'commit', 'refresh', 'bounds', 'group-rollback'], fixture.events)

    def test_empty_targets_do_not_start_transactions(self):
        ns = namespace()
        fixture = GeometryFixture(ns, {})
        ns['_fallback_tag_metrics'] = lambda sample: (1, 1, 1, 1)
        self.assertEqual(({}, (1, 1, 1, 1)), ns['build_tag_size_cache']([], 20, 0, None))
        self.assertEqual([], fixture.transactions)

    def test_missing_size_probe_bounds_enlarge_planning_from_actual_text(self):
        ns = namespace()
        fixture = GeometryFixture(ns, {})
        ns.update({'_tag_measure_key': lambda duct: duct.Id,
                   '_fallback_tag_metrics': lambda sample: (.3, .3, .09, .09),
                   'duct_line': lambda duct: SimpleNamespace(Evaluate=lambda *args: Point(0)),
                   'TAG_SIZE_SAFETY_PAPER_IN': .035,
                   'element_rect': lambda tag, diagnostics=None: None})
        def create(duct, point, *args):
            tag = Tag(text='24 x 16\nBOD:10 ft 8 in')
            tag.TagHeadPosition = point
            fixture.tags[100] = tag
            return tag, None
        ns['create_raw_tag'] = create
        cache, fallback = ns['build_tag_size_cache']([{'duct': SimpleNamespace(Id=10)}], 20, 0, None)
        self.assertGreater(cache[10][0], fallback[0])
        self.assertGreater(cache[10][2], fallback[2])
        self.assertEqual({}, fixture.tags)


class EstimatedMetricTests(unittest.TestCase):
    def setUp(self):
        self.ns = namespace()
        self.ns['paper_to_model'] = lambda value: value

    def test_long_multiline_and_rotated_text_receive_larger_estimates(self):
        tag = Tag(text='8 x 8')
        short = self.ns['_estimated_tag_metrics'](tag)
        tag.TagText = '24 x 16\nBOD:10 ft 8 in'
        larger = self.ns['_estimated_tag_metrics'](tag)
        self.assertGreater(larger[0], short[0])
        self.assertGreater(larger[2], short[2])
        tag.RotationAngle = math.pi / 2
        rotated = self.ns['_estimated_tag_metrics'](tag)
        self.assertAlmostEqual(larger[0], rotated[2])
        self.assertAlmostEqual(larger[2], rotated[0])

    def test_exposed_larger_type_font_and_width_scale_enlarge_estimate(self):
        tag = Tag(text='BOD:10 ft 8 in')
        normal = self.ns['_estimated_tag_metrics'](tag)
        self.ns['DB'].BuiltInParameter = SimpleNamespace(TEXT_SIZE='size', TEXT_WIDTH_SCALE='width')
        values = {'size': .25 / 12, 'width': 1.5}
        symbol = SimpleNamespace(get_Parameter=lambda key:
                                 SimpleNamespace(HasValue=True, AsDouble=lambda: values[key]))
        self.ns['doc'] = SimpleNamespace(GetElement=lambda eid: symbol)
        larger = self.ns['_estimated_tag_metrics'](tag)
        self.assertGreater(larger[0], normal[0] * 2)
        self.assertGreater(larger[2], normal[2])

    def test_unresolved_text_has_no_usable_estimate(self):
        for text in ['', ' ', '?']:
            self.assertIsNone(self.ns['_estimated_tag_metrics'](Tag(text=text)))
