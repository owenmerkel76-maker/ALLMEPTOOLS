# -*- coding: utf-8 -*-
"""Non-destructive likely-close-duplicate hanger review for ROB MEP tools.

No elements are deleted. Reports suspicious DRAFT pairs at the same physical
support station with same service. Requires field judgment and SMACNA review.
"""
import math
from pyrevit import revit, forms, script
from Autodesk.Revit.DB import FabricationPart, BuiltInCategory, BuiltInParameter, FilteredElementCollector, ElementId

doc=revit.doc
uidoc=revit.uidoc
out=script.get_output()

def num(id):
    try:return int(id.Value)
    except Exception:return int(id.IntegerValue)

def notes(h):
    try:
        p=h.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        return (p.AsString() or '').upper() if p else ''
    except Exception:return ''

def pos(h):
    try: return h.Origin
    except Exception:
        bbox=h.get_BoundingBox(None)
        return (bbox.Min+bbox.Max)*.5 if bbox else None

def host(h):
    try:
        info=h.GetHostedInfo()
        return doc.GetElement(info.HostId) if info else None
    except Exception:return None

def axes(part):
    try:
        pts=[c.Origin for c in part.ConnectorManager.Connectors]
        far=None
        for a in pts:
            for b in pts:
                dx=b.X-a.X;dy=b.Y-a.Y;dz=b.Z-a.Z
                length=math.sqrt(dx*dx+dy*dy+dz*dz)
                if length>.001 and (far is None or length>far[0]):
                    far=(length,(dx/length,dy/length,dz/length))
        return far[1] if far else None
    except Exception:return None

def run():
    data=[]
    for h in FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_FabricationHangers).WhereElementIsNotElementType():
        if not isinstance(h,FabricationPart) or 'AUTO HANGER DRAFT' not in notes(h):
            continue
        hp=pos(h);duct=host(h)
        if hp is None or duct is None:continue
        try:
            if not duct.IsAStraight():continue
            data.append((h,hp,duct,int(duct.ServiceId),axes(duct)))
        except Exception:pass
    # Compare only same-system co-linear duct supports at almost the same 3D
    # position. This identifies potential duplicates, never certifies extras.
    bins={}
    for item in data:
        h,p,duct,sid,axis=item
        cell=(int(p.X/.75),int(p.Y/.75),int(p.Z/.75))
        bins.setdefault((sid,cell),[]).append(item)
    suspicious=[];seen=set()
    for item in data:
        h,p,duct,sid,axis=item
        cell=(int(p.X/.75),int(p.Y/.75),int(p.Z/.75))
        for x in (-1,0,1):
            for y in (-1,0,1):
                for z in (-1,0,1):
                    nearby=bins.get((sid,(cell[0]+x,cell[1]+y,cell[2]+z)),[])
                    for other in nearby:
                        h2,p2,d2,s2,a2=other
                        ids=tuple(sorted((num(h.Id),num(h2.Id))))
                        if ids in seen or ids[0]==ids[1]:continue
                        seen.add(ids)
                        if axis is None or a2 is None:continue
                        if abs(sum(axis[i]*a2[i] for i in range(3)))<.995:continue
                        separation=math.sqrt((p.X-p2.X)**2+(p.Y-p2.Y)**2+(p.Z-p2.Z)**2)
                        if separation<=1.0:
                            suspicious.append((ids,separation,num(duct.Id),num(d2.Id)))
    out.print_md('# ROB MEP HANGERS - Close Hanger Review')
    out.print_md('**{} labeled DRAFTs checked; {} close pairs flagged.**'.format(len(data),len(suspicious)))
    out.print_md('Pairs have matching fabrication service, parallel host axes and are within 1 foot. These are POTENTIAL extras only, not confirmed unnecessary supports.')
    for ids,distance,h1,h2 in suspicious[:120]:
        out.print_md('- Hangers {} and {} ({:.1f} in apart); host ducts {}, {}'.format(
            ids[0],ids[1],distance*12,h1,h2))
    if not suspicious:
        forms.alert('No near-duplicate Auto Hanger DRAFT pairs were detected.\n'
                    'Spacing still requires visual and project-schedule review.')
        return
    if forms.alert('Highlight {} POTENTIAL duplicate pairs in Revit?\n'
        'No hangers will be deleted.'.format(len(suspicious)),yes=True,no=True):
        from System.Collections.Generic import List
        selected=List[ElementId]()
        for x in sorted(set(id for row in suspicious for id in row[0])):
            selected.Add(ElementId(int(x)))
        uidoc.Selection.SetElementIds(selected)
    forms.alert('{} close pairs flagged. No elements were deleted.\n'
                'Inspect these before removing any hanger; support loads and elbow requirements still apply.'.format(len(suspicious)))

try:run()
except Exception as e:forms.alert('Review Hangers: {}'.format(e))
