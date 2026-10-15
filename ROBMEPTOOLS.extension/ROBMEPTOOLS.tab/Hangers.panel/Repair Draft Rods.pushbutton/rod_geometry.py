# -*- coding: utf-8 -*-
"""Autohanger: approved structure measured at each individual rod position.

GEOMETRIC rod sizing does not create a Revit structural attachment. Each rod
is measured to a true intersection with selected link/native solids. No
reference-level / bounding-box-top estimate is accepted as an attachment.
"""

def base_from_tip(tip_z, rod_length):
    return float(tip_z) - float(rod_length)


def target_length(base_z, target_z, max_ft):
    length=float(target_z)-float(base_z)
    if length < .10:
        raise ValueError('Overhead structure is too close to or below rod base')
    if length > float(max_ft):
        raise ValueError('Target exceeds maximum rod length')
    return length


def choose_target(ifc_hit, roof_hit, base_z, max_rod):
    """Pure priority calculation. IFC beam/joist ALWAYS wins when measurable."""
    for kind,hit in (('IFC',ifc_hit),('ROOF',roof_hit)):
        if hit is None:
            continue
        z,element_id=hit
        try:
            length=target_length(base_z,z,max_rod)
            return {'tier':kind,'z':float(z),'id':int(element_id),
                    'length':length}
        except ValueError:
            continue
    return None


def _contains_world_xy(bounds,pt,margin=.04):
    x1,x2,y1,y2,z1,z2=bounds
    return (x1-margin<=pt.X<=x2+margin and y1-margin<=pt.Y<=y2+margin)


def _primitives(geometry,depth=0):
    from Autodesk.Revit.DB import Solid, Mesh, GeometryInstance
    if geometry is None or depth>7:
        return
    for item in geometry:
        if isinstance(item,Solid):
            try:
                if item.Volume>1e-8:
                    yield item
            except Exception:
                continue
        elif isinstance(item,Mesh):
            try:
                if item.NumTriangles>0:
                    yield item
            except Exception:
                continue
        elif isinstance(item,GeometryInstance):
            # Revit returns instance geometry in its parent document coords.
            try:
                for primitive in _primitives(item.GetInstanceGeometry(),depth+1):
                    yield primitive
            except Exception:
                pass


def _checked_primitives(geometry, depth=0):
    """Return geometry plus read status; a failure is not a geometric miss.

    GetInstanceGeometry already returns coordinates in the parent document.
    Link transforms are applied once, by the ray caller, never here.
    """
    from Autodesk.Revit.DB import Solid, Mesh, GeometryInstance
    primitives=[]
    failed=False
    if geometry is None or depth>16:
        return primitives,True
    try:
        for item in geometry:
            if isinstance(item,Solid):
                try:
                    if item.Volume>1e-8:
                        primitives.append(item)
                except Exception:
                    failed=True
            elif isinstance(item,Mesh):
                try:
                    if item.NumTriangles>0:
                        primitives.append(item)
                except Exception:
                    failed=True
            elif isinstance(item,GeometryInstance):
                try:
                    nested,bad=_checked_primitives(item.GetInstanceGeometry(),depth+1)
                    primitives.extend(nested)
                    failed=failed or bad
                except Exception:
                    failed=True
    except Exception:
        failed=True
    return primitives,failed


def _dot(a,b):
    return sum(x*y for x,y in zip(a,b))

def _sub(a,b):
    return tuple(x-y for x,y in zip(a,b))

def _cross(a,b):
    return (a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],
            a[0]*b[1]-a[1]*b[0])

def segment_triangle_fraction(a,b,p0,p1,p2):
    """Pure Moller-Trumbore segment intersection. Triangle can be double sided."""
    d=_sub(b,a)
    e1=_sub(p1,p0)
    e2=_sub(p2,p0)
    p=_cross(d,e2)
    det=_dot(e1,p)
    if abs(det)<1e-11: return None
    inv=1.0/det
    tv=_sub(a,p0)
    u=_dot(tv,p)*inv
    if u< -1e-8 or u>1.+1e-8: return None
    q=_cross(tv,e1)
    v=_dot(d,q)*inv
    if v< -1e-8 or u+v>1.+1e-8: return None
    t=_dot(e2,q)*inv
    return t if 0.-1e-8<=t<=1.+1e-8 else None

def _closed_mesh_contains(triangles,point):
    """Detect a rod base inside an actual closed mesh shell.

    Open IFC surface meshes remain usable. Closed connected components are
    checked separately, since a joist may contain several overlapping parts.
    Coordinate welding is used only to determine topology, never elevation.
    Three independent actual triangle rays guard against edge tangencies.
    """
    # A double-sided IFC export can repeat every face with reversed winding.
    # Deduplicate only for shell topology; the measurement caller retains all
    # original triangle coordinates for its actual intersection elevations.
    distinct=[]
    seen_triangles=set()
    for triangle in triangles:
        key=tuple(sorted(tuple(round(value,7) for value in vertex) for vertex in triangle))
        if key not in seen_triangles:
            seen_triangles.add(key)
            distinct.append(triangle)
    triangles=distinct
    edges={}
    triangle_edges=[]
    for i,triangle in enumerate(triangles):
        keys=[tuple(round(value,7) for value in vertex) for vertex in triangle]
        items=[]
        for a,b in ((0,1),(1,2),(2,0)):
            edge=tuple(sorted((keys[a],keys[b])))
            edges.setdefault(edge,[]).append(i)
            items.append(edge)
        triangle_edges.append(items)
    visited=set()
    expanded_edges=set()
    for first in range(len(triangles)):
        if first in visited:
            continue
        component=[]
        pending=[first]
        closed=True
        while pending:
            index=pending.pop()
            if index in visited:
                continue
            visited.add(index)
            component.append(index)
            for edge in triangle_edges[index]:
                owners=edges[edge]
                # Repeated face triangulations can use different diagonals:
                # interior diagonals occur twice and perimeter edges occur
                # an even number of times. The actual containment rays below
                # merge coincident crossings, independent of tessellation.
                if len(owners)<2 or len(owners)%2 or edge[0]==edge[1]:
                    closed=False
                if edge not in expanded_edges:
                    expanded_edges.add(edge)
                    pending.extend(owner for owner in owners if owner not in visited)
        if not closed:
            continue
        vertices=[vertex for index in component for vertex in triangles[index]]
        if any(point[k]<min(vertex[k] for vertex in vertices)-1e-7 or
               point[k]>max(vertex[k] for vertex in vertices)+1e-7 for k in (0,1,2)):
            # Actual vertex extents screen containment only. They do not
            # provide the ray hit or any structural attachment elevation.
            continue
        # Some IFC surface exports duplicate each triangle with reversed
        # winding. Their edge counts resemble a closed shell, but a coplanar
        # double-sided surface has no enclosed interior.
        plane=None
        for index in component:
            triangle=triangles[index]
            normal=_cross(_sub(triangle[1],triangle[0]),_sub(triangle[2],triangle[0]))
            norm=sum(value*value for value in normal)**.5
            if norm>1e-12:
                plane=(triangle[0],normal,norm)
                break
        if plane is None:
            continue
        origin,normal,norm=plane
        if not any(abs(_dot(_sub(vertex,origin),normal))>norm*1e-7
                   for index in component for vertex in triangles[index]):
            continue
        extent=max(sum((vertex[k]-point[k])**2 for k in (0,1,2))**.5
                   for vertex in vertices)
        votes=[]
        for direction in ((1.,.371,.613),(.419,1.,.277),(.233,.527,1.)):
            norm=sum(value*value for value in direction)**.5
            distance=(extent*2.+1.)/norm
            end=tuple(point[k]+direction[k]*distance for k in (0,1,2))
            hits=[]
            for index in component:
                fraction=segment_triangle_fraction(point,end,*triangles[index])
                if fraction is not None and fraction>1e-10:
                    hits.append(fraction)
            hits.sort()
            unique=[]
            for value in hits:
                if not unique or abs(value-unique[-1])>1e-9:
                    unique.append(value)
            votes.append(bool(len(unique)%2))
        if all(votes):
            return True
        if any(votes):
            # A tangent or ambiguous closed shell cannot establish clearance.
            return None
    return False


def _mesh_intersections(mesh,a,b,to_world,world_base):
    from Autodesk.Revit.DB import XYZ
    points=[]
    failed=False
    aa=(a.X,a.Y,a.Z); bb=(b.X,b.Y,b.Z)
    triangles=[]
    for i in range(mesh.NumTriangles):
        try:
            tri=mesh.get_Triangle(i)
            p=[tri.get_Vertex(k) for k in (0,1,2)]
            triangles.append(tuple((point.X,point.Y,point.Z) for point in p))
        except Exception:
            failed=True
    inside=_closed_mesh_contains(triangles,aa)
    if inside is True or inside is None:
        # A ray starting inside steel first reaches its exit/top face. That
        # face cannot be used as the underside for a valid attachment length.
        return [],True
    for triangle in triangles:
        try:
            t=segment_triangle_fraction(aa,bb,*triangle)
            if t is None: continue
            t=max(0.,min(1.,t))
            point=XYZ(a.X+(b.X-a.X)*t,a.Y+(b.Y-a.Y)*t,a.Z+(b.Z-a.Z)*t)
            height=to_world.OfPoint(point).Z if to_world else point.Z
            if height>=world_base-1e-8: points.append(height)
        except Exception:
            failed=True
    return points,failed


def _mesh_entry_heights(mesh,a,b,to_world,world_base):
    """Compatibility wrapper; richer callers also inspect mesh-read status."""
    return _mesh_intersections(mesh,a,b,to_world,world_base)[0]


def _intersection_result(element, local_a, local_b, to_world, world_base):
    """Return ('hit', Z), ('miss', None), or ('unknown', None).

    Z is the first actual Solid or Mesh intersection in host coordinates.
    Unreadable geometry, including a partially unreadable mesh or instance,
    cannot certify that a farther target has an unobstructed preferred path.
    """
    from Autodesk.Revit.DB import Options, Line, SolidCurveIntersectionOptions, Mesh
    try:
        geo=element.get_Geometry(Options())
        if geo is None:
            return 'unknown',None
        curve=Line.CreateBound(local_a,local_b)
    except Exception:
        return 'unknown',None
    intersections=[]
    primitives,failed=_checked_primitives(geo)
    if not primitives:
        return 'unknown',None
    try:
        options=SolidCurveIntersectionOptions()
    except Exception:
        return 'unknown',None
    try:
        for primitive in primitives:
            if isinstance(primitive,Mesh):
                try:
                    points,bad=_mesh_intersections(primitive,local_a,local_b,
                                                   to_world,world_base)
                    intersections.extend(points)
                    failed=failed or bad
                except Exception:
                    failed=True
                continue
            intervals=None
            try:
                intervals=primitive.IntersectWithCurve(curve,options)
                if intervals is None:
                    failed=True
                    continue
                for i in range(intervals.SegmentCount):
                    seg=intervals.GetCurveSegment(i)
                    for k in (0,1):
                        z=to_world.OfPoint(seg.GetEndPoint(k)).Z if to_world else seg.GetEndPoint(k).Z
                        if z>=world_base-1e-8:
                            intersections.append(z)
            except Exception:
                failed=True
            finally:
                if intervals is not None:
                    try: intervals.Dispose()
                    except Exception: pass
    finally:
        try: options.Dispose()
        except Exception: pass
    if failed:
        return 'unknown',None
    if intersections:
        return 'hit',min(intersections)
    return 'miss',None


def _lowest_intersection_z(element, local_a, local_b, to_world, world_base):
    """Legacy return shape; never turn unreadable geometry into an elevation."""
    state,z=_intersection_result(element,local_a,local_b,to_world,world_base)
    return z if state=='hit' else None


def ifc_framing_hit(choice, base, max_rod):
    """Nearest 3D hit on SELECTED linked beams/joists above this rod XY.

    RevitLinkInstance transform maps LINK element coordinates into host.
    AABB is used only for broad phase; actual elevation is from geometry.
    Returns (Z, linked ElementId) or None. A missing bbox is tested locally.
    """
    if choice is None or choice.link is None:
        return None
    from Autodesk.Revit.DB import XYZ
    ceiling=base.Z+float(max_rod)
    a=choice.inverse.OfPoint(XYZ(base.X,base.Y,base.Z+.01))
    b=choice.inverse.OfPoint(XYZ(base.X,base.Y,ceiling))
    candidates=[]
    for member_id,member,bounds in choice.bounds:
        if not _contains_world_xy(bounds,base):
            continue
        if bounds[5]<base.Z+.02 or bounds[4]>ceiling:
            continue
        candidates.append((member_id,member))
    # For rare unindexed IFC members, attempt actual geometry; don't let one
    # missing bounding box globally disable every other rod/roof fallback.
    for mid,member in choice.preferred.items():
        if mid in choice.indexed_ids:
            continue
        candidates.append((mid,member))
    hits=[]
    for member_id,member in candidates:
        z=_lowest_intersection_z(member,a,b,choice.transform,base.Z)
        if z is not None:
            try:
                target_length(base.Z,z,max_rod)
                hits.append((z,int(member_id)))
            except ValueError:
                pass
    if hits:
        hits.sort()
        return hits[0]
    return None


def roof_hit(doc, allowed_ids, base, max_ft):
    """Find selected roof/deck underside exactly at rod XY, including slope."""
    from Autodesk.Revit.DB import XYZ, Line, Options, ElementId, Transform
    if not allowed_ids:
        return None
    top=base.Z+float(max_ft)
    hits=[]
    for rid in allowed_ids:
        try:
            element=doc.GetElement(ElementId(int(rid)))
            if element is None:
                continue
            bb=element.get_BoundingBox(None)
            if bb is not None:
                # Evaluate all box corners in HOST coordinates; local Z is not
                # necessarily the world roof elevation when bbox has transform.
                if bb.Transform.BasisZ.Z>.999:
                    inv=bb.Transform.Inverse
                    local=inv.OfPoint(XYZ(base.X,base.Y,base.Z))
                    if not (bb.Min.X-.05<=local.X<=bb.Max.X+.05 and bb.Min.Y-.05<=local.Y<=bb.Max.Y+.05):
                        continue
                heights=[]
                for xx in (bb.Min.X,bb.Max.X):
                    for yy in (bb.Min.Y,bb.Max.Y):
                        for zz in (bb.Min.Z,bb.Max.Z):
                            heights.append(bb.Transform.OfPoint(XYZ(xx,yy,zz)).Z)
                if max(heights)<base.Z+.02 or min(heights)>top:
                    continue
            z=_lowest_intersection_z(element,XYZ(base.X,base.Y,base.Z+.01),
                      XYZ(base.X,base.Y,top),None,base.Z)
            if z is not None:
                try:
                    target_length(base.Z,z,max_ft)
                    hits.append((z,int(rid)))
                except ValueError:
                    pass
        except Exception:
            continue
    if hits:
        hits.sort()
        return hits[0]
    return None


def read_rods(hanger):
    """Read rod points before edits; never manipulate natively attached rods."""
    from Autodesk.Revit.DB import XYZ
    info=hanger.GetRodInfo()
    if info is None:
        raise ValueError('Hanger has no FabricationRodInfo')
    rods=[]
    try:
        if info.IsAttachedToStructure:
            raise ValueError('Already structurally attached; will not resize')
        for i in range(info.RodCount):
            tip=info.GetRodEndPosition(i)
            length=float(info.GetRodLength(i))
            if not 0.001<length<1000:
                raise ValueError('Rod {} has invalid current length'.format(i))
            rods.append((i,XYZ(tip.X,tip.Y,base_from_tip(tip.Z,length)),length))
    finally:
        try: info.Dispose()
        except Exception: pass
    if not rods:
        raise ValueError('Hanger has no rods')
    return rods


def plan_rods(hanger,doc,choice,max_rod_ft):
    """All rods, individual (x,y), IFC first, roof second, no approximation."""
    targets=[]
    if hasattr(choice,'bind_document'):
        choice.bind_document(doc)
    for i,base,old_length in read_rods(hanger):
        if hasattr(choice,'target_for_rod'):
            try:
                selected=choice.target_for_rod(base,max_rod_ft)
            except ValueError as ex:
                detail = choice.target_diagnostic_text(base, max_rod_ft) if hasattr(
                    choice, 'target_diagnostic_text') else ''
                raise ValueError(u'Rod {}: {}. {}'.format(i,ex,detail))
        else:
            primary=ifc_framing_hit(choice,base,max_rod_ft)
            selected=choose_target(primary,None,base.Z,max_rod_ft)
            if selected is None:
                secondary=roof_hit(doc,choice.fallback,base,max_rod_ft)
                selected=choose_target(None,secondary,base.Z,max_rod_ft)
        if selected is None:
            detail = choice.target_diagnostic_text(base, max_rod_ft) if hasattr(
                choice, 'target_diagnostic_text') else ''
            raise ValueError(u'Rod {}: no selected IFC beam/joist or roof solid above its XY. {}'.format(i, detail))
        selected.update(index=i,base=base,old=old_length)
        targets.append(selected)
    return targets


def apply_lengths(hanger,targets,regenerate,tolerance_ft=.08):
    """Set all rods transactionally; validate base remains fixed and end hits."""
    info=hanger.GetRodInfo()
    if info is None:
        raise ValueError('No fabrication rod info')
    try:
        if info.IsAttachedToStructure:
            raise ValueError('Hanger is already attached')
        info.CanRodsBeHosted=False
        for row in targets:
            if not info.SetRodLength(row['index'],row['length']):
                raise ValueError('Rod {} did not accept target length'.format(row['index']))
    finally:
        try: info.Dispose()
        except Exception: pass
    regenerate()
    check=hanger.GetRodInfo()
    if check is None:
        raise ValueError('No rod info after regeneration')
    try:
        if check.IsAttachedToStructure:
            raise ValueError('Unexpected auto attachment')
        for row in targets:
            i=row['index']
            actual=float(check.GetRodLength(i))
            tip=check.GetRodEndPosition(i)
            if abs(actual-row['length'])>.025:
                raise ValueError('Rod {} rejected exact length'.format(i))
            # On free rods, rod end is the upper endpoint. Recheck it, and the
            # inferred base, against the original fixed rod support point.
            if (abs(tip.Z-row['z'])>tolerance_ft or
                    abs((tip.Z-actual)-row['base'].Z)>tolerance_ft or
                    abs(tip.X-row['base'].X)>tolerance_ft or
                    abs(tip.Y-row['base'].Y)>tolerance_ft):
                raise ValueError('Rod {} moved support point or missed overhead solid'.format(i))
    finally:
        try: check.Dispose()
        except Exception: pass
    return True
