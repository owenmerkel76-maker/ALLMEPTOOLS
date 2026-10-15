# -*- coding: utf-8 -*-
"""STEELTOOLS / Joist Groups v0.5.1 (Revit 2025, pyRevit IronPython 2.7).

User defines BOS at start and end of the first member, or one BOS + roof pitch.
Parallel arrays may also change BOS across the joist row. A member is a
straight sloping Structural Framing proxy; only verified 3D solids are kept.

Locked NWD geometry cannot be scanned from Revit 2025: all elevations must be
verified from design records or measurements before using hanger supports.
For tapered/kinked/curved chords or a change in slope: split the group.

Physical underside is measured by solid / vertical-line intersections at
multiple interior stations. An unverifiable member is removed. All created
proxies are undoable together; no real framing is changed.
"""
from __future__ import division

import math
import traceback
import re

from pyrevit import DB, forms, script
from Autodesk.Revit.DB.Structure import StructuralType
from Autodesk.Revit.Exceptions import OperationCanceledException

__title__ = 'Slope\nJoists'
__doc__ = 'Build flat/sloped joist support proxies by BOS start/end or roof pitch, with optional elevation change across an array and measured underside verification.'

uidoc = __revit__.ActiveUIDocument
if uidoc is None:
    forms.alert('Open a Revit project first.', title='STEELTOOLS')
    script.exit()
doc = uidoc.Document
view = uidoc.ActiveView
if doc.IsFamilyDocument:
    forms.alert('Run this in a Revit project.', title='STEELTOOLS')
    script.exit()

MAX_GROUPS = 30
MAX_PER_GROUP = 100
MAX_TOTAL = 200
MIN_SPAN = 0.5
MIN_SPACING = 0.15
XY_TOL = 1.0 / 48.0                # 1/4 in for matching existing axes
BOS_DUP_TOL = 1.0 / 12.0          # 1 in for duplicate detection
BOS_VERIFY_TOL = 1.0 / 192.0     # 1/16 in for placed physical solids
Z_AXIS = DB.XYZ.BasisZ


def name_of(el):
    if el is None:
        return '<none>'
    try:
        p = el.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM)
        if p and p.HasValue:
            s = p.AsString() or p.AsValueString()
            if s:
                return str(s)
    except Exception:
        pass
    try:
        return str(DB.Element.Name.GetValue(el))
    except Exception:
        try:
            return str(el.Name)
        except Exception:
            return 'Id {}'.format(el.Id.IntegerValue)


def symbol_name(sym):
    try:
        fam = sym.FamilyName
    except Exception:
        try:
            fam = name_of(sym.Family)
        except Exception:
            fam = 'Structural Framing'
    return '{} : {} [ID {}]'.format(fam, name_of(sym), sym.Id.IntegerValue)


def level_z(lev):
    return lev.ProjectElevation


def level_name(lev):
    return '{} (project Z {:+.3f} ft)'.format(name_of(lev), level_z(lev))


def fmt(z):
    return '{:+.3f} ft'.format(z)


def parse_number_with_fraction(raw):
    """Accept 4, 4.25, 4 1/2, 1/2, -1/2 (inches/feet before conversion)."""
    s = str(raw).strip()
    if not s:
        raise ValueError('Enter a distance.')
    sign = -1.0 if s.startswith('-') else 1.0
    if s[0:1] in ('-', '+'):
        s = s[1:].strip()
    if not s:
        raise ValueError('Enter a number.')
    parts = s.split()
    if len(parts) > 2:
        raise ValueError('Invalid fraction: {}'.format(raw))
    total = 0.0
    for p in parts:
        if '/' in p:
            num, den = p.split('/', 1)
            den = float(den)
            if den == 0:
                raise ValueError('A fraction cannot have denominator zero.')
            total += float(num) / den
        else:
            total += float(p)
    if math.isnan(total) or math.isinf(total):
        raise ValueError('Non-finite number.')
    return sign * total


def parse_ft(raw, empty_as_zero=False):
    """Return internal feet. Bare numbers are decimal FEET, quotes are inches.

    Supports: 12'-6 1/2\", 12'-6.5\", 6\", 12.5, -2'-3\", +1/4\".
    """
    s = str(raw or '').strip().replace(u'\u2032', "'").replace(u'\u2033', '"')
    s = s.replace(u'\u2212', '-').replace(',', '')
    if not s:
        if empty_as_zero:
            return 0.0
        raise ValueError('Enter the group Bottom of Steel elevation.')
    s = s.strip()
    sign = -1.0 if s.startswith('-') else 1.0
    if s[0:1] in ('-', '+'):
        s = s[1:].strip()
    if "'" in s:
        footpart, inchpart = s.split("'", 1)
        feet = parse_number_with_fraction(footpart)
        inchpart = inchpart.strip().replace('"', '').lstrip('-').strip()
        inches = parse_number_with_fraction(inchpart) if inchpart else 0.0
        if feet < 0 or not (0 <= inches < 12):
            raise ValueError('Use 0-11 15/16 inches after the foot mark.')
        val = feet + inches / 12.0
    elif '"' in s:
        val = parse_number_with_fraction(s.replace('"', '')) / 12.0
    else:
        val = parse_number_with_fraction(s)
    if math.isnan(val) or math.isinf(val):
        raise ValueError('Invalid non-finite length.')
    return sign * val


def pxy(p, z):
    return DB.XYZ(p.X, p.Y, z)


def equal_axis(a, b, c, d):
    # All XY checks deliberately ignore reference-line Z. BOS is checked apart.
    dx = lambda p, q: math.hypot(p.X - q.X, p.Y - q.Y)
    return ((dx(a, c) < XY_TOL and dx(b, d) < XY_TOL) or
            (dx(a, d) < XY_TOL and dx(b, c) < XY_TOL))


symbols = sorted(list(DB.FilteredElementCollector(doc).OfClass(DB.FamilySymbol)
                      .OfCategory(DB.BuiltInCategory.OST_StructuralFraming)),
                 key=lambda el: symbol_name(el).lower())
levels = sorted(list(DB.FilteredElementCollector(doc).OfClass(DB.Level)),
                key=lambda el: level_z(el))
if not symbols:
    forms.alert('No native Structural Framing family types loaded.\n'
                'Load a suitable beam family before running Joist Groups.',
                title='STEELTOOLS')
    script.exit()
if not levels:
    forms.alert('No Revit levels were found.', title='STEELTOOLS')
    script.exit()



class GroupDialog(forms.WPFWindow):
    def __init__(self, prior, index, queued):
        forms.WPFWindow.__init__(self, script.get_bundle_file('ui.xaml'))
        self.value = None
        self.beams = {}
        self.levels = {}
        self.session_title.Text = 'Area {} | {} queued support members'.format(index, queued)
        for sym in symbols:
            label = symbol_name(sym)
            self.beams[label] = sym
            self.beam_combo.Items.Add(label)
        for lev in levels:
            label = level_name(lev)
            self.levels[label] = lev
            self.level_combo.Items.Add(label)
        self.mode_combo.Items.Add('Parallel array | 3 XY picks')
        self.mode_combo.Items.Add('Irregular trace | 2 XY picks per beam')
        self.zmode_combo.Items.Add('BOS offset above selected Revit level')
        self.zmode_combo.Items.Add('Absolute BOS | Revit internal project Z')
        self.group_text.Text = 'Joist Area {}'.format(index)
        self.count_text.Text = str(prior.get('count', 8))
        self.step_start_text.Text = '0'
        self.step_end_text.Text = ''
        # Never silently carry elevations into a new region.
        self.bos_start_text.Text = ''
        self.bos_end_text.Text = ''
        self.pitch_text.Text = ''
        self.beam_combo.SelectedIndex = prior.get('sym_idx', 0)
        self.level_combo.SelectedIndex = prior.get('lev_idx', 0)
        self.mode_combo.SelectedIndex = prior.get('mode', 0)
        self.zmode_combo.SelectedIndex = prior.get('zmode', 0)
        self.mode_combo.SelectionChanged += self.mode_changed
        self.run_button.Click += self.on_start
        self.cancel_button.Click += self.on_cancel
        self.mode_changed(None, None)

    def mode_changed(self, sender, args):
        is_array = self.mode_combo.SelectedIndex == 0
        self.count_text.IsEnabled = is_array
        self.step_start_text.IsEnabled = is_array
        self.step_end_text.IsEnabled = is_array
        if is_array:
            self.pick_help.Text = ('ARRAY: pick FIRST joist START, FIRST joist END, '
                                   'then a corresponding point on the NEXT '
                                   'joist for perpendicular spacing.')
        else:
            self.pick_help.Text = ('TRACE: pick START then END for each member; '
                                   'Esc at the next START ends this area. '
                                   'Cross-row BOS steps do not apply.')

    def on_cancel(self, sender, args):
        self.DialogResult = False
        self.Close()

    def on_start(self, sender, args):
        try:
            mode = int(self.mode_combo.SelectedIndex)
            number = int(str(self.count_text.Text).strip()) if mode == 0 else 1
            if number < 1 or number > MAX_PER_GROUP:
                raise ValueError('Count must be 1 to {} members.'.format(MAX_PER_GROUP))
            sym = self.beams[str(self.beam_combo.SelectedItem)]
            lev = self.levels[str(self.level_combo.SelectedItem)]
            mode_z = int(self.zmode_combo.SelectedIndex)
            base_z = level_z(lev) if mode_z == 0 else 0.0
            start = parse_ft(self.bos_start_text.Text) + base_z
            end_raw = str(self.bos_end_text.Text).strip()
            pitch_raw = str(self.pitch_text.Text).strip()
            if end_raw and pitch_raw:
                raise ValueError('Use either END BOS or RISE in/ft, not both.')
            pitch = parse_number_with_fraction(pitch_raw) if pitch_raw else None
            if pitch is not None and abs(pitch) > 24.0:
                raise ValueError('Rise in/ft outside +/-24. Check pitch units.')
            end = (parse_ft(end_raw) + base_z) if end_raw else None
            s_start = parse_ft(self.step_start_text.Text, True) if mode == 0 else 0.0
            raw_step_end = str(self.step_end_text.Text).strip()
            s_end = parse_ft(raw_step_end) if (mode == 0 and raw_step_end) else s_start
            if abs(s_start) > 10.0 or abs(s_end) > 10.0:
                raise ValueError('Cross-row BOS change per joist exceeds 10 ft.')
            # If steps differ, each joist has a different pitch. This is a
            # deliberate complex grading input and must be independently verified.
            name = str(self.group_text.Text).strip() or 'Joist Area'
            if len(name) > 80:
                raise ValueError('Keep the area name under 80 characters.')
            self.value = dict(label=name, symbol=sym, level=lev, mode=mode,
                              count=number, bos_start=start, bos_end=end,
                              pitch=pitch, step_start=s_start, step_end=s_end,
                              sym_idx=int(self.beam_combo.SelectedIndex),
                              lev_idx=int(self.level_combo.SelectedIndex),
                              zmode=mode_z, entered=str(self.bos_start_text.Text))
            self.DialogResult = True
            self.Close()
        except Exception as ex:
            forms.alert(str(ex), title='STEELTOOLS | Check Joist Settings')


def ensure_pick_plane(lev):
    if view.ViewType != DB.ViewType.ThreeD:
        return
    if view.IsPerspective:
        raise ValueError('Use an orthographic 3D or plan view, not perspective.')
    try:
        old = view.SketchPlane
        if old and abs(old.GetPlane().Normal.Z) > 0.999:
            return
    except Exception:
        pass
    t = DB.Transaction(doc, 'STEELTOOLS | Set XY picking plane')
    try:
        t.Start()
        plane = DB.Plane.CreateByNormalAndOrigin(Z_AXIS, DB.XYZ(0, 0, level_z(lev)))
        view.SketchPlane = DB.SketchPlane.Create(doc, plane)
        t.Commit()
    except Exception as ex:
        try:
            t.RollBack()
        except Exception:
            pass
        raise ValueError('Could not set 3D picking plane: {}. Try plan view.'.format(ex))


def choose_end_bos(cfg, horizontal_span):
    if cfg['bos_end'] is not None:
        return cfg['bos_end']
    if cfg['pitch'] is not None:
        return cfg['bos_start'] + cfg['pitch'] * horizontal_span / 12.0
    return cfg['bos_start']


def pick_group(cfg):
    out = []
    if cfg['mode'] == 0:
        forms.alert('AREA: {}\n\nPick 3 points on the horizontal work plane:\n'
                    '1. First joist START\n2. First joist END\n'
                    '3. Point on NEXT joist (establish spacing)\n\n'
                    'These are visual XY picks, NOT measured NWD points. '
                    'BOS is calculated from your typed elevations/pitch.'.format(cfg['label']),
                    title='STEELTOOLS | Pick Joist Array')
        p1 = uidoc.Selection.PickPoint('FIRST JOIST START | {}'.format(cfg['label']))
        p2 = uidoc.Selection.PickPoint('FIRST JOIST END | {}'.format(cfg['label']))
        p3 = uidoc.Selection.PickPoint('NEXT JOIST SPACING | {}'.format(cfg['label']))
        vx, vy = p2.X - p1.X, p2.Y - p1.Y
        length = math.hypot(vx, vy)
        if length < MIN_SPAN:
            raise ValueError('Joist span is shorter than 6 inches.')
        nx, ny = -vy / length, vx / length
        spacing = (p3.X - p1.X) * nx + (p3.Y - p1.Y) * ny
        if cfg['count'] > 1 and abs(spacing) < MIN_SPACING:
            raise ValueError('Array spacing too small; pick NEXT joist.')
        cfg['spacing'] = spacing
        base_end = choose_end_bos(cfg, length)
        for i in range(cfg['count']):
            x_shift, y_shift = i*spacing*nx, i*spacing*ny
            out.append(dict(a=DB.XYZ(p1.X+x_shift, p1.Y+y_shift, level_z(cfg['level'])),
                            b=DB.XYZ(p2.X+x_shift, p2.Y+y_shift, level_z(cfg['level'])),
                            bos_start=cfg['bos_start'] + i*cfg['step_start'],
                            bos_end=base_end + i*cfg['step_end'],
                            group=cfg['label'], order=i+1, symbol=cfg['symbol'],
                            level=cfg['level']))
    else:
        forms.alert('TRACE {}\n\nPick START and END for each beam. '
                    'Esc at next START to finish this area. '
                    'Each uses the area start/end BOS (or pitch).'.format(cfg['label']),
                    title='STEELTOOLS | Trace Joists')
        for i in range(MAX_PER_GROUP):
            try:
                p1 = uidoc.Selection.PickPoint('JOIST {} START (Esc finishes)'.format(i+1))
            except OperationCanceledException:
                break
            try:
                p2 = uidoc.Selection.PickPoint('JOIST {} END'.format(i+1))
            except OperationCanceledException:
                break
            length = math.hypot(p2.X-p1.X, p2.Y-p1.Y)
            if length < MIN_SPAN:
                forms.alert('Joist too short, skipped.', title='STEELTOOLS')
                continue
            out.append(dict(a=pxy(p1, level_z(cfg['level'])),
                            b=pxy(p2, level_z(cfg['level'])),
                            bos_start=cfg['bos_start'],
                            bos_end=choose_end_bos(cfg, length),
                            group=cfg['label'], order=i+1,
                            symbol=cfg['symbol'], level=cfg['level']))
    return out


def comment_bos_range(el):
    try:
        p = el.get_Parameter(DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        s = (p.AsString() or '') if p else ''
        start = re.search(r'STEELTOOLS BOS START=([-+0-9.]+)', s)
        end = re.search(r'STEELTOOLS BOS END=([-+0-9.]+)', s)
        if start and end:
            return float(start.group(1)), float(end.group(1))
        previous = re.search(r'STEELTOOLS GROUP BOS=([-+0-9.]+)', s)
        if previous:
            return float(previous.group(1)), float(previous.group(1))
    except Exception:
        pass
    return None


def current_axes():
    axes = []
    for el in DB.FilteredElementCollector(doc).OfCategory(
            DB.BuiltInCategory.OST_StructuralFraming).WhereElementIsNotElementType():
        try:
            loc = el.Location
            if not isinstance(loc, DB.LocationCurve) or not isinstance(loc.Curve, DB.Line):
                continue
            a, b = loc.Curve.GetEndPoint(0), loc.Curve.GetEndPoint(1)
            z = comment_bos_range(el)
            if z:
                axes.append((a, b, z[0], z[1]))
            else:
                # Unknown actual underside: flag XY duplicate conservatively.
                axes.append((a, b, None, None))
        except Exception:
            continue
    return axes


def deduplicate(proposals):
    axes = current_axes()
    accepted, skipped = [], []
    for p in proposals:
        a, b, low, high = p['a'], p['b'], p['bos_start'], p['bos_end']
        is_dupe = False
        for aa, bb, low2, high2 in axes:
            if equal_axis(a, b, aa, bb):
                # An existing member with no metadata cannot be presumed safe to overlap.
                reversed_axis = (math.hypot(a.X-bb.X,a.Y-bb.Y) < XY_TOL)
                if low2 is None or (abs(low-(high2 if reversed_axis else low2)) < BOS_DUP_TOL
                                     and abs(high-(low2 if reversed_axis else high2)) < BOS_DUP_TOL):
                    is_dupe = True
                    break
        if not is_dupe:
            for old in accepted:
                if equal_axis(a,b,old['a'],old['b']):
                    flipped = math.hypot(a.X-old['b'].X,a.Y-old['b'].Y) < XY_TOL
                    if (abs(low-(old['bos_end'] if flipped else old['bos_start'])) < BOS_DUP_TOL and
                        abs(high-(old['bos_start'] if flipped else old['bos_end'])) < BOS_DUP_TOL):
                        is_dupe=True
                        break
        if is_dupe:
            skipped.append('{} #{}: duplicate XY axis or existing framing'.format(p['group'],p['order']))
        else:
            accepted.append(p)
    return accepted, skipped


def all_solids(inst):
    op = DB.Options()
    op.DetailLevel = DB.ViewDetailLevel.Fine
    op.IncludeNonVisibleObjects = False
    out=[]
    def collect(geo, depth=0):
        if geo is None or depth > 5:
            return
        for obj in geo:
            if isinstance(obj, DB.Solid):
                try:
                    if obj.Volume > 0.000001 and obj.Faces.Size > 0:
                        out.append(obj)
                except Exception:
                    pass
            elif isinstance(obj, DB.GeometryInstance):
                try:
                    collect(obj.GetInstanceGeometry(), depth+1)
                except Exception:
                    pass
    collect(inst.get_Geometry(op))
    return out


def sample_underface(inst, xy_start, xy_end, fractions, target0, target1):
    """Project vertical test lines through the member centerline.

    Actual bottom = minimum Z of all inside-solid intersection segments.
    This tests physical 3D support surfaces, not family reference-line offsets.
    """
    solids = all_solids(inst)
    if not solids:
        raise ValueError('No measurable solid; choose a physical beam family.')
    results = []
    vertical_low = min(target0, target1)-30.0
    vertical_high = max(target0, target1)+30.0
    opts = DB.SolidCurveIntersectionOptions()
    for f in fractions:
        x = xy_start.X + f*(xy_end.X-xy_start.X)
        y = xy_start.Y + f*(xy_end.Y-xy_start.Y)
        probe = DB.Line.CreateBound(DB.XYZ(x,y,vertical_low),
                                    DB.XYZ(x,y,vertical_high))
        hits=[]
        for solid in solids:
            try:
                crossed = solid.IntersectWithCurve(probe, opts)
                for i in range(crossed.SegmentCount):
                    seg = crossed.GetCurveSegment(i)
                    hits.append(min(seg.GetEndPoint(0).Z,seg.GetEndPoint(1).Z))
            except Exception:
                pass
        if not hits:
            raise ValueError('No solid underside at {:g}% span; '
                             'try a simple W-shape or rectangular beam family.'.format(100*f))
        results.append(min(hits))
    return results


def set_axis_z(inst, xy_a, xy_b, start_z, end_z):
    loc = inst.Location
    if not isinstance(loc, DB.LocationCurve):
        raise ValueError('Beam has no editable location line.')
    loc.Curve = DB.Line.CreateBound(DB.XYZ(xy_a.X,xy_a.Y,start_z),
                                    DB.XYZ(xy_b.X,xy_b.Y,end_z))


def align_and_verify(inst, p):
    """Iterate end reference elevations until underside agrees at BOTH ends.

    We measure at fractions .2/.8 because many beam families contain start/end
    cutbacks. The two measured stations define a linear BOS profile; a third
    station at .5 checks that the underside is not locally different.
    """
    a,b = p['a'],p['b']
    z0,z1 = p['bos_start'],p['bos_end']
    set_axis_z(inst,a,b,z0,z1)
    t1,t2=0.20,0.80
    for _ in range(4):
        doc.Regenerate()
        actual=sample_underface(inst,a,b,[t1,t2],z0,z1)
        want=[z0+(z1-z0)*t for t in (t1,t2)]
        e1,e2=want[0]-actual[0],want[1]-actual[1]
        if max(abs(e1),abs(e2)) < BOS_VERIFY_TOL*0.5:
            break
        # Linear transform from interior errors to corrections at endpoints.
        dz0=(e1*t2-e2*t1)/(t2-t1)
        dz1=(e2*(1-t1)-e1*(1-t2))/(t2-t1)
        if abs(dz0)>15 or abs(dz1)>15:
            raise ValueError('Unexpected >15 ft underside correction; invalid family.')
        current=inst.Location.Curve
        z_start=current.GetEndPoint(0).Z
        z_end=current.GetEndPoint(1).Z
        set_axis_z(inst,a,b,z_start+dz0,z_end+dz1)
    doc.Regenerate()
    fractions=[0.20,0.50,0.80]
    samples=sample_underface(inst,a,b,fractions,z0,z1)
    errors=[]
    for t,got in zip(fractions,samples):
        expected=z0+t*(z1-z0)
        errors.append(abs(got-expected))
    if max(errors)>BOS_VERIFY_TOL:
        raise ValueError('Physical BOS verification missed by {:.3f} inches '
                         'at interior sample points.'.format(12.0*max(errors)))
    return samples


def build_all(items):
    passed, errors = [], []
    tx=DB.Transaction(doc, 'STEELTOOLS | Sloped joist support proxies')
    try:
        tx.Start()
        activated=set()
        for p in items:
            sy=p['symbol']
            if sy.Id.IntegerValue not in activated:
                if not sy.IsActive:
                    sy.Activate()
                activated.add(sy.Id.IntegerValue)
        doc.Regenerate()
        for p in items:
            sub=DB.SubTransaction(doc)
            try:
                sub.Start()
                line=DB.Line.CreateBound(DB.XYZ(p['a'].X,p['a'].Y,p['bos_start']),
                                         DB.XYZ(p['b'].X,p['b'].Y,p['bos_end']))
                inst=doc.Create.NewFamilyInstance(line,p['symbol'],p['level'],
                                                  StructuralType.Beam)
                if inst is None:
                    raise ValueError('NewFamilyInstance returned nothing.')
                measurements=align_and_verify(inst,p)
                try:
                    comment=inst.get_Parameter(DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
                    if comment and not comment.IsReadOnly:
                        comment.Set('STEELTOOLS PROXY | STEELTOOLS BOS START={:.6f} | '
                                    'STEELTOOLS BOS END={:.6f} | AREA={} | MEMBER={}'.format(
                                        p['bos_start'],p['bos_end'],p['group'],p['order']))
                except Exception:
                    pass
                new_id=inst.Id
                sub.Commit()
                passed.append(dict(id=new_id,prop=p,measured=measurements))
            except Exception as ex:
                errors.append('{} #{}: {}'.format(p['group'],p['order'],ex))
                try:
                    sub.RollBack()
                except Exception as clean:
                    raise ValueError('Unable to roll back failed member: {}'.format(clean))
        if not passed:
            tx.RollBack()
            return [],errors
        tx.Commit()
        return passed,errors
    except Exception as ex:
        try:
            tx.RollBack()
        except Exception:
            pass
        return [], ['Whole batch rolled back: {}'.format(ex),traceback.format_exc()]


def show_preview(groups, proposals, skipped):
    lines=['STEELTOOLS v0.5.1 | SUPPORT PROXY PREVIEW',
           'NOTHING CREATED YET',
           '{} areas | {} candidate members | {} duplicates skipped'.format(
               len(groups),len(proposals),len(skipped)),'']
    for cfg in groups:
        selected=[x for x in proposals if x['group']==cfg['label']]
        if not selected: continue
        first,last=selected[0],selected[-1]
        lines.append('{} | {} members | {}'.format(cfg['label'],len(selected),symbol_name(cfg['symbol'])))
        lines.append('  FIRST: BOS start {} | BOS end {}'.format(fmt(first['bos_start']),
                                                                 fmt(first['bos_end'])))
        if len(selected)>1:
            lines.append('  LAST: BOS start {} | BOS end {}'.format(fmt(last['bos_start']),
                                                                    fmt(last['bos_end'])))
        if cfg['mode']==0:
            lines.append('  Span array spacing: {:.3f} ft'.format(abs(cfg.get('spacing',0))))
    lines.extend(['','BEFORE GENERATING HANGERS:',
                  '1. Linked NWD and project must be aligned in XY and Z.',
                  '2. Entered BOS/pitch is NOT extracted from the locked NWD.',
                  '3. These are straight sloping proxy members; not tapered/kinked chords.',
                  '4. Plan pick points do NOT guarantee NWD beam centerlines.',
                  '5. The tool physically tests the underside at 20%, 50%, 80%.',
                  '6. Verify start/end in section and attach ONE sample hanger.',
                  '7. Proxies are for coordination, NOT load-bearing design.'])
    return '\n'.join(lines)


def main():
    if view.ViewType not in (DB.ViewType.ThreeD,DB.ViewType.FloorPlan,
                             DB.ViewType.EngineeringPlan,DB.ViewType.CeilingPlan):
        forms.alert('Open an orthographic 3D or plan view.',title='STEELTOOLS')
        return
    try:
        if view.ViewType==DB.ViewType.ThreeD and view.IsPerspective:
            forms.alert('Use orthographic 3D or a plan.',title='STEELTOOLS')
            return
    except Exception:
        pass
    if not forms.alert('SLOPED JOIST GROUPS v0.5.1\n\n'
                       'Select a BOS at START and either BOS at END or roof RISE in/ft. '
                       'For level joists, leave both end and rise blank.\n\n'
                       'A group can rise along joists AND change elevation from '
                       'one parallel joist to the next.\n\n'
                       'WARNING: The protected NWD cannot be sampled by this tool. '
                       'Your entered reference must come from verified drawings '
                       'or field measurements.\n\nStart layout?',
                       title='STEELTOOLS | Sloped Joists',yes=True,no=True):
        return
    initial=0.0
    try: initial=view.Origin.Z
    except Exception: pass
    near=min(range(len(levels)),key=lambda i:abs(level_z(levels[i])-initial))
    prior=dict(sym_idx=0,lev_idx=near,zmode=0,count=8,mode=0)
    groups=[]
    proposals=[]
    while len(groups)<MAX_GROUPS:
        dlg=GroupDialog(prior,len(groups)+1,len(proposals))
        dlg.ShowDialog()
        if not dlg.value:
            break
        cfg=dlg.value
        prior.update(dict(sym_idx=cfg['sym_idx'],lev_idx=cfg['lev_idx'],
                          zmode=cfg['zmode'],count=cfg['count'],mode=cfg['mode']))
        try:
            ensure_pick_plane(cfg['level'])
            picked=pick_group(cfg)
        except OperationCanceledException:
            forms.alert('Cancelled area; nothing added.',title='STEELTOOLS')
            picked=[]
        except Exception as ex:
            forms.alert('Cannot lay out area: {}'.format(ex),title='STEELTOOLS')
            picked=[]
        if not picked:
            if not groups: return
            action=forms.CommandSwitchWindow.show(
                ['Review queued areas','Try next area','Discard'],
                message='No members added in latest area.')
            if action=='Try next area': continue
            if action!='Review queued areas': return
            break
        if len(proposals)+len(picked)>MAX_TOTAL:
            forms.alert('Maximum {} supports per run; review existing queue.'.format(MAX_TOTAL),
                        title='STEELTOOLS')
            break
        groups.append(cfg)
        proposals.extend(picked)
        action=forms.CommandSwitchWindow.show(
            ['Add next area','Preview and create','Discard'],
            message='Queued {} members in {} areas. No framing created.'.format(
                len(proposals),len(groups)))
        if action=='Add next area': continue
        if action!='Preview and create': return
        break
    if not proposals: return
    unique,skipped=deduplicate(proposals)
    if not unique:
        forms.alert('All members appear to duplicate existing framing.',
                    title='STEELTOOLS')
        return
    preview=show_preview(groups,unique,skipped)
    try:
        op=script.get_output()
        op.print_md('### STEELTOOLS | Sloped Joists Preview')
        op.print_code(preview)
    except Exception: pass
    if not forms.alert(preview+'\n\nCREATE THESE STRUCTURAL FRAMING PROXIES?',
                       title='STEELTOOLS | Confirm',yes=True,no=True):
        return
    good,errors=build_all(unique)
    if good:
        try:
            from System.Collections.Generic import List
            selected=List[DB.ElementId]()
            for row in good: selected.Add(row['id'])
            uidoc.Selection.SetElementIds(selected)
        except Exception: pass
    lines=['Created with checked physical underside: {}'.format(len(good)),
           'Unverified / removed / failed: {}'.format(len(errors)),
           'Already present: {}'.format(len(skipped)),'']
    for row in good[:6]:
        p=row['prop']
        lines.append('ID {} | {} #{} | BOS {} -> {}'.format(row['id'].IntegerValue,
                      p['group'],p['order'],fmt(p['bos_start']),fmt(p['bos_end'])))
    if errors:
        lines.extend(['','First errors:']+errors[:8])
    lines.extend(['','Check framing underside at each end against your steel reference, '
                  'then attach ONE real fabrication hanger. '
                  'A passing solid-intersection test is NOT confirmation '
                  'of the NWD elevation or structural suitability.'])
    result='\n'.join(lines)
    forms.alert(result,title='STEELTOOLS | Result')
    try:
        op=script.get_output()
        op.print_md('### STEELTOOLS | Placement Results')
        op.print_code(result)
    except Exception: pass


try:
    main()
except Exception:
    forms.alert('Unexpected error:\n{}'.format(traceback.format_exc()),
                title='STEELTOOLS | Error')
