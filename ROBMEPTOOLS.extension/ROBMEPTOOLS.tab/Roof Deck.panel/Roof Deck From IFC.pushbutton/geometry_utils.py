# coding: utf-8
"""Pure Python 2/3 XY boundary reconstruction utilities; lengths are Revit internal feet.
The utilities do not guess a rectangular roof when exact boundary extraction fails.
"""

import math

XY_TOL = 1.0 / 96.0  # 1/8 inch snap for noisy CAD vertex connectivity
MIN_AREA = 4.0       # sq ft; filters individual deck-flute polygons
SIMPLIFY_TOL = 1.0 / 32.0  # 3/8 inch, inside typical CAD geometry tolerance


def area(poly):
    s = 0.0
    for i in range(len(poly)):
        a = poly[i]
        b = poly[(i + 1) % len(poly)]
        s += a[0] * b[1] - b[0] * a[1]
    return 0.5 * s


def key(point, tol=XY_TOL):
    return (int(round(point[0] / tol)), int(round(point[1] / tol)))


def unkey(k, tol=XY_TOL):
    return (k[0] * tol, k[1] * tol)


def edge_key(a, b):
    if a <= b:
        return (a, b)
    return (b, a)


def _perp_distance(p, a, b):
    dx = b[0] - a[0]
    dy = b[1] - a[1]
    l = math.sqrt(dx * dx + dy * dy)
    if l < 1.0e-9:
        return math.sqrt((p[0]-a[0])**2 + (p[1]-a[1])**2)
    return abs(dx * (a[1]-p[1]) - (a[0]-p[0]) * dy) / l


def clean_ring(pts, tol=SIMPLIFY_TOL):
    pts = [(float(p[0]), float(p[1])) for p in pts]
    if len(pts) >= 2 and key(pts[0]) == key(pts[-1]):
        pts.pop()
    # Collapse consecutive coincident points
    uniq = []
    for p in pts:
        if not uniq or key(p) != key(uniq[-1]):
            uniq.append(p)
    if len(uniq) >= 2 and key(uniq[0]) == key(uniq[-1]):
        uniq.pop()
    if len(uniq) < 3:
        return []
    # Drop small collinear facets without erasing true right-angle notches.
    for dummy in range(4):
        if len(uniq) <= 3:
            break
        changed = False
        result = []
        n = len(uniq)
        for i in range(n):
            a, p, b = uniq[(i-1) % n], uniq[i], uniq[(i+1) % n]
            va = (p[0]-a[0], p[1]-a[1])
            vb = (b[0]-p[0], b[1]-p[1])
            dot = va[0] * vb[0] + va[1] * vb[1]
            if _perp_distance(p, a, b) <= tol and dot >= -1.0e-7:
                changed = True
                continue
            result.append(p)
        if len(result) < 3:
            break
        uniq = result
        if not changed:
            break
    return uniq


def _rings_from_edges(keys):
    """Return (rings, issues) after graph tracing. No convex-hull fallback."""
    adj = {}
    for a,b in keys:
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)
    bad = [p for p, connected in adj.items() if len(connected) != 2]
    if bad:
        return ([], 'Open/branching CAD boundaries at %d vertices (not safe to guess).' % len(bad))
    unused = set(keys)
    loops = []
    while unused:
        e = next(iter(unused))
        a, b = e
        start, prev, cur = a, a, b
        ring = [start]
        unused.remove(e)
        count = 0
        while cur != start:
            count += 1
            if count > len(adj) + 1:
                return ([], 'Broken CAD outline graph.')
            ring.append(cur)
            choices = [p for p in adj[cur] if p != prev]
            if len(choices) != 1:
                return ([], 'Ambiguous boundary junction.')
            nxt = choices[0]
            edge = edge_key(cur, nxt)
            if edge not in unused:
                return ([], 'Boundary intersects itself or is doubled.')
            unused.remove(edge)
            prev, cur = cur, nxt
        poly = clean_ring([unkey(k) for k in ring])
        if len(poly) >= 3 and abs(area(poly)) >= MIN_AREA:
            loops.append(poly)
    return (loops, '')


def mesh_boundary_rings(triangles, sign=1):
    """triangles: iterable of three (x,y) pairs with positive or negative XY winding.
    Neighboring face edges cancel. Only topology-complete watertight top skins succeed.
    """
    counts = {}
    used = 0
    for p0, p1, p2 in triangles:
        poly = [p0, p1, p2]
        da = area(poly)
        if sign * da <= 1.0e-9:
            continue
        pts = [key(p) for p in poly]
        if len(set(pts)) < 3:
            continue
        used += 1
        for i in range(3):
            a, b = pts[i], pts[(i + 1) % 3]
            e = edge_key(a,b)
            counts[e] = counts.get(e,0) + 1
    if not used:
        return ([], 'No oriented top triangles recovered.')
    boundary = [e for e, n in counts.items() if n % 2 == 1]
    if not boundary:
        return ([], 'Triangle edges all canceled; overlapping DXF meshes may be present.')
    return _rings_from_edges(boundary)


def line_boundary_rings(segments):
    # Deduplicate overlaid DXF edges rather than parity cancelling.
    edges = set()
    for a,b in segments:
        a,b = key(a),key(b)
        if a != b:
            edges.add(edge_key(a,b))
    if not edges:
        return ([], 'No edge lines available.')
    return _rings_from_edges(edges)


def point_inside(point, polygon):
    x,y = point
    inside = False
    for i in range(len(polygon)):
        ax, ay = polygon[i]
        bx, by = polygon[(i + 1) % len(polygon)]
        if (ay > y) != (by > y):
            xx = ax + (bx-ax) * (y-ay) / (by-ay)
            if xx > x:
                inside = not inside
    return inside


def unique_rings(rings):
    found = set()
    output = []
    for r in rings:
        cleaned = clean_ring(r)
        if len(cleaned) < 3 or abs(area(cleaned)) < MIN_AREA:
            continue
        # Dedup geometry even when the exported face outline has reversed winding.
        signature = tuple(sorted(key(p) for p in cleaned))
        if signature in found:
            continue
        found.add(signature)
        output.append(cleaned)
    return output


def group_rings(rings):
    """Returns groups [(outer, [holes...]),...]. Supports islands inside openings."""
    rings = unique_rings(rings)
    rings.sort(key=lambda x: -abs(area(x)))
    if not rings:
        return []
    parents = []
    for i, r in enumerate(rings):
        # Slightly nudge first point toward another vertex to avoid shared-edge ambiguity.
        a = r[0]
        b = r[1]
        test = (a[0] * 0.99999 + b[0] * 0.00001,
                a[1] * 0.99999 + b[1] * 0.00001)
        parent = -1
        for j in range(i-1, -1, -1):
            if point_inside(test, rings[j]):
                parent = j
                break
        parents.append(parent)
    depths = []
    for i in range(len(rings)):
        depth = 0
        p = parents[i]
        while p != -1:
            depth += 1
            p = parents[p]
        depths.append(depth)
    groups = []
    for i, outer in enumerate(rings):
        if depths[i] % 2 != 0:
            continue
        holes = [rings[j] for j in range(len(rings))
                 if parents[j] == i and depths[j] == depths[i] + 1]
        if area(outer) < 0:
            outer = list(reversed(outer))
        normalized_holes = []
        for hole in holes:
            if area(hole) > 0:
                hole = list(reversed(hole))
            normalized_holes.append(hole)
        groups.append((outer, normalized_holes))
    return groups
