"""Anonymous regression evidence; no private drawing/model data required."""
import importlib.util
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location('comparison', Path(__file__).resolve().parents[1]
                                             / 'tools/compare_autodim_evidence.py')
comparison = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(comparison)


class EvidenceComparisonTests(unittest.TestCase):
    def test_dimension_parser_excludes_room_and_ceiling_annotations(self):
        self.assertAlmostEqual(2 + 7.375 / 12, comparison.feet_inches('2\'-7 3/8"'))
        for label in ('9\'-0"AFF', 'ROOM 200', '1/4" = 1\'-0"', '1\'-2 1/0"'):
            self.assertIsNone(comparison.feet_inches(label))

    def test_downstream_context_is_not_an_additional_required_target(self):
        audit = {'targets': [
            {'role': 'straight_locator', 'source_id': 1, 'covered': True},
            {'role': 'branch_downstream_straight', 'source_id': 2, 'covered': True},
            {'role': 'branch_connector', 'source_id': 3, 'branch_key': 'b', 'covered': False}],
            'summary': {'cert_required': 2, 'certified_targets': 1}}
        result = comparison.coverage(audit)
        self.assertEqual((2, 1, 1), (result['required_rows'], result['covered_rows'], result['context_rows']))
        self.assertEqual({}, result['summary_mismatches'])

    def test_repeated_projected_key_warns_without_merging_connectors(self):
        first = {'role': 'branch_connector', 'source_id': 3, 'branch_key': 'same-xy', 'covered': True}
        second = dict(first, point=[1, 2, 9])
        result = comparison.coverage({'targets': [first, second]})
        self.assertEqual(2, result['required_rows'])
        self.assertFalse(result['repeated_keys'][0]['identical_audit_rows'])

    def test_inconsistent_reported_coverage_is_visible(self):
        result = comparison.coverage({'targets': [], 'summary': {'cert_required': 1}})
        self.assertEqual({'reported': 1, 'computed': 0}, result['summary_mismatches']['cert_required'])

    def test_touching_boxes_are_not_positive_area_overlaps(self):
        spans = [{'text': str(i), 'bbox': r} for i, r in enumerate(
            [(0, 0, 10, 5), (10, 0, 20, 5), (9, 1, 11, 4)])]
        result = comparison.overlaps(spans)
        self.assertEqual([[1, 3], [2, 3]], [p['labels'] for p in result])
        self.assertEqual([3, 3], [p['area_pt2'] for p in result])

    def test_vertical_text_uses_its_reading_axis_for_width(self):
        metric = {'label': '1\'-0"', 'width_paper_in': .5, 'height_paper_in': .1}
        spans = [{'text': metric['label'], 'bbox': (0, 0, 10, 60), 'direction': (0, -1)}]
        result = comparison.metric_ratios(spans, [metric], 72)[0]
        self.assertAlmostEqual(60 / 36, result['width_ratio'])
        self.assertAlmostEqual(10 / 7.2, result['height_ratio'])

    def test_metric_comparison_requires_scale_and_skips_oblique_aabb(self):
        with self.assertRaises(ValueError):
            comparison.metric_ratios([], [], 0)
        span = {'text': 'x', 'bbox': [0, 0, 10, 10], 'direction': [.707, .707]}
        metric = {'label': 'x', 'width_paper_in': 1, 'height_paper_in': 1}
        self.assertEqual([], comparison.metric_ratios([span], [metric], 72))

    def test_grid_registration_handles_pdf_inverted_y_and_measures_residual(self):
        fit = comparison.fit_axis([{'model': 0, 'pdf': 100}, {'model': 10, 'pdf': 80},
                                   {'model': 20, 'pdf': 60}])
        self.assertEqual((-2, 100, 0), (fit['slope'], fit['offset'], fit['max_residual_pt']))
        with self.assertRaises(ValueError):
            comparison.fit_axis([{'model': 2, 'pdf': 1}, {'model': 2, 'pdf': 10}])

    def test_equal_value_on_wrong_axis_does_not_link_an_export(self):
        spans = [{'text': '1\'-0"', 'direction': (1, 0)}]
        dimensions = [{'actual_value_ft': 1, 'grid_id': 7}]
        self.assertTrue(comparison.ordered_value_agreement(spans, dimensions, {7: {'axis': [0, 1, 0]}}))
        self.assertFalse(comparison.ordered_value_agreement(spans, dimensions, {7: {'axis': [1, 0, 0]}}))
        self.assertFalse(comparison.ordered_value_agreement(spans, [], {}))
        dimensions[0]['actual_value_ft'] = 1.1
        self.assertFalse(comparison.ordered_value_agreement(spans, dimensions, {7: {'axis': [0, 1, 0]}}))


if __name__ == '__main__':
    unittest.main()
