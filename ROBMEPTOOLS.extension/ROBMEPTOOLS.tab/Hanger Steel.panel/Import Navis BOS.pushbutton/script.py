# coding: utf-8
# STEELTOOLS v0.3 - Navisworks bounding box to native Revit Structural Framing
# Revit 2025 / pyRevit IronPython 2.7. No reliance on coordination geometry extraction in Revit.
from __future__ import division
import csv
import os
import hashlib
from pyrevit import revit, DB, forms, script

DOC = revit.doc
OUT = script.get_output()
MARKER = 'STEELTOOLS_NAVIS_BOS:'
FT_PER_UNIT = {'Meters': 3.28083989501312, 'Centimeters': .0328083989501312,
               'Millimeters': .00328083989501312, 'Feet': 1., 'Inches': 1./12.,
               'Yards': 3., 'Kilometers': 3280.83989501312,
               'Micrometers': .00000328083989501312}
MAX_IMPORT = 150
TOL_FT = 1.0 / 192.0  # physical BOS must be within 1/16 inch


def msg(text):
    forms.alert(text, title='STEELTOOLS | Batch BOS')


def safe_float(value):
    v = float(value)
    if v != v or abs(v) > 1000000000.0:
        raise ValueError('Invalid coordinate')
    return v


def candidate_from_row(row, index):
    if row.get('Format') != 'STBBOX1':
        return None, 'wrong_format'
    units = row.get('NavisUnits', '').strip()
    if units not in FT_PER_UNIT:
        return None, 'unsupported_units:' + units
    f = FT_PER_UNIT[units]
    try:
        x0, y0, z0, x1, y1, z1 = [safe_float(row[k])*f for k in
            ('MinX','MinY','MinZ','MaxX','MaxY','MaxZ')]
    except Exception:
        return None, 'bad_number'
    dx,dy,dz=x1-x0,y1-y0,z1-z0
    if min(dx,dy,dz) <= 0:
        return None,'invalid_box'
    long_length = max(dx,dy)
    width = min(dx,dy)
    if long_length < 6.0 or long_length > 150.0:
        return None,'length_filter'
    if width < .12 or width > 4.0:
        return None,'width_filter'
    if dz < .10 or dz > 4.0:
        return None,'height_filter'
    if long_length / width < 4.5:
        return None,'not_beam_like'
    axis='X' if dx > dy else 'Y'
    # Boxes are world-aligned; rotated/diagonal members can produce misleading centerlines.
    key = ('%.4f|%.4f|%.4f|%.4f|%.4f|%.4f' % (x0,y0,z0,x1,y1,z1))
    id_ = hashlib.sha1(key.encode('ascii')).hexdigest()[:16]
    item={'id': id_, 'name': row.get('Name',''), 'parent':row.get('ParentName',''),
          'box':(x0,y0,z0,x1,y1,z1), 'long':long_length,'width':width,
          'depth':dz,'axis':axis,'bos':z0,'index':index}
    return item, None


def load_scan(path):
    accepted, rejected, seen = [], {}, set()
    with open(path, 'rb') as fp:
        reader = csv.DictReader(fp)
        required = set(('Format','NavisUnits','Name','ParentName','MinX','MinY','MinZ','MaxX','MaxY','MaxZ'))
        if not required.issubset(set(reader.fieldnames or [])):
            raise ValueError('Not a STEELTOOLS Navisworks scanner CSV. Required columns missing.')
        for n, row in enumerate(reader):
            item, reason=candidate_from_row(row,n+2)
            if reason:
                rejected[reason]=rejected.get(reason,0)+1
                continue
            if item['id'] in seen:
                rejected['duplicate_box']=rejected.get('duplicate_box',0)+1
                continue
            seen.add(item['id'])
            accepted.append(item)
    return accepted,rejected


def type_name(symbol):
    # Avoid IronPython's FamilySymbol.Name reflection bug from the v0.1 traceback.
    try:
        p=symbol.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM)
        t=p.AsString() if p else None
        return t or '<Unnamed type>'
    except Exception:
        return '<Unnamed type>'


def min_solid_z(instance):
    opts=DB.Options()
    opts.ComputeReferences=False
    opts.IncludeNonVisibleObjects=False
    opts.DetailLevel=DB.ViewDetailLevel.Fine
    geo=instance.get_Geometry(opts)
    vals=[]
    def walk(elems):
        for geo_obj in elems:
            if isinstance(geo_obj,DB.Solid):
                if geo_obj.Volume > 1e-9:
                    bb=geo_obj.GetBoundingBox()
                    if bb is None: continue
                    for xx in (bb.Min.X,bb.Max.X):
                        for yy in (bb.Min.Y,bb.Max.Y):
                            for zz in (bb.Min.Z,bb.Max.Z):
                                vals.append(bb.Transform.OfPoint(DB.XYZ(xx,yy,zz)).Z)
            elif isinstance(geo_obj,DB.GeometryInstance):
                walk(geo_obj.GetInstanceGeometry())
    if geo: walk(geo)
    if not vals:
        raise Exception('No physical solid geometry; use a 3D structural beam family.')
    return min(vals)


def make_beam(doc, item, sym, level, offsets):
    x0,y0,z0,x1,y1,z1=item['box']
    ox,oy,oz=offsets
    # Centerline location is approximate. Z location is corrected using real generated solid geometry.
    if item['axis']=='X':
        a=DB.XYZ(x0+ox,(y0+y1)*.5+oy,z0+oz+1.0)
        b=DB.XYZ(x1+ox,(y0+y1)*.5+oy,z0+oz+1.0)
    else:
        a=DB.XYZ((x0+x1)*.5+ox,y0+oy,z0+oz+1.0)
        b=DB.XYZ((x0+x1)*.5+ox,y1+oy,z0+oz+1.0)
    line=DB.Line.CreateBound(a,b)
    instance=doc.Create.NewFamilyInstance(line,sym,level,DB.Structure.StructuralType.Beam)
    doc.Regenerate()
    measured=min_solid_z(instance)
    delta=z0+oz-measured
    if abs(delta)>1e-8:
        DB.ElementTransformUtils.MoveElement(doc,instance.Id,DB.XYZ(0,0,delta))
    doc.Regenerate()
    checked=min_solid_z(instance)
    if abs(checked-(z0+oz))>TOL_FT:
        raise Exception('BOS verification failed: target %.4f ft / measured %.4f ft' %(z0+oz,checked))
    p=instance.get_Parameter(DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
    if p and not p.IsReadOnly:
        p.Set(MARKER+item['id'])
    return instance,checked


def main():
    if DOC.IsFamilyDocument:
        msg('Open a Revit project, not the Family Editor.')
        return
    if int(DOC.Application.VersionNumber)!=2025:
        msg('This prototype is designed for Revit 2025. Current version: '+ DOC.Application.VersionNumber)
        return
    path=forms.pick_file(file_ext='csv',title='Select Navisworks STEELTOOLS scanner CSV')
    if not path:
        return
    try:
        candidates,rejected=load_scan(path)
    except Exception as ex:
        msg('Unable to read scan:\n'+str(ex))
        return
    if not candidates:
        msg('No beam-like candidates passed the conservative filters.\n\nRejected:\n'+str(rejected))
        return
    if len(candidates)>200000:
        msg('Too many candidates. Scan a smaller steel selection in Navisworks.')
        return
    xs=[(r['box'][0]+r['box'][3])*.5 for r in candidates]
    ys=[(r['box'][1]+r['box'][4])*.5 for r in candidates]
    bz=[r['bos'] for r in candidates]
    rej=', '.join(['%s: %s' %(k,v) for k,v in sorted(rejected.items())])
    summary='''Scan: %s
Beam-like bounding boxes: %d
Rejected/filtered: %d
BOS range in Navisworks coordinate system: %.3f to %.3f ft
X center range: %.1f .. %.1f ft
Y center range: %.1f .. %.1f ft

Excluded reasons: %s

WARNING: axis-aligned boxes may misidentify angled framing, plates, or IFC subparts. XY alignment with Revit is NOT automatically established.''' %(
        os.path.basename(path),len(candidates),sum(rejected.values()),min(bz),max(bz),min(xs),max(xs),min(ys),max(ys),rej[:450])
    OUT.print_md('### STEELTOOLS — Preview of Navisworks beam candidates')
    OUT.print_md('```\n'+summary+'\n```')
    OUT.print_md('| CSV Row | Source | Axis | Length ft | Width ft | BOS ft |')
    OUT.print_md('|---:|---|:---:|---:|---:|---:|')
    for r in candidates[:25]:
        name=(r['name'] or r['parent'] or '(unnamed)').replace('|','/')[:35]
        OUT.print_md('| %s | %s | %s | %.2f | %.2f | %.3f |' % (r['index'],name,r['axis'],r['long'],r['width'],r['bos']))
    choice=forms.CommandSwitchWindow.show(
        ['Preview only (no changes)', 'Create first 5 (test alignment)',
         'Create up to 150 (verified area only)'],
        message='Read the preview in the pyRevit output panel BEFORE creating elements.')
    if not choice or choice.startswith('Preview'):
        return
    # Global transform correction happens once per model, not for each beam.
    config=script.get_config()
    default=getattr(config,'navis_offsets_ft','0,0,0')
    txt=forms.ask_for_string(default=default,
        prompt='Navisworks -> Revit internal origin offsets DX,DY,DZ in FEET.\n'
        'Use 0,0,0 ONLY if the linked NWD and Revit internal coordinates align.\n'
        'This is a ONE-TIME model calibration, not individual BOS entry.',
        title='STEELTOOLS | Coordinate calibration')
    if txt is None:return
    try:
        v=[safe_float(s.strip()) for s in txt.split(',')]
        if len(v)!=3 or any(abs(t)>100000 for t in v):raise ValueError()
    except Exception:
        msg('Enter three numeric offsets separated by commas, for example 0,0,0')
        return
    offsets=tuple(v)
    config.navis_offsets_ft=txt
    script.save_config()
    all_syms=list(DB.FilteredElementCollector(DOC).OfClass(DB.FamilySymbol).OfCategory(DB.BuiltInCategory.OST_StructuralFraming))
    if not all_syms:
        msg('No Structural Framing family loaded. Load a 3D beam family first.')
        return
    names={}
    for sym in all_syms:
        try:
            fam=sym.Family
            family_name=fam.Name if fam else 'Framing'
            key='%s : %s [ID %s]' %(family_name,type_name(sym),sym.Id.IntegerValue)
            names[key]=sym
        except Exception:
            pass
    selected=forms.SelectFromList.show(sorted(names.keys()),
               title='Select Physical Structural Framing Type (bottom face will match BOS)',button_name='Use Type')
    if not selected: return
    sym=names[selected]
    levels=list(DB.FilteredElementCollector(DOC).OfClass(DB.Level))
    if not levels:
        msg('Project has no levels.')
        return
    levels.sort(key=lambda l:l.Elevation)
    opts=['%s  [%.2f ft]' % (str(l.Name),l.Elevation) for l in levels]
    level_choice=forms.SelectFromList.show(opts,title='Reference Level for Proxies',button_name='Use Level')
    if not level_choice:return
    level=levels[opts.index(level_choice)]
    # Do not create duplicates on reruns; comments on created elements store stable geometry ID.
    existing=set()
    for fi in DB.FilteredElementCollector(DOC).OfCategory(DB.BuiltInCategory.OST_StructuralFraming).WhereElementIsNotElementType():
        try:
            p=fi.get_Parameter(DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
            value=p.AsString() if p else ''
            if value and value.startswith(MARKER):existing.add(value[len(MARKER):])
        except Exception:pass
    if '150' in choice and not existing:
        msg('Bulk creation is locked until you have created and checked a 5-beam test batch. Run Create first 5, inspect the NWD alignment and rod attachment, then rerun to import more.')
        return
    wanted=5 if 'first 5' in choice else MAX_IMPORT
    todo=[r for r in candidates if r['id'] not in existing][:wanted]
    if not todo:
        msg('All candidates in this batch have already been imported. No duplicates placed.')
        return
    if not forms.alert('Create %d STRUCTURAL FRAMING proxies?\n\n'
        'YOU MUST HAVE VERIFIED XY ALIGNMENT AND A KNOWN BOS DATUM.\n'
        'Coordinate offsets (ft): %s\n'
        'This is NOT a structural design or an authoritative hanger elevation.\n\n'
        'Test one rod connection and compare against the NWD before bulk import.' %(len(todo),str(offsets)),
        title='STEELTOOLS — Confirm experimental placement',yes=True,no=True):
        return
    transaction=DB.Transaction(DOC,'STEELTOOLS - import Navisworks hanger BOS proxy framing')
    created,failures=[],[]
    try:
        transaction.Start()
        if not sym.IsActive:
            sym.Activate()
            DOC.Regenerate()
        for item in todo:
            # A subtransaction prevents a failed/invalid beam from being left in the model.
            child=DB.SubTransaction(DOC)
            try:
                x0,y0,z0,x1,y1,z1=item['box']
                if max(abs(x0+offsets[0]),abs(y0+offsets[1]),abs(x1+offsets[0]),abs(y1+offsets[1]))>40000:
                    raise Exception('Coordinates too far from Revit origin; calibrate first.')
                child.Start()
                fi,z=make_beam(DOC,item,sym,level,offsets)
                child.Commit()
                created.append((fi.Id,item,z))
            except Exception as ex:
                try:
                    if child.GetStatus()==DB.TransactionStatus.Started:
                        child.RollBack()
                except Exception:
                    pass
                failures.append((item['index'],str(ex)))
        transaction.Commit()
    except Exception as ex:
        if transaction.GetStatus()==DB.TransactionStatus.Started:transaction.RollBack()
        msg('Batch rolled back: '+str(ex))
        return
    OUT.print_md('### Import results')
    OUT.print_md('Created **%s** proxies, skipped **%s** previously imported, failed **%s**.' %
                 (len(created),len(existing.intersection(set([r['id'] for r in candidates]))),len(failures)))
    for line,err in failures[:20]:OUT.print_md('* Row %s: %s' %(line,err.replace('|','/')))
    if created:
        OUT.print_md('**Created Element IDs (first 20):** '+', '.join([str(x[0].IntegerValue) for x in created[:20]]))
    msg('Placed %d verified-BOS proxy beam(s).\nFailures: %d.\n\n'
        'IMPORTANT: Check underside AND X/Y against NWD. Then test actual Fabrication hanger rod attachment.' % (len(created),len(failures)))


if __name__ == '__main__':
    main()
