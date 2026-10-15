# -*- coding: utf-8 -*-
"""
DUCT AUTODIM - source-backed certification engine v6.8

Purpose
-------
Create one locating dimension from selected straight ductwork to the closest
parallel host-model grid in the active plan view.

Reference policy in v6.8:
  * No substitute reference lines or reference planes are created or reused.
  * Missing stable source references remain unresolved in the target audit.

Measurement rules:
  * Rectangular / oval straight duct -> dimension closest duct EDGE to closest grid.
  * Round straight duct             -> dimension duct CENTER to closest grid.
  * Native Revit duct + MEP Fabrication ductwork are supported.
  * Fittings / non-straight parts are ignored.
  * Host-model straight grids only in v0.2 (linked / curved grids are skipped).
  * Existing grid-to-duct dimensions are not duplicated.

Workflow
--------
1. Select one or more straight duct pieces, then run DUCT AUTODIM.
   - If nothing valid is selected, the command asks you to pick ductwork.
2. The tool finds the nearest grid parallel to each duct run.
3. It creates a linear dimension using the current Revit default dimension type.

v1.2 keeps the proven fabrication reference adapter from v1.1 and adds a
pre-placement dimension-text pocket search. A candidate corridor is no longer
rejected just because Revit's default midpoint value would land on MEP; the
planner searches along the dimension line for a clean annotation-safe text
pocket first, then creates the dimension with that planned text location. Native
Revit duct keeps the hardened reference path.
"""

import math
import time
import json
import uuid
from collections import deque
from System import Int64
from System.Collections.Generic import List

from pyrevit import revit, DB, UI, forms, script

uidoc = revit.uidoc
doc = revit.doc
view = doc.ActiveView
output = script.get_output()


# -----------------------------------------------------------------------------
# TUNING
# -----------------------------------------------------------------------------
PARALLEL_TOL_DEG = 5.0
HORIZONTAL_SLOPE_TOL = 0.035     # ~2 degrees out of plan
MAX_GRID_DISTANCE_FT = 150.0
DIM_LINE_EXTRA_FT = 1.0
# Stability rule: linear dimensions are created only when the model
# reference is parallel to the chosen Grid. The old angled-center
# rescue could create dimensions that Revit accepted initially but
# rejected during transaction regeneration as no longer parallel.
ENABLE_NONPARALLEL_CENTER_RESCUE = False
ENABLE_OUTSIDE_REFERENCE_CORRIDOR_RESCUE = False
BRANCH_SCAN_MAX_HOPS = 10
BRANCH_SCOPE_MARGIN_FT = 12.0
BRANCH_CENTER_MAX_OFFSET_FT = 0.03

# When a rectangular/oval duct has several candidate references, prefer a real
# top-face edge first, then a planar side face. This follows the proven Revit API
# pattern of using ComputeReferences=True on element geometry.
USE_EDGE_REFERENCE_FIRST = True

# v0.2 collision-aware layout. Distances are PAPER inches so the behavior remains
# visually similar at different plan scales. The dimension may slide along the
# selected duct, but never beyond the useful straight-run extent.
DIM_CANDIDATE_SHIFTS_PAPER_IN = [
    0.0, 0.18, -0.18, 0.35, -0.35, 0.55, -0.55,
    0.80, -0.80
]
DIM_MAX_SHIFT_FRACTION = 0.40
DIM_LINE_HALO_PAPER_IN = 0.028
DIM_TEXT_HALF_W_PAPER_IN = 0.54
DIM_TEXT_HALF_H_PAPER_IN = 0.16
DIM_TEXT_HALO_PAPER_IN = 0.060
DIM_SHIFT_PENALTY_PER_PAPER_IN = 65.0
DIM_MAX_LAYOUT_ATTEMPTS = 8

# v0.6 benchmark pass: post-placement text cleanup inspired by mature AutoDim
# workflows that separately solve geometry placement and text readability.
DIM_TEXT_NUDGE_PAPER_IN = [0.0, 0.18, -0.18, 0.30, -0.30, 0.45, -0.45]
# v1.2: before rejecting a corridor because the default dimension value lands on
# MEP/annotation, search for a clean value pocket along the dimension line.
# Fractions keep the value visually tied to its own grid-to-duct string.
DIM_TEXT_POCKET_FRACTIONS = [0.50, 0.40, 0.60, 0.30, 0.70, 0.20, 0.80, 0.10, 0.90]
DIM_TEXT_POCKET_PAPER_OFFSETS = [0.18, -0.18, 0.34, -0.34, 0.52, -0.52, 0.72, -0.72]
DIM_TEXT_POCKET_MOVE_PENALTY = 35.0
DIM_TEXT_NUDGE_MEP_LIMIT = 0

# Soft-awareness of architectural/structural RVT links. The linked geometry is
# used only as a placement cost; dimensions still reference host grids in v0.6.
MAX_LINK_BACKGROUND_ELEMENTS = 25000

# Collision weights. Existing dimensions/tags are strongest because overlapping
# annotation is the first thing a drafter notices. MEP geometry is also hard;
# architectural/CAD background is a softer preference so a difficult dimension
# can still be created instead of failing.
W_EXISTING_DIM = 12000.0
W_EXISTING_DIM_LINE = 3800.0
W_DIMENSION_LANE = 3400.0
DIMENSION_LANE_HALO_PAPER_IN = 0.075
W_TAG = 11000.0
W_TAG_LEADER = 2400.0
W_ANNOTATION = 9000.0
TAG_HEAD_HALF_W_PAPER_IN = 0.40
TAG_HEAD_HALF_H_PAPER_IN = 0.11
OUTSIDE_CORRIDOR_PENALTY = 2400.0
OUTSIDE_CORRIDOR_EXTRA_PAPER_IN = []
W_DUCT = 7000.0
W_FITTING = 6500.0
W_BACKGROUND = 850.0
W_CAD_MAJOR = 950.0
W_CAD_MEDIUM = 260.0
W_CAD_MINOR = 12.0
W_CAD_HATCH = 0.10


# v0.4 keeps run de-duplication but makes collision handling adaptive.
# Existing dimensions/tags/annotations are absolute blockers. Other MEP is
# strongly avoided, but a small number of crossings is allowed when every
# annotation-safe route on a dense floor touches unrelated ductwork.
RUN_MERGE_CENTER_TOL_FT = 0.5 / 12.0   # 1/2 inch model-space
RUN_MERGE_GAP_FT = 1.0                 # bridge short couplings; do not jump across larger branch zones
RUN_MAX_COVERAGE_SPAN_FT = 18.0         # long trunks get additional locating anchors

# Legacy run-envelope data retained for compatibility; v0.8 primarily uses real member hosts. After same-run de-duplication, the kept
# representative can place its dimension anywhere along the usable envelope of
# that local collinear run, not only within the single longest straight piece.
RUN_CORRIDOR_END_MARGIN_PAPER_IN = 0.12
RUN_CORRIDOR_FRACTIONS = [0.22, 0.40, 0.58, 0.76, 0.92]
_RUN_CORRIDOR_LIMITS = {}
# v0.8: representative id -> all physical straight members in the collapsed run.
# This lets the corridor planner use the correct Revit reference on whichever
# member owns the chosen witness-line location, rather than extending one bounded
# reference across the whole run.
_RUN_MEMBER_RECORDS = {}
_RUN_MEMBER_IDS = {}
_BRANCH_DOWNSTREAM_IDS = set()
HARD_COLLISION_KINDS = ('dimension_text', 'tag', 'annotation')
MEP_COLLISION_KINDS = ('duct', 'fitting')
# v0.9 separates a dimension VALUE/text collision from a witness/dimension-line
# crossing. A value sitting on ductwork is unreadable and stays forbidden, while
# the dimension line itself may cross unrelated MEP when that is the only clean
# annotation-safe route. This mirrors normal drafting practice much better than
# the old blanket 2-crossing limit.
PREFERRED_MEP_LINE_CROSSINGS = 2
MAX_MEP_LINE_CROSSINGS_RESCUE = 12
MAX_TEXT_MEP_OVERLAPS = 0
MEP_CROSSING_EXTRA_PENALTY = 9000.0
MEP_CROSSING_QUADRATIC_PENALTY = 2600.0

CAD_SCAN_MARGIN_PAPER_IN = 0.70
MAX_CAD_SEGMENTS = 15000
CAD_MIN_WEIGHT_TO_INDEX = 900.0
MAX_GRID_CELLS_PER_RECORD = 4096


# -----------------------------------------------------------------------------
# BASIC HELPERS
# -----------------------------------------------------------------------------
def eid_int(eid):
    try:
        return int(eid.Value)
    except Exception:
        return int(eid.IntegerValue)


def bic_int(bic):
    try:
        return eid_int(DB.ElementId(bic))
    except Exception:
        return int(bic)


def xyz2(x, y, z=0.0):
    return DB.XYZ(float(x), float(y), float(z))


def plan_vec(v):
    ln = math.sqrt(v.X * v.X + v.Y * v.Y)
    if ln < 1e-9:
        return None
    return DB.XYZ(v.X / ln, v.Y / ln, 0.0)


def perp_xy(v):
    return DB.XYZ(-v.Y, v.X, 0.0)


def midpoint(a, b):
    return DB.XYZ((a.X + b.X) * 0.5,
                  (a.Y + b.Y) * 0.5,
                  (a.Z + b.Z) * 0.5)


def dot_xy(a, b):
    return a.X * b.X + a.Y * b.Y


def vector_xy(a, b):
    return DB.XYZ(b.X - a.X, b.Y - a.Y, 0.0)


def distance_xy(a, b):
    dx = a.X - b.X
    dy = a.Y - b.Y
    return math.sqrt(dx * dx + dy * dy)


def line_midpoint(line):
    return midpoint(line.GetEndPoint(0), line.GetEndPoint(1))


def view_plane_z():
    try:
        if view.GenLevel is not None:
            return float(view.GenLevel.Elevation)
    except Exception:
        pass
    try:
        return float(view.Origin.Z)
    except Exception:
        return 0.0


def paper_to_model(paper_inches):
    try:
        scale = max(1, int(view.Scale))
    except Exception:
        scale = 1
    return float(paper_inches) * float(scale) / 12.0


def uv_of_point(p):
    return (float(p.X), float(p.Y))


def dist2_uv(a, b):
    dx = a[0] - b[0]
    dy = a[1] - b[1]
    return math.sqrt(dx * dx + dy * dy)


def rect_expand(r, pad):
    return (r[0] - pad, r[1] - pad, r[2] + pad, r[3] + pad)


def rect_union(rects):
    valid = [x for x in rects if x is not None]
    if not valid:
        return None
    return (min(x[0] for x in valid), min(x[1] for x in valid),
            max(x[2] for x in valid), max(x[3] for x in valid))


def rect_intersects(a, b):
    return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])


def point_in_rect(p, r):
    return p[0] >= r[0] and p[0] <= r[2] and p[1] >= r[1] and p[1] <= r[3]


def orient2d(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def segments_intersect(a, b, c, d):
    if max(a[0], b[0]) < min(c[0], d[0]) or max(c[0], d[0]) < min(a[0], b[0]):
        return False
    if max(a[1], b[1]) < min(c[1], d[1]) or max(c[1], d[1]) < min(a[1], b[1]):
        return False
    o1 = orient2d(a, b, c)
    o2 = orient2d(a, b, d)
    o3 = orient2d(c, d, a)
    o4 = orient2d(c, d, b)
    eps = 1e-9
    if ((o1 > eps and o2 < -eps) or (o1 < -eps and o2 > eps)) and \
       ((o3 > eps and o4 < -eps) or (o3 < -eps and o4 > eps)):
        return True
    if abs(o1) <= eps and point_in_rect(c, (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))):
        return True
    if abs(o2) <= eps and point_in_rect(d, (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))):
        return True
    if abs(o3) <= eps and point_in_rect(a, (min(c[0], d[0]), min(c[1], d[1]), max(c[0], d[0]), max(c[1], d[1]))):
        return True
    if abs(o4) <= eps and point_in_rect(b, (min(c[0], d[0]), min(c[1], d[1]), max(c[0], d[0]), max(c[1], d[1]))):
        return True
    return False


def segment_intersects_rect(a, b, r):
    if point_in_rect(a, r) or point_in_rect(b, r):
        return True
    p1 = (r[0], r[1]); p2 = (r[2], r[1])
    p3 = (r[2], r[3]); p4 = (r[0], r[3])
    return (segments_intersect(a, b, p1, p2) or segments_intersect(a, b, p2, p3) or
            segments_intersect(a, b, p3, p4) or segments_intersect(a, b, p4, p1))


def bbox_to_rect(bb):
    if bb is None:
        return None
    try:
        tr = bb.Transform
    except Exception:
        tr = DB.Transform.Identity
    mn = bb.Min; mx = bb.Max
    pts = []
    for x in (mn.X, mx.X):
        for y in (mn.Y, mx.Y):
            for z in (mn.Z, mx.Z):
                q = DB.XYZ(x, y, z)
                try:
                    q = tr.OfPoint(q)
                except Exception:
                    pass
                pts.append((q.X, q.Y))
    if not pts:
        return None
    return (min(x[0] for x in pts), min(x[1] for x in pts),
            max(x[0] for x in pts), max(x[1] for x in pts))


def element_rect(elem):
    try:
        return bbox_to_rect(elem.get_BoundingBox(view))
    except Exception:
        return None


class SpatialGrid(object):
    def __init__(self, cell_size):
        self.cell = max(float(cell_size), 0.10)
        self.cells = {}
        self.records = []
        self.oversized = []

    def _bounds(self, r):
        return (int(math.floor(r[0] / self.cell)), int(math.floor(r[1] / self.cell)),
                int(math.floor(r[2] / self.cell)), int(math.floor(r[3] / self.cell)))

    def _keys(self, r):
        x0, y0, x1, y1 = self._bounds(r)
        nx = x1 - x0 + 1; ny = y1 - y0 + 1
        if nx <= 0 or ny <= 0 or nx * ny > MAX_GRID_CELLS_PER_RECORD:
            return None
        out = []
        for ix in range(x0, x1 + 1):
            for iy in range(y0, y1 + 1):
                out.append((ix, iy))
        return out

    def _add(self, rec, bbox):
        idx = len(self.records)
        self.records.append(rec)
        keys = self._keys(bbox)
        if keys is None:
            self.oversized.append(idx)
            return
        for key in keys:
            if key not in self.cells:
                self.cells[key] = []
            self.cells[key].append(idx)

    def add_rect(self, kind, r, weight, source_id=None):
        if r is None:
            return
        self._add(('rect', kind, r, float(weight), source_id), r)

    def add_segment(self, kind, a, b, weight, source_id=None):
        r = (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))
        self._add(('seg', kind, (a, b), float(weight), source_id), r)

    def _candidates(self, r):
        keys = self._keys(r)
        if keys is None:
            return set(range(len(self.records)))
        found = set(self.oversized)
        for key in keys:
            for idx in self.cells.get(key, []):
                found.add(idx)
        return found

    def score_rect(self, r, ignore_source_id=None, ignore_source_ids=None):
        score = 0.0
        hits = {'dimension': 0, 'tag': 0, 'annotation': 0, 'duct': 0,
                'fitting': 0, 'background': 0, 'cad': 0}
        ignore_ids = ignore_source_ids
        if ignore_ids is None:
            ignore_ids = set()
        elif not isinstance(ignore_ids, set):
            ignore_ids = set(ignore_ids)
        if ignore_source_id is not None:
            ignore_ids.add(ignore_source_id)
        for idx in self._candidates(r):
            rec = self.records[idx]
            if rec[4] is not None and rec[4] in ignore_ids:
                continue
            if rec[0] == 'rect':
                hit = rect_intersects(r, rec[2])
            else:
                hit = segment_intersects_rect(rec[2][0], rec[2][1], r)
            if not hit:
                continue
            score += rec[3]
            if rec[1] in hits:
                hits[rec[1]] += 1
        return score, hits

    def score_segment(self, a, b, ignore_source_id=None, ignore_source_ids=None):
        br = (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))
        score = 0.0
        hits = {'dimension': 0, 'tag': 0, 'annotation': 0, 'duct': 0,
                'fitting': 0, 'background': 0, 'cad': 0}
        ignore_ids = ignore_source_ids
        if ignore_ids is None:
            ignore_ids = set()
        elif not isinstance(ignore_ids, set):
            ignore_ids = set(ignore_ids)
        if ignore_source_id is not None:
            ignore_ids.add(ignore_source_id)
        for idx in self._candidates(br):
            rec = self.records[idx]
            if rec[4] is not None and rec[4] in ignore_ids:
                continue
            if rec[0] == 'rect':
                hit = segment_intersects_rect(a, b, rec[2])
            else:
                hit = segments_intersect(a, b, rec[2][0], rec[2][1])
            if not hit:
                continue
            score += rec[3]
            if rec[1] in hits:
                hits[rec[1]] += 1
        return score, hits


# -----------------------------------------------------------------------------
# DUCT CLASSIFICATION / CENTERLINE
# -----------------------------------------------------------------------------
def is_native_duct(elem):
    try:
        return isinstance(elem, DB.Mechanical.Duct)
    except Exception:
        return False


def is_fabrication_duct_part(elem):
    try:
        return (isinstance(elem, DB.FabricationPart) and
                elem.Category is not None and
                eid_int(elem.Category.Id) == bic_int(DB.BuiltInCategory.OST_FabricationDuctwork))
    except Exception:
        return False


def is_physical_connector_type(connector_type):
    try:
        return connector_type in (
            DB.ConnectorType.End,
            DB.ConnectorType.Curve,
            DB.ConnectorType.Physical,
        )
    except Exception:
        return False


def get_connectors(elem):
    result = []
    try:
        cm = elem.ConnectorManager
        for c in cm.Connectors:
            result.append(c)
        return result
    except Exception:
        pass
    try:
        mep = elem.MEPModel
        if mep is not None and mep.ConnectorManager is not None:
            for c in mep.ConnectorManager.Connectors:
                result.append(c)
    except Exception:
        pass
    return result


def physical_connectors(elem):
    result = []
    for c in get_connectors(elem):
        try:
            if is_physical_connector_type(c.ConnectorType):
                result.append(c)
        except Exception:
            pass
    return result


def connector_axis(conn):
    try:
        cs = conn.CoordinateSystem
        if cs is not None:
            return cs.BasisZ.Normalize()
    except Exception:
        pass
    return None


def connector_signature(conn):
    try:
        shape = str(conn.Shape).lower()
    except Exception:
        shape = 'unknown'
    dims = ()
    if 'round' in shape:
        try:
            dims = (float(conn.Radius) * 2.0,)
        except Exception:
            pass
    elif 'rect' in shape or 'oval' in shape:
        try:
            dims = tuple(sorted((float(conn.Width), float(conn.Height))))
        except Exception:
            pass
    return shape, dims


def fabrication_straight_fallback(elem):
    """Strict straight-through recovery for FabricationPart.

    Some real fabrication straights are not cleanly reported by IsAStraight().
    Require a matching, opposite, collinear connector pair so fittings are not
    promoted to straight hosts.
    """
    if not is_fabrication_duct_part(elem):
        return False
    try:
        if bool(elem.IsAHanger()) or bool(elem.IsATap()):
            return False
    except Exception:
        pass

    conns = physical_connectors(elem)
    if len(conns) < 2:
        return False

    for i in range(len(conns)):
        for j in range(i + 1, len(conns)):
            c0 = conns[i]
            c1 = conns[j]
            try:
                p0 = c0.Origin
                p1 = c1.Origin
                delta = p1 - p0
                dist = delta.GetLength()
                if dist <= 1e-4:
                    continue
                chord = delta.Normalize()
            except Exception:
                continue

            s0 = connector_signature(c0)
            s1 = connector_signature(c1)
            if s0[0] != s1[0] or len(s0[1]) != len(s1[1]):
                continue
            ok = True
            for a, b in zip(s0[1], s1[1]):
                if abs(a - b) > (1.0 / 192.0):
                    ok = False
                    break
            if not ok:
                continue

            d0 = connector_axis(c0)
            d1 = connector_axis(c1)
            if d0 is None or d1 is None:
                continue
            if d0.DotProduct(d1) > -0.96:
                continue
            if abs(d0.DotProduct(chord)) < 0.965:
                continue
            if abs(d1.DotProduct(chord)) < 0.965:
                continue
            return True
    return False


def is_fabrication_straight(elem):
    if not is_fabrication_duct_part(elem):
        return False
    try:
        if bool(elem.IsAStraight()):
            return True
    except Exception:
        pass
    try:
        legacy = getattr(elem, 'IsStraightSegment', None)
        if legacy is not None and bool(legacy()):
            return True
    except Exception:
        pass
    return fabrication_straight_fallback(elem)


def is_supported_straight_duct(elem):
    if is_native_duct(elem):
        return True
    return is_fabrication_straight(elem)


def fabrication_centerline(elem):
    pts = []
    for c in physical_connectors(elem):
        try:
            pts.append(c.Origin)
        except Exception:
            pass
    if len(pts) < 2:
        return None
    best = None
    best_dist = -1.0
    for i in range(len(pts)):
        for j in range(i + 1, len(pts)):
            try:
                d = pts[i].DistanceTo(pts[j])
            except Exception:
                continue
            if d > best_dist:
                best_dist = d
                best = (pts[i], pts[j])
    if best is None or best_dist <= 1e-6:
        return None
    try:
        return DB.Line.CreateBound(best[0], best[1])
    except Exception:
        return None


def duct_centerline(elem):
    if is_native_duct(elem):
        try:
            crv = elem.Location.Curve
            if isinstance(crv, DB.Line):
                return crv
        except Exception:
            return None
    if is_fabrication_straight(elem):
        return fabrication_centerline(elem)
    return None


def is_plan_run(elem):
    line = duct_centerline(elem)
    if line is None:
        return False
    try:
        d = line.Direction.Normalize()
        return abs(d.Z) <= HORIZONTAL_SLOPE_TOL
    except Exception:
        return False


def duct_shape(elem):
    for c in physical_connectors(elem):
        try:
            text = str(c.Shape).lower()
            if 'round' in text:
                return 'round'
            if 'oval' in text:
                return 'oval'
            if 'rect' in text:
                return 'rectangular'
        except Exception:
            pass

    if is_native_duct(elem):
        try:
            p = elem.get_Parameter(DB.BuiltInParameter.RBS_CURVE_DIAMETER_PARAM)
            if p is not None and p.HasValue and p.AsDouble() > 1e-8:
                return 'round'
        except Exception:
            pass
        return 'rectangular'
    return 'unknown'


# -----------------------------------------------------------------------------
# GRID DATA / REFERENCES
# -----------------------------------------------------------------------------
def reference_type_name(ref):
    if ref is None:
        return 'None'
    try:
        return str(ref.ElementReferenceType)
    except Exception:
        return 'unknown'


def grid_reference(grid):
    """Return the grid reference Revit expects for linear dimensions.

    Autodesk API examples/community guidance are counter-intuitive here: for a
    Grid, NewDimension normally wants Reference(grid) (REFERENCE_TYPE_NONE), not
    the surface/curve reference exposed by Grid.Curve or display geometry.  v0.9
    preferred geometry references first, which explains many field errors saying
    "references are not geometric references" on otherwise valid grids.
    """
    try:
        ref = DB.Reference(grid)
        if ref is not None:
            return ref
    except Exception:
        pass

    # Compatibility fallback only.  Normal Revit 2025-2027 host grids should
    # succeed above.
    try:
        crv = grid.Curve
        if crv is not None and crv.Reference is not None:
            return crv.Reference
    except Exception:
        pass
    return None


def collect_straight_grids():
    """Retain view grids first, with host-document coverage fallback.

    A successful view collector can omit an entire datum direction (view
    extents/crop/visibility). Exception-only document fallback is insufficient.
    Explicit selected IDs are resolved from the host document as well.
    """
    result = []
    selected_ids = globals().get('AUTODIM_GRID_IDS', None)
    selected_ids = set(int(x) for x in selected_ids) if selected_ids is not None else set()
    inventory = {'view_grid_ids': [], 'fallback_grid_ids': [], 'rejected': [],
                 'selected_missing_ids': [], 'warnings': []}
    globals()['AUTODIM_GRID_INVENTORY'] = inventory
    candidates = {}
    view_ids = set()
    try:
        for grid in (DB.FilteredElementCollector(doc, view.Id).OfClass(DB.Grid)
                     .WhereElementIsNotElementType()):
            grid_id = eid_int(grid.Id)
            candidates[grid_id] = grid
            view_ids.add(grid_id)
    except Exception as error:
        inventory['warnings'].append('View grid collection failed: ' + str(error))
    try:
        for grid in (DB.FilteredElementCollector(doc).OfClass(DB.Grid)
                     .WhereElementIsNotElementType()):
            candidates[eid_int(grid.Id)] = grid
    except Exception as error:
        inventory['warnings'].append('Host grid fallback collection failed: ' + str(error))
    for grid_id in selected_ids:
        if grid_id not in candidates:
            grid = doc.GetElement(DB.ElementId(Int64(int(grid_id))))
            if isinstance(grid, DB.Grid):
                candidates[grid_id] = grid
            else:
                inventory['selected_missing_ids'].append(grid_id)
    for grid_id in sorted(candidates):
        grid = candidates[grid_id]
        try:
            curve = grid.Curve
            if not isinstance(curve, DB.Line):
                inventory['rejected'].append({'id': grid_id, 'reason': 'curved-or-nonlinear-grid'})
                continue
            axis = plan_vec(curve.Direction)
            reference = grid_reference(grid)
            if axis is None or reference is None:
                inventory['rejected'].append({'id': grid_id, 'reason': 'no-plan-axis-or-usable-reference'})
                continue
            view_candidate = grid_id in view_ids
            result.append({'element': grid, 'line': curve, 'axis': axis,
                           'origin': curve.Origin, 'reference': reference, 'name': grid.Name,
                           'selected': grid_id in selected_ids, 'view_candidate': view_candidate})
            inventory['view_grid_ids' if view_candidate else 'fallback_grid_ids'].append(grid_id)
        except Exception as error:
            inventory['rejected'].append({'id': grid_id, 'reason': str(error)})
    inventory['grids'] = [{'id': eid_int(g['element'].Id), 'name': str(g['name']),
                          'axis': _audit_point(g['axis']), 'selected': g['selected'],
                          'view_candidate': g['view_candidate']} for g in result]
    return result


def _grid_rank(grid_info, distance):
    """Preserve eligible visible grids, then fill missing directions from host grids."""
    mode = str(globals().get('AUTODIM_GRID_MODE', 'all')).lower()
    selected = bool(grid_info.get('selected', False))
    if mode == 'strict' and not selected:
        return None
    visible_rank = 0 if grid_info.get('view_candidate', True) else 1
    selection_rank = (0 if selected else 1) if mode == 'prefer' else 0
    return (selection_rank, visible_rank, float(distance))


def nearest_parallel_grid(duct_line, grids):
    axis = plan_vec(duct_line.Direction)
    if axis is None:
        return None
    perp = perp_xy(axis)
    mid = line_midpoint(duct_line)
    cos_tol = math.cos(math.radians(PARALLEL_TOL_DEG))

    best = None
    best_dist = None
    best_signed = None
    best_rank = None
    for g in grids:
        try:
            parallel = abs(dot_xy(axis, g['axis'])) >= cos_tol
        except Exception:
            parallel = False
        if not parallel:
            continue
        signed = dot_xy(vector_xy(mid, g['origin']), perp)
        dist = abs(signed)
        if dist > MAX_GRID_DISTANCE_FT:
            continue
        rank = _grid_rank(g, dist)
        if rank is None:
            continue
        if best is None or rank < best_rank:
            best = g
            best_dist = dist
            best_signed = signed
            best_rank = rank

    if best is None:
        return None
    if best_dist is not None and best_dist > MAX_GRID_DISTANCE_FT:
        return None
    return best, best_dist, best_signed, axis, perp, mid


def nearest_grid_for_round_center(duct_line, grids):
    """Fallback for diagonal ROUND duct when no grid is parallel to the run.

    A round duct is located by its center, not by a side-edge line.  The existing
    element-center reference is point-like enough for Revit to attempt a
    grid-to-center dimension even when the duct axis is diagonal.  The dimension
    line is therefore normal to the chosen GRID (not normal to the duct).

    This fallback is deliberately round-only.  Rectangular/oval edge references
    are line/face references and still require a compatible parallel grid; we do
    not fake those dimensions with temporary detail geometry.
    """
    axis = plan_vec(duct_line.Direction)
    if axis is None:
        return None
    mid = line_midpoint(duct_line)

    best = None
    best_dist = None
    best_signed = None
    best_perp = None
    best_rank = None
    for g in grids:
        try:
            gperp = perp_xy(g['axis'])
            signed = dot_xy(vector_xy(mid, g['origin']), gperp)
            dist = abs(signed)
        except Exception:
            continue
        if dist > MAX_GRID_DISTANCE_FT:
            continue
        rank = _grid_rank(g, dist)
        if rank is None:
            continue
        if best is None or rank < best_rank:
            best = g
            best_dist = dist
            best_signed = signed
            best_perp = gperp
            best_rank = rank

    if best is None or best_perp is None:
        return None
    if best_dist is not None and best_dist > MAX_GRID_DISTANCE_FT:
        return None
    return best, best_dist, best_signed, axis, best_perp, mid


def grid_is_parallel_to_duct(gdata):
    try:
        grid = gdata[0]
        axis = gdata[3]
        cos_tol = math.cos(math.radians(PARALLEL_TOL_DEG))
        return abs(dot_xy(axis, grid['axis'])) >= cos_tol
    except Exception:
        return True


# -----------------------------------------------------------------------------
# DUCT GEOMETRIC REFERENCES
# -----------------------------------------------------------------------------
def _collect_reference_solids(geo, parent_transform, result):
    """Collect (Solid, transform) pairs while preserving usable references.

    GeometryInstance.GetInstanceGeometry() returns a COPY whose references are
    explicitly not suitable for creating dimensions.  GetSymbolGeometry() with
    no transform returns the actual Revit geometry and its references; we carry
    the instance transform separately only for geometric tests in model space.
    """
    if geo is None:
        return
    for item in geo:
        try:
            if isinstance(item, DB.Solid):
                if item.Faces.Size > 0 and item.Volume > 1e-9:
                    result.append((item, parent_transform))
            elif isinstance(item, DB.GeometryInstance):
                try:
                    child_transform = parent_transform.Multiply(item.Transform)
                except Exception:
                    child_transform = item.Transform
                try:
                    sym_geo = item.GetSymbolGeometry()
                    _collect_reference_solids(sym_geo, child_transform, result)
                except Exception:
                    pass
        except Exception:
            continue


def _reference_geometry_options(use_view):
    opt = DB.Options()
    opt.ComputeReferences = True
    opt.IncludeNonVisibleObjects = True
    if use_view:
        try:
            opt.View = view
        except Exception:
            pass
    else:
        try:
            opt.DetailLevel = DB.ViewDetailLevel.Fine
        except Exception:
            pass
    return opt


def element_solids_with_refs(elem):
    # Prefer uncut model geometry at Fine detail.  If an element exposes useful
    # references only in the active view, fall back to view-specific geometry.
    for use_view in (False, True):
        result = []
        try:
            geo = elem.get_Geometry(_reference_geometry_options(use_view))
            _collect_reference_solids(geo, DB.Transform.Identity, result)
        except Exception:
            result = []
        if result:
            return result
    return []


def _model_point(tr, p):
    try:
        return tr.OfPoint(p)
    except Exception:
        return None


def _model_vector(tr, v):
    try:
        return tr.OfVector(v)
    except Exception:
        return None


def _model_curve(tr, crv):
    try:
        return crv.CreateTransformed(tr)
    except Exception:
        return None


# -----------------------------------------------------------------------------
# v1.1 VERIFIED MEP FABRICATION REFERENCE ADAPTER
# -----------------------------------------------------------------------------
FAB_SIDE_MIN_OFFSET_FT = 0.02
FAB_MAX_REFERENCE_CANDIDATES = 6


def _fab_relation_to_axis(curve, axis):
    if not isinstance(curve, DB.Line):
        return 'non-line'
    a = plan_vec(curve.Direction)
    if a is None:
        return 'non-plan-line'
    v = abs(dot_xy(a, axis))
    cos_tol = math.cos(math.radians(7.0))
    if v >= cos_tol:
        return 'parallel-run'
    if v <= math.sin(math.radians(7.0)):
        return 'perpendicular-run'
    return 'angled-run'


def _fab_candidate_key(ref, source):
    try:
        stable = ref.ConvertToStableRepresentation(doc)
        if stable:
            return stable
    except Exception:
        pass
    return '{0}:{1}'.format(source, reference_type_name(ref))


def _fab_add_candidate(records, seen, ref, source, kind, relation,
                       witness, center_mid, run_normal, model_direction=None, model_normal=None,
                       model_start=None, model_end=None, endpoint_index=None):
    if ref is None or witness is None:
        return
    key = _fab_candidate_key(ref, source)
    if key in seen:
        return
    seen.add(key)
    try:
        off = dot_xy(vector_xy(center_mid, witness), run_normal)
    except Exception:
        return
    records.append({
        'ref': ref,
        'source': source,
        'kind': kind,
        'relation': relation,
        'witness': witness,
        'offset': off,
        'abs_offset': abs(off),
        'model_direction': model_direction, 'model_normal': model_normal,
        'model_start': model_start, 'model_end': model_end,
        'endpoint_index': endpoint_index,
    })


def _fab_harvest_solid(solid, tr, prefix, run_axis, center_mid, run_normal,
                       records, seen):
    try:
        faces = list(solid.Faces)
    except Exception:
        faces = []
    for fi, face in enumerate(faces):
        if isinstance(face, DB.PlanarFace):
            try:
                fw = _model_point(tr, face.Origin)
                n = plan_vec(_model_vector(tr, face.FaceNormal))
                if n is None:
                    frel = 'horizontal-face'
                elif abs(dot_xy(n, run_normal)) >= math.cos(math.radians(7.0)):
                    frel = 'side-face'
                else:
                    frel = 'other-face'
                _fab_add_candidate(
                    records, seen, face.Reference,
                    '{0}.face[{1}]'.format(prefix, fi),
                    'face', frel, fw, center_mid, run_normal,
                    model_normal=_model_vector(tr, face.FaceNormal)
                )
            except Exception:
                pass

        try:
            loops = face.EdgeLoops
        except Exception:
            loops = []
        ei = 0
        for loop in loops:
            for edge in loop:
                try:
                    raw = edge.AsCurve()
                    mc = _model_curve(tr, raw)
                    if isinstance(mc, DB.Line):
                        witness = line_midpoint(mc)
                    else:
                        witness = _model_point(tr, raw.Evaluate(0.5, True))
                    rel = _fab_relation_to_axis(mc, run_axis)
                    _fab_add_candidate(
                        records, seen, edge.Reference,
                        '{0}.face[{1}].edge[{2}]'.format(prefix, fi, ei),
                        'edge', rel, witness, center_mid, run_normal,
                        model_direction=mc.Direction if isinstance(mc, DB.Line) else None,
                        model_start=mc.GetEndPoint(0) if isinstance(mc, DB.Line) else None,
                        model_end=mc.GetEndPoint(1) if isinstance(mc, DB.Line) else None
                    )
                    for ep_idx in (0, 1):
                        try:
                            epr = edge.GetEndPointReference(ep_idx)
                            ep = _model_point(tr, raw.GetEndPoint(ep_idx))
                            _fab_add_candidate(
                                records, seen, epr,
                                '{0}.face[{1}].edge[{2}].endpoint[{3}]'.format(
                                    prefix, fi, ei, ep_idx),
                                'endpoint', 'point', ep, center_mid, run_normal,
                                model_direction=mc.Direction if isinstance(mc, DB.Line) else None,
                                model_start=mc.GetEndPoint(0) if isinstance(mc, DB.Line) else None,
                                model_end=mc.GetEndPoint(1) if isinstance(mc, DB.Line) else None,
                                endpoint_index=ep_idx
                            )
                        except Exception:
                            pass
                except Exception:
                    pass
                ei += 1


def _fab_harvest_geometry(geo, parent_tr, prefix, run_axis, center_mid,
                          run_normal, records, seen):
    if geo is None:
        return
    gi = 0
    si = 0
    ci = 0
    for item in geo:
        try:
            if isinstance(item, DB.Solid):
                if item.Faces.Size > 0:
                    _fab_harvest_solid(
                        item, parent_tr,
                        '{0}.solid[{1}]'.format(prefix, si),
                        run_axis, center_mid, run_normal, records, seen
                    )
                    si += 1
            elif isinstance(item, DB.GeometryInstance):
                try:
                    child_tr = parent_tr.Multiply(item.Transform)
                except Exception:
                    continue
                try:
                    sym = item.GetSymbolGeometry()
                    _fab_harvest_geometry(
                        sym, child_tr,
                        '{0}.instance[{1}].symbol'.format(prefix, gi),
                        run_axis, center_mid, run_normal, records, seen
                    )
                except Exception:
                    pass
                gi += 1
            elif isinstance(item, DB.Curve):
                try:
                    mc = _model_curve(parent_tr, item)
                    if isinstance(mc, DB.Line):
                        witness = line_midpoint(mc)
                    else:
                        witness = _model_point(parent_tr, item.Evaluate(0.5, True))
                    _fab_add_candidate(
                        records, seen, getattr(item, 'Reference', None),
                        '{0}.curve[{1}]'.format(prefix, ci),
                        'curve', _fab_relation_to_axis(mc, run_axis),
                        witness, center_mid, run_normal,
                        model_direction=mc.Direction if isinstance(mc, DB.Line) else None,
                        model_start=mc.GetEndPoint(0) if isinstance(mc, DB.Line) else None,
                        model_end=mc.GetEndPoint(1) if isinstance(mc, DB.Line) else None
                    )
                    ci += 1
                except Exception:
                    pass
        except Exception:
            pass


def _fab_reference_candidates(elem, duct_line):
    axis = plan_vec(duct_line.Direction)
    if axis is None:
        return []
    center_mid = line_midpoint(duct_line)
    run_normal = perp_xy(axis)
    records = []
    seen = set()
    try:
        geo = elem.get_Geometry(_reference_geometry_options(False))
        _fab_harvest_geometry(
            geo, DB.Transform.Identity, 'fab-symbol',
            axis, center_mid, run_normal, records, seen
        )
    except Exception:
        pass
    return records


def _fab_candidate_grid_distance(candidate, grid_info):
    try:
        axis = grid_info['axis']
        gp = grid_info['origin']
        perp = perp_xy(axis)
        return abs(dot_xy(vector_xy(candidate['witness'], gp), perp))
    except Exception:
        return 1e30


def _fab_grid_side_sign(duct_line, grid_info):
    try:
        axis = plan_vec(duct_line.Direction)
        normal = perp_xy(axis)
        mid = line_midpoint(duct_line)
        signed = dot_xy(vector_xy(mid, grid_info['origin']), normal)
        if abs(signed) < 1e-8:
            return 0.0
        return 1.0 if signed > 0.0 else -1.0
    except Exception:
        return 0.0


def fabrication_center_reference_candidates(elem, duct_line, grid_info):
    """Classifier-proven Fabrication round center references.

    Real Revit 2025 tests showed symbol-geometry curves at zero connector-
    centerline offset are valid NewDimension references with Reference(grid).
    """
    cands = _fab_reference_candidates(elem, duct_line)
    parallel = [c for c in cands
                if c['kind'] == 'curve' and c['relation'] == 'parallel-run']
    parallel.sort(
        key=lambda c: (c['abs_offset'],
                       _fab_candidate_grid_distance(c, grid_info),
                       c['source'])
    )
    result = []
    for c in parallel:
        result.append((c['ref'], 'fab-center:' + c['source']))
    # Do not let rejected curves hide a later genuine center endpoint.
    # Both groups are validated before applying the final candidate limit.
    # Very conservative rescue: only real endpoint references nearest center.
    points = [c for c in cands if c['kind'] == 'endpoint']
    points.sort(
        key=lambda c: (c['abs_offset'],
                       _fab_candidate_grid_distance(c, grid_info),
                       c['source'])
    )
    for c in points:
        result.append((c['ref'], 'fab-center-endpoint:' + c['source']))
    return result


def fabrication_edge_candidates_toward_grid(elem, duct_line, grid_info):
    """Classifier-proven Fabrication rectangular/oval near-edge refs.

    Revit 2025 field tests verified the near-side endpoint references at exactly
    half the duct width from the connector-derived centerline. We still rank
    true parallel edge/curve refs first when a fabrication family exposes them.
    """
    cands = _fab_reference_candidates(elem, duct_line)
    side_sign = _fab_grid_side_sign(duct_line, grid_info)

    pool = [c for c in cands
            if c['kind'] in ('edge', 'curve')
            and c['relation'] == 'parallel-run'
            and c['abs_offset'] >= FAB_SIDE_MIN_OFFSET_FT]
    if side_sign != 0.0:
        same = [c for c in pool if c['offset'] * side_sign > 0.0]
        if same:
            pool = same
    pool.sort(
        key=lambda c: (-c['abs_offset'],
                       _fab_candidate_grid_distance(c, grid_info),
                       c['source'])
    )

    faces = [c for c in cands
             if c['kind'] == 'face'
             and c['relation'] == 'side-face'
             and c['abs_offset'] >= FAB_SIDE_MIN_OFFSET_FT]
    if side_sign != 0.0:
        same = [c for c in faces if c['offset'] * side_sign > 0.0]
        if same:
            faces = same
    faces.sort(
        key=lambda c: (-c['abs_offset'],
                       _fab_candidate_grid_distance(c, grid_info),
                       c['source'])
    )

    points = [c for c in cands
              if c['kind'] == 'endpoint'
              and c['abs_offset'] >= FAB_SIDE_MIN_OFFSET_FT]
    if side_sign != 0.0:
        same = [c for c in points if c['offset'] * side_sign > 0.0]
        if same:
            points = same
    points.sort(
        key=lambda c: (-c['abs_offset'],
                       _fab_candidate_grid_distance(c, grid_info),
                       c['source'])
    )

    ordered = pool + faces + points
    result = []
    for c in ordered:
        result.append((
            _fab_candidate_grid_distance(c, grid_info),
            c['ref'],
            c['witness'],
            'fab-near-edge:' + c['source']
        ))
    return result


def edge_candidates_toward_grid(elem, duct_line, grid_info):
    if is_fabrication_duct_part(elem):
        return fabrication_edge_candidates_toward_grid(elem, duct_line, grid_info)

    """Return real Revit references for the closest rectangular/oval side.

    Preferred reference order:
      1) long plan edge from a horizontal face
      2) planar vertical side face
      3) endpoint reference from the long plan edge (rescue only)

    Symbol geometry is evaluated in model coordinates using its instance
    transform, while its original references are preserved for NewDimension.
    """
    axis = plan_vec(duct_line.Direction)
    if axis is None:
        return []
    perp = perp_xy(axis)
    mid = line_midpoint(duct_line)
    g_origin = grid_info['origin']
    grid_signed = dot_xy(vector_xy(mid, g_origin), perp)
    wanted_sign = 1.0 if grid_signed >= 0.0 else -1.0
    cos_parallel = math.cos(math.radians(6.0))

    edge_recs = []
    face_recs = []
    endpoint_recs = []
    solids = element_solids_with_refs(elem)

    for solid, tr in solids:
        for face in solid.Faces:
            if not isinstance(face, DB.PlanarFace):
                continue
            try:
                n = _model_vector(tr, face.FaceNormal).Normalize()
            except Exception:
                continue

            # Horizontal face exposes the visible plan-outline edges.
            if abs(n.Z) >= 0.92:
                try:
                    loops = face.EdgeLoops
                except Exception:
                    loops = []
                for loop in loops:
                    for edge in loop:
                        try:
                            raw_curve = edge.AsCurve()
                            if not isinstance(raw_curve, DB.Line):
                                continue
                            crv = _model_curve(tr, raw_curve)
                            eaxis = plan_vec(crv.Direction)
                            if eaxis is None or abs(dot_xy(axis, eaxis)) < cos_parallel:
                                continue
                            emid = line_midpoint(crv)
                            side_coord = dot_xy(vector_xy(mid, emid), perp)
                            side_sign = 1.0 if side_coord >= 0.0 else -1.0
                            if side_sign != wanted_sign and abs(side_coord) > 1e-5:
                                continue
                            grid_dist = abs(dot_xy(vector_xy(g_origin, emid), perp))

                            eref = edge.Reference
                            if eref is not None:
                                edge_recs.append((grid_dist, eref, emid, 'edge'))

                            # Autodesk's published duct-edge solution also uses
                            # edge endpoint references. They are a useful rescue
                            # when Edge.Reference itself is absent/non-dimensionable.
                            for idx in (0, 1):
                                try:
                                    pref = edge.GetEndPointReference(idx)
                                    if pref is None:
                                        continue
                                    p = _model_point(tr, raw_curve.GetEndPoint(idx))
                                    endpoint_recs.append((grid_dist + 0.0001, pref, p,
                                                          'edge-endpoint-{0}'.format(idx)))
                                except Exception:
                                    pass
                        except Exception:
                            continue

            # Vertical side face parallel to the run/grid.
            try:
                nxy = plan_vec(n)
            except Exception:
                nxy = None
            if nxy is None or abs(n.Z) > 0.25:
                continue
            if abs(dot_xy(nxy, axis)) > 0.18:
                continue
            if face.Reference is None:
                continue
            try:
                fpt = _model_point(tr, face.Origin)
            except Exception:
                continue
            side_coord = dot_xy(vector_xy(mid, fpt), perp)
            side_sign = 1.0 if side_coord >= 0.0 else -1.0
            if side_sign != wanted_sign and abs(side_coord) > 1e-5:
                continue
            grid_dist = abs(dot_xy(vector_xy(g_origin, fpt), perp))
            face_recs.append((grid_dist, face.Reference, fpt, 'side-face'))

    edge_recs.sort(key=lambda x: x[0])
    face_recs.sort(key=lambda x: x[0])
    endpoint_recs.sort(key=lambda x: x[0])
    if USE_EDGE_REFERENCE_FIRST:
        return edge_recs + face_recs + endpoint_recs
    return face_recs + edge_recs + endpoint_recs


def center_reference_candidates(elem, duct_line=None, grid_info=None):
    result = []

    if is_fabrication_duct_part(elem):
        if duct_line is None:
            duct_line = duct_centerline(elem)
        if grid_info is not None and duct_line is not None:
            return fabrication_center_reference_candidates(elem, duct_line, grid_info)
        return result

    # Native Revit duct keeps the v1.0 reference path.
    if is_native_duct(elem):
        try:
            crv = elem.Location.Curve
            if crv is not None and crv.Reference is not None:
                result.append((crv.Reference, 'native-location-curve'))
        except Exception:
            pass

        try:
            r = DB.Reference(elem)
            if r is not None:
                result.append((r, 'native-element-center'))
        except Exception:
            pass

    return result


# -----------------------------------------------------------------------------
# STABLE-HYBRID REFERENCE + PERFORMANCE LAYER
# -----------------------------------------------------------------------------
STRICT_REF_PARALLEL_DEG = 0.20
STRICT_REF_MAX_Z = 0.0025
HELPER_SHIFT_PAPER_IN = [0.0, 0.25, -0.25, 0.50, -0.50, 0.80, -0.80, 1.15, -1.15, 1.55, -1.55, 2.05, -2.05, 2.70, -2.70, 3.40, -3.40]
BRANCH_HELPER_SHIFT_PAPER_IN = [0.0, 0.25, -0.25, 0.50, -0.50, 0.80, -0.80, 1.15, -1.15, 1.60, -1.60, 2.20, -2.20]
MAX_BRANCH_MEP_LINE_CROSSINGS_RESCUE = 16

# Final required-target rescue settings.
# These are used ONLY after normal placement and normal recovery have both failed.
MANDATORY_HELPER_SHIFT_PAPER_IN = [
    0.0,
    0.20, -0.20,
    0.40, -0.40,
    0.65, -0.65,
    0.95, -0.95,
    1.30, -1.30,
    1.75, -1.75,
    2.30, -2.30,
    3.00, -3.00,
    3.80, -3.80,
]
MANDATORY_TEXT_NUDGE_PAPER_IN = [
    0.0,
    0.18, -0.18,
    0.35, -0.35,
    0.55, -0.55,
    0.80, -0.80,
    1.10, -1.10,
    1.50, -1.50,
]
MANDATORY_MEP_LINE_CROSSINGS_RESCUE = 32
_MANDATORY_RESCUE_MODE = False


BRANCH_COVERAGE_MAX_DISTANCE_FT = paper_to_model(0.90)
POST_COMMIT_RECOVERY_MAX_ATTEMPTS = 999

_ELEMENT_RECT_CACHE = {}
_CONNECTOR_CACHE = {}
_CENTERLINE_CACHE = {}
_FAB_REF_CACHE = {}
_CREATED_DIM_IDS = set()
_CREATED_DIM_SOURCE = {}
_CREATED_DIM_MODE = {}
_CREATED_DIM_TARGETS = {}
_CREATED_DIM_BRANCH_KEY = {}
# Existing direct model-to-grid dimensions are audited independently. They never
# enter _CREATED_DIM_IDS, so deletion/cleanup cannot alter a user's dimensions.
_EXISTING_DIRECT_DIM_RECORDS = {}
_RUN_EXPECTED_TARGET_CACHE = {}

# Actual post-commit geometric coverage certification.
# A target is not "covered" merely because a related dimension survives.
# The surviving dimension must reference the intended grid and its measured
# value must match the recorded target-to-grid geometry within tolerance.
_CREATED_DIM_GRID = {}
_CERTIFICATION_STATS = {
    'checked': 0,
    'certified_dims': 0,
    'rejected_dims': 0,
    'grid_ref_mismatch': 0,
    'value_mismatch': 0,
    'direction_mismatch': 0,
    'source_target_mismatch': 0,
    'metadata_missing': 0,
    'missing_dimension': 0,
    'pre_rescue_required': 0,
    'pre_rescue_certified': 0,
    'pre_rescue_uncovered_runs': 0,
    'pre_rescue_uncovered_branches': 0,
    'rescued_runs': 0,
    'rescued_branches': 0,
    'final_required': 0,
    'final_certified': 0,
    'final_uncovered_runs': 0,
    'final_uncovered_branches': 0,
    'false_coverage_rejected': 0,
    'certification_runtime': 0.0,
}
CERT_VALUE_TOL_FT = 1.0 / 96.0       # 1/8 in
CERT_DIM_GRID_PERP_DOT_MAX = 0.08    # geometric sanity, not target matching
_CERT_FINAL_IDS = set()
_CERT_FINAL_UNCOVERED_RUN_IDS = []
_CERT_FINAL_UNCOVERED_BRANCH_KEYS = []
_CERT_REJECTED_DETAILS = []
_EXISTING_BRANCH_KEYS = set()
_BRANCH_LEG_RECORDS = []
_STABILITY_STATS = {
    'direct_refs_rejected': 0,
    'helper_used': 0,
    'helper_created': 0,
    'helper_reused': 0,
    'helper_hidden': 0,
    'branch_helper_created': 0,
    'resolved_helper_attempts': 0,
    'resolved_helper_created': 0,
    'resolved_helper_blocked': 0,
    'commit_pruned': 0,
}

# Cache the expensive geometry/connectivity calls for this one command execution.
_element_rect_uncached = element_rect
_physical_connectors_uncached = physical_connectors
_centerline_uncached = duct_centerline
_fab_reference_candidates_uncached = _fab_reference_candidates


def element_rect(elem):
    try:
        key = eid_int(elem.Id)
    except Exception:
        return _element_rect_uncached(elem)
    if key not in _ELEMENT_RECT_CACHE:
        _ELEMENT_RECT_CACHE[key] = _element_rect_uncached(elem)
    return _ELEMENT_RECT_CACHE[key]


def physical_connectors(elem):
    try:
        key = eid_int(elem.Id)
    except Exception:
        return _physical_connectors_uncached(elem)
    if key not in _CONNECTOR_CACHE:
        _CONNECTOR_CACHE[key] = list(_physical_connectors_uncached(elem))
    return _CONNECTOR_CACHE[key]


def duct_centerline(elem):
    try:
        key = eid_int(elem.Id)
    except Exception:
        return _centerline_uncached(elem)
    if key not in _CENTERLINE_CACHE:
        _CENTERLINE_CACHE[key] = _centerline_uncached(elem)
    return _CENTERLINE_CACHE[key]


def _fab_reference_candidates(elem, run_line):
    try:
        axis = plan_vec(run_line.Direction)
        mid = line_midpoint(run_line)
        key = (eid_int(elem.Id),
               round(axis.X, 4), round(axis.Y, 4),
               round(mid.X, 2), round(mid.Y, 2))
    except Exception:
        return _fab_reference_candidates_uncached(elem, run_line)
    if key not in _FAB_REF_CACHE:
        _FAB_REF_CACHE[key] = list(_fab_reference_candidates_uncached(elem, run_line))
    return _FAB_REF_CACHE[key]


def _strict_parallel_dot():
    return math.cos(math.radians(STRICT_REF_PARALLEL_DEG))


def _reference_geometry_object(owner, ref):
    try:
        return owner.GetGeometryObjectFromReference(ref)
    except Exception:
        pass
    try:
        other = doc.GetElement(ref.ElementId)
        if other is not None:
            return other.GetGeometryObjectFromReference(ref)
    except Exception:
        pass
    return None


def _fabrication_reference_check(owner, ref, grid_info, candidate=None):
    """Use original source references with MODEL-coordinate geometry evidence.

    GetGeometryObjectFromReference can return symbol-local geometry. Its raw
    tangent/normal must not be compared to a host-grid model axis. Harvesting
    computes directions with the full nested instance transform while retaining
    the original Edge/Face/Curve/endpoint Reference for NewDimension.
    """
    if ref is None or grid_info is None:
        return False, 'missing-reference-or-grid'
    try:
        if eid_int(ref.ElementId) != eid_int(owner.Id):
            return False, 'reference-owner-mismatch'
    except Exception:
        return False, 'reference-owner-unavailable'
    direction = None
    normal = None
    if candidate is not None:
        if ref is not candidate['ref']:
            key = _stable_reference_key(ref)
            if key is None or key != _stable_reference_key(candidate['ref']):
                return False, 'reference-evidence-mismatch'
        if candidate.get('kind') == 'endpoint':
            # This Reference comes from the actual Edge.GetEndPointReference.
            # A source corner is a point, not its parent's line reference. End
            # caps commonly expose transverse/vertical edges, so comparing that
            # parent tangent with the grid rejects genuine duct corner points.
            index = candidate.get('endpoint_index')
            endpoint = candidate.get('model_start' if index == 0 else 'model_end')
            witness = candidate.get('witness')
            if index not in (0, 1) or endpoint is None or witness is None:
                return False, 'missing-source-endpoint-proof'
            try:
                delta = ((endpoint.X-witness.X)**2 + (endpoint.Y-witness.Y)**2 +
                         (endpoint.Z-witness.Z)**2)
                if math.isnan(delta) or math.isinf(delta) or delta > 1e-12:
                    return False, 'source-endpoint-position-mismatch'
            except Exception:
                return False, 'invalid-source-endpoint-proof'
            return True, 'verified-source-corner-point'
        direction = candidate.get('model_direction')
        normal = candidate.get('model_normal')
        if direction is None and normal is None:
            return False, 'missing-model-geometry-proof'
    else:
        # Non-instance callers can still use resolved geometry. Fabrication
        # placement always supplies harvested model-coordinate evidence.
        go = _reference_geometry_object(owner, ref)
        try:
            crv = go.AsCurve() if isinstance(go, DB.Edge) else go
            if isinstance(crv, DB.Line):
                direction = crv.Direction
            elif isinstance(go, DB.PlanarFace):
                normal = go.FaceNormal
        except Exception:
            return False, 'reference-geometry-unavailable'
    try:
        if direction is not None:
            d = direction.Normalize()
            if abs(float(d.Z)) > STRICT_REF_MAX_Z:
                return False, 'sloped-source-edge'
            a = plan_vec(d)
            ok = a is not None and abs(dot_xy(a, grid_info['axis'])) >= _strict_parallel_dot()
            return ok, 'parallel-model-edge' if ok else 'model-edge-not-parallel'
        if normal is not None:
            n = normal.Normalize()
            if abs(float(n.Z)) > 0.02:
                return False, 'nonvertical-source-face'
            a = plan_vec(n)
            ok = a is not None and abs(dot_xy(a, perp_xy(grid_info['axis']))) >= _strict_parallel_dot()
            return ok, 'parallel-model-face' if ok else 'model-face-not-parallel'
    except Exception:
        return False, 'invalid-model-geometry'
    return False, 'unsupported-source-geometry'


def _stable_fabrication_reference_to_grid(owner, ref, grid_info, candidate=None):
    return _fabrication_reference_check(owner, ref, grid_info, candidate)[0]


def _record_fabrication_reference_check(owner, candidate, grid_info, valid, reason):
    records = globals().setdefault('AUTODIM_REFERENCE_DIAGNOSTICS', {})
    source = eid_int(owner.Id)
    key = (source, _fab_candidate_key(candidate['ref'], candidate['source']),
           eid_int(grid_info['element'].Id))
    if key not in records:
        records[key] = {'source_id': source, 'grid_id': key[2],
                        'grid_name': str(grid_info['name']), 'source': candidate['source'],
                        'kind': candidate['kind'], 'accepted': bool(valid), 'reason': reason,
                        'model_direction': _audit_point(candidate.get('model_direction')),
                        'model_normal': _audit_point(candidate.get('model_normal')),
                        'model_witness': _audit_point(candidate.get('witness')),
                        'endpoint_index': candidate.get('endpoint_index'),
                        'abs_run_offset_ft': float(candidate['abs_offset']),
                        'stable_key_available': _stable_reference_key(candidate['ref']) is not None,
                        'reference_owner_id': eid_int(candidate['ref'].ElementId)}
    return valid


def _validated_record_for_reference(valid, ref):
    """Match the original Reference, without using decorated display labels.

    The old fallback identity included a source label. The edge/center adapter
    adds a label prefix, which could discard accepted refs when Revit does not
    expose a stable representation. Cached original reference identity works
    in that case; separately resolved objects require a matching stable key.
    """
    for candidate in valid.values():
        if ref is candidate['ref']:
            return candidate
    key = _stable_reference_key(ref)
    if key is not None:
        for candidate in valid.values():
            if _stable_reference_key(candidate['ref']) == key:
                return candidate
    return None


def _validated_fabrication_candidates(elem, run_line, grid_info):
    out = {}
    for c in _fab_reference_candidates(elem, run_line):
        ok, reason = _fabrication_reference_check(elem, c['ref'], grid_info, c)
        _record_fabrication_reference_check(elem, c, grid_info, ok, reason)
        if ok:
            out[_fab_candidate_key(c['ref'], c['source'])] = c
        else:
            _STABILITY_STATS['direct_refs_rejected'] += 1
    return out


# Filter only Fabrication references. Native Revit references keep their own
# hardened path. Line/face references must be parallel to the grid in model space. Actual
# corner-point references instead prove their endpoint identity and position.
_fab_center_candidates_unfiltered = fabrication_center_reference_candidates
_fab_edge_candidates_unfiltered = fabrication_edge_candidates_toward_grid


def fabrication_center_reference_candidates(elem, run_line, grid_info):
    valid = _validated_fabrication_candidates(elem, run_line, grid_info)
    raw = _fab_center_candidates_unfiltered(elem, run_line, grid_info)
    out = []
    for ref, source in raw:
        candidate = _validated_record_for_reference(valid, ref)
        if candidate is not None and candidate['abs_offset'] <= CERT_VALUE_TOL_FT:
            out.append((ref, source))
    return out[:FAB_MAX_REFERENCE_CANDIDATES]


def fabrication_edge_candidates_toward_grid(elem, run_line, grid_info):
    valid = _validated_fabrication_candidates(elem, run_line, grid_info)
    raw = _fab_edge_candidates_unfiltered(elem, run_line, grid_info)
    return [(dist, ref, witness, source) for dist, ref, witness, source in raw
            if _validated_record_for_reference(valid, ref) is not None][:FAB_MAX_REFERENCE_CANDIDATES]


def _nearest_any_grid_for_point(point, grids):
    best = None
    best_dist = None
    best_rank = None
    for g in grids:
        try:
            n = perp_xy(g['axis'])
            d = abs(dot_xy(vector_xy(point, g['origin']), n))
        except Exception:
            continue
        if d > MAX_GRID_DISTANCE_FT:
            continue
        rank = _grid_rank(g, d)
        if rank is None:
            continue
        if best is None or rank < best_rank:
            best = g
            best_dist = d
            best_rank = rank
    if best is None or best_dist is None:
        return None
    return best


def _raw_fab_edge_location(elem, run_line, grid_info):
    """Geometry LOCATION only; the reference itself is not used here."""
    try:
        cands = _fab_reference_candidates(elem, run_line)
        side = _fab_grid_side_sign(run_line, grid_info)
        usable = [c for c in cands if c['kind'] in ('edge', 'curve', 'endpoint')
                  and c['abs_offset'] >= FAB_SIDE_MIN_OFFSET_FT]
        if side != 0.0:
            same = [c for c in usable if c['offset'] * side > 0.0]
            if same:
                usable = same
        usable.sort(key=lambda c: (-c['abs_offset'], c['source']))
        if usable:
            p = usable[0]['witness']
            return DB.XYZ(p.X, p.Y, view_plane_z())
    except Exception:
        pass
    return None


def _source_target_for_element(elem, grid_info):
    line = duct_centerline(elem)
    if line is None:
        return None, None
    mid = line_midpoint(line)
    shape = duct_shape(elem)
    if True and shape != 'round':
        p = _raw_fab_edge_location(elem, line, grid_info)
        if p is not None:
            return p, 'edge'
    return DB.XYZ(mid.X, mid.Y, view_plane_z()), 'round-center'


class _AutoDimFailurePreprocessor(DB.IFailuresPreprocessor):
    def PreprocessFailures(self, failuresAccessor):
        changed = False
        try:
            msgs = list(failuresAccessor.GetFailureMessages())
        except Exception:
            msgs = []
        for msg in msgs:
            try:
                fid = msg.GetFailureDefinitionId()
                if fid != DB.BuiltInFailures.DimensionFailures.LinearConstraintNotParallel:
                    continue
                doomed = List[DB.ElementId]()
                for eid in msg.GetFailingElementIds():
                    try:
                        if eid_int(eid) in _CREATED_DIM_IDS:
                            doomed.Add(eid)
                    except Exception:
                        pass
                if doomed.Count > 0:
                    failuresAccessor.DeleteElements(doomed)
                    _STABILITY_STATS['commit_pruned'] += int(doomed.Count)
                    changed = True
            except Exception:
                pass
        if changed:
            return DB.FailureProcessingResult.ProceedWithCommit
        return DB.FailureProcessingResult.Continue

# -----------------------------------------------------------------------------
# v0.2 COLLISION / BACKGROUND SCANNING
# -----------------------------------------------------------------------------
def _cad_weight(layer_name, paper_len):
    name = (layer_name or '').lower()
    hatch_words = ('hatch', 'pattern', 'fill', 'poche', 'poch', 'solid', 'tile', 'insul')
    major_words = ('wall', 'door', 'window', 'glaz', 'partition', 'shaft', 'column',
                   'case', 'mill', 'stair', 'beam', 'struct', 'curb', 'arch')
    if any(x in name for x in hatch_words):
        return W_CAD_HATCH
    if any(x in name for x in major_words):
        return W_CAD_MAJOR
    if paper_len >= 0.80:
        return W_CAD_MEDIUM
    if paper_len >= 0.20:
        return W_CAD_MINOR
    return 0.5


def _graphics_style_name(obj, cache):
    try:
        sid = obj.GraphicsStyleId
        key = eid_int(sid)
        if key < 0:
            return ''
        if key in cache:
            return cache[key]
        gs = doc.GetElement(sid)
        name = ''
        if gs is not None and gs.GraphicsStyleCategory is not None:
            try:
                if view.GetCategoryHidden(gs.GraphicsStyleCategory.Id):
                    cache[key] = None
                    return None
            except Exception:
                pass
            try:
                name = gs.GraphicsStyleCategory.Name or ''
            except Exception:
                name = ''
        cache[key] = name
        return name
    except Exception:
        return ''


def _add_cad_polyline(points, grid, source_id, counter, scan_rect, layer_name):
    if points is None or len(points) < 2:
        return
    factor = max(paper_to_model(1.0), 1e-9)
    for i in range(len(points) - 1):
        if counter[0] >= MAX_CAD_SEGMENTS:
            return
        a = uv_of_point(points[i]); b = uv_of_point(points[i + 1])
        if dist2_uv(a, b) < paper_to_model(0.004):
            continue
        sr = (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))
        if scan_rect is not None and not rect_intersects(sr, scan_rect):
            continue
        plen = dist2_uv(a, b) / factor
        wt = _cad_weight(layer_name, plen)
        if wt < CAD_MIN_WEIGHT_TO_INDEX:
            continue
        grid.add_segment('cad', a, b, wt, source_id)
        counter[0] += 1


def _scan_cad_geometry(geo, grid, source_id, counter, scan_rect, style_cache):
    if geo is None or counter[0] >= MAX_CAD_SEGMENTS:
        return
    for obj in geo:
        if counter[0] >= MAX_CAD_SEGMENTS:
            return
        try:
            if isinstance(obj, DB.GeometryInstance):
                _scan_cad_geometry(obj.GetInstanceGeometry(), grid, source_id, counter, scan_rect, style_cache)
            elif isinstance(obj, DB.PolyLine):
                lname = _graphics_style_name(obj, style_cache)
                if lname is None:
                    continue
                _add_cad_polyline(list(obj.GetCoordinates()), grid, source_id, counter, scan_rect, lname)
            elif isinstance(obj, DB.Curve):
                lname = _graphics_style_name(obj, style_cache)
                if lname is None:
                    continue
                _add_cad_polyline(list(obj.Tessellate()), grid, source_id, counter, scan_rect, lname)
        except Exception:
            pass


def scan_visible_dwgs(grid, scan_rect):
    counter = [0]
    imports_count = 0
    failures = 0
    style_cache = {}
    opts = DB.Options()
    try:
        opts.View = view
    except Exception:
        pass
    opts.IncludeNonVisibleObjects = False
    opts.ComputeReferences = False
    try:
        imports = (DB.FilteredElementCollector(doc, view.Id)
                   .OfClass(DB.ImportInstance)
                   .WhereElementIsNotElementType())
    except Exception:
        return (0, 0, False, 0)
    for imp in imports:
        if counter[0] >= MAX_CAD_SEGMENTS:
            break
        try:
            if imp.IsHidden(view):
                continue
        except Exception:
            pass
        r = element_rect(imp)
        if scan_rect is not None and r is not None and not rect_intersects(r, scan_rect):
            continue
        imports_count += 1
        try:
            geo = imp.get_Geometry(opts)
            if geo is None:
                failures += 1
                continue
            _scan_cad_geometry(geo, grid, eid_int(imp.Id), counter, scan_rect, style_cache)
        except Exception:
            failures += 1
    return (imports_count, counter[0], counter[0] >= MAX_CAD_SEGMENTS, failures)


def _add_category_rects(grid, bic_name, kind, weight, pad_paper=0.012):
    try:
        bic = getattr(DB.BuiltInCategory, bic_name)
        elems = (DB.FilteredElementCollector(doc, view.Id)
                 .OfCategory(bic)
                 .WhereElementIsNotElementType())
        for e in elems:
            r = element_rect(e)
            if r is not None:
                grid.add_rect(kind, rect_expand(r, paper_to_model(pad_paper)), weight, eid_int(e.Id))
    except Exception:
        pass


def _linked_element_rect(link_inst, elem):
    """Return linked-element XY bbox transformed into host coordinates."""
    try:
        bb = elem.get_BoundingBox(None)
    except Exception:
        bb = None
    if bb is None:
        return None
    try:
        bb_tr = bb.Transform
    except Exception:
        bb_tr = DB.Transform.Identity
    try:
        link_tr = link_inst.GetTotalTransform()
    except Exception:
        try:
            link_tr = link_inst.GetTransform()
        except Exception:
            link_tr = DB.Transform.Identity
    pts = []
    try:
        mn = bb.Min; mx = bb.Max
        for x in (mn.X, mx.X):
            for y in (mn.Y, mx.Y):
                for z in (mn.Z, mx.Z):
                    q = DB.XYZ(x, y, z)
                    try:
                        q = bb_tr.OfPoint(q)
                    except Exception:
                        pass
                    try:
                        q = link_tr.OfPoint(q)
                    except Exception:
                        pass
                    pts.append(uv_of_point(q))
    except Exception:
        return None
    if not pts:
        return None
    return (min(x[0] for x in pts), min(x[1] for x in pts),
            max(x[0] for x in pts), max(x[1] for x in pts))


def scan_linked_background(grid, scan_rect):
    """Index common architectural/structural categories from visible RVT links.

    v0.8 retains the batched category filters into one collector per linked document.
    Earlier builds created a separate collector for every category in every link,
    which worked but doubled runtime on larger coordinated models. Linked geometry
    remains a soft placement cost only.
    """
    link_count = 0
    elem_count = 0
    capped = False
    cats = (
        'OST_Walls', 'OST_Doors', 'OST_Windows', 'OST_StructuralColumns',
        'OST_Columns', 'OST_StructuralFraming', 'OST_Casework', 'OST_Furniture',
        'OST_PlumbingFixtures', 'OST_SpecialityEquipment'
    )
    try:
        links = (DB.FilteredElementCollector(doc, view.Id)
                 .OfClass(DB.RevitLinkInstance)
                 .WhereElementIsNotElementType())
    except Exception:
        links = []
    for inst in links:
        try:
            if inst.IsHidden(view):
                continue
        except Exception:
            pass
        try:
            ldoc = inst.GetLinkDocument()
        except Exception:
            ldoc = None
        if ldoc is None:
            continue
        link_count += 1
        inst_id = eid_int(inst.Id)

        filters = List[DB.ElementFilter]()
        for bic_name in cats:
            try:
                bic = getattr(DB.BuiltInCategory, bic_name)
                filters.Add(DB.ElementCategoryFilter(bic))
            except Exception:
                continue
        try:
            if filters.Count == 0:
                continue
            if filters.Count == 1:
                collector = (DB.FilteredElementCollector(ldoc)
                             .WherePasses(filters[0])
                             .WhereElementIsNotElementType())
            else:
                multi = DB.LogicalOrFilter(filters)
                collector = (DB.FilteredElementCollector(ldoc)
                             .WherePasses(multi)
                             .WhereElementIsNotElementType())
        except Exception:
            # Compatibility fallback if a Revit/IronPython build rejects the
            # LogicalOrFilter overload. Keep the command functional.
            collector = []
            for bic_name in cats:
                try:
                    bic = getattr(DB.BuiltInCategory, bic_name)
                    for e in (DB.FilteredElementCollector(ldoc)
                              .OfCategory(bic)
                              .WhereElementIsNotElementType()):
                        collector.append(e)
                except Exception:
                    continue

        for e in collector:
            if elem_count >= MAX_LINK_BACKGROUND_ELEMENTS:
                capped = True
                return (link_count, elem_count, capped)
            try:
                r = _linked_element_rect(inst, e)
                if r is None:
                    continue
                if scan_rect is not None and not rect_intersects(r, scan_rect):
                    continue
                sid = 'link:{0}:{1}'.format(inst_id, eid_int(e.Id))
                grid.add_rect('background', rect_expand(r, paper_to_model(0.006)),
                              W_BACKGROUND, sid)
                elem_count += 1
            except Exception:
                continue
    return (link_count, elem_count, capped)


def build_dimension_obstacle_grid(targets_and_grids):
    grid = SpatialGrid(max(paper_to_model(0.65), 0.5))

    # MEP geometry: native duct plus the full fabrication ductwork category. The
    # selected host is ignored while its own candidate is scored, but it remains
    # an obstacle for dimensions belonging to other ducts.
    _add_category_rects(grid, 'OST_DuctCurves', 'duct', W_DUCT, 0.010)
    try:
        parts = (DB.FilteredElementCollector(doc, view.Id)
                 .OfClass(DB.FabricationPart)
                 .WhereElementIsNotElementType())
        fab_id = bic_int(DB.BuiltInCategory.OST_FabricationDuctwork)
        for e in parts:
            try:
                if e.Category is None or eid_int(e.Category.Id) != fab_id:
                    continue
                r = element_rect(e)
                if r is None:
                    continue
                kind = 'duct' if is_fabrication_straight(e) else 'fitting'
                wt = W_DUCT if kind == 'duct' else W_FITTING
                grid.add_rect(kind, rect_expand(r, paper_to_model(0.010)), wt, eid_int(e.Id))
            except Exception:
                pass
    except Exception:
        pass

    for bic_name in ('OST_DuctFitting', 'OST_DuctAccessory', 'OST_FlexDuctCurves',
                     'OST_DuctTerminal', 'OST_MechanicalEquipment'):
        _add_category_rects(grid, bic_name, 'fitting', W_FITTING, 0.012)

    # Native architectural/model background. These are intentionally soft so the
    # dimension can cross background geometry when every clean route is blocked.
    for bic_name in ('OST_Walls', 'OST_Doors', 'OST_Windows', 'OST_StructuralColumns',
                     'OST_Columns', 'OST_Casework', 'OST_Furniture',
                     'OST_PlumbingFixtures', 'OST_SpecialityEquipment'):
        _add_category_rects(grid, bic_name, 'background', W_BACKGROUND, 0.006)

    # Existing annotation is hard. Dimensions are indexed separately so the
    # candidate scorer can report exactly what it is avoiding.
    try:
        owned = (DB.FilteredElementCollector(doc)
                 .OwnedByView(view.Id)
                 .WhereElementIsNotElementType())
        for e in owned:
            try:
                kind = None; wt = None; pad = 0.012
                if isinstance(e, DB.Dimension):
                    # Model existing dimensions precisely. The old whole-element
                    # bounding box included long witness lines and created many
                    # false "annotation blocked" misses.
                    try:
                        crv = e.Curve
                        if isinstance(crv, DB.Line):
                            _d0 = uv_of_point(crv.GetEndPoint(0))
                            _d1 = uv_of_point(crv.GetEndPoint(1))
                            grid.add_segment(
                                'dimension_line',
                                _d0, _d1,
                                W_EXISTING_DIM_LINE,
                                eid_int(e.Id)
                            )
                            _lane = rect_expand(
                                (min(_d0[0], _d1[0]), min(_d0[1], _d1[1]),
                                 max(_d0[0], _d1[0]), max(_d0[1], _d1[1])),
                                paper_to_model(DIMENSION_LANE_HALO_PAPER_IN))
                            grid.add_rect('dimension_lane', _lane,
                                          W_DIMENSION_LANE, eid_int(e.Id))
                    except Exception:
                        pass
                    try:
                        tp = e.TextPosition
                        if tp is not None:
                            grid.add_rect(
                                'dimension_text',
                                _text_rect_at_point(tp, _dimension_text_direction(e), _dimension_value(e)),
                                W_EXISTING_DIM,
                                eid_int(e.Id)
                            )
                    except Exception:
                        pass
                    continue
                elif isinstance(e, DB.IndependentTag):
                    # IndependentTag bounding boxes can include long leaders.
                    # Keep the visible tag head hard, but make the full leader
                    # extent soft so it does not falsely eliminate an entire run.
                    try:
                        r = element_rect(e)
                        if r is not None:
                            grid.add_rect('tag_leader',
                                          rect_expand(r, paper_to_model(0.010)),
                                          W_TAG_LEADER, eid_int(e.Id))
                        hp = e.TagHeadPosition
                        if hp is not None:
                            hw = paper_to_model(TAG_HEAD_HALF_W_PAPER_IN)
                            hh = paper_to_model(TAG_HEAD_HALF_H_PAPER_IN)
                            grid.add_rect('tag',
                                          (hp.X - hw, hp.Y - hh,
                                           hp.X + hw, hp.Y + hh),
                                          W_TAG, eid_int(e.Id))
                            continue
                    except Exception:
                        pass
                    kind = 'tag'; wt = W_TAG; pad = 0.025
                elif isinstance(e, DB.TextNote):
                    kind = 'annotation'; wt = W_ANNOTATION; pad = 0.018
                else:
                    try:
                        if isinstance(e, DB.SpatialElementTag):
                            kind = 'annotation'; wt = W_ANNOTATION; pad = 0.018
                    except Exception:
                        pass
                    if kind is None:
                        try:
                            if e.Category is not None and eid_int(e.Category.Id) == bic_int(DB.BuiltInCategory.OST_GenericAnnotation):
                                kind = 'annotation'; wt = W_ANNOTATION; pad = 0.018
                        except Exception:
                            pass
                if kind is None:
                    continue
                r = element_rect(e)
                if r is not None:
                    grid.add_rect(kind, rect_expand(r, paper_to_model(pad)), wt, eid_int(e.Id))
            except Exception:
                pass
    except Exception:
        pass

    # CAD scan region must include the complete corridor between each selected
    # duct and its grid, not just the duct itself.
    scan_rects = []
    for elem, gdata in targets_and_grids:
        try:
            line = duct_centerline(elem)
            if line is None or gdata is None:
                continue
            grid_info = gdata[0]
            _, _, _, axis, perp, mid = gdata
            gpt = grid_plan_point(mid, perp, grid_info['origin'])
            r = element_rect(elem)
            if r is not None:
                scan_rects.append(r)
            a = uv_of_point(mid); b = uv_of_point(gpt)
            scan_rects.append(rect_expand((min(a[0], b[0]), min(a[1], b[1]),
                                           max(a[0], b[0]), max(a[1], b[1])),
                                          paper_to_model(CAD_SCAN_MARGIN_PAPER_IN)))
        except Exception:
            pass
    scan_rect = rect_union(scan_rects)
    link_info = scan_linked_background(grid, scan_rect)
    dwg_info = scan_visible_dwgs(grid, scan_rect)
    return grid, dwg_info, link_info


def candidate_axis_shifts(duct_line, target_id=None):
    """Return signed along-run shifts for dimension placement.

    Legacy helper can supplement representative-piece shifts with positions spread across
    the full same-run envelope captured during de-duplication. This lets a short
    split segment borrow a clean corridor farther along its actual duct run.
    """
    try:
        length = float(duct_line.Length)
    except Exception:
        length = 0.0
    max_shift = max(0.0, length * DIM_MAX_SHIFT_FRACTION)
    values = []
    for paper in DIM_CANDIDATE_SHIFTS_PAPER_IN:
        val = paper_to_model(paper)
        if abs(val) <= max_shift + 1e-9:
            values.append((val, abs(float(paper)), False))
    # On long representative pieces, test near-end points as before.
    for frac in (0.30, -0.30, 0.40, -0.40, 0.46, -0.46):
        val = length * frac
        if abs(val) <= max_shift + 1e-9:
            paper = abs(val) / max(paper_to_model(1.0), 1e-9)
            values.append((val, paper, False))

    # Full local-run envelope discovered by collapse_same_run_dimensions().
    if target_id is not None and target_id in _RUN_CORRIDOR_LIMITS:
        try:
            can_x, can_y, neg_can, pos_can = _RUN_CORRIDOR_LIMITS[target_id]
            actual = plan_vec(duct_line.Direction)
            if actual is not None:
                sign = 1.0 if (actual.X * can_x + actual.Y * can_y) >= 0.0 else -1.0
                neg_lim = neg_can if sign > 0.0 else pos_can
                pos_lim = pos_can if sign > 0.0 else neg_can
                for frac in RUN_CORRIDOR_FRACTIONS:
                    if pos_lim > 1e-6:
                        val = pos_lim * frac
                        paper = abs(val) / max(paper_to_model(1.0), 1e-9)
                        values.append((val, paper, True))
                    if neg_lim > 1e-6:
                        val = -neg_lim * frac
                        paper = abs(val) / max(paper_to_model(1.0), 1e-9)
                        values.append((val, paper, True))
        except Exception:
            pass

    # Coverage rescue: test dimension-line locations just beyond each
    # physical straight. These are penalized heavily, so an inside-run corridor
    # always wins when it is reasonably clean.
    if length > 1e-6:
        half_len = 0.5 * length
        for extra_paper in OUTSIDE_CORRIDOR_EXTRA_PAPER_IN:
            extra_model = paper_to_model(extra_paper)
            for sign in (-1.0, 1.0):
                val = sign * (half_len + extra_model)
                paper = abs(val) / max(paper_to_model(1.0), 1e-9)
                values.append((val, paper, True))

    out = []
    seen = set()
    for val, paper, extended in values:
        key = int(round(val * 10000.0))
        if key in seen:
            continue
        seen.add(key)
        out.append((val, paper, extended))
    return out


def _dimension_text_profile():
    """Read the same default linear dimension type that NewDimension uses."""
    if '_DIM_TEXT_PROFILE_CACHE' in globals():
        return globals()['_DIM_TEXT_PROFILE_CACHE']
    profile = None
    try:
        typ = doc.GetElement(doc.GetDefaultElementTypeId(DB.ElementTypeGroup.LinearDimensionType))
        size = typ.get_Parameter(DB.BuiltInParameter.TEXT_SIZE)
        size_in = float(size.AsDouble()) * 12.0
        if not (0.01 <= size_in <= 1.0):
            raise ValueError('Unknown dimension text size')
        font_param = typ.get_Parameter(DB.BuiltInParameter.TEXT_FONT)
        font = str(font_param.AsString() or 'Arial') if font_param else 'Arial'
        scale = 1.0
        try:
            width_param = typ.get_Parameter(DB.BuiltInParameter.TEXT_WIDTH_SCALE)
            if width_param:
                scale = max(0.1, min(5.0, float(width_param.AsDouble())))
        except Exception:
            pass
        profile = {'type': typ, 'size_in': size_in, 'font': font, 'width_scale': scale}
    except Exception:
        pass
    globals()['_DIM_TEXT_PROFILE_CACHE'] = profile
    return profile


def _dimension_label(value_ft, profile):
    units = doc.GetUnits()
    spec = DB.SpecTypeId.Length
    try:
        options = profile['type'].GetUnitsFormatOptions()
    except Exception:
        options = None
    if options is not None and not options.UseDefault:
        value_options = DB.FormatValueOptions()
        value_options.SetFormatOptions(options)
        return str(DB.UnitFormatUtils.Format(units, spec, abs(float(value_ft)), False, value_options))
    return str(DB.UnitFormatUtils.Format(units, spec, abs(float(value_ft)), False))


def _measure_dimension_label(label, profile):
    """Paper-inch glyph bounds; Windows GDI when available, font-sized fallback."""
    bitmap = graphics = font = None
    try:
        import clr
        clr.AddReference('System.Drawing')
        from System import Single
        from System.Drawing import Bitmap, Graphics, Font, FontStyle, GraphicsUnit, PointF, StringFormat
        bitmap = Bitmap(1, 1)
        bitmap.SetResolution(Single(96.0), Single(96.0))
        graphics = Graphics.FromImage(bitmap)
        font = Font(profile['font'], Single(profile['size_in'] * 72.0),
                    FontStyle.Regular, GraphicsUnit.Point)
        size = graphics.MeasureString(label, font, PointF(0.0, 0.0), StringFormat.GenericTypographic)
        return (float(size.Width) / 96.0 * profile['width_scale'],
                max(profile['size_in'], float(size.Height) / 96.0), 'windows-font')
    except Exception:
        # Keep a conservative width for glyphs, fractions, feet/inch symbols.
        return (max(1.5, len(label) * 0.65) * profile['size_in'] * profile['width_scale'],
                profile['size_in'] * 1.25, 'font-estimate')
    finally:
        for item in (font, graphics, bitmap):
            if item is not None:
                try:
                    item.Dispose()
                except Exception:
                    pass


def _dimension_text_size(value_ft):
    if value_ft is None:
        return None
    profile = _dimension_text_profile()
    if profile is None:
        return None
    try:
        value_key = round(abs(float(value_ft)), 8)
        values = globals().setdefault('_DIM_TEXT_VALUE_CACHE', {})
        if value_key in values:
            return values[value_key]
        label = _dimension_label(value_ft, profile)
        cache = globals().setdefault('_DIM_TEXT_METRIC_CACHE', {})
        if label not in cache:
            width, height, method = _measure_dimension_label(label, profile)
            # Include unit decoration even if a platform font metric is tiny.
            width = max(width, profile['size_in'] * 1.5)
            cache[label] = (width, height)
            globals().setdefault('AUTODIM_TEXT_METRICS', {})[label] = {
                'label': label, 'width_paper_in': width, 'height_paper_in': height,
                'font': profile['font'], 'font_size_paper_in': profile['size_in'],
                'method': method}
        values[value_key] = cache[label]
        return cache[label]
    except Exception:
        # Never guess small bounds when the project/style units are unavailable.
        return None


def dimension_text_rect(gpt, tpt):
    center = DB.XYZ((gpt.X + tpt.X) * 0.5, (gpt.Y + tpt.Y) * 0.5,
                    (gpt.Z + tpt.Z) * 0.5)
    return _text_rect_at_point(center, plan_vec(vector_xy(gpt, tpt)), distance_xy(gpt, tpt))


def run_ignore_source_ids(target_id):
    ids = _RUN_MEMBER_IDS.get(target_id)
    if ids:
        return set(ids)
    return set([target_id])


def _dimension_text_pocket_candidates(gpt, tpt):
    """Return candidate value positions along the dimension line.

    The midpoint remains first. Fractional positions cover long grid-to-duct
    strings, while small paper-space offsets cover shorter dimensions.
    """
    vx = tpt.X - gpt.X
    vy = tpt.Y - gpt.Y
    length = math.sqrt(vx * vx + vy * vy)
    if length < 1e-9:
        return []
    ux = vx / length
    uy = vy / length
    z = (gpt.Z + tpt.Z) * 0.5
    out = []
    seen = set()

    def add_point(q, move_model):
        key = (int(round(q.X * 10000.0)), int(round(q.Y * 10000.0)))
        if key in seen:
            return
        seen.add(key)
        move_paper = abs(move_model) / max(paper_to_model(1.0), 1e-9)
        out.append((q, move_paper))

    for frac in DIM_TEXT_POCKET_FRACTIONS:
        f = max(0.08, min(0.92, float(frac)))
        q = DB.XYZ(gpt.X + vx * f, gpt.Y + vy * f, z)
        add_point(q, length * (f - 0.5))

    mid = DB.XYZ((gpt.X + tpt.X) * 0.5, (gpt.Y + tpt.Y) * 0.5, z)
    for paper in DIM_TEXT_POCKET_PAPER_OFFSETS:
        d = paper_to_model(paper)
        # Do not push beyond the string by more than a small amount.
        max_d = max(0.0, length * 0.44)
        if abs(d) > max_d + 1e-9:
            continue
        q = DB.XYZ(mid.X + ux * d, mid.Y + uy * d, z)
        add_point(q, d)
    size = _dimension_text_size(length)
    half_label = (size[0] * 0.5 if size else DIM_TEXT_HALF_W_PAPER_IN) + DIM_TEXT_HALO_PAPER_IN
    for paper in (half_label + 0.04, half_label + 0.18, half_label + 0.36, half_label + 0.60):
        extra = paper_to_model(paper)
        for end, sign in ((gpt, -1.0), (tpt, 1.0)):
            q = DB.XYZ(end.X + ux * extra, end.Y + uy * extra, z)
            add_point(q, length * 0.5 + extra)
    return out


def _text_bounds_visible(bounds):
    """Keep moved labels within an enabled rectangular annotation crop."""
    try:
        if not view.CropBoxActive:
            return True
        active = view.get_Parameter(DB.BuiltInParameter.VIEWER_ANNOTATION_CROP_ACTIVE)
        if active is None or active.AsInteger() == 0:
            return True
        box = view.CropBox
        manager = view.GetCropRegionShapeManager()
        x0 = box.Min.X - manager.LeftAnnotationCropOffset
        x1 = box.Max.X + manager.RightAnnotationCropOffset
        y0 = box.Min.Y - manager.BottomAnnotationCropOffset
        y1 = box.Max.Y + manager.TopAnnotationCropOffset
        inverse = box.Transform.Inverse
        for x, y in ((bounds[0], bounds[1]), (bounds[0], bounds[3]),
                     (bounds[2], bounds[1]), (bounds[2], bounds[3])):
            point = inverse.OfPoint(DB.XYZ(x, y, view_plane_z()))
            if point.X < x0 or point.X > x1 or point.Y < y0 or point.Y > y1:
                return False
        return True
    except Exception:
        # Unknown crop APIs do not license changing the view's crop settings.
        globals()['AUTODIM_TEXT_CROP_UNVERIFIED'] = True
        return True


def _best_dimension_text_pocket(obstacle_grid, gpt, tpt, target_id):
    ignore_ids = run_ignore_source_ids(target_id)
    options = []
    for q, move_paper in _dimension_text_pocket_candidates(gpt, tpt):
        r = _text_rect_at_point(q, plan_vec(vector_xy(gpt, tpt)), distance_xy(gpt, tpt))
        if not _text_bounds_visible(r):
            continue
        # A witness must touch its source, but its label must clear ALL MEP.
        score, hits = obstacle_grid.score_rect(r, ignore_source_ids=set())
        hard = sum(int(hits.get(k, 0)) for k in HARD_COLLISION_KINDS)
        mep = int(hits.get('duct', 0)) + int(hits.get('fitting', 0))
        options.append((hard, mep, score + move_paper * DIM_TEXT_POCKET_MOVE_PENALTY,
                        move_paper, q, r, hits))
    if not options:
        return None
    options.sort(key=lambda x: (x[0], x[1], x[2], x[3]))
    return options[0]


def score_dimension_candidate(obstacle_grid, gpt, tpt, target_id, shift_paper):
    a = uv_of_point(gpt); b = uv_of_point(tpt)
    # Witness-line collisions and value collisions are solved separately. v1.2
    # also searches for a clear value pocket before rejecting a valid corridor.
    ignore_ids = run_ignore_source_ids(target_id)
    line_score, line_hits = obstacle_grid.score_segment(
        a, b, ignore_source_ids=ignore_ids
    )
    tr = dimension_text_rect(gpt, tpt)
    text_score, text_hits = obstacle_grid.score_rect(
        tr, ignore_source_ids=set()
    )

    if not _text_bounds_visible(tr):
        text_hits['annotation'] = text_hits.get('annotation', 0) + 1
    base_hard = sum(int(text_hits.get(k, 0)) for k in HARD_COLLISION_KINDS)
    base_mep = int(text_hits.get('duct', 0)) + int(text_hits.get('fitting', 0))
    planned_text_point = None
    pocket_moved = False
    pocket_move_paper = 0.0

    if base_hard > 0 or base_mep > MAX_TEXT_MEP_OVERLAPS:
        pocket = _best_dimension_text_pocket(obstacle_grid, gpt, tpt, target_id)
        if pocket is not None:
            phard, pmep, pscore, pmove, pq, pr, phits = pocket
            # Use the pocket only if it genuinely improves the blocking tuple.
            if (phard, pmep, pscore) < (base_hard, base_mep, text_score):
                text_score = pscore
                text_hits = phits
                tr = pr
                planned_text_point = pq
                pocket_move_paper = pmove
                pocket_moved = pmove > 1e-6

    line_mep = int(line_hits.get('duct', 0)) + int(line_hits.get('fitting', 0))
    text_mep = int(text_hits.get('duct', 0)) + int(text_hits.get('fitting', 0))
    extra_line = max(0, line_mep - PREFERRED_MEP_LINE_CROSSINGS)
    crossing_pen = (line_mep * MEP_CROSSING_EXTRA_PENALTY +
                    extra_line * extra_line * MEP_CROSSING_QUADRATIC_PENALTY)
    score = (line_score + text_score * 1.15 + crossing_pen +
             abs(shift_paper) * DIM_SHIFT_PENALTY_PER_PAPER_IN)
    hits = {}
    for key in ('dimension_line', 'dimension_lane', 'dimension_text', 'tag', 'tag_leader', 'annotation', 'duct', 'fitting', 'background', 'cad'):
        hits[key] = line_hits.get(key, 0) + text_hits.get(key, 0)
    hits['_line_mep'] = line_mep
    hits['_text_mep'] = text_mep
    hits['_line_hard'] = sum(int(line_hits.get(k, 0)) for k in HARD_COLLISION_KINDS)
    hits['_text_hard'] = sum(int(text_hits.get(k, 0)) for k in HARD_COLLISION_KINDS)
    hits['_planned_text_point'] = planned_text_point
    hits['_text_pocket_moved'] = pocket_moved
    hits['_text_pocket_move_paper'] = pocket_move_paper
    return score, hits, tr


def _text_rect_at_point(p, direction=None, value_ft=None):
    """Conservative bounds for horizontal or line-aligned dimension text.

    Revit dimension styles can change the text reading convention. Include
    both orientations rather than assuming every value is horizontal. All
    sizes remain in paper space, converted using the active view scale.
    """
    size = _dimension_text_size(value_ft)
    if size is None:
        half_width, half_height = DIM_TEXT_HALF_W_PAPER_IN, DIM_TEXT_HALF_H_PAPER_IN
    else:
        half_width, half_height = size[0] * 0.5, size[1] * 0.5
    hw = paper_to_model(half_width + DIM_TEXT_HALO_PAPER_IN)
    hh = paper_to_model(half_height + DIM_TEXT_HALO_PAPER_IN)
    try:
        length = math.sqrt(direction.X ** 2 + direction.Y ** 2)
        if length < 1e-9:
            raise ValueError('Unknown dimension direction')
        ax = abs(direction.X) / length
        ay = abs(direction.Y) / length
        rotated_hw = ax * hw + ay * hh
        rotated_hh = ay * hw + ax * hh
        hw = max(hw, rotated_hw)
        hh = max(hh, rotated_hh)
    except Exception:
        hw = hh = max(hw, hh)
    return (p.X - hw, p.Y - hh, p.X + hw, p.Y + hh)


def _dimension_value(dim):
    try:
        return abs(float(dim.Value))
    except Exception:
        return None


def _dimension_text_direction(dim):
    try:
        return plan_vec(dim.Curve.Direction)
    except Exception:
        return None


def _layout_candidate_rank(score, shift_paper, hits):
    # Hard/text safety and crossing tiers are filtered before sorting. The
    # weighted score already penalizes movement; a second shift-first sort
    # previously forced a crowded midpoint to beat a clearer nearby station.
    return (int(hits.get('dimension_lane', 0)),
            line_mep_collision_count(hits), float(score), abs(float(shift_paper)))


def adjust_dimension_text(dim, obstacle_grid, gpt, tpt, target_id):
    """Nudge a single linear dimension's text only when readability improves.

    Geometry placement remains primary. This is a small post-pass comparable to
    mature AutoDim tools that move cramped values after the witness line is valid.
    """
    try:
        current = dim.TextPosition
    except Exception:
        return (False, None)
    if current is None:
        return (False, None)
    try:
        if not dim.IsTextPositionAdjustable():
            return (False, _text_rect_at_point(current, _dimension_text_direction(dim), _dimension_value(dim)))
    except Exception:
        # If Revit cannot establish adjustability, retain the text position.
        return (False, _text_rect_at_point(current, _dimension_text_direction(dim), _dimension_value(dim)))
    direction = plan_vec(vector_xy(gpt, tpt))
    if direction is None:
        return (False, _text_rect_at_point(current, _dimension_text_direction(dim), _dimension_value(dim)))

    options = []
    _text_nudges = (MANDATORY_TEXT_NUDGE_PAPER_IN
                    if bool(globals().get('_MANDATORY_RESCUE_MODE', False))
                    else DIM_TEXT_NUDGE_PAPER_IN)
    for paper in _text_nudges:
        d = paper_to_model(paper)
        q = DB.XYZ(current.X + direction.X * d,
                   current.Y + direction.Y * d,
                   current.Z)
        r = _text_rect_at_point(q, direction, _dimension_value(dim))
        if not _text_bounds_visible(r):
            continue
        score, hits = obstacle_grid.score_rect(r, ignore_source_ids=set([eid_int(dim.Id)]))
        hard = hard_collision_count(hits)
        mep = mep_collision_count(hits)
        # Text should be more conservative than the witness line. Do not nudge a
        # value into a pile of MEP just to shave a soft background penalty.
        options.append((hard, mep, score, abs(float(paper)), q, r))
    if not options:
        return (False, _text_rect_at_point(current, direction, _dimension_value(dim)))
    options.sort(key=lambda x: (x[0], x[1], x[2], x[3]))
    best = options[0]
    base = [x for x in options if x[3] <= 1e-9]
    base = base[0] if base else None
    if best[0] > 0 or best[1] > DIM_TEXT_NUDGE_MEP_LIMIT:
        return (False, _text_rect_at_point(current, direction, _dimension_value(dim)))
    if base is not None:
        # Move only for a real gain; otherwise leave Revit's natural text position.
        gain = (best[0] < base[0] or best[1] < base[1] or best[2] + 100.0 < base[2])
        if not gain or best[3] <= 1e-9:
            return (False, base[5])
    try:
        dim.TextPosition = best[4]
        return (True, best[5])
    except Exception:
        return (False, _text_rect_at_point(current, direction, _dimension_value(dim)))


def _created_dimension_text_is_clear(dim, obstacle_grid):
    try:
        point = dim.TextPosition
        if point is None:
            return False
        bounds = _text_rect_at_point(point, _dimension_text_direction(dim), _dimension_value(dim))
        if not _text_bounds_visible(bounds):
            return False
        score, hits = obstacle_grid.score_rect(bounds, ignore_source_ids=set([eid_int(dim.Id)]))
        return hard_collision_count(hits) == 0 and mep_collision_count(hits) == 0
    except Exception:
        return False


def reserve_created_dimension(obstacle_grid, dim, gpt, tpt, text_rect,
                              record_target=True):
    try:
        sid = eid_int(dim.Id)
    except Exception:
        sid = None
    _a = uv_of_point(gpt)
    _b = uv_of_point(tpt)
    obstacle_grid.add_segment('dimension_line', _a, _b, W_EXISTING_DIM_LINE, sid)
    _lane = rect_expand(
        (min(_a[0], _b[0]), min(_a[1], _b[1]),
         max(_a[0], _b[0]), max(_a[1], _b[1])),
        paper_to_model(DIMENSION_LANE_HALO_PAPER_IN))
    obstacle_grid.add_rect('dimension_lane', _lane, W_DIMENSION_LANE, sid)
    # Prefer Revit's actual dimension text position when available; otherwise use
    # the conservative estimate used during planning.
    actual_rect = None
    try:
        p = dim.TextPosition
        if p is not None:
            actual_rect = _text_rect_at_point(p, _dimension_text_direction(dim), _dimension_value(dim))
    except Exception:
        pass
    obstacle_grid.add_rect('dimension_text', actual_rect or text_rect, W_EXISTING_DIM, sid)
    if sid is not None and record_target:
        try:
            _CREATED_DIM_TARGETS[sid] = DB.XYZ(tpt.X, tpt.Y, tpt.Z)
        except Exception:
            pass


def duct_size_signature(elem):
    """Stable shape/size signature used only for same-run de-duplication."""
    for c in physical_connectors(elem):
        try:
            shape, dims = connector_signature(c)
            if dims:
                return (shape, tuple(round(float(x), 5) for x in dims))
        except Exception:
            pass
    if is_native_duct(elem):
        try:
            p = elem.get_Parameter(DB.BuiltInParameter.RBS_CURVE_DIAMETER_PARAM)
            if p is not None and p.HasValue and p.AsDouble() > 1e-8:
                return ('round', (round(float(p.AsDouble()), 5),))
        except Exception:
            pass
        vals = []
        for bip in (DB.BuiltInParameter.RBS_CURVE_WIDTH_PARAM,
                    DB.BuiltInParameter.RBS_CURVE_HEIGHT_PARAM):
            try:
                p = elem.get_Parameter(bip)
                vals.append(round(float(p.AsDouble()), 5) if p is not None and p.HasValue else 0.0)
            except Exception:
                vals.append(0.0)
        return ('rectangular', tuple(sorted(vals)))
    return (duct_shape(elem), ())


def _canonical_axis_from_line(line):
    axis = plan_vec(line.Direction) if line is not None else None
    if axis is None:
        return None
    # Make opposite element directions land in the same bucket.
    if axis.X < -1e-9 or (abs(axis.X) <= 1e-9 and axis.Y < 0.0):
        axis = DB.XYZ(-axis.X, -axis.Y, 0.0)
    return axis


# -----------------------------------------------------------------------------
# LOGICAL-LEG MEASUREMENT GROUPING v5.0
# -----------------------------------------------------------------------------
# Every raw straight is a drafting target FIRST.
# A piece can be suppressed only after Revit's own Connector.AllRefs proves
# physical continuity and both pieces measure the same line to the same grid.
#
# Geometric/proximity connector recovery is intentionally prohibited from
# target suppression. Extra dimensions are safer than silent misses.

_MEASURE_STATS = {}
# Runtime state explicitly owned by the Coverage-First engine.
_TOPOLOGY_STATS = {}
_CONNECTIVITY_STATS = {
    'allrefs_links': 0,
    'fallback_links': 0,
    'fallback_queries': 0,
}

MEASURE_AXIS_DOT = 0.9995
MEASURE_3D_DIR_DOT = 0.9990
MEASURE_OFFSET_TOL_FT = 1.0 / 192.0   # 1/16 in
MEASURE_Z_TOL_FT = 0.25 / 12.0        # 1/4 in
MEASURE_MAX_INLINE_HOPS = 3


def _same_connector_size(c0, c1):
    try:
        s0 = connector_signature(c0)
        s1 = connector_signature(c1)
        if s0[0] != s1[0] or len(s0[1]) != len(s1[1]):
            return False
        for a, b in zip(s0[1], s1[1]):
            if abs(float(a) - float(b)) > (1.0 / 192.0):
                return False
        return True
    except Exception:
        return False


def _strict_allrefs_other_owners(conn, owner_id):
    out = []
    seen = set()
    try:
        refs = conn.AllRefs
    except Exception:
        refs = []
    for rc in refs:
        try:
            other = rc.Owner
            if other is None:
                continue
            oid = eid_int(other.Id)
            if oid == owner_id or oid in seen:
                continue
            seen.add(oid)
            out.append(other)
        except Exception:
            pass
    return out


_CONNECTOR_SPATIAL_INDEX = None
_CONNECTOR_SPATIAL_CELL_FT = 1.0 / 48.0    # 1/4 in cell
_CONNECTOR_MATCH_TOL_FT = 1.0 / 96.0      # 1/8 in match
_CONNECTOR_SIZE_TOL_FT = 1.0 / 192.0      # 1/16 in size
_CONNECTOR_OPPOSITE_DOT = -0.70


def _connector_index_key(point):
    try:
        c = _CONNECTOR_SPATIAL_CELL_FT
        return (int(math.floor(point.X / c)),
                int(math.floor(point.Y / c)),
                int(math.floor(point.Z / c)))
    except Exception:
        return None


def _connector_sig_compatible(a, b):
    try:
        sa = connector_signature(a)
        sb = connector_signature(b)
        if sa[0] != sb[0] or len(sa[1]) != len(sb[1]):
            return False
        for x, y in zip(sa[1], sb[1]):
            if abs(float(x) - float(y)) > _CONNECTOR_SIZE_TOL_FT:
                return False
        return True
    except Exception:
        return False


def _connector_axis_compatible(a, b):
    da = connector_axis(a)
    db = connector_axis(b)
    if da is None or db is None:
        return True
    try:
        return da.Normalize().DotProduct(db.Normalize()) <= _CONNECTOR_OPPOSITE_DOT
    except Exception:
        return True


def _connector_index_elements():
    result = []
    seen = set()

    # Discipline-specific Fabrication parts.
    try:
        parts = (DB.FilteredElementCollector(doc, view.Id)
                 .OfClass(DB.FabricationPart)
                 .WhereElementIsNotElementType())
        for e in parts:
            try:
                if not is_fabrication_duct_part(e):
                    continue
                k = eid_int(e.Id)
                if k not in seen:
                    seen.add(k)
                    result.append(e)
            except Exception:
                pass
    except Exception:
        pass

    # Native MEP curves/fittings/accessories/equipment.
    for _cat_name in ['OST_DuctCurves', 'OST_DuctFitting', 'OST_DuctAccessory', 'OST_DuctTerminal', 'OST_MechanicalEquipment']:
        try:
            bic = getattr(DB.BuiltInCategory, _cat_name)
            items = (DB.FilteredElementCollector(doc, view.Id)
                     .OfCategory(bic)
                     .WhereElementIsNotElementType())
            for e in items:
                try:
                    k = eid_int(e.Id)
                    if k not in seen:
                        seen.add(k)
                        result.append(e)
                except Exception:
                    pass
        except Exception:
            pass

    return result


def _build_connector_spatial_index():
    global _CONNECTOR_SPATIAL_INDEX
    if _CONNECTOR_SPATIAL_INDEX is not None:
        return _CONNECTOR_SPATIAL_INDEX

    idx = {}
    for elem in _connector_index_elements():
        try:
            oid = eid_int(elem.Id)
        except Exception:
            continue
        for conn in physical_connectors(elem):
            try:
                p = conn.Origin
                key = _connector_index_key(p)
                if key is None:
                    continue
                idx.setdefault(key, []).append((oid, elem, conn, p))
            except Exception:
                pass

    _CONNECTOR_SPATIAL_INDEX = idx
    return idx


def _spatial_connector_matches(conn, owner_id):
    idx = _build_connector_spatial_index()
    if not idx:
        return []

    try:
        p = conn.Origin
        base = _connector_index_key(p)
    except Exception:
        return []
    if base is None:
        return []

    best_by_owner = {}
    bx, by, bz = base

    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for dz in (-1, 0, 1):
                for oid, elem, other_conn, op in idx.get((bx+dx, by+dy, bz+dz), []):
                    if oid == owner_id:
                        continue
                    try:
                        dist = p.DistanceTo(op)
                    except Exception:
                        continue
                    if dist > _CONNECTOR_MATCH_TOL_FT:
                        continue
                    if not _connector_sig_compatible(conn, other_conn):
                        continue
                    if not _connector_axis_compatible(conn, other_conn):
                        continue

                    # Lower score wins: exact physical coincidence first,
                    # then strongest opposing direction.
                    dot_pen = 0.0
                    try:
                        a = connector_axis(conn)
                        b = connector_axis(other_conn)
                        if a is not None and b is not None:
                            dot_pen = abs(1.0 + a.Normalize().DotProduct(b.Normalize()))
                    except Exception:
                        pass
                    score = dist * 1000.0 + dot_pen
                    old = best_by_owner.get(oid)
                    if old is None or score < old[0]:
                        best_by_owner[oid] = (score, elem)

    ordered = sorted(best_by_owner.items(), key=lambda kv: kv[1][0])
    return [data[1] for oid, data in ordered[:2]]


def _connector_other_owners(conn, owner_id):
    owners = []
    seen = set()

    # Revit-native connector ownership remains authoritative.
    for other in _strict_allrefs_other_owners(conn, owner_id):
        try:
            oid = eid_int(other.Id)
        except Exception:
            continue
        if oid in seen:
            continue
        seen.add(oid)
        owners.append(other)
        _CONNECTIVITY_STATS['allrefs_links'] = _CONNECTIVITY_STATS.get('allrefs_links', 0) + 1

    # Fabrication fallback is supplemental, never a proximity-only target rule.
    _CONNECTIVITY_STATS['fallback_queries'] = _CONNECTIVITY_STATS.get('fallback_queries', 0) + 1
    for other in _spatial_connector_matches(conn, owner_id):
        try:
            oid = eid_int(other.Id)
        except Exception:
            continue
        if oid in seen:
            continue
        seen.add(oid)
        owners.append(other)
        _CONNECTIVITY_STATS['fallback_links'] = _CONNECTIVITY_STATS.get('fallback_links', 0) + 1

    return owners


def _strict_inline_passthrough(elem):
    try:
        if is_supported_straight_duct(elem):
            return False
    except Exception:
        pass

    try:
        if isinstance(elem, DB.FabricationPart):
            try:
                if bool(elem.IsATap()) or bool(elem.IsAHanger()):
                    return False
            except Exception:
                pass
    except Exception:
        pass

    conns = physical_connectors(elem)
    if len(conns) != 2:
        return False

    c0, c1 = conns[0], conns[1]
    if not _same_connector_size(c0, c1):
        return False

    d0 = connector_axis(c0)
    d1 = connector_axis(c1)
    if d0 is None or d1 is None:
        return False

    try:
        if d0.DotProduct(d1) > -0.985:
            return False
        chord = (c1.Origin - c0.Origin).Normalize()
        if abs(d0.DotProduct(chord)) < 0.985:
            return False
        if abs(d1.DotProduct(chord)) < 0.985:
            return False
    except Exception:
        return False
    return True


def _strict_reached_straights(elem, end_conn, target_ids):
    start_id = eid_int(elem.Id)
    found = set()
    visited = set([start_id])
    frontier = []

    for other in _connector_other_owners(end_conn, start_id):
        frontier.append((other, 0))

    while frontier:
        owner, depth = frontier.pop(0)
        try:
            oid = eid_int(owner.Id)
        except Exception:
            continue
        if oid in visited:
            continue
        visited.add(oid)

        if oid in target_ids:
            found.add(oid)
            continue

        if depth >= MEASURE_MAX_INLINE_HOPS:
            continue
        if not _strict_inline_passthrough(owner):
            continue

        for c in physical_connectors(owner):
            for other in _connector_other_owners(c, oid):
                try:
                    nid = eid_int(other.Id)
                except Exception:
                    continue
                if nid not in visited:
                    frontier.append((other, depth + 1))
    return found


def _measure_record(elem, gdata):
    line = duct_centerline(elem)
    if line is None or gdata is None:
        return None
    try:
        grid = gdata[0]
        gid = eid_int(grid['element'].Id)
        axis = _canonical_axis_from_line(line)
        if axis is None:
            return None
        target, mode = _source_target_for_element(elem, grid)
        if target is None:
            return None
        perp = perp_xy(axis)
        offset = target.X * perp.X + target.Y * perp.Y
        mid = line_midpoint(line)
        d3 = line.Direction.Normalize()
        if (d3.X < -1e-9 or
            (abs(d3.X) <= 1e-9 and d3.Y < -1e-9) or
            (abs(d3.X) <= 1e-9 and abs(d3.Y) <= 1e-9 and d3.Z < 0.0)):
            d3 = DB.XYZ(-d3.X, -d3.Y, -d3.Z)
        return {
            'elem': elem,
            'gdata': gdata,
            'id': eid_int(elem.Id),
            'line': line,
            'grid_id': gid,
            'axis': axis,
            'dir3': d3,
            'mode': mode,
            'offset': float(offset),
            'z': float(mid.Z),
            'size': duct_size_signature(elem),
            'length': float(line.Length),
        }
    except Exception:
        return None


def _same_measurement(a, b):
    if a is None or b is None:
        return False
    if a['grid_id'] != b['grid_id']:
        return False
    if a['mode'] != b['mode']:
        return False
    if a['size'] != b['size']:
        return False
    try:
        if a['axis'].DotProduct(b['axis']) < MEASURE_AXIS_DOT:
            return False
        if abs(a['dir3'].DotProduct(b['dir3'])) < MEASURE_3D_DIR_DOT:
            return False
    except Exception:
        return False
    if abs(a['offset'] - b['offset']) > MEASURE_OFFSET_TOL_FT:
        return False
    if abs(a['z'] - b['z']) > MEASURE_Z_TOL_FT:
        return False
    return True


def collapse_same_run_dimensions(resolved):
    _RUN_CORRIDOR_LIMITS.clear()
    _RUN_MEMBER_RECORDS.clear()
    _RUN_MEMBER_IDS.clear()
    _TOPOLOGY_STATS.clear()
    _MEASURE_STATS.clear()

    if not resolved:
        _TOPOLOGY_STATS.update({
            'components': 0, 'inline_links': 0,
            'topology_break_links': 0, 'singleton_components': 0,
        })
        _MEASURE_STATS.update({
            'raw': 0, 'groups': 0, 'suppressed': 0,
            'strict_links': 0, 'unmergeable_links': 0,
        })
        return [], 0

    records = {}
    for elem, gdata in resolved:
        rec = _measure_record(elem, gdata)
        if rec is not None:
            records[rec['id']] = rec

    ids = set(records.keys())
    graph = dict((i, set()) for i in ids)
    strict_links = set()
    rejected_links = set()

    for did, rec in records.items():
        elem = rec['elem']
        for conn in physical_connectors(elem):
            for nid in _strict_reached_straights(elem, conn, ids):
                if nid == did or nid not in records:
                    continue
                edge = (min(did, nid), max(did, nid))
                if _same_measurement(rec, records[nid]):
                    graph[did].add(nid)
                    graph[nid].add(did)
                    strict_links.add(edge)
                else:
                    rejected_links.add(edge)

    components = []
    unseen = set(ids)
    while unseen:
        root = next(iter(unseen))
        unseen.remove(root)
        stack = [root]
        comp = []
        while stack:
            cur = stack.pop()
            comp.append(cur)
            for nxt in graph.get(cur, ()):
                if nxt in unseen:
                    unseen.remove(nxt)
                    stack.append(nxt)
        components.append(comp)

    kept = []
    suppressed = 0

    for comp in components:
        recs = [records[i] for i in comp if i in records]
        if not recs:
            continue

        best = max(recs, key=lambda r: r['length'])
        rep_id = best['id']
        kept.append((best['elem'], best['gdata']))
        _RUN_MEMBER_RECORDS[rep_id] = [(r['elem'], r['gdata']) for r in recs]
        _RUN_MEMBER_IDS[rep_id] = set(r['id'] for r in recs)
        suppressed += max(0, len(recs) - 1)

        try:
            axis = best['axis']
            intervals = []
            for r in recs:
                p0 = r['line'].GetEndPoint(0)
                p1 = r['line'].GetEndPoint(1)
                a0 = p0.X * axis.X + p0.Y * axis.Y
                a1 = p1.X * axis.X + p1.Y * axis.Y
                intervals.append((min(a0, a1), max(a0, a1)))
            group_lo = min(x[0] for x in intervals)
            group_hi = max(x[1] for x in intervals)
            bmid = line_midpoint(best['line'])
            rep_mid = bmid.X * axis.X + bmid.Y * axis.Y
            margin = paper_to_model(RUN_CORRIDOR_END_MARGIN_PAPER_IN)
            usable_lo = min(rep_mid, group_lo + margin)
            usable_hi = max(rep_mid, group_hi - margin)
            _RUN_CORRIDOR_LIMITS[rep_id] = (
                axis.X, axis.Y,
                max(0.0, rep_mid - usable_lo),
                max(0.0, usable_hi - rep_mid))
        except Exception:
            pass

    # Never silently lose a resolved straight if measurement extraction failed.
    represented = set()
    for ids_ in _RUN_MEMBER_IDS.values():
        represented.update(ids_)
    for elem, gdata in resolved:
        did = eid_int(elem.Id)
        if did not in represented:
            kept.append((elem, gdata))
            _RUN_MEMBER_RECORDS[did] = [(elem, gdata)]
            _RUN_MEMBER_IDS[did] = set([did])

    group_count = len(kept)
    singleton_count = sum(1 for ids_ in _RUN_MEMBER_IDS.values() if len(ids_) == 1)

    _TOPOLOGY_STATS.update({
        'components': group_count,
        'inline_links': len(strict_links),
        'topology_break_links': len(rejected_links),
        'singleton_components': singleton_count,
    })
    _MEASURE_STATS.update({
        'raw': len(resolved),
        'groups': group_count,
        'suppressed': suppressed,
        'strict_links': len(strict_links),
        'unmergeable_links': len(rejected_links),
    })
    return kept, suppressed

def _target_branch_priority(item):
    elem, gdata = item
    try:
        line = duct_centerline(elem)
        length = float(line.Length) if line is not None else 1e9
    except Exception:
        length = 1e9
    try:
        did = eid_int(elem.Id)
    except Exception:
        did = -1
    return (length, did)


def hard_collision_count(hits):
    return sum(int(hits.get(k, 0)) for k in HARD_COLLISION_KINDS)


def mep_collision_count(hits):
    return sum(int(hits.get(k, 0)) for k in MEP_COLLISION_KINDS)


def line_mep_collision_count(hits):
    return int(hits.get('_line_mep', mep_collision_count(hits)))


def text_mep_collision_count(hits):
    return int(hits.get('_text_mep', 0))


# -----------------------------------------------------------------------------
# DIRECT-SOURCE RECOVERY
# -----------------------------------------------------------------------------


def _record_dimension_attempt(source_id, phase, outcome):
    attempts = globals().setdefault('AUTODIM_ATTEMPTS', [])
    attempts.append({'source_id': int(source_id), 'phase': str(phase),
                     'status': str(outcome[0]), 'mode': outcome[1],
                     'grid_name': outcome[2], 'detail': str(outcome[3])})
    return outcome


def try_dimension_direct_recovery(elem, grid_info, existing_pairs,
                                  obstacle_grid, placement_stats, token='E'):
    """Retry actual duct references only; a point/connector cannot be a reference."""
    source_id = eid_int(elem.Id)
    try:
        line = duct_centerline(elem)
        gdata = nearest_parallel_grid(line, [grid_info]) if line is not None else None
        if gdata is None:
            outcome = ('no-grid', duct_shape(elem), grid_info['name'],
                       'No parallel grid for an actual duct reference. No helper datum created.')
        else:
            outcome = try_dimension_duct(elem, gdata, existing_pairs,
                                         obstacle_grid, placement_stats)
    except Exception as error:
        _record_dimension_attempt(source_id, 'direct:' + str(token),
                                  ('exception', None, grid_info['name'], str(error)))
        raise
    return _record_dimension_attempt(source_id, 'direct:' + str(token), outcome)


# -----------------------------------------------------------------------------
# DIMENSION PLACEMENT
# -----------------------------------------------------------------------------
def existing_grid_duct_pairs():
    pairs = set()
    try:
        dims = (DB.FilteredElementCollector(doc, view.Id)
                .OfClass(DB.Dimension)
                .WhereElementIsNotElementType())
    except Exception:
        return pairs

    for dim in dims:
        try:
            refs = dim.References
            if refs is None or refs.Size < 2:
                continue
            ids = []
            for r in refs:
                try:
                    rid = eid_int(r.ElementId)
                    if rid >= 0:
                        ids.append(rid)
                except Exception:
                    pass
            # Register every pair in the chain. This is conservative and prevents
            # the rough draft from stacking a duplicate on an existing location dim.
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    a = min(ids[i], ids[j])
                    b = max(ids[i], ids[j])
                    pairs.add((a, b))
        except Exception:
            continue
    return pairs


def target_plan_point(mid, perp, target_geom_point):
    # Project the selected duct edge/face point onto the dimension line through
    # the duct midpoint. Only the perpendicular coordinate matters.
    offset = dot_xy(vector_xy(mid, target_geom_point), perp)
    return DB.XYZ(mid.X + perp.X * offset,
                  mid.Y + perp.Y * offset,
                  view_plane_z())


def center_plan_point(mid):
    return DB.XYZ(mid.X, mid.Y, view_plane_z())


def grid_plan_point(mid, perp, grid_origin):
    offset = dot_xy(vector_xy(mid, grid_origin), perp)
    return DB.XYZ(mid.X + perp.X * offset,
                  mid.Y + perp.Y * offset,
                  view_plane_z())


def make_dimension_line(grid_pt, target_pt):
    v = vector_xy(grid_pt, target_pt)
    d = plan_vec(v)
    if d is None:
        return None
    p0 = DB.XYZ(grid_pt.X - d.X * DIM_LINE_EXTRA_FT,
                grid_pt.Y - d.Y * DIM_LINE_EXTRA_FT,
                grid_pt.Z)
    p1 = DB.XYZ(target_pt.X + d.X * DIM_LINE_EXTRA_FT,
                target_pt.Y + d.Y * DIM_LINE_EXTRA_FT,
                target_pt.Z)
    try:
        return DB.Line.CreateBound(p0, p1)
    except Exception:
        return None


def create_dim(grid_ref, duct_ref, dim_line):
    ra = DB.ReferenceArray()
    ra.Append(grid_ref)
    ra.Append(duct_ref)
    dim = doc.Create.NewDimension(view, dim_line, ra)
    if dim is not None:
        try:
            _CREATED_DIM_IDS.add(eid_int(dim.Id))
        except Exception:
            pass
    return dim


def try_dimension_duct(elem, grid_data, existing_pairs, obstacle_grid, placement_stats):
    """Return (status, mode, grid_name, detail).

    v0.8 treats a collapsed same-size collinear run as one drafting target while
    keeping every physical straight as a legal reference host. Candidate witness
    lines are generated on each member's real extent, and all same-run straights
    are ignored as self-obstacles. This avoids both false Heavy-MEP blocking and
    invalid attempts to use one bounded reference far beyond its own piece.
    """
    did = eid_int(elem.Id)
    grid = grid_data[0]
    grid_id = eid_int(grid['element'].Id)

    run_hosts = _RUN_MEMBER_RECORDS.get(did)
    if not run_hosts:
        run_hosts = [(elem, grid_data)]
    run_ids = set()
    for host_elem, host_gdata in run_hosts:
        try:
            run_ids.add(eid_int(host_elem.Id))
        except Exception:
            pass
    if not run_ids:
        run_ids.add(did)

    # If ANY member of the collapsed run already has a dimension to this grid,
    # the run is already located. This makes reruns stable even when v0.8 chose a
    # different physical member than the original representative.
    audited_existing = _audited_existing_direct_source_ids()
    for rid in run_ids:
        pair = (min(rid, grid_id), max(rid, grid_id))
        if pair in existing_pairs and rid in audited_existing:
            return ('duplicate', None, grid['name'],
                    'Existing dimension references this run and grid.')

    shape = duct_shape(elem)
    layouts = []
    host_reference_failures = 0

    for host_elem, host_gdata in run_hosts:
        try:
            host_id = eid_int(host_elem.Id)
            host_grid = host_gdata[0]
            _, _, _, axis, perp, mid = host_gdata
            duct_line = duct_centerline(host_elem)
            if duct_line is None:
                continue
            host_shape = duct_shape(host_elem)
            ref_records = []

            if host_shape == 'round':
                for ref, source in center_reference_candidates(host_elem, duct_line, host_grid):
                    ref_records.append((ref, source, None, 'round-center'))
            else:
                candidates = edge_candidates_toward_grid(host_elem, duct_line, host_grid)
                if not candidates:
                    host_reference_failures += 1
                    continue
                for _, ref, geom_pt, source in candidates[:10]:
                    ref_records.append((ref, source, geom_pt, 'edge'))

            if not ref_records:
                host_reference_failures += 1
                continue

            # Search only within this member's own real extent. Because every run
            # member is visited, the union of these candidates covers the run
            # without extending a bounded Revit reference beyond its host.
            for ref, source, geom_pt, mode in ref_records:
                for shift_model, shift_paper, outside_corridor in candidate_axis_shifts(duct_line, None):
                    base = DB.XYZ(mid.X + axis.X * shift_model,
                                  mid.Y + axis.Y * shift_model,
                                  mid.Z)
                    gpt = grid_plan_point(base, perp, host_grid['origin'])
                    if mode == 'round-center':
                        tpt = center_plan_point(base)
                    else:
                        tpt = target_plan_point(base, perp, geom_pt)
                    dim_line = make_dimension_line(gpt, tpt)
                    if dim_line is None:
                        continue
                    score, hits, text_rect = score_dimension_candidate(
                        obstacle_grid, gpt, tpt, did, shift_paper
                    )
                    if outside_corridor:
                        score += OUTSIDE_CORRIDOR_PENALTY
                    alternate_host = host_id != did
                    layouts.append((score, shift_paper, ref, source, mode, dim_line,
                                    gpt, tpt, text_rect, hits, alternate_host,
                                    host_id, host_grid['reference'], outside_corridor))
        except Exception:
            continue

    if not layouts:
        if shape != 'round' and host_reference_failures:
            return ('no-edge-ref', shape, grid['name'],
                    'No stable actual duct-edge reference. No substitute datum is used.')
        return ('failed', shape, grid['name'],
                'No usable layout for an actual duct reference.')

    placement_stats['candidates'] += len(layouts)
    annotation_safe = [x for x in layouts if hard_collision_count(x[9]) == 0]
    if not annotation_safe:
        placement_stats['blocked'] += 1
        placement_stats['blocked_annotation'] += 1
        return ('blocked', shape, grid['name'],
                'Actual duct-reference corridors intersect annotation.')

    # A dimension value must stay off MEP even when the witness line is allowed
    # to cross it. This is the main v0.9 coverage/readability split.
    text_mep_safe = [x for x in annotation_safe
                     if text_mep_collision_count(x[9]) <= MAX_TEXT_MEP_OVERLAPS]
    if not text_mep_safe:
        placement_stats['blocked'] += 1
        placement_stats['blocked_text_mep'] += 1
        placement_stats['blocked_mep'] += 1
        return ('blocked', shape, grid['name'],
                'Actual duct-reference text pockets remain on MEP.')

    fully_clean = [x for x in text_mep_safe if line_mep_collision_count(x[9]) == 0]
    if fully_clean:
        layouts = fully_clean
        placement_stats['clean_corridor'] += 1
    else:
        min_mep = min(line_mep_collision_count(x[9]) for x in text_mep_safe)
        if min_mep > MAX_MEP_LINE_CROSSINGS_RESCUE:
            placement_stats['blocked'] += 1
            placement_stats['blocked_mep'] += 1
            return ('blocked', shape, grid['name'],
                    'Actual duct-reference witness corridors remain too congested.')
        # Keep the minimum-crossing family, then let the weighted score choose
        # the cleanest background/shift option within that family.
        layouts = [x for x in text_mep_safe if line_mep_collision_count(x[9]) == min_mep]
        if min_mep <= PREFERRED_MEP_LINE_CROSSINGS:
            placement_stats['mep_relaxed'] += 1
        else:
            placement_stats['witness_rescue'] += 1

    layouts.sort(key=lambda x: _layout_candidate_rank(x[0], x[1], x[9]))
    if abs(layouts[0][1]) > 0.02:
        placement_stats['shifted'] += 1
    else:
        placement_stats['centered'] += 1

    last = None
    for rec in layouts[:DIM_MAX_LAYOUT_ATTEMPTS]:
        (score, shift_paper, ref, source, mode, dim_line, gpt, tpt,
         text_rect, hits, alternate_host, host_id, host_grid_ref,
         outside_corridor) = rec
        try:
            dim = create_dim(host_grid_ref, ref, dim_line)
            if dim is None:
                continue
            try:
                doc.Regenerate()
            except Exception as _regen_ex:
                try:
                    doc.Delete(dim.Id)
                except Exception:
                    pass
                last = 'Regenerate rejected direct reference: {0}'.format(_regen_ex)
                continue

            # v1.2: if planning found a clean value pocket, apply it before the
            # normal cleanup pass. If Revit refuses that position, abandon this
            # layout rather than keeping a dimension whose value lands on MEP.
            planned_text = hits.get('_planned_text_point')
            if hits.get('_text_pocket_moved') and planned_text is not None:
                try:
                    dim.TextPosition = planned_text
                    placement_stats['text_pocket_rescued'] += 1
                except Exception:
                    try:
                        doc.Delete(dim.Id)
                    except Exception:
                        pass
                    last = 'Revit rejected planned clean text pocket.'
                    continue

            # Mark every member pair as satisfied only after the planned value
            # position is accepted. One visible locating dimension is intended
            # for the whole collapsed run.
            for rid in run_ids:
                existing_pairs.add((min(rid, grid_id), max(rid, grid_id)))

            moved_text, adjusted_text_rect = adjust_dimension_text(
                dim, obstacle_grid, gpt, tpt, did
            )
            if moved_text:
                placement_stats['text_nudged'] += 1
            doc.Regenerate()
            if not _created_dimension_text_is_clear(dim, obstacle_grid):
                doc.Delete(dim.Id)
                last = 'Revit did not retain a text position clear of all MEP/annotation.'
                continue
            if alternate_host:
                placement_stats['run_extended_used'] += 1
                placement_stats['alternate_run_host_used'] += 1
            if outside_corridor:
                placement_stats['outside_corridor_used'] += 1
            reserve_created_dimension(obstacle_grid, dim, gpt, tpt,
                                      adjusted_text_rect or text_rect)
            try:
                _dimid = eid_int(dim.Id)
                _CREATED_DIM_SOURCE[_dimid] = did
                _CREATED_DIM_MODE[_dimid] = mode
                _CREATED_DIM_GRID[_dimid] = int(grid_id)
            except Exception:
                pass
            placement_stats['best_score_sum'] += score
            if hits.get('dimension_line', 0) + hits.get('dimension_text', 0) > 0:
                placement_stats['dim_hits'] += 1
            if hits.get('tag', 0) + hits.get('annotation', 0) > 0:
                placement_stats['annotation_hits'] += 1
            if hits.get('duct', 0) + hits.get('fitting', 0) > 0:
                placement_stats['mep_hits'] += 1
            return ('created', mode, grid['name'],
                    '{0}; host {1}; shift {2:.2f}" paper; score {3:.0f}'.format(
                        source, host_id, shift_paper, score))
        except Exception as ex:
            last = '{0} [grid-ref={1}; duct-ref={2}; source={3}; host={4}]'.format(
                ex, reference_type_name(host_grid_ref), reference_type_name(ref), source, host_id)
            continue

    return ('failed', shape, grid['name'],
            last or 'Revit rejected the actual duct references.')


# -----------------------------------------------------------------------------
# v1.6 BRANCH-COVERAGE AUDIT / RECOVERY
# -----------------------------------------------------------------------------
# Straight-only collection misses an important drafting case: a branch can leave
# a takeoff/tee and immediately enter an elbow before any straight exists. Also,
# a short straight just after that fitting chain can be omitted from a user's
# preselection. We inventory fabrication branch events inside the selected plan
# scope, automatically add the first downstream straight on each leg, and create
# a conservative ROUND center anchor for a takeoff leg that immediately enters a
# fitting instead of a straight.


def _union_rect(a, b):
    if a is None:
        return b
    if b is None:
        return a
    return (min(a[0], b[0]), min(a[1], b[1]),
            max(a[2], b[2]), max(a[3], b[3]))


def _selected_scope_rect(elements):
    r = None
    for e in elements:
        r = _union_rect(r, element_rect(e))
    if r is None:
        return None
    return rect_expand(r, BRANCH_SCOPE_MARGIN_FT)


def _rect_contains_center(scope_rect, elem):
    if scope_rect is None:
        return True
    r = element_rect(elem)
    if r is None:
        return False
    cx = 0.5 * (r[0] + r[2])
    cy = 0.5 * (r[1] + r[3])
    return (scope_rect[0] <= cx <= scope_rect[2] and
            scope_rect[1] <= cy <= scope_rect[3])


def _visible_fabrication_parts_in_scope(scope_rect):
    out = []
    try:
        col = (DB.FilteredElementCollector(doc, view.Id)
               .OfCategory(DB.BuiltInCategory.OST_FabricationDuctwork)
               .WhereElementIsNotElementType())
    except Exception:
        col = (DB.FilteredElementCollector(doc)
               .OfCategory(DB.BuiltInCategory.OST_FabricationDuctwork)
               .WhereElementIsNotElementType())
    for e in col:
        try:
            if is_fabrication_duct_part(e) and _rect_contains_center(scope_rect, e):
                out.append(e)
        except Exception:
            pass
    return out


def _is_branch_event_part(elem):
    if not is_fabrication_duct_part(elem):
        return False
    try:
        if bool(elem.IsATap()):
            return True
    except Exception:
        pass
    try:
        return len(physical_connectors(elem)) >= 3
    except Exception:
        return False


def _owner_straight_axis(owner):
    if owner is None or not is_supported_straight_duct(owner):
        return None
    line = duct_centerline(owner)
    if line is None:
        return None
    return plan_vec(line.Direction)


def _branch_connector_candidates(branch_part):
    """Return likely branch-side connectors of a tap/tee/cross.

    For a 3+ connector fitting, the most-opposed pair is treated as the trunk;
    remaining connectors are branch legs. For a tap, a connector attached to a
    straight whose run axis is nearly perpendicular to the connector axis is the
    host/trunk side; other connected connectors are branch-side candidates.
    """
    conns = physical_connectors(branch_part)
    if not conns:
        return []

    try:
        is_tap = bool(branch_part.IsATap())
    except Exception:
        is_tap = False

    if len(conns) >= 3 and not is_tap:
        axes = []
        for i, c in enumerate(conns):
            a = connector_axis(c)
            pa = plan_vec(a) if a is not None else None
            axes.append((i, pa))
        best_pair = None
        best_dot = 2.0
        for i, ai in axes:
            if ai is None:
                continue
            for j, aj in axes:
                if j <= i or aj is None:
                    continue
                try:
                    d = dot_xy(ai, aj)
                except Exception:
                    continue
                if d < best_dot:
                    best_dot = d
                    best_pair = (i, j)
        if best_pair is not None:
            return [c for i, c in enumerate(conns) if i not in best_pair]

    result = []
    for c in conns:
        ca = connector_axis(c)
        pa = plan_vec(ca) if ca is not None else None
        if pa is None:
            continue
        owners = _connector_other_owners(c, eid_int(branch_part.Id))
        if not owners:
            continue
        host_side = False
        for other in owners:
            oa = _owner_straight_axis(other)
            if oa is None:
                continue
            try:
                # Tap host straight is usually transverse to the tap connector.
                if abs(dot_xy(pa, oa)) < 0.30:
                    host_side = True
                    break
            except Exception:
                pass
        if not host_side:
            result.append(c)
    return result


def _trace_first_straights_from_connector(branch_part, start_conn):
    """Traverse fittings after a branch event until the first straight(s).

    This catches takeoff -> elbow -> straight and tee -> reducer -> straight
    arrangements that a straight-only selection can otherwise miss.
    """
    start_id = eid_int(branch_part.Id)
    found = {}
    visited = set([start_id])
    frontier = []
    for other in _connector_other_owners(start_conn, start_id):
        frontier.append((other, 0))

    while frontier:
        owner, depth = frontier.pop(0)
        try:
            oid = eid_int(owner.Id)
        except Exception:
            continue
        if oid in visited:
            continue
        visited.add(oid)

        if is_supported_straight_duct(owner):
            if is_plan_run(owner):
                found[oid] = owner
            continue

        if depth >= BRANCH_SCAN_MAX_HOPS:
            continue
        if not is_fabrication_duct_part(owner):
            continue
        # Do not walk through a second branch event; it starts a new branch.
        if oid != start_id and _is_branch_event_part(owner):
            continue

        for c in physical_connectors(owner):
            for other in _connector_other_owners(c, oid):
                try:
                    if eid_int(other.Id) not in visited:
                        frontier.append((other, depth + 1))
                except Exception:
                    pass

    return list(found.values())


def _branch_connector_candidates(branch_part):
    conns = physical_connectors(branch_part)
    if not conns:
        return []
    try:
        is_tap = bool(branch_part.IsATap())
    except Exception:
        is_tap = False

    # True tee/cross: most-opposed pair is the through/trunk pair.
    if len(conns) >= 3 and not is_tap:
        axes = []
        for i, c in enumerate(conns):
            a = connector_axis(c)
            axes.append((i, plan_vec(a) if a is not None else None))
        best_pair = None
        best_dot = 2.0
        for i, ai in axes:
            if ai is None:
                continue
            for j, aj in axes:
                if j <= i or aj is None:
                    continue
                try:
                    d = dot_xy(ai, aj)
                except Exception:
                    continue
                if d < best_dot:
                    best_dot = d
                    best_pair = (i, j)
        if best_pair is not None and best_dot < -0.60:
            return [c for i, c in enumerate(conns) if i not in best_pair]

    # Tap / ambiguous fabrication branch. First prove connectors that are on
    # the host side: an immediate straight whose axis is transverse to the
    # connector. Everything else connected is a branch candidate. This keeps
    # takeoff -> elbow -> straight legs, which the previous alignment test could
    # misclassify as host-side after the elbow changed direction.
    host_ids = set()
    connected_ids = set()
    branch_proof_ids = set()
    immediate_straight_ids = set()
    for i, c in enumerate(conns):
        ca = connector_axis(c)
        pa = plan_vec(ca) if ca is not None else None
        owners = _connector_other_owners(c, eid_int(branch_part.Id))
        if owners:
            connected_ids.add(i)
        for other in owners:
            oa = _owner_straight_axis(other)
            if oa is None or pa is None:
                continue
            immediate_straight_ids.add(i)
            try:
                ad = abs(dot_xy(pa, oa))
                if ad < 0.30:
                    host_ids.add(i)
                elif ad > 0.70:
                    branch_proof_ids.add(i)
            except Exception:
                pass

    explicit = [c for i, c in enumerate(conns)
                if i in branch_proof_ids and i not in host_ids]
    if explicit:
        return explicit

    if host_ids:
        result = [c for i, c in enumerate(conns)
                  if i in connected_ids and i not in host_ids]
        if result:
            return result

    # If one side is a direct straight and the other enters a fitting chain,
    # the fitting-chain side is the branch in the common tap condition.
    if len(conns) == 2 and len(immediate_straight_ids) == 1:
        idx = 0 if 0 not in immediate_straight_ids else 1
        if idx in connected_ids:
            return [conns[idx]]

    # Last-resort classification: prefer a connector whose first reachable
    # straight remains aligned to its connector. Do not return every connector;
    # that would create a false branch dimension on the trunk side.
    best_i = None
    best_score = -1.0
    for i, c in enumerate(conns):
        if i not in connected_ids:
            continue
        ca = connector_axis(c)
        pa = plan_vec(ca) if ca is not None else None
        if pa is None:
            continue
        score = 0.0
        try:
            ds = _trace_first_straights_from_connector(branch_part, c)
        except Exception:
            ds = []
        for s in ds:
            try:
                ln = duct_centerline(s)
                sa = plan_vec(ln.Direction) if ln is not None else None
                if sa is not None:
                    score = max(score, abs(dot_xy(pa, sa)))
            except Exception:
                pass
        if score > best_score:
            best_score = score
            best_i = i
    if best_i is not None:
        return [conns[best_i]]
    return []


def _immediate_branch_has_straight(branch_part, conn):
    for other in _connector_other_owners(conn, eid_int(branch_part.Id)):
        try:
            if is_supported_straight_duct(other) and is_plan_run(other):
                return True
        except Exception:
            pass
    return False


def _branch_axis_has_direct_locating_straight(branch_part, start_conn):
    """True only when the branch axis itself reaches an aligned straight.

    Traversal is intentionally conservative:
      branch connector -> straight
      branch connector -> verified inline coupling(s) -> straight

    Any elbow, tee/wye, tap, transition/size change, offset, or other non-inline
    fitting means the connector axis needs its OWN locating dimension.
    """
    start_id = eid_int(branch_part.Id)
    ca = connector_axis(start_conn)
    branch_axis = plan_vec(ca) if ca is not None else None
    if branch_axis is None:
        return False

    visited = set([start_id])
    frontier = []
    for other in _connector_other_owners(start_conn, start_id):
        frontier.append((other, 0))

    while frontier:
        owner, depth = frontier.pop(0)
        try:
            oid = eid_int(owner.Id)
        except Exception:
            continue
        if oid in visited:
            continue
        visited.add(oid)

        try:
            if is_supported_straight_duct(owner) and is_plan_run(owner):
                line = duct_centerline(owner)
                sa = plan_vec(line.Direction) if line is not None else None
                if sa is not None and abs(dot_xy(branch_axis, sa)) >= 0.985:
                    return True
                # First real straight is turned from the branch axis.
                return False
        except Exception:
            pass

        if depth >= 3:
            continue
        try:
            if not is_fabrication_duct_part(owner):
                return False
        except Exception:
            return False

        # Do not walk through another branch event.
        try:
            if _is_branch_event_part(owner):
                return False
        except Exception:
            pass

        # Only straight-through same-section couplings are transparent.
        if not _strict_inline_passthrough(owner):
            return False

        for c in physical_connectors(owner):
            for other in _connector_other_owners(c, oid):
                try:
                    nid = eid_int(other.Id)
                except Exception:
                    continue
                if nid not in visited:
                    frontier.append((other, depth + 1))

    return False


def augment_ducts_from_branch_events(ducts):
    global _BRANCH_DOWNSTREAM_IDS, _BRANCH_LEG_RECORDS
    _BRANCH_DOWNSTREAM_IDS.clear()
    _BRANCH_LEG_RECORDS[:] = []
    """Return (augmented ducts, direct round anchors, stats)."""
    scope = _selected_scope_rect(ducts)
    parts = _visible_fabrication_parts_in_scope(scope)
    branch_parts = [p for p in parts if _is_branch_event_part(p)]

    by_id = {}
    for d in ducts:
        try:
            by_id[eid_int(d.Id)] = d
        except Exception:
            pass

    anchors = []
    stats = {
        'events': len(branch_parts),
        'legs': 0,
        'auto_added_straights': 0,
        'mapped_straight_legs': 0,
        'priority_targets': 0,
        'events_no_branch_connector': 0,
        'direct_round_candidates': 0,
        'no_straight_legs': 0,
        'direct_axis_legs': 0,
        'connector_target_legs': 0,
        'connector_target_with_downstream': 0,
    }
    anchor_seen = set()

    for bp in branch_parts:
        _branch_candidates = _branch_connector_candidates(bp)
        if not _branch_candidates:
            stats['events_no_branch_connector'] += 1
        for conn in _branch_candidates:
            stats['legs'] += 1
            downstream = _trace_first_straights_from_connector(bp, conn)

            # Drafting intent is NOT the same as topology reachability.
            # A downstream straight after an elbow does not locate the original
            # takeoff axis. Only a direct/aligned straight (possibly through a
            # verified inline coupling) can satisfy this branch connector.
            _direct_axis_located = _branch_axis_has_direct_locating_straight(bp, conn)
            _requires_connector_target = not _direct_axis_located
            if _direct_axis_located:
                stats['direct_axis_legs'] += 1
            else:
                stats['connector_target_legs'] += 1
                if downstream:
                    stats['connector_target_with_downstream'] += 1

            if downstream:
                stats['mapped_straight_legs'] += 1
                for s in downstream:
                    sid = eid_int(s.Id)
                    _BRANCH_DOWNSTREAM_IDS.add(sid)
                    if sid not in by_id:
                        by_id[sid] = s
                        stats['auto_added_straights'] += 1
            else:
                stats['no_straight_legs'] += 1

            # Preserve the branch INTENT even when no straight exists. The
            # post-commit coverage audit uses this record to verify that each
            # takeoff/tee/wye leg actually owns a surviving nearby dimension.
            try:
                _p = conn.Origin
                _ca = connector_axis(conn)
                _pa = plan_vec(_ca) if _ca is not None else None
                _shape = str(conn.Shape).lower()
                _leg_key = '{0}_{1}_{2}'.format(
                    eid_int(bp.Id), int(round(_p.X * 100.0)), int(round(_p.Y * 100.0)))
                _cs = None
                _bx = None
                _by = None
                _cw = None
                _ch = None
                try:
                    _cs = conn.CoordinateSystem
                    if _cs is not None:
                        _bx = plan_vec(_cs.BasisX)
                        _by = plan_vec(_cs.BasisY)
                except Exception:
                    pass
                try:
                    _cw = float(conn.Width)
                    _ch = float(conn.Height)
                except Exception:
                    pass
                _BRANCH_LEG_RECORDS.append({
                    'key': _leg_key,
                    'branch_id': eid_int(bp.Id),
                    'point': DB.XYZ(_p.X, _p.Y, view_plane_z()),
                    'axis': _pa,
                    'shape': _shape,
                    'width': _cw,
                    'height': _ch,
                    'basis_x': _bx,
                    'basis_y': _by,
                    'downstream_ids': [eid_int(_s.Id) for _s in downstream],
                    'rep_ids': [],
                    'direct_axis_located': bool(_direct_axis_located),
                    'requires_connector_target': bool(_requires_connector_target),
                })
            except Exception:
                pass

            # A direct fitting immediately after the branch event means there is
            # no straight host on the actual takeoff leg. For ROUND legs, preserve
            # the connector center as a conservative direct locating anchor.
            if _immediate_branch_has_straight(bp, conn):
                continue

            # If the fitting chain eventually reaches a straight that is still
            # parallel to the takeoff connector, that straight already locates
            # this branch axis. A direct fitting anchor is only needed when the
            # branch turns before its first straight (takeoff -> elbow -> straight)
            # or when no downstream straight exists at all.
            ca0 = connector_axis(conn)
            pa0 = plan_vec(ca0) if ca0 is not None else None
            same_axis_downstream = False
            if pa0 is not None:
                for ds in downstream:
                    try:
                        dl = duct_centerline(ds)
                        da = plan_vec(dl.Direction) if dl is not None else None
                        if da is not None and abs(dot_xy(pa0, da)) >= 0.985:
                            same_axis_downstream = True
                            break
                    except Exception:
                        pass
            if same_axis_downstream:
                continue

            try:
                shape = str(conn.Shape).lower()
            except Exception:
                shape = ''
            if 'round' not in shape:
                continue
            ca = connector_axis(conn)
            axis = plan_vec(ca) if ca is not None else None
            if axis is None:
                continue
            try:
                p = conn.Origin
                key = (eid_int(bp.Id), round(p.X, 4), round(p.Y, 4),
                       round(axis.X, 3), round(axis.Y, 3))
            except Exception:
                continue
            if key in anchor_seen:
                continue
            anchor_seen.add(key)
            anchors.append({
                'element': bp,
                'connector': conn,
                'point': p,
                'axis': axis,
            })
            stats['direct_round_candidates'] += 1

    return list(by_id.values()), anchors, stats


def _anchor_synthetic_line(anchor):
    p = anchor['point']
    a = anchor['axis']
    try:
        return DB.Line.CreateBound(
            DB.XYZ(p.X - a.X * 0.5, p.Y - a.Y * 0.5, p.Z),
            DB.XYZ(p.X + a.X * 0.5, p.Y + a.Y * 0.5, p.Z)
        )
    except Exception:
        return None


def _round_anchor_reference_candidates(anchor, grid_info):
    """Only accept real LINEAR fitting references nearly on the connector center."""
    elem = anchor['element']
    line = _anchor_synthetic_line(anchor)
    if line is None:
        return []
    cands = _fab_reference_candidates(elem, line)
    good = [c for c in cands
            if c['kind'] == 'curve'
            and c['relation'] == 'parallel-run'
            and c['abs_offset'] <= BRANCH_CENTER_MAX_OFFSET_FT]
    good.sort(key=lambda c: (c['abs_offset'],
                             _fab_candidate_grid_distance(c, grid_info),
                             c['source']))
    return good[:6]


def try_dimension_round_branch_anchor(anchor, grids, existing_pairs,
                                      obstacle_grid, placement_stats):
    outcome = ('unsupported', 'round-center', None,
               'A round connector coordinate is not an actual duct center reference. '
               'No substitute datum is created.')
    return _record_dimension_attempt(eid_int(anchor['element'].Id),
                                     'direct-round-branch', outcome)


# -----------------------------------------------------------------------------
# POST-COMMIT SURVIVAL + BRANCH COVERAGE AUDIT
# -----------------------------------------------------------------------------

def _dimension_reference_element_ids(dim):
    ids = []
    try:
        refs = dim.References
        count = int(refs.Size)
        for i in range(count):
            try:
                r = refs.get_Item(i)
                if r is not None and r.ElementId is not None:
                    ids.append(eid_int(r.ElementId))
            except Exception:
                pass
    except Exception:
        pass
    return ids


def _expected_target_to_grid_value(grid_elem, target_point):
    try:
        crv = grid_elem.Curve
        if not isinstance(crv, DB.Line):
            return None
        axis = plan_vec(crv.Direction)
        if axis is None:
            return None
        perp = perp_xy(axis)
        return abs(dot_xy(vector_xy(target_point, crv.Origin), perp))
    except Exception:
        return None


def _dimension_direction_is_grid_normal(dim, grid_elem):
    try:
        crv = dim.Curve
        gcrv = grid_elem.Curve
        if not isinstance(crv, DB.Line) or not isinstance(gcrv, DB.Line):
            return False
        dd = plan_vec(crv.Direction)
        gd = plan_vec(gcrv.Direction)
        if dd is None or gd is None:
            return False
        # A linear locating dimension should run essentially normal to its grid.
        return abs(dot_xy(dd, gd)) <= CERT_DIM_GRID_PERP_DOT_MAX
    except Exception:
        return False


def _single_dimension_references(dim):
    """Return exactly two references for an unsegmented dimension, or fail closed."""
    try:
        if int(dim.NumberOfSegments) != 0:
            return []
        refs = dim.References
        if refs is None or int(refs.Size) != 2:
            return []
        return [refs.get_Item(0), refs.get_Item(1)]
    except Exception:
        return []


def _certify_dimension_against_target(dim, grid_id, target):
    """Check actual single-dimension geometry without assuming its ownership."""
    if dim is None:
        return (False, 'missing-dimension', None, None)
    if grid_id is None or target is None:
        return (False, 'metadata-missing', None, None)
    refs = _single_dimension_references(dim)
    if not refs:
        return (False, 'direction-mismatch', None, None)
    try:
        grid = doc.GetElement(DB.ElementId(Int64(int(int(grid_id)))))
    except Exception:
        grid = None
    if grid is None:
        return (False, 'metadata-missing', None, None)
    if int(grid_id) not in _dimension_reference_element_ids(dim):
        return (False, 'grid-reference-mismatch', None, None)
    expected = _expected_target_to_grid_value(grid, target)
    if expected is None:
        return (False, 'metadata-missing', None, None)
    try:
        actual = abs(float(dim.Value))
        if math.isnan(actual) or math.isinf(actual):
            actual = None
    except Exception:
        actual = None
    if actual is None:
        return (False, 'metadata-missing', expected, None)
    if abs(actual - expected) > CERT_VALUE_TOL_FT:
        return (False, 'value-mismatch', expected, actual)
    if not _dimension_direction_is_grid_normal(dim, grid):
        return (False, 'direction-mismatch', expected, actual)
    return (True, 'certified', expected, actual)


def _certify_created_dimension(dimid):
    """Certify one surviving new dimension against recorded intended geometry."""
    try:
        dimid = int(dimid)
        dim = doc.GetElement(DB.ElementId(Int64(int(dimid))))
    except Exception:
        dim = None
    outcome = _certify_dimension_against_target(
        dim, _CREATED_DIM_GRID.get(dimid), _CREATED_DIM_TARGETS.get(dimid))
    if not outcome[0]:
        return outcome
    source_id = _CREATED_DIM_SOURCE.get(dimid)
    allowed = set(_RUN_MEMBER_IDS.get(source_id, set([source_id])))
    owners = set(_dimension_reference_element_ids(dim)) - set([_CREATED_DIM_GRID.get(dimid)])
    if not owners or not owners.issubset(allowed):
        return (False, 'source-reference-mismatch', outcome[2], outcome[3])
    try:
        if dim.ValueOverride:
            return (False, 'display-override', outcome[2], outcome[3])
    except Exception:
        return (False, 'metadata-missing', outcome[2], outcome[3])
    return outcome


def _stable_reference_key(ref):
    try:
        key = ref.ConvertToStableRepresentation(doc)
        return str(key) if key else None
    except Exception:
        return None


def _expected_run_target(elem, grid_info):
    """Source geometry used to prove that a dimension locates this run."""
    key = (eid_int(elem.Id), eid_int(grid_info['element'].Id))
    if key in _RUN_EXPECTED_TARGET_CACHE:
        return _RUN_EXPECTED_TARGET_CACHE[key]
    result = (None, None)
    try:
        line = duct_centerline(elem)
        if line is not None:
            mid = line_midpoint(line)
            if duct_shape(elem) == 'round':
                result = (center_plan_point(mid), 'round-center')
            else:
                candidates = edge_candidates_toward_grid(elem, line, grid_info)
                if candidates:
                    normal = perp_xy(grid_info['axis'])
                    result = (target_plan_point(mid, normal, candidates[0][2]), 'edge')
                else:
                    point, mode = _source_target_for_element(elem, grid_info)
                    if point is not None and mode == 'edge':
                        result = (point, 'edge')
    except Exception:
        pass
    _RUN_EXPECTED_TARGET_CACHE[key] = result
    return result


def _record_matches_run_target(target, mode, grid_id, elem, gdata):
    """Do not award run coverage for a source ID or a different axis alone."""
    if target is None or grid_id is None:
        return False
    try:
        if gdata is not None:
            grid_info = gdata[0]
            if int(grid_id) != eid_int(grid_info['element'].Id):
                return False
        else:
            grid = doc.GetElement(DB.ElementId(Int64(int(int(grid_id)))))
            curve = grid.Curve
            if not isinstance(curve, DB.Line):
                return False
            axis = plan_vec(curve.Direction)
            if axis is None:
                return False
            grid_info = {'element': grid, 'axis': axis, 'origin': curve.Origin}
        expected, expected_mode = _expected_run_target(elem, grid_info)
        if expected is None:
            return False
        is_edge = 'edge' in str(mode or '')
        is_center = 'center' in str(mode or '')
        if ((expected_mode == 'edge' and not is_edge) or
                (expected_mode == 'round-center' and not is_center)):
            return False
        normal = perp_xy(grid_info['axis'])
        error = abs(dot_xy(vector_xy(expected, target), normal))
        return error <= CERT_VALUE_TOL_FT
    except Exception:
        return False


def _existing_direct_record_is_valid(record):
    try:
        dim = doc.GetElement(DB.ElementId(Int64(int(int(record['dim_id'])))))
        refs = _single_dimension_references(dim)
        keys = set(_stable_reference_key(r) for r in refs)
        if None in keys or keys != set(record['reference_keys']):
            return False
        # A displayed override is not proof of a usable measured dimension.
        if dim.ValueOverride:
            return False
        return _certify_dimension_against_target(
            dim, record['grid_id'], record['target'])[0]
    except Exception:
        return False


def _audited_existing_direct_source_ids():
    return set(int(record['source_id'])
               for record in _EXISTING_DIRECT_DIM_RECORDS.values()
               if _existing_direct_record_is_valid(record))


def _audit_existing_direct_dimensions(resolved):
    """Prove current direct refs; unknown helper planes cannot satisfy targets.

    Only a two-reference, unsegmented dimension to the currently assigned grid
    can qualify. Its model reference must exactly match a current near-edge or
    round-center candidate, and its actual value must match source geometry.
    """
    hosts = {}
    for elem, gdata in resolved:
        rep = eid_int(elem.Id)
        for host, host_gdata in _RUN_MEMBER_RECORDS.get(rep, [(elem, gdata)]):
            if host_gdata is not None:
                hosts[eid_int(host.Id)] = (host, host_gdata)
    try:
        dims = (DB.FilteredElementCollector(doc, view.Id)
                .OfClass(DB.Dimension).WhereElementIsNotElementType())
    except Exception:
        return {}
    records = {}
    for dim in dims:
        refs = _single_dimension_references(dim)
        if not refs:
            continue
        try:
            ids = [eid_int(r.ElementId) for r in refs]
            source_ids = [i for i in ids if i in hosts]
            if len(source_ids) != 1:
                continue
            source = source_ids[0]
            elem, gdata = hosts[source]
            grid_info = gdata[0]
            grid_id = eid_int(grid_info['element'].Id)
            if grid_id not in ids:
                continue
            model_ref = refs[ids.index(source)]
            grid_ref = refs[ids.index(grid_id)]
            model_key = _stable_reference_key(model_ref)
            grid_key = _stable_reference_key(grid_ref)
            if (model_key is None or grid_key is None or
                    grid_key != _stable_reference_key(grid_info['reference'])):
                continue
            line = duct_centerline(elem)
            if line is None:
                continue
            mid = line_midpoint(line)
            normal = perp_xy(grid_info['axis'])
            mode = 'round-center' if duct_shape(elem) == 'round' else 'edge'
            if mode == 'round-center':
                candidates = [(ref, center_plan_point(mid))
                              for ref, source_name in center_reference_candidates(
                                  elem, line, grid_info)]
            else:
                candidates = [(ref, target_plan_point(mid, normal, point))
                              for distance, ref, point, source_name in
                              edge_candidates_toward_grid(elem, line, grid_info)]
            for ref, target in candidates:
                if _stable_reference_key(ref) != model_key:
                    continue
                if not _record_matches_run_target(target, mode, grid_id, elem, gdata):
                    continue
                record = {'dim_id': eid_int(dim.Id), 'source_id': source,
                          'grid_id': grid_id, 'target': target, 'mode': mode,
                          'reference_keys': (grid_key, model_key)}
                if _existing_direct_record_is_valid(record):
                    records[record['dim_id']] = record
                    break
        except Exception:
            continue
    return records


def _certified_branch_keys(certified_ids):
    out = set(str(record['branch_key']) for record in _EXISTING_DIRECT_DIM_RECORDS.values()
              if record.get('branch_key') is not None and _existing_direct_record_is_valid(record))
    out.update(str(key) for key, record in globals().get('_BRANCH_RUN_REUSE', {}).items()
               if _shared_run_branch_record_is_valid(record))
    for dimid in certified_ids:
        try:
            key = _CREATED_DIM_BRANCH_KEY.get(int(dimid))
            if key is not None:
                out.add(str(key))
        except Exception:
            pass
    return out


def _certification_snapshot(resolved, surviving_ids, pre_no_grid=None):
    """Certify dimensions and convert them into actual covered drafting targets."""
    certified = set()
    rejected = []
    target_items = list(resolved) + [(elem, None) for elem in (pre_no_grid or [])]
    target_by_rep = dict((eid_int(elem.Id), (elem, gdata)) for elem, gdata in target_items)
    member_to_rep = _member_to_rep_map(resolved)

    for dimid in sorted(set(int(x) for x in surviving_ids)):
        ok, reason, expected, actual = _certify_created_dimension(dimid)
        if ok and _CREATED_DIM_BRANCH_KEY.get(dimid) is None:
            # A numerically valid dimension can still locate the wrong source
            # coordinate. Remove only this run's obsolete straight dimensions;
            # independent branch obligations and existing user dims stay intact.
            source = _CREATED_DIM_SOURCE.get(dimid)
            rep = member_to_rep.get(source, source)
            item = target_by_rep.get(rep)
            if item is None or not _record_matches_run_target(
                    _CREATED_DIM_TARGETS.get(dimid), _CREATED_DIM_MODE.get(dimid),
                    _CREATED_DIM_GRID.get(dimid), item[0], item[1]):
                ok, reason = False, 'source-target-mismatch'
        if ok:
            certified.add(dimid)
        else:
            rejected.append((dimid, reason, expected, actual))

    covered_runs = _covered_run_rep_ids(resolved, certified, pre_no_grid)
    branch_keys = _certified_branch_keys(certified)

    required_branch_legs = [
        leg for leg in _BRANCH_LEG_RECORDS
        if bool(leg.get('requires_connector_target', False))
    ]
    missing_branch_legs = [
        leg for leg in required_branch_legs
        if str(leg.get('key')) not in branch_keys
    ]

    missing_run_items = []
    missing_run_ids = []
    for elem, gdata in target_items:
        try:
            rid = eid_int(elem.Id)
        except Exception:
            continue
        if rid not in covered_runs:
            missing_run_items.append((elem, gdata))
            missing_run_ids.append(rid)

    return {
        'certified_ids': certified,
        'rejected': rejected,
        'covered_runs': covered_runs,
        'branch_keys': branch_keys,
        'missing_run_items': missing_run_items,
        'missing_run_ids': missing_run_ids,
        'missing_branch_legs': missing_branch_legs,
        'required_run_count': len(target_items),
        'required_branch_count': len(required_branch_legs),
        'required_total': len(target_items) + len(required_branch_legs),
        'certified_total': len(covered_runs) + (len(required_branch_legs) - len(missing_branch_legs)),
    }


def _record_certification_rejections(rejected):
    del _CERT_REJECTED_DETAILS[:]
    reason_map = {
        'grid-reference-mismatch': 'grid_ref_mismatch',
        'value-mismatch': 'value_mismatch',
        'direction-mismatch': 'direction_mismatch',
        'source-target-mismatch': 'source_target_mismatch',
        'metadata-missing': 'metadata_missing',
        'missing-dimension': 'missing_dimension',
    }
    for dimid, reason, expected, actual in rejected:
        key = reason_map.get(reason)
        if key is not None:
            _CERTIFICATION_STATS[key] = _CERTIFICATION_STATS.get(key, 0) + 1
        _CERT_REJECTED_DETAILS.append((dimid, reason, expected, actual))


def _delete_created_dimensions(dimids, transaction_name):
    ids = [int(x) for x in dimids]
    if not ids:
        return 0
    deleted = 0
    tx = DB.Transaction(doc, transaction_name)
    try:
        tx.Start()
        for did in ids:
            try:
                if doc.GetElement(DB.ElementId(Int64(int(did)))) is not None:
                    doc.Delete(DB.ElementId(Int64(int(did))))
                    deleted += 1
            except Exception:
                pass
        tx.Commit()
    except Exception:
        try:
            tx.RollBack()
        except Exception:
            pass
        return 0
    return deleted


def _surviving_created_dim_ids():
    out = set()
    lookup_failed = False
    for did in list(_CREATED_DIM_IDS):
        try:
            if doc.GetElement(DB.ElementId(Int64(int(did)))) is not None:
                out.add(int(did))
        except Exception as error:
            # A lookup error is not evidence that Revit deleted a dimension.
            lookup_failed = True
            globals().setdefault('AUTODIM_LOOKUP_ERRORS', []).append(
                {'dimension_id': int(did), 'phase': 'survival', 'error': str(error)})
    if lookup_failed:
        path = None
        try:
            path = _write_run_audit({'schema_version': 3, 'engine': 'duct-6.8-text-pockets',
                                    'phase': 'survival-lookup-failed',
                                    'lookup_errors': globals().get('AUTODIM_LOOKUP_ERRORS', []),
                                    'recovery_stopped': True})
        except Exception:
            pass
        raise RuntimeError('Dimension lookup failed; recovery stopped to avoid repeated creation. '
                           'Lookup audit: {0}'.format(path or 'could not be saved'))
    return out


def _xy_distance_points(a, b):
    try:
        dx = float(a.X) - float(b.X)
        dy = float(a.Y) - float(b.Y)
        return (dx * dx + dy * dy) ** 0.5
    except Exception:
        return 1e99


def _source_to_surviving_dims(surviving_ids):
    out = {}
    for dimid in surviving_ids:
        sid = _CREATED_DIM_SOURCE.get(dimid)
        if sid is None:
            continue
        out.setdefault(int(sid), []).append(int(dimid))
    return out


def _member_to_rep_map(resolved):
    out = {}
    for elem, _gdata in resolved:
        try:
            rid = eid_int(elem.Id)
        except Exception:
            continue
        mids = _RUN_MEMBER_IDS.get(rid, set([rid]))
        for mid in mids:
            out[int(mid)] = rid
    return out


def _leg_has_near_surviving_dimension(leg, member_to_rep, source_dims, surviving_ids):
    p = leg.get('point')
    for sid in leg.get('downstream_ids', []):
        rep = member_to_rep.get(int(sid), int(sid))
        for dimid in source_dims.get(rep, []):
            if dimid not in surviving_ids:
                continue
            tp = _CREATED_DIM_TARGETS.get(dimid)
            if tp is None:
                return True
            if _xy_distance_points(p, tp) <= BRANCH_COVERAGE_MAX_DISTANCE_FT:
                return True
    return False


def build_recovery_obstacle_grid(exclude_dim_ids=None):
    exclude_dim_ids = exclude_dim_ids or set()
    """Fast second-pass obstacle model: MEP + annotations + surviving dims only.

    Background/CAD is deliberately omitted here. This pass is only for targets
    that survived all normal layout logic yet still have no actual dimension;
    coverage is more important than soft architectural/CAD preferences.
    """
    grid = SpatialGrid(max(paper_to_model(0.65), 0.5))
    _add_category_rects(grid, 'OST_DuctCurves', 'duct', W_DUCT, 0.010)
    try:
        parts = (DB.FilteredElementCollector(doc, view.Id)
                 .OfClass(DB.FabricationPart)
                 .WhereElementIsNotElementType())
        fab_id = bic_int(DB.BuiltInCategory.OST_FabricationDuctwork)
        for e in parts:
            try:
                if e.Category is None or eid_int(e.Category.Id) != fab_id:
                    continue
                r = element_rect(e)
                if r is None:
                    continue
                kind = 'duct' if is_fabrication_straight(e) else 'fitting'
                wt = W_DUCT if kind == 'duct' else W_FITTING
                grid.add_rect(kind, rect_expand(r, paper_to_model(0.010)), wt, eid_int(e.Id))
            except Exception:
                pass
    except Exception:
        pass

    for bic_name in ('OST_DuctFitting', 'OST_DuctAccessory', 'OST_FlexDuctCurves',
                     'OST_DuctTerminal', 'OST_MechanicalEquipment'):
        _add_category_rects(grid, bic_name, 'fitting', W_FITTING, 0.012)

    try:
        owned = (DB.FilteredElementCollector(doc)
                 .OwnedByView(view.Id)
                 .WhereElementIsNotElementType())
        for e in owned:
            try:
                if isinstance(e, DB.Dimension):
                    try:
                        if eid_int(e.Id) in exclude_dim_ids:
                            continue
                    except Exception:
                        pass
                    try:
                        crv = e.Curve
                        if isinstance(crv, DB.Line):
                            a = uv_of_point(crv.GetEndPoint(0))
                            b = uv_of_point(crv.GetEndPoint(1))
                            grid.add_segment('dimension_line', a, b, W_EXISTING_DIM_LINE, eid_int(e.Id))
                            lane = rect_expand(
                                (min(a[0], b[0]), min(a[1], b[1]),
                                 max(a[0], b[0]), max(a[1], b[1])),
                                paper_to_model(DIMENSION_LANE_HALO_PAPER_IN))
                            grid.add_rect('dimension_lane', lane, W_DIMENSION_LANE, eid_int(e.Id))
                    except Exception:
                        pass
                    try:
                        tp = e.TextPosition
                        if tp is not None:
                            grid.add_rect('dimension_text',
                                          _text_rect_at_point(tp, _dimension_text_direction(e), _dimension_value(e)),
                                          W_EXISTING_DIM, eid_int(e.Id))
                    except Exception:
                        pass
                    continue
                if isinstance(e, DB.IndependentTag):
                    try:
                        r = element_rect(e)
                        if r is not None:
                            grid.add_rect('tag_leader', rect_expand(r, paper_to_model(0.010)),
                                          W_TAG_LEADER, eid_int(e.Id))
                        hp = e.TagHeadPosition
                        if hp is not None:
                            hw = paper_to_model(TAG_HEAD_HALF_W_PAPER_IN)
                            hh = paper_to_model(TAG_HEAD_HALF_H_PAPER_IN)
                            grid.add_rect('tag', (hp.X-hw, hp.Y-hh, hp.X+hw, hp.Y+hh),
                                          W_TAG, eid_int(e.Id))
                            continue
                    except Exception:
                        pass
                if isinstance(e, DB.TextNote):
                    r = element_rect(e)
                    if r is not None:
                        grid.add_rect('annotation', rect_expand(r, paper_to_model(0.018)),
                                      W_ANNOTATION, eid_int(e.Id))
            except Exception:
                pass
    except Exception:
        pass
    return grid


def _surviving_branch_keys(surviving_ids):
    out = set(str(x) for x in _EXISTING_BRANCH_KEYS)
    out.update(str(key) for key, record in globals().get('_BRANCH_RUN_REUSE', {}).items()
               if _shared_run_branch_record_is_valid(record))
    for dimid in surviving_ids:
        try:
            key = _CREATED_DIM_BRANCH_KEY.get(int(dimid))
            if key is not None:
                out.add(str(key))
        except Exception:
            pass
    return out


def _covered_run_rep_ids(resolved, surviving_ids, pre_no_grid=None):
    """Run coverage requires intended grid, mode, source offset, and actual value."""
    member_to_rep = _member_to_rep_map(resolved)
    targets = dict((eid_int(elem.Id), (elem, gdata)) for elem, gdata in resolved)
    for elem in pre_no_grid or []:
        targets[eid_int(elem.Id)] = (elem, None)
    covered = set()
    for dimid in surviving_ids:
        try:
            dimid = int(dimid)
            # Branch identity alone is insufficient; source/grid/mode/offset
            # below independently prove whether this also locates the run.
            source = _CREATED_DIM_SOURCE.get(dimid)
            if source is None:
                continue
            rep = member_to_rep.get(int(source), int(source))
            if rep not in targets:
                continue
            elem, gdata = targets[rep]
            if (_record_matches_run_target(
                    _CREATED_DIM_TARGETS.get(dimid), _CREATED_DIM_MODE.get(dimid),
                    _CREATED_DIM_GRID.get(dimid), elem, gdata) and
                    _certify_created_dimension(dimid)[0]):
                covered.add(rep)
        except Exception:
            pass
    for record in _EXISTING_DIRECT_DIM_RECORDS.values():
        try:
            source = int(record['source_id'])
            rep = member_to_rep.get(source, source)
            if rep not in targets:
                continue
            elem, gdata = targets[rep]
            if (_existing_direct_record_is_valid(record) and
                    _record_matches_run_target(record['target'], record['mode'],
                                               record['grid_id'], elem, gdata)):
                covered.add(rep)
        except Exception:
            pass
    return covered


def _semantic_branch_coverage_counts(covered_run_reps, branch_keys):
    """Return drafting-intent covered-by-run, covered-by-connector, uncovered."""
    covered_downstream = 0
    covered_connector = 0
    uncovered = 0

    for leg in _BRANCH_LEG_RECORDS:
        key = str(leg.get('key'))

        if bool(leg.get('requires_connector_target', False)):
            if key in branch_keys:
                covered_connector += 1
            else:
                uncovered += 1
            continue

        reps = []
        for rid in leg.get('rep_ids', []):
            try:
                reps.append(int(rid))
            except Exception:
                pass

        if reps and any(rid in covered_run_reps for rid in reps):
            covered_downstream += 1
        elif key in branch_keys:
            # Conservative fallback: a separately verified connector dimension may be valid.
            covered_connector += 1
        else:
            uncovered += 1

    return covered_downstream, covered_connector, uncovered


def _raw_target_final_coverage(resolved, pre_no_grid, surviving_ids):
    """Compatibility entry point: report all physical members of verified runs."""
    return _raw_piece_coverage(resolved, pre_no_grid, surviving_ids)


def _raw_piece_coverage(resolved, pre_no_grid, surviving_ids):
    covered_reps = _covered_run_rep_ids(resolved, surviving_ids, pre_no_grid)
    covered_raw = set()

    for rep in covered_reps:
        for mid in _RUN_MEMBER_IDS.get(rep, set([rep])):
            covered_raw.add(int(mid))

    raw_ids = set()
    for elem, _gdata in resolved:
        rep = eid_int(elem.Id)
        for mid in _RUN_MEMBER_IDS.get(rep, set([rep])):
            raw_ids.add(int(mid))
    for elem in pre_no_grid:
        try:
            raw_ids.add(eid_int(elem.Id))
        except Exception:
            pass

    return raw_ids, covered_raw, raw_ids - covered_raw


def _audit_point(point):
    try:
        values = [float(point.X), float(point.Y), float(point.Z)]
        if any(math.isnan(value) or math.isinf(value) for value in values):
            return None
        return values
    except Exception:
        return None


def _build_run_audit(resolved, pre_no_grid, surviving_ids, result):
    """Inventory intended targets so a PDF gap can be traced to its source."""
    covered = _covered_run_rep_ids(resolved, surviving_ids, pre_no_grid)
    branch_keys = _certified_branch_keys(surviving_ids)
    targets = []
    for elem, gdata in list(resolved) + [(e, None) for e in pre_no_grid]:
        source = eid_int(elem.Id)
        grid_info = gdata[0] if gdata is not None else None
        point, mode = (_expected_run_target(elem, grid_info)
                       if grid_info is not None else (None, None))
        line = duct_centerline(elem)
        targets.append({
            'role': 'straight_locator', 'source_id': source,
            'physical_member_ids': sorted(_RUN_MEMBER_IDS.get(source, set([source]))),
            'assigned_grid_id': eid_int(grid_info['element'].Id) if grid_info else None,
            'assigned_grid_name': str(grid_info.get('name', '')) if grid_info else None,
            'assigned_grid_axis': _audit_point(grid_info.get('axis')) if grid_info else None,
            'host_grid_fallback': bool(grid_info and not grid_info.get('view_candidate', True)),
            'source_axis': _audit_point(getattr(line, 'Direction', None)) if line else None,
            'expected_target': _audit_point(point), 'mode': mode,
            'source_midpoint': _audit_point(line_midpoint(line)) if line else None,
            'covered': source in covered, 'no_parallel_grid': gdata is None,
        })
    for leg in _BRANCH_LEG_RECORDS:
        required = bool(leg.get('requires_connector_target', False))
        key = str(leg.get('key'))
        located = (key in branch_keys if required else
                   any(int(rep) in covered for rep in leg.get('rep_ids', [])))
        targets.append({
            'role': 'branch_connector' if required else 'branch_downstream_straight',
            'branch_key': key, 'source_id': leg.get('branch_id'),
            'point': _audit_point(leg.get('point')), 'axis': _audit_point(leg.get('axis')),
            'downstream_ids': list(leg.get('downstream_ids', [])),
            'run_representative_ids': list(leg.get('rep_ids', [])),
            'requires_separate_connector_target': required, 'covered': located,
        })
    dimensions = []
    for dimid in sorted(surviving_ids):
        valid, reason, expected, actual = _certify_created_dimension(dimid)
        dimensions.append({
            'dimension_id': int(dimid), 'created_this_run': True,
            'reference_kind': 'direct-model-reference',
            'reference_element_ids': sorted(_dimension_reference_element_ids(
                doc.GetElement(DB.ElementId(Int64(int(dimid)))))),
            'source_id': _CREATED_DIM_SOURCE.get(dimid),
            'branch_key': _CREATED_DIM_BRANCH_KEY.get(dimid),
            'grid_id': _CREATED_DIM_GRID.get(dimid), 'mode': _CREATED_DIM_MODE.get(dimid),
            'recorded_target': _audit_point(_CREATED_DIM_TARGETS.get(dimid)),
            'certified': valid, 'reason': reason,
            'expected_value_ft': expected, 'actual_value_ft': actual,
        })
    for record in _EXISTING_DIRECT_DIM_RECORDS.values():
        dimensions.append({
            'dimension_id': int(record['dim_id']), 'created_this_run': False,
            'reference_kind': record.get('kind', 'direct-model-reference'),
            'branch_key': record.get('branch_key'),
            'helper_id': record.get('helper_id'),
            'source_id': int(record['source_id']), 'grid_id': int(record['grid_id']),
            'mode': record['mode'], 'recorded_target': _audit_point(record['target']),
            'certified': _existing_direct_record_is_valid(record),
        })
    return {
        'schema_version': 2, 'engine': 'duct-6.8-text-pockets',
        'grid_inventory': globals().get('AUTODIM_GRID_INVENTORY', {}),
        'document': str(doc.Title), 'view': str(view.Name), 'view_id': eid_int(view.Id),
        'revit_version': str(doc.Application.VersionNumber), 'view_scale': int(view.Scale),
        'scope': str(globals().get('AUTODIM_SCOPE', 'view')),
        'grid_mode': str(globals().get('AUTODIM_GRID_MODE', 'all')),
        'summary': dict((key, value) for key, value in result.items() if key != 'message'),
        'targets': targets, 'dimensions': dimensions,
        'attempts': list(globals().get('AUTODIM_ATTEMPTS', [])),
        'lookup_errors': list(globals().get('AUTODIM_LOOKUP_ERRORS', [])),
        'reference_diagnostics': list(globals().get('AUTODIM_REFERENCE_DIAGNOSTICS', {}).values()),
        'text_metrics': list(globals().get('AUTODIM_TEXT_METRICS', {}).values()),
        'text_crop_unverified': bool(globals().get('AUTODIM_TEXT_CROP_UNVERIFIED', False)),
        'branch_run_reuse': [dict((k, _audit_point(v) if k == 'target' else v)
                                  for k, v in record.items())
                             for record in globals().get('_BRANCH_RUN_REUSE', {}).values()
                             if _shared_run_branch_record_is_valid(record)],
        'failures': list(result.get('failures', [])),
        'limitations': [
            'Actual duct references only; no reference-line or reference-plane fallback.',
            'Connector-only targets without a stable physical reference remain unresolved.',
            'Coverage does not certify plotted readability or equivalence to the human sheet.',
        ],
    }


def _write_run_audit(payload):
    path = script.get_data_file('robmep_autodim_duct_' + uuid.uuid4().hex, 'json')
    with open(path, 'w') as stream:
        json.dump(payload, stream, indent=2, sort_keys=True, allow_nan=False)
    return path


def _branch_rep_ids_for_keys(keys):
    keys = set(str(x) for x in keys)
    out = set()
    for leg in _BRANCH_LEG_RECORDS:
        if str(leg.get('key')) not in keys:
            continue
        for rid in leg.get('rep_ids', []):
            try:
                out.add(int(rid))
            except Exception:
                pass
    return out


def _branch_grid_for_leg(leg, grids, allow_any=True):
    p = leg.get('point')
    axis = leg.get('axis')
    if p is not None and axis is not None:
        try:
            a = DB.XYZ(p.X - axis.X, p.Y - axis.Y, view_plane_z())
            b = DB.XYZ(p.X + axis.X, p.Y + axis.Y, view_plane_z())
            ln = DB.Line.CreateBound(a, b)
            gdata = nearest_parallel_grid(ln, grids)
            if gdata is not None:
                return gdata[0]
        except Exception:
            pass
    if allow_any and p is not None:
        return _nearest_any_grid_for_point(p, grids)
    return None


def _combine_branch_station_with_target(leg_point, target_point, grid_info):
    if leg_point is None or target_point is None or grid_info is None:
        return target_point
    try:
        axis = grid_info['axis']
        perp = perp_xy(axis)
        s = leg_point.X * axis.X + leg_point.Y * axis.Y
        n = target_point.X * perp.X + target_point.Y * perp.Y
        return DB.XYZ(axis.X * s + perp.X * n,
                      axis.Y * s + perp.Y * n,
                      view_plane_z())
    except Exception:
        return target_point


def _connector_edge_target_for_leg(leg, grid_info):
    # Rectangular/oval no-straight branch: compute the actual plan edge from the
    # branch connector section. Connector BasisX/BasisY tells us which section
    # dimension lies in plan; projecting both gives a rotation-safe half extent.
    p = leg.get('point')
    axis = leg.get('axis')
    if p is None or axis is None or grid_info is None:
        return None
    shp = str(leg.get('shape') or '').lower()
    if 'rect' not in shp and 'oval' not in shp:
        return None
    try:
        w = float(leg.get('width'))
        h = float(leg.get('height'))
    except Exception:
        return None
    cross = perp_xy(axis)
    extent = 0.0
    bx = leg.get('basis_x')
    by = leg.get('basis_y')
    try:
        if bx is not None:
            extent += abs(dot_xy(cross, bx)) * 0.5 * w
    except Exception:
        pass
    try:
        if by is not None:
            extent += abs(dot_xy(cross, by)) * 0.5 * h
    except Exception:
        pass
    if extent <= 1e-8:
        return None
    p1 = DB.XYZ(p.X + cross.X * extent, p.Y + cross.Y * extent, view_plane_z())
    p2 = DB.XYZ(p.X - cross.X * extent, p.Y - cross.Y * extent, view_plane_z())
    try:
        gn = perp_xy(grid_info['axis'])
        go = grid_info['origin']
        d1 = abs((p1.X-go.X)*gn.X + (p1.Y-go.Y)*gn.Y)
        d2 = abs((p2.X-go.X)*gn.X + (p2.Y-go.Y)*gn.Y)
        return p1 if d1 <= d2 else p2
    except Exception:
        return p1


def _nearest_downstream_straight(leg):
    best = None
    best_d = 1e99
    p = leg.get('point')
    for sid in leg.get('downstream_ids', []):
        try:
            e = doc.GetElement(DB.ElementId(Int64(int(int(sid)))))
            if e is None or not is_supported_straight_duct(e):
                continue
            line = duct_centerline(e)
            if line is None:
                continue
            d = _xy_distance_points(p, line_midpoint(line))
            if d < best_d:
                best_d = d
                best = e
        except Exception:
            pass
    return best


def _branch_source_reference_candidates(elem, leg, grid):
    """Match a genuine fitting/duct reference to the connector's required edge.

    The connector point determines intent only. It is never substituted into
    the ReferenceArray. Every accepted reference comes from the physical part.
    """
    point = leg.get('point')
    axis = leg.get('axis')
    if point is None or axis is None or not is_fabrication_duct_part(elem):
        return None, None, []
    shape = str(leg.get('shape') or '').lower()
    if 'round' in shape:
        target = DB.XYZ(point.X, point.Y, view_plane_z())
        mode = 'branch-round-center'
    else:
        target = _connector_edge_target_for_leg(leg, grid)
        mode = 'branch-edge'
    if target is None:
        return None, mode, []
    # A calculation-only Line describes this connector axis for geometry
    # classification. It is not a Revit element or a dimension reference.
    line = DB.Line.CreateBound(
        DB.XYZ(point.X - axis.X, point.Y - axis.Y, point.Z),
        DB.XYZ(point.X + axis.X, point.Y + axis.Y, point.Z))
    normal = perp_xy(grid['axis'])
    candidates = []
    for c in _fab_reference_candidates(elem, line):
        valid, reason = _fabrication_reference_check(elem, c['ref'], grid, c)
        if valid and abs(dot_xy(vector_xy(target, c['witness']), normal)) > CERT_VALUE_TOL_FT:
            valid, reason = False, 'branch-source-offset-mismatch'
        if valid and 'round' in shape and c['kind'] not in ('curve', 'endpoint'):
            valid, reason = False, 'not-actual-round-center-reference'
        _record_fabrication_reference_check(elem, c, grid, valid, reason)
        if valid:
            candidates.append(c)
    candidates.sort(key=lambda c: (_xy_distance_points(point, c['witness']),
                                   1 if c['kind'] == 'endpoint' else 0))
    return target, mode, candidates


def _shared_run_branch_record_is_valid(record):
    """Same connected source coordinate, not equal displayed values alone."""
    try:
        rep = int(record['run_rep'])
        members = globals().get('_RUN_MEMBER_IDS', {}).get(rep, set())
        if int(record['branch_source']) not in members:
            return False
        dimid = int(record['dim_id'])
        existing = globals().get('_EXISTING_DIRECT_DIM_RECORDS', {}).get(dimid)
        if existing is not None:
            valid = _existing_direct_record_is_valid(existing)
            source = int(existing['source_id'])
            grid_id = int(existing['grid_id'])
            mode = existing['mode']
        else:
            valid = _certify_created_dimension(dimid)[0]
            source = int(_CREATED_DIM_SOURCE.get(dimid, -1))
            grid_id = int(_CREATED_DIM_GRID.get(dimid, -1))
            mode = _CREATED_DIM_MODE.get(dimid)
        if not valid or source not in members or grid_id != int(record['grid_id']):
            return False
        if ('edge' in str(mode)) != ('edge' in str(record['mode'])):
            return False
        dim = doc.GetElement(DB.ElementId(Int64(dimid)))
        return _certify_dimension_against_target(dim, grid_id, record['target'])[0]
    except Exception:
        return False


def _reuse_verified_run_for_branch(elem, leg, target, mode, grid):
    source = eid_int(elem.Id)
    # Inline runs were built with physical AllRefs connectivity, collinearity
    # and matching cross-sections. Unconnected parallel ducts cannot qualify.
    reps = [rep for rep, members in globals().get('_RUN_MEMBER_IDS', {}).items()
            if source in members]
    if not reps:
        return False
    dimids = set(globals().get('_CREATED_DIM_IDS', set()))
    dimids.update(globals().get('_EXISTING_DIRECT_DIM_RECORDS', {}).keys())
    for rep in reps:
        for dimid in dimids:
            record = {'dim_id': int(dimid), 'run_rep': int(rep), 'branch_source': source,
                      'grid_id': eid_int(grid['element'].Id), 'target': target,
                      'mode': mode, 'branch_key': str(leg.get('key'))}
            if _shared_run_branch_record_is_valid(record):
                globals().setdefault('_BRANCH_RUN_REUSE', {})[record['branch_key']] = record
                return True
    return False


def _existing_branch_source_dimension(elem, target, mode, grid, candidate, key):
    """Reuse only the exact source reference, measured geometry and grid."""
    grid_key = _stable_reference_key(grid['reference'])
    source_key = _stable_reference_key(candidate['ref'])
    if grid_key is None or source_key is None:
        return False
    for dim in (DB.FilteredElementCollector(doc, view.Id).OfClass(DB.Dimension)
                .WhereElementIsNotElementType()):
        refs = _single_dimension_references(dim)
        if set(_stable_reference_key(r) for r in refs) != set([grid_key, source_key]):
            continue
        if set(_dimension_reference_element_ids(dim)) != set([
                eid_int(elem.Id), eid_int(grid['element'].Id)]):
            continue
        record = {'dim_id': eid_int(dim.Id), 'source_id': eid_int(elem.Id),
                  'grid_id': eid_int(grid['element'].Id), 'target': target,
                  'mode': mode, 'reference_keys': (grid_key, source_key),
                  'kind': 'direct-branch-reference', 'branch_key': str(key)}
        if _existing_direct_record_is_valid(record):
            _EXISTING_DIRECT_DIM_RECORDS[record['dim_id']] = record
            return True
    return False


def _place_branch_source_dimension(elem, leg, target, mode, grid, candidates,
                                   existing_pairs, obstacle_grid, placement_stats):
    source = eid_int(elem.Id)
    key = str(leg.get('key'))
    if _reuse_verified_run_for_branch(elem, leg, target, mode, grid):
        return ('duplicate', mode, grid['name'],
                'Verified connected run already measures this exact branch edge/center coordinate.')
    normal = perp_xy(grid['axis'])
    layouts = []
    for c in candidates:
        if _existing_branch_source_dimension(elem, target, mode, grid, c, key):
            return ('duplicate', mode, grid['name'], 'Verified actual branch source reference.')
        stations = [target]
        # Stay on the physical line reference's real extent. Planes may be
        # intersected at the connector station; no invented datum is involved.
        a, b = c.get('model_start'), c.get('model_end')
        if c['kind'] == 'endpoint':
            # Place at the actual source point, not a shifted parent-edge line.
            stations = [c['witness']]
        elif a is not None and b is not None:
            sa, sb = dot_xy(a, grid['axis']), dot_xy(b, grid['axis'])
            st = dot_xy(target, grid['axis'])
            if min(sa, sb) - CERT_VALUE_TOL_FT <= st <= max(sa, sb) + CERT_VALUE_TOL_FT:
                try:
                    line = DB.Line.CreateBound(a, b)
                    mid = line_midpoint(line)
                    stations = []
                    for shift, paper, outside in candidate_axis_shifts(line, None):
                        stations.append(DB.XYZ(mid.X + grid['axis'].X * shift,
                                               mid.Y + grid['axis'].Y * shift,
                                               view_plane_z()))
                except Exception:
                    stations = [target]
            else:
                continue  # a parallel edge elsewhere on the part is not this branch
        for station in stations:
            tpt = _combine_branch_station_with_target(station, target, grid)
            gpt = grid_plan_point(tpt, normal, grid['origin'])
            dim_line = make_dimension_line(gpt, tpt)
            if dim_line is None:
                continue
            score, hits, text_rect = score_dimension_candidate(
                obstacle_grid, gpt, tpt, source, 0.0)
            if (hard_collision_count(hits) or
                    text_mep_collision_count(hits) > MAX_TEXT_MEP_OVERLAPS or
                    line_mep_collision_count(hits) > MAX_MEP_LINE_CROSSINGS_RESCUE):
                continue
            layouts.append((score, c, dim_line, gpt, tpt, text_rect, hits))
    placement_stats['candidates'] += len(layouts)
    layouts.sort(key=lambda x: _layout_candidate_rank(x[0], 0.0, x[6]))
    last = None
    for score, candidate, line, gpt, tpt, text_rect, hits in layouts[:DIM_MAX_LAYOUT_ATTEMPTS]:
        dim = None
        try:
            dim = create_dim(grid['reference'], candidate['ref'], line)
            if dim is None:
                continue
            doc.Regenerate()
            _dimid = eid_int(dim.Id)
            _CREATED_DIM_SOURCE[_dimid] = source
            _CREATED_DIM_GRID[_dimid] = eid_int(grid['element'].Id)
            _CREATED_DIM_MODE[_dimid] = mode
            _CREATED_DIM_BRANCH_KEY[_dimid] = key
            _CREATED_DIM_TARGETS[_dimid] = tpt
            if not _certify_created_dimension(_dimid)[0]:
                doc.Delete(dim.Id)
                last = 'Actual branch reference failed measured geometry certification.'
                continue
            planned = hits.get('_planned_text_point')
            if hits.get('_text_pocket_moved') and planned is not None:
                dim.TextPosition = planned
            moved, actual_text_rect = adjust_dimension_text(dim, obstacle_grid, gpt, tpt, source)
            doc.Regenerate()
            if not _created_dimension_text_is_clear(dim, obstacle_grid):
                doc.Delete(dim.Id)
                last = 'Revit branch text did not retain a clear position.'
                continue
            reserve_created_dimension(obstacle_grid, dim, gpt, tpt, actual_text_rect or text_rect)
            existing_pairs.add((min(source, eid_int(grid['element'].Id)),
                                max(source, eid_int(grid['element'].Id))))
            return ('created', mode, grid['name'], 'Actual branch source: ' + candidate['source'])
        except Exception as error:
            last = str(error)
            if dim is not None:
                try:
                    doc.Delete(dim.Id)
                except Exception:
                    pass
    if not layouts:
        return ('blocked', mode, grid['name'], 'Actual branch references found, but no readable bounded corridor.')
    return ('failed', mode, grid['name'], last or 'Revit rejected actual branch source references.')


def _recover_branch_leg_without_helpers(leg, grids, existing_pairs,
                                        obstacle_grid, placement_stats):
    """Try real source geometry; a connector coordinate alone never qualifies."""
    source = int(leg.get('branch_id', -1))
    grid = _branch_grid_for_leg(leg, grids, allow_any=False)
    if grid is None:
        outcome = ('no-grid', 'branch', None, 'No parallel host grid for this branch axis.')
    else:
        elem = doc.GetElement(DB.ElementId(Int64(source)))
        target, mode, candidates = _branch_source_reference_candidates(elem, leg, grid)
        if not candidates:
            outcome = ('unsupported', mode or 'branch', grid['name'],
                       'No actual source edge/center reference matches this branch connector target. '
                       'Reference lines and planes are not used.')
        else:
            outcome = _place_branch_source_dimension(elem, leg, target, mode, grid, candidates,
                                                      existing_pairs, obstacle_grid, placement_stats)
    return _record_dimension_attempt(source, 'direct-branch:' + str(leg.get('key')), outcome)


# -----------------------------------------------------------------------------
# SELECTION
# -----------------------------------------------------------------------------
class DuctSelectionFilter(UI.Selection.ISelectionFilter):
    def AllowElement(self, elem):
        try:
            return is_supported_straight_duct(elem) and is_plan_run(elem)
        except Exception:
            return False

    def AllowReference(self, reference, point):
        return True


def selected_ducts():
    result = []
    seen = set()
    try:
        ids = list(uidoc.Selection.GetElementIds())
    except Exception:
        ids = []
    for eid in ids:
        elem = doc.GetElement(eid)
        if elem is None:
            continue
        try:
            if is_supported_straight_duct(elem) and is_plan_run(elem):
                k = eid_int(elem.Id)
                if k not in seen:
                    seen.add(k)
                    result.append(elem)
        except Exception:
            pass
    return result


def pick_ducts():
    try:
        refs = uidoc.Selection.PickObjects(
            UI.Selection.ObjectType.Element,
            DuctSelectionFilter(),
            'Select straight ductwork to dimension to nearest grid, then Finish.'
        )
    except Exception:
        return []
    result = []
    seen = set()
    for r in refs:
        try:
            elem = doc.GetElement(r.ElementId)
            k = eid_int(elem.Id)
            if k not in seen:
                seen.add(k)
                result.append(elem)
        except Exception:
            pass
    return result


def visible_ducts():
    """Collect every visible straight duct target in the active view."""
    result = []
    seen = set()
    collectors = []
    try:
        collectors.append(
            DB.FilteredElementCollector(doc, view.Id)
              .OfCategory(DB.BuiltInCategory.OST_DuctCurves)
              .WhereElementIsNotElementType()
        )
    except Exception:
        pass
    try:
        collectors.append(
            DB.FilteredElementCollector(doc, view.Id)
              .OfClass(DB.FabricationPart)
              .WhereElementIsNotElementType()
        )
    except Exception:
        pass

    for collector in collectors:
        try:
            items = list(collector)
        except Exception:
            items = []
        for elem in items:
            try:
                if not is_supported_straight_duct(elem) or not is_plan_run(elem):
                    continue
                did = eid_int(elem.Id)
                if did in seen:
                    continue
                seen.add(did)
                result.append(elem)
            except Exception:
                pass
    return result


def input_ducts():
    scope = str(globals().get('AUTODIM_SCOPE', 'view')).lower()
    if scope == 'view':
        return visible_ducts()
    if scope == 'pick':
        return pick_ducts()
    return selected_ducts()


# -----------------------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------------------
def main():
    started = time.time()
    globals()['AUTODIM_ATTEMPTS'] = []
    globals()['AUTODIM_LOOKUP_ERRORS'] = []
    globals()['_BRANCH_RUN_REUSE'] = {}

    if not isinstance(view, DB.ViewPlan):
        forms.alert('DUCT AUTODIM v6.0 currently runs in plan views only.', title='DUCT AUTODIM')
        return
    try:
        if view.IsTemplate:
            forms.alert('Open a normal project plan view first.', title='DUCT AUTODIM')
            return
    except Exception:
        pass
    try:
        if doc.IsReadOnly:
            forms.alert('This Revit document is read-only.', title='DUCT AUTODIM')
            return
    except Exception:
        pass

    ducts = input_ducts()
    if not ducts:
        forms.alert(
            'No straight ductwork was found in the chosen AutoDim scope.',
            title='AUTODIM SMART'
        )
        return

    # Branch inventory can recover a straight just after a takeoff/elbow chain
    # even if it was not present in the user's original straight-only selection.
    _t_branch = time.time()
    ducts, direct_branch_anchors, branch_stats = augment_ducts_from_branch_events(ducts)
    phase_branch = time.time() - _t_branch

    _t_grid = time.time()
    grids = collect_straight_grids()
    phase_grid = time.time() - _t_grid
    if not grids:
        forms.alert(
            'No straight host-model gridlines with usable Revit references were found.\n\n'
            'Actual duct references are required; linked/curved grids remain unsupported.',
            title='DUCT AUTODIM'
        )
        return

    # Resolve each duct's nearest grid once, then build one shared obstacle index
    # covering the actual dimension corridors. This lets dimensions coordinate
    # with tags/background/ductwork AND with dimensions created earlier in the run.
    resolved = []
    pre_no_grid = []
    angled_round_rescued_ids = set()
    for elem in ducts:
        line = duct_centerline(elem)
        gdata = nearest_parallel_grid(line, grids) if line is not None else None

        # v0.5+ angled-round rule: a diagonal ROUND straight does not have a side-edge requirement.
        # If no grid is parallel to its axis, try the nearest straight grid and
        # dimension the round center point normal to that grid.  This specifically
        # catches short 30/45-degree round branches like the field-test miss.
        if (ENABLE_NONPARALLEL_CENTER_RESCUE and gdata is None and
                line is not None and duct_shape(elem) == 'round'):
            gdata = nearest_grid_for_round_center(line, grids)
            if gdata is not None and not grid_is_parallel_to_duct(gdata):
                angled_round_rescued_ids.add(eid_int(elem.Id))

        if gdata is None:
            pre_no_grid.append(elem)
        else:
            resolved.append((elem, gdata))

    # Topology-aware branch segmentation: suppress only physically connected
    # inline pieces. Branches, elbows, transitions and disconnected nearby runs
    # remain independent locating targets.
    resolved, run_suppressed = collapse_same_run_dimensions(resolved)
    resolved.sort(key=_target_branch_priority)
    branch_stats['priority_targets'] = sum(
        1 for _e, _g in resolved
        if any(_id in _BRANCH_DOWNSTREAM_IDS
               for _id in _RUN_MEMBER_IDS.get(eid_int(_e.Id), set([eid_int(_e.Id)])))
    )
    _branch_member_to_rep = _member_to_rep_map(resolved)
    for _leg in _BRANCH_LEG_RECORDS:
        _reps = []
        for _sid in _leg.get('downstream_ids', []):
            try:
                _rid = _branch_member_to_rep.get(int(_sid), int(_sid))
                if _rid not in _reps:
                    _reps.append(_rid)
            except Exception:
                pass
        _leg['rep_ids'] = _reps

    _RUN_EXPECTED_TARGET_CACHE.clear()
    _EXISTING_DIRECT_DIM_RECORDS.clear()
    _EXISTING_DIRECT_DIM_RECORDS.update(_audit_existing_direct_dimensions(resolved))

    _t_obstacles = time.time()
    obstacle_grid, dwg_info, link_info = build_dimension_obstacle_grid(resolved)
    phase_obstacles = time.time() - _t_obstacles
    existing_pairs = existing_grid_duct_pairs()
    placement_stats = {
        'candidates': 0, 'shifted': 0, 'centered': 0,
        'dim_hits': 0, 'annotation_hits': 0, 'mep_hits': 0,
        'best_score_sum': 0.0, 'blocked': 0,
        'blocked_annotation': 0, 'blocked_mep': 0, 'blocked_text_mep': 0,
        'clean_corridor': 0, 'mep_relaxed': 0, 'witness_rescue': 0,
        'text_nudged': 0, 'run_extended_used': 0,
        'alternate_run_host_used': 0, 'outside_corridor_used': 0, 'text_pocket_rescued': 0,
    }
    counts = {
        'created': 0,
        'edge': 0,
        'round-center': 0,
        'duplicate': 0,
        'no-grid': 0,
        'no-edge-ref': 0,
        'blocked': 0,
        'failed': 0,
        'branch-anchor-created': 0,
        'branch-anchor-blocked': 0,
        'branch-anchor-failed': 0,
        'branch-first-created': 0,
        'branch-first-duplicate': 0,
        'branch-first-blocked': 0,
    }
    angled_round_created = 0
    failures = []
    recovery_stats = {
        'initial_survivors': 0,
        'missing_targets_after_commit': 0,
        'direct_recovery_created': 0,
        'direct_recovery_blocked': 0,
        'branch_legs_covered_near': 0,
        'branch_legs_rescued': 0,
        'branch_legs_still_uncovered': 0,
        'unsupported_branch_shape': 0,
        'branch_identity_covered_first': 0,
        'branch_downstream_covered': 0,
        'branch_connector_covered': 0,
        'run_segments_total': 0,
        'run_segments_covered_first': 0,
        'run_segments_covered_final': 0,
        'run_segments_still_uncovered': 0,
        'raw_straights_total': 0,
        'raw_straights_covered': 0,
        'raw_straights_uncovered': 0,
        'raw_uncovered_ids': [],
        'final_text_deconflicts': 0,
        'mandatory_run_rescued': 0,
        'mandatory_branch_rescued': 0,
        'mandatory_blocked': 0,
        'mandatory_runtime': 0.0,
    }
    phase_recovery = 0.0

    _t_place = time.time()
    tx = DB.Transaction(doc, 'DUCT AUTODIM - nearest grid')
    try:
        tx.Start()
        _failure_preprocessor = _AutoDimFailurePreprocessor()
        try:
            _fho = tx.GetFailureHandlingOptions()
            _fho.SetFailuresPreprocessor(_failure_preprocessor)
            tx.SetFailureHandlingOptions(_fho)
        except Exception:
            pass
    except Exception as ex:
        forms.alert('Could not start Revit transaction.\n\n{0}'.format(ex), title='DUCT AUTODIM')
        return

    try:
        # RAW-TARGET REBUILD:
        # straight MEP pieces always place first. Branch obligations are additive
        # and are deferred until after all real straight targets are attempted.
        _branch_first_rep_ids = set()

        for elem in pre_no_grid:
            did = eid_int(elem.Id)
            st = DB.SubTransaction(doc)
            st.Start()
            try:
                line = duct_centerline(elem)
                mid = line_midpoint(line) if line is not None else None
                any_grid = _nearest_any_grid_for_point(mid, grids) if mid is not None else None
                if any_grid is None:
                    st.RollBack()
                    counts['no-grid'] += 1
                    failures.append((did, 'No host grid within {0:.0f} ft.'.format(MAX_GRID_DISTANCE_FT)))
                    continue
                status, mode, grid_name, detail = try_dimension_direct_recovery(
                    elem, any_grid, existing_pairs, obstacle_grid, placement_stats,
                    token='NG')
                if status == 'created':
                    st.Commit()
                    counts['created'] += 1
                    if mode in counts:
                        counts[mode] += 1
                elif status == 'duplicate':
                    st.Commit()
                    counts['duplicate'] += 1
                else:
                    st.RollBack()
                    if status == 'blocked':
                        counts['blocked'] += 1
                    elif status == 'no-edge-ref':
                        counts['no-edge-ref'] += 1
                    else:
                        counts['no-grid'] += 1
                    failures.append((did, 'direct-recovery {0} | Grid {1} | {2}'.format(
                        status, grid_name, detail)))
            except Exception as ex:
                try:
                    st.RollBack()
                except Exception:
                    pass
                counts['no-grid'] += 1
                failures.append((did, 'direct-recovery exception | {0}'.format(ex)))

        for elem, gdata in resolved:
            did = eid_int(elem.Id)
            st = DB.SubTransaction(doc)
            st.Start()
            try:
                status, mode, grid_name, detail = try_dimension_duct(elem, gdata, existing_pairs, obstacle_grid, placement_stats)
                if status == 'created':
                    st.Commit()
                    counts['created'] += 1
                    if mode in counts:
                        counts[mode] += 1
                    if did in angled_round_rescued_ids:
                        angled_round_created += 1
                elif status == 'duplicate':
                    # A verified direct duplicate may retain existing measured geometry. Retain
                    # that verified update instead of rolling it back on rerun.
                    st.Commit()
                    counts['duplicate'] += 1
                else:
                    st.RollBack()
                    if status in counts:
                        counts[status] += 1
                    else:
                        counts['failed'] += 1
                    if status not in ('duplicate',):
                        failures.append((did, '{0} | Grid {1} | {2}'.format(status, grid_name, detail)))
            except Exception as ex:
                try:
                    st.RollBack()
                except Exception:
                    pass
                counts['failed'] += 1
                failures.append((did, str(ex)))

        # Add genuine no-straight branch stubs only AFTER all raw straight
        # targets have had first claim on placement space.
        for _leg in _BRANCH_LEG_RECORDS:
            if not bool(_leg.get('requires_connector_target', False)):
                continue
            st = DB.SubTransaction(doc)
            st.Start()
            try:
                _status = _recover_branch_leg_without_helpers(
                    _leg, grids, existing_pairs, obstacle_grid, placement_stats)
                if _status[0] == 'created':
                    st.Commit()
                    counts['created'] += 1
                    counts['branch-first-created'] += 1
                elif _status[0] == 'duplicate':
                    st.Commit()
                    counts['branch-first-duplicate'] += 1
                else:
                    st.RollBack()
                    counts['branch-first-blocked'] += 1
            except Exception:
                try:
                    st.RollBack()
                except Exception:
                    pass
                counts['branch-first-blocked'] += 1

        # Branch anchors are intentionally deferred until AFTER the first commit.
        # That lets us audit which dimensions actually survived Revit failure
        # processing and prevents dimension duplicates on already-covered branches.

        if counts['created'] > 0:
            tx.Commit()
        else:
            tx.RollBack()
    except Exception as ex:
        try:
            tx.RollBack()
        except Exception:
            pass
        forms.alert('DUCT AUTODIM stopped.\n\n{0}'.format(ex), title='DUCT AUTODIM')
        return

    # ------------------------------------------------------------------
    # Post-commit survival audit. The failure preprocessor can delete a bad
    # dimension during Commit(), so "NewDimension succeeded" is not proof that
    # the drawing actually contains that location dimension.
    # ------------------------------------------------------------------
    _t_recovery = time.time()
    surviving_first = _surviving_created_dim_ids()
    recovery_stats['initial_survivors'] = len(surviving_first)
    source_dims = _source_to_surviving_dims(surviving_first)
    member_to_rep = _member_to_rep_map(resolved)

    # Semantic drafting truth:
    # Every topology straight-run must own a surviving locating dimension.
    # Branches with a downstream straight are covered by that RUN, not by a
    # branch-key proxy. Only no-straight branches require their own connector
    # helper dimension.
    covered_run_reps = _covered_run_rep_ids(resolved, surviving_first, pre_no_grid)
    covered_branch_keys = _surviving_branch_keys(surviving_first)
    _bd, _bc, _bu = _semantic_branch_coverage_counts(
        covered_run_reps, covered_branch_keys)

    recovery_stats['branch_downstream_covered'] = _bd
    recovery_stats['branch_connector_covered'] = _bc
    recovery_stats['branch_legs_covered_near'] = _bd + _bc
    recovery_stats['branch_identity_covered_first'] = _bd + _bc
    recovery_stats['run_segments_total'] = len(resolved) + len(pre_no_grid)
    recovery_stats['run_segments_covered_first'] = len(covered_run_reps)

    # Connector-only targets remain explicit unresolved obligations when
    # no actual physical source reference is available.
    uncovered_legs = [
        leg for leg in _BRANCH_LEG_RECORDS
        if bool(leg.get('requires_connector_target', False))
        and str(leg.get('key')) not in covered_branch_keys
    ]

    # Primary recovery targets are uncovered topology runs. A branch dimension
    # is never allowed to hide a missing straight-run dimension.
    potential_missing_targets = []
    for _elem, _gdata in resolved:
        _sid = eid_int(_elem.Id)
        if _sid not in covered_run_reps:
            potential_missing_targets.append((_elem, _gdata))
    for _elem in pre_no_grid:
        _sid = eid_int(_elem.Id)
        if not source_dims.get(_sid):
            potential_missing_targets.append((_elem, None))

    recovery_stats['missing_targets_after_commit'] = len(potential_missing_targets)

    if potential_missing_targets or uncovered_legs:
        recovery_grid = build_recovery_obstacle_grid()
        recovery_pairs = existing_grid_duct_pairs()
        rtx = DB.Transaction(doc, 'DUCT AUTODIM - identity coverage recovery')
        try:
            rtx.Start()
            try:
                _rfho = rtx.GetFailureHandlingOptions()
                _rfho.SetFailuresPreprocessor(_AutoDimFailurePreprocessor())
                rtx.SetFailureHandlingOptions(_rfho)
            except Exception:
                pass

            # RAW-TARGET RECOVERY:
            # missing straight pieces retry actual references before branch review.
            _surv_mid = _surviving_created_dim_ids()
            _covered_runs_mid = _covered_run_rep_ids(resolved, _surv_mid, pre_no_grid)

            # Recover every topology run that STILL lacks its own surviving
            # location dimension.
            for _elem, _gdata in potential_missing_targets[:POST_COMMIT_RECOVERY_MAX_ATTEMPTS]:
                _sid = eid_int(_elem.Id)
                if _sid in _covered_runs_mid:
                    continue
                st = DB.SubTransaction(doc)
                st.Start()
                try:
                    if _gdata is not None:
                        _grid = _gdata[0]
                    else:
                        _line = duct_centerline(_elem)
                        _mid = line_midpoint(_line) if _line is not None else None
                        _grid = _nearest_any_grid_for_point(_mid, grids) if _mid is not None else None
                    if _grid is None:
                        st.RollBack()
                        recovery_stats['direct_recovery_blocked'] += 1
                        continue
                    _status = try_dimension_direct_recovery(
                        _elem, _grid, recovery_pairs, recovery_grid,
                        placement_stats, token='PC')
                    if _status[0] == 'created':
                        st.Commit()
                        recovery_stats['direct_recovery_created'] += 1
                    elif _status[0] == 'duplicate':
                        st.Commit()
                    else:
                        st.RollBack()
                        recovery_stats['direct_recovery_blocked'] += 1
                except Exception:
                    try:
                        st.RollBack()
                    except Exception:
                        pass
                    recovery_stats['direct_recovery_blocked'] += 1

            # Only after straight recovery is exhausted do we add genuine
            # unresolved no-straight branch connectors.
            for _leg in uncovered_legs:
                st = DB.SubTransaction(doc)
                st.Start()
                try:
                    _status = _recover_branch_leg_without_helpers(
                        _leg, grids, recovery_pairs, recovery_grid,
                        placement_stats)
                    if _status[0] == 'created':
                        st.Commit()
                        recovery_stats['branch_legs_rescued'] += 1
                    elif _status[0] == 'duplicate':
                        st.Commit()
                    else:
                        st.RollBack()
                        if _status[0] == 'unsupported':
                            recovery_stats['unsupported_branch_shape'] += 1
                except Exception:
                    try:
                        st.RollBack()
                    except Exception:
                        pass

            rtx.Commit()
        except Exception as _rex:
            try:
                rtx.RollBack()
            except Exception:
                pass
            failures.append((-1, 'identity-coverage recovery | {0}'.format(_rex)))


    # -----------------------------------------------------------------
    # FINAL MANDATORY COVERAGE RESCUE
    # Normal placement and normal recovery are finished. Now rescue only
    # targets that are STILL semantically uncovered.
    # -----------------------------------------------------------------
    _mandatory_start = time.time()
    recovery_stats['mandatory_run_rescued'] = 0
    recovery_stats['mandatory_branch_rescued'] = 0
    recovery_stats['mandatory_blocked'] = 0

    _pre_mandatory_survivors = _surviving_created_dim_ids()
    _pre_mandatory_branch_keys = _surviving_branch_keys(_pre_mandatory_survivors)
    _pre_mandatory_runs = _covered_run_rep_ids(resolved, _pre_mandatory_survivors, pre_no_grid)

    _missing_run_items = []
    for _elem, _gdata in list(resolved) + [(elem, None) for elem in pre_no_grid]:
        try:
            _rid = eid_int(_elem.Id)
        except Exception:
            continue
        if _rid not in _pre_mandatory_runs:
            _missing_run_items.append((_elem, _gdata))

    _missing_branch_legs = []
    for _leg in _BRANCH_LEG_RECORDS:
        if not bool(_leg.get('requires_connector_target', False)):
            continue
        if str(_leg.get('key')) in _pre_mandatory_branch_keys:
            continue
        _missing_branch_legs.append(_leg)

    if _missing_run_items or _missing_branch_legs:
        _mandatory_pairs = existing_grid_duct_pairs()
        _mandatory_grid = build_recovery_obstacle_grid(
            exclude_dim_ids=_pre_mandatory_survivors)
        _mtx = DB.Transaction(doc, 'DUCT AUTODIM - mandatory coverage rescue')
        try:
            _mtx.Start()
            try:
                _mfho = _mtx.GetFailureHandlingOptions()
                _mfho.SetFailuresPreprocessor(_AutoDimFailurePreprocessor())
                _mtx.SetFailureHandlingOptions(_mfho)
            except Exception:
                pass

            globals()['_MANDATORY_RESCUE_MODE'] = True

            for _elem, _gdata in _missing_run_items:
                st = DB.SubTransaction(doc)
                st.Start()
                try:
                    _grid = _gdata[0] if _gdata is not None else None
                    if _grid is None:
                        _line = duct_centerline(_elem)
                        _mid = line_midpoint(_line) if _line is not None else None
                        _grid = _nearest_any_grid_for_point(_mid, grids) if _mid is not None else None
                    if _grid is None:
                        st.RollBack()
                        recovery_stats['mandatory_blocked'] += 1
                        continue
                    _status = try_dimension_direct_recovery(
                        _elem, _grid, _mandatory_pairs, _mandatory_grid,
                        placement_stats, token='MR')
                    if _status[0] == 'created':
                        st.Commit()
                        recovery_stats['mandatory_run_rescued'] += 1
                    elif _status[0] == 'duplicate':
                        st.Commit()
                    else:
                        st.RollBack()
                        recovery_stats['mandatory_blocked'] += 1
                        failures.append((eid_int(_elem.Id), 'mandatory {0} | Grid {1} | {2}'.format(
                            _status[0], _status[2], _status[3])))
                except Exception as _mandatory_error:
                    try:
                        st.RollBack()
                    except Exception:
                        pass
                    recovery_stats['mandatory_blocked'] += 1
                    failures.append((eid_int(_elem.Id), 'mandatory exception | ' + str(_mandatory_error)))

            for _leg in _missing_branch_legs:
                st = DB.SubTransaction(doc)
                st.Start()
                try:
                    _status = _recover_branch_leg_without_helpers(
                        _leg, grids, _mandatory_pairs, _mandatory_grid,
                        placement_stats)
                    if _status[0] == 'created':
                        st.Commit()
                        recovery_stats['mandatory_branch_rescued'] += 1
                    elif _status[0] == 'duplicate':
                        st.Commit()
                    else:
                        st.RollBack()
                        recovery_stats['mandatory_blocked'] += 1
                except Exception:
                    try:
                        st.RollBack()
                    except Exception:
                        pass
                    recovery_stats['mandatory_blocked'] += 1

            globals()['_MANDATORY_RESCUE_MODE'] = False
            _mtx.Commit()
        except Exception as _mex:
            globals()['_MANDATORY_RESCUE_MODE'] = False
            try:
                _mtx.RollBack()
            except Exception:
                pass
            failures.append((-1, 'mandatory coverage rescue | {0}'.format(_mex)))

    recovery_stats['mandatory_runtime'] = time.time() - _mandatory_start


    # -----------------------------------------------------------------
    # ACTUAL GEOMETRIC COVERAGE CERTIFICATION
    # A topology/source relationship is only a candidate. Coverage is granted
    # only after the surviving Revit Dimension itself proves:
    #   1) it references the intended grid;
    #   2) its actual measured Value matches the recorded target-to-grid value;
    #   3) its dimension line is geometrically compatible with that grid.
    # -----------------------------------------------------------------
    _cert_started = time.time()
    _cert_before = _certification_snapshot(resolved, _surviving_created_dim_ids(), pre_no_grid)
    _CERTIFICATION_STATS['checked'] = len(_surviving_created_dim_ids())
    _CERTIFICATION_STATS['pre_rescue_required'] = _cert_before['required_total']
    _CERTIFICATION_STATS['pre_rescue_certified'] = _cert_before['certified_total']
    _CERTIFICATION_STATS['pre_rescue_uncovered_runs'] = len(_cert_before['missing_run_items'])
    _CERTIFICATION_STATS['pre_rescue_uncovered_branches'] = len(_cert_before['missing_branch_legs'])
    _CERTIFICATION_STATS['false_coverage_rejected'] = len(_cert_before['rejected'])
    _record_certification_rejections(_cert_before['rejected'])

    # Uncertified dimensions created by this command are not allowed to remain
    # as visual clutter or to block a correct rescue dimension.
    _delete_created_dimensions(
        [r[0] for r in _cert_before['rejected']],
        'DUCT AUTODIM - remove uncertified dimensions')

    _cert_survivors = _surviving_created_dim_ids()
    _cert_state = _certification_snapshot(resolved, _cert_survivors, pre_no_grid)

    if _cert_state['missing_run_items'] or _cert_state['missing_branch_legs']:
        _cert_pairs = existing_grid_duct_pairs()
        _cert_grid = build_recovery_obstacle_grid(exclude_dim_ids=_cert_survivors)
        _ctx_cert = DB.Transaction(doc, 'DUCT AUTODIM - geometric certification rescue')
        try:
            _ctx_cert.Start()
            try:
                _cfho = _ctx_cert.GetFailureHandlingOptions()
                _cfho.SetFailuresPreprocessor(_AutoDimFailurePreprocessor())
                _ctx_cert.SetFailureHandlingOptions(_cfho)
            except Exception:
                pass

            # Certification rescue is mandatory-target mode: broad witness-line
            # routing is allowed, but actual text safety is still validated.
            globals()['_MANDATORY_RESCUE_MODE'] = True

            for _elem, _gdata in _cert_state['missing_run_items']:
                st = DB.SubTransaction(doc)
                st.Start()
                try:
                    _grid = _gdata[0] if _gdata is not None else None
                    if _grid is None:
                        _line = duct_centerline(_elem)
                        _mid = line_midpoint(_line) if _line is not None else None
                        _grid = _nearest_any_grid_for_point(_mid, grids) if _mid is not None else None
                    if _grid is None:
                        st.RollBack()
                        continue
                    _status = try_dimension_direct_recovery(
                        _elem, _grid, _cert_pairs, _cert_grid,
                        placement_stats, token='GC')
                    if _status[0] == 'created':
                        st.Commit()
                        _CERTIFICATION_STATS['rescued_runs'] += 1
                    elif _status[0] == 'duplicate':
                        st.Commit()
                    else:
                        st.RollBack()
                except Exception:
                    try:
                        st.RollBack()
                    except Exception:
                        pass

            for _leg in _cert_state['missing_branch_legs']:
                st = DB.SubTransaction(doc)
                st.Start()
                try:
                    _status = _recover_branch_leg_without_helpers(
                        _leg, grids, _cert_pairs, _cert_grid,
                        placement_stats)
                    if _status[0] == 'created':
                        st.Commit()
                        _CERTIFICATION_STATS['rescued_branches'] += 1
                    elif _status[0] == 'duplicate':
                        st.Commit()
                    else:
                        st.RollBack()
                except Exception:
                    try:
                        st.RollBack()
                    except Exception:
                        pass

            globals()['_MANDATORY_RESCUE_MODE'] = False
            _ctx_cert.Commit()
        except Exception as _cert_ex:
            globals()['_MANDATORY_RESCUE_MODE'] = False
            try:
                _ctx_cert.RollBack()
            except Exception:
                pass
            failures.append((-1, 'geometric certification rescue | {0}'.format(_cert_ex)))

    # Re-certify the ACTUAL post-rescue dimensions. Any rescue dimension that
    # still fails geometric truth is removed and does not count as coverage.
    _cert_after = _certification_snapshot(resolved, _surviving_created_dim_ids(), pre_no_grid)
    _delete_created_dimensions(
        [r[0] for r in _cert_after['rejected']],
        'DUCT AUTODIM - remove failed certification rescues')
    _cert_final = _certification_snapshot(resolved, _surviving_created_dim_ids(), pre_no_grid)

    _CERTIFICATION_STATS['certified_dims'] = len(_cert_final['certified_ids'])
    _CERTIFICATION_STATS['rejected_dims'] = len(_cert_before['rejected']) + len(_cert_after['rejected'])
    _CERTIFICATION_STATS['final_required'] = _cert_final['required_total']
    _CERTIFICATION_STATS['final_certified'] = _cert_final['certified_total']
    _CERTIFICATION_STATS['final_uncovered_runs'] = len(_cert_final['missing_run_items'])
    _CERTIFICATION_STATS['final_uncovered_branches'] = len(_cert_final['missing_branch_legs'])
    _CERTIFICATION_STATS['certification_runtime'] = time.time() - _cert_started

    globals()['_CERT_FINAL_IDS'] = set(_cert_final['certified_ids'])
    globals()['_CERT_FINAL_UNCOVERED_RUN_IDS'] = list(_cert_final['missing_run_ids'])
    globals()['_CERT_FINAL_UNCOVERED_BRANCH_KEYS'] = [
        str(x.get('key')) for x in _cert_final['missing_branch_legs']
    ]

    # Final semantic truth after recovery.
    _surv_after_recovery = set(_CERT_FINAL_IDS)
    _final_branch_keys = _surviving_branch_keys(_surv_after_recovery)
    _final_covered_runs = _covered_run_rep_ids(resolved, _surv_after_recovery, pre_no_grid)
    _fd, _fc, _fu = _semantic_branch_coverage_counts(
        _final_covered_runs, _final_branch_keys)

    recovery_stats['branch_downstream_covered'] = _fd
    recovery_stats['branch_connector_covered'] = _fc
    recovery_stats['branch_legs_still_uncovered'] = _fu
    recovery_stats['branch_legs_covered_near'] = _fd + _fc
    recovery_stats['run_segments_covered_final'] = len(_final_covered_runs)
    recovery_stats['run_segments_still_uncovered'] = max(
        0, len(resolved) + len(pre_no_grid) - len(_final_covered_runs))
    _raw_ids, _raw_covered, _raw_missing = _raw_target_final_coverage(
        resolved, pre_no_grid, _surv_after_recovery)
    recovery_stats['raw_straights_total'] = len(_raw_ids)
    recovery_stats['raw_straights_covered'] = len(_raw_covered.intersection(_raw_ids))
    recovery_stats['raw_straights_uncovered'] = len(_raw_missing)
    recovery_stats['raw_uncovered_ids'] = sorted(list(_raw_missing))
    phase_recovery = time.time() - _t_recovery

    # FINAL truth comes from what still exists in the model after both commits.
    final_survivors = set(_CERT_FINAL_IDS).intersection(_surviving_created_dim_ids())

    # Re-space actual surviving text positions after Revit has finished all
    # transaction/failure processing. Existing dimensions stay in the obstacle
    # model; this run's dimensions are inserted one-by-one after cleanup so they
    # cannot finish on top of one another.
    if final_survivors:
        _cleanup_grid = build_recovery_obstacle_grid(exclude_dim_ids=final_survivors)
        _ctx = DB.Transaction(doc, 'DUCT AUTODIM - final text deconflict')
        try:
            _ctx.Start()
            for _dimid in sorted(final_survivors):
                try:
                    _dim = doc.GetElement(DB.ElementId(Int64(int(int(_dimid)))))
                    if _dim is None:
                        continue
                    _crv = _dim.Curve
                    if not isinstance(_crv, DB.Line):
                        continue
                    _gpt = _crv.GetEndPoint(0)
                    _tpt = _crv.GetEndPoint(1)
                    _sid = _CREATED_DIM_SOURCE.get(int(_dimid), -1)
                    _moved, _rect = adjust_dimension_text(
                        _dim, _cleanup_grid, _gpt, _tpt, _sid)
                    if _moved:
                        recovery_stats['final_text_deconflicts'] += 1
                    reserve_created_dimension(
                        _cleanup_grid, _dim, _gpt, _tpt,
                        _rect or dimension_text_rect(_gpt, _tpt), record_target=False)
                except Exception:
                    pass
            _ctx.Commit()
        except Exception:
            try:
                _ctx.RollBack()
            except Exception:
                pass
        final_survivors = set(_CERT_FINAL_IDS).intersection(_surviving_created_dim_ids())
    # Report one coherent snapshot after the final text transaction commits.
    # A dimension removed by regeneration must not remain in target totals.
    _cert_final = _certification_snapshot(resolved, _surviving_created_dim_ids(), pre_no_grid)
    final_survivors = set(_cert_final['certified_ids'])
    globals()['_CERT_FINAL_IDS'] = set(final_survivors)
    globals()['_CERT_FINAL_UNCOVERED_RUN_IDS'] = list(_cert_final['missing_run_ids'])
    globals()['_CERT_FINAL_UNCOVERED_BRANCH_KEYS'] = [
        str(leg.get('key')) for leg in _cert_final['missing_branch_legs']]
    _CERTIFICATION_STATS['certified_dims'] = len(final_survivors)
    _CERTIFICATION_STATS['final_required'] = _cert_final['required_total']
    _CERTIFICATION_STATS['final_certified'] = _cert_final['certified_total']
    _CERTIFICATION_STATS['final_uncovered_runs'] = len(_cert_final['missing_run_items'])
    _CERTIFICATION_STATS['final_uncovered_branches'] = len(_cert_final['missing_branch_legs'])
    _final_covered_runs = _cert_final['covered_runs']
    recovery_stats['run_segments_covered_final'] = len(_final_covered_runs)
    recovery_stats['run_segments_still_uncovered'] = (
        len(resolved) + len(pre_no_grid) - len(_final_covered_runs))
    _fd, _fc, _fu = _semantic_branch_coverage_counts(
        _final_covered_runs, _cert_final['branch_keys'])
    recovery_stats['branch_downstream_covered'] = _fd
    recovery_stats['branch_connector_covered'] = _fc
    recovery_stats['branch_legs_still_uncovered'] = _fu
    recovery_stats['branch_legs_covered_near'] = _fd + _fc
    _raw_ids, _raw_covered, _raw_missing = _raw_piece_coverage(
        resolved, pre_no_grid, final_survivors)
    recovery_stats['raw_straights_total'] = len(_raw_ids)
    recovery_stats['raw_straights_covered'] = len(_raw_covered.intersection(_raw_ids))
    recovery_stats['raw_straights_uncovered'] = len(_raw_missing)
    recovery_stats['raw_uncovered_ids'] = sorted(_raw_missing)

    final_edge = 0
    final_center = 0
    for _dimid in final_survivors:
        _mode = str(_CREATED_DIM_MODE.get(_dimid, ''))
        if 'edge' in _mode:
            final_edge += 1
        elif 'center' in _mode:
            final_center += 1
    initial_attempted_created = counts['created']
    counts['created'] = len(final_survivors)
    counts['edge'] = final_edge
    counts['round-center'] = final_center

    phase_place = time.time() - _t_place
    elapsed = time.time() - started

    existing_direct_used = sum(1 for record in _EXISTING_DIRECT_DIM_RECORDS.values()
                               if _existing_direct_record_is_valid(record))

    if failures:
        try:
            output.print_md('## DUCT AUTODIM v6.8 text-pocket diagnostics')
            for did, msg in failures[:80]:
                output.print_md('- Duct `{0}`: {1}'.format(did, msg))
        except Exception:
            pass

    msg = (
        'Created {0} SURVIVING dimension(s).\n\n'
        'Rectangular/oval edge -> grid: {1}\n'
        'Round center -> grid: {2}\n'
        '  Unstable angled-center dimensions disabled: yes\n'
        'Already dimensioned / skipped: {3}\n'
        'No usable grid: {4}\n'
        'No usable edge reference: {5}\n'
        'Blocked / skipped for collisions: {6}\n'
        '  Annotation/dimension blocked: {17}\n'
        '  Heavy-MEP blocked: {18}\n'
        'Failed: {7}\n\n'
        'Straight ducts in scope: {8}\n'
        'Raw straight pieces collapsed into verified logical legs: {9}\n'
        'Logical locating legs after resolution: {30}\n'
        'Inline connected links: {31}\n'
        'Topology-break links protected: {32}\n'
        'Singleton branch segments: {33}\n'
        'Branch fittings/events scanned: {34}\n'
        'Branch legs audited: {35}\n'
        'Branch-adjacent straights auto-added: {36}\n'
        'Branch legs mapped to existing straights: {40}\n'
        'Branch-priority locating targets: {41}\n'
        'Round branch connector candidates: {37}\n'
        'Round branch connector dimensions created: {38}\n'
        'Branch legs with no downstream straight: {39}\n'
        'Visible straight grids: {10}\n'
        'Runtime: {11:.2f} sec\n'
        'Initial created attempts before commit pruning: {42}\n'
        'Surviving after first commit: {43}\n'
        'Topology targets missing after first commit: {44}\n'
        'Targets recovered with actual post-commit duct references: {45}\n'
        'Branch legs with own surviving locating dimension: {46}\n'
        'Branch legs recovered after first commit: {47}\n'
        'Branch legs still uncovered: {48}\n'
        'Unsupported no-straight branch shapes: {49}\n'
        'Recovery pass runtime: {50:.2f} sec\n\n'
        'Direct-source certification v6.8:\n'
        'Shifted away from midpoint: {12}\n'
        'Kept near midpoint: {13}\n'
        'Layout candidates scored: {14}\n'
        'Clean corridors used: {19}\n'
        'MEP-relaxed corridors used (<=2 line crossings): {20}\n'
        'Witness-line rescue corridors used (3-12 crossings): {26}\n'
        'Text-on-MEP blocked: {27}\n'
        'Text-pocket rescues: {28}\n'
        'Outside-run corridor rescues: disabled for stability\n'
        'Dimension text nudged: {22}\n'
        'Alternate run-member hosts used: {25}\n'
        'Linked RVT backgrounds scanned: {23}\n'
        'Linked background elements indexed: {24}\n'
        'Visible DWGs scanned: {15}\n'
        'DWG segments indexed: {16}\n\n'
        'Hard avoids dimension text, tag heads and annotations; tag leaders and existing dimension lines use precise soft geometry.\n'
        'Dimension values stay off ductwork/fittings. Witness lines strongly avoid MEP but may cross up to 12 unrelated MEP obstacles only as a rescue.\n'
        'Host + linked-model background/CAD are soft avoidance. Straight targets are suppressed only when Revit AllRefs connectivity proves the same physical measurement. Branch events are audited even when no straight was preselected; takeoff/elbow chains recover downstream straights when possible, while unresolved branch/no-grid/Fabrication targets are reported explicitly. No reference lines or planes are created or reused. Tees/taps, elbows, transitions, offsets, open ends and disconnected/stacked straights start new topology branches; any branch member can host its locating dimension. Fabrication references are classifier-verified on Revit 2025; native duct keeps the hardened geometry path. Host-model straight grids only.'
    ).format(
        counts['created'], counts['edge'], counts['round-center'],
        counts['duplicate'], counts['no-grid'], counts['no-edge-ref'],
        counts['blocked'], counts['failed'], len(ducts), run_suppressed, len(grids), elapsed,
        placement_stats['shifted'], placement_stats['centered'],
        placement_stats['candidates'], dwg_info[0], dwg_info[1],
        placement_stats['blocked_annotation'], placement_stats['blocked_mep'],
        placement_stats['clean_corridor'], placement_stats['mep_relaxed'],
        angled_round_created, placement_stats['text_nudged'], link_info[0], link_info[1],
        placement_stats['alternate_run_host_used'], placement_stats['witness_rescue'],
        placement_stats['blocked_text_mep'], placement_stats['text_pocket_rescued'],
        placement_stats['outside_corridor_used'],
        _TOPOLOGY_STATS.get('components', 0),
        _TOPOLOGY_STATS.get('inline_links', 0),
        _TOPOLOGY_STATS.get('topology_break_links', 0),
        _TOPOLOGY_STATS.get('singleton_components', 0),
        branch_stats.get('events', 0),
        branch_stats.get('legs', 0),
        branch_stats.get('auto_added_straights', 0),
        branch_stats.get('direct_round_candidates', 0),
        counts.get('branch-anchor-created', 0),
        branch_stats.get('no_straight_legs', 0),
        branch_stats.get('mapped_straight_legs', 0),
        branch_stats.get('priority_targets', 0),
        initial_attempted_created,
        recovery_stats.get('initial_survivors', 0),
        recovery_stats.get('missing_targets_after_commit', 0),
        recovery_stats.get('direct_recovery_created', 0),
        recovery_stats.get('branch_legs_covered_near', 0),
        recovery_stats.get('branch_legs_rescued', 0),
        recovery_stats.get('branch_legs_still_uncovered', 0),
        recovery_stats.get('unsupported_branch_shape', 0),
        phase_recovery
    )
    msg += (
        '\n\nDirect duct references only / performance:'
        '\nReference-line and reference-plane fallback: disabled'
        '\nLegacy helper references used (must be zero): {0}'
        '\n  Helpers created this run: {1}'
        '\n  Helpers reused/updated: {2}'
        '\n  Branch helper dimensions: {3}'
        '\nUnstable Fabrication references rejected before creation: {4}'
        '\nTargets sent to helper fallback (disabled): {5}'
        '\nTargets recovered by helper fallback (disabled): {6}'
        '\nHelper attempts blocked (fallback disabled): {7}'
        '\nUnstable new dimensions auto-pruned at commit: {8}'
        '\nCAD scan lightened: yes (major layers only)'
        '\nFinal created count is post-commit survival-verified: yes'
        '\nPerformance phases (sec): branch {9:.2f} | grids {10:.2f} | obstacles/CAD {11:.2f} | placement+commit {12:.2f}'
    ).format(
        _STABILITY_STATS.get('helper_used', 0),
        _STABILITY_STATS.get('helper_created', 0),
        _STABILITY_STATS.get('helper_reused', 0),
        _STABILITY_STATS.get('branch_helper_created', 0),
        _STABILITY_STATS.get('direct_refs_rejected', 0),
        _STABILITY_STATS.get('resolved_helper_attempts', 0),
        _STABILITY_STATS.get('resolved_helper_created', 0),
        _STABILITY_STATS.get('resolved_helper_blocked', 0),
        _STABILITY_STATS.get('commit_pruned', 0),
        phase_branch, phase_grid, phase_obstacles, phase_place
    )
    msg += '\nExisting direct model-to-grid dimensions verified: {0}'.format(existing_direct_used)

    msg += (
        '\n\nExplicit-target / benchmark diagnostics:'
        '\nBranch events with no usable branch connector candidate: {0}'
        '\nConnector links recovered geometrically when AllRefs was empty: {1}'
        '\nBranch targets placed before generic run targets: {2}'
        '\nBranch target duplicates/reused: {3}'
        '\nBranch-first targets blocked: {4}'
        '\nFinal text overlaps/nudges resolved in post-pass: {5}'
        '\nCoverage accounting is topology-run based: yes'
    ).format(
        branch_stats.get('events_no_branch_connector', 0),
        _CONNECTIVITY_STATS.get('fallback_links', 0),
        counts.get('branch-first-created', 0),
        counts.get('branch-first-duplicate', 0),
        counts.get('branch-first-blocked', 0),
        recovery_stats.get('final_text_deconflicts', 0)
    )
    msg += (
        '\n\nRAW-TARGET BASELINE:'
        '\nPhysical straight pieces required: {0}'
        '\nPhysical straight pieces geometrically covered: {1}'
        '\nPHYSICAL STRAIGHT PIECES STILL UNCOVERED: {2}'
        '\nNo-straight branch stubs still uncovered: {3}'
        '\nFabrication connector links recovered geometrically: {4}'
        '\n'
        '\nVerified logical-leg grouping is enabled.'
        '\nOnly inline pieces with the same grid/size/direction/elevation/measurement may share one locating dimension.'
        '\nFabrication connector fallback links are used for branch discovery and verified inline grouping.'
        '\nBranch stubs remain additive and never suppress a logical straight leg.'
    ).format(
        recovery_stats.get('raw_straights_total', 0),
        recovery_stats.get('raw_straights_covered', 0),
        recovery_stats.get('raw_straights_uncovered', 0),
        recovery_stats.get('branch_legs_still_uncovered', 0),
        _CONNECTIVITY_STATS.get('fallback_links', 0)
    )
    if recovery_stats.get('raw_uncovered_ids'):
        try:
            output.print_md('## DUCT AUTODIM RAW TARGETS STILL UNCOVERED')
            for _uid in recovery_stats.get('raw_uncovered_ids', [])[:160]:
                try:
                    _el = doc.GetElement(DB.ElementId(Int64(int(int(_uid)))))
                    _line = duct_centerline(_el) if _el is not None else None
                    _mid = line_midpoint(_line) if _line is not None else None
                    if _mid is not None:
                        output.print_md(
                            '- `{0}` | midpoint ({1:.2f}, {2:.2f})'.format(
                                _uid, _mid.X, _mid.Y))
                    else:
                        output.print_md('- `{0}`'.format(_uid))
                except Exception:
                    output.print_md('- `{0}`'.format(_uid))
        except Exception:
            pass
    msg += (
        '\n\nDrafting-intent branch audit:'
        '\nBranch legs satisfied by a DIRECT aligned straight: {0}'
        '\nBranch connector targets REQUIRED: {1}'
        '\n  Required even though a downstream straight exists: {2}'
        '\nConnector-target dimensions created in first pass: {3}'
        '\nConnector-target attempts blocked/unsupported first pass: {4}'
        '\nFinal branch legs still uncovered by drafting intent: {5}'
        '\n'
        '\nRule: takeoff -> elbow/offset/transition -> straight does NOT count as'
        '\nlocated by that downstream straight. The original takeoff connector'
        '\ngets its own center/edge-to-grid target.'
    ).format(
        branch_stats.get('direct_axis_legs', 0),
        branch_stats.get('connector_target_legs', 0),
        branch_stats.get('connector_target_with_downstream', 0),
        counts.get('branch-first-created', 0),
        counts.get('branch-first-blocked', 0),
        recovery_stats.get('branch_legs_still_uncovered', 0)
    )

    msg += (
        '\n\nMandatory coverage rescue:'
        '\nLogical straight legs rescued in final pass: {0}'
        '\nRequired branch connector targets rescued in final pass: {1}'
        '\nRequired targets still blocked after expanded rescue: {2}'
        '\nMandatory rescue runtime: {3:.2f} sec'
        '\n'
        '\nThe final rescue expands local stations and allows a more permissive'
        '\nwitness-line path ONLY for targets that remained truly missing.'
        '\nActual dimension text is still rejected if it finishes on hard'
        '\nannotation or unacceptable MEP overlap.'
    ).format(
        recovery_stats.get('mandatory_run_rescued', 0),
        recovery_stats.get('mandatory_branch_rescued', 0),
        recovery_stats.get('mandatory_blocked', 0),
        recovery_stats.get('mandatory_runtime', 0.0)
    )

    msg += (
        '\n\nACTUAL GEOMETRIC COVERAGE CERTIFICATION:'
        '\nRequired locating targets: {0}'
        '\nCertified after normal + mandatory placement: {1}'
        '\nFalse coverage / wrong geometry rejected: {2}'
        '\nCertification-rescued logical legs: {3}'
        '\nCertification-rescued branch axes: {4}'
        '\nFINAL UNCERTIFIED LOGICAL LEGS: {5}'
        '\nFINAL UNCERTIFIED BRANCH AXES: {6}'
        '\nGrid-reference mismatches: {7}'
        '\nMeasured-value mismatches: {8}'
        '\nDimension-direction mismatches: {9}'
        '\nCertification metadata failures: {10}'
        '\nCertification runtime: {11:.2f} sec'
        '\n'
        '\nCoverage is now awarded ONLY when the surviving Revit Dimension'
        '\nreferences the intended grid AND the actual duct source, and its value matches'
        '\nthe recorded target-to-grid geometry within 1/8 inch.'
    ).format(
        _CERTIFICATION_STATS.get('final_required', 0),
        _CERTIFICATION_STATS.get('final_certified', 0),
        _CERTIFICATION_STATS.get('false_coverage_rejected', 0),
        _CERTIFICATION_STATS.get('rescued_runs', 0),
        _CERTIFICATION_STATS.get('rescued_branches', 0),
        _CERTIFICATION_STATS.get('final_uncovered_runs', 0),
        _CERTIFICATION_STATS.get('final_uncovered_branches', 0),
        _CERTIFICATION_STATS.get('grid_ref_mismatch', 0),
        _CERTIFICATION_STATS.get('value_mismatch', 0),
        _CERTIFICATION_STATS.get('direction_mismatch', 0),
        _CERTIFICATION_STATS.get('metadata_missing', 0),
        _CERTIFICATION_STATS.get('certification_runtime', 0.0)
    )

    msg += '\nSource-target mismatches rejected: {0}'.format(
        _CERTIFICATION_STATS.get('source_target_mismatch', 0))
    msg += ('\n\nCertification checks the defined target inventory; it does not certify'
            '\nthat every human branch/terminal locator is present or that the plot is readable.')

    if _CERT_FINAL_UNCOVERED_RUN_IDS or _CERT_FINAL_UNCOVERED_BRANCH_KEYS:
        try:
            output.print_md('## AUTODIM GEOMETRICALLY UNCERTIFIED TARGETS')
            for _uid in _CERT_FINAL_UNCOVERED_RUN_IDS[:120]:
                output.print_md('- Straight/logical leg element `{0}`'.format(_uid))
            for _bkey in _CERT_FINAL_UNCOVERED_BRANCH_KEYS[:120]:
                output.print_md('- Branch axis `{0}`'.format(_bkey))
        except Exception:
            pass

    msg += '\n\nGrid inventory: {0} view candidates, {1} host fallback candidates.'.format(
        len(globals().get('AUTODIM_GRID_INVENTORY', {}).get('view_grid_ids', [])),
        len(globals().get('AUTODIM_GRID_INVENTORY', {}).get('fallback_grid_ids', [])))
    _autodim_result = {
        'discipline': 'duct',
        'scope': str(globals().get('AUTODIM_SCOPE', 'view')),
        'review_version': 'duct-6.8-text-pockets',
        'created': int(counts.get('created', 0)),
        'input_count': int(len(ducts)),
        'existing_direct_verified': int(existing_direct_used),
        'raw_targets': int(recovery_stats.get('raw_straights_total', 0)),
        'raw_uncovered': int(recovery_stats.get('raw_straights_uncovered', 0)),
        'raw_uncovered_ids': list(recovery_stats.get('raw_uncovered_ids', [])),
        'branch_uncovered': int(_CERTIFICATION_STATS.get('final_uncovered_branches', 0)),
        'cert_required': int(_CERTIFICATION_STATS.get('final_required', 0)),
        'certified_targets': int(_CERTIFICATION_STATS.get('final_certified', 0)),
        'uncertified_runs': int(_CERTIFICATION_STATS.get('final_uncovered_runs', 0)),
        'uncertified_branches': int(_CERTIFICATION_STATS.get('final_uncovered_branches', 0)),
        'false_coverage_rejected': int(_CERTIFICATION_STATS.get('false_coverage_rejected', 0)),
        'blocked': int(counts.get('blocked', 0)),
        'failed': int(counts.get('failed', 0)),
        'runtime': float(elapsed),
        'attempt_counts': dict(counts),
        'placement_stats': dict(placement_stats),
        'recovery_stats': dict(recovery_stats),
        'stability_stats': dict(_STABILITY_STATS),
        'lookup_error_count': len(globals().get('AUTODIM_LOOKUP_ERRORS', [])),
        'failures': [{'source_id': int(source), 'reason': str(reason)} for source, reason in failures],
        'message': msg,
    }
    try:
        _audit = _build_run_audit(resolved, pre_no_grid, final_survivors, _autodim_result)
        _audit_path = _write_run_audit(_audit)
        _autodim_result['audit_path'] = _audit_path
        msg += '\n\nTarget audit JSON: {0}'.format(_audit_path)
        try:
            output.print_md('## DUCT AUTODIM target audit')
            output.print_md('Saved JSON: `{0}`'.format(_audit_path))
        except Exception:
            pass
    except Exception as _audit_error:
        _autodim_result['audit_error'] = str(_audit_error)
        msg += '\n\nTarget audit JSON could not be saved: {0}'.format(_audit_error)
    _autodim_result['message'] = msg
    globals()['AUTODIM_LAST_RESULT'] = _autodim_result
    if not bool(globals().get('AUTODIM_SUPPRESS_RESULT_DIALOG', False)):
        forms.alert(msg, title='DUCT AUTODIM')
    return _autodim_result


if __name__ == '__main__':
    main()
