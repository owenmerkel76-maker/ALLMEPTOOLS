# coding: utf-8
"""ROOFDECKTOOLS - Roof Deck From DXF v0.2 (Revit 2025+).

Specifically handles two or more distinct 3D ACIS roof solids. Inspects each
solid's actual outward-facing underside PlanarFace; creates a native structural
Floor with an equivalent flat/sloped UNDERSIDE. Never approximates all CAD parts
with a shared XY bounding box or shared Z elevation.

This is an attachment host/proxy, NOT a faithful corrugated sheet deck model.
Revit required for end-to-end testing. IronPython 2.7 compatible.
"""
import math
import os
import sys
import traceback
import clr

clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
from Autodesk.Revit.DB import (FilteredElementCollector, ImportInstance,
    Options, GeometryInstance, Solid, PlanarFace, Floor, FloorType, Level, Element, XYZ,
    Line, CurveLoop, BoundaryValidation, ElementId, CompoundStructure,
    EndCapCondition, MaterialFunctionAssignment, BuiltInParameter, Transaction, ViewDetailLevel)
from System.Collections.Generic import List
from pyrevit import forms, script

HERE = os.path.dirname(__file__)
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import geometry_utils as geo
import surface_utils as surf

uidoc = __revit__.ActiveUIDocument
doc = uidoc.Document
out = script.get_output()

MIN_FACE_AREA = 4.0                # ft2: small noise / flute sides ignored
SECONDARY_PLANE_MAX = 0.05       # >5% significant underside plane needs splitting
BOTTOM_NZ_MIN = 0.7             # absolute normal Z of candidate bottom faces
MAX_PITCH = 0.5                 # 6:12; refuse implausibly steep 'roof deck' faces
MAX_GROUPS = 50
BOT_TOL = 1.0/96.0               # 1/8 inch at vertices of reconstructed host
VERSION = 'v0.3.2'


def elid(eid):
    try:
        return str(eid.Value)
    except Exception:
        return str(eid.IntegerValue)


def coord(v):
    return (float(v.X),float(v.Y),float(v.Z))


def get_cad():
    selection = [doc.GetElement(i) for i in uidoc.Selection.GetElementIds()]
    chosen = [el for el in selection if isinstance(el, ImportInstance)]
    if len(chosen) == 1:
        return chosen[0]
    imports = list(FilteredElementCollector(doc).OfClass(ImportInstance).ToElements())
    if not imports:
        forms.alert('Link/import the 3D ROOF DECK.dxf first:\n'
                    'Insert > Link CAD, position it, select it and rerun.',
                    title='ROOF DECK TOOLS')
        return None
    if len(imports) == 1:
        return imports[0]
    options = {}
    for cad in imports:
        options['%s | CAD Element %s' % (cad.Name,elid(cad.Id))] = cad
    choice = forms.SelectFromList.show(sorted(options.keys()),
             title='Choose your positioned roof-deck-only CAD link',
             button_name='Use this CAD')
    return options.get(choice) if choice else None


def solids_from_geometry(items, level=0):
    """GetInstanceGeometry resolves the ImportInstance transform (model feet)."""
    if level > 10:
        return
    for item in items:
        if isinstance(item, GeometryInstance):
            for solid in solids_from_geometry(item.GetInstanceGeometry(), level+1):
                yield solid
        elif isinstance(item, Solid):
            try:
                if item.Faces.Size > 0 and abs(item.Volume) > 0.00001:
                    yield item
            except Exception:
                continue


def bottom_surface_of_solid(solid, source_index):
    """Recover mesh outline from planar BOTTOM faces of a single CAD solid.

    If a second significant plane exists, abort this solid; a constant-thickness
    sloped Revit floor cannot reproduce stepped/multiple underside elevations.
    """
    clusters = []
    n_faces = 0
    for face in solid.Faces:
        if not isinstance(face, PlanarFace):
            continue
        normal = face.FaceNormal
        if normal.Z > -BOTTOM_NZ_MIN:
            continue  # top / side faces are NOT hanger attachment targets
        n_faces += 1
        try:
            plane = surf.plane_from_point_normal(coord(face.Origin),coord(normal))
            mesh = face.Triangulate()
            triangles = []
            samples = []
            for i in range(mesh.NumTriangles):
                tr = mesh.get_Triangle(i)
                points3d = [coord(tr.get_Vertex(k)) for k in range(3)]
                pts = [(p[0],p[1]) for p in points3d]
                if surf.triangle_area_xy(pts[0],pts[1],pts[2]) < 1.e-8:
                    continue
                if geo.area(pts) < 0.0:
                    pts.reverse()
                triangles.append(tuple(pts))
                samples.extend(points3d)
            if not triangles:
                continue
            face_xy_area = abs(normal.Z) * float(face.Area)
            if face_xy_area < MIN_FACE_AREA:
                continue
            representative = samples[0]
            assigned = None
            for cluster in clusters:
                if surf.same_plane(plane,cluster['plane'],
                                   representative[0],representative[1]):
                    assigned = cluster
                    break
            if assigned is None:
                assigned = {'plane':plane, 'triangles':[], 'samples':[],
                            'area':0.0, 'face_count':0}
                clusters.append(assigned)
            assigned['triangles'].extend(triangles)
            assigned['samples'].extend(samples)
            assigned['area'] += face_xy_area
            assigned['face_count'] += 1
        except Exception:
            continue

    if not clusters:
        raise ValueError('Solid %d has no usable planar downward face '
                         '(downward planar faces checked: %d).' % (source_index,n_faces))
    clusters.sort(key=lambda c:-c['area'])
    main = clusters[0]
    others = sum(x['area'] for x in clusters[1:])
    if others > max(MIN_FACE_AREA, main['area']*SECONDARY_PLANE_MAX):
        raise ValueError('Solid %d has multiple substantial underside planes '
                         '(primary %.1f ft2, other %.1f ft2). Refusing '
                         'to ignore stepped/pitched surfaces.' %
                         (source_index, main['area'], others))
    if math.hypot(main['plane'][0],main['plane'][1]) > MAX_PITCH:
        raise ValueError('Solid %d underside slope exceeds 6:12; '
                         'verify roof solid orientation.' % source_index)

    rings, reason = geo.mesh_boundary_rings(main['triangles'], 1)
    groups = geo.group_rings(rings)
    if not groups:
        raise ValueError('Solid %d bottom footprint cannot be traced safely: %s' %
                         (source_index,reason))
    outputs = []
    for outer, holes in groups:
        area = abs(geo.area(outer)) - sum(abs(geo.area(h)) for h in holes)
        if area < geo.MIN_AREA:
            continue
        outputs.append({'solid_no':source_index, 'outer':outer,'holes':holes,
                        'plane':main['plane'], 'area':area,
                        'source_face_area':main['area']})
    # Catches an incomplete mesh that otherwise might miss most of the roof.
    # Accommodate small fluctuations from vertex snapping and triangulation.
    recovered_area = sum(x['area'] for x in outputs)
    if recovered_area < 0.92 * main['area'] or recovered_area > 1.08 * main['area']:
        raise ValueError('Solid %d boundary coverage is inconsistent '
                         '(%.1f ft2 outline versus %.1f ft2 underside). No guesses.' %
                         (source_index,recovered_area,main['area']))
    return outputs


def make_curveloop(points):
    loop = CurveLoop()
    for i,p in enumerate(points):
        q = points[(i+1)%len(points)]
        start = XYZ(p[0],p[1],0)
        finish = XYZ(q[0],q[1],0)
        if start.DistanceTo(finish) < doc.Application.ShortCurveTolerance:
            raise ValueError('CAD outline edge shorter than Revit short curve tolerance.')
        loop.Append(Line.CreateBound(start,finish))
    return loop


def floor_profile(region):
    loops = List[CurveLoop]()
    loops.Add(make_curveloop(region['outer']))
    for hole in region['holes']:
        loops.Add(make_curveloop(hole))
    if not BoundaryValidation.IsValidHorizontalBoundary(loops):
        raise ValueError('Revit rejected a self-intersecting or overlapping region.')
    return loops


def safe_floor_type_name(floor_type):
    """IronPython cannot reliably read FloorType.Name in Revit 2025.

    Use the built-in type-name parameter; fall back to inherited Element.Name
    descriptor. The old direct property throws AttributeError: Name.
    """
    for bip in (BuiltInParameter.SYMBOL_NAME_PARAM,
                BuiltInParameter.ALL_MODEL_TYPE_NAME):
        try:
            p = floor_type.get_Parameter(bip)
            value = p.AsString() if p else None
            if value:
                return value
        except Exception:
            pass
    return Element.Name.__get__(floor_type)


def make_floor_type(thickness):
    types = list(FilteredElementCollector(doc).OfClass(FloorType).ToElements())
    bases = [ft for ft in types if not ft.IsFoundationSlab]
    if not bases:
        raise ValueError('This project does not have a regular Revit FloorType.')
    name = 'ROB ROOF DECK HANGER HOST - %.2f IN' % (thickness*12.0)
    for ft in bases:
        if safe_floor_type_name(ft) == name:
            cs = ft.GetCompoundStructure()
            if cs and abs(cs.GetWidth()-thickness) <= 1./1200.:
                return ft
    names = set(safe_floor_type_name(ft) for ft in types)
    if name in names:
        idx = 2
        while '%s (%d)' % (name,idx) in names:
            idx += 1
        name = '%s (%d)' % (name,idx)
    try:
        default = doc.GetElement(Floor.GetDefaultFloorType(doc,True))
        base = default if default and not default.IsFoundationSlab else bases[0]
    except Exception:
        base = bases[0]
    newtype = base.Duplicate(name)
    material = ElementId.InvalidElementId
    try:
        layers = list(base.GetCompoundStructure().GetLayers())
        if layers:
            material = layers[0].MaterialId
    except Exception:
        pass
    cs = CompoundStructure.CreateSingleLayerCompoundStructure(
            MaterialFunctionAssignment.Structure, thickness, material)
    # Floor compound structures may not use wall-style end wrapping.
    cs.EndCap = EndCapCondition.NoEndCap
    newtype.SetCompoundStructure(cs)
    applied = newtype.GetCompoundStructure()
    if (applied is None or applied.EndCap != EndCapCondition.NoEndCap or
            abs(applied.GetWidth()-thickness) > 1./1200.):
        raise ValueError('Created floor type did not retain the requested '
                         'thickness / NoEndCap structure')
    return newtype


def floor_underside_plane(floor):
    options = Options()
    options.DetailLevel = ViewDetailLevel.Fine
    solid_faces = []
    geometry = floor.get_Geometry(options)
    if geometry is None:
        raise ValueError('The native Floor has no readable geometry.')
    for solid in solids_from_geometry(geometry):
        for face in solid.Faces:
            if isinstance(face,PlanarFace) and face.FaceNormal.Z < -BOTTOM_NZ_MIN:
                solid_faces.append((face.Area*abs(face.FaceNormal.Z),face))
    if not solid_faces:
        raise ValueError('Could not find the generated structural floor underside.')
    solid_faces.sort(key=lambda pair:-pair[0])
    face = solid_faces[0][1]
    return surf.plane_from_point_normal(coord(face.Origin),coord(face.FaceNormal))


def level_near(z):
    levels = list(FilteredElementCollector(doc).OfClass(Level).ToElements())
    if not levels:
        raise ValueError('No levels in the MEP project. Create a level first.')
    return min(levels,key=lambda l:abs(l.Elevation-z))


def place_one(region,floor_type,thickness,cad):
    plane = region['plane']
    outer = region['outer']
    holes = region['holes']
    samples = list(outer)
    for h in holes:
        samples.extend(h)
    cx = sum(p[0] for p in outer)/float(len(outer))
    cy = sum(p[1] for p in outer)/float(len(outer))
    # The XY center only sets the slope-arrow direction, not outline location.
    # Revit requires a horizontal arrow; actual created face is verified below.
    arrow_xy,pitch = surf.slope_arrow_xy(plane,(cx,cy))
    arrow = None
    if arrow_xy:
        a,b = arrow_xy
        arrow = Line.CreateBound(XYZ(a[0],a[1],0),XYZ(b[0],b[1],0))
    bottom = surf.plane_z(plane,cx,cy)
    level = level_near(bottom+thickness)
    curves = floor_profile(region)
    floor = Floor.Create(doc,curves,floor_type.Id,level.Id,True,arrow,pitch)
    offset = floor.get_Parameter(BuiltInParameter.FLOOR_HEIGHTABOVELEVEL_PARAM)
    if offset is None or offset.IsReadOnly:
        raise ValueError('New Floor Height Offset From Level not writable.')
    offset.Set(bottom+thickness-level.Elevation)
    doc.Regenerate()

    # Geometric bottom check, not bbox.Min.Z! A pitched deck naturally spans Z.
    for iteration in range(3):
        actual = floor_underside_plane(floor)
        delta = bottom - surf.plane_z(actual,cx,cy)
        good, error = surf.verify_at_points(plane,actual,samples,BOT_TOL)
        if good:
            break
        if iteration == 2:
            raise ValueError('Native floor underside did not match source: '
                             'max drift %.3f inches. Rolled back.' % (error*12.0))
        # Correct only a uniform Z translation. Wrong pitch/orientation will still fail.
        if abs(delta) < 1.e-10:
            raise ValueError('Native floor pitch differs from the source '
                             '(%.3f inch max error); cannot correct by elevation.' %
                             (error*12.0))
        offset.Set(offset.AsDouble() + delta)
        doc.Regenerate()

    comment = floor.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
    if comment is not None and not comment.IsReadOnly:
        comment.Set('ROB RoofDeckFromDXF %s; source element %s; solid %d; '
                    'BOS plane %.8f*x + %.8f*y + %.5f; proxy thickness %.2f in; '
                    'VERIFY hanger rods' %
                    (VERSION,elid(cad.Id),region['solid_no'],
                     plane[0],plane[1],plane[2],thickness*12.0))
    return floor


def previous_host_floors(cad):
    tag = 'source element %s' % elid(cad.Id)
    existing = []
    for el in FilteredElementCollector(doc).OfClass(Floor).ToElements():
        parameter = el.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        if parameter:
            value = parameter.AsString() or ''
            if 'ROB RoofDeckFromDXF' in value and tag in value:
                existing.append(el)
    return existing


def main():
    if doc.IsFamilyDocument:
        forms.alert('Use this tool inside a Revit project, not a family.')
        return
    cad = get_cad()
    if cad is None:
        return
    options = Options()
    options.DetailLevel = ViewDetailLevel.Fine
    options.IncludeNonVisibleObjects = False
    options.ComputeReferences = False
    try:
        geometry = cad.get_Geometry(options)
        if geometry is None:
            raise ValueError('CAD has no accessible geometry.')
        solids = list(solids_from_geometry(geometry))
        if not solids:
            raise ValueError('The selected DXF does not expose 3D Revit Solids. '
                             'The supplied ROOF DECK.dxf has 2 ACIS 3DSOLIDs, '
                             'but Revit must load them as actual solids. '
                             'Verify in a 3D view and use Link CAD, not exploded 2D linework.')
        regions = []
        for i,solid in enumerate(solids):
            regions.extend(bottom_surface_of_solid(solid,i+1))
        if len(regions) == 0 or len(regions) > MAX_GROUPS:
            raise ValueError('Expected 1-%d safe underside regions, recovered %d.' %
                             (MAX_GROUPS,len(regions)))
        # Verify all geometry before asking to change the model.
        for region in regions:
            floor_profile(region)
        count = len(regions)
        previous = previous_host_floors(cad)
    except Exception as ex:
        out.print_md('### Roof Deck From DXF v0.2 - no model changes')
        out.print_md('`%s`' % str(ex))
        forms.alert('The converter could not safely recover every solid underside. '
                    'No new floors created.\n\n%s' % str(ex),
                    title='Roof Deck From DXF - stopped safely')
        return

    host_in = forms.ask_for_string(default='1.50',
              prompt='Enter native structural hanger-host thickness (inches).\n\n'
                     '1.50 in is a proxy, NOT exact corrugated metal geometry.\n'
                     'The BOTTOM face will follow the DXF underside.',
              title='Roof Deck From DXF - Host Thickness')
    if host_in is None:
        return
    try:
        thickness_in = float(host_in.strip())
        if not (0.25 <= thickness_in <= 24.0):
            raise ValueError('Enter a number from 0.25 to 24 inches.')
    except Exception:
        forms.alert('Enter a valid host thickness, e.g. 1.50 or 8.00.')
        return
    thickness = thickness_in/12.0
    summary = []
    for j,region in enumerate(regions):
        p = region['plane']
        slope = surf.pitch_in_per_foot(p)
        elevation_mid = surf.plane_z(p,region['outer'][0][0],region['outer'][0][1])
        summary.append('Deck %d (DXF solid %d): %.0f SF | underside %.3f in/ft | '
                       'BOS at one corner %.2f ft' %
                       (j+1,region['solid_no'],region['area'],slope,elevation_mid))
    msg = ('DXF: %s\n'
           'Revit 3D solids found: %d\n'
           'Separate native structural floors: %d\n\n%s\n\n'
           'Thickness of HANGER HOST: %.2f in\n'
           'Previously generated hosts to replace: %d\n\n'
           'NO imported CAD solids will be deleted. All new floors must pass '
           'a 1/8-in underside match test or the entire operation rolls back.\n\n'
           'Important: This is a structural FLOOR proxy, not a flute-accurate '
           'metal deck. Confirm hanger attachment in a section.' %
           (cad.Name,len(solids),count,'\n'.join(summary),thickness_in,len(previous)))
    if not forms.alert(msg, title='Roof Deck From DXF v0.2 - preview',yes=True,no=True):
        return
    t = Transaction(doc,'ROOFDECKTOOLS - Separate Sloped Roof Deck Hanger Hosts')
    created = []
    try:
        t.Start()
        floor_type = make_floor_type(thickness)
        if previous:
            doc.Delete(List[ElementId]([e.Id for e in previous]))
        for region in regions:
            created.append(place_one(region,floor_type,thickness,cad).Id)
        t.Commit()
    except Exception as ex:
        try:
            t.RollBack()
        except Exception:
            pass
        out.print_md('### Roof Deck From DXF v0.2 - rolled back')
        out.print_md('```\n%s\n```' % traceback.format_exc())
        forms.alert('No changes retained. The floor conversion failed a '
                    'creation or underside validation check:\n\n%s' % str(ex),
                    title='Roof Deck From DXF - rollback')
        return

    uidoc.Selection.SetElementIds(List[ElementId](created))
    out.print_md('## Roof Deck From DXF - v0.2')
    out.print_md('Created **%d native Revit structural floors**, based on %d CAD solids.' %
                 (len(created),len(solids)))
    for j,reg in enumerate(regions):
        out.print_md('- Host %d: Solid %d; %.1f ft²; underside pitch %.3f in/ft' %
                     (j+1,reg['solid_no'],reg['area'],
                      surf.pitch_in_per_foot(reg['plane'])))
    out.print_md('**Please inspect the underside in a section, then select a '
                 'fabrication hanger and run Attach to Structure.**')
    forms.alert('%d native structural floor host(s) created and selected.\n\n'
                'Each floor underside was checked against its DXF solid within '
                '1/8 inch at the detected footprint vertices.\n\n'
                'NEXT: Inspect a section and TEST one fabrication hanger using '
                'Attach to Structure. No rods were changed automatically.' %
                len(created),title='Roof Deck From DXF v0.2')


if __name__ == '__main__':
    main()
