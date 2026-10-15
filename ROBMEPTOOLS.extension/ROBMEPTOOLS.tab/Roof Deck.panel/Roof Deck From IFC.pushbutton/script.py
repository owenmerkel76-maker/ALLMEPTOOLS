# coding: utf-8
"""ROOFDECKTOOLS v0.3.2 - direct IFC2x3 -> native Revit 2025 structural floors.

No Revit IFC linking needed: read the IFC STEP file directly in IronPython,
recover each IfcRoof's *downward planar face*, and build actual native Floors.
Site georeference is intentionally ignored; coordinates use the source
Revit project's internal origin. VERIFY placement relative to MEP model.
It does not recreate an exact profiled/corrugated roof deck.

Field-test build: source IFC2x3 faceted BRep with planar roof undersides only.
"""
import math
import os
import sys
import traceback
import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
from Autodesk.Revit.DB import (FilteredElementCollector, Options, Solid, GeometryInstance,
    PlanarFace, Floor, FloorType, Level, Element, XYZ, Line, CurveLoop, BoundaryValidation,
    ElementId, CompoundStructure, EndCapCondition, MaterialFunctionAssignment, BuiltInParameter,
    Transaction, ViewDetailLevel)
from System.Collections.Generic import List
from pyrevit import forms, script

HERE=os.path.dirname(__file__)
if HERE not in sys.path:sys.path.insert(0,HERE)
import ifc_geometry as parser
import geometry_utils as geo
import surface_utils as surf

uidoc=__revit__.ActiveUIDocument
doc=uidoc.Document
out=script.get_output()
VERSION='v0.3.2'
TOL=1.0/96.0                 # 1/8 inch actual underside check
MAX_REGIONS=50
MAX_SLOPE=0.5


def coord(v):return (float(v.X),float(v.Y),float(v.Z))

def valid_ring(ring):
    pts=geo.clean_ring(ring)
    if len(pts)<3 or abs(geo.area(pts))<4:
        raise ValueError('IFC roof contains a degenerate or too-small outline')
    if len(pts)>300:
        raise ValueError('Roof boundary has >300 corners; needs a more detailed version')
    return pts


def orient(ring,ccw):
    pts=valid_ring(ring)
    if (geo.area(pts)>0)!=ccw:pts.reverse()
    return pts


def make_curveloop(pts):
    loop=CurveLoop()
    for p,q in zip(pts,pts[1:]+pts[:1]):
        start=XYZ(p[0],p[1],0)
        end=XYZ(q[0],q[1],0)
        if start.DistanceTo(end)<doc.Application.ShortCurveTolerance:
            raise ValueError('IFC profile has edge shorter than Revit tolerance')
        loop.Append(Line.CreateBound(start,end))
    return loop


def floor_profile(region):
    loops=List[CurveLoop]()
    loops.Add(make_curveloop(orient(region['outer'],True)))
    for h in region['holes']:
        loops.Add(make_curveloop(orient(h,False)))
    if not BoundaryValidation.IsValidHorizontalBoundary(loops):
        raise ValueError('Native Floor rejected the IFC roof boundary/opening loops')
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
    types=list(FilteredElementCollector(doc).OfClass(FloorType).ToElements())
    bases=[ft for ft in types if not ft.IsFoundationSlab]
    if not bases:raise ValueError('No native floor types available in this Revit project')
    name='ROB ROOF DECK HANGER HOST - %.2f IN'%(thickness*12)
    for ft in bases:
        if safe_floor_type_name(ft)==name:
            cs=ft.GetCompoundStructure()
            if cs and abs(cs.GetWidth()-thickness)<1./1200.:
                return ft
    if name in set(safe_floor_type_name(x) for x in types):
        n=2
        while '%s (%d)'%(name,n) in set(safe_floor_type_name(x) for x in types):n+=1
        name='%s (%d)'%(name,n)
    try:
        base=doc.GetElement(Floor.GetDefaultFloorType(doc,True))
        if not base or base.IsFoundationSlab:base=bases[0]
    except Exception:base=bases[0]
    new=base.Duplicate(name)
    material=ElementId.InvalidElementId
    try:
        layers=list(base.GetCompoundStructure().GetLayers())
        if layers:material=layers[0].MaterialId
    except Exception:pass
    cs=CompoundStructure.CreateSingleLayerCompoundStructure(
        MaterialFunctionAssignment.Structure,thickness,material)
    # Revit API 2025 requires NoEndCap for FLOORS/ROOFS.
    # The single-layer factory can default to a wall-style wrapping condition,
    # which fails with "wrong EndCap condition" on SetCompoundStructure.
    cs.EndCap=EndCapCondition.NoEndCap
    new.SetCompoundStructure(cs)
    applied=new.GetCompoundStructure()
    if (applied is None or applied.EndCap!=EndCapCondition.NoEndCap or
            abs(applied.GetWidth()-thickness)>1./1200.):
        raise ValueError('Created floor type did not retain the requested '
                         'thickness / NoEndCap structure')
    return new


def all_solids(items,depth=0):
    if depth>10:return
    for obj in items:
        if isinstance(obj,GeometryInstance):
            for s in all_solids(obj.GetInstanceGeometry(),depth+1):yield s
        elif isinstance(obj,Solid) and obj.Faces.Size>0:
            yield obj


def underside_plane(floor):
    opt=Options();opt.DetailLevel=ViewDetailLevel.Fine
    fs=[]
    for solid in all_solids(floor.get_Geometry(opt)):
        for f in solid.Faces:
            if isinstance(f,PlanarFace) and f.FaceNormal.Z<-0.7:
                fs.append((abs(f.FaceNormal.Z)*f.Area,f))
    if not fs:raise ValueError('Native structural Floor underside cannot be evaluated')
    fs.sort(key=lambda item:-item[0])
    f=fs[0][1]
    return surf.plane_from_point_normal(coord(f.Origin),coord(f.FaceNormal))


def nearest_level(z):
    levels=list(FilteredElementCollector(doc).OfClass(Level).ToElements())
    if not levels:raise ValueError('Revit project needs at least one Level')
    return min(levels,key=lambda l:abs(l.Elevation-z))


def in_roof(p,region):
    return (geo.point_inside(p,region['outer']) and
            not any(geo.point_inside(p,h) for h in region['holes']))


def arrow_for_region(region):
    plane=region['plane'];a,b=plane[:2]
    pitch=math.hypot(a,b)
    if pitch<1.e-6:return None,0.0
    ux=a/pitch;uy=b/pitch
    xs=[p[0] for p in region['outer']];ys=[p[1] for p in region['outer']]
    mx=sum(xs)/len(xs);my=sum(ys)/len(ys)
    candidates=[(mx,my),((min(xs)+max(xs))/2,(min(ys)+max(ys))/2)]
    for iy in range(13):
        for ix in range(13):
            candidates.append((min(xs)+(ix+0.5)*(max(xs)-min(xs))/13.,
                               min(ys)+(iy+0.5)*(max(ys)-min(ys))/13.))
    for x,y in candidates:
        if in_roof((x,y),region) and in_roof((x+ux,y+uy),region):
            return Line.CreateBound(XYZ(x,y,0),XYZ(x+ux,y+uy,0)),pitch
    raise ValueError('Could not locate a slope arrow entirely inside the roof boundary')


def make_floor(region,floor_type,thickness,src):
    plane=region['plane'];outer=region['outer']
    arrow,pitch=arrow_for_region(region)
    x=sum(p[0] for p in outer)/len(outer)
    y=sum(p[1] for p in outer)/len(outer)
    btm=surf.plane_z(plane,x,y)
    level=nearest_level(btm+thickness)
    loops=floor_profile(region)
    f=Floor.Create(doc,loops,floor_type.Id,level.Id,True,arrow,pitch)
    offset=f.get_Parameter(BuiltInParameter.FLOOR_HEIGHTABOVELEVEL_PARAM)
    if offset is None or offset.IsReadOnly:
        raise ValueError('Floor offset parameter could not be set')
    offset.Set(btm+thickness-level.Elevation)
    doc.Regenerate()
    vertices=outer[:]
    for ring in region['holes']:vertices.extend(ring)
    for n in range(3):
        actual=underside_plane(f)
        ok,error=surf.verify_at_points(plane,actual,vertices,TOL)
        if ok:break
        dz=btm-surf.plane_z(actual,x,y)
        if n==2 or abs(dz)<1.e-10:
            raise ValueError('Floor underside mismatch: %.3f inches; rolled back'%(12*error))
        offset.Set(offset.AsDouble()+dz)
        doc.Regenerate()
    cp=f.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
    if cp and not cp.IsReadOnly:
        cp.Set('ROB RoofDeckFromIFC %s; source %s; IfcGUID %s; '
               'underside plane %.8f*x + %.8f*y + %.5f; '
               'proxy %.2f in; verify hangers'%(VERSION,src,region['ifc_id'],
                                    plane[0],plane[1],plane[2],thickness*12))
    return f


def previous_hosts(filename):
    tag='ROB RoofDeckFromIFC'
    source='source %s;'%filename
    result=[]
    for f in FilteredElementCollector(doc).OfClass(Floor).ToElements():
        p=f.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        value=p.AsString() if p else ''
        if value and tag in value and source in value:result.append(f)
    return result


def main():
    if doc.IsFamilyDocument:
        forms.alert('Open a Revit project, not a family, to make hanger-host floors.')
        return
    filepath=forms.pick_file(file_ext='ifc',title='Select Revit 2026 ROOF-ONLY IFC2x3 file')
    if not filepath:return
    filename=os.path.basename(filepath)
    try:
        regions=parser.IFCReader(filepath).roofs()
        if not regions or len(regions)>MAX_REGIONS:
            raise ValueError('Expected 1-%d roof surfaces, found %d'%(MAX_REGIONS,len(regions)))
        for reg in regions:
            reg['outer']=orient(reg['outer'],True)
            reg['holes']=[orient(h,False) for h in reg['holes']]
            floor_profile(reg)
            if math.hypot(reg['plane'][0],reg['plane'][1])>MAX_SLOPE:
                raise ValueError('IFC roof pitch >6:12, needs a different host type')
    except Exception as exc:
        out.print_md('### IFC parse: no model changes\n`%s`'%str(exc))
        forms.alert('Cannot safely reconstruct this IFC:\n\n%s\n\nNo elements were made.'%str(exc),
                    title='Roof Deck From IFC - stopped safely')
        return
    choice=forms.ask_for_string(default='1.50',
        prompt='Enter NATIVE structural FLOOR hanger-host thickness (inches).\n\n'
               '1.50 inches is a proxy, not the actual roof type thickness.\n'
               'The floor UNDERSIDE will match the source IFC roof underside.',
        title='Roof Deck From IFC v0.3.2')
    if choice is None:return
    try:
        inches=float(choice.strip())
        if not .25<=inches<=24:raise ValueError()
    except Exception:
        forms.alert('Enter a thickness in inches between 0.25 and 24.0')
        return
    thickness=inches/12.0
    old=previous_hosts(filename)
    summary=[]
    for n,r in enumerate(regions):
        zvals=[surf.plane_z(r['plane'],p[0],p[1]) for p in r['outer']]
        summary.append('  %d: %s | %.1f SF | slope %.3f in/ft | BOS %.2f-%.2f ft | openings %d'%(
                n+1,r['name'],r['area'],surf.pitch_in_per_foot(r['plane']),
                min(zvals),max(zvals),len(r['holes'])))
    preview=('FILE: %s\n\nIFC roofs: %d\n%s\n\n'
             'Replace existing native hosts generated from this IFC: %d\n'
             'Host thickness: %.2f inches\n\n'
             'IMPORTANT: Uses the source building INTERNAL coordinates, '
             'NOT the far-away shared site position. Align/verify roof to '
             'your Revit 2025 MEP grids BEFORE attaching rods.\n\n'
             'Native floors are committed only after a 1/8-inch underside geometry check. '
             'This is a hanger-host proxy, not a corrugated roof deck.\n\nCreate?'%(
                 filename,len(regions),'\n'.join(summary),len(old),inches))
    if not forms.alert(preview,title='Roof Deck From IFC v0.3.2 - review',yes=True,no=True):return
    t=Transaction(doc,'ROOFDECKTOOLS v0.3.2 - IFC Native Structural Floors')
    ids=[]
    stage='Start transaction'
    try:
        t.Start()
        stage='Create or reuse structural Floor Type'
        floor_type=make_floor_type(thickness)
        if old:
            stage='Replace prior generated hosts'
            doc.Delete(List[ElementId]([x.Id for x in old]))
        for i,r in enumerate(regions):
            stage='Create and verify roof %d (%s)'%(i+1,r['name'])
            ids.append(make_floor(r,floor_type,thickness,filename).Id)
        stage='Commit Revit transaction'
        t.Commit()
    except Exception as exc:
        try: t.RollBack()
        except Exception: pass
        detail=traceback.format_exc()
        out.print_md('### IFC reconstruction: rolled back without saving changes')
        out.print_md('**Failure stage:** %s'%stage)
        out.print_md('**Error type:** %s'%type(exc).__name__)
        out.print_md('```\n%s\n```'%detail)
        forms.alert('No model changes retained.\n\nFailed at: %s\n\n%s: %s\n\n'
                    'For the full traceback, open the pyRevit output panel.'%(
                    stage,type(exc).__name__,str(exc)),
                    title='Roof Deck From IFC v0.3.2 - rolled back')
        return
    uidoc.Selection.SetElementIds(List[ElementId](ids))
    out.print_md('## Roof Deck From IFC %s'%VERSION)
    out.print_md('Created **%s** native structural floors from %s.'%(len(ids),filename))
    for r in regions:
        out.print_md('* %s: %.1f SF, pitch %.3f in/ft'%(r['name'],r['area'],surf.pitch_in_per_foot(r['plane'])))
    forms.alert('Created %d native structural floor hanger hosts.\n\n'
                'Verify their placement against MEP grids and the underside '
                'in SECTION. Then test Attach to Structure on ONE fabrication '
                'hanger. Rods have NOT been modified.'%len(ids),
                title='Roof Deck From IFC - complete')

if __name__=='__main__':main()
