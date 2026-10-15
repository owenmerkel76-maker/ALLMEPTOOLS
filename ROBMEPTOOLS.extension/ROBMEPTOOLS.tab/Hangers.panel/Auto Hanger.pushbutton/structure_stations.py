# -*- coding: utf-8 -*-
"""Bounded station proposals and run-wide coverage; geometry grants approval.

Boxes seed search positions only. The caller must test a real fabrication
hanger at each candidate, including every rod, and roll the probe back.
"""


def _merge(intervals):
    result=[]
    for lo,hi in sorted(intervals):
        if hi<lo:
            continue
        if result and lo<=result[-1][1]+1e-8:
            result[-1]=(result[-1][0],max(hi,result[-1][1]))
        else:
            result.append((lo,hi))
    return result


def _ray_band(base, direction, bounds, low, high):
    """Station deltas for which the rod XY is inside a supplied host box."""
    for coordinate,axis,lo,hi in ((base[0],direction[0],bounds[0],bounds[1]),
                                  (base[1],direction[1],bounds[2],bounds[3])):
        if abs(axis)<1e-10:
            if not lo<=coordinate<=hi:
                return None
        else:
            a,b=(lo-coordinate)/axis,(hi-coordinate)/axis
            low,high=max(low,min(a,b)),min(high,max(a,b))
            if low>high:
                return None
    return low,high


def candidate_jobs(planning, run, job, rod_bases, bounds, blocked=None,
                   branches=None, existing=None, limit=24):
    """Nearby SAME-piece jobs, max 4 ft shift, boxes plus bounded samples.

    Common bands require a possible box for every rod, including different
    members for different rods. Geometry still decides every candidate.
    """
    if limit<1:
        return []
    station=job['station']
    radius=min(4.0,job['max_spacing']/2.0)
    low,high=-radius,radius
    common=[(low,high)] if rod_bases else []
    for base in rod_bases:
        bands=[]
        for box in bounds:
            band=_ray_band(base,run['direction'],box,low,high)
            if band is not None:
                bands.append(band)
        common=_merge((max(a,c),min(b,d)) for a,b in common for c,d in _merge(bands)
                      if max(a,c)<=min(b,d))
    seeds=[station]
    common=sorted(common,key=lambda band:abs((band[0]+band[1])/2.0))
    # Visit each possible crossing before spending the budget on its edges
    # and interior; otherwise the first band can hide a valid opposite crossing.
    seeds.extend(station+(lo+hi)/2.0 for lo,hi in common)
    edges=[]; interiors=[]
    for lo,hi in common:
        edges.extend(delta for delta in (lo+.01,hi-.01) if lo<=delta<=hi)
        # Actual joist meshes can have openings; sample inside the screen band.
        n=min(16,max(1,int((hi-lo)/.125)))
        interiors.extend(lo+(hi-lo)*i/float(n) for i in range(1,n))
    seeds.extend(station+delta for delta in sorted(edges,key=abs))
    seeds.extend(station+delta for delta in sorted(interiors,key=abs))
    # If boxes are wrong, small-selection exact checks can still find a target.
    # Alternate directions so neither end consumes the bounded search budget.
    step=.25
    for index in range(1,int(radius/step)+1):
        seeds.extend((station-index*step,station+index*step))
    seen=set(); jobs=[]
    for proposed in seeds:
        if abs(proposed-station)>radius+1e-7:
            continue
        found=planning.locate_piece(run,proposed)
        if found is None:
            continue
        piece,from_a,actual=found
        if piece['id']!=job['piece']['id'] or abs(actual-proposed)>.02:
            continue
        key=round(actual,6)
        if key in seen:
            continue
        seen.add(key)
        if any(a-1e-6<actual<b+1e-6 for a,b in (blocked or [])):
            continue
        if any(abs(actual-b)<.75-1e-6 for b in (branches or [])):
            continue
        if any(abs(actual-e)<=.75 for e in (existing or [])):
            continue
        candidate=dict(job,station=actual,from_a=from_a)
        jobs.append(candidate)
        if len(jobs)>=limit:
            break
    return jobs


def select_layout(groups, originals, length, maximum, branches=None,
                  existing=None, end_limits=(2.0,2.0)):
    """Choose one measured candidate per job with complete run coverage.

    Dynamic programming minimizes total station movement. Existing stations
    preserve physical occupancy; they are not proof of approved attachment.
    """
    if not groups or any(not group for group in groups):
        return None
    existing=sorted(s for s in (existing or []) if 0<=s<=length)
    branches=[s for s in (branches or []) if 0<s<length]

    def gap_ok(stations):
        if any(b-a>maximum+1e-6 for a,b in zip(stations,stations[1:])):
            return False
        return all(min(abs(s-b) for s in stations)<=4.0+1e-6
                   for b in branches if stations[0]<=b<=stations[-1])

    def prefix_ok(s):
        stations=[e for e in existing if e<s]+[s]
        return (stations[0]<=end_limits[0]+1e-6 and gap_ok(stations) and
                all(stations[0]-b<=4.0+1e-6 for b in branches if b<stations[0]))

    def edge_ok(a,b):
        return b-a>.75 and gap_ok([a]+[e for e in existing if a<e<b]+[b])

    def suffix_ok(s):
        stations=[s]+[e for e in existing if e>s]
        return (length-stations[-1]<=end_limits[1]+1e-6 and gap_ok(stations) and
                all(b-stations[-1]<=4.0+1e-6 for b in branches if b>stations[-1]))

    states=[]
    for index,group in enumerate(groups):
        next_states=[]
        for job in sorted(group,key=lambda j:j['station']):
            s=job['station']
            if any(abs(s-e)<=.75 for e in existing):
                continue
            cost=abs(s-originals[index]['station'])
            if index==0:
                if prefix_ok(s):
                    next_states.append((cost,[job]))
            else:
                paths=[(old_cost+cost,path+[job]) for old_cost,path in states
                       if edge_ok(path[-1]['station'],s)]
                if paths:
                    next_states.append(min(paths,key=lambda item:item[0]))
        states=next_states
        if not states:
            return None
    complete=[state for state in states if suffix_ok(state[1][-1]['station'])]
    return min(complete,key=lambda item:item[0])[1] if complete else None
