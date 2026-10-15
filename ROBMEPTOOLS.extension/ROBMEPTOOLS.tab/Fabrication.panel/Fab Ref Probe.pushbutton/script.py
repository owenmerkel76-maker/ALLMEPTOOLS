# -*- coding: utf-8 -*-
"""
FAB REF PROBE - ROBMEPTOOLS diagnostic pushbutton

Purpose
-------
Safely discover which Revit geometric references from MEP Fabrication straights
can actually create a project linear dimension to a host-model Grid.

The command is intentionally diagnostic. It creates trial dimensions only inside
rollback subtransactions and rolls back the parent transaction, so the model is
left unchanged.

Workflow
--------
1. In a plan view, preselect one or more MEP Fabrication duct/pipe straights.
   A selected host-model Grid is optional; otherwise the probe picks the nearest
   parallel straight grid for each part (or nearest grid when no parallel exists).
2. Run FAB REF PROBE.
3. Review the pyRevit output and the text report written to the Desktop.

The report compares:
- Grid element reference vs Grid.Curve reference (when available)
- Element-level FabricationPart reference
- Direct solid edge / face references
- GeometryInstance SymbolGeometry references (real geometry)
- GeometryInstance InstanceGeometry references (copy; expected to be weak/bad)
- Edge endpoint references
- Stable-representation round trips
- Actual NewDimension acceptance inside rollback subtransactions

Designed for Revit 2025+ and IronPython-friendly pyRevit execution.
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

MAX_PARTS = 8
MAX_REFERENCE_CANDIDATES = 28
PARALLEL_TOL_DEG = 8.0
TRIAL_HALF_LENGTH_FT = 20.0


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


def safe_str(v):
    try:
        return str(v)
    except Exception:
        return '<unprintable>'


def app_info():
    app = doc.Application
    out = []
    for label, attr in (
        ('VersionNumber', 'VersionNumber'),
        ('VersionName', 'VersionName'),
        ('VersionBuild', 'VersionBuild'),
        ('SubVersionNumber', 'SubVersionNumber'),
    ):
        try:
            out.append('{0}={1}'.format(label, getattr(app, attr)))
        except Exception:
            pass
    return ', '.join(out)


def is_fabrication_part(elem):
    try:
        return isinstance(elem, DB.FabricationPart)
    except Exception:
        return False


def fab_domain(elem):
    try:
        return safe_str(elem.DomainType)
    except Exception:
        return 'unknown'


def fab_category(elem):
    try:
        return elem.Category.Name
    except Exception:
        return 'unknown'


def is_fab_straight(elem):
    if not is_fabrication_part(elem):
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
    # Diagnostic tool intentionally allows a two-port fabrication part through
    # even when straight flags are unreliable, but labels it accordingly.
    try:
        return len(physical_connectors(elem)) >= 2
    except Exception:
        return False


def is_physical_connector_type(ct):
    try:
        return ct in (DB.ConnectorType.End, DB.ConnectorType.Curve, DB.ConnectorType.Physical)
    except Exception:
        return False


def get_connectors(elem):
    result = []
    try:
        for c in elem.ConnectorManager.Connectors:
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


def collect_grids():
    result = []
    try:
        coll = DB.FilteredElementCollector(doc, view.Id).OfClass(DB.Grid).WhereElementIsNotElementType()
    except Exception:
        coll = DB.FilteredElementCollector(doc).OfClass(DB.Grid).WhereElementIsNotElementType()
    for grid in coll:
        try:
            crv = grid.Curve
            if not isinstance(crv, DB.Line):
                continue
            axis = plan_vec(crv.Direction)
            if axis is None:
                continue
            result.append({'element': grid, 'line': crv, 'axis': axis, 'name': grid.Name})
        except Exception:
            continue
    return result


def project_point_to_grid(point, grid_line):
    try:
        q = grid_line.Project(point)
        if q is not None:
            return q.XYZPoint
    except Exception:
        pass
    axis = plan_vec(grid_line.Direction)
    if axis is None:
        return None
    try:
        origin = grid_line.Origin
    except Exception:
        origin = grid_line.GetEndPoint(0)
    dx = point.X - origin.X
    dy = point.Y - origin.Y
    t = dx * axis.X + dy * axis.Y
    return DB.XYZ(origin.X + axis.X * t, origin.Y + axis.Y * t, point.Z)


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
            gp = project_point_to_grid(mid, g['line'])
            if gp is None:
                continue
            d = math.sqrt((gp.X-mid.X)**2 + (gp.Y-mid.Y)**2)
            rec = (d, g)
            fallback.append(rec)
            if abs(dot_xy(axis, g['axis'])) >= cos_tol:
                preferred.append(rec)
        except Exception:
            pass
    pool = preferred if preferred else fallback
    if not pool:
        return None, 'no-grid'
    pool.sort(key=lambda x: x[0])
    return pool[0][1], ('nearest-parallel' if preferred else 'nearest-any')


def ref_type(ref):
    if ref is None:
        return 'None'
    try:
        return safe_str(ref.ElementReferenceType)
    except Exception:
        return 'unknown'


def ref_element_id(ref):
    try:
        return eid_int(ref.ElementId)
    except Exception:
        return None


def stable_rep(ref):
    if ref is None:
        return None
    try:
        return ref.ConvertToStableRepresentation(doc)
    except Exception:
        return None


def roundtrip_reference(ref):
    stable = stable_rep(ref)
    if not stable:
        return None, 'no-stable'
    try:
        parsed = DB.Reference.ParseFromStableRepresentation(doc, stable)
        return parsed, 'ok'
    except Exception as ex:
        return None, 'parse-failed: {0}'.format(ex)


def geometry_object_type(owner, ref):
    if owner is None or ref is None:
        return 'None'
    try:
        obj = owner.GetGeometryObjectFromReference(ref)
        if obj is None:
            return 'None'
        return obj.GetType().Name
    except Exception as ex:
        return 'error:{0}'.format(ex)


def reference_options(use_view=False):
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


def candidate_key(ref, source, witness):
    stable = stable_rep(ref)
    if stable:
        return 'S:' + stable
    rid = ref_element_id(ref)
    wt = ''
    try:
        wt = '{0:.5f},{1:.5f},{2:.5f}'.format(witness.X, witness.Y, witness.Z)
    except Exception:
        pass
    return 'F:{0}:{1}:{2}:{3}'.format(source, rid, ref_type(ref), wt)


def add_candidate(records, seen, ref, source, witness, geometry_desc, relation='unknown'):
    if ref is None:
        return
    key = candidate_key(ref, source, witness)
    if key in seen:
        return
    seen.add(key)
    parsed, parse_status = roundtrip_reference(ref)
    records.append({
        'ref': ref,
        'source': source,
        'witness': witness,
        'geometry': geometry_desc,
        'ref_type': ref_type(ref),
        'element_id': ref_element_id(ref),
        'stable': stable_rep(ref),
        'parsed_ref': parsed,
        'parse_status': parse_status,
        'relation': relation,
    })


def edge_relation(edge_curve, grid_axis):
    try:
        if isinstance(edge_curve, DB.Line):
            a = plan_vec(edge_curve.Direction)
            if a is None:
                return 'non-plan-line'
            val = abs(dot_xy(a, grid_axis))
            if val >= math.cos(math.radians(PARALLEL_TOL_DEG)):
                return 'parallel-grid'
            if val <= math.sin(math.radians(PARALLEL_TOL_DEG)):
                return 'perpendicular-grid'
            return 'angled-grid'
    except Exception:
        pass
    return 'non-line'


def face_relation(face, tr, grid_axis):
    if not isinstance(face, DB.PlanarFace):
        return 'non-planar-face'
    try:
        n = model_vector(tr, face.FaceNormal).Normalize()
        nxy = plan_vec(n)
        if nxy is None:
            return 'horizontal-face'
        # A vertical face is parallel to a grid line when its normal is
        # perpendicular to the grid axis.
        val = abs(dot_xy(nxy, grid_axis))
        if val <= math.sin(math.radians(PARALLEL_TOL_DEG)):
            return 'face-parallel-grid'
        if val >= math.cos(math.radians(PARALLEL_TOL_DEG)):
            return 'face-normal-grid'
        return 'face-angled-grid'
    except Exception:
        return 'face-unknown'


def harvest_solid(solid, tr, source_prefix, grid_axis, records, seen):
    try:
        faces = list(solid.Faces)
    except Exception:
        faces = []
    for fi, face in enumerate(faces):
        try:
            fw = model_point(tr, face.Origin) if isinstance(face, DB.PlanarFace) else None
        except Exception:
            fw = None
        add_candidate(records, seen, getattr(face, 'Reference', None),
                      '{0}.face[{1}]'.format(source_prefix, fi), fw,
                      face.GetType().Name, face_relation(face, tr, grid_axis))
        try:
            loops = face.EdgeLoops
        except Exception:
            loops = []
        edge_index = 0
        for loop in loops:
            for edge in loop:
                try:
                    raw = edge.AsCurve()
                    crv = model_curve(tr, raw)
                    witness = line_midpoint(crv) if isinstance(crv, DB.Line) else model_point(tr, raw.Evaluate(0.5, True))
                except Exception:
                    raw = None
                    crv = None
                    witness = None
                add_candidate(records, seen, getattr(edge, 'Reference', None),
                              '{0}.face[{1}].edge[{2}]'.format(source_prefix, fi, edge_index),
                              witness, 'Edge/{0}'.format(crv.GetType().Name if crv is not None else 'unknown'),
                              edge_relation(crv, grid_axis) if crv is not None else 'unknown')
                if raw is not None:
                    for ei in (0, 1):
                        try:
                            er = edge.GetEndPointReference(ei)
                            ep = model_point(tr, raw.GetEndPoint(ei))
                            add_candidate(records, seen, er,
                                          '{0}.face[{1}].edge[{2}].endpoint[{3}]'.format(source_prefix, fi, edge_index, ei),
                                          ep, 'EdgeEndpoint', 'point')
                        except Exception:
                            pass
                edge_index += 1


def harvest_geometry(geo, parent_tr, source_prefix, grid_axis, records, seen, instance_is_copy=False):
    if geo is None:
        return
    gi_idx = 0
    solid_idx = 0
    curve_idx = 0
    for item in geo:
        try:
            if isinstance(item, DB.Solid):
                if item.Faces.Size <= 0:
                    continue
                harvest_solid(item, parent_tr, '{0}.solid[{1}]'.format(source_prefix, solid_idx),
                              grid_axis, records, seen)
                solid_idx += 1
            elif isinstance(item, DB.GeometryInstance):
                inst_source = '{0}.instance[{1}]'.format(source_prefix, gi_idx)
                # Instance reference itself can be informative.
                try:
                    iw = model_point(parent_tr, item.Transform.Origin)
                except Exception:
                    iw = None
                add_candidate(records, seen, getattr(item, 'Reference', None),
                              inst_source + '.instance-ref', iw, 'GeometryInstance', 'instance')

                # REAL symbol geometry: references may be dimensionable.
                try:
                    child_tr = parent_tr.Multiply(item.Transform)
                except Exception:
                    child_tr = item.Transform
                try:
                    sym = item.GetSymbolGeometry()
                    harvest_geometry(sym, child_tr, inst_source + '.symbol', grid_axis, records, seen, False)
                except Exception:
                    pass

                # COPIED instance geometry: diagnostic comparison only.
                try:
                    inst_geo = item.GetInstanceGeometry()
                    harvest_geometry(inst_geo, DB.Transform.Identity, inst_source + '.instance-copy',
                                     grid_axis, records, seen, True)
                except Exception:
                    pass
                gi_idx += 1
            elif isinstance(item, DB.Curve):
                try:
                    mc = model_curve(parent_tr, item)
                    w = line_midpoint(mc) if isinstance(mc, DB.Line) else model_point(parent_tr, item.Evaluate(0.5, True))
                except Exception:
                    mc = item
                    w = None
                add_candidate(records, seen, getattr(item, 'Reference', None),
                              '{0}.curve[{1}]'.format(source_prefix, curve_idx), w,
                              item.GetType().Name, edge_relation(mc, grid_axis))
                curve_idx += 1
        except Exception:
            continue


def harvest_candidates(part, grid_data):
    records = []
    seen = set()

    # Element-level reference is important for round-center experiments even
    # though it reports REFERENCE_TYPE_NONE.
    try:
        add_candidate(records, seen, DB.Reference(part), 'element-reference',
                      line_midpoint(fabrication_centerline(part)), 'FabricationPart', 'element')
    except Exception:
        pass

    for use_view in (False, True):
        try:
            geo = part.get_Geometry(reference_options(use_view))
            harvest_geometry(geo, DB.Transform.Identity,
                             ('view-geometry' if use_view else 'model-geometry'),
                             grid_data['axis'], records, seen)
        except Exception:
            pass

    # Prioritize references that are plausible for a dimension to the chosen grid.
    priority = {
        'parallel-grid': 0,
        'face-parallel-grid': 1,
        'point': 2,
        'element': 3,
        'instance': 4,
        'angled-grid': 5,
        'face-angled-grid': 6,
        'perpendicular-grid': 7,
        'face-normal-grid': 8,
        'horizontal-face': 9,
    }
    records.sort(key=lambda r: (priority.get(r['relation'], 20),
                                1 if '.instance-copy' in r['source'] else 0,
                                r['source']))
    return records[:MAX_REFERENCE_CANDIDATES]


def grid_reference_candidates(grid):
    result = []
    try:
        result.append(('grid-element', DB.Reference(grid)))
    except Exception:
        pass
    try:
        if grid.Curve is not None and grid.Curve.Reference is not None:
            result.append(('grid-curve', grid.Curve.Reference))
    except Exception:
        pass
    # Dedupe by stable representation/type.
    final = []
    seen = set()
    for name, ref in result:
        k = stable_rep(ref) or '{0}:{1}'.format(ref_type(ref), ref_element_id(ref))
        if k in seen:
            continue
        seen.add(k)
        final.append((name, ref))
    return final


def make_trial_line(part, grid_data, witness):
    cl = fabrication_centerline(part)
    if cl is None:
        return None
    if witness is None:
        witness = line_midpoint(cl)
    witness = to_view_z(witness)
    grid_axis = grid_data['axis']
    normal = perp_xy(grid_axis)
    gp = project_point_to_grid(witness, grid_data['line'])
    if gp is None:
        gp = grid_data['line'].Origin
    gp = to_view_z(gp)
    mid = midpoint(gp, witness)
    # Dimension line runs normal to the grid. Use a long line so it spans both
    # references even for point/surface trials.
    p0 = mid - normal.Multiply(TRIAL_HALF_LENGTH_FT)
    p1 = mid + normal.Multiply(TRIAL_HALF_LENGTH_FT)
    try:
        return DB.Line.CreateBound(p0, p1)
    except Exception:
        return None


def compact_error(ex):
    try:
        text = safe_str(ex).replace('\r', ' ').replace('\n', ' ')
        while '  ' in text:
            text = text.replace('  ', ' ')
        return text[:260]
    except Exception:
        return 'unknown error'


def trial_dimension(part, grid_data, grid_ref, duct_ref, witness):
    line = make_trial_line(part, grid_data, witness)
    if line is None:
        return False, 'no trial line'
    refs = DB.ReferenceArray()
    refs.Append(grid_ref)
    refs.Append(duct_ref)
    st = DB.SubTransaction(doc)
    st.Start()
    try:
        dim = doc.Create.NewDimension(view, line, refs)
        if dim is None:
            raise RuntimeError('NewDimension returned None')
        try:
            doc.Regenerate()
        except Exception:
            pass
        try:
            val = float(dim.Value)
            info = 'SUCCESS value={0:.6f}ft'.format(val)
        except Exception:
            info = 'SUCCESS'
        st.RollBack()
        return True, info
    except Exception as ex:
        try:
            st.RollBack()
        except Exception:
            pass
        return False, compact_error(ex)


def fabrication_dimension_info(part):
    rows = []
    try:
        dims = part.GetDimensions()
    except Exception:
        dims = []
    for d in dims:
        try:
            name = d.Name
        except Exception:
            name = '?'
        try:
            dtype = safe_str(d.Type)
        except Exception:
            dtype = '?'
        try:
            val = part.GetDimensionValue(d)
            sval = '{0:.6f}ft'.format(float(val))
        except Exception:
            try:
                sval = safe_str(part.GetCalculatedDimensionValue(d))
            except Exception:
                sval = '?'
        rows.append('{0} | {1} | {2}'.format(name, dtype, sval))
        if len(rows) >= 20:
            break
    return rows


def selected_parts_and_grid():
    parts = []
    selected_grid = None
    try:
        ids = list(uidoc.Selection.GetElementIds())
    except Exception:
        ids = []
    for eid in ids:
        elem = doc.GetElement(eid)
        if elem is None:
            continue
        if isinstance(elem, DB.Grid):
            selected_grid = elem
        elif is_fabrication_part(elem):
            parts.append(elem)
    if not parts:
        class FabFilter(UI.Selection.ISelectionFilter):
            def AllowElement(self, elem):
                return is_fabrication_part(elem)
            def AllowReference(self, reference, point):
                return False
        try:
            picked = uidoc.Selection.PickObjects(UI.Selection.ObjectType.Element, FabFilter(),
                                                  'Pick one or more MEP Fabrication straight parts')
            for pr in picked:
                elem = doc.GetElement(pr.ElementId)
                if elem is not None:
                    parts.append(elem)
        except Exception:
            return [], selected_grid
    # Unique, limit.
    final = []
    seen = set()
    for p in parts:
        try:
            pid = eid_int(p.Id)
        except Exception:
            continue
        if pid in seen:
            continue
        seen.add(pid)
        final.append(p)
        if len(final) >= MAX_PARTS:
            break
    return final, selected_grid


def report_path():
    name = 'FAB_REF_PROBE_{0}.txt'.format(datetime.now().strftime('%Y%m%d_%H%M%S'))
    try:
        from System import Environment
        desktop = Environment.GetFolderPath(Environment.SpecialFolder.Desktop)
        if desktop:
            return os.path.join(desktop, name)
    except Exception:
        pass
    try:
        return os.path.join(os.environ.get('TEMP', os.getcwd()), name)
    except Exception:
        return name


def line_report(lines, text=''):
    lines.append(text)


def part_meta(part):
    fields = []
    for label, attr in (
        ('Category', None),
        ('DomainType', 'DomainType'),
        ('ServiceName', 'ServiceName'),
        ('ServiceAbbreviation', 'ServiceAbbreviation'),
        ('ProductName', 'ProductName'),
        ('ProductShortDescription', 'ProductShortDescription'),
        ('ProductSizeDescription', 'ProductSizeDescription'),
        ('OverallSize', 'OverallSize'),
        ('Size', 'Size'),
        ('Slope', 'Slope'),
    ):
        try:
            if label == 'Category':
                val = fab_category(part)
            else:
                val = getattr(part, attr)
            fields.append('{0}={1}'.format(label, safe_str(val)))
        except Exception:
            pass
    return '; '.join(fields)


def run_probe():
    if not isinstance(view, DB.ViewPlan):
        forms.alert('FAB REF PROBE runs in a plan view.', title='FAB REF PROBE')
        return

    parts, selected_grid = selected_parts_and_grid()
    if not parts:
        return

    grids = collect_grids()
    if not grids:
        forms.alert('No straight host-model grids were found.', title='FAB REF PROBE')
        return

    selected_grid_id = eid_int(selected_grid.Id) if selected_grid is not None else None
    started = time.time()
    lines = []
    successes = []
    failures = []

    line_report(lines, 'ROBMEPTOOLS FAB REF PROBE v0.1')
    line_report(lines, 'Revit: {0}'.format(app_info()))
    line_report(lines, 'View: {0} | Scale 1:{1}'.format(view.Name, view.Scale))
    line_report(lines, 'Parts selected: {0} (max {1})'.format(len(parts), MAX_PARTS))
    line_report(lines, '')

    tx = DB.Transaction(doc, 'FAB REF PROBE - ROLLBACK')
    try:
        tx.Start()
    except Exception as ex:
        forms.alert('Could not start diagnostic transaction:\n\n{0}'.format(ex), title='FAB REF PROBE')
        return

    try:
        for pi, part in enumerate(parts):
            pid = eid_int(part.Id)
            cl = fabrication_centerline(part)
            grid_data, grid_mode = nearest_grid(part, grids, selected_grid_id)
            line_report(lines, '=' * 92)
            line_report(lines, 'PART {0}/{1} | ElementId {2}'.format(pi + 1, len(parts), pid))
            line_report(lines, part_meta(part))
            line_report(lines, 'Connector shape={0}; IsAStraight={1}; centerline={2}'.format(
                connector_shape(part),
                safe_str(getattr(part, 'IsAStraight', lambda: '?')() if hasattr(part, 'IsAStraight') else '?'),
                'yes' if cl is not None else 'no'))
            if grid_data is None:
                line_report(lines, 'GRID: NONE ({0})'.format(grid_mode))
                failures.append((pid, 'no-grid'))
                continue
            line_report(lines, 'GRID: {0} | ElementId {1} | mode={2}'.format(
                grid_data['name'], eid_int(grid_data['element'].Id), grid_mode))

            line_report(lines, 'Fabrication dimensions (first 20):')
            fdi = fabrication_dimension_info(part)
            if not fdi:
                line_report(lines, '  <none/read unavailable>')
            else:
                for row in fdi:
                    line_report(lines, '  ' + row)

            grid_refs = grid_reference_candidates(grid_data['element'])
            line_report(lines, 'Grid reference candidates:')
            for gname, gref in grid_refs:
                line_report(lines, '  {0}: type={1}; stable={2}'.format(
                    gname, ref_type(gref), stable_rep(gref) or '<none>'))

            refs = harvest_candidates(part, grid_data)
            line_report(lines, 'Fabrication reference candidates harvested: {0}'.format(len(refs)))
            line_report(lines, '')

            for ri, rec in enumerate(refs):
                owner_geom = geometry_object_type(part, rec['ref'])
                line_report(lines, '  REF {0:02d} | {1}'.format(ri + 1, rec['source']))
                line_report(lines, '    type={0}; relation={1}; geom={2}; ownerGeom={3}; elementId={4}'.format(
                    rec['ref_type'], rec['relation'], rec['geometry'], owner_geom, rec['element_id']))
                line_report(lines, '    stable={0}'.format(rec['stable'] or '<none>'))
                line_report(lines, '    stable-roundtrip={0}; parsed-type={1}'.format(
                    rec['parse_status'], ref_type(rec['parsed_ref']) if rec['parsed_ref'] is not None else 'None'))

                for gname, gref in grid_refs:
                    ok, msg = trial_dimension(part, grid_data, gref, rec['ref'], rec['witness'])
                    mark = 'PASS' if ok else 'FAIL'
                    line_report(lines, '    TEST original + {0}: {1} | {2}'.format(gname, mark, msg))
                    if ok:
                        successes.append((pid, grid_data['name'], rec['source'], rec['ref_type'], gname, 'original'))
                    else:
                        failures.append((pid, rec['source'], gname, msg))

                    if rec['parsed_ref'] is not None:
                        ok2, msg2 = trial_dimension(part, grid_data, gref, rec['parsed_ref'], rec['witness'])
                        mark2 = 'PASS' if ok2 else 'FAIL'
                        line_report(lines, '    TEST parsed   + {0}: {1} | {2}'.format(gname, mark2, msg2))
                        if ok2:
                            successes.append((pid, grid_data['name'], rec['source'], ref_type(rec['parsed_ref']), gname, 'parsed'))
                line_report(lines, '')
    finally:
        try:
            tx.RollBack()
        except Exception:
            pass

    elapsed = time.time() - started
    line_report(lines, '=' * 92)
    line_report(lines, 'SUMMARY')
    line_report(lines, 'Elapsed: {0:.2f} sec'.format(elapsed))
    line_report(lines, 'Successful trial dimensions: {0}'.format(len(successes)))
    if successes:
        line_report(lines, 'Successful strategies:')
        for row in successes[:80]:
            line_report(lines, '  Element {0} | Grid {1} | {2} | ref={3} | {4} | {5}'.format(*row))
    else:
        line_report(lines, 'NO dimension reference strategy succeeded in this probe.')
    line_report(lines, '')
    line_report(lines, 'The parent transaction was rolled back. No probe dimensions were retained.')

    path = report_path()
    try:
        with open(path, 'w') as fp:
            fp.write('\n'.join(lines))
    except Exception as ex:
        path = '<report write failed: {0}>'.format(ex)

    # pyRevit output: concise enough to scan, full details remain in report.
    output.print_md('# FAB REF PROBE v0.1')
    output.print_md('**Revit:** `{0}`'.format(app_info()))
    output.print_md('**Selected fabrication parts:** `{0}`'.format(len(parts)))
    output.print_md('**Successful trial dimensions:** `{0}`'.format(len(successes)))
    output.print_md('**Runtime:** `{0:.2f} sec`'.format(elapsed))
    output.print_md('**Report:** `{0}`'.format(path))
    if successes:
        output.print_md('## Successful reference strategies')
        for row in successes[:40]:
            output.print_md('- Element `{0}` → Grid **{1}** | `{2}` | `{3}` | `{4}` | `{5}`'.format(*row))
    else:
        output.print_md('## No trial reference pair succeeded')
        output.print_md('Attach the generated report so the next Fabrication reference adapter can be based on exact Revit 2025/2027 behavior.')

    forms.alert(
        'FAB REF PROBE finished.\n\n'
        'Parts tested: {0}\n'
        'Successful trial dimensions: {1}\n'
        'Runtime: {2:.1f} sec\n\n'
        'Nothing was changed in the model; every trial was rolled back.\n\n'
        'A detailed report was written to:\n{3}'.format(len(parts), len(successes), elapsed, path),
        title='FAB REF PROBE'
    )


if __name__ == '__main__':
    run_probe()
