"""Behavior regressions for shipped Pipe AutoTag functions, without Revit.

AST extraction uses the real engine code; the mocks represent only the API
surfaces involved in each invariant. These are not Revit integration tests.
"""
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
                 'AutoTag Smart.pushbutton/engines/pipe_engine.py')


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
    path = Path(os.environ.get('PIPE_AUTOTAG_ENGINE_PATH', str(ENGINE)))
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

    def test_actual_unfamiliar_bop_text_is_kept_without_numeric_rewriting(self):
        self.tag.TagText = 'BOP=19 feet 2 3/8 inches'
        self.assertTrue(self.ns['_tag_identity_check'](self.tag, 20, 10)[0])
        self.assertEqual('BOP=19 feet 2 3/8 inches', self.tag.TagText)


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


class DensityTests(unittest.TestCase):
    def setUp(self):
        self.ns = namespace()
        self.ns['_straight_is_local_fixture_tail'] = lambda host: True

    def test_fixture_tail_suppression_preserves_changed_values_and_endcaps(self):
        targets = {index: {'duct': SimpleNamespace(Id=index), 'reasons': set(reasons)}
                   for index, reasons in enumerate([['turn'], ['branch'], ['size'], ['elevation'],
                                                    ['shape'], ['endcap'], ['turn', 'size']], 1)}
        self.assertEqual(2, self.ns['suppress_fixture_tail_bop_targets'](targets))
        self.assertEqual({3, 4, 5, 6, 7}, set(targets))

    def test_local_density_does_not_collapse_transitively_across_long_run(self):
        targets = {index: {'duct': SimpleNamespace(Id=index), 'reasons': {'turn'},
                           'event_points': []} for index in (1, 2, 3, 4)}
        links = {1: [2], 2: [1, 3], 3: [2, 4], 4: [3]}
        self.ns.update({'SMART_HUMAN_LOCAL_TURN_CONSOLIDATION': True,
                        'HUMAN_LOCAL_TURN_MAX_SPAN_FT': 14,
                        '_human_turn_state_key': lambda host: ('CW', 'round', .5, 8),
                        '_human_target_midpoint': lambda host: Point((host.Id-1)*10),
                        '_human_turn_keep_rank': lambda target: (target['duct'].Id,),
                        'first_end_connectors': lambda host: [None],
                        'walk_from_duct_end': lambda host, connector: [
                            (targets[n]['duct'], None, False) for n in links[host.Id]]})
        self.assertEqual(2, self.ns['suppress_redundant_human_turn_targets'](targets))
        self.assertEqual({1, 3}, set(targets))

    def test_different_state_and_vertical_transition_never_share_callout(self):
        for had_nonhorizontal, same_state in ((True, True), (False, False)):
            with self.subTest(vertical=had_nonhorizontal, same_state=same_state):
                targets = {index: {'duct': SimpleNamespace(Id=index), 'reasons': {'turn'},
                                   'event_points': []} for index in (1, 2)}
                self.ns.update({'SMART_HUMAN_LOCAL_TURN_CONSOLIDATION': True,
                                'HUMAN_LOCAL_TURN_MAX_SPAN_FT': 14,
                                '_human_turn_state_key': lambda host: 1 if same_state else host.Id,
                                '_human_target_midpoint': lambda host: Point(host.Id),
                                '_human_turn_keep_rank': lambda target: (target['duct'].Id,),
                                'first_end_connectors': lambda host: [None],
                                'walk_from_duct_end': lambda host, connector: [
                                    (targets[3-host.Id]['duct'], None, had_nonhorizontal)]})
                self.assertEqual(0, self.ns['suppress_redundant_human_turn_targets'](targets))


class CollisionTests(unittest.TestCase):
    def setUp(self):
        self.ns = namespace()
        self.ns.update({'CAD_EXTREME_BLOCK_THRESHOLD': 1000,
                        'SMART_BRIDGE_MEP_MAX_SCORE': 2000,
                        'MAX_LEADER_TOTAL_PAPER_IN': .92,
                        'uv_of_point': lambda point: (point.X, point.Y),
                        'leader_length_paper': lambda a, b: math.hypot(a[0]-b[0], a[1]-b[1])})
        self.target = {'duct': SimpleNamespace(Id=10)}
        self.layout = (1, Point(.5, .5), None, (.4, .4, .6, .6), True,
                       Point(.8, .5), Point(.6, .5))
        self.grid = mock.Mock()
        self.grid.score_rect_components.return_value = (0, 0)
        self.grid.score_segment_detail.return_value = {'blocking': 0, 'mep': 0}
        self.crop = (0, 0, 1, 1)

    def test_clean_local_layout_is_accepted(self):
        self.assertTrue(self.ns['_layout_is_safe'](self.target, self.layout, self.grid, self.crop))

    def test_emergency_cannot_force_text_or_mep_head_overlap(self):
        self.grid.score_rect_components.return_value = (1, 0)
        self.assertFalse(self.ns['_layout_is_safe'](self.target, self.layout, self.grid, self.crop))

    def test_crop_and_neighbor_text_leader_crossing_are_hard_failures(self):
        self.assertFalse(self.ns['_layout_is_safe'](self.target, self.layout, self.grid, (0, 0, .3, .3)))
        self.grid.score_segment_detail.return_value = {'blocking': 1, 'mep': 0}
        self.assertFalse(self.ns['_layout_is_safe'](self.target, self.layout, self.grid, self.crop))

    def test_inline_checks_ignore_only_the_actual_host(self):
        inline = list(self.layout)
        inline[4] = False
        self.assertTrue(self.ns['_layout_is_safe'](self.target, tuple(inline), self.grid, self.crop))
        self.grid.score_rect_components.assert_called_with(inline[3], ignore_source_id=10)

    def test_forced_fallback_without_collision_database_is_unavailable(self):
        self.assertIsNone(self.ns['_deterministic_last_resort'](self.target, (1, 1, 1, 1), self.crop))

    def test_emergency_early_stop_counts_only_safe_routes_and_reaches_other_side(self):
        self.ns.update({'SMART_V6_ACTIVE': True, 'SMART_V3_ACTIVE': True,
                        'SMART_STRAIGHT_FIRST': True, 'SMART_ALLOW_DOGLEGS_WHEN_STRAIGHT': False,
                        'SMART_ANCHOR_LIMIT': 1, 'EMERGENCY_HARD_WEIGHT': 18,
                        'EMERGENCY_MAX_TOTAL_PAPER_IN': .68, 'MAX_LAYOUT_ATTEMPTS': 12,
                        '_LAYOUT_TELEMETRY': {'v6_emergency_head_tests': 0,
                                              'v9_emergency_text_blocked_heads': 0},
                        'paper_to_model': lambda value: value,
                        'host_layout_points': lambda target: [Point(0)],
                        'duct_axis_and_perp': lambda host: ((1, 0), (0, 1)),
                        'vec_from_uv': lambda u, v: Point(u, v),
                        'RIGHT': Point(1, 0), 'TAG_CLEARANCE_PAPER_IN': 0,
                        'plan_half_width': lambda host: 0,
                        '_head_scores': lambda grid, r, crop: (0, 0),
                        '_anchor_candidates_from_elbow': lambda host, head: [Point(head.X, 0)],
                        '_preferred_edge_sign': lambda head, metrics, anchor: 1,
                        '_leader_distance_cost': lambda length: 0,
                        '_smart_length_breakpoint_penalty': lambda length: 0,
                        '_telemetry_pool': lambda *args: None})
        route_checks = []
        def route_detail(a, b, ignore_source_id=None):
            route_checks.append(a)
            return {'blocking': 1 if a[1] > 0 else 0, 'mep': 0}
        self.grid.score_segment_detail.side_effect = route_detail
        self.grid.score_segment_components.return_value = (0, 0)
        candidates = self.ns['generate_emergency_layout_candidates'](
            self.target, self.grid, (.01, .01, .01, .01), None)
        self.assertTrue(candidates, 'Blocked first-side routes must not stop later clear-side search')
        self.assertGreater(sum(a[1] > 0 for a in route_checks), 8)
        self.assertTrue(all(candidate[1].Y < 0 for candidate in candidates))


class MeasuredHeadTests(unittest.TestCase):
    def test_failed_final_regeneration_rolls_back_before_any_more_model_reads(self):
        ns = namespace()
        class RegenerationFailedException(Exception):
            pass
        st = SimpleNamespace(Start=mock.Mock(), RollBack=mock.Mock())
        tag = Tag()
        document = SimpleNamespace(GetElement=mock.Mock(return_value=tag), Delete=mock.Mock(),
                                   Regenerate=mock.Mock(side_effect=RegenerationFailedException('failed')))
        ns.update({'doc': document, 'DB': SimpleNamespace(SubTransaction=lambda doc: st, ElementId=ElementId),
                   'element_rect': mock.Mock()})
        record = {'tag_id': 100, 'anchor': Point(0), 'target': {'duct': SimpleNamespace(Id=10)}}
        grid = mock.Mock()
        with self.assertRaises(RegenerationFailedException):
            ns['_verify_created_tag_head_clearance']([record], grid, None)
        st.RollBack.assert_called_once()
        ns['element_rect'].assert_not_called()
        grid.remove_source.assert_not_called()
        document.Delete.assert_not_called()

    def test_missing_family_bbox_is_reported_and_removed_before_commit(self):
        ns = namespace()
        st = SimpleNamespace(Start=mock.Mock(), RollBack=mock.Mock())
        document = SimpleNamespace(GetElement=mock.Mock(return_value=Tag()), Delete=mock.Mock(),
                                   Regenerate=mock.Mock())
        ns.update({'doc': document, 'DB': SimpleNamespace(SubTransaction=lambda doc: st, ElementId=ElementId),
                   'element_rect': lambda tag: None, '_reserve_record_geometry': mock.Mock()})
        record = {'tag_id': 100, 'anchor': Point(0), 'target': {'duct': SimpleNamespace(Id=10)}}
        survivors, rejected = ns['_verify_created_tag_head_clearance']([record], mock.Mock(), None)
        self.assertEqual([], survivors)
        self.assertEqual([(10, 'Actual tag family bounding box is unavailable.')], rejected)
        document.Delete.assert_called_once_with(100)

    def test_real_family_extents_prune_newest_overlapping_head_and_restore_tag_state(self):
        ns = namespace()
        tags = {100: Tag(100), 101: Tag(101, 11)}
        tags[100].TagHeadPosition = Point(5, 5)
        tags[101].TagHeadPosition = Point(5.15, 5)
        deleted = []
        document = SimpleNamespace(GetElement=tags.get, Delete=deleted.append, Regenerate=mock.Mock())
        class Transaction:
            def __init__(self, doc):
                self.snapshot = {eid: (tag.TagHeadPosition, tag.HasLeader) for eid, tag in tags.items()}
            def Start(self):
                pass
            def RollBack(self):
                for eid, (head, leader) in self.snapshot.items():
                    tags[eid].TagHeadPosition, tags[eid].HasLeader = head, leader
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
        ns.update({'doc': document, 'DB': SimpleNamespace(SubTransaction=Transaction, ElementId=ElementId),
                   'uv_of_point': lambda p: (p.X, p.Y), 'paper_to_model': lambda value: value,
                   'element_rect': lambda tag: (tag.TagHeadPosition.X-.2, tag.TagHeadPosition.Y-.1,
                                                tag.TagHeadPosition.X+.2, tag.TagHeadPosition.Y+.1),
                   'TAG_CLEARANCE_PAPER_IN': 0, 'SMART_V8_RESERVE_PAD_PAPER_IN': 0,
                   'W_TAG': 1, 'W_LEADER': 1, 'CAD_EXTREME_BLOCK_THRESHOLD': 1000})
        records = [{'tag_id': tag_id, 'target': {'duct': SimpleNamespace(Id=source)},
                    'anchor': Point(0), 'rect': (0, 0, .01, .01), 'leader_applied': False}
                   for tag_id, source in ((100, 10), (101, 11))]
        surviving, rejected = ns['_verify_created_tag_head_clearance'](records, Grid(), None)
        self.assertEqual([100], [record['tag_id'] for record in surviving])
        self.assertEqual([101], deleted)
        self.assertEqual(11, rejected[0][0])
        self.assertTrue(surviving[0]['head_clearance_verified'])
        self.assertEqual(5, tags[100].TagHeadPosition.X)
        self.assertEqual(5.15, tags[101].TagHeadPosition.X)
        self.assertTrue(tags[100].HasLeader)
        document.Regenerate.assert_called_once()


class AuditTests(unittest.TestCase):
    def test_component_only_success_saves_same_run_diagnostics_with_source_records(self):
        ns = namespace()
        stats = {'created': 1, 'failed': 0, 'skipped': 2, 'unmapped': 0,
                 'created_ids': [100], 'created_records': [{'tag_id': 100, 'source_id': 10, 'type_id': 20}],
                 'post_commit_rejected': 0}
        ns.update({'doc': SimpleNamespace(Title='Review', Application=SimpleNamespace(VersionNumber='2025')),
                   'view': SimpleNamespace(Name='Plan', Id=1, Scale=96), 'time': time,
                   'AUTOTAG_RUN_OPTIONS': {}, 'SMART_SELECTION_ONLY': False,
                   'AUTOTAG_SUPPRESS_RESULT_DIALOG': True, '_run_component_tags': lambda: stats,
                   'component_summary': lambda stats: 'Created 1 component tag.',
                   '_save_tag_run_audit': mock.Mock(return_value='/tmp/pipe-review.json')})
        result = ns['_finish_no_new_pipe_tags']('Component-only profile.', {}, {}, None, {}, time.time())
        self.assertEqual(1, result['component_created'])
        self.assertEqual('/tmp/pipe-review.json', result['audit_path'])
        payload = ns['_save_tag_run_audit'].call_args.args[0]
        self.assertEqual(stats['created_records'], payload['components']['created_records'])
        self.assertEqual(2, payload['components']['skipped'])

    def test_missing_suppressed_and_surviving_sources_have_distinct_statuses(self):
        ns = namespace()
        ns.update({'doc': SimpleNamespace(Title='Review', Application=SimpleNamespace(VersionNumber='2025')),
                   'view': SimpleNamespace(Name='Plan', Id=1, Scale=96),
                   'AUTOTAG_RUN_OPTIONS': {'event_tag_type': {'id': 20}},
                   'SMART_SELECTION_ONLY': False,
                   '_pipe_source_audit': lambda host: {'source_id': host.Id}})
        raw = {i: {'duct': SimpleNamespace(Id=i), 'reasons': {'turn'}} for i in (10, 11, 12, 13)}
        density = {i: raw[i] for i in (10, 11, 12)}
        record = {'tag_id': 100, 'target': raw[10], 'actual_text': 'BOP=19 feet', 'head': Point(5),
                  'leader_applied': True, 'source': 'normal'}
        audit = ns['_build_tag_run_audit'](raw, density, list(density.values()), [record], 20,
                                          {11: [101]}, {'created_ids': [102], 'post_commit_rejected': 1},
                                          [(12, 'blocked')], {'created': 1, 'message': 'test'})
        statuses = {entry['source_id']: entry['status'] for entry in audit['targets']}
        self.assertEqual({10: 'created-source-type-verified', 11: 'existing-source-type-verified',
                          12: 'missing-required-tag', 13: 'redundant-routing-target-suppressed'}, statuses)
        self.assertEqual('BOP=19 feet', audit['tags'][0]['text'])
        self.assertEqual([102], audit['components']['created_ids'])
        self.assertEqual(1, audit['components']['post_commit_rejected'])
        json.dumps(audit, allow_nan=False)


if __name__ == '__main__':
    unittest.main()
