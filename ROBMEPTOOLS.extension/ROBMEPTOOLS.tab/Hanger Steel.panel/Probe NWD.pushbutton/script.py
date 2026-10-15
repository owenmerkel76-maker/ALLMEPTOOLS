# -*- coding: utf-8 -*-
"""STEELTOOLS v0.4.5 - Nested NWD API geometry diagnostic for Revit 2025.
No picking, no Tab selection, no transactions and no changes to the Revit model.

The linked NWD is a DirectContext3D coordination handle. This probe reports
what the PUBLIC Revit API can read. A link-wide bounding box is NEVER treated
as bottom-of-steel elevation or as a member's bounding box.
"""
from __future__ import division
import os
import datetime
import traceback

from pyrevit import revit, DB, forms, script

DOC = revit.doc
UIDOC = revit.uidoc
OUTPUT = script.get_output()
TITLE = 'STEELTOOLS | Probe NWD (nested geometry)'
VERSION = 'v0.4.5'
REPORT = []
MAX_SAMPLE = 40
MAX_TOTAL_OBJECTS = 120
MAX_CHILDREN_PER_LEVEL = 40
MAX_DEPTH = 2
MAX_GEOMETRY_INSTANCES = 4


def txt(value):
    if value is None:
        return u'<none>'
    try:
        return unicode(value)
    except Exception:
        try:
            return unicode(str(value), 'utf-8', 'replace')
        except Exception:
            return u'<unprintable>'


def log(message=''):
    REPORT.append(txt(message))


def id_str(elid):
    if elid is None:
        return '<none>'
    try:
        return txt(elid.Value)
    except Exception:
        try:
            return txt(elid.IntegerValue)
        except Exception:
            return txt(elid)


def prop(obj, attr):
    if obj is None:
        return '<none>'
    try:
        return txt(getattr(obj, attr))
    except Exception as ex:
        return '<not exposed: %s>' % type(ex).__name__


def bboxes_for(el):
    try:
        bb = el.get_BoundingBox(None)
        if bb is None:
            return 'No bounding box available.'
        coords = []
        for x in (bb.Min.X, bb.Max.X):
            for y in (bb.Min.Y, bb.Max.Y):
                for z in (bb.Min.Z, bb.Max.Z):
                    coords.append(bb.Transform.OfPoint(DB.XYZ(x, y, z)))
        return ('WHOLE COORDINATION LINK extents, NOT steel BOS: '
                'X %.4f to %.4f; Y %.4f to %.4f; Z %.4f to %.4f ft (internal coordinates)' %
                (min(p.X for p in coords), max(p.X for p in coords),
                 min(p.Y for p in coords), max(p.Y for p in coords),
                 min(p.Z for p in coords), max(p.Z for p in coords)))
    except Exception as ex:
        return 'Bounding box unavailable: %s: %s' % (type(ex).__name__, txt(ex))


def get_coordination_links():
    # Autodesk uses DirectContext3D handles to represent local coordination models.
    collected = {}
    log('Discovery A: Revit OST_Coordination_Model category')
    try:
        els = (DB.FilteredElementCollector(DOC)
               .OfCategory(DB.BuiltInCategory.OST_Coordination_Model)
               .WhereElementIsNotElementType().ToElements())
        for e in els:
            collected[id_str(e.Id)] = e
        log('  Category collector returned %d instance(s).' % len(els))
    except Exception as ex:
        log('  Category collector unavailable: %s: %s' % (type(ex).__name__, txt(ex)))
    log('Discovery B: DirectContext3D coordination handles')
    try:
        from Autodesk.Revit.DB.DirectContext3D import DirectContext3DDocumentUtils
        catid = DB.ElementId(DB.BuiltInCategory.OST_Coordination_Model)
        ids = DirectContext3DDocumentUtils.GetDirectContext3DHandleInstances(DOC, catid)
        log('  Handle API returned %d instance(s).' % len(ids))
        for eid in ids:
            e = DOC.GetElement(eid)
            if e is not None:
                collected[id_str(eid)] = e
    except Exception as ex:
        log('  Handle API unavailable: %s: %s' % (type(ex).__name__, txt(ex)))
    return sorted(collected.values(), key=lambda e: id_str(e.Id))


def candidate_label(el):
    name = prop(el, 'Name')
    try:
        elem_type = DOC.GetElement(el.GetTypeId())
        type_name = prop(elem_type, 'Name')
    except Exception:
        type_name = '<unknown type>'
    return 'ID %s | %s | %s' % (id_str(el.Id), name, type_name)


def report_link(el, i):
    log('')
    log('LINK %d: %s' % (i, candidate_label(el)))
    log('  Class: %s' % prop(el.GetType(), 'FullName'))
    try:
        log('  Category: %s' % txt(el.Category.Name))
    except Exception:
        log('  Category: unavailable')
    log('  ' + bboxes_for(el))
    try:
        typ = DOC.GetElement(el.GetTypeId())
        if typ is not None:
            for p in typ.Parameters:
                try:
                    pname = txt(p.Definition.Name)
                    if ('path' in pname.lower() or 'file' in pname.lower() or
                        'name' in pname.lower()):
                        val = p.AsString() or p.AsValueString()
                        if val:
                            log('  Type property %s: %s' % (pname, txt(val)))
                except Exception:
                    continue
    except Exception:
        pass


def geometry_summary(obj):
    """Only informational counts; not certified beam geometry."""
    kind = prop(obj.GetType(), 'FullName')
    try:
        if isinstance(obj, DB.Solid):
            return kind + ' | faces=%d edges=%d volume=%.3f cu.ft.' % (
                obj.Faces.Size, obj.Edges.Size, obj.Volume)
        if isinstance(obj, DB.Mesh):
            return kind + ' | triangles=%d' % obj.NumTriangles
        if isinstance(obj, DB.Curve):
            return kind + ' | length=%.3f ft' % obj.Length
        if isinstance(obj, DB.PolyLine):
            return kind + ' | points=%d' % len(obj.GetCoordinates())
    except Exception as ex:
        return kind + ' | details unavailable (%s)' % type(ex).__name__
    return kind


def walk_geometry(geometry, depth, state, prefix):
    """Bounded, read-only inspection. GetInstanceGeometry can be costly; stop early."""
    if geometry is None:
        log('  %s returned null.' % prefix)
        return
    local_count = 0
    for obj in geometry:
        if state['count'] >= MAX_TOTAL_OBJECTS:
            state['truncated'] = True
            break
        if local_count >= MAX_CHILDREN_PER_LEVEL:
            state['truncated'] = True
            log('  %s: stopped after %d children.' % (prefix, MAX_CHILDREN_PER_LEVEL))
            break
        local_count += 1
        state['count'] += 1
        t = prop(obj.GetType(), 'FullName')
        state['types'][t] = state['types'].get(t, 0) + 1
        if isinstance(obj, DB.Solid):
            try:
                if obj.Faces.Size > 0:
                    state['solids'] += 1
            except Exception:
                pass
        if isinstance(obj, DB.Mesh):
            try:
                if obj.NumTriangles > 0:
                    state['meshes'] += 1
            except Exception:
                pass
        if len(state['samples']) < 24:
            state['samples'].append('  %s[%d]: %s' % (
                prefix, local_count, geometry_summary(obj)))
        if isinstance(obj, DB.GeometryInstance):
            if depth >= MAX_DEPTH:
                log('  %s[%d]: nested GeometryInstance; depth limit reached.' % (prefix, local_count))
                state['truncated'] = True
                continue
            if state['expanded'] >= MAX_GEOMETRY_INSTANCES:
                log('  %s[%d]: nested GeometryInstance; expansion count limit reached.' % (prefix, local_count))
                state['truncated'] = True
                continue
            state['expanded'] += 1
            try:
                xf = obj.Transform
                if xf is not None:
                    log('  %s[%d]: instance origin (%.4f, %.4f, %.4f) internal feet' % (
                        prefix, local_count, xf.Origin.X, xf.Origin.Y, xf.Origin.Z))
            except Exception as ex:
                log('  %s[%d]: transform unavailable (%s)' % (prefix, local_count, type(ex).__name__))
            try:
                child = obj.GetInstanceGeometry()
                if child is None:
                    log('  %s[%d]: GetInstanceGeometry() returned null.' % (prefix, local_count))
                else:
                    log('  %s[%d]: GetInstanceGeometry() succeeded; inspecting children.' % (prefix, local_count))
                    walk_geometry(child, depth + 1, state, prefix + '/instance')
            except Exception as ex:
                log('  %s[%d]: GetInstanceGeometry FAILED: %s: %s' % (
                    prefix, local_count, type(ex).__name__, txt(ex)))
                # Symbol geometry may only be in LOCAL symbol coordinates.
                # We report availability, not extents or BOS.
                try:
                    sg = obj.GetSymbolGeometry()
                    if sg is None:
                        log('  %s[%d]: GetSymbolGeometry() also returned null.' % (prefix, local_count))
                    else:
                        log('  %s[%d]: GetSymbolGeometry() returned geometry in SYMBOL-LOCAL coordinates.' % (
                            prefix, local_count))
                        walk_geometry(sg, depth + 1, state, prefix + '/symbol-local')
                        state['used_local_coords'] = True
                except Exception as symex:
                    log('  %s[%d]: GetSymbolGeometry FAILED: %s: %s' % (
                        prefix, local_count, type(symex).__name__, txt(symex)))
    if local_count == 0:
        log('  %s: empty GeometryElement.' % prefix)


def geometry_probe(el):
    log('')
    log('GEOMETRY API TEST - %s' % candidate_label(el))
    log('This reads geometry provided by a DirectContext3D coordination handle.')
    log('Linked NWD object identities, faces, and BOS are not assumed accessible.')
    try:
        opts = DB.Options()
        opts.ComputeReferences = False
        opts.IncludeNonVisibleObjects = False
        opts.DetailLevel = DB.ViewDetailLevel.Medium
        geo = el.get_Geometry(opts)
        if geo is None:
            log('Result: get_Geometry returned null.')
            log('STATUS: NO USABLE GEOMETRY exposed by this API call.')
            return
        state = {'count':0, 'types':{}, 'solids':0, 'meshes':0, 'expanded':0,
                 'truncated':False, 'samples':[], 'used_local_coords':False}
        log('Expanding up to %d GeometryInstances, depth %d; limit %d objects total.' % (
            MAX_GEOMETRY_INSTANCES, MAX_DEPTH, MAX_TOTAL_OBJECTS))
        walk_geometry(geo, 0, state, 'root')
        log('')
        log('Objects sampled (including nested): %d' % state['count'])
        log('Instance expansions: %d' % state['expanded'])
        log('Solids with faces: %d | Meshes with triangles: %d' % (
            state['solids'], state['meshes']))
        for t in sorted(state['types']):
            log('  type %s: %d' % (t, state['types'][t]))
        for sample in state['samples']:
            log(sample)
        if state['truncated']:
            log('NOTE: Traversal was capped for responsiveness; results are only a sample.')
        if state['used_local_coords']:
            log('NOTE: Some geometry was only accessible in symbol-local coordinates.')
        if state['solids'] or state['meshes']:
            log('STATUS: PRIMITIVE GEOMETRY FOUND; these may be placeholders or unrelated elements.')
            log('NO automatic BOS or individual steel-member classification established.')
        else:
            log('STATUS: NO SOLID/MESH PRIMITIVES FOUND in this bounded test.')
            log('Revit returned no identifiable individual steel members.')
        log('NEVER treat a whole-link or aggregate shape as an individual beam or its BOS.')
    except Exception as ex:
        log('Result: geometry access raised %s: %s' % (type(ex).__name__, txt(ex)))
        log(txt(traceback.format_exc()))
        log('STATUS: INCONCLUSIVE - API ERROR')

def choose_link(links):
    if len(links) == 1:
        return links[0]
    labels, lookup = [], {}
    for el in links:
        lab = candidate_label(el)
        labels.append(lab)
        lookup[lab] = el
    try:
        selected = forms.SelectFromList.show(labels, title='Select NWD coordination link to test',
                                              multiselect=False, button_name='Probe selected link')
        if selected:
            return lookup.get(selected)
    except Exception as ex:
        log('Selection dialog error: %s: %s' % (type(ex).__name__, txt(ex)))
    return None


def write_report():
    log('')
    log('INTERPRETATION: Nested geometry objects are not proof of IFC steel beam IDs, coordinates, or accurate BOS.')
    log('Whole-NWD bounding boxes and instances are NOT individual member coordinates or BOS.')
    log('No Revit elements were created, modified, or deleted.')
    candidates = []
    try:
        from System import Environment
        docs = txt(Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments))
        if docs and docs != '<none>':
            candidates.append(os.path.join(docs, 'STEELTOOLS_Reports'))
    except Exception:
        pass
    candidates.append(os.path.join(os.environ.get('TEMP', os.getcwd()), 'STEELTOOLS_Reports'))
    fname = 'Probe_NWD_Nested_%s.txt' % datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    final_path = None
    for folder in candidates:
        try:
            if not os.path.isdir(folder):
                os.makedirs(folder)
            final_path = os.path.join(folder, fname)
            with open(final_path, 'wb') as stream:
                stream.write(u('\r\n').join(REPORT).encode('utf-8', 'replace'))
            break
        except Exception:
            final_path = None
    try:
        OUTPUT.print_md('## STEELTOOLS - Nested NWD diagnostic v0.4.5')
        if final_path:
            OUTPUT.print_md('Report: `%s`' % txt(final_path).replace('`',''))
        OUTPUT.print_md('```text\n%s\n```' % u('\n').join(REPORT).replace('```', '~~~'))
    except Exception:
        for line in REPORT:
            try:
                print(line)
            except Exception:
                pass
    if final_path:
        forms.alert('Scan complete. No beam picking required.\n\n'
                    'Please send me this report:\n%s' % final_path, title=TITLE)
    else:
        forms.alert('Scan complete. Please copy the text from the pyRevit output window.', title=TITLE)


def main():
    log('STEELTOOLS %s - Read-only nested coordination model probe' % VERSION)
    log('Time: %s' % datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    log('Document: %s' % (txt(DOC.Title) if DOC else '<no project>'))
    if not DOC or not UIDOC:
        log('Open a Revit project before running this button.')
        return
    log('Revit: %s, build %s' % (prop(DOC.Application, 'VersionNumber'),
                                prop(DOC.Application, 'VersionBuild')))
    log('Active view: %s' % prop(UIDOC.ActiveView, 'Name'))
    log('No Tab selection or PickObject calls will be used.')
    log('Units: all coordinates in INTERNAL FEET (not project or Navisworks display elevations).')
    log('')
    links = get_coordination_links()
    log('Total detected linked coordination model instances: %d' % len(links))
    for i, el in enumerate(links[:30]):
        report_link(el, i + 1)
    if not links:
        log('No coordination link instances were found through either API route.')
        return
    chosen = choose_link(links)
    if chosen is None:
        log('Geometry probe skipped: no link selected. Inventory only.')
        return
    log('')
    log('Selected for geometry probing: %s' % candidate_label(chosen))
    try:
        ok = forms.alert('Inspect nested Revit API geometry of this NWD link?\n\n'
                         'No picking or model edits. Large NWD files may take time to inspect. Inspection is capped.',
                         title=TITLE, yes=True, no=True)
    except Exception:
        ok = False
    if ok:
        geometry_probe(chosen)
    else:
        log('Geometry test skipped at user request. Link inventory still completed.')


try:
    main()
except Exception as ex:
    log('UNHANDLED ERROR: %s: %s' % (type(ex).__name__, txt(ex)))
    log(txt(traceback.format_exc()))
finally:
    write_report()
