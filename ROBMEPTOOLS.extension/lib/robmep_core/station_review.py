# -*- coding: utf-8 -*-
"""Immutable-in-use station review records and exact host-axis validation."""
import math


def point(value):
    result = tuple(float(v) for v in value)
    if len(result) != 3 or any(math.isnan(v) or math.isinf(v) for v in result):
        raise ValueError('Station needs three finite host-world coordinates')
    return result


def exact_axis_distance(a, b, requested):
    a, b, requested = point(a), point(b), point(requested)
    vector = tuple(b[i]-a[i] for i in range(3))
    length = math.sqrt(sum(v*v for v in vector))
    if math.isnan(length) or math.isinf(length) or length <= .51:
        raise ValueError('Host axis cannot provide a legal test station')
    direct = tuple(v/length for v in vector)
    distance = sum((requested[i]-a[i])*direct[i] for i in range(3))
    projected = tuple(a[i]+direct[i]*distance for i in range(3))
    if math.sqrt(sum((projected[i]-requested[i])**2 for i in range(3))) > 1e-4:
        raise ValueError('Preview station is not on the current host axis')
    if not .255-1e-6 <= distance <= length-.255+1e-6:
        raise ValueError('Preview station is outside the legal inboard host range')
    return distance


def review_records(snapshot, result, limit=200):
    if limit <= 0:
        raise ValueError('Marker limit must be positive')
    parts = dict((p['key'],p) for p in snapshot['parts'])
    records = []
    for route_index, route in enumerate(result['routes']):
        for station in route['stations']:
            host = parts[station['host_key']]
            if host['element_id'] != station['element_id'] or host['kind'] != 'straight':
                raise ValueError('Preview station host identity is inconsistent')
            record = dict(station)
            record.update(number=len(records)+1,route_number=route_index+1,
                          source=snapshot['source'],host_record=dict(host),
                          host_geometry=snapshot['route_geometry'][host['key']])
            record['point_ft'] = point(record['point_ft'])
            exact_axis_distance(host['axis_start_ft'],host['axis_end_ft'],record['point_ft'])
            records.append(record)
    return records[:limit],len(records)


def validate_snapshot(original, current):
    for name in ('source','parts','connection_ports','route_geometry','excluded_parts'):
        if original[name] != current[name]:
            raise ValueError('Model/connector data changed; rerun route preview before testing')


def validate_candidate(current_result, record):
    requested = point(record['point_ft'])
    for route in current_result['routes']:
        for station in route['stations']:
            if station['host_key'] == record['host_key'] and station['element_id'] == record['element_id']:
                actual = point(station['point_ft'])
                if max(abs(a-b) for a,b in zip(actual,requested)) <= 1e-6:
                    return
    raise ValueError('Candidate is no longer proposed; rerun preview before testing')
