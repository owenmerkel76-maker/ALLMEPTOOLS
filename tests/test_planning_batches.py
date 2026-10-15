"""Compare optimized batching with the previous identity-based algorithm."""
import ast
import copy
from pathlib import Path
import random
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'ROBMEPTOOLS.extension/lib'))
from robmep_core.planning_batches import group_station_jobs


def legacy_batches(tasks):
    contexts = []
    for job in tasks:
        context = job['run_context']
        if not any(context is existing for existing in contexts):
            contexts.append(context)
    return [(context, sorted([job for job in tasks if job['run_context'] is context],
                             key=lambda job: job['station'])) for context in contexts]


class PlanningBatchTests(unittest.TestCase):
    def test_identity_order_stable_stations_and_input_preservation(self):
        a, b = {'length': 10}, {'length': 10}
        tasks = [dict(run_context=a, station=5, name='a5'),
                 dict(run_context=b, station=2, name='b2'),
                 dict(run_context=a, station=1, name='a1-first'),
                 dict(run_context=a, station=1, name='a1-second')]
        before = copy.deepcopy(tasks)
        result = group_station_jobs(tasks)
        self.assertEqual(before, tasks)
        self.assertIs(a, result[0][0])
        self.assertIs(b, result[1][0])
        self.assertEqual(['a1-first', 'a1-second', 'a5'], [j['name'] for j in result[0][1]])
        self.assertEqual(legacy_batches(tasks), result)
        self.assertIs(tasks[2], result[0][1][0])

    def test_interleaved_runs_match_legacy_by_object_identity(self):
        rng = random.Random(143)
        contexts = [{} for _ in range(50)]
        tasks = [dict(run_context=rng.choice(contexts), station=rng.randrange(20))
                 for _ in range(1000)]
        expected, actual = legacy_batches(tasks), group_station_jobs(tasks)
        self.assertEqual(len(expected), len(actual))
        for (ec, ej), (ac, aj) in zip(expected, actual):
            self.assertIs(ec, ac)
            self.assertEqual([id(j) for j in ej], [id(j) for j in aj])

    def test_empty_and_missing_job_metadata(self):
        self.assertEqual([], group_station_jobs([]))
        for tasks in ([{}], [{'run_context': {}}]):
            with self.assertRaises(KeyError):
                group_station_jobs(tasks)

    def test_actual_alignment_uses_batches_without_task_rescans(self):
        path = ROOT / 'ROBMEPTOOLS.extension/ROBMEPTOOLS.tab/Hangers.panel/Auto Hanger.pushbutton/script.py'
        tree = ast.parse(path.read_text())
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                        and n.name == 'align_structure_tasks')
        calls = [n.func.id for n in ast.walk(function)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
        self.assertIn('group_station_jobs', calls)
        # No loop in this expensive Revit phase should rescan the full task list.
        iterations = [n.iter for n in ast.walk(function)
                      if isinstance(n, (ast.For, ast.comprehension))]
        self.assertFalse(any(isinstance(n, ast.Name) and n.id == 'tasks' for n in iterations))
