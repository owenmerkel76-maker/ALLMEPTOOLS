"""Same-area drafting regressions: physical takeoffs and external callout boxes."""
import ast
from collections import deque
import math
import unittest
from types import SimpleNamespace
from unittest import mock
from test_duct_autotag_review import namespace, Point, Tag, ENGINE


class Vector(Point):
    def Normalize(self):
        length = math.sqrt(self.X**2 + self.Y**2 + self.Z**2)
        return Vector(self.X / length, self.Y / length, self.Z / length)

    def DotProduct(self, other):
        return self.X * other.X + self.Y * other.Y + self.Z * other.Z


def port(owner, x, y, dx, dy):
    return SimpleNamespace(Owner=owner, Origin=Point(x, y),
                           CoordinateSystem=SimpleNamespace(BasisZ=Vector(dx, dy)), refs=[])


class BranchTakeoffTests(unittest.TestCase):
    def setUp(self):
        self.ns = namespace()
        self.ns.update({'AUTOTAG_ENABLED_REASONS': {'branch'},
                        'deque': deque,
                        'connector_refs': lambda c: c.refs,
                        'physical_connectors': lambda e: e.ports,
                        'first_end_connectors': lambda e: e.ports,
                        'is_duct_fitting': lambda e: getattr(e, 'fitting', False),
                        'is_endcap_duct_fitting': lambda e: False})
        self.fitting = SimpleNamespace(Id=40, fitting=True)
        self.fitting.ports = [port(self.fitting, -1, 0, -1, 0),
                              port(self.fitting, 1, 0, 1, 0),
                              port(self.fitting, 0, 1, 0, 1)]
        self.ducts = []
        for index, fitting_port in enumerate(self.fitting.ports):
            duct = SimpleNamespace(Id=10 + index)
            c = port(duct, fitting_port.Origin.X, fitting_port.Origin.Y, 1, 0)
            c.refs = [fitting_port]
            fitting_port.refs = [c]
            duct.ports = [c]
            self.ducts.append(duct)

    def test_tee_branch_gets_a_target_without_tagging_the_two_main_ports(self):
        targets = {}
        audit = self.ns['audit_duct_branch_takeoffs'](self.ducts, targets)
        self.assertEqual([12], list(targets))
        self.assertEqual({'branch'}, targets[12]['reasons'])
        self.assertEqual([12], audit['added_source_ids'])
        self.assertEqual([{'fitting_id': 40, 'source_id': 12, 'port_index': 2,
                           'path_source_ids': [12, 40]}], audit['connections'])

    def test_existing_change_target_merges_branch_reason_without_duplicate(self):
        targets = {12: {'duct': self.ducts[2], 'event_points': [], 'reasons': {'size'}}}
        audit = self.ns['audit_duct_branch_takeoffs'](self.ducts, targets)
        self.assertEqual(1, len(targets))
        self.assertEqual({'size', 'branch'}, targets[12]['reasons'])
        self.assertEqual([], audit['added_source_ids'])

    def test_coincident_disconnected_branch_is_not_inferred_from_position(self):
        self.fitting.ports[2].refs = []
        targets = {}
        self.ns['audit_duct_branch_takeoffs'](self.ducts, targets)
        self.assertEqual({}, targets)

    def test_cross_with_two_main_axes_is_reported_as_ambiguous(self):
        self.fitting.ports.append(port(self.fitting, 0, -1, 0, -1))
        targets = {}
        audit = self.ns['audit_duct_branch_takeoffs'](self.ducts, targets)
        self.assertEqual({}, targets)
        self.assertEqual([40], audit['ambiguous_fitting_ids'])

    def test_missing_or_nonopposed_port_axes_are_not_branch_proof(self):
        self.fitting.ports[0].CoordinateSystem = None
        targets = {}
        audit = self.ns['audit_duct_branch_takeoffs'](self.ducts, targets)
        self.assertEqual({}, targets)
        self.assertEqual([40], audit['ambiguous_fitting_ids'])

    def test_native_or_fabrication_api_identified_tap_is_covered(self):
        self.fitting.ports = self.fitting.ports[:2]
        self.fitting.IsATap = lambda: True
        targets = {}
        self.ns['audit_duct_branch_takeoffs'](self.ducts[:2], targets)
        self.assertEqual({10, 11}, set(targets))

    def test_disabled_branch_checkbox_does_not_add_branch_targets(self):
        self.ns['AUTOTAG_ENABLED_REASONS'] = {'size'}
        targets = {}
        audit = self.ns['audit_duct_branch_takeoffs'](self.ducts, targets)
        self.assertFalse(audit['enabled'])
        self.assertEqual({}, targets)

    def test_same_signed_fabrication_frames_need_and_use_collinear_port_positions(self):
        self.fitting.ports[1].CoordinateSystem.BasisZ = Vector(-1, 0)
        targets = {}
        self.ns['audit_duct_branch_takeoffs'](self.ducts, targets)
        self.assertEqual({12}, set(targets))
        self.fitting.ports[1].Origin = Point(1, 1)
        targets = {}
        audit = self.ns['audit_duct_branch_takeoffs'](self.ducts, targets)
        self.assertEqual({}, targets)
        self.assertEqual([40], audit['ambiguous_fitting_ids'])

    def test_inline_damper_path_reaches_branch_without_crossing_the_main(self):
        duct = self.ducts[2]
        start = duct.ports[0]
        start.Origin = Point(0, 2)
        damper = SimpleNamespace(Id=50, Category=SimpleNamespace(Id=500))
        entrance = port(damper, 0, 2, 0, 1)
        exit = port(damper, 0, 1, 0, -1)
        damper.ports = [entrance, exit]
        start.refs = [entrance]
        entrance.refs = [start]
        exit.refs = [self.fitting.ports[2]]
        self.fitting.ports[2].refs = [exit]
        self.ns['DB'].BuiltInCategory = SimpleNamespace(OST_DuctAccessory=500)
        self.ns['bic_int'] = int
        targets = {}
        audit = self.ns['audit_duct_branch_takeoffs'](self.ducts, targets)
        self.assertEqual({12}, set(targets))
        self.assertEqual([12, 50, 40], audit['connections'][0]['path_source_ids'])
        # An unrelated straight occupying the same place is not an inline
        # accessory, even if it happens to have two physical ports.
        damper.Category.Id = 999
        targets = {}
        self.ns['audit_duct_branch_takeoffs'](self.ducts, targets)
        self.assertEqual({}, targets)

    def test_unreadable_path_is_reported_and_does_not_invent_a_target(self):
        self.ns['_duct_branch_port_indices'] = mock.Mock(side_effect=RuntimeError('unreadable ports'))
        targets = {}
        audit = self.ns['audit_duct_branch_takeoffs'](self.ducts, targets)
        self.assertEqual({}, targets)
        self.assertTrue(audit['query_failures'])
        self.assertEqual('unreadable ports', audit['query_failures'][0]['reason'])

    def test_fatal_path_error_propagates_instead_of_reading_another_source(self):
        class RegenerationFailedException(Exception):
            pass
        self.ns['_duct_branch_port_indices'] = mock.Mock(side_effect=RegenerationFailedException('rollback'))
        with self.assertRaises(RegenerationFailedException):
            self.ns['audit_duct_branch_takeoffs'](self.ducts, {})
        self.assertEqual(1, self.ns['_duct_branch_port_indices'].call_count)


def layout_namespace():
    ns = namespace()
    ns.update({'paper_to_model': lambda value: value, '_PAPER_TO_MODEL_FACTOR': 1,
               'MAX_GRID_CELLS_PER_RECORD': 4096,
               'TAG_CLEARANCE_PAPER_IN': .045, 'TAG_SIZE_SAFETY_PAPER_IN': .035,
               'CAD_HEAD_BLOCK_THRESHOLD': 1800, 'W_TAG': 6000, 'W_LEADER': 900,
               'uv_of_point': lambda p: (p.X, p.Y),
               'vec_from_uv': lambda u, v: Point(u, v)})
    tree = ast.parse(ENGINE.read_text())
    node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'SpatialGrid')
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(ENGINE), 'exec'), ns)
    return ns


class ComponentPlacementTests(unittest.TestCase):
    def setUp(self):
        self.ns = layout_namespace()
        self.grid = self.ns['SpatialGrid'](.5)
        self.host_rect = (0, 0, 1, 1)
        self.grid.add_rect('terminal', self.host_rect, 1900, 10)
        self.metrics = (.3, .3, .1, .1)

    def candidates(self, crop=None):
        return self.ns['_component_layout_candidates']((.5, .5), self.host_rect,
                                                       self.metrics, self.grid, crop, 10)

    def test_every_candidate_clears_its_own_diffuser_symbol(self):
        candidates = self.candidates()
        self.assertTrue(candidates)
        for _score, _head, rect, _attachment in candidates:
            self.assertFalse(self.ns['rect_intersects'](rect, self.host_rect))

    def test_blocked_side_uses_other_open_space_and_short_leaders(self):
        self.grid.add_rect('annotation', (1, -2, 4, 3), 4500, 20)
        candidates = self.candidates()
        self.assertTrue(candidates)
        for _score, _head, rect, attachment in candidates:
            self.assertEqual(0, self.grid.score_rect_components(rect)[0])
            self.assertLessEqual(self.ns['leader_length_paper']((.5, .5), attachment), 1.10)

    def test_no_clear_crop_or_fully_blocked_area_has_no_on_host_fallback(self):
        self.assertEqual([], self.candidates((0, 0, 1, 1)))
        self.grid.add_rect('annotation', (-10, -10, 10, 10), 4500, 20)
        self.assertEqual([], self.candidates())

    def test_protected_annotation_blocks_leader_route_as_well_as_text_box(self):
        self.grid.add_rect('annotation', (1.01, -2, 1.02, 3), 4500, 20)
        for _score, _head, rect, attachment in self.candidates():
            self.assertEqual(0, self.grid.score_segment_detail((.5, .5), attachment, 10)['blocking'])

    def test_diagonal_whitespace_pocket_outside_old_stagger_range_is_used(self):
        for source_id, rect in enumerate([(-10, -10, 1.09, 10), (1.80, -10, 10, 10),
                                           (-10, -10, 10, 1.10), (-10, 1.51, 10, 10)], 20):
            self.grid.add_rect('fitting', rect, 1900, source_id)
        candidates = self.candidates((0, 0, 2.5, 2))
        self.assertTrue(candidates)
        for _, head, rect, attachment in candidates:
            self.assertGreater(abs(head[1]-.5), .60)
            self.assertEqual(0, self.grid.score_rect_components(rect)[0])
            self.assertLessEqual(self.ns['leader_length_paper']((.5, .5), attachment), 1.10)

    def install_handler(self, constrained=False):
        source = SimpleNamespace(Id=10)
        tag = Tag()
        tag.TagHeadPosition = Point(.5, .5)
        tag.TagText = ''
        def regenerate():
            tag.TagText = 'SD1 6 in\n100 CFM'
            if constrained:
                tag.TagHeadPosition = Point(.5, .5)
        self.ns.update({'collect_mode_ductwork': lambda mode: [],
                        'build_obstacle_grid': lambda ducts: (self.grid, None),
                        'crop_rect_for_view': lambda view: None,
                        'element_rect': lambda elem: self.host_rect if elem is source else None,
                        'doc': SimpleNamespace(Regenerate=mock.Mock(side_effect=regenerate)),
                        '_components_enabled': lambda: True})
        self.ns['DB'].Reference = lambda elem: elem.Id
        handler = self.ns['_make_duct_component_layout']()
        return handler, tag, source

    def test_real_handler_waits_for_text_and_reserves_external_head_with_leader(self):
        handler, tag, source = self.install_handler()
        result = handler(tag, source, 'Air terminals / diffusers', Point(.5, .5))
        self.assertTrue(tag.HasLeader)
        self.assertEqual('estimated-text-footprint', result['head_bounds_phase'])
        self.assertEqual('placed', handler.diagnostics[0]['status'])
        self.assertFalse(self.ns['rect_intersects'](result['head_rect_uv'], self.host_rect))
        self.assertTrue(self.grid.rect_hits_kinds(tuple(result['head_rect_uv']), {'tag'}))
        handler.release(100)
        self.assertFalse(self.grid.rect_hits_kinds(tuple(result['head_rect_uv']), {'tag'}))

    def test_revit_constrained_head_is_rejected_before_reserving_an_overlay(self):
        handler, tag, source = self.install_handler(constrained=True)
        with self.assertRaisesRegex(ValueError, 'No clear external'):
            handler(tag, source, 'Air terminals / diffusers', Point(.5, .5))
        self.assertFalse(self.grid.source_records.get(100))
        self.assertEqual('no-clear-position', handler.diagnostics[0]['status'])

    def test_component_only_command_installs_the_external_layout_handler(self):
        callback = mock.Mock()
        self.ns.update({'_components_enabled': lambda: True,
                        '_make_duct_component_layout': mock.Mock(return_value=callback),
                        'run_direct_component_tags': mock.Mock(return_value={'created': 1}),
                        'AUTOTAG_RUN_OPTIONS': {}, 'doc': object(), 'uidoc': object()})
        self.ns['_run_component_tags']()
        self.assertIs(callback, self.ns['run_direct_component_tags'].call_args.kwargs['layout_handler'])


class AllStraightTargetTests(unittest.TestCase):
    def setUp(self):
        self.ns = layout_namespace()
        class Line:
            def Evaluate(self, t, normalized):
                return Point(.5, .5)
        self.ns['DB'].Line = Line
        self.ns.update({'AUTOTAG_ENABLED_REASONS': {'all_straights'},
                        'is_native_duct': lambda d: getattr(d, 'native', False),
                        'is_fabrication_straight': lambda d: getattr(d, 'fab_straight', False),
                        'duct_line': lambda d: getattr(d, 'line', None),
                        'horizontal_axis_uv': lambda d: getattr(d, 'axis', (1, 0))})
        self.line_class = Line

    def native(self, source_id, axis=(1, 0)):
        line = self.line_class()
        return SimpleNamespace(Id=source_id, native=True, Location=SimpleNamespace(Curve=line),
                               line=line, axis=axis)

    def test_unchanged_straight_and_diagonal_runs_are_targets_without_events(self):
        ducts = [self.native(10), self.native(11, (.707, .707))]
        targets = {}
        audit = self.ns['audit_all_straight_targets'](ducts, targets)
        self.assertEqual({10, 11}, set(targets))
        self.assertTrue(all(t['reasons'] == {'all_straights'} for t in targets.values()))
        self.assertEqual([10, 11], audit['added_source_ids'])

    def test_existing_change_target_merges_with_all_straights_not_a_second_tag(self):
        duct = self.native(10)
        targets = {10: {'duct': duct, 'event_points': [], 'reasons': {'size'}}}
        audit = self.ns['audit_all_straight_targets']([duct], targets)
        self.assertEqual({'size', 'all_straights'}, targets[10]['reasons'])
        self.assertEqual([], audit['added_source_ids'])

    def test_sloped_and_vertical_straights_are_not_removed_by_horizontal_filter(self):
        sloped, vertical = self.native(10), self.native(11, None)
        targets = {}
        self.ns['audit_all_straight_targets']([sloped, vertical], targets)
        self.assertEqual({10, 11}, set(targets))
        self.assertTrue(targets[11]['pointlike_straight'])

    def test_fittings_and_native_arcs_are_excluded_but_unreadable_straight_is_explicit(self):
        elbow = SimpleNamespace(Id=20, native=False, fab_straight=False)
        arc = self.native(21)
        arc.Location.Curve = object()
        unknown = SimpleNamespace(Id=22, fab_straight=True, line=None)
        native_unknown = self.native(23)
        native_unknown.Location.Curve = None
        native_unknown.line = None
        targets = {}
        audit = self.ns['audit_all_straight_targets']([elbow, arc, unknown, native_unknown], targets)
        self.assertEqual({22, 23}, set(targets))
        self.assertEqual([20, 21], audit['excluded_nonstraight_source_ids'])
        self.assertEqual([22, 23], audit['unknown_geometry_source_ids'])
        self.assertTrue(targets[22]['source_line_unavailable'])

    def test_all_straights_option_can_be_disabled(self):
        self.ns['AUTOTAG_ENABLED_REASONS'] = {'size'}
        targets = {}
        audit = self.ns['audit_all_straight_targets']([self.native(10)], targets)
        self.assertFalse(audit['enabled'])
        self.assertEqual({}, targets)

    def test_shipped_menu_emits_all_straights_without_requiring_change_events(self):
        path = ENGINE.parent.parent / 'autotag_menu.py'
        tree = ast.parse(path.read_text())
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'AutoTagSmartWindow')
        methods = [n for n in cls.body if isinstance(n, ast.FunctionDef)
                   and n.name in ('_event_controls', '_read_discipline')]
        ns = {}
        exec(compile(ast.Module(body=methods, type_ignores=[]), str(path), 'exec'), ns)
        window = SimpleNamespace()
        for name in ('DuctEventDirection', 'DuctEventElevation', 'DuctEventSize', 'DuctEventShape',
                     'DuctEventEndcap', 'DuctEventBranch', 'DuctAllStraights', 'AllowDoglegs',
                     'ForceLeaders', 'ExtraCleanup', 'ScopeSelection', 'DetailedReport'):
            setattr(window, name, SimpleNamespace(IsChecked=name == 'DuctAllStraights'))
        window._event_controls = lambda discipline: ns['_event_controls'](window, discipline)
        window._component_controls = lambda discipline: [SimpleNamespace(IsChecked=False) for _ in range(4)]
        window._selected_choice = lambda *args: {'id': 20, 'mode': 'fabrication'}
        window._combo_for = lambda *args: None
        window._engine_key = lambda: 'balanced'
        options = ns['_read_discipline'](window, 'duct')
        self.assertEqual(['all_straights'], options['event_reasons'])
        self.ns['AUTOTAG_ENABLED_REASONS'] = set(options['event_reasons'])
        targets = {}
        self.ns['audit_all_straight_targets']([self.native(10)], targets)
        self.assertEqual({10}, set(targets))

    def test_vertical_straight_uses_real_host_with_external_leader(self):
        duct = self.native(10, None)
        self.ns['element_rect'] = lambda d: (0, 0, 1, 1)
        grid = self.ns['SpatialGrid'](.5)
        grid.add_rect('duct', (0, 0, 1, 1), 1900, 10)
        pool = self.ns['generate_ranked_layout_pool'](
            {'duct': duct, 'pointlike_straight': True}, grid, (.3, .3, .1, .1), None)
        self.assertTrue(pool)
        self.assertTrue(all(layout[4] and len(layout) == 7 for layout in pool))
        self.assertTrue(all(not self.ns['rect_intersects'](layout[3], (0, 0, 1, 1)) for layout in pool))
