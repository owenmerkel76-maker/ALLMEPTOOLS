# -*- coding: utf-8 -*-
"""Read-only, horizontal straight-through route planning. No Autodesk imports.

A fitting chord is accepted only when both connector normals align with it.
Turns, offsets, gaps and ambiguous ports are boundaries, never invented lengths.
Existing supports are coordination records, not verified structural supports.
"""
import math

ACCESSORY_TOKENS = ('damper', 'fire smoke', 'fire/smoke', 'smoke/fire',
                    'access door', 'access panel', 'volume control',
                    'vcd', 'fsd', 'sdd', 'backdraft', 'back draft',
                    'sleeve', 'silencer', 'attenuator', 'sensor',
                    'terminal unit', 'vav ', 'balancing damper')


def _finite(value):
    value = float(value)
    if math.isnan(value) or math.isinf(value):
        raise ValueError('Nonfinite route geometry')
    return value


def _point(value):
    result = tuple(_finite(v) for v in value)
    if len(result) != 3:
        raise ValueError('Expected three host-world coordinates')
    return result


def _sub(a, b):
    return tuple(a[i] - b[i] for i in range(3))


def _dot(a, b):
    return sum(a[i] * b[i] for i in range(3))


def _norm(a):
    return math.sqrt(_dot(a, a))


def _unit(a):
    length = _norm(a)
    if length < 1e-9:
        raise ValueError('Zero route axis')
    return tuple(v / length for v in a)


def _lane(part, geometry):
    if geometry.get('reason'):
        raise ValueError(geometry['reason'])
    if geometry.get('category') != 'duct':
        raise ValueError('PIPE_PLACEMENT_NOT_IN_THIS_PREVIEW')
    ends = sorted((p for p in geometry['ports'] if p['type'] == 'end'), key=lambda p: p['id'])
    if len(ends) != 2:
        raise ValueError('BRANCH_OR_AMBIGUOUS_ENDS')
    a, b = [_point(p['origin_ft']) for p in ends]
    direct = _unit(_sub(b, a))
    if abs(direct[2]) > 1e-6:
        raise ValueError('SLOPED_OR_VERTICAL_ROUTE_NOT_SUPPORTED')
    if not geometry.get('service'):
        raise ValueError('MISSING_ROUTE_SERVICE')
    if part['kind'] != 'straight':
        if len(geometry['ports']) != 2:
            raise ValueError('BRANCH_OR_AMBIGUOUS_FITTING')
        for port in ends:
            if port.get('normal') is None:
                raise ValueError('FITTING_NORMAL_UNREADABLE')
            normal = _unit(_point(port['normal']))
            if abs(_dot(normal, direct)) < 1. - 1e-8:
                raise ValueError('TURN_OR_OFFSET_FITTING_UNVERIFIED')
    labels = ' '.join(geometry.get('product_labels', [])).lower()
    hostable = part['kind'] == 'straight' and not any(t in labels for t in ACCESSORY_TOKENS)
    return dict(a=a, b=b, direct=direct, ends=ends, geometry=geometry,
                hostable=hostable, part=part)


def build_route_preview(snapshot, existing, planner, spacing_cap_ft=8., end_offset_ft=1.5):
    """Return geometric candidate stations only, never an apply-ready plan.

    Scope cuts do not force users to select an entire system. They bound a
    partial route and remain visible warnings. Branch offsets use the existing
    planner's preliminary four-foot proximity rule plus a half-foot keep-out;
    neither represents a reviewed company profile or a hardware clearance test.
    """
    cap, offset = _finite(spacing_cap_ft), _finite(end_offset_ft)
    if not 2. <= cap <= 12. or not .5 <= offset <= 2.:
        raise ValueError('Spacing cap must be 2-12 ft; end target must be 0.5-2 ft')
    tolerance = 1e-4
    records = dict((p['key'], p) for p in snapshot['parts'])
    geometry = snapshot.get('route_geometry', {})
    lanes, issues = {}, []
    for key in sorted(records):
        try:
            lanes[key] = _lane(records[key], geometry.get(key, {'reason':'ROUTE_GEOMETRY_UNAVAILABLE'}))
        except (KeyError, TypeError, ValueError) as ex:
            issues.append({'keys':[key], 'reason':str(ex)})
    neighbors = dict((k, set()) for k in lanes)
    boundaries = dict((k, set()) for k in lanes)
    branches = dict((k, []) for k in lanes)
    edge_ports = {}
    for edge in snapshot.get('connection_ports', []):
        a, b = edge['keys']; pa, pb = edge['port_ids']
        ports = []
        for key, cid in ((a, pa), (b, pb)):
            g = geometry.get(key, {})
            ports.append(next((p for p in g.get('ports', []) if p['id'] == cid), None))
        if a not in lanes or b not in lanes:
            for key, port in zip((a,b), ports):
                if key in lanes:
                    boundaries[key].add('SELECTED_SCOPE_OR_UNSUPPORTED_NEIGHBOR')
                    if port is not None and port['type'] != 'end':
                        branches[key].append(_point(port['origin_ft']))
            continue
        if any(p is None for p in ports):
            raise ValueError('Physical edge has no captured connector geometry')
        if any(p['type'] != 'end' for p in ports):
            for key, port in zip((a,b), ports):
                boundaries[key].add('BRANCH_CONNECTION')
                branches[key].append(_point(port['origin_ft']))
            continue
        reason = None
        if _finite(edge['gap_ft']) > tolerance:
            reason = 'CONNECTED_ORIGIN_GAP_NOT_TRAVERSED'
        elif records[a]['source'] != records[b]['source']:
            reason = 'SOURCE_BOUNDARY'
        elif lanes[a]['geometry']['service'] != lanes[b]['geometry']['service']:
            reason = 'SERVICE_BOUNDARY'
        elif abs(_dot(lanes[a]['direct'], lanes[b]['direct'])) < 1. - 1e-8:
            reason = 'DIRECTION_BOUNDARY'
        if reason:
            boundaries[a].add(reason); boundaries[b].add(reason)
        else:
            neighbors[a].add(b); neighbors[b].add(a)
            edge_ports[(a,b)] = (pa,pb); edge_ports[(b,a)] = (pb,pa)
    # Owner graphs cannot resolve a fork or multiple peers on a single end.
    ambiguous = set(k for k in lanes if len(neighbors[k]) > 2)
    for k in lanes:
        cids = [edge_ports[(k,n)][0] for n in neighbors[k]]
        if len(set(cids)) != len(cids):
            ambiguous.add(k)
    for key in ambiguous:
        boundaries[key].add('AMBIGUOUS_END_CONNECTIONS')
        for other in list(neighbors[key]):
            neighbors[other].discard(key); boundaries[other].add('AMBIGUOUS_NEIGHBOR')
        neighbors[key].clear()
    routes, remaining = [], set(lanes) - ambiguous
    while remaining:
        seed = min(remaining); component = set(); pending = [seed]
        while pending:
            key = pending.pop()
            if key in component:
                continue
            component.add(key); pending.extend(neighbors[key] - component)
        remaining.difference_update(component)
        ends = sorted(k for k in component if len(neighbors[k]) < 2)
        if not ends:
            issues.append({'keys':sorted(component), 'reason':'CLOSED_LOOP_NOT_PLANNED'}); continue
        ordered = []; previous = None; current = ends[0]
        while current is not None:
            ordered.append(current)
            nexts = sorted(neighbors[current] - set([previous]))
            previous, current = current, nexts[0] if nexts else None
        # Leading/trailing non-hostable fittings are outside the supported axis
        # preview. Do not make their missing geometry into a false endpoint.
        host_indices = [i for i,k in enumerate(ordered) if lanes[k]['hostable']]
        if not host_indices:
            issues.append({'keys':ordered, 'reason':'NO_ELIGIBLE_STRAIGHT_DUCT'}); continue
        if host_indices[0] != 0 or host_indices[-1] != len(ordered)-1:
            issues.append({'keys':ordered, 'reason':'FITTING_OR_DEVICE_AT_ROUTE_END'}); continue
        first = lanes[ordered[0]]
        start_port = first['ends'][0]
        if len(ordered) > 1:
            joined = edge_ports[(ordered[0],ordered[1])][0]
            start_port = next(p for p in first['ends'] if p['id'] != joined)
        origin = _point(start_port['origin_ft'])
        other = first['b'] if start_port['id'] == first['ends'][0]['id'] else first['a']
        direct = _unit(_sub(other,origin))
        pieces = []; length = 0.; branch_stations = []; errors = set()
        for key in ordered:
            lane = lanes[key]
            positions = [_dot(_sub(p,origin),direct) for p in (lane['a'],lane['b'])]
            lo, hi = min(positions), max(positions)
            if abs(lo-length) > tolerance:
                errors.add('NONCONTINUOUS_ROUTE_AXIS')
            length = hi
            if lane['hostable']:
                p = lane['part']; size = p['size']
                piece = dict(id=p['element_id'], key=key, a=lane['a'], b=lane['b'],
                             shape=p['shape'], w=size[0], h=size[-1], service_id=p['service'])
                pieces.append((lo,hi,piece))
            for point in branches[key]:
                station = _dot(_sub(point,origin),direct)
                if lo - tolerance <= station <= hi + tolerance:
                    branch_stations.append(station)
                else:
                    errors.add('BRANCH_STATION_OUTSIDE_HOST')
            errors.update(boundaries[key])
        run = dict(origin=origin, direction=direct, pieces=pieces)
        blocked = [(max(0.,s-.5),min(length,s+.5)) for s in branch_stations]
        jobs, note = planner.plan_run(run,cap,offset,branch_stations,blocked)
        maximum = min(planner.rule_spacing(p['shape'],p['w'],p['h'],cap)[0]
                      for lo,hi,p in pieces) if jobs else None
        old = []; old_rows = []
        existing_issues = list(existing.get('global_issues', []))
        for row in existing.get('hangers', []):
            if row['host_key'] not in ordered:
                continue
            lane = lanes[row['host_key']]
            point = _point(row['point_ft'])
            local = _dot(_sub(point,lane['a']),lane['direct'])
            if not -.0001 <= local <= _norm(_sub(lane['b'],lane['a'])) + .0001:
                existing_issues.append('EXISTING_HANGER_ORIGIN_OUTSIDE_HOST'); continue
            station = _dot(_sub(point,origin),direct)
            old.append(station); old_rows.append(dict(row, station_ft=station))
        for row in existing.get('issues', []):
            if row.get('host_key') in ordered:
                existing_issues.append(row['reason'])
        # Unknown geometry or unreadable existing-host positions cannot justify
        # a claim that proposed stations are nonduplicate.
        fatal = bool(errors & set(['NONCONTINUOUS_ROUTE_AXIS','BRANCH_STATION_OUTSIDE_HOST'])) or bool(existing_issues)
        if fatal:
            jobs = []; errors.update(existing_issues)
        elif jobs:
            jobs = planner.optimize_support_count(jobs,old,length,maximum,branch_stations,
                                                  end_limits=(2.,2.))
            jobs = [j for j in jobs if not any(abs(j['station']-s) <= .25 for s in old)]
        stations = []
        for job in jobs:
            stations.append(dict(element_id=job['piece']['id'], host_key=job['piece']['key'],
                                 station_ft=job['station'], from_a_ft=job['from_a'],
                                 point_ft=tuple(origin[i]+direct[i]*job['station'] for i in range(3))))
        coverage = sorted(old+[j['station_ft'] for j in stations])
        complete = bool(coverage) and coverage[0] <= 2.+1e-6 and length-coverage[-1] <= 2.+1e-6
        if maximum is not None:
            complete = complete and all(b-a <= maximum+1e-6 for a,b in zip(coverage,coverage[1:]))
        else:
            complete = False
        if branch_stations:
            complete = complete and all(min([abs(s-b) for s in coverage] or [1e9]) <= 4.+1e-6
                                        for b in branch_stations)
        complete = complete and not fatal
        if not complete:
            errors.add('COORDINATION_COVERAGE_UNRESOLVED')
        if note:
            errors.add(note)
        routes.append(dict(keys=ordered,length_ft=length,maximum_ft=maximum,stations=stations,
                           existing=old_rows,branch_stations=branch_stations,
                           reasons=sorted(errors),coordination_coverage_complete=complete,
                           apply_ready=False))
    for key in sorted(ambiguous):
        issues.append({'keys':[key],'reason':'AMBIGUOUS_END_CONNECTIONS'})
    baseline_parts = []
    for key in sorted(lanes):
        lane = lanes[key]
        if lane['hostable']:
            part = lane['part']; size = part['size']
            baseline_parts.append(dict(id=part['element_id'],a=lane['a'],b=lane['b'],
                                       shape=part['shape'],w=size[0],h=size[-1],service_id=part['service']))
    baseline_groups = planner.group_runs(baseline_parts)
    baseline_jobs = sum(len(planner.plan_run(run,cap,offset)[0]) for run in baseline_groups)
    return dict(routes=routes,issues=issues,spacing_cap_ft=cap,end_offset_ft=offset,
                baseline_geometric_groups=len(baseline_groups),
                baseline_raw_station_count=baseline_jobs,
                branch_proximity_ft=4.,branch_keepout_ft=.5,apply_ready=False)
