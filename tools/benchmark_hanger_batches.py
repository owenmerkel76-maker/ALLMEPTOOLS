"""Optional offline microbenchmark; does not measure Revit or vendor performance."""
from pathlib import Path
import random
import statistics
import sys
import time

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


def main():
    rng = random.Random(143)
    contexts = [{} for _ in range(1000)]
    tasks = [dict(run_context=contexts[i % 1000], station=rng.randrange(100))
             for i in range(10000)]
    expected = legacy_batches(tasks)
    actual = group_station_jobs(tasks)
    assert [(id(c), [id(j) for j in jobs]) for c, jobs in expected] == [
        (id(c), [id(j) for j in jobs]) for c, jobs in actual]
    for function in (legacy_batches, group_station_jobs):
        timings = []
        for _ in range(3):
            start = time.perf_counter()
            function(tasks)
            timings.append(time.perf_counter() - start)
        print('{}: {:.6f} s median'.format(function.__name__, statistics.median(timings)))
    print('Python batching only; actual Revit performance requires field profiling.')


if __name__ == '__main__':
    main()
