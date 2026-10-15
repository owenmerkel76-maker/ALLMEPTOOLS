"""Physical topology fixtures; no Autodesk imports or inferred endpoint links."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ROBMEPTOOLS.extension/lib'))
from robmep_core.connector_graph import build_runs


def part(key, **options):
    record = dict(key=key, source='host', kind='straight', service='duct-service-1',
                  shape='rectangular', size=(2., 1.), length_ft=3., direction=(1., 0., 0.))
    record.update(options)
    return record


def keys(result):
    return [r['keys'] for r in result['runs']]


class ConnectorGraphTests(unittest.TestCase):
    def test_five_pieces_are_one_fifteen_foot_run(self):
        result = build_runs([part(str(i)) for i in range(5)], [('0','1'),('1','2'),('2','3'),('3','4')])
        self.assertEqual([['0','1','2','3','4']], keys(result))
        self.assertEqual(15., result['runs'][0]['length_ft'])
        self.assertEqual([0.,3.,6.,9.,12.], [s['start_ft'] for s in result['runs'][0]['segments']])
        self.assertEqual(15., result['runs'][0]['segments'][-1]['end_ft'])

    def test_nearby_or_overlapping_parts_without_connectors_stay_separate(self):
        self.assertEqual([['a'],['b']], keys(build_runs([part('a'), part('b')], [])))

    def test_duplicate_and_reversed_edges_do_not_create_branch(self):
        result = build_runs([part('a'),part('b')], [('a','b'),('b','a'),('a','b')])
        self.assertEqual([['a','b']], keys(result))
        self.assertEqual({}, result['boundaries'])

    def test_tee_fitting_splits_all_legs(self):
        parts = [part(k) for k in 'abc'] + [part('tee',kind='fitting')]
        result = build_runs(parts, [('a','tee'),('b','tee'),('c','tee')])
        self.assertEqual([['a'],['b'],['c']], keys(result))
        self.assertEqual(['NON_STRAIGHT'], result['boundaries']['a'])

    def test_branch_on_straight_cannot_join_neighboring_runs(self):
        result = build_runs([part(k) for k in 'abcd'], [('a','b'),('b','c'),('b','d')])
        self.assertEqual([['a'],['b'],['c'],['d']], keys(result))
        self.assertIn('BRANCH', result['boundaries']['b'])

    def test_source_service_shape_size_and_direction_are_boundaries(self):
        cases = [('SOURCE_BOUNDARY',dict(source='link-1')),
                 ('SERVICE_BOUNDARY',dict(service='other-service')),
                 ('PROFILE_BOUNDARY',dict(shape='round',size=(1.,))),
                 ('PROFILE_BOUNDARY',dict(size=(2.01,1.))),
                 ('DIRECTION_CHANGE',dict(direction=(0.,1.,0.)))]
        for reason, options in cases:
            with self.subTest(reason=reason, options=options):
                result = build_runs([part('a'),part('b',**options)],[('a','b')])
                self.assertEqual([['a'],['b']],keys(result))
                self.assertIn(reason,result['boundaries']['a'])

    def test_reversed_and_sloping_direction_still_connect(self):
        result = build_runs([part('a',direction=(1.,0.,1.)),part('b',direction=(-2.,0.,-2.))],[('a','b')])
        self.assertEqual([['a','b']],keys(result))

    def test_missing_scope_is_reported_and_not_bridged(self):
        result = build_runs([part('a'),part('b')],[('a','b'),('b','outside')])
        self.assertEqual([['a'],['b']],keys(result))
        self.assertIn('OUTSIDE_SCOPE',result['boundaries']['b'])
        self.assertEqual([('OUTSIDE_SCOPE','b','outside')],result['unresolved'])

    def test_closed_loop_is_unresolved_not_arbitrary_linear_run(self):
        result = build_runs([part(k) for k in 'abc'],[('a','b'),('b','c'),('c','a')])
        self.assertEqual([],result['runs'])
        self.assertEqual([('CLOSED_LOOP','a','b','c')],result['unresolved'])

    def test_self_connection_is_reported_and_blocks_joining(self):
        result = build_runs([part('a'),part('b')],[('a','a'),('a','b')])
        self.assertEqual([['a'],['b']],keys(result))
        self.assertEqual([('SELF_CONNECTION','a')],result['unresolved'])

    def test_order_rerun_and_inputs_are_stable(self):
        parts=[part(k) for k in 'cba'];edges=[('c','b'),('b','a')]
        before=copy.deepcopy((parts,edges))
        expected=build_runs(parts,edges)
        self.assertEqual(expected,build_runs(list(reversed(parts)),list(reversed(edges))))
        self.assertEqual(expected,build_runs(parts,edges))
        self.assertEqual(before,(parts,edges))

    def test_invalid_or_ambiguous_records_fail_explicitly(self):
        cases=[dict(length_ft=0),dict(length_ft=float('nan')),dict(size=(float('inf'),1.)),
               dict(direction=(0,0,0)),dict(direction=(float('nan'),0,0)),dict(service=None),
               dict(source=''),dict(kind='unknown'),dict(shape='unknown'),dict(size=(1.,)),
               dict(key='')]
        for options in cases:
            with self.subTest(options=options):
                with self.assertRaises((ValueError,TypeError)):
                    build_runs([part('a',**options)],[])
        with self.assertRaises(ValueError):build_runs([part('a'),part('a')],[])

    def test_equipment_boundary_and_empty_scope(self):
        result=build_runs([part('a'),part('ahu',kind='equipment')],[('a','ahu')])
        self.assertEqual([['a']],keys(result))
        self.assertIn('NON_STRAIGHT',result['boundaries']['a'])
        self.assertEqual([],build_runs([],[])['runs'])

    def test_threshold_and_malformed_edges_rejected(self):
        for threshold in (0,-1,1.1,float('nan')):
            with self.assertRaises(ValueError):build_runs([],[],threshold)
        for edges in ([('a',)],[('a','b','c')],[(None,'a')]):
            with self.assertRaises(ValueError):build_runs([part('a')],edges)
