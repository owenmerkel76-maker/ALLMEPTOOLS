# -*- coding: utf-8 -*-
"""ROB MEP -- Auto Hanger v0.3.7 source upgrade (multi-model IFC picker)
Revit 2025 / 2027, pyRevit IronPython-compatible.

SAFE BY DESIGN:
- Works only with actual straight, horizontal Fabrication duct parts.
- Review models, categories, types or individual members in the structural
  picker, with approved native/linked fallback. Every native rod attachment
  is checked against its measured source, link instance and member.
- Revit automatically chooses nearest structure; an explicit host cannot
  be passed into the fabrication hanger API. Priority checks fail closed.
- Does not claim SMACNA certification; hardware loads/attachments require review.
- Excludes vertical/sloped pieces and inline accessories from normal hosting.
- Optional, verified experimental elbow fitting-extension fallback for unsupported runs.
- Reuses existing hanger positions to avoid duplicates.
"""
import os
import sys
import math
import traceback

from pyrevit import revit, forms, script
from Autodesk.Revit.DB import (BuiltInCategory, ElementId, FabricationPart,
                               FabricationConfiguration, FilteredElementCollector,
                               Transaction, SubTransaction, XYZ, Outline, BoundingBoxIntersectsFilter)
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
from Autodesk.Revit.Exceptions import OperationCanceledException

_DIR = os.path.dirname(__file__)
if _DIR not in sys.path:
    sys.path.insert(0, _DIR)
import planner
import structure_priority
import collision_guard
import rod_geometry
import structure_picker
import linked_obstacles
import structure_stations

DOC = revit.doc
UIDOC = revit.uidoc
OUTPUT = script.get_output()
_LINKED_CLEARANCE = None  # rebuilt for each run; never reuse stale linked geometry


def element_number(elid):
    try:
        return int(elid.Value)
    except Exception:
        return int(elid.IntegerValue)


def bic_number(bic):
    return element_number(ElementId(bic))

DUCT_CAT = bic_number(BuiltInCategory.OST_FabricationDuctwork)
HANGER_CAT = bic_number(BuiltInCategory.OST_FabricationHangers)
STRUCT_CATS = set([bic_number(BuiltInCategory.OST_StructuralFraming),
                   bic_number(BuiltInCategory.OST_Floors),
                   bic_number(BuiltInCategory.OST_Roofs),
                   bic_number(BuiltInCategory.OST_Stairs)])


def cat_of(e):
    try:
        return element_number(e.Category.Id)
    except Exception:
        return None


def is_fabrication_duct(e):
    # FabricationPart.IsAHanger is a METHOD, unlike a service button's
    # IsAHanger (a property). v0.3 mistakenly tested the bound methods as
    # booleans, rejecting every valid duct in the Revit selection filter.
    try:
        return (e is not None and isinstance(e, FabricationPart)
                and cat_of(e) == DUCT_CAT and not e.IsAHanger())
    except Exception:
        return False


# Descriptions are only used to EXCLUDE obvious inline devices, never to
# positively authorize a hanger host. Your FAB database may use custom names.
ACCESSORY_TOKENS = ('damper', 'fire smoke', 'fire/smoke', 'smoke/fire',
                    'access door', 'access panel', 'volume control',
                    'vcd', 'fsd', 'sdd', 'backdraft', 'back draft',
                    'sleeve', 'silencer', 'attenuator', 'sensor',
                    'terminal unit', 'vav ', 'balancing damper')


def is_inline_accessory(part):
    """Exclude known inline devices before IsAStraight can authorize hosting.

    This intentionally fails closed only for recognizable product metadata;
    unrecognized devices must still pass ordinary geometry and 3-D checks.
    """
    if part is None or not isinstance(part, FabricationPart):
        return False
    names=[]
    for prop in ('ProductName','ProductLongDescription','ProductShortDescription',
                 'Alias','Name'):
        try:
            value=getattr(part,prop)
            if value:
                names.append(str(value).lower())
        except Exception:
            pass
    label=' '.join(names)
    return any(token in label for token in ACCESSORY_TOKENS)


def is_duct_straight(e):
    # FabricationPart.IsAStraight is also a METHOD on Revit 2025/2027.
    # We allow selecting fittings too so the user can preselect full runs;
    # only straight parts are passed to the hanger planning code.
    try:
        return (is_fabrication_duct(e) and bool(e.IsAStraight())
                and not bool(e.IsATap()) and not is_inline_accessory(e))
    except Exception:
        return False


class DuctFilter(ISelectionFilter):
    def AllowElement(self, e):
        # Allow duct fittings to be picked along with straight duct; they are
        # skipped safely after the pick. This supports broad selection of runs.
        return is_fabrication_duct(e)
    def AllowReference(self, ref, point):
        return False


class StructureFilter(ISelectionFilter):
    def AllowElement(self, e):
        return cat_of(e) in STRUCT_CATS
    def AllowReference(self, ref, point):
        return False


def selected_or_pick(flt, prompt, startup_ids):
    # Snapshot initial UI selection ONCE before PickObjects. Otherwise the
    # second structure-selection stage could accidentally reuse a selection
    # modified by the first stage instead of prompting for structure.
    existing=[]
    for eid in startup_ids:
        el=DOC.GetElement(eid)
        if el is not None and flt.AllowElement(el):
            existing.append(el)
    if existing:
        return existing
    refs=UIDOC.Selection.PickObjects(ObjectType.Element, flt, prompt)
    out=[]
    seen=set()
    for r in refs:
        if r is None:
            continue
        eid=element_number(r.ElementId)
        if eid not in seen:
            seen.add(eid)
            el=DOC.GetElement(r.ElementId)
            if el is not None and flt.AllowElement(el):
                out.append(el)
    return out


def xyz_tuple(pt):
    return (pt.X,pt.Y,pt.Z)


def profile_size(part, connectors):
    """Read connector physical sizes, never silently guess from a name."""
    from Autodesk.Revit.DB import ConnectorProfileType
    for c in connectors:
        try:
            if c.Shape == ConnectorProfileType.Round:
                d = 2.0*float(c.Radius)
                if d > 0:
                    return 'round', d, d
            if c.Shape == ConnectorProfileType.Rectangular:
                w,h=float(c.Width),float(c.Height)
                if w > 0 and h > 0:
                    return 'rectangular',w,h
            if c.Shape == ConnectorProfileType.Oval:
                w,h=float(c.Width),float(c.Height)
                if w > 0 and h > 0:
                    return 'oval',w,h
        except Exception:
            pass
    # Fabrication dimension definitions often have names like Width/Depth/Diameter.
    dimensions={}
    try:
        for dim in part.GetDimensions():
            dimensions[str(dim.Name).strip().lower()]=float(part.GetDimensionValue(dim))
    except Exception:
        pass
    diameter=dimensions.get('diameter',0.0)
    if diameter > 0:
        return 'round',diameter,diameter
    w=dimensions.get('width',0)
    h=dimensions.get('height',dimensions.get('depth',0))
    if w > 0 and h > 0:
        return 'rectangular',w,h
    return None,0,0


def extract_segment(part):
    """Get actual axis endpoints, with Revit Connector objects retained for placement."""
    ports=[]
    for c in part.ConnectorManager.Connectors:
        try:
            p=xyz_tuple(c.Origin)
            if not any(planner.distance(p,item[0]) < 1e-5 for item in ports):
                ports.append((p,c))
        except Exception:
            pass
    best=None
    longest=0.0
    for i in range(len(ports)):
        for j in range(i+1,len(ports)):
            length=planner.distance(ports[i][0],ports[j][0])
            if length > longest:
                longest=length
                best=(ports[i],ports[j])
    if best is None or longest < 0.5:
        return None,'Cannot read two usable end connectors / too short'
    a,ca=best[0]
    b,cb=best[1]
    # Vertical/sloped ducts are out of v0.1 support. 1/4 inch change over each
    # 10 ft horizontal avoids unintentionally treating intentional slope as flat.
    horiz=math.sqrt((b[0]-a[0])**2+(b[1]-a[1])**2)
    if horiz < 0.5 or abs(b[2]-a[2]) > max(0.02,0.002*horiz):
        return None,'Non-horizontal / vertical duct requires another support design'
    shape,w,h=profile_size(part,[ca,cb])
    if shape is None:
        return None,'Unknown duct size/profile: not safe to set spacing'
    try:
        service_id=int(part.ServiceId)
        service_name=str(part.ServiceName)
    except Exception:
        return None,'Cannot identify fabrication ServiceId; no cross-service fallback'
    return {'id':element_number(part.Id),'part':part,'a':a,'b':b,
            'ca':ca,'cb':cb,'shape':shape,'w':w,'h':h,
            'service_id':service_id,'service_name':service_name},None


def service_hanger_choices(needed_ids):
    """Return loaded hanger buttons PER FABRICATION SERVICE ID.

    Service IDs, not display names or UI palette selection, are the identity.
    Do not fall back to another service when a palette is absent.
    """
    config=FabricationConfiguration.GetFabricationConfiguration(DOC)
    inventory={}
    for sid in sorted(needed_ids):
        data={'name':'Service {}'.format(sid), 'buttons':[]}
        inventory[sid]=data
        if config is None:
            continue
        try:
            service=config.GetService(int(sid))
            if service is None:
                continue
            data['name']=str(service.Name)
            for palette in range(service.PaletteCount):
                try:
                    palette_name=str(service.GetPaletteName(palette))
                except Exception:
                    palette_name='Palette {}'.format(palette)
                for button_index in range(service.GetButtonCount(palette)):
                    try:
                        button=service.GetButton(palette,button_index)
                        if button is not None and button.IsAHanger and button.IsValid():
                            label='{}  /  {}  [P{} B{}]'.format(
                                palette_name,str(button.Name),palette+1,button_index+1)
                            data['buttons'].append((label,button))
                    except Exception:
                        pass
        except Exception:
            continue
        data['buttons'].sort(key=lambda pair:pair[0].lower())
    return inventory



def existing_by_host():
    grouped={}
    for h in (FilteredElementCollector(DOC)
              .OfCategory(BuiltInCategory.OST_FabricationHangers)
              .WhereElementIsNotElementType()):
        if not isinstance(h,FabricationPart):
            continue
        try:
            info=h.GetHostedInfo()
            if info is None:
                continue
            host=element_number(info.HostId)
            try:
                p=xyz_tuple(h.Origin)
            except Exception:
                bb=h.get_BoundingBox(None)
                p=xyz_tuple((bb.Min+bb.Max)*0.5)
            grouped.setdefault(host,[]).append(p)
        except Exception:
            continue
    return grouped


def branch_stations_for_run(run, all_segments):
    """Simple branch geometry heuristic; supplements end-of-run support.
    It does not certify complex tap/branch fittings, see report.
    """
    axis=run['direction']
    start=run['origin']
    length=max(t[1] for t in run['pieces'])
    memberids=set(s['id'] for _,_,s in run['pieces'])
    max_width=max(s['w'] for _,_,s in run['pieces'])
    service_id=run['pieces'][0][2]['service_id']
    out=[]
    for seg in all_segments:
        if seg['id'] in memberids or seg['service_id'] != service_id:
            continue
        other_dir=planner.unit(planner.sub(seg['b'],seg['a']))
        if abs(planner.dot(other_dir,axis)) > 0.83:
            continue
        for p in (seg['a'],seg['b']):
            s=planner.projections(p,start,axis)
            if s<0.5 or s>length-0.5:
                continue
            closest=planner.add(start,planner.mul(axis,s))
            lateral=planner.distance(p,closest)
            if (abs(p[2]-closest[2]) < (6.0/12.0)
                    and lateral < (max_width+seg['w'])*0.5+0.75):
                if not any(abs(x-s)<1.0 for x in out):
                    out.append(s)
    return out


def connected_branch_stations_for_run(run):
    """Detect branch fitting connectors attached to selected straight runs.

    Includes model-connected takeoffs even if a user selected only straights.
    Only fitting parts with >=3 connectors and same fabrication service are
    candidates, and their ports must be near the actual run axis. Geometry
    remains a heuristic; tee/tap exceptions require visual coordination.
    """
    origin=run['origin']
    axis=run['direction']
    length=max(item[1] for item in run['pieces'])
    widths=[item[2]['w'] for item in run['pieces']]
    max_width=max(widths)
    sid=run['pieces'][0][2]['service_id']
    visited=set()
    stations=[]
    for lo,hi,piece in run['pieces']:
        try:
            connectors=piece['part'].ConnectorManager.Connectors
        except Exception:
            continue
        for conn in connectors:
            try:
                refs=conn.AllRefs
            except Exception:
                continue
            for link in refs:
                try:
                    fitting=link.Owner
                    if (not isinstance(fitting,FabricationPart)
                            or cat_of(fitting)!=DUCT_CAT
                            or fitting.IsAHanger() or fitting.IsAStraight()
                            or int(fitting.ServiceId)!=sid):
                        continue
                    eid=element_number(fitting.Id)
                    if eid in visited:
                        continue
                    visited.add(eid)
                    ports=[xyz_tuple(fconn.Origin)
                           for fconn in fitting.ConnectorManager.Connectors]
                    if len(ports)<3:
                        continue
                    nearby=[]
                    for pos in ports:
                        s=planner.projections(pos,origin,axis)
                        projection=planner.add(origin,planner.mul(axis,s))
                        lateral=planner.distance(pos,projection)
                        if (0.3<s<length-0.3 and
                                abs(pos[2]-projection[2])<0.5 and
                                lateral < 0.5*max_width+1.0):
                            nearby.append(s)
                    if nearby:
                        center=sum(nearby)/float(len(nearby))
                        if not any(abs(t-center)<0.75 for t in stations):
                            stations.append(center)
                except Exception:
                    continue
    return stations


def _end_connections(piece, end_point):
    """Return connected non-self owners at an actual run-end connector."""
    owners=[]
    for conn in (piece['ca'],piece['cb']):
        try:
            if planner.distance(xyz_tuple(conn.Origin),end_point)>0.3:
                continue
            for link in conn.AllRefs:
                owner=link.Owner
                if owner is None or element_number(owner.Id)==piece['id']:
                    continue
                if not any(element_number(item.Id)==element_number(owner.Id)
                           for item in owners):
                    owners.append(owner)
        except Exception:
            continue
    return owners


def _connectors_of_element(el):
    try:
        return list(el.ConnectorManager.Connectors)
    except Exception:
        pass
    try:
        return list(el.MEPModel.ConnectorManager.Connectors)
    except Exception:
        return []


def _element_center(el):
    try:
        bb=el.get_BoundingBox(None)
        if bb is not None:
            return xyz_tuple((bb.Min+bb.Max)*0.5)
    except Exception:
        pass
    return None


def _looks_like_downturned_fitting(fitting, origin_z):
    """Detect a lower port or an elbow outlet directed vertically down."""
    for conn in _connectors_of_element(fitting):
        try:
            if conn.Origin.Z < origin_z-0.25:
                return True
            vec=conn.CoordinateSystem.BasisZ
            if vec.Z < -0.8 and conn.Origin.Z<=origin_z+0.25:
                return True
        except Exception:
            continue
    return False



def end_needs_close_support(run):
    """Detect actual fitting/turn vs ordinary straight-run endpoint.

    SMACNA close-to-elbow check is applied at an END with a real fitting.
    Open ends, unselected straight continuations and air terminals are not
    automatically misclassified as elbows needing a second hanger.
    """
    length=max(p[1] for p in run['pieces'])
    out=[]
    for endstation in (0.0,length):
        end=planner.add(run['origin'],planner.mul(run['direction'],endstation))
        adjacent=[]
        for lo,hi,piece in run['pieces']:
            if min(abs(lo-endstation),abs(hi-endstation))<.3:
                adjacent.extend(_end_connections(piece,end))
        required=False
        for other in adjacent:
            try:
                if not isinstance(other,FabricationPart) or other.IsAHanger():
                    continue
                if other.IsAStraight() and not is_inline_accessory(other):
                    continue
                # A connected change in direction/transition/branch deserves
                # proximity review. Accessories alone are not close-turn rules.
                if is_inline_accessory(other):
                    continue
                required=True
            except Exception:
                continue
        out.append(required)
    return tuple(out)


def terminal_drops_for_run(run):
    """Inspect real connector graph, bounded to 5 hops near each run end.

    Look for an end elbow leading down to a connected Revit air terminal.
    Unconnected diffuser families cannot be certified and remain a warning.
    No hangers are placed on vertical drops, diffuser families or elbows.
    """
    out=[]
    length=max(piece[1] for piece in run['pieces'])
    memberids=set(piece['id'] for _,_,piece in run['pieces'])
    for endname,station in (('start',0.0),('end',length)):
        endpos=planner.add(run['origin'],planner.mul(run['direction'],station))
        nearpieces=[p for lo,hi,p in run['pieces']
                    if (lo<0.3 if endname=='start' else length-hi<0.3)]
        seeds=[]
        for part in nearpieces:
            seeds.extend(_end_connections(part,endpos))
        for seed in seeds:
            try:
                if (not isinstance(seed,FabricationPart) or cat_of(seed)!=DUCT_CAT
                        or seed.IsAHanger() or seed.IsAStraight()):
                    continue
                # Starts with a FAB fitting (usually an elbow), not another
                # selected straight and not a distant network connection.
                has_down=_looks_like_downturned_fitting(seed,endpos[2])
                visited=set(memberids)
                queue=[(seed,0)]
                diffuser_id=None
                drop_seen=False
                while queue:
                    el,depth=queue.pop(0)
                    eid=element_number(el.Id)
                    if eid in visited or depth>5:
                        continue
                    visited.add(eid)
                    pos=_element_center(el)
                    if pos is not None:
                        if (math.hypot(pos[0]-endpos[0],pos[1]-endpos[1])>7.0
                                or abs(pos[2]-endpos[2])>18.0):
                            continue
                    if cat_of(el)==bic_number(BuiltInCategory.OST_DuctTerminal):
                        if pos is not None and pos[2]<endpos[2]-0.4:
                            diffuser_id=eid
                        break
                    for connector in _connectors_of_element(el):
                        try:
                            if connector.Origin.Z<endpos[2]-0.4:
                                drop_seen=True
                            for ref in connector.AllRefs:
                                other=ref.Owner
                                if other is not None and element_number(other.Id) not in visited:
                                    queue.append((other,depth+1))
                        except Exception:
                            pass
                    if len(visited)>38:
                        break
                if diffuser_id is not None and (has_down or drop_seen):
                    out.append((endname,'connected',diffuser_id))
                    break
                if has_down or drop_seen:
                    out.append((endname,'possible',eid))
                    break
            except Exception:
                continue
    return out


def side_tap_clearance_intervals(run, max_rod_ft):
    """Collect nearby fabrication fittings/other ducts, project AABBs.

    Conservative initial screening for support straps and rod paths, including
    side taps, other branch ducts and drops. This cannot replace a true
    solid-to-solid interference check or rod routing review.
    """
    length=max(part[1] for part in run['pieces'])
    width=max(max(s['w'],s['h']) for _,_,s in run['pieces'])
    lateral=0.5*width+0.75       # 9-inch preliminary side hardware allowance
    vertical=0.5*width+0.75
    end=planner.add(run['origin'],planner.mul(run['direction'],length))
    lo=[min(run['origin'][i],end[i]) for i in range(3)]
    hi=[max(run['origin'][i],end[i]) for i in range(3)]
    # This is a near-duct fitting/side-tap BODY screening pass only.
    # Do not exclude hanger locations simply because other duct is overhead
    # anywhere in the maximum rod-height column. The actual created rods
    # are checked separately after creation against higher MEP.
    # Linked MEP remains outside this broad-phase screening.
    bmin=XYZ(lo[0]-lateral-1,lo[1]-lateral-1,lo[2]-vertical)
    bmax=XYZ(hi[0]+lateral+1,hi[1]+lateral+1,hi[2]+vertical+0.5)
    envelope=BoundingBoxIntersectsFilter(Outline(bmin,bmax))
    nearby=[]
    for category in (BuiltInCategory.OST_FabricationDuctwork,
                     BuiltInCategory.OST_DuctAccessory,
                     BuiltInCategory.OST_FabricationPipework,
                     BuiltInCategory.OST_PipeAccessory,
                     BuiltInCategory.OST_PipeCurves,
                     BuiltInCategory.OST_DuctCurves):
        try:
            nearby.extend(list(FilteredElementCollector(DOC)
                .OfCategory(category).WhereElementIsNotElementType()
                .WherePasses(envelope)))
        except Exception:
            continue
    memberids=set(piece['id'] for _,_,piece in run['pieces'])
    occupied=[]
    rejected=[]
    for other in nearby:
        try:
            eid=element_number(other.Id)
            if eid in memberids:
                continue
            # Adjacent SAME-AXIS straight lengths are an extension of the
            # selected run, not an obstacle on its own. Crossed branches and
            # nearby parallel runs remain conservatively screened.
            if is_duct_straight(other):
                ports=[xyz_tuple(c.Origin) for c in other.ConnectorManager.Connectors]
                if len(ports)>=2:
                    od=planner.unit(planner.sub(ports[1],ports[0]))
                    center=tuple((ports[0][i]+ports[1][i])/2 for i in range(3))
                    station=planner.projections(center,run['origin'],run['direction'])
                    project=planner.add(run['origin'],planner.mul(run['direction'],station))
                    if (abs(planner.dot(od,run['direction']))>0.997
                            and planner.distance(center,project)<0.15):
                        continue
            bbox=other.get_BoundingBox(None)
            if bbox is None:
                continue
            interval=planner.blocked_interval_from_bbox(
                run,xyz_tuple(bbox.Min),xyz_tuple(bbox.Max),
                lateral_ft=lateral,below_ft=vertical,
                rise_ft=vertical+0.5,along_clearance_ft=0.35)
            if interval is not None:
                occupied.append(interval)
                rejected.append(eid)
        except Exception:
            continue
        if len(occupied)>150:
            raise RuntimeError('More than 150 nearby duct obstructions; select a smaller area')
    return occupied,rejected



# Native-MEP broad phase is deliberately separate from structure attachment.
# Attachment to a beam can be valid while a rod crosses duct/pipe along the way.
# The first pass (side_tap_clearance_intervals) is along-run planning. This
# second pass verifies actual native hanger rod positions AFTER CreateHanger.
CLASH_CATS=set([bic_number(BuiltInCategory.OST_FabricationDuctwork),
                bic_number(BuiltInCategory.OST_FabricationPipework),
                bic_number(BuiltInCategory.OST_DuctAccessory),
                bic_number(BuiltInCategory.OST_PipeAccessory),
                bic_number(BuiltInCategory.OST_DuctCurves),
                bic_number(BuiltInCategory.OST_PipeCurves),
                bic_number(BuiltInCategory.OST_MechanicalEquipment)])


def native_world_bbox(el):
    """AABB corners with BoundingBox.Transform, not Min/Max alone."""
    bbox=el.get_BoundingBox(None)
    if bbox is None:
        return None
    pts=[]
    for x in (bbox.Min.X,bbox.Max.X):
        for y in (bbox.Min.Y,bbox.Max.Y):
            for z in (bbox.Min.Z,bbox.Max.Z):
                pt=bbox.Transform.OfPoint(XYZ(x,y,z))
                pts.append((pt.X,pt.Y,pt.Z))
    return collision_guard.bbox_from_corners(pts)


def check_new_rod_clashes(hanger,host_id,max_rod_ft,enabled=True):
    """Return safe, reason. Retains native screening and checks linked paths.

    Uses TWO possible vertical directions from GetRodEndPosition because
    Autodesk does not document which end it means. Result is conservative:
    false positives require review. Linked structural obstacles use actual
    intersections, while linked MEP envelopes remain conservative screening.
    """
    if not enabled:
        return True,'3D rod clearance check disabled by user'
    info=None
    try:
        info=hanger.GetRodInfo()
        if info is None or info.RodCount<1:
            return False,'Unable to inspect hanger rods for MEP interference'
        linked_paths=[]
        approved=[]
        for rod_i in range(info.RodCount):
            endpoint=info.GetRodEndPosition(rod_i)
            length=float(info.GetRodLength(rod_i))
            if length<=0 or length>max_rod_ft:
                return False,'Rod {} has invalid length for clash check'.format(rod_i)
            linked_paths.append({'index':rod_i,
                'base':XYZ(endpoint.X,endpoint.Y,endpoint.Z-length),
                'tip':endpoint})
            attached=info.GetRodAttachedElementId(rod_i)
            if attached is not None:
                link_id=element_number(attached.LinkInstanceId)
                approved.append({'index':rod_i,
                    'link_id':link_id if link_id>0 else None,
                    'id':element_number(attached.LinkedElementId) if link_id>0
                         else element_number(attached.HostElementId),
                    'z':endpoint.Z})
            envelope=collision_guard.rod_envelope((endpoint.X,endpoint.Y,endpoint.Z),length,0.10)
            lo=XYZ(envelope[0],envelope[1],envelope[2])
            hi=XYZ(envelope[3],envelope[4],envelope[5])
            collector=(FilteredElementCollector(DOC).WhereElementIsNotElementType()
                .WherePasses(BoundingBoxIntersectsFilter(Outline(lo,hi))))
            seen=0
            for el in collector:
                eid=element_number(el.Id)
                if eid in (host_id,element_number(hanger.Id)):
                    continue
                category=cat_of(el)
                if category not in CLASH_CATS:
                    continue
                seen+=1
                if seen>120:
                    return False,'Over 120 possible MEP obstacles near hanger rod; narrow selection'
                world_box=native_world_bbox(el)
                if world_box is None:
                    return False,'MEP element {} has uncheckable 3D envelope'.format(eid)
                if collision_guard.intersects(envelope,world_box):
                    return False,collision_guard.reason_for_clash(rod_i,eid,str(el.Category.Name))
        if _LINKED_CLEARANCE is not None:
            linked_issues=_LINKED_CLEARANCE.check(linked_paths,approved_targets=approved,host_id=host_id)
            if linked_issues:
                return False,linked_issues[0]
        return True,'No potential MEP rod envelope or linked structural-path conflicts found'
    except Exception as ex:
        return False,'Rod collision inspection unavailable: {}'.format(ex)
    finally:
        if info is not None:
            try: info.Dispose()
            except Exception: pass


def fitting_extension_candidates_for_run(run):
    """Potential fitting extensions at run ends, not proof of a straight throat.

    Revit supports fabrication hangers on *some* fitting extensions, but no
    universal API exposes a certified straight throat length for all database
    patterns. We therefore create a short list of connector-based probes; on
    placement each is tried in a rollback-able SubTransaction and must pass
    CreateHanger plus actual attachment/host verification. Do not preview them
    as certain placements.
    """
    length=max(piece[1] for piece in run['pieces'])
    seen=set()
    candidates=[]
    for endname,station in (('start',0.0),('end',length)):
        endpos=planner.add(run['origin'],planner.mul(run['direction'],station))
        for lo,hi,piece in run['pieces']:
            if min(abs(lo-station),abs(hi-station))>0.3:
                continue
            for part in _end_connections(piece,endpos):
                try:
                    if (not isinstance(part,FabricationPart) or cat_of(part)!=DUCT_CAT
                            or part.IsAHanger() or part.IsAStraight() or part.IsATap()
                            or is_inline_accessory(part)
                            or int(part.ServiceId)!=piece['service_id']):
                        continue
                    connectors=_connectors_of_element(part)
                    # only two-port elbows/angles: tees, taps, dampers and
                    # multi-port components must never be used as a fallback
                    if len(connectors)!=2:
                        continue
                    # choose the connector physically touching the run end.
                    linked=[c for c in connectors
                            if planner.distance(xyz_tuple(c.Origin),endpos)<0.30]
                    if not linked:
                        continue
                    incoming=linked[0]
                    inward=incoming.CoordinateSystem.BasisZ
                    axis=run['direction']
                    if (abs(inward.Z)>0.12 or
                            abs(inward.X*axis[0]+inward.Y*axis[1])<0.985):
                        continue
                    bbox=part.get_BoundingBox(None)
                    if bbox is None:
                        continue
                    # Geometric broad-phase only. AABB length is an upper bound
                    # and need not equal the usable straight throat. API probes
                    # below are still required to confirm actual host eligibility.
                    origin=xyz_tuple(incoming.Origin)
                    max_depth=min(1.25,planner.norm(planner.sub(
                        xyz_tuple(bbox.Max),xyz_tuple(bbox.Min))))
                    if max_depth<0.4:
                        continue
                    key=element_number(part.Id)
                    if key in seen:
                        continue
                    seen.add(key)
                    candidates.append({'id':key,'part':part,'connector':incoming,
                                       'service_id':int(part.ServiceId),
                                       'shape':piece['shape'],
                                       'probe_distances':tuple(d for d in
                                           (0.35,0.5,0.75,1.0)
                                           if d<max_depth-0.08),
                                       'endname':endname,'near_piece':piece})
                except Exception:
                    continue
    return [c for c in candidates if c['probe_distances']]


def attached_to_proposed_host(hanger, host_id):
    """Reject any Revit-created hanger on an unexpected host object."""
    try:
        hosted=hanger.GetHostedInfo()
        return hosted is not None and element_number(hosted.HostId)==host_id
    except Exception:
        return False




def retry_native_attachment(hanger, choice, maximum):
    """Re-ask Revit to locate nearest structure, then recheck ALL rod IDs.

    It cannot specify IFC targets. A wrong target is still rejected.
    """
    try:
        info=hanger.GetRodInfo()
        if info is None:
            return False,'No rod info on first attachment attempt',None
        try:
            info.CanRodsBeHosted=True
            info.AttachToStructure()
        finally:
            try: info.Dispose()
            except Exception: pass
        DOC.Regenerate()
    except Exception as ex:
        return False,'Reattachment request unavailable: {}'.format(ex),None
    return choice.verify(hanger,maximum)



def check_measured_draft_rod_clashes(hanger,host_id,targets,enabled=True):
    """Test ONLY measured vertical rod paths, not mirrored 20-ft envelopes.

    Native MEP broadphase: conservative AABB check at actual sized rod XY/Z.
    Linked paths are checked separately; final hardware needs field review.
    """
    if not enabled:
        return True,'Draft rod MEP scan disabled'
    for target in targets:
        start=target['base']
        stop=target['z']
        pad=.09
        lo=XYZ(start.X-pad,start.Y-pad,start.Z+.09)
        hi=XYZ(start.X+pad,start.Y+pad,stop+pad)
        search=(FilteredElementCollector(DOC).WhereElementIsNotElementType()
             .WherePasses(BoundingBoxIntersectsFilter(Outline(lo,hi))))
        rod_box=(lo.X,lo.Y,lo.Z,hi.X,hi.Y,hi.Z)
        count=0
        for item in search:
            item_id=element_number(item.Id)
            if item_id in (host_id,element_number(hanger.Id)):
                continue
            if cat_of(item) not in CLASH_CATS:
                continue
            count+=1
            if count>140:
                return False,'Too many potential nearby MEP conflicts at rod {}'.format(target['index'])
            bbox=native_world_bbox(item)
            if bbox is None:
                return False,'MEP element {} has no readable geometry envelope'.format(item_id)
            if collision_guard.intersects(rod_box,bbox):
                return False,'Rod {} may intersect native MEP {}'.format(target['index'],item_id)
    if _LINKED_CLEARANCE is not None:
        paths=[{'index':t['index'],'base':t['base'],
                'tip':XYZ(t['base'].X,t['base'].Y,t['z'])} for t in targets]
        linked_issues=_LINKED_CLEARANCE.check(paths,approved_targets=targets,host_id=host_id)
        if linked_issues:
            return False,linked_issues[0]
    return True,'No nearby MEP envelope or linked structural-path conflicts at measured lengths'


def draft_label(hanger, original_reason, targets=None):
    """Never retain an unattached hanger without visible model marking."""
    from Autodesk.Revit.DB import BuiltInParameter
    kinds=','.join('{}:{}:{}:R{}'.format(t['tier'],
        'LINK{}'.format(t['link_id']) if t.get('link_id') is not None else 'HOST',
        t['id'],t['index']) for t in (targets or []))
    label='AUTO HANGER DRAFT / GEOMETRY-SIZED / UNATTACHED / TARGETS {} / MANUAL ANCHORAGE REQUIRED'.format(kinds)
    targets=[]
    try:
        targets.append(hanger.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS))
    except Exception:
        pass
    for name in ('Comments','Fabrication Notes'):
        try: targets.append(hanger.LookupParameter(name))
        except Exception: pass
    for p in targets:
        try:
            if p is not None and not p.IsReadOnly:
                # Do not wipe out existing unrelated notes.
                prior=p.AsString() or ''
                new_text=label if not prior else (prior+' | '+label)
                p.Set(new_text)
                return True
        except Exception:
            continue
    return False


def create_unattached_draft(button, part, host_id, connector, distance, reason,
                            choice, max_rod, check_clashes=True):
    """Produce only a clearly marked fabrication HANGER, never a false link.

    The model element is hosted to the duct but NOT to a structural member.
    Every rod is sized independently to selected IFC joist/beam solids FIRST,
    then selected native roof/deck solids. Unmeasured candidates are discarded.
    No hanger is claimed to have a structural connection.
    """
    sub=SubTransaction(DOC)
    begun=False
    try:
        sub.Start(); begun=True
        hanger=FabricationPart.CreateHanger(DOC,button,part.Id,
                                            connector,float(distance),False)
        if hanger is None:
            raise Exception('Revit could not create unhosted hanger')
        DOC.Regenerate()
        if not attached_to_proposed_host(hanger,host_id):
            raise Exception('Draft hanger was not hosted on the selected duct')
        info=hanger.GetRodInfo()
        if info is None or info.RodCount<1:
            raise Exception('Draft has no rod information')
        try:
            if info.IsAttachedToStructure:
                raise Exception('Draft unexpectedly auto-attached to structure')
            info.CanRodsBeHosted=False
        finally:
            try: info.Dispose()
            except Exception: pass
        plan=rod_geometry.plan_rods(hanger,DOC,choice,max_rod)
        rod_geometry.apply_lengths(hanger,plan,DOC.Regenerate)
        clear,why=check_measured_draft_rod_clashes(hanger,host_id,plan,check_clashes)
        if not clear:
            raise Exception(why)
        if not draft_label(hanger,reason,targets=plan):
            raise Exception('Cannot mark hanger as UNATTACHED in Comments; draft not kept')
        DOC.Regenerate()
        # Geometric length is NOT a structurally attached / anchored rod.
        # Exact clash/anchor checks are still required in Revit.
        hid=element_number(hanger.Id)
        sub.Commit(); begun=False
        targets=', '.join('{}:{} rod {}'.format(p['tier'],p['id'],p['index']) for p in plan)
        return True,hid,'GEOMETRY-SIZED {} rods [{}]; UNATTACHED'.format(len(plan),targets)
    except Exception as ex:
        if begun:
            try: sub.RollBack()
            except Exception: pass
        return False,None,str(ex)


def probe_structural_station(job, choice, cfg):
    """Measure EVERY actual fabrication rod and always discard the probe."""
    sub=SubTransaction(DOC)
    begun=False
    bases=[]
    if hasattr(choice,'last_target_diagnostics'):
        choice.last_target_diagnostics=[]
    try:
        sub.Start(); begun=True
        piece=job['piece']
        hanger=FabricationPart.CreateHanger(DOC,job['button'],piece['part'].Id,
                                            piece['ca'],float(job['from_a']),False)
        if hanger is None:
            raise ValueError('Revit could not create a station probe')
        DOC.Regenerate()
        if not attached_to_proposed_host(hanger,piece['id']):
            raise ValueError('Station probe hosted on an unexpected duct')
        info=hanger.GetRodInfo()
        if info is None:
            raise ValueError('Station probe has no rod information')
        try:
            if info.RodCount<1 or info.IsAttachedToStructure:
                raise ValueError('Station probe needs measurable unattached rods')
            info.CanRodsBeHosted=False
        finally:
            info.Dispose()
        bases=[(base.X,base.Y,base.Z) for index,base,length in rod_geometry.read_rods(hanger)]
        if not bases:
            raise ValueError('No readable station-probe rods')
        plan=rod_geometry.plan_rods(hanger,DOC,choice,cfg['max_rod'])
        if len(plan)!=len(bases):
            raise ValueError('Not all station-probe rods were measured')
        rod_geometry.apply_lengths(hanger,plan,DOC.Regenerate)
        clear,why=check_measured_draft_rod_clashes(hanger,piece['id'],plan,
                                                 cfg['reject_rod_clashes'])
        if not clear:
            raise ValueError(why)
        return True,bases,'All {} rods have measured approved targets'.format(len(plan))
    except Exception as ex:
        return False,bases,str(ex)
    finally:
        # A rollback failure must escape to the enclosing transaction. Never
        # proceed after an uncertain probe cleanup, even if geometry succeeded.
        if begun:
            status=sub.RollBack()
            if status is not None and str(status)!='RolledBack':
                raise ValueError('Station probe rollback did not complete; stopping placement')


def align_structure_tasks(tasks, choice, cfg, stats, issues, notes):
    """Bounded rolled-back probes, followed by run-wide coverage selection."""
    contexts=[]
    for job in tasks:
        context=job['run_context']
        if not any(context is existing for existing in contexts):
            contexts.append(context)
    selected=[]
    total=max(1,len(contexts))
    budget=600
    stats['structure_probes']=0
    stats['structure_shifted']=0
    stats['structure_withheld']=0
    roles={'preferred_first':('preferred','fallback'),
           'preferred_only':('preferred',),'fallback_only':('fallback',)}[choice.priority_mode]
    boxes=[box for source in choice.sources for role in roles
           for box in source.bounds[role].values()]
    with forms.ProgressBar(title='Checking steel connections: {value}/{max_value} runs',
                           cancellable=True,step=1) as progress:
        for run_index,context in enumerate(contexts):
            if progress.cancelled:
                raise ValueError('Structural station search cancelled; probes rolled back')
            originals=sorted([job for job in tasks if job['run_context'] is context],
                             key=lambda job:job['station'])
            groups=[]; probes=[]; reasons=[]; candidate_failures=[]; cache={}
            run_budget=160

            def probe(job):
                key=(job['piece']['id'],round(job['station'],6))
                if key not in cache:
                    if progress.cancelled:
                        raise ValueError('Structural station search cancelled; probes rolled back')
                    progress.title='Checking steel connections: run {} / {} | probe {}'.format(
                        run_index+1,total,stats['structure_probes']+1)
                    progress.update_progress(run_index,total)
                    if progress.cancelled:
                        raise ValueError('Structural station search cancelled; probes rolled back')
                    cache[key]=probe_structural_station(job,choice,cfg)
                    stats['structure_probes']+=1
                return cache[key]

            for job in originals:
                if budget<=0 or run_budget<=0:
                    outcome=(False,[],'Station search budget reached')
                else:
                    outcome=probe(job)
                    budget-=1; run_budget-=1
                ok,bases,why=outcome
                groups.append([job] if ok else [])
                probes.append(bases); reasons.append(why); candidate_failures.append(None)
            chosen=structure_stations.select_layout(groups,originals,context['length'],
                context['maximum'],context['branches'],context['existing'],context['end_limits'])
            if chosen is None:
                # Expand even a successful original station: a neighboring
                # shift can otherwise force excessive spacing or endpoint gaps.
                for index,job in enumerate(originals):
                    candidates=structure_stations.candidate_jobs(planner,context['run'],job,
                        probes[index],boxes,context['blocked'],context['branches'],
                        context['existing'],limit=24)
                    for candidate in candidates:
                        key=(candidate['piece']['id'],round(candidate['station'],6))
                        if key in cache:
                            continue
                        if budget<=0 or run_budget<=0:
                            break
                        ok,bases,why=probe(candidate)
                        budget-=1; run_budget-=1
                        if ok:
                            groups[index].append(candidate)
                        elif candidate_failures[index] is None:
                            # Keep informative nearby failures rather than
                            # repeating only the original station's XY miss.
                            hit=any(counts.get('hit',0)>0 for label,role,counts in
                                    getattr(choice,'last_target_diagnostics',[]))
                            later_rod=why.startswith('Rod ') and not why.startswith('Rod 0:')
                            if hit or later_rod or 'obstruct' in why.lower() or 'collision' in why.lower():
                                candidate_failures[index]=(candidate['from_a'],why)
                    if progress.cancelled:
                        raise ValueError('Structural station search cancelled; probes rolled back')
                chosen=structure_stations.select_layout(groups,originals,context['length'],
                    context['maximum'],context['branches'],context['existing'],context['end_limits'])
            if chosen is None:
                stats['structure_withheld']+=len(originals)
                stats['blocked_runs']+=1
                issues.append('STRUCTURE ALIGNMENT WITHHELD run {}: no complete measured layout '
                              'within 4 ft along the same duct pieces, with required spacing/end/branch '
                              'coverage and clearance. {} probes; no probe hangers retained. '
                              'Parallel-offset steel may require another approved support arrangement.'
                              .format(originals[0]['piece']['id'],len(cache)))
                for index,group in enumerate(groups):
                    if not group:
                        issues.append('DRAFT TARGET SEARCH duct {} @ {:.2f} ft: {}'.format(
                            originals[index]['piece']['id'],originals[index]['from_a'],reasons[index]))
                    if candidate_failures[index] is not None:
                        distance,reason=candidate_failures[index]
                        issues.append('DRAFT TARGET SEARCH CANDIDATE duct {} @ {:.2f} ft: {}'.format(
                            originals[index]['piece']['id'],distance,reason))
                if budget<=0 or run_budget<=0:
                    notes.append('Bounded structural station search reached its probe budget; '
                                 'an unresolved run is not proof that no support arrangement exists.')
            else:
                for original,job in zip(originals,chosen):
                    if abs(job['station']-original['station'])>.02:
                        stats['structure_shifted']+=1
                        issues.append('STRUCTURE ALIGNED duct {}: station {:.2f} -> {:.2f} ft along '
                                      'run; every probe rod measured; final placement will be reverified.'
                                      .format(job['piece']['id'],original['station'],job['station']))
                selected.extend(chosen)
            progress.update_progress(run_index+1,total)
    notes.append('Structure-aware station search: at most 24 candidate positions/job, '
                 '160 probes/run, 600 probes total, 4 ft maximum same-piece movement. '
                 'All probes rolled back. Existing station occupancy is not structural attachment proof.')
    return selected


def review_clearance_references(checker):
    """Explicit, unchecked-by-default, execution-only reference classification."""
    with forms.ProgressBar(title='Inspecting unreadable reference candidates: {value}/{max_value}',
                           step=1) as progress:
        rows=checker.reference_review_candidates(
            progress=lambda current,total:progress.update_progress(current,max(1,total)))
    if not rows:
        return
    forms.alert('Some drawing/coordination objects cannot be evaluated for clearance.\n'
                'In the next list, check ONLY objects you know are background or duplicate references.\n'
                'Checked objects will be excluded from clearance for THIS RUN ONLY.\n'
                'Leave physical or uncertain objects unchecked; Cancel excludes nothing.')
    class ReferenceOption(forms.TemplateListItem):
        @property
        def name(self):
            return self.item['label']
    options=[ReferenceOption(row,checked=False) for row in rows]
    selected=forms.SelectFromList.show(options,multiselect=True,
        title='ROB MEP | Classify known drawing / coordination references',
        button_name='Use checked as references for this run')
    if selected:
        checker.apply_reference_review([getattr(row,'item',row)['key'] for row in selected])


def inspect_single_hanger(job, choice, cfg):
    """Isolate API creation, raw targets, all-rod clearance, sizing and cleanup.

    Diagnostic only: every probe is rolled back, including a successful test.
    Raw measurements do not disable clearance for validated targets or sizing.
    """
    result={'created':False,'hosted':False,'rod_count':0,'raw_targets':0,
            'validated_targets':0,'lengths_verified':False,'clearance':False,
            'cleaned':False,'rods':[],'errors':[],'origin':None}
    sub=SubTransaction(DOC)
    begun=False
    try:
        sub.Start(); begun=True
        piece=job['piece']
        hanger=FabricationPart.CreateHanger(DOC,job['button'],piece['part'].Id,
                                            piece['ca'],float(job['from_a']),False)
        if hanger is None:
            raise ValueError('Revit returned no fabrication hanger')
        result['created']=True
        DOC.Regenerate()
        try:
            result['origin']=xyz_tuple(hanger.Origin)
        except Exception:
            pass
        if not attached_to_proposed_host(hanger,piece['id']):
            raise ValueError('Created hanger is not hosted on the selected duct')
        result['hosted']=True
        info=hanger.GetRodInfo()
        if info is None:
            raise ValueError('Created hanger has no rod information')
        try:
            if info.IsAttachedToStructure:
                raise ValueError('Unattached test unexpectedly attached to structure')
            info.CanRodsBeHosted=False
        finally:
            info.Dispose()
        rods=rod_geometry.read_rods(hanger)
        result['rod_count']=len(rods)
        targets=[]
        for index,base,old in rods:
            row={'index':index,'base':xyz_tuple(base),'old_length':old,
                 'raw':None,'validated':None,'errors':[]}
            result['rods'].append(row)
            # Measure raw geometry first so obstruction failure at rod 0
            # cannot hide rod 1's geometry, coordinates or independent length.
            validator=choice.path_validator
            try:
                choice.path_validator=None
                raw=choice.target_for_rod(base,cfg['max_rod'])
                if raw is not None:
                    row['raw']=dict(raw)
                    result['raw_targets']+=1
                else:
                    row['errors'].append('No raw approved geometric target. '+
                        choice.target_diagnostic_text(base,cfg['max_rod']))
            except Exception as ex:
                row['errors'].append('Raw geometry: '+str(ex))
            finally:
                choice.path_validator=validator
            try:
                validated=choice.target_for_rod(base,cfg['max_rod'])
                if validated is None:
                    raise ValueError('No approved reachable target')
                row['validated']=dict(validated)
                validated.update(index=index,base=base,old=old)
                targets.append(validated)
                result['validated_targets']+=1
            except Exception as ex:
                row['errors'].append('Validated path: '+str(ex))
        if len(targets)==len(rods) and rods:
            rod_geometry.apply_lengths(hanger,targets,DOC.Regenerate)
            result['lengths_verified']=True
            clear,why=check_measured_draft_rod_clashes(hanger,piece['id'],targets,True)
            result['clearance']=bool(clear)
            if not clear:
                result['errors'].append('Final sized-rod clearance: '+why)
    except Exception as ex:
        result['errors'].append(str(ex))
    finally:
        if begun:
            status=sub.RollBack()
            if status is not None and str(status)!='RolledBack':
                raise ValueError('Single-hanger test cleanup failed; stopping transaction')
            result['cleaned']=True
    return result


def run_single_hanger_test(part, choice, cfg):
    """One user-picked station, no run optimizer, no retained model changes."""
    piece,issue=extract_segment(part)
    if piece is None:
        forms.alert('Single hanger test cannot use this duct: {}. No test hanger was created.'
                    .format(issue or 'No usable straight duct geometry'))
        return
    vector=planner.sub(piece['b'],piece['a'])
    length=planner.norm(vector)
    if length<=.51:
        raise ValueError('Selected duct is too short for an inboard test station')
    try:
        point=UIDOC.Selection.PickPoint('SINGLE HANGER TEST: click desired station along the selected duct')
    except OperationCanceledException:
        return
    direction=planner.unit(vector)
    requested=planner.projections(xyz_tuple(point),piece['a'],direction)
    distance=max(.255,min(length-.255,requested))
    intended=planner.add(piece['a'],planner.mul(direction,distance))
    button=cfg['buttons_by_service'].get(piece['service_id'],{}).get(piece['shape'])
    if (piece['shape']=='rectangular' and cfg['large_threshold_ft'] is not None
            and piece['w']>=cfg['large_threshold_ft']):
        button=cfg['buttons_by_service'].get(piece['service_id'],{}).get('trapeze')
    if button is None:
        raise ValueError('No hanger button selected for this duct service/profile')
    transaction=Transaction(DOC,'ROB MEP - Single Hanger Test (rolled back)')
    transaction.Start()
    try:
        result=inspect_single_hanger({'piece':piece,'button':button,'from_a':distance},choice,cfg)
    finally:
        status=transaction.RollBack()
        if status is not None and str(status)!='RolledBack':
            raise ValueError('Single-hanger test transaction rollback did not complete')
    offset=(planner.projections(result['origin'],piece['a'],direction)-distance
            if result['origin'] is not None else None)
    geometry_pass=(result['created'] and result['hosted'] and result['rod_count']>0 and
            result['validated_targets']==result['rod_count'] and
            result['lengths_verified'] and result['clearance'] and result['cleaned'])
    passed=geometry_pass and offset is not None and abs(offset)<=.25
    status='PASS' if passed else 'STATION REVIEW' if geometry_pass else 'BLOCKED'
    OUTPUT.print_md('# ROB MEP Auto Hanger | SINGLE HANGER TEST | {}'.format(status))
    OUTPUT.print_md('**Diagnostic only: every test hanger was rolled back. Zero retained is expected. '
                    'This test does not validate native anchorage or a complete support layout.**')
    OUTPUT.print_md('Duct {} / service {} / hanger {} / connector distance {:.3f} ft / '
                    'requested axis point {} / actual hanger origin {}'.format(
                        piece['id'],piece['service_id'],button.Name,distance,intended,result['origin']))
    OUTPUT.print_md('Along-duct hanger-origin offset from requested station: {} ft. '
                    'Offsets over 0.25 ft need station/product-origin review; no automatic reversal was applied.'
                    .format(offset if offset is not None else 'unavailable'))
    OUTPUT.print_md('| Stage | Result |\n|---|---|\n'
                    '| API created hanger | {} |\n| Correct duct host | {} |\n'
                    '| Rod count | {} |\n| Raw geometric targets | {} |\n'
                    '| Targets passing structural path checks | {} |\n'
                    '| Independent lengths verified | {} |\n| Final rod clearance | {} |\n'
                    '| Test rolled back | {} |'.format(result['created'],result['hosted'],
                        result['rod_count'],result['raw_targets'],result['validated_targets'],
                        result['lengths_verified'],result['clearance'],result['cleaned']))
    for row in result['rods']:
        OUTPUT.print_md('### Rod {}'.format(row['index']))
        OUTPUT.print_md('Host base XYZ {} ft; initial length {:.3f} ft'.format(row['base'],row['old_length']))
        for name in ('raw','validated'):
            target=row[name]
            if target:
                OUTPUT.print_md('{} target: {} / {} #{} / host Z {:.3f} ft / length {:.3f} ft'.format(
                    name,target['tier'],target['source_label'],target['id'],target['z'],target['length']))
        for error in row['errors']:
            OUTPUT.print_md('- '+error.replace('|','/'))
    for error in result['errors']:
        OUTPUT.print_md('- '+error.replace('|','/'))
    if _LINKED_CLEARANCE is not None:
        for note in _LINKED_CLEARANCE.reference_notes():
            OUTPUT.print_md('- '+note.replace('|','/'))
    forms.alert('SINGLE HANGER TEST: {}\nAPI created hanger: {}\n'
                'Measured targets: {} / {}; validated paths: {} / {}\n'
                'All test hangers removed. Zero retained is expected.\n'
                'Send the SINGLE HANGER TEST output.'.format(status,
                    result['created'],result['raw_targets'],result['rod_count'],
                    result['validated_targets'],result['rod_count']))


def get_settings():
    from System.Windows import Thickness, FontWeights, TextWrapping, MessageBox
    from System.Windows.Controls import StackPanel, ComboBox, TextBlock, Orientation

    class SettingsWindow(forms.WPFWindow):
        def __init__(self, service_inventory, initial_max_rod=20.0):
            forms.WPFWindow.__init__(self,os.path.join(_DIR,'settings.xaml'))
            self.confirmed=False
            self.settings=None
            self.service_controls={}
            self.inventory=service_inventory
            self.rodBox.Text=str(float(initial_max_rod))
            # Only services used by the selected duct appear. Each row has its
            # own buttons, which makes accidentally mixing SA and RA impossible.
            for sid in sorted(service_inventory):
                info=service_inventory[sid]
                choices=info['buttons']
                labels=['(Do not place)']+[label for label,button in choices]
                lookup=dict(choices)
                header=TextBlock()
                header.Text='{}  |  Service ID {}'.format(info['name'],sid)
                header.FontSize=14
                header.FontWeight=FontWeights.SemiBold
                header.Margin=Thickness(0,13,0,4)
                self.serviceRows.Children.Add(header)
                if not choices:
                    warning=TextBlock()
                    warning.Text='No loaded fabrication hanger buttons in this duct service; skipped.'
                    warning.TextWrapping=TextWrapping.Wrap
                    warning.Margin=Thickness(0,0,0,8)
                    self.serviceRows.Children.Add(warning)
                    self.service_controls[sid]={'lookup':{},'controls':{}}
                    continue
                row=StackPanel()
                row.Orientation=Orientation.Horizontal
                row.Margin=Thickness(0,0,0,8)
                controls={}
                for shape,heading in (('rectangular','RECT / HALF-STRAP'),
                                      ('round','ROUND'),('oval','OVAL'),
                                      ('trapeze','LARGE / TRAPEZE')):
                    col=StackPanel()
                    col.Width=197
                    col.Margin=Thickness(0,0,8,0)
                    title=TextBlock()
                    title.Text=heading
                    title.FontSize=10
                    title.Margin=Thickness(0,0,0,2)
                    col.Children.Add(title)
                    combo=ComboBox()
                    combo.ItemsSource=labels
                    combo.SelectedIndex=planner.guess_hanger_choice(labels,shape)
                    combo.Height=28
                    combo.Margin=Thickness(0,0,0,0)
                    col.Children.Add(combo)
                    row.Children.Add(col)
                    controls[shape]=combo
                self.serviceRows.Children.Add(row)
                self.service_controls[sid]={'lookup':lookup,'controls':controls}
            self.largeRectCheck.IsChecked=False
            self.largeRectWidthBox.IsEnabled=False
            self.largeRectCheck.Checked+=self.on_large_toggle
            self.largeRectCheck.Unchecked+=self.on_large_toggle
            self.previewCheck.IsChecked=True
            self.sideTapCheck.IsChecked=True
            self.rodClashCheck.IsChecked=True
            self.fittingCheck.IsChecked=True
            self.draftCheck.IsChecked=True
            self.placeButton.Click+=self.on_run
            self.cancelButton.Click+=self.on_cancel

        def on_large_toggle(self,sender,args):
            self.largeRectWidthBox.IsEnabled=bool(self.largeRectCheck.IsChecked)

        def on_cancel(self,sender,args):
            self.Close()

        def on_run(self,sender,args):
            try:
                spacing=float(self.spacingBox.Text)
                offset=float(self.offsetBox.Text)
                maxrod=float(self.rodBox.Text)
                if not (2.0<=spacing<=12.0 and 0.5<=offset<=2.0
                        and 1.0<=maxrod<=60.0):
                    raise ValueError('Spacing 2-12 ft, offset 0.5-2 ft, rod 1-60 ft')
                large_enabled=bool(self.largeRectCheck.IsChecked)
                large_threshold_ft=None
                if large_enabled:
                    large_threshold_in=float(self.largeRectWidthBox.Text)
                    if not (6.0<=large_threshold_in<=240.0):
                        raise ValueError('Large rectangular override must be 6-240 inches')
                    large_threshold_ft=large_threshold_in/12.0
                mapping={}
                for sid,item in self.service_controls.items():
                    lookup=item['lookup']
                    mapping[sid]={}
                    for shape,combo in item['controls'].items():
                        mapping[sid][shape]=lookup.get(str(combo.SelectedItem))
                if not any(button is not None for types in mapping.values()
                           for button in types.values()):
                    raise ValueError('No service has a selected fabrication hanger button')
                if large_enabled:
                    for sid,types in mapping.items():
                        if types.get('rectangular') is not None and types.get('trapeze') is None:
                            raise ValueError('No LARGE / TRAPEZE choice for {}'.format(
                                self.inventory[sid]['name']))
                single_test=bool(self.singleTestCheck.IsChecked)
                self.settings={'single_test':single_test,
                               'review_references':single_test or bool(self.referenceReviewCheck.IsChecked),
                               'max_spacing':spacing,'end_offset':offset,
                               'max_rod':maxrod,
                               'preview':bool(self.previewCheck.IsChecked) and not single_test,
                               'buttons_by_service':mapping,
                               'large_threshold_ft':large_threshold_ft,
                               'avoid_side_taps':bool(self.sideTapCheck.IsChecked),
                               'reject_rod_clashes':single_test or bool(self.rodClashCheck.IsChecked),
                               'try_fitting':bool(self.fittingCheck.IsChecked),
                               'keep_drafts':bool(self.draftCheck.IsChecked)}
                self.confirmed=True
                self.Close()
            except Exception as ex:
                MessageBox.Show(str(ex),'Check Auto Hanger settings')
    return SettingsWindow



def report_counts(stats,issues,planning_notes,preview):
    OUTPUT.print_md('# ROB MEP Auto Hanger v0.3.7 | {}'.format('PREVIEW' if preview else 'RESULTS'))
    OUTPUT.print_md('**Per-service fabrication hanger buttons.** User-approved preferred structure and fallback surfaces from the structural type picker; SMACNA-informed layout and conservative 3D clearance screening. Check hardware/rod clearance and anchor design; not compliance certification.')
    lines=['| Metric | Count |','|---|---:|']
    for key,name in (('selected','Horizontal straight duct segments'),
                     ('runs','Grouped straight runs'),
                     ('drop_routes','Elbow/downturn-to-diffuser connections flagged for review'),
                     ('collision_runs','Runs with nearby side-tap/accessory clearance envelopes'),
                     ('rod_clashes','Hangers rolled back for potential 3D rod/MEP clashes'),
                     ('fitting_probes','Fitting-extension candidates for unsupported runs (UNVERIFIED)'),
                     ('fitting_placed','Verified fitting-extension hangers placed'),
                     ('blocked_runs','Runs withheld by clearance or spacing checks'),
                     ('planned','Planned hanger stations'),
                     ('structure_probes','Rolled-back structural station probes'),
                     ('structure_shifted','Stations adjusted to measured structure'),
                     ('structure_withheld','Stations withheld: no complete measured layout'),
                     ('redundant_removed','Unneeded proposed hanger stations removed'),
                     ('existing','Existing hanger near planned station'),
                     ('no_button','Skipped: no hanger mapping for duct service/profile'),
                     ('unlocatable','Skipped: cannot locate eligible duct station'),
                     ('placed','Verified hangers created'),
                     ('ifc_attached','Attached to approved preferred structure'),
                     ('roof_attached','Attached to approved fallback structure'),
                     ('mixed_attached','Mixed IFC + roof rod connections'),
                     ('preferred_members','Approved preferred structural elements'),
                     ('fallback_roof','Approved native or linked fallback elements'),
                     ('unattached','Unverified structural attachment attempts'),
                     ('native_recovered','Verified after Revit reattachment retry'),
                     ('draft_placed','DRAFT hangers IFC/roof geometry sized - UNATTACHED'),
                     ('draft_failed','Draft attempts rejected/unavailable'),
                     ('errors','Failed placements')):
        lines.append('| {} | {} |'.format(name,stats.get(key,0)))
    OUTPUT.print_md('\n'.join(lines))
    if issues:
        # Attachment results were hidden past line 120 in v0.3.5.
        # Put them first so the next site-test report tells us the real cause.
        important=[x for x in issues if str(x).startswith(('ATTACHMENT ', 'DRAFT ', 'RECOVERED '))]
        other=[x for x in issues if x not in important]
        if important:
            OUTPUT.print_md('### Attachment and draft outcomes (first 100)')
            for line in important[:100]:
                OUTPUT.print_md('- {}'.format(str(line).replace('|','/')))
        OUTPUT.print_md('### Planning / other issues (first 85)')
        for line in other[:85]:
            OUTPUT.print_md('- {}'.format(str(line).replace('|','/')))
    if planning_notes:
        OUTPUT.print_md('### Spacing/planning notes')
        for n in sorted(set(planning_notes)):
            OUTPUT.print_md('- {}'.format(n))


def run():
    global _LINKED_CLEARANCE
    _LINKED_CLEARANCE=None
    if DOC.IsFamilyDocument:
        forms.alert('Run Auto Hanger in a Revit project, not in the Family Editor.')
        return
    try:
        # Support BOTH workflows: preselect duct/structure before clicking
        # the tool, OR launch tool and pick ducts first, structure second.
        startup_ids=list(UIDOC.Selection.GetElementIds())
        duct_candidates=selected_or_pick(
            DuctFilter(),
            'AUTO HANGER 1/2: Pick FABRICATION ducts (fittings OK); click Finish',
            startup_ids)
        duct_parts=[p for p in duct_candidates if is_duct_straight(p)]
        avoided_accessories=[p for p in duct_candidates if is_inline_accessory(p)]
        if not duct_parts:
            if duct_candidates:
                forms.alert('Found {} fabrication duct part(s), but none were STRAIGHT.\n'
                            'Select at least one straight fabrication duct segment.'
                            .format(len(duct_candidates)))
            else:
                forms.alert('No fabrication ducts selected. This tool works with\n'
                            'MEP Fabrication Ductwork, not regular Revit design duct.')
            return
        selection=structure_picker.choose_structure(DOC,UIDOC,startup_ids=startup_ids)
        if selection is None:
            return
        choice=structure_priority.StructureChoice(
            sources=selection['sources'],priority_mode=selection['priority_mode'],
            exact_small_selection=True)
        unlocated=choice.preflight_unlocated()
        if unlocated:
            forms.alert(u'{} selected structural objects cannot be located or measured. '
                        u'No placement was attempted.\n\n{}\n\n'
                        u'Reselect IFC beam/joist types and roof/deck fallback; '
                        u'leave unrelated or unreadable custom objects unchecked.'
                        .format(len(unlocated),u'\n'.join(unlocated[:8])))
            return
    except OperationCanceledException:
        return
    except Exception as ex:
        forms.alert('Selection failed: {}\nSee pyRevit output if this persists.'.format(ex))
        try:
            OUTPUT.print_md('### Selection exception')
            OUTPUT.print_md('```\n{}\n```'.format(traceback.format_exc()))
        except Exception:
            pass
        return

    duct_service_ids=set()
    for part in duct_parts:
        try:
            duct_service_ids.add(int(part.ServiceId))
        except Exception:
            pass
    inventory=service_hanger_choices(duct_service_ids)
    if not inventory or not any(item['buttons'] for item in inventory.values()):
        forms.alert('No fabrication hanger service buttons loaded for the selected duct\n'
                    '(the tool will NOT borrow buttons from another service).')
        return
    Settings=get_settings()
    wnd=Settings(inventory,selection['max_rod'])
    wnd.ShowDialog()
    if not wnd.confirmed:
        return
    cfg=wnd.settings
    if cfg.get('single_test') and len(duct_parts)!=1:
        forms.alert('Single hanger test requires exactly ONE straight fabrication duct. Reselect one duct and run again.')
        return
    selection_warnings=list(selection.get('warnings',[]))
    try:
        save_preferences=selection.get('save_preferences')
        if save_preferences is not None:
            save_preferences(cfg['max_rod'])
    except Exception as ex:
        selection_warnings.append('Structural preferences could not be saved: {}'.format(ex))
    if cfg['reject_rod_clashes'] and not cfg['preview']:
        try:
            _LINKED_CLEARANCE=linked_obstacles.LinkedObstructionChecker(
                DOC,structural_sources=choice.sources).prepare()
            selection_warnings.extend(getattr(_LINKED_CLEARANCE,'warnings',[]))
            if _LINKED_CLEARANCE.failures:
                raise ValueError('; '.join(_LINKED_CLEARANCE.failures))
            if cfg.get('review_references'):
                review_clearance_references(_LINKED_CLEARANCE)
            def validate_structural_path(base,target):
                row=dict(target)
                row['index']=0
                path={'index':0,'base':base,'tip':XYZ(base.X,base.Y,target['z'])}
                return _LINKED_CLEARANCE.check([path],approved_targets=[row])
            choice.path_validator=validate_structural_path
        except Exception as ex:
            forms.alert('Linked clearance inspection could not start: {}. No hangers were created.'.format(ex))
            return
    if cfg.get('single_test'):
        run_single_hanger_test(duct_parts[0],choice,cfg)
        return
    stats={'selected':0,'runs':0,'planned':0,'existing':0,'drop_routes':0,'collision_runs':0,'no_button':0,
           'unlocatable':0,'placed':0,'rod_clashes':0,'unattached':0,'errors':0,
           'fitting_probes':0,'fitting_placed':0,'blocked_runs':0,
           'ifc_attached':0,'roof_attached':0,'mixed_attached':0,
           'preferred_members':choice.preferred_count,'fallback_roof':choice.fallback_count,
           'native_recovered':0,'draft_placed':0,'draft_failed':0,'redundant_removed':0}
    issues=[]
    notes=selection_warnings
    notes.append('Small-selection exact geometry checks enabled for up to 12 approved members per active role; bounding boxes never supply rod lengths.')
    notes.append('Structural targeting mode: {}. Inventoried fallback counts are inactive in preferred_only mode.'.format(selection['priority_mode']))
    for source in choice.sources:
        notes.append('Approved structure: {} / {} preferred / {} fallback'.format(
            source.label,len(source.preferred),len(source.fallback)))
    if choice.bad_boxes:
        notes.append('{} approved member(s) lack a bbox; actual geometry is tested. Unreadable geometry requires reselection; no bbox rod lengths are used.'.format(choice.bad_boxes))
    if avoided_accessories:
        issues.append('ACCESSORY EXCLUSION: {} selected inline accessory part(s) are '
                      'NOT valid duct-straight hanger hosts: {}'.format(
            len(avoided_accessories),', '.join(str(element_number(p.Id))
                                             for p in avoided_accessories[:15])))
    segments=[]
    for p in duct_parts:
        try:
            seg,issue=extract_segment(p)
            if seg:
                segments.append(seg)
            else:
                issues.append('Duct {}: {}'.format(element_number(p.Id),issue))
        except Exception as ex:
            issues.append('Duct {}: {}'.format(element_number(p.Id),ex))
    stats['selected']=len(segments)
    if not segments:
        report_counts(stats,issues,[],True)
        return

    runs=planner.group_runs(segments)
    stats['runs']=len(runs)
    existing=existing_by_host()
    notes.append('Existing hanger occupancy before optimization: {} station(s) on selected ducts. Existing-near-planned count is evaluated only after optimization.'.format(
        sum(len(existing.get(element_number(part.Id),[])) for part in duct_parts)))
    tasks=[]
    fitting_tasks=[]
    reserved_fitting_ids=set()
    for r in runs:
        # Inspect duct fitting network beyond the selected straights. A
        # connected elbow/drop/diffuser still receives its support on the
        # horizontal duct; never place an automatic hanger on the vertical.
        drops=terminal_drops_for_run(r)
        stats['drop_routes']+=len(drops)
        if drops:
            ids=', '.join(str(p['id']) for lo,hi,p in r['pieces'][:6])
            for side,kind,target in drops:
                if kind=='connected':
                    issues.append('DIFFUSER DROP near ducts {} ({} end): '
                                  'downturned elbow leads to connected air terminal {}; '
                                  'review independent diffuser support; horizontal support '
                                  'must stay near elbow.'.format(ids,side,target))
                else:
                    issues.append('POSSIBLE DIFFUSER DROP near ducts {} ({} end): '
                                  'downturned fitting {} detected but no connected air '
                                  'terminal confirmed; visually inspect connection/support.'
                                  .format(ids,side,target))
        blocked=[]
        if cfg['avoid_side_taps']:
            try:
                blocked,conflicts=side_tap_clearance_intervals(r,cfg['max_rod'])
                if blocked:
                    stats['collision_runs']+=1
                    ids=', '.join(str(p['id']) for lo,hi,p in r['pieces'][:5])
                    issues.append('CLEARANCE near ducts {}: conservative 3D interference '
                                  'envelopes from nearby MEP FAB duct/fittings {}. '
                                  'Stations are shifted or run withheld if no safe '
                                  'spacing is possible.'.format(
                                    ids,', '.join(str(x) for x in conflicts[:12])))
            except Exception as collision_error:
                ids=', '.join(str(p['id']) for lo,hi,p in r['pieces'][:5])
                issues.append('Run around ducts {} withheld: 3D side-tap screening '
                              'failed: {}'.format(ids,collision_error))
                continue
        extra=branch_stations_for_run(r,segments)
        for point in connected_branch_stations_for_run(r):
            if not any(abs(point-q)<0.75 for q in extra):
                extra.append(point)
        jobs, note=planner.plan_run(r,cfg['max_spacing'],cfg['end_offset'],extra,
                                    blocked_intervals=blocked)
        # One max-spacing value per constant-profile run. This is an actual
        # applied cap, not SMACNA certification of the selected hanger hardware.
        shape_piece=r['pieces'][0][2]
        span,limit_note=planner.rule_spacing(shape_piece['shape'],
                 shape_piece['w'],shape_piece['h'],cfg['max_spacing'])
        if span:
            dims=('diameter {:.0f} in'.format(shape_piece['w']*12.0)
                  if shape_piece['shape']=='round' else
                  'W {:.0f} + H {:.0f} in'.format(
                      shape_piece['w']*12.0,shape_piece['h']*12.0))
            notes.append('Run {} / {} / {}: maximum {:.1f} ft (global cap {:.1f} ft)'
                   .format(shape_piece['id'],shape_piece['shape'],dims,
                           span,cfg['max_spacing']))
        if note:
            notes.append(note)
            if ('manual' in note.lower() or 'opposite branch' in note.lower()
                    or 'no support within' in note.lower()):
                near_ids=', '.join(str(seg['id']) for _,_,seg in r['pieces'][:8])
                issues.append('CHECK SUPPORT LOCATION near ducts {}: {}'.format(near_ids,note))
        if not jobs:
            stats['blocked_runs']+=1
            ids=', '.join(str(seg['id']) for _,_,seg in r['pieces'][:8])
            issues.append('Run around elements {}: no valid planned hanger station: {}'.format(ids,note))
            if cfg['try_fitting']:
                candidates=fitting_extension_candidates_for_run(r)
                for c in candidates:
                    sid=c['service_id']
                    button=cfg['buttons_by_service'].get(sid,{}).get(c['shape'])
                    if button is None:
                        continue
                    # Do not duplicate an already hosted fitting support.
                    if existing.get(c['id']) or c['id'] in reserved_fitting_ids:
                        continue
                    reserved_fitting_ids.add(c['id'])
                    c['button']=button
                    fitting_tasks.append(c)
                    stats['fitting_probes']+=1
                    issues.append('FITTING EXTENSION PROBE: duct {} has no legal straight '
                                  'station; test fitting {} ({}) in placement mode '
                                  'with rollback/rod verification; preview does not '
                                  'verify a physical throat.'.format(
                                     ids,c['id'],c['endname']))
        # Existing hangers on any piece of run counted by station, not per piece.
        old=[]
        for lo,hi,piece in r['pieces']:
            for pos in existing.get(piece['id'],[]):
                old.append(planner.projections(pos,r['origin'],r['direction']))
        # Minimize added support count against existing hangers across the
        # ENTIRE run. Do not add new hangers where previous DRAFT stations
        # already occupy the model. DRAFTs still need structural review.
        if jobs:
            shape_piece=r['pieces'][0][2]
            maximum,_=planner.rule_spacing(shape_piece['shape'],
                shape_piece['w'],shape_piece['h'],cfg['max_spacing'])
            total_length=max(x[1] for x in r['pieces'])
            before=len(jobs)
            turn_ends=end_needs_close_support(r)
            end_limits=tuple(2.0 if must else min(3.0,maximum)
                             for must in turn_ends)
            # For short runs with no elbows, support once near the middle
            # rather than automatically adding one at each fabrication end.
            # A branch and any real elbow keep their proximity requirements.
            if not any(turn_ends) and not extra and total_length<=maximum:
                midpoint=planner._nearest_clear_job(r,total_length/2.0,
                                         maximum,blocked)
                if midpoint is not None:
                    if (midpoint['station']<=end_limits[0]+1e-5 and
                        total_length-midpoint['station']<=end_limits[1]+1e-5):
                        jobs=[midpoint]
            jobs=planner.optimize_support_count(jobs,old,
                total_length,maximum,extra,end_limits=end_limits)
            stats['redundant_removed']+=before-len(jobs)
        run_context={'run':r,'length':max(x[1] for x in r['pieces']),
                     'maximum':span,'branches':list(extra),'blocked':list(blocked),
                     'existing':list(old),'end_limits':end_limits if jobs else (2.0,2.0)}
        for job in jobs:
            job['run_context']=run_context
            stats['planned']+=1
            piece=job['piece']
            button=cfg['buttons_by_service'].get(piece['service_id'],{}).get(piece['shape'])
            # Opt-in override for rectangular duct above an approved
            # project-specific width. The user defines the breakpoint.
            if (piece['shape']=='rectangular'
                    and cfg['large_threshold_ft'] is not None
                    and piece['w'] >= cfg['large_threshold_ft']):
                button=cfg['buttons_by_service'].get(piece['service_id'],{}).get('trapeze')
            if button is None:
                stats['no_button']+=1
                issues.append('Duct {}: no hanger button in service {} for {}'.format(
                    piece['id'],piece['service_name'],piece['shape']))
                continue
            if any(abs(e-job['station']) <= 0.75 for e in old):
                stats['existing']+=1
                continue
            # Reserve this station against duplicate plans on the same run.
            old.append(job['station'])
            job['button']=button
            tasks.append(job)

    if cfg['preview']:
        OUTPUT.print_md('**PREVIEW only** - no Revit elements were changed. Uncheck Preview to place hangers.')
        report_counts(stats,issues,notes,True)
        counts={}
        for job in tasks:
            label='{} (Service {}) / {}'.format(job['piece']['service_name'],job['piece']['service_id'],str(job['button'].Name))
            counts[label]=counts.get(label,0)+1
        OUTPUT.print_md('### Selected hanger buttons by FABRICATION service')
        for label in sorted(counts):
            OUTPUT.print_md('- {}: {} proposed'.format(label,counts[label]))
        OUTPUT.print_md('Would attempt {} straight placements; {} preferred members and {} approved fallback objects across {} structural sources.'.format(
            len(tasks),choice.preferred_count,choice.fallback_count,len(choice.sources)))
        OUTPUT.print_md('Structure-aware station adjustment is evaluated only in placement mode using temporary rolled-back fabrication hangers. Preview stations are preliminary.')
        OUTPUT.print_md('Preview does not prove native IFC connectivity. Actual rod targets are verified after placement; wrong targets are rolled back.')
        if fitting_tasks:
            OUTPUT.print_md('**{} provisional fitting-extension probes** on elbows/angles. '
                            'These are NOT confirmed hangers in Preview; Revit validates '
                            'actual usable straight throats during placement.'.format(
                                len(fitting_tasks)))
        return

    created_ids=[]
    draft_ids=[]
    transaction=Transaction(DOC,'ROB MEP - Auto Hanger [IFC Geometry First + Roof Second]')
    transaction.Start()
    try:
        tasks=align_structure_tasks(tasks,choice,cfg,stats,issues,notes)
        for job in tasks:
            piece=job['piece']
            button=job['button']
            sub=SubTransaction(DOC)
            started=False
            try:
                # HostConnector distance is measured from that specific connector,
                # even when this segment orientation is reversed in the run.
                part=piece['part']
                from_a=job['from_a']
                length=planner.norm(planner.sub(piece['b'],piece['a']))
                if from_a<=0.25 or length-from_a<=0.25:
                    stats['unlocatable']+=1
                    continue
                sub.Start()
                started=True
                hanger=FabricationPart.CreateHanger(DOC,button,part.Id,
                                                    piece['ca'],float(from_a),True)
                if hanger is None:
                    raise Exception('Revit returned no hanger')
                DOC.Regenerate()
                if not attached_to_proposed_host(hanger,piece['id']):
                    raise Exception('New hanger hosted on unexpected part/accessory')
                ok,reason,tier=choice.verify(hanger,cfg['max_rod'])
                if not ok:
                    # Revit may initially leave rods unattached even when a
                    # native target exists. A second attempt is API-supported,
                    # but it still chooses nearest and MUST be reverified.
                    try_ok,try_reason,try_tier=retry_native_attachment(
                        hanger,choice,cfg['max_rod'])
                    if try_ok:
                        ok,reason,tier=try_ok,try_reason,try_tier
                        stats['native_recovered']+=1
                        issues.append('RECOVERED duct {} @ {:.2f} ft: Revit reattachment verified'.format(
                            piece['id'],from_a))
                    else:
                        detail='initial: {}; retry: {}'.format(reason,try_reason)
                        sub.RollBack(); started=False
                        stats['unattached']+=1
                        issues.append('ATTACHMENT duct {} @ {:.2f} ft: {}'.format(
                            piece['id'],from_a,detail))
                        if cfg['keep_drafts']:
                            draft_ok,draft_id,draft_reason=create_unattached_draft(
                                button,part,piece['id'],piece['ca'],from_a,detail,choice,cfg['max_rod'],cfg['reject_rod_clashes'])
                            if draft_ok:
                                stats['draft_placed']+=1
                                created_ids.append(draft_id)
                                draft_ids.append(draft_id)
                                issues.append('DRAFT duct {} @ {:.2f} ft: hanger {} - {}'.format(
                                    piece['id'],from_a,draft_id,draft_reason))
                            else:
                                stats['draft_failed']+=1
                                issues.append('DRAFT FAILURE duct {} @ {:.2f} ft: {}'.format(
                                    piece['id'],from_a,draft_reason))
                        continue
                clear,clear_note=check_new_rod_clashes(
                    hanger,piece['id'],cfg['max_rod'],cfg['reject_rod_clashes'])
                if not clear:
                    sub.RollBack()
                    started=False
                    stats['rod_clashes']+=1
                    issues.append('Duct {} at {:.2f} ft: {}'.format(piece['id'],from_a,clear_note))
                    continue
                sub.Commit()
                started=False
                stats['placed']+=1
                created_ids.append(element_number(hanger.Id))
                if tier=='IFC': stats['ifc_attached']+=1
                elif tier=='ROOF': stats['roof_attached']+=1
                else: stats['mixed_attached']+=1
            except Exception as ex:
                if started:
                    try:
                        sub.RollBack()
                    except Exception:
                        pass
                stats['errors']+=1
                issues.append('Duct {}: {}'.format(piece['id'],str(ex)))
        # Fallback ONLY for runs without a legal straight station. Probe on
        # actual two-port fabrication fitting extensions; every attempt uses
        # its own subtransaction and is rolled back if API/host/rod checks fail.
        for candidate in fitting_tasks:
            success=False
            for depth in candidate['probe_distances']:
                sub=SubTransaction(DOC)
                started=False
                try:
                    sub.Start()
                    started=True
                    hanger=FabricationPart.CreateHanger(
                        DOC,candidate['button'],candidate['part'].Id,
                        candidate['connector'],float(depth),True)
                    if hanger is None:
                        raise Exception('No compatible hanger/straight fitting extension')
                    DOC.Regenerate()
                    if not attached_to_proposed_host(hanger,candidate['id']):
                        raise Exception('Hanger hosted on unexpected part')
                    ok,reason,tier=choice.verify(hanger,cfg['max_rod'])
                    if not ok:
                        raise Exception(reason)
                    clear,clear_note=check_new_rod_clashes(
                        hanger,candidate['id'],cfg['max_rod'],cfg['reject_rod_clashes'])
                    if not clear:
                        stats['rod_clashes']+=1
                        raise Exception(clear_note)
                    sub.Commit()
                    started=False
                    success=True
                    stats['placed']+=1
                    stats['fitting_placed']+=1
                    created_ids.append(element_number(hanger.Id))
                    if tier=='IFC': stats['ifc_attached']+=1
                    elif tier=='ROOF': stats['roof_attached']+=1
                    else: stats['mixed_attached']+=1
                    issues.append('FITTING EXTENSION PLACED: fitting {} at {:.2f} ft '
                                  'from connector; review throat clearance and final '
                                  'hanger spacing in 3D.'.format(candidate['id'],depth))
                    break
                except Exception:
                    if started:
                        try: sub.RollBack()
                        except Exception: pass
            if not success:
                issues.append('FITTING EXTENSION UNAVAILABLE: fitting {} had no '
                              'Revit-accepted, selected-structure-attached hanger '
                              'location; needs manual support.'.format(candidate['id']))
        transaction.Commit()
    except Exception:
        try:
            transaction.RollBack()
        except Exception:
            pass
        issues.append('Transaction rolled back: {}'.format(traceback.format_exc()))
        stats['placed']=0
        stats['ifc_attached']=0
        stats['roof_attached']=0
        stats['mixed_attached']=0
        stats['draft_placed']=0
        created_ids=[]
        draft_ids=[]
    if stats['unattached'] or stats['errors'] or stats['unlocatable'] or stats['blocked_runs'] or stats['rod_clashes'] or stats['draft_placed']:
        notes.append('PLACEMENT INCOMPLETE: review actual support distances after failed/rolled-back or DRAFT hangers. DRAFT hangers do not constitute approved structural supports. Preview spacing is not as-built spacing.')
    notes.extend(choice.screen_mismatch_warnings)
    if _LINKED_CLEARANCE is not None:
        notes.extend(_LINKED_CLEARANCE.reference_notes())
    report_counts(stats,issues,notes,False)
    if created_ids:
        OUTPUT.print_md('### New hanger element IDs (click/select in Revit)')
        OUTPUT.print_md(', '.join(str(x) for x in created_ids[:200]))
        if draft_ids:
            OUTPUT.print_md('**UNATTACHED / IFC-OR-ROOF-GEOMETRY-SIZED DRAFT element IDs:** '+', '.join(str(x) for x in draft_ids[:200]))
        # Highlight all actually kept hangers. A successful commit remains
        # intact even if the active view cannot display all of them.
        try:
            from System.Collections.Generic import List
            ids=List[ElementId]()
            for n in created_ids:
                ids.Add(ElementId(int(n)))
            UIDOC.Selection.SetElementIds(ids)
        except Exception as ex:
            OUTPUT.print_md('Created hangers could not be selected automatically: {}'.format(ex))
    if stats['placed'] == 0 and stats['draft_placed'] == 0:
        forms.alert('No hangers were kept.\n'
                    '{} temporary station probes rolled back; {} proposed stations withheld.\n\n'
                    'See DRAFT TARGET SEARCH / CANDIDATE and STRUCTURE ALIGNMENT in output.\n'
                    'Clearance reference filter notes list excluded drawing/reference objects.\n'
                    'Unresolved blockers now include their Revit class.'.format(
                        stats.get('structure_probes',0),stats.get('structure_withheld',0)))
    elif stats['draft_placed']:
        forms.alert('{} VERIFIED, {} DRAFT UNATTACHED hangers created.\n'
                    'Drafts are NOT connected to structure; IFC/roof geometry measured,\n'
                    'check each anchor/clearance and connect before use.\n'
                    'See pyRevit results and Comments field.'.format(
                        stats['placed'],stats['draft_placed']))


try:
    run()
except Exception as fatal:
    try:
        OUTPUT.print_md('## Auto Hanger stopped before completion')
        OUTPUT.print_md('```\n{}\n```'.format(traceback.format_exc()))
    except Exception:
        pass
    forms.alert('Auto Hanger error: {}'.format(fatal))
