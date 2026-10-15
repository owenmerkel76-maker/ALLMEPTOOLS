# coding: utf-8
"""IFC2x3 faceted-BRep roof-UNDERSIDE extractor; no Revit dependency.

Designed for Revit 2026's IFC2x3 IfcRoof export, using native roof
faces directly rather than CAD solids. Lengths in source conversion
based units, converted to Revit internal FEET. Crucially excludes the
far-from-origin IFC *site* placement; retains internal building/roof
placements. Does NOT produce Revit geometry by itself.
"""
from __future__ import division
import math
import os
import re

class IFCError(ValueError):
    pass


def split_args(s):
    result=[];start=0;depth=0;inside=False;i=0
    while i<len(s):
        c=s[i]
        if c=="'":
            if inside and i+1<len(s) and s[i+1]=="'":
                i+=2;continue
            inside=not inside
        elif not inside:
            if c=='(': depth+=1
            elif c==')': depth-=1
            elif c==',' and depth==0:
                result.append(s[start:i].strip());start=i+1
        i+=1
    result.append(s[start:].strip())
    return result


def refs(s):
    return [int(x) for x in re.findall(r'#(\d+)',s)]


def normal3(r):
    nx=ny=nz=0.0
    for p,q in zip(r,r[1:]+r[:1]):
        nx+=(p[1]-q[1])*(p[2]+q[2])
        ny+=(p[2]-q[2])*(p[0]+q[0])
        nz+=(p[0]-q[0])*(p[1]+q[1])
    d=math.sqrt(nx*nx+ny*ny+nz*nz)
    if d<1.e-9:raise IFCError('Degenerate IFC face')
    return (nx/d,ny/d,nz/d)


def area_xy(r):
    return 0.5*sum(p[0]*q[1]-q[0]*p[1]
                   for p,q in zip(r,r[1:]+r[:1]))


def plane3(r):
    n=normal3(r)
    if abs(n[2])<0.7:raise IFCError('Roof underside is too steep for structural Floor')
    a=-n[0]/n[2]; b=-n[1]/n[2];c=r[0][2]-a*r[0][0]-b*r[0][1]
    if max(abs(p[2]-(a*p[0]+b*p[1]+c)) for p in r)>1.0/192.0:
        raise IFCError('Roof face vertices are not planar within 1/16 inch')
    return (a,b,c)


def flat_loop(s):
    s=s.strip()
    if not(s.startswith('(') and s.endswith(')')):
        raise IFCError('Malformed IFC list')
    return split_args(s[1:-1])


class IFCReader(object):
    def __init__(self,filepath):
        with open(filepath,'rb') as f: data=f.read()
        if len(data)>30*1024*1024:
            raise IFCError('IFC exceeds 30MB; v0.3 specialized parser needs a roof-only export')
        data=data.decode('utf-8-sig')
        if "FILE_SCHEMA(('IFC2X3'))" not in data.replace(' ',''):
            raise IFCError('This first version supports IFC2X3 only; re-export IFC2x3 Coordination View 2.0')
        self.items={}
        for m in re.finditer(r'(?m)^#(\d+)=(IFC[A-Z0-9_]+)\((.*)\);\s*$',data):
            self.items[int(m.group(1))]=(m.group(2),m.group(3))
        if not self.items:raise IFCError('No IFC STEP entities found')
        self.scale=1.0
        # Revit built-in coordinates are feet; IFC may use metre or foot.
        # In the supplied file units #10='FOOT', #7='METRE'.
        if "'FOOT'" in data and 'IFCCONVERSIONBASEDUNIT' in data:
            self.scale=1.0
        elif re.search(r'IFCSIUNIT\([^;]*\.LENGTHUNIT\.,\$,\.METRE\.\)',data):
            self.scale=3.28083989501312
        else:
            raise IFCError('Unknown length units. Use Revit IFC2x3 export with FEET or METRE')
        self.ignore_root_site=True

    def entity(self,ref,kind=None):
        if ref not in self.items:raise IFCError('Missing IFC entity #%s'%ref)
        name,arguments=self.items[ref]
        if kind and name!=kind:raise IFCError('Expected %s, got %s (#%s)'%(kind,name,ref))
        return name,split_args(arguments)

    def point(self,rid):
        name,a=self.entity(rid,'IFCCARTESIANPOINT')
        values=flat_loop(a[0]); v=[float(x)*self.scale for x in values]
        return tuple((v+[0.0,0.0,0.0])[:3])

    def direction(self,rid):
        name,a=self.entity(rid,'IFCDIRECTION')
        values=[float(x) for x in flat_loop(a[0])]
        return tuple((values+[0.,0.,0.])[:3])

    def axisplacement(self,rid):
        if rid is None:return (1.,0.,0.,0.,0.)
        name,a=self.entity(rid,'IFCAXIS2PLACEMENT3D')
        pt=self.point(refs(a[0])[0]); axes=refs(a[1]);xx=refs(a[2]);
        if axes:
            zz=self.direction(axes[0])
            if abs(zz[0])>1.e-7 or abs(zz[1])>1.e-7 or abs(zz[2]-1.)>1.e-7:
                raise IFCError('Roof uses tilted element coordinate frame: not supported in v0.3')
        v=self.direction(xx[0]) if xx else (1.,0.,0.)
        norm=math.hypot(v[0],v[1]);
        if norm<1.e-9:raise IFCError('Invalid roof local axes')
        return (v[0]/norm,v[1]/norm,pt[0],pt[1],pt[2])

    def placement(self,rid,depth=0):
        if depth>15:raise IFCError('Nested IFC placement too deep')
        name,a=self.entity(rid,'IFCLOCALPLACEMENT')
        parent=refs(a[0]); here=refs(a[1])
        if not here:raise IFCError('Missing IFC local placement')
        if not parent:
            # Critical: Skip the *site* transform which may be >20 mi
            # from Revit 2025's internal origin. Geometry is placed at
            # its 2026 project-internal coordinates for user alignment.
            return (1.,0.,0.,0.,0.)
        pc,ps,px,py,pz=self.placement(parent[0],depth+1)
        c,s,x,y,z=self.axisplacement(here[0])
        return (pc*c-ps*s,ps*c+pc*s,px+pc*x-ps*y,py+ps*x+pc*y,pz+z)

    def transform(self,xyz,place):
        c,s,x,y,z=place
        return (x+c*xyz[0]-s*xyz[1],y+s*xyz[0]+c*xyz[1],z+xyz[2])

    def get_bounds(self,faceid,transform):
        _,a=self.entity(faceid,'IFCFACE')
        boundaries=refs(a[0]);outer=None;holes=[]
        for rid in boundaries:
            name,args=self.entity(rid)
            if name not in ('IFCFACEOUTERBOUND','IFCFACEBOUND'):
                raise IFCError('Unexpected IFC face boundary type')
            loopid=refs(args[0])[0]
            _,loopargs=self.entity(loopid,'IFCPOLYLOOP')
            ring=[self.transform(self.point(i),transform) for i in refs(loopargs[0])]
            if args[1]=='.F.':ring.reverse()
            if name=='IFCFACEOUTERBOUND':
                if outer is not None:raise IFCError('Face with more than one outer boundary')
                outer=ring
            else:holes.append(ring)
        if not outer:raise IFCError('Face missing outer ring')
        return outer,holes

    def shapes(self,roofargs):
        placement_ids=refs(roofargs[5]); shape_ids=refs(roofargs[6]);
        if not placement_ids or not shape_ids:raise IFCError('IFC roof missing placement or geometry')
        _,d=self.entity(shape_ids[0],'IFCPRODUCTDEFINITIONSHAPE')
        representation_ids=refs(d[-1]); breps=[]
        for rid in representation_ids:
            name,rep=self.entity(rid,'IFCSHAPEREPRESENTATION')
            for item in refs(rep[-1]):
                kind,brep=self.entity(item)
                if kind!='IFCFACETEDBREP':
                    raise IFCError('Roof body is %s, not IFCFACETEDBREP'%kind)
                shellid=refs(brep[0])[0]
                _,shell=self.entity(shellid,'IFCCLOSEDSHELL')
                breps.append(refs(shell[0]))
        if not breps:raise IFCError('Roof missing faceted BRep geometry')
        return self.placement(placement_ids[0]),breps

    def roofs(self):
        all_roofs=[]
        for rid,(kind,body) in sorted(self.items.items()):
            if kind!='IFCROOF':continue
            _,args=self.entity(rid,'IFCROOF')
            globalid=args[0].strip("'")
            name=args[2].strip("'").replace("''", "'")
            place,breps=self.shapes(args)
            roof_faces=[]
            for shell in breps:
                for faceid in shell:
                    outer,holes=self.get_bounds(faceid,place)
                    normal=normal3(outer)
                    if normal[2]>=-0.7:continue
                    area=abs(area_xy(outer))-sum(abs(area_xy(h)) for h in holes)
                    if area<4.0:continue
                    plane=plane3(outer)
                    roof_faces.append(dict(outer3=outer,holes3=holes,
                                            normal=normal,plane=plane,area=area))
            if not roof_faces:
                raise IFCError('IFC roof %s has no sizable planar downward-facing underside'%name)
            roof_faces.sort(key=lambda f:-f['area'])
            if sum(f['area'] for f in roof_faces[1:]) > max(4.0,.05*roof_faces[0]['area']):
                raise IFCError('IFC roof %s has multiple substantial undersides; safe surface split required'%name)
            # This initial importer handles the actual file supplied: one
            # large planar underside per roof, possibly with through-openings.
            f=roof_faces[0]
            for ring in [f['outer3']]+f['holes3']:
                for p in ring:
                    if abs(p[2]-(f['plane'][0]*p[0]+f['plane'][1]*p[1]+f['plane'][2]))>1./192.:
                        raise IFCError('Opening edges on another roof plane')
            all_roofs.append(dict(ifc_id=globalid,name=name,area=f['area'],
                                  plane=f['plane'],outer=[(p[0],p[1]) for p in f['outer3']],
                                  holes=[[(p[0],p[1]) for p in ring] for ring in f['holes3']]))
        if not all_roofs:raise IFCError('IFC has no IfcRoof elements. Please export roof-only IFC2x3')
        return all_roofs
