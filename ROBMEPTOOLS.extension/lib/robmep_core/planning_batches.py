# -*- coding: utf-8 -*-
"""Stable per-run station batches, independent of Autodesk and Python version."""


def group_station_jobs(tasks):
    """Keep first-seen context identity order and stable ascending station order.

    Equal-valued context dictionaries can represent different physical runs.
    Retaining the context in each batch also keeps its id alive for this call.
    Input lists, jobs and context dictionaries are never changed.
    """
    batches = []
    by_identity = {}
    for job in tasks:
        context = job['run_context']
        identity = id(context)
        if identity not in by_identity:
            jobs = []
            by_identity[identity] = jobs
            batches.append((context, jobs))
        by_identity[identity].append(job)
    return [(context, sorted(jobs, key=lambda job: job['station']))
            for context, jobs in batches]
