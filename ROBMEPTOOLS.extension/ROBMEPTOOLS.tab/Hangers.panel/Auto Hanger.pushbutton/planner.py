# -*- coding: utf-8 -*-
"""Pure-Python geometric hanger planner. No Revit dependencies.

SMACNA-informed, *not* a certification or hardware load calculation.
Dimensions and coordinates are in feet.
"""
import math

JOIN_TOL = 2.0 / 12.0       # consecutive selected duct straights
PARALLEL_DOT = 0.996       # do not join on a direction change
SIZE_TOL = 0.5 / 12.0     # do not join through size changes
POINT_EPS = 1e-6


def dot(a, b):
    return a[0]*b[0]+a[1]*b[1]+a[2]*b[2]


def sub(a, b):
    return (a[0]-b[0], a[1]-b[1], a[2]-b[2])


def add(a, b):
    return (a[0]+b[0], a[1]+b[1], a[2]+b[2])


def mul(a, s):
    return (a[0]*s, a[1]*s, a[2]*s)


def norm(a):
    return math.sqrt(dot(a, a))


def distance(a, b):
    return norm(sub(a, b))


def unit(a):
    n = norm(a)
    return mul(a, 1.0/n) if n > POINT_EPS else (0, 0, 0)


def projections(p, start, direct):
    return dot(sub(p, start), direct)


def rule_spacing(shape, width_ft, height_ft, user_cap_ft):
    """Return (preliminary feet, note). No load/rod sizing performed.

    Rectangular: Table 5-1 has hardware-dependent alternatives for 4/5/8/10ft.
    Round: Table 5-2 permits 12ft for listed size ranges *with matching
    hanger hardware*. We conservatively cap placements pending verification.
    Flat-oval: use 4ft preliminary; review its construction & hardware.
    """
    if user_cap_ft <= 0:
        return None, 'Invalid user spacing cap'
    if shape == 'round':
        dia_in = width_ft * 12.0
        if dia_in < 0.25 or dia_in > 96:
            return None, 'Round size is outside reviewed table range'
        if dia_in <= 24:
            return min(user_cap_ft, 10.0), 'Round preliminary; hardware review required'
        if dia_in <= 36:
            return min(user_cap_ft, 8.0), 'Round preliminary; hardware review required'
        if dia_in <= 60:
            return min(user_cap_ft, 6.0), 'Large round; hanger capacity review required'
        return min(user_cap_ft, 4.0), 'Very large round; engineering review required'
    if shape == 'rectangular':
        halfper_in = (width_ft + height_ft) * 12.0
        if halfper_in < 0.5 or halfper_in > 192:
            return None, 'Rectangular half-perimeter outside reviewed table range'
        if halfper_in <= 72:
            return min(user_cap_ft, 8.0), 'Rectangular preliminary; hanger capacity review required'
        if halfper_in <= 120:
            return min(user_cap_ft, 5.0), 'Large rectangular; hanger capacity review required'
        return min(user_cap_ft, 4.0), 'Very large rectangular; engineering review required'
    if shape == 'oval':
        if width_ft <= 0 or height_ft <= 0:
            return None, 'Unknown oval size'
        return min(user_cap_ft, 4.0), 'Oval preliminary; project hanger schedule required'
    return None, 'Unknown duct profile'


def contiguous(a, b):
    if a['shape'] != b['shape'] or abs(a['w']-b['w']) > SIZE_TOL or abs(a['h']-b['h']) > SIZE_TOL:
        return False
    # Services must remain separate even on geometrically continuous ducts.
    if a.get('service_id') != b.get('service_id'):
        return False
    ad = unit(sub(a['b'], a['a']))
    bd = unit(sub(b['b'], b['a']))
    if abs(dot(ad, bd)) < PARALLEL_DOT:
        return False
    for p in (a['a'], a['b']):
        for q in (b['a'], b['b']):
            if distance(p, q) < JOIN_TOL:
                return True
    return False


def group_runs(segments):
    """Group collinear, same-size selected straights at coincident endpoints.
    Stops at elbows/size transitions, branches, gaps and direction changes.
    """
    n = len(segments)
    parent = list(range(n))
    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    def unite(i,j):
        ri,rj = root(i),root(j)
        if ri != rj:
            parent[rj] = ri

    # Endpoint bucket candidate pairs to avoid quadratic all-to-all geometry.
    # Bucket at 2*join tolerance then compare exact distance.
    cell = JOIN_TOL * 2
    buckets = {}
    for i,s in enumerate(segments):
        for p in (s['a'],s['b']):
            k = tuple(int(math.floor(x/cell)) for x in p)
            for dx in (-1,0,1):
                for dy in (-1,0,1):
                    for dz in (-1,0,1):
                        for j in buckets.get((k[0]+dx,k[1]+dy,k[2]+dz), []):
                            if i != j and contiguous(segments[i], segments[j]):
                                unite(i,j)
            buckets.setdefault(k, []).append(i)

    grouped = {}
    for i,s in enumerate(segments):
        grouped.setdefault(root(i),[]).append(s)
    result=[]
    for group in grouped.values():
        first=group[0]
        d = unit(sub(first['b'],first['a']))
        # Canonical orientation stable between runs (flip if negative sum)
        if (d[0] < -POINT_EPS or (abs(d[0]) < POINT_EPS and d[1] < -POINT_EPS)):
            d = mul(d,-1)
        base=first['a']
        ends=[]
        for piece in group:
            ends.append(projections(piece['a'],base,d))
            ends.append(projections(piece['b'],base,d))
        low, high = min(ends),max(ends)
        start=add(base,mul(d,low))
        ordered=[]
        for piece in group:
            lo=min(projections(piece['a'],start,d), projections(piece['b'],start,d))
            hi=max(projections(piece['a'],start,d), projections(piece['b'],start,d))
            ordered.append((lo,hi,piece))
        ordered.sort(key=lambda x:x[0])
        # Do not bridge over gaps: the group union should only join adjacency,
        # but return disjoint components safely as separate runs if needed.
        chunk=[]
        end=-1e10
        for item in ordered:
            if chunk and item[0]-end > JOIN_TOL:
                rebase=min(t[0] for t in chunk)
                shifted=[(t[0]-rebase,t[1]-rebase,t[2]) for t in chunk]
                result.append({'origin':add(start,mul(d,rebase)),
                               'direction':d, 'pieces':shifted})
                chunk=[]
            chunk.append(item)
            end=max(end,item[1])
        if chunk:
            rebase=min(t[0] for t in chunk)
            shifted=[(t[0]-rebase,t[1]-rebase,t[2]) for t in chunk]
            result.append({'origin':add(start,mul(d,rebase)),
                           'direction':d, 'pieces':shifted})
    return result


def plan_positions(length_ft, max_span_ft, end_offset_ft, branch_stations=None):
    """Propose run-wide stations including end and branch supports.

    The 1 ft side-of-branch preference is a coordination clearance, not a
    dimension claimed to be in SMACNA. Figure 5-13 says do not support exactly
    opposite of a branch; it does not prescribe that lateral clearance.
    """
    if length_ft < 0.5 or max_span_ft <= 0:
        return []
    edge = min(end_offset_ft, length_ft / 2.0)
    left, right = edge, length_ft - edge
    if right - left < max(1.0, max_span_ft * 0.32):
        planned = [length_ft / 2.0]
    else:
        planned = [left, right]
    for s in sorted(set(branch_stations or [])):
        if not 0.1 < s < length_ft - 0.1:
            continue
        # If no existing hanger is close to the intersection, add a side
        # hanger within the 4 ft branch-support limit (prefer about 1 ft).
        if min(abs(x - s) for x in planned) > 3.0:
            candidates = [s - 1.0, s + 1.0]
            candidates = [x for x in candidates if 0.26 < x < length_ft - 0.26]
            if candidates:
                planned.append(min(candidates, key=lambda x: min(abs(x-y) for y in planned)))
    planned = sorted(set(planned))
    out = [planned[0]]
    for b in planned[1:]:
        a = out[-1]
        gaps = int(math.ceil((b-a)/max_span_ft))
        if gaps > 1:
            for i in range(1,gaps):
                out.append(a+(b-a)*float(i)/gaps)
        out.append(b)
    return out


def locate_piece(run, station_ft, minimum_clearance_ft=3.0/12.0):
    """Return (piece, length from 'a', adjusted station), or None.

    Adjust a candidate on a fabrication connector to a legal position inside
    the neighboring duct. Do not drop the midpoint hanger at a shop seam.
    """
    origin,d=run['origin'],run['direction']
    opts=[]
    for lo,hi,segment in run['pieces']:
        vec=sub(segment['b'],segment['a'])
        l=norm(vec)
        if l < 2*minimum_clearance_ft:
            continue
        # Adjust close-to-connector planned positions inward.
        legal_lo=lo+minimum_clearance_ft+0.005
        legal_hi=hi-minimum_clearance_ft-0.005
        if legal_lo > legal_hi:
            continue
        candidate=max(legal_lo,min(legal_hi,station_ft))
        actual=add(origin,mul(d,candidate))
        projection=dot(sub(actual,segment['a']),unit(vec))
        gap=norm(sub(actual,add(segment['a'],mul(unit(vec),projection))))
        if gap <= JOIN_TOL and minimum_clearance_ft < projection < l-minimum_clearance_ft:
            opts.append((abs(candidate-station_ft),gap,segment,projection,candidate))
    if not opts:
        return None
    opts.sort(key=lambda o:(o[0],o[1]))
    _,_,segment,projection,candidate=opts[0]
    return segment,projection,candidate


def blocked_interval_from_bbox(run, bmin, bmax, lateral_ft, below_ft,
                               rise_ft, along_clearance_ft=0.5):
    """Conservative 3-D AABB -> occupied length of a horizontal duct run.

    Axis-aligned boxes are BROAD-PHASE only: a returned occupied interval does
    not prove contact, and a clear interval does not certify a rod-free path.
    `lateral_ft` includes the duct half-width + provisional hanger side room.
    """
    axis=run['direction']
    origin=run['origin']
    length=max(piece[1] for piece in run['pieces'])
    if bmax[2] < origin[2]-below_ft or bmin[2] > origin[2]+rise_ft:
        return None
    sideways=(-axis[1],axis[0],0.0)
    transverse=[]
    stations=[]
    for x in (bmin[0],bmax[0]):
        for y in (bmin[1],bmax[1]):
            p=(x,y,origin[2])
            transverse.append(dot(sub(p,origin),sideways))
            stations.append(projections(p,origin,axis))
    if min(transverse)>lateral_ft or max(transverse)<-lateral_ft:
        return None
    lo=max(0.0,min(stations)-along_clearance_ft)
    hi=min(length,max(stations)+along_clearance_ft)
    if lo >= hi:
        return None
    return (lo,hi)


def legal_station_intervals(run, blocked_intervals=None,
                            connector_clearance_ft=3.0/12.0):
    """Legal inboard stations after avoiding fittings, side taps and ducts."""
    pieces=[]
    for lo,hi,_ in run['pieces']:
        low=lo+connector_clearance_ft+0.005
        high=hi-connector_clearance_ft-0.005
        if high>=low:
            pieces.append((low,high))
    for begin,end in sorted(blocked_intervals or []):
        nextpieces=[]
        for lo,hi in pieces:
            if end<=lo or begin>=hi:
                nextpieces.append((lo,hi))
                continue
            if begin>lo:
                nextpieces.append((lo,min(begin,hi)))
            if end<hi:
                nextpieces.append((max(end,lo),hi))
        pieces=nextpieces
    return pieces


def _nearest_clear_job(run, proposed, maximum, blocked_intervals=None,
                       low=None, high=None):
    """Find a legal physical duct station, never in a side-tap clearance band."""
    if not blocked_intervals:
        j=_make_job(run,proposed,maximum)
        if j is not None and (low is None or j['station']>=low-1e-6) and (high is None or j['station']<=high+1e-6):
            return j
        return None
    options=[]
    for a,b in legal_station_intervals(run,blocked_intervals):
        lo=max(a,low) if low is not None else a
        hi=min(b,high) if high is not None else b
        if hi < lo+1e-6:
            continue
        # A small interior inset avoids placing exactly on collision envelope.
        candidate=max(lo+0.003,min(hi-0.003,proposed)) if hi-lo>0.006 else (hi+lo)/2
        j=_make_job(run,candidate,maximum)
        if j is not None and lo-1e-6<=j['station']<=hi+1e-6:
            options.append((abs(j['station']-proposed),j))
    if not options:
        return None
    options.sort(key=lambda item:(item[0],item[1]['station']))
    return options[0][1]


def _make_job(run, proposed, maximum):
    found=locate_piece(run, proposed)
    if found is None:
        return None
    piece, from_a, actual=found
    return {'station':actual,'piece':piece,'from_a':from_a,
            'max_spacing':maximum}


def _fix_stations(run, jobs, maximum, length, branches, notes, blocked_intervals=None):
    """Re-check real hanger locations after snapping them off fab joints."""
    if not jobs:
        return [], 'No eligible hanger stations'
    # Avoid a planned support directly across from a side branch. This is an
    # office placement preference of 9 in (not a prescribed SMACNA distance).
    for branch in branches:
        for i,job in enumerate(jobs):
            if abs(job['station']-branch)>=0.75:
                continue
            choices=[]
            for away in (0.85, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0):
                for target in (branch-away,branch+away):
                    if not 0.26 < target < length-0.26:
                        continue
                    candidate=_nearest_clear_job(run,target,maximum,blocked_intervals)
                    if candidate and all(abs(candidate['station']-other)>=0.75
                                         for other in branches):
                        # Preserve end proximity and avoid near-duplicate jobs.
                        others=[j for k,j in enumerate(jobs) if k!=i]
                        if others and min(abs(j['station']-candidate['station']) for j in others)<0.35:
                            continue
                        spacing_penalty=0.0
                        if others:
                            joined=sorted([j['station'] for j in others]+[candidate['station']])
                            spacing_penalty=max(0.0,max(joined[z+1]-joined[z] for z in range(len(joined)-1))-maximum)
                        end_penalty=max(0.0,candidate['station']-2.0) if i==0 else 0.0
                        end_penalty+=max(0.0,length-candidate['station']-2.0) if i==len(jobs)-1 else 0.0
                        choices.append((spacing_penalty*10+end_penalty*5+
                                        abs(candidate['station']-job['station']),candidate))
            if choices:
                choices.sort(key=lambda c:c[0])
                jobs[i]=choices[0][1]
            else:
                if 'Branch support opposite takeoff: manual relocation needed' not in notes:
                    notes.append('Branch support opposite takeoff: manual relocation needed')
    # Put an additional support close to each end if a connector adjustment
    # left its nearest support >2 ft away. If there is no legal station,
    # retain existing jobs but warn; NEVER represent it as compliant.
    for target,left_side in ((min(1.0,length/2.0),True),
                             (max(length-1.0,length/2.0),False)):
        jobs.sort(key=lambda j:j['station'])
        gap=jobs[0]['station'] if left_side else length-jobs[-1]['station']
        if gap <= 2.0+1e-5:
            continue
        candidate=_nearest_clear_job(run,target,maximum,blocked_intervals)
        if candidate and (candidate['station'] <= 2.0+1e-5 if left_side
                          else length-candidate['station'] <= 2.0+1e-5):
            if min(abs(j['station']-candidate['station']) for j in jobs)>=0.3:
                jobs.append(candidate)
    # Moving a hanger off a joint or branch can increase a gap. Keep filling
    # the gap only when Revit's fabrication host has a legal station.
    for attempt in range(30):
        jobs.sort(key=lambda j:j['station'])
        # Collapse snapped duplicate jobs, never place two hangers at a seam.
        dedup=[]
        for job in jobs:
            if not dedup or job['station']-dedup[-1]['station']>0.25:
                dedup.append(job)
        jobs=dedup
        gaps=[(jobs[i+1]['station']-jobs[i]['station'],i)
              for i in range(len(jobs)-1)]
        if not gaps:
            break
        biggest,index=max(gaps)
        if biggest<=maximum+1e-5:
            break
        mid=(jobs[index]['station']+jobs[index+1]['station'])/2.0
        candidate=_nearest_clear_job(run,mid,maximum,blocked_intervals,
                                     low=jobs[index]['station']+0.30,
                                     high=jobs[index+1]['station']-0.30)
        if candidate is None or min(abs(j['station']-candidate['station']) for j in jobs)<0.30:
            return [], 'Cannot resolve excessive support gap after joint/branch adjustment'
        jobs.append(candidate)
    else:
        return [], 'Exceeded support gap repair attempts'
    jobs.sort(key=lambda j:j['station'])
    if jobs[0]['station']>2.0+1e-5 or length-jobs[-1]['station']>2.0+1e-5:
        notes.append('Run end has no support within 2 ft; check elbows and short pieces')
    for s in branches:
        if min(abs(j['station']-s) for j in jobs)>4.0+1e-5:
            notes.append('Branch has no support within 4 ft; manual layout required')
        if any(abs(j['station']-s)<0.75 for j in jobs):
            if 'Support opposite branch; manual clearance check required' not in notes:
                notes.append('Support opposite branch; manual clearance check required')
    return jobs, None


def plan_run(run, user_cap_ft=8.0, end_offset_ft=1.5, branch_stations=None,
             blocked_intervals=None):
    parts=run['pieces']
    if not parts:
        return [], 'Empty run'
    maxs=[]
    notes=[]
    for _,_,piece in parts:
        m,note=rule_spacing(piece['shape'],piece['w'],piece['h'],user_cap_ft)
        if m is None:
            return [],note
        maxs.append(m)
        if note not in notes:
            notes.append(note)
    maximum=min(maxs)
    length=max(x[1] for x in parts)-min(x[0] for x in parts)
    branches=sorted(set(s for s in (branch_stations or []) if 0<s<length))
    blocked_intervals=blocked_intervals or []
    if blocked_intervals and not legal_station_intervals(run,blocked_intervals):
        return [], 'No legal hanger locations after 3D side-tap clearance screening'
    desired=plan_positions(length,maximum,end_offset_ft,branches)
    jobs=[]
    for station in desired:
        candidate=_nearest_clear_job(run,station,maximum,blocked_intervals)
        if candidate is None:
            return [],'Could not locate a legal station clear of fittings, connectors and side taps'
        jobs.append(candidate)
    jobs,error=_fix_stations(run,jobs,maximum,length,branches,notes,blocked_intervals)
    if error:
        return [],error
    if blocked_intervals:
        if any(any(a-1e-6 < j['station'] < b+1e-6
                   for a,b in blocked_intervals) for j in jobs):
            return [],'A station intersects a side-tap/duct collision envelope'
        if len(jobs)>1 and any(jobs[i+1]['station']-jobs[i]['station']>maximum+1e-5
                               for i in range(len(jobs)-1)):
            return [],'Cannot preserve support spacing around side-tap clearance zones'
    # Never auto-place a layout with a known unresolved Chapter 5 proximity or
    # directly-opposite-branch conflict. The branch detector is heuristic, so
    # leave a diagnostic for human resolution rather than implying compliance.
    unsafe_branch_flags=('manual relocation needed','manual clearance check required')
    if any(any(flag in msg for flag in unsafe_branch_flags) for msg in notes):
        return [],'Manual branch conflict (run withheld): '+'; '.join(
            msg for msg in notes if any(flag in msg for flag in unsafe_branch_flags))
    incomplete_support_flags=('no support within 4 ft','no support within 2 ft')
    if any(any(flag in msg for flag in incomplete_support_flags) for msg in notes):
        # v0.3.5 withheld EVERY hanger when one run end had no near support.
        # Keep other legal stations and FLAG missing endpoint/branch support;
        # this remains a partial layout requiring manual coordination.
        return jobs,'PARTIAL SUPPORT - MANUAL REVIEW REQUIRED: '+'; '.join(
            msg for msg in notes if any(flag in msg for flag in incomplete_support_flags))
    return jobs,'; '.join(notes)


def button_name_from_label(label):
    """UI label includes a palette and a stable palette/button position suffix."""
    name=str(label).split('  /  ')[-1]
    return name.split('  [P')[0]


def normalized_button_name(label):
    return ''.join(c for c in button_name_from_label(label).lower()
                   if c.isalnum())


def is_trapeze_button_label(label):
    name=normalized_button_name(label)
    return 'trapeze' in name or name.startswith('trap')


def guess_hanger_choice(labels, shape):
    """Safely auto-select a real loaded button, by shape and precise button name.

    Half Strap Hanger wins over Half Strap Hanger_4in for rectangular,
    mirroring the user's selected palette button. Round and oval duct get
    their proper profile-specific straps instead of an unverified rect strap.
    """
    prefs={
        'rectangular':('halfstraphanger','halfstrap','trapezehanger','trapeze'),
        'round':('roundstraphanger','roundstrap','roundwirehanger','roundwire',
                 'unistruthangerround','trapezehangerround'),
        'oval':('ovalstraphanger','ovalstrap'),
        'trapeze':('trapezehanger','trapeze')
    }
    names=[normalized_button_name(label) for label in labels]
    def eligible(name,shape):
        if shape=='trapeze':
            return ('trapeze' in name and 'round' not in name)
        if shape=='rectangular':
            return 'round' not in name and 'oval' not in name
        if shape=='round':
            return 'round' in name
        if shape=='oval':
            return 'oval' in name
        return False
    for keyword in prefs.get(shape,()):
        for i in range(1,len(labels)):
            name=names[i]
            if name==keyword and eligible(name,shape):
                return i
        for i in range(1,len(labels)):
            name=names[i]
            if keyword in name and eligible(name,shape):
                return i
    return 0


def optimize_support_count(jobs, existing_stations, length, max_spacing, branch_stations=None,
                           end_limit=2.0, end_limits=None):
    """Remove *provably redundant* planned supports on one continuous run.

    Keep start/end proximity, the maximum support span and branch coverage.
    Existing hanger stations count before any new hanger is proposed. An
    unsupported or unverified existing DRAFT still prevents duplicate model
    insertion; this is coordination-only, NOT structural compliance approval.
    """
    existing=sorted(x for x in (existing_stations or []) if -.05<=x<=length+.05)
    pending=sorted(jobs,key=lambda j:j['station'])
    branches=[x for x in (branch_stations or []) if 0<x<length]
    left_limit,right_limit=end_limits if end_limits is not None else (end_limit,end_limit)

    def valid(left):
        stations=sorted(existing+[j['station'] for j in left])
        if not stations:
            return False
        if stations[0]>left_limit+1e-6 or length-stations[-1]>right_limit+1e-6:
            return False
        if any(b-a>max_spacing+1e-6 for a,b in zip(stations,stations[1:])):
            return False
        if any(min(abs(s-b) for s in stations)>4.0+1e-6 for b in branches):
            return False
        return True

    # Near-coincident stations are easiest redundancies. Then remove from
    # center outward, preferring to keep supports toward physical run ends.
    while len(pending)>0:
        removable=[]
        for index,j in enumerate(pending):
            remain=pending[:index]+pending[index+1:]
            if valid(remain):
                s=j['station']
                covered=min([abs(s-t['station']) for t in remain]+[
                    abs(s-t) for t in existing] or [1e9])
                # Remove duplicates and central stations first.
                removable.append((covered,abs(s-length*.5),index))
        if not removable:
            break
        removable.sort()
        pending.pop(removable[0][2])
    return pending
