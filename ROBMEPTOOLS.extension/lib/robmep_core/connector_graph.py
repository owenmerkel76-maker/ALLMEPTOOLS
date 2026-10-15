# -*- coding: utf-8 -*-
"""Pure connector-snapshot analysis, compatible with IronPython 2.7.

This module never reads or modifies a Revit document. The caller must provide
verified physical connector edges, not proximity guesses or logical-system edges.
Each part has a source-qualified string key, source, kind, service, shape, size,
length_ft and direction. Only straight parts need the last five fields. All
coordinates/lengths must already be in host-world feet. Source identity and key
must remain stable across snapshots. The separate revit_connector_snapshot
adapter collects selected host FabricationPart data; linked collection is pending.

Runs stop at fittings/equipment, branches, scope cuts, source/service/profile
boundaries and direction changes. No station placement or hardware rule is implied.
Closed loops are reported unresolved rather than assigned an arbitrary start.
"""
import math

try:
    string_types = (basestring,)
except NameError:
    string_types = (str,)


def _positive(value):
    result = float(value)
    if math.isnan(result) or math.isinf(result) or result <= 0:
        raise ValueError('Expected finite positive dimension')
    return result


def _straight(part):
    if not isinstance(part.get('service'), string_types) or not part['service']:
        raise ValueError('Straight requires an explicit service identity')
    expected = {'round': 1, 'rectangular': 2, 'oval': 2}.get(part.get('shape'))
    size = tuple(_positive(v) for v in part['size'])
    if expected is None or len(size) != expected:
        raise ValueError('Unknown shape or invalid size arity')
    direction = tuple(float(v) for v in part['direction'])
    if len(direction) != 3 or any(math.isnan(v) or math.isinf(v) for v in direction):
        raise ValueError('Invalid host-world direction')
    magnitude = math.sqrt(sum(v * v for v in direction))
    if magnitude <= 1e-12 or math.isinf(magnitude):
        raise ValueError('Direction must be nonzero and finite')
    return (part['service'], part['shape'], size, _positive(part['length_ft']),
            tuple(v / magnitude for v in direction))


def build_runs(parts, connections, parallel_dot=0.996):
    """Return deterministic linear runs, boundary reasons and unresolved inputs.

    Connections are unordered pairs of part keys derived from physical connectors.
    Duplicate/reversed edges count once; self-edges and unknown keys are diagnosed.
    Invalid records fail explicitly, never falling back to guessed geometry. A
    scope cut blocks joining at that part until its topology is fully known.
    Run segments expose cumulative start/end feet, not connector orientation.
    """
    threshold = float(parallel_dot)
    if not 0 < threshold <= 1:
        raise ValueError('parallel_dot must be in (0, 1]')
    records, straight = {}, {}
    for part in parts:
        key = part.get('key')
        if not isinstance(key, string_types) or not key:
            raise ValueError('Part key must be a nonempty source-qualified string')
        if key in records:
            raise ValueError('Duplicate part key: ' + key)
        if not isinstance(part.get('source'), string_types) or not part['source']:
            raise ValueError('Part requires source identity: ' + key)
        if part.get('kind') not in ('straight', 'fitting', 'equipment'):
            raise ValueError('Unsupported part kind: ' + key)
        records[key] = part
        if part['kind'] == 'straight':
            straight[key] = _straight(part)
    neighbors = dict((key, set()) for key in records)
    boundaries = dict((key, set()) for key in records)
    unresolved = set()
    for edge in connections:
        if len(edge) != 2:
            raise ValueError('Each connection must have two part keys')
        a, b = edge
        if any(not isinstance(k, string_types) or not k for k in (a, b)):
            raise ValueError('Connection keys must be nonempty strings')
        if a == b:
            unresolved.add(('SELF_CONNECTION', a))
            if a in records:
                boundaries[a].add('SELF_CONNECTION')
            continue
        if a not in records or b not in records:
            unresolved.add(('OUTSIDE_SCOPE', min(a, b), max(a, b)))
            for key in (a, b):
                if key in records:
                    boundaries[key].add('OUTSIDE_SCOPE')
            continue
        neighbors[a].add(b)
        neighbors[b].add(a)
    eligible = dict((key, set()) for key in straight)
    for key in sorted(straight):
        if len(neighbors[key]) > 2:
            boundaries[key].add('BRANCH')
        for other in sorted(neighbors[key]):
            if other not in straight:
                boundaries[key].add('NON_STRAIGHT')
                continue
            left, right = straight[key], straight[other]
            reason = None
            if records[key]['source'] != records[other]['source']:
                reason = 'SOURCE_BOUNDARY'
            elif left[0] != right[0]:
                reason = 'SERVICE_BOUNDARY'
            elif left[1:3] != right[1:3]:
                reason = 'PROFILE_BOUNDARY'
            elif abs(sum(a * b for a, b in zip(left[4], right[4]))) < threshold:
                reason = 'DIRECTION_CHANGE'
            if reason:
                boundaries[key].add(reason)
                continue
            # Do not infer topology across an incomplete or branching record.
            if (len(neighbors[key]) > 2 or len(neighbors[other]) > 2 or
                    'OUTSIDE_SCOPE' in boundaries[key] or
                    'OUTSIDE_SCOPE' in boundaries[other] or
                    'SELF_CONNECTION' in boundaries[key] or
                    'SELF_CONNECTION' in boundaries[other]):
                continue
            eligible[key].add(other)
    runs, remaining = [], set(straight)
    while remaining:
        seed = min(remaining)
        component, pending = set(), [seed]
        while pending:
            key = pending.pop()
            if key in component:
                continue
            component.add(key)
            pending.extend(eligible[key] - component)
        ends = sorted(key for key in component if len(eligible[key]) < 2)
        remaining.difference_update(component)
        if not ends:
            unresolved.add(tuple(['CLOSED_LOOP'] + sorted(component)))
            continue
        ordered, previous, current = [], None, ends[0]
        while current is not None:
            ordered.append(current)
            following = sorted(eligible[current] - set([previous]))
            previous, current = current, following[0] if following else None
        offset, segments = 0., []
        for key in ordered:
            end = offset + straight[key][3]
            segments.append({'key': key, 'start_ft': offset, 'end_ft': end})
            offset = end
        runs.append({'keys': ordered, 'length_ft': offset, 'segments': segments})
    return {'runs': runs,
            'boundaries': dict((k, sorted(v)) for k, v in sorted(boundaries.items()) if v),
            'unresolved': sorted(unresolved)}
