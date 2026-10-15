# -*- coding: utf-8 -*-
"""
FAB REF CLASSIFIER v0.2 - ROBMEPTOOLS

Diagnostic bridge between FAB REF PROBE and production DUCT/PIPE AUTODIM.

Purpose
-------
Classify *which* valid MEP FabricationPart geometric reference corresponds to:
- ROUND duct / FAB pipe: connector-derived CENTERLINE
- RECTANGULAR / OVAL duct: the plan SIDE EDGE nearest the chosen grid

The command does not leave any dimensions in the model. Production-reference
candidates are verified with NewDimension inside rollback SubTransactions and
the parent Transaction is rolled back.

Designed for Revit 2025+ / pyRevit / IronPython-friendly execution.
"""

import os
import math
import time
from datetime import datetime

from pyrevit import revit, DB, UI, forms, script

uidoc = revit.uidoc
doc = revit.doc
view = doc.ActiveView
output = script.get_output()

MAX_PARTS = 12
PARALLEL_TOL_DEG = 7.0
CENTER_TOL_FT = 0.02       # ~1/4 in plan/model; only used to identify near-center refs
SIDE_MIN_OFFSET_FT = 0.02  # exclude near-center refs from rectangular/oval side selection
TRIAL_HALF_LENGTH_FT = 30.0
MAX_ALTERNATES = 8


def eid_int(eid):
    try:
        return int(eid.Value)
    except Exception:
        return int(eid.IntegerValue)


def safe_str(v):
    try:
        return str(v)
    except Exception:
        return '<unprintable>'


def plan_vec(v):
    try:
        ln = math.sqrt(v.X * v.X + v.Y * v.Y)
        if ln < 1e-9:
            return None
        return DB.XYZ(v.X / ln, v.Y / ln, 0.0)
    except Exception:
        return None


def dot_xy(a, b):
    return a.X * b.X + a.Y * b.Y


def perp_xy(v):
    return DB.XYZ(-v.Y, v.X, 0.0)


def midpoint(a, b):
    return DB.XYZ((a.X + b.X) * 0.5,
                  (a.Y + b.Y) * 0.5,
                  (a.Z + b.Z) * 0.5)


def line_midpoint(line):
    return midpoint(line.GetEndPoint(0), line.GetEndPoint(1))


def view_z():
    try:
        if view.GenLevel is not None:
            return float(view.GenLevel.Elevation)
    except Exception:
        pass
    try:
        return float(view.Origin.Z)
    except Exception:
        return 0.0


def to_view_z(p):
    return DB.XYZ(float(p.X), float(p.Y), view_z())


def is_fabrication_part(elem):
    try:
        return isinstance(elem, DB.FabricationPart)
    except Exception:
        return False


def is_physical_connector_type(ct):
    try:
        return ct in (DB.ConnectorType.End, DB.ConnectorType.Curve, DB.ConnectorType.Physical)
    except Exception:
        return False


def get_connectors(elem):
    out = []
    try:
        for c in elem.ConnectorManager.Connectors:
            out.append(c)
        return out
    except Exception:
        pass
    try:
        mm = elem.MEPModel
        if mm is not None and mm.ConnectorManager is not None:
            for c in mm.ConnectorManager.Connectors:
                out.append(c)
    except Exception:
        pass
    return out


def physical_connectors(elem):
    out = []
    for c in get_connectors(elem):
        try:
            if is_physical_connector_type(c.ConnectorType):
                out.append(c)
        except Exception:
            pass
    return out


def connector_shape(elem):
    for c in physical_connectors(elem):
        try:
            return safe_str(c.Shape)
        except Exception:
            pass
    return 'unknown'


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
    best_d = -1.0
    for i in range(len(pts)):
        for j in range(i + 1, len(pts)):
            try:
                d = pts[i].DistanceTo(pts[j])
            except Exception:
                continue
            if d > best_d:
                best_d = d
                best = (pts[i], pts[j])
    if best is None or best_d <= 1e-6:
        return None
    try:
        return DB.Line.CreateBound(best[0], best[1])
    except Exception:
        return None


def strict_straight(elem):
    try:
        return bool(elem.IsAStraight())
    except Exception:
        pass
    try:
        m = getattr(elem, 'IsStraightSegment', None)
        if m is not None:
            return bool(m())
    except Exception:
        pass
    return False


def app_info():
    a = doc.Application
    vals = []
    for k in ('VersionNumber', 'VersionName', 'VersionBuild', 'SubVersionNumber'):
        try:
            vals.append('{0}={1}'.format(k, getattr(a, k)))
        except Exception:
            pass
    return ', '.join(vals)


def part_meta(part):
    vals = []
    for label, attr in (
        ('Category', None),
        ('DomainType', 'DomainType'),
        ('ServiceName', 'ServiceName'),
        ('ServiceAbbreviation', 'ServiceAbbreviation'),
        ('ProductName', 'ProductName'),
        ('ProductShortDescription', 'ProductShortDescription'),
        ('OverallSize', 'OverallSize'),
        ('Size', 'Size'),
        ('Slope', 'Slope'),
    ):
        try:
            if label == 'Category':
                val = part.Category.Name
            else:
                val = getattr(part, attr)
            vals.append('{0}={1}'.format(label, safe_str(val)))
        except Exception:
            pass
    return '; '.join(vals)


def collect_grids():
    out = []
    try:
        coll = DB.FilteredElementCollector(doc, view.Id).OfClass(DB.Grid).WhereElementIsNotElementType()
    except Exception:
        coll = DB.FilteredElementCollector(doc).OfClass(DB.Grid).WhereElementIsNotElementType()
    for g in coll:
        try:
            crv = g.Curve
            if not isinstance(crv, DB.Line):
                continue
            axis = plan_vec(crv.Direction)
            if axis is None:
                continue
            out.append({'element': g, 'line': crv, 'axis': axis, 'name': g.Name})
        except Exception:
            pass
    return out


def project_point_to_line(point, line):
    try:
        ir = line.Project(point)
        if ir is not None:
            return ir.XYZPoint
    except Exception:
        pass
    try:
        axis = plan_vec(line.Direction)
        if axis is None:
            return None
        o = line.Origin
        dx = point.X - o.X
        dy = point.Y - o.Y
        t = dx * axis.X + dy * axis.Y
        return DB.XYZ(o.X + axis.X*t, o.Y + axis.Y*t, point.Z)
    except Exception:
        return None


def point_line_distance_xy(point, line):
    q = project_point_to_line(point, line)
    if q is None:
        return 1e30
    return math.sqrt((point.X-q.X)**2 + (point.Y-q.Y)**2)


def nearest_grid(part, grids, selected_grid_id=None):
    if selected_grid_id is not None:
        for g in grids:
            try:
                if eid_int(g['element'].Id) == selected_grid_id:
                    return g, 'selected'
            except Exception:
                pass
    cl = fabrication_centerline(part)
    if cl is None:
        return None, 'no-centerline'
    axis = plan_vec(cl.Direction)
    mid = line_midpoint(cl)
    if axis is None:
        return None, 'no-axis'
    cos_tol = math.cos(math.radians(PARALLEL_TOL_DEG))
    preferred = []
    fallback = []
    for g in grids:
        try:
            d = point_line_distance_xy(mid, g['line'])
            fallback.append((d, g))
            if abs(dot_xy(axis, g['axis'])) >= cos_tol:
                preferred.append((d, g))
        except Exception:
            pass
    pool = preferred if preferred else fallback
    if not pool:
        return None, 'no-grid'
    pool.sort(key=lambda x: x[0])
    return pool[0][1], ('nearest-parallel' if preferred else 'nearest-any')


def stable_rep(ref):
    if ref is None:
        return None
    try:
        return ref.ConvertToStableRepresentation(doc)
    except Exception:
        return None


def ref_type(ref):
    if ref is None:
        return 'None'
    try:
        return safe_str(ref.ElementReferenceType)
    except Exception:
        return 'unknown'


def model_point(tr, p):
    try:
        return tr.OfPoint(p)
    except Exception:
        return p


def model_vector(tr, v):
    try:
        return tr.OfVector(v)
    except Exception:
        return v


def model_curve(tr, c):
    try:
        return c.CreateTransformed(tr)
    except Exception:
        return c


def reference_options():
    opt = DB.Options()
    opt.ComputeReferences = True
    opt.IncludeNonVisibleObjects = True
    try:
        opt.DetailLevel = DB.ViewDetailLevel.Fine
    except Exception:
        pass
    return opt


def relation_to_axis(curve, axis):
    if not isinstance(curve, DB.Line):
        return 'non-line'
    a = plan_vec(curve.Direction)
    if a is None:
        return 'non-plan-line'
    v = abs(dot_xy(a, axis))
    cos_tol = math.cos(math.radians(PARALLEL_TOL_DEG))
    if v >= cos_tol:
        return 'parallel-run'
    if v <= math.sin(math.radians(PARALLEL_TOL_DEG)):
        return 'perpendicular-run'
    return 'angled-run'


def signed_offset_from_center(witness, center_mid, run_normal):
    if witness is None:
        return None
    d = DB.XYZ(witness.X-center_mid.X, witness.Y-center_mid.Y, 0.0)
    return dot_xy(d, run_normal)


def grid_side_sign(center_mid, grid_line, run_normal):
    gp = project_point_to_line(center_mid, grid_line)
    if gp is None:
        return 0.0
    d = DB.XYZ(gp.X-center_mid.X, gp.Y-center_mid.Y, 0.0)
    s = dot_xy(d, run_normal)
    if abs(s) < 1e-8:
        return 0.0
    return 1.0 if s > 0 else -1.0


def candidate_key(ref, source):
    s = stable_rep(ref)
    if s:
        return s
    return '{0}:{1}'.format(source, ref_type(ref))


def add_candidate(records, seen, part, ref, source, kind, relation, witness, center_mid, run_normal, extra=None):
    if ref is None or witness is None:
        return
    k = candidate_key(ref, source)
    if k in seen:
        return
    seen.add(k)
    off = signed_offset_from_center(witness, center_mid, run_normal)
    records.append({
        'ref': ref,
        'source': source,
        'kind': kind,
        'relation': relation,
        'witness': witness,
        'offset': off,
        'abs_offset': abs(off) if off is not None else 1e30,
        'stable': stable_rep(ref),
        'ref_type': ref_type(ref),
        'extra': extra or '',
    })


def harvest_solid(solid, tr, prefix, part, run_axis, center_mid, run_normal, records, seen):
    try:
        faces = list(solid.Faces)
    except Exception:
        faces = []
    for fi, face in enumerate(faces):
        # Face candidate. Use planar-face origin as witness.
        if isinstance(face, DB.PlanarFace):
            try:
                fw = model_point(tr, face.Origin)
                n = plan_vec(model_vector(tr, face.FaceNormal))
                frel = 'horizontal-face' if n is None else ('side-face' if abs(dot_xy(n, run_normal)) >= math.cos(math.radians(PARALLEL_TOL_DEG)) else 'other-face')
                add_candidate(records, seen, part, face.Reference,
                              '{0}.face[{1}]'.format(prefix, fi), 'face', frel,
                              fw, center_mid, run_normal)
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
                    mc = model_curve(tr, raw)
                    if isinstance(mc, DB.Line):
                        witness = line_midpoint(mc)
                    else:
                        witness = model_point(tr, raw.Evaluate(0.5, True))
                    rel = relation_to_axis(mc, run_axis)
                    add_candidate(records, seen, part, edge.Reference,
                                  '{0}.face[{1}].edge[{2}]'.format(prefix, fi, ei),
                                  'edge', rel, witness, center_mid, run_normal)
                    # Endpoints are useful fallbacks if edge refs are rejected.
                    for ep_idx in (0, 1):
                        try:
                            epr = edge.GetEndPointReference(ep_idx)
                            ep = model_point(tr, raw.GetEndPoint(ep_idx))
                            add_candidate(records, seen, part, epr,
                                          '{0}.face[{1}].edge[{2}].endpoint[{3}]'.format(prefix, fi, ei, ep_idx),
                                          'endpoint', 'point', ep, center_mid, run_normal)
                        except Exception:
                            pass
                except Exception:
                    pass
                ei += 1


def harvest_geometry(geo, parent_tr, prefix, part, run_axis, center_mid, run_normal, records, seen):
    if geo is None:
        return
    gi = 0
    si = 0
    ci = 0
    for item in geo:
        try:
            if isinstance(item, DB.Solid):
                if item.Faces.Size > 0:
                    harvest_solid(item, parent_tr, '{0}.solid[{1}]'.format(prefix, si), part,
                                  run_axis, center_mid, run_normal, records, seen)
                    si += 1
            elif isinstance(item, DB.GeometryInstance):
                try:
                    child_tr = parent_tr.Multiply(item.Transform)
                except Exception:
                    child_tr = item.Transform
                try:
                    sym = item.GetSymbolGeometry()
                    harvest_geometry(sym, child_tr, '{0}.instance[{1}].symbol'.format(prefix, gi), part,
                                     run_axis, center_mid, run_normal, records, seen)
                except Exception:
                    pass
                gi += 1
            elif isinstance(item, DB.Curve):
                try:
                    mc = model_curve(parent_tr, item)
                    if isinstance(mc, DB.Line):
                        witness = line_midpoint(mc)
                    else:
                        witness = model_point(parent_tr, item.Evaluate(0.5, True))
                    add_candidate(records, seen, part, getattr(item, 'Reference', None),
                                  '{0}.curve[{1}]'.format(prefix, ci), 'curve', relation_to_axis(mc, run_axis),
                                  witness, center_mid, run_normal,
                                  'geom={0}'.format(item.GetType().Name))
                    ci += 1
                except Exception:
                    pass
        except Exception:
            pass


def harvest_candidates(part, cl):
    run_axis = plan_vec(cl.Direction)
    if run_axis is None:
        return []
    center_mid = line_midpoint(cl)
    run_normal = perp_xy(run_axis)
    records = []
    seen = set()
    try:
        geo = part.get_Geometry(reference_options())
        harvest_geometry(geo, DB.Transform.Identity, 'model-geometry', part,
                         run_axis, center_mid, run_normal, records, seen)
    except Exception:
        pass
    return records


def dimension_line(grid_data, witness):
    gaxis = grid_data['axis']
    normal = perp_xy(gaxis)
    gp = project_point_to_line(witness, grid_data['line'])
    if gp is None:
        return None
    gp = to_view_z(gp)
    wp = to_view_z(witness)
    mid = midpoint(gp, wp)
    try:
        return DB.Line.CreateBound(mid - normal.Multiply(TRIAL_HALF_LENGTH_FT),
                                   mid + normal.Multiply(TRIAL_HALF_LENGTH_FT))
    except Exception:
        return None


def compact_error(ex):
    try:
        t = safe_str(ex).replace('\r', ' ').replace('\n', ' ')
        while '  ' in t:
            t = t.replace('  ', ' ')
        return t[:240]
    except Exception:
        return 'unknown error'


def trial_dimension(grid_data, candidate):
    try:
        gref = DB.Reference(grid_data['element'])
    except Exception as ex:
        return False, 'grid-ref failed: {0}'.format(compact_error(ex))
    dl = dimension_line(grid_data, candidate['witness'])
    if dl is None:
        return False, 'no dimension line'
    arr = DB.ReferenceArray()
    arr.Append(gref)
    arr.Append(candidate['ref'])
    st = DB.SubTransaction(doc)
    st.Start()
    try:
        dim = doc.Create.NewDimension(view, dl, arr)
        if dim is None:
            raise RuntimeError('NewDimension returned None')
        try:
            doc.Regenerate()
        except Exception:
            pass
        try:
            value = dim.Value
            msg = 'PASS value={0}'.format(value)
        except Exception:
            msg = 'PASS'
        st.RollBack()
        return True, msg
    except Exception as ex:
        try:
            st.RollBack()
        except Exception:
            pass
        return False, compact_error(ex)


def candidate_distance_to_grid(cand, grid_data):
    return point_line_distance_xy(cand['witness'], grid_data['line'])


def classify_round(cands, grid_data):
    # Production preference: REAL symbol/model curve on connector centerline.
    parallel = [c for c in cands if c['kind'] == 'curve' and c['relation'] == 'parallel-run']
    parallel.sort(key=lambda c: (c['abs_offset'], candidate_distance_to_grid(c, grid_data), c['source']))
    primary = parallel[0] if parallel else None
    # Endpoint fallback closest to centerline if no line exists.
    alternates = list(parallel[1:MAX_ALTERNATES+1])
    if primary is None:
        pts = [c for c in cands if c['kind'] == 'endpoint']
        pts.sort(key=lambda c: (c['abs_offset'], candidate_distance_to_grid(c, grid_data), c['source']))
        if pts:
            primary = pts[0]
            alternates = pts[1:MAX_ALTERNATES+1]
    return primary, alternates


def classify_rect_or_oval(cands, grid_data, cl):
    run_axis = plan_vec(cl.Direction)
    center_mid = line_midpoint(cl)
    run_normal = perp_xy(run_axis)
    side_sign = grid_side_sign(center_mid, grid_data['line'], run_normal)

    # Edges/curves parallel to run are the cleanest side-edge refs. Exclude near-center refs.
    pool = [c for c in cands
            if c['kind'] in ('edge', 'curve')
            and c['relation'] == 'parallel-run'
            and c['abs_offset'] >= SIDE_MIN_OFFSET_FT]
    if side_sign != 0:
        same_side = [c for c in pool if c['offset'] * side_sign > 0]
        if same_side:
            pool = same_side
    # Prefer the outermost same-side line (actual side) and then nearest to grid.
    pool.sort(key=lambda c: (-c['abs_offset'], candidate_distance_to_grid(c, grid_data), c['source']))
    primary = pool[0] if pool else None
    alternates = pool[1:MAX_ALTERNATES+1]

    # If no line/edge survives, use side faces.
    if primary is None:
        faces = [c for c in cands if c['kind'] == 'face' and c['relation'] == 'side-face' and c['abs_offset'] >= SIDE_MIN_OFFSET_FT]
        if side_sign != 0:
            sf = [c for c in faces if c['offset'] * side_sign > 0]
            if sf:
                faces = sf
        faces.sort(key=lambda c: (-c['abs_offset'], candidate_distance_to_grid(c, grid_data), c['source']))
        if faces:
            primary = faces[0]
            alternates = faces[1:MAX_ALTERNATES+1]

    # Endpoint rescue: choose point on outer near side.
    if primary is None:
        pts = [c for c in cands if c['kind'] == 'endpoint' and c['abs_offset'] >= SIDE_MIN_OFFSET_FT]
        if side_sign != 0:
            sp = [c for c in pts if c['offset'] * side_sign > 0]
            if sp:
                pts = sp
        pts.sort(key=lambda c: (-c['abs_offset'], candidate_distance_to_grid(c, grid_data), c['source']))
        if pts:
            primary = pts[0]
            alternates = pts[1:MAX_ALTERNATES+1]
    return primary, alternates


def classify_part(part, grid_data):
    cl = fabrication_centerline(part)
    if cl is None:
        return None
    cands = harvest_candidates(part, cl)
    shape = connector_shape(part).lower()
    category = ''
    try:
        category = part.Category.Name.lower()
    except Exception:
        pass
    is_pipe = 'pipe' in category
    is_round = ('round' in shape) or is_pipe
    if is_round:
        primary, alts = classify_round(cands, grid_data)
        mode = 'CENTER'
    else:
        primary, alts = classify_rect_or_oval(cands, grid_data, cl)
        mode = 'NEAR_EDGE'
    return {
        'centerline': cl,
        'candidates': cands,
        'primary': primary,
        'alternates': alts,
        'mode': mode,
        'shape': connector_shape(part),
        'is_pipe': is_pipe,
    }


def selected_parts_and_grid():
    parts = []
    sel_grid = None
    try:
        ids = list(uidoc.Selection.GetElementIds())
    except Exception:
        ids = []
    for eid in ids:
        el = doc.GetElement(eid)
        if el is None:
            continue
        if isinstance(el, DB.Grid):
            sel_grid = el
        elif is_fabrication_part(el):
            parts.append(el)
    if not parts:
        class FabFilter(UI.Selection.ISelectionFilter):
            def AllowElement(self, elem):
                return is_fabrication_part(elem)
            def AllowReference(self, reference, point):
                return False
        try:
            picks = uidoc.Selection.PickObjects(UI.Selection.ObjectType.Element, FabFilter(),
                                                'Pick MEP Fabrication straight duct/pipe parts')
            for p in picks:
                el = doc.GetElement(p.ElementId)
                if el is not None:
                    parts.append(el)
        except Exception:
            return [], sel_grid
    out = []
    seen = set()
    for p in parts:
        try:
            pid = eid_int(p.Id)
        except Exception:
            continue
        if pid in seen:
            continue
        seen.add(pid)
        out.append(p)
        if len(out) >= MAX_PARTS:
            break
    return out, sel_grid


def report_path():
    name = 'FAB_REF_CLASSIFIER_{0}.txt'.format(datetime.now().strftime('%Y%m%d_%H%M%S'))
    try:
        from System import Environment
        desktop = Environment.GetFolderPath(Environment.SpecialFolder.Desktop)
        if desktop:
            return os.path.join(desktop, name)
    except Exception:
        pass
    return os.path.join(os.environ.get('TEMP', os.getcwd()), name)


def fmt_offset(ft):
    if ft is None:
        return '?'
    return '{0:.5f}ft ({1:.3f}in)'.format(ft, ft * 12.0)


def run():
    if not isinstance(view, DB.ViewPlan):
        forms.alert('FAB REF CLASSIFIER runs in a plan view.', title='FAB REF CLASSIFIER')
        return
    parts, selected_grid = selected_parts_and_grid()
    if not parts:
        return
    grids = collect_grids()
    if not grids:
        forms.alert('No straight host-model grids were found.', title='FAB REF CLASSIFIER')
        return
    selected_grid_id = eid_int(selected_grid.Id) if selected_grid is not None else None

    started = time.time()
    lines = []
    verified = 0
    verified_center = 0
    verified_edge = 0
    skipped_nonstraight = 0
    no_candidate = 0
    failed_primary = 0
    alt_rescued = 0

    lines.append('ROBMEPTOOLS FAB REF CLASSIFIER v0.2')
    lines.append('Revit: {0}'.format(app_info()))
    lines.append('View: {0} | Scale 1:{1}'.format(view.Name, view.Scale))
    lines.append('Parts selected: {0}'.format(len(parts)))
    lines.append('')

    tx = DB.Transaction(doc, 'FAB REF CLASSIFIER - ROLLBACK')
    tx.Start()
    try:
        for i, part in enumerate(parts):
            pid = eid_int(part.Id)
            lines.append('=' * 96)
            lines.append('PART {0}/{1} | ElementId {2}'.format(i+1, len(parts), pid))
            lines.append(part_meta(part))
            lines.append('Connector shape={0}; IsAStraight={1}'.format(connector_shape(part), strict_straight(part)))
            if not strict_straight(part):
                skipped_nonstraight += 1
                lines.append('CLASSIFICATION: SKIP_NONSTRAIGHT')
                continue

            gd, gmode = nearest_grid(part, grids, selected_grid_id)
            if gd is None:
                no_candidate += 1
                lines.append('GRID: NONE ({0})'.format(gmode))
                continue
            lines.append('GRID: {0} | ElementId {1} | mode={2}'.format(gd['name'], eid_int(gd['element'].Id), gmode))

            rec = classify_part(part, gd)
            if rec is None or rec['primary'] is None:
                no_candidate += 1
                lines.append('CLASSIFICATION: NO_PRODUCTION_REFERENCE')
                continue

            lines.append('TARGET MODE: {0}'.format(rec['mode']))
            lines.append('Harvested real-reference candidates: {0}'.format(len(rec['candidates'])))
            p = rec['primary']
            lines.append('PRIMARY: {0}'.format(p['source']))
            lines.append('  kind={0}; relation={1}; refType={2}'.format(p['kind'], p['relation'], p['ref_type']))
            lines.append('  center-offset={0}; grid-distance={1:.5f}ft'.format(fmt_offset(p['offset']), candidate_distance_to_grid(p, gd)))
            lines.append('  stable={0}'.format(p['stable'] or '<none>'))

            ok, msg = trial_dimension(gd, p)
            lines.append('  TRIAL PRIMARY: {0} | {1}'.format('PASS' if ok else 'FAIL', msg))
            winner = p if ok else None
            if not ok:
                failed_primary += 1
                for ai, a in enumerate(rec['alternates']):
                    aok, amsg = trial_dimension(gd, a)
                    lines.append('ALT {0}: {1}'.format(ai+1, a['source']))
                    lines.append('  kind={0}; relation={1}; refType={2}; center-offset={3}; grid-distance={4:.5f}ft'.format(
                        a['kind'], a['relation'], a['ref_type'], fmt_offset(a['offset']), candidate_distance_to_grid(a, gd)))
                    lines.append('  TRIAL: {0} | {1}'.format('PASS' if aok else 'FAIL', amsg))
                    if aok:
                        winner = a
                        alt_rescued += 1
                        break

            if winner is not None:
                verified += 1
                if rec['mode'] == 'CENTER':
                    verified_center += 1
                else:
                    verified_edge += 1
                lines.append('PRODUCTION WINNER: {0}'.format(winner['source']))
                lines.append('  CLASS={0}; center-offset={1}; grid-distance={2:.5f}ft'.format(
                    rec['mode'], fmt_offset(winner['offset']), candidate_distance_to_grid(winner, gd)))
            else:
                lines.append('PRODUCTION WINNER: NONE')

            # Compact ranking table for geometry sanity-checking.
            ranked = list(rec['candidates'])
            ranked.sort(key=lambda c: (c['abs_offset'], c['source']))
            lines.append('NEAREST-TO-CENTER REAL REFERENCES (first 8):')
            for c in ranked[:8]:
                lines.append('  {0} | {1}/{2} | off={3}'.format(c['source'], c['kind'], c['relation'], fmt_offset(c['offset'])))
    finally:
        try:
            tx.RollBack()
        except Exception:
            pass

    elapsed = time.time() - started
    lines.append('')
    lines.append('=' * 96)
    lines.append('SUMMARY')
    lines.append('Elapsed: {0:.2f} sec'.format(elapsed))
    lines.append('Verified production references: {0}'.format(verified))
    lines.append('  CENTER verified: {0}'.format(verified_center))
    lines.append('  NEAR_EDGE verified: {0}'.format(verified_edge))
    lines.append('Non-straights skipped: {0}'.format(skipped_nonstraight))
    lines.append('No production reference/grid: {0}'.format(no_candidate))
    lines.append('Primary trial failures: {0}'.format(failed_primary))
    lines.append('Alternate references rescued: {0}'.format(alt_rescued))
    lines.append('Parent transaction rolled back; no classifier dimensions were retained.')

    path = report_path()
    try:
        with open(path, 'w') as fp:
            fp.write('\n'.join(lines))
    except Exception as ex:
        path = '<report write failed: {0}>'.format(ex)

    output.print_md('# FAB REF CLASSIFIER v0.2')
    output.print_md('**Verified production references:** `{0}` / `{1}` selected'.format(verified, len(parts)))
    output.print_md('**Center refs:** `{0}` | **Near-edge refs:** `{1}`'.format(verified_center, verified_edge))
    output.print_md('**Non-straights skipped:** `{0}` | **Alternate rescues:** `{1}`'.format(skipped_nonstraight, alt_rescued))
    output.print_md('**Runtime:** `{0:.2f} sec`'.format(elapsed))
    output.print_md('**Report:** `{0}`'.format(path))

    forms.alert(
        'FAB REF CLASSIFIER finished.\n\n'
        'Parts selected: {0}\n'
        'Verified production references: {1}\n'
        '  Center: {2}\n'
        '  Near edge: {3}\n'
        'Non-straights skipped: {4}\n'
        'Alternate rescues: {5}\n'
        'Runtime: {6:.1f} sec\n\n'
        'Nothing was changed in the model; all trial dimensions were rolled back.\n\n'
        'Report:\n{7}'.format(len(parts), verified, verified_center, verified_edge,
                              skipped_nonstraight, alt_rescued, elapsed, path),
        title='FAB REF CLASSIFIER'
    )


if __name__ == '__main__':
    run()
