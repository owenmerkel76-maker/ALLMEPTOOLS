# -*- coding: utf-8 -*-
"""STEELTOOLS | Reconstruct Steel v0.2 BOS edition.

pyRevit / IronPython 2.7 / Revit 2025.
Create native Structural Framing from user-picked XY axes, then measure the
REAL Revit solids and vertically align their lowest physical geometry to the
user's target Bottom Of Steel (BOS). No access to protected NWD geometry.
"""
from __future__ import division

import math
import traceback

from pyrevit import DB, forms, script
from Autodesk.Revit.DB.Structure import StructuralType
from Autodesk.Revit.UI.Selection import ObjectType
from Autodesk.Revit.Exceptions import OperationCanceledException

__title__ = 'Reconstruct\nSteel'
__doc__ = 'Create native Structural Framing aligned to a verified Bottom of Steel elevation.'

uidoc = __revit__.ActiveUIDocument
if uidoc is None:
    forms.alert('Open a project before running STEELTOOLS.', title='STEELTOOLS')
    script.exit()
doc = uidoc.Document
view = uidoc.ActiveView
if doc.IsFamilyDocument:
    forms.alert('Run this in a project, not the family editor.', title='STEELTOOLS')
    script.exit()

# Tolerances: all Revit API length values are feet.
DUPLICATE_TOL = 1.0 / 96.0             # 1/8 in for endpoint matching
BOS_TOL = 1.0 / 384.0                 # 1/32 in max allowable underside error
MIN_LENGTH = 0.2                      # 2.4 in
MAX_ARRAY = 200
MAX_TRACE = 250


def elem_name(el):
    """Avoid the IronPython FamilySymbol.Name AttributeError reported in v0.1."""
    if el is None:
        return '<none>'
    for bip in (DB.BuiltInParameter.SYMBOL_NAME_PARAM,
                DB.BuiltInParameter.DATUM_TEXT):
        try:
            p = el.get_Parameter(bip)
            if p and p.HasValue:
                val = p.AsString() or p.AsValueString()
                if val:
                    return val
        except Exception:
            pass
    try:
        name = DB.Element.Name.GetValue(el)
        if name:
            return str(name)
    except Exception:
        pass
    try:
        return str(el.Name)
    except Exception:
        return 'Element #{}'.format(el.Id.IntegerValue)


def symbol_label(sym):
    family = None
    try:
        family = sym.FamilyName
    except Exception:
        pass
    if not family:
        try:
            family = elem_name(sym.Family)
        except Exception:
            family = 'Framing'
    return '{} / {} [ID {}]'.format(family, elem_name(sym), sym.Id.IntegerValue)


def lvl_z(level):
    # NOT Level.Elevation: the latter can reflect a shared/survey elevation base.
    return level.ProjectElevation


def level_label(level):
    return '{} [project Z: {:+.3f} ft]'.format(elem_name(level), lvl_z(level))


def ft_from_text(value):
    """Parse decimal feet, 12'-6.5\", -0'-3\", or 90\".  No units = feet."""
    s = str(value).strip().replace(u'\u2032', "'").replace(u'\u2033', '"')
    s = s.replace(' ', '').replace(',', '')
    if not s:
        raise ValueError('Enter a Bottom of Steel elevation.')
    neg = s.startswith('-')
    if s[0:1] in ('-', '+'):
        s = s[1:]
    if "'" in s:
        parts = s.split("'")
        if len(parts) != 2 or not parts[0]:
            raise ValueError('Use feet-inches, e.g. 12\'-6\".')
        feet = float(parts[0])
        inchstr = parts[1].replace('"', '')
        if inchstr.startswith('-'):
            inchstr = inchstr[1:]  # standard feet-inches separator
        inches = float(inchstr) if inchstr else 0.0
        if not (0 <= inches < 12):
            raise ValueError('Inches must be in the range 0–11.999.')
        val = feet + inches / 12.0
    elif '"' in s:
        val = float(s.replace('"', '')) / 12.0
    else:
        val = float(s)
    if math.isnan(val) or math.isinf(val):
        raise ValueError('Bottom of Steel must be finite.')
    return -val if neg else val


def fmt_z(z):
    return '{:+.4f} ft'.format(z)


def dist(a, b):
    return a.DistanceTo(b)


def with_z(p, z):
    return DB.XYZ(p.X, p.Y, z)


def same_endpoints(p1, p2, q1, q2):
    return ((dist(p1, q1) <= DUPLICATE_TOL and dist(p2, q2) <= DUPLICATE_TOL) or
            (dist(p1, q2) <= DUPLICATE_TOL and dist(p2, q1) <= DUPLICATE_TOL))


def existing_axes():
    out = []
    for el in DB.FilteredElementCollector(doc).OfCategory(
            DB.BuiltInCategory.OST_StructuralFraming).WhereElementIsNotElementType():
        try:
            loc = el.Location
            if isinstance(loc, DB.LocationCurve):
                out.append((loc.Curve.GetEndPoint(0), loc.Curve.GetEndPoint(1)))
        except Exception:
            pass
    return out


def new_xy_axis(point1, point2, levelz):
    # Beam line is a provisional Z only. Real BOS is measured and aligned later.
    a = with_z(point1, levelz)
    b = with_z(point2, levelz)
    if dist(a, b) < MIN_LENGTH:
        raise ValueError('Beam endpoints are too close together.')
    return a, b


def target_from_text(text, state):
    elevation = ft_from_text(text)
    return lvl_z(state['level']) + elevation if state['z_mode'] == 0 else elevation


symbols = sorted(
    list(DB.FilteredElementCollector(doc).OfClass(DB.FamilySymbol)
         .OfCategory(DB.BuiltInCategory.OST_StructuralFraming)),
    key=lambda el: symbol_label(el).lower())
levels = sorted(list(DB.FilteredElementCollector(doc).OfClass(DB.Level)),
                key=lambda el: lvl_z(el))
if not symbols:
    forms.alert('No Structural Framing family types were found.\n'
                'Load a suitable structural beam family (Insert > Load Family).',
                title='STEELTOOLS')
    script.exit()
if not levels:
    forms.alert('No levels found in this model.', title='STEELTOOLS')
    script.exit()


class SetupDialog(forms.WPFWindow):
    def __init__(self):
        forms.WPFWindow.__init__(self, script.get_bundle_file('ui.xaml'))
        self.settings = None
        self.symbol_lookup = {}
        self.level_lookup = {}
        for beam in symbols:
            label = symbol_label(beam)
            self.symbol_lookup[label] = beam
            self.beam_combo.Items.Add(label)
        for level in levels:
            label = level_label(level)
            self.level_lookup[label] = level
            self.level_combo.Items.Add(label)
        self.mode_combo.Items.Add('Rapid Trace | multiple beams')
        self.mode_combo.Items.Add('Parallel Array | repeated joists')
        self.point_combo.Items.Add('XY / active work plane (recommended)')
        self.point_combo.Items.Add('3D object point (experimental with NWD)')
        self.z_combo.Items.Add('BOS offset ABOVE selected Revit level')
        self.z_combo.Items.Add('Absolute project BOS elevation')
        self.mode_combo.SelectedIndex = 0
        self.point_combo.SelectedIndex = 0
        self.z_combo.SelectedIndex = 0
        self.beam_combo.SelectedIndex = 0
        try:
            active_z = view.Origin.Z
        except Exception:
            active_z = 0.0
        chosen = min(levels, key=lambda l: abs(lvl_z(l) - active_z))
        for i in range(self.level_combo.Items.Count):
            if self.level_lookup[str(self.level_combo.Items[i])].Id == chosen.Id:
                self.level_combo.SelectedIndex = i
                break
        self.bos_text.Text = '12\'-0"'
        self.count_text.Text = '10'
        self.mode_combo.SelectionChanged += self.mode_changed
        self.run_button.Click += self.run_clicked
        self.cancel_button.Click += self.cancel_clicked
        self.mode_changed(None, None)

    def mode_changed(self, sender, args):
        arr = (self.mode_combo.SelectedIndex == 1)
        self.count_text.IsEnabled = arr
        self.per_beam_check.IsEnabled = not arr
        if arr:
            self.per_beam_check.IsChecked = False

    def cancel_clicked(self, sender, args):
        self.DialogResult = False
        self.Close()

    def run_clicked(self, sender, args):
        try:
            beam = self.symbol_lookup[str(self.beam_combo.SelectedItem)]
            level = self.level_lookup[str(self.level_combo.SelectedItem)]
            state = dict(symbol=beam, level=level,
                         mode=self.mode_combo.SelectedIndex,
                         use_3d=self.point_combo.SelectedIndex == 1,
                         z_mode=self.z_combo.SelectedIndex,
                         bos_text=str(self.bos_text.Text).strip(),
                         per_beam=bool(self.per_beam_check.IsChecked))
            state['target_bos'] = target_from_text(state['bos_text'], state)
            count = int(str(self.count_text.Text).strip()) if state['mode'] == 1 else 1
            if count < 1 or count > MAX_ARRAY:
                raise ValueError('Array count must be between 1 and 200.')
            state['count'] = count
            self.settings = state
            self.DialogResult = True
            self.Close()
        except Exception as ex:
            forms.alert(str(ex), title='STEELTOOLS | Check Settings')


def pick_point(prompt, state):
    if state['use_3d']:
        ref = uidoc.Selection.PickObject(ObjectType.PointOnElement, prompt)
        if ref is None or ref.GlobalPoint is None:
            raise ValueError('No valid 3D object point returned by Revit. '
                             'Use XY mode in a plan view instead.')
        return ref.GlobalPoint
    return uidoc.Selection.PickPoint(prompt)


def prepare_workplane(state):
    if state['use_3d'] or view.ViewType != DB.ViewType.ThreeD:
        return True
    if not forms.alert(
            '3D PickPoint requires a horizontal work plane. Set it at the chosen '
            'BOS elevation {}?\n\nYour clicks will be projected to that plane. '
            'This DOES NOT sample the NWD beam bottom. Use actual Navisworks '
            'elevation or a verified section dimension.'.format(fmt_z(state['target_bos'])),
            title='STEELTOOLS | 3D Work Plane', yes=True, no=True):
        return False
    trans = DB.Transaction(doc, 'STEELTOOLS | Set 3D pick work plane')
    try:
        trans.Start()
        plane = DB.Plane.CreateByNormalAndOrigin(DB.XYZ.BasisZ,
                                                 DB.XYZ(0, 0, state['target_bos']))
        view.SketchPlane = DB.SketchPlane.Create(doc, plane)
        trans.Commit()
        return True
    except Exception:
        try:
            trans.RollBack()
        except Exception:
            pass
        raise ValueError('Could not create the 3D work plane. '
                         'Try this tool in a floor plan with the NWD visible.')


def get_trace(state):
    forms.alert('RAPID TRACE\n\nChoose XY endpoints along the axis of each '
                'steel beam. Continue picking START and END for additional beams.\n\n'
                'ESC at the next START finishes. An incomplete pair is discarded.\n'
                '{}'.format('You will enter BOS for each completed member.'
                            if state['per_beam'] else
                            'All members use BOS {}.'.format(fmt_z(state['target_bos']))),
                title='STEELTOOLS | Rapid Trace')
    proposed = []
    while len(proposed) < MAX_TRACE:
        try:
            p1 = pick_point('Beam {} START | ESC to finish'.format(len(proposed) + 1), state)
        except OperationCanceledException:
            break
        try:
            p2 = pick_point('Beam {} END'.format(len(proposed) + 1), state)
        except OperationCanceledException:
            break
        try:
            a, b = new_xy_axis(p1, p2, lvl_z(state['level']))
        except Exception as ex:
            forms.alert(str(ex), title='STEELTOOLS')
            continue
        bos = state['target_bos']
        if state['per_beam']:
            input_str = forms.ask_for_string(default=state['bos_text'],
                       prompt='Beam {} BOS ({}). Enter feet/inches:'.format(
                           len(proposed) + 1, 'level offset' if state['z_mode'] == 0 else 'project Z'),
                       title='STEELTOOLS | Beam BOS')
            if input_str is None:
                break
            try:
                bos = target_from_text(input_str, state)
                state['bos_text'] = input_str
            except Exception as ex:
                forms.alert('Invalid BOS; beam was skipped: {}'.format(ex),
                            title='STEELTOOLS')
                continue
        proposed.append((a, b, bos))
    return proposed, None


def get_array(state):
    forms.alert('PARALLEL ARRAY\n\nPick: (1) first beam START, (2) first '
                'beam END, (3) NEXT parallel beam START. The offset between '
                'beams determines spacing.\n\nAll beams use BOS {}. '
                'Only use for members with equal span/spacing and BOS.'.format(
                    fmt_z(state['target_bos'])), title='STEELTOOLS | Array')
    p1 = pick_point('First beam START', state)
    p2 = pick_point('First beam END', state)
    p3 = pick_point('Second beam START (spacing)', state)
    a, b = new_xy_axis(p1, p2, lvl_z(state['level']))
    dx, dy = b.X - a.X, b.Y - a.Y
    span = math.sqrt(dx * dx + dy * dy)
    nx, ny = -dy / span, dx / span
    step = (p3.X - a.X) * nx + (p3.Y - a.Y) * ny
    if abs(step) < 0.1:
        raise ValueError('Spacing below 1.2 in. Pick a point on the next beam axis.')
    proposed = []
    for index in range(state['count']):
        x = nx * step * index
        y = ny * step * index
        proposed.append((DB.XYZ(a.X+x, a.Y+y, a.Z),
                         DB.XYZ(b.X+x, b.Y+y, b.Z), state['target_bos']))
    return proposed, abs(step)


def distinct_proposals(proposed):
    existing = existing_axes()
    unique, skipped = [], 0
    for a, b, target in proposed:
        if any(same_endpoints(a, b, p, q) for p, q in existing) or \
           any(same_endpoints(a, b, p, q) for p, q, z in unique):
            skipped += 1
        else:
            unique.append((a, b, target))
    return unique, skipped


def solid_min_z(solid):
    """Take minimum true model-Z from a physical solid's transformed bounds."""
    bound = solid.GetBoundingBox()
    trans = bound.Transform
    minimum = None
    for x in (bound.Min.X, bound.Max.X):
        for y in (bound.Min.Y, bound.Max.Y):
            for z in (bound.Min.Z, bound.Max.Z):
                p = trans.OfPoint(DB.XYZ(x, y, z))
                if minimum is None or p.Z < minimum:
                    minimum = p.Z
    return minimum


def gather_solid_mins(geo, output, depth=0):
    if geo is None or depth > 6:
        return
    for obj in geo:
        if isinstance(obj, DB.Solid):
            try:
                if obj.Volume > 1e-7 and obj.Faces.Size > 0:
                    output.append(solid_min_z(obj))
            except Exception:
                pass
        elif isinstance(obj, DB.GeometryInstance):
            try:
                # GetInstanceGeometry is already transformed to model coordinates.
                gather_solid_mins(obj.GetInstanceGeometry(), output, depth + 1)
            except Exception:
                pass


def real_bos(instance):
    """Measure from solids, NOT a symbolic-line/geometry-inflated element box."""
    opts = DB.Options()
    opts.DetailLevel = DB.ViewDetailLevel.Fine
    opts.IncludeNonVisibleObjects = False
    zs = []
    gather_solid_mins(instance.get_Geometry(opts), zs)
    if not zs:
        raise ValueError('No measurable solid in this family type. '
                         'Choose a physical beam/joist family.')
    return min(zs)


def write_metadata(instance, target):
    try:
        p = instance.get_Parameter(DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        if p and not p.IsReadOnly:
            p.Set('STEELTOOLS proxy | verified BOS {:.4f} project ft'.format(target))
    except Exception:
        pass


def build(state, candidates):
    """Three batched regenerations: create, align, remeasure.

    Delete any framing that cannot be geometrically verified. No unverified
    physical support is left behind.
    """
    created, bad = [], []
    trans = DB.Transaction(doc, 'STEELTOOLS | Create and verify BOS framing')
    try:
        trans.Start()
        symbol = state['symbol']
        if not symbol.IsActive:
            symbol.Activate()
            doc.Regenerate()
        # Placement lines use reference-level Z. Actual BOS is fixed afterward.
        for i, (a, b, target) in enumerate(candidates):
            try:
                line = DB.Line.CreateBound(a, b)
                inst = doc.Create.NewFamilyInstance(line, symbol, state['level'],
                                                    StructuralType.Beam)
                if inst is None:
                    raise ValueError('Revit returned a null beam instance.')
                created.append(dict(index=i+1, id=inst.Id, target=target))
            except Exception as ex:
                bad.append('Beam {}: unable to create: {}'.format(i+1, ex))
        if not created:
            trans.RollBack()
            return [], bad
        doc.Regenerate()
        for item in created:
            try:
                instance = doc.GetElement(item['id'])
                z_initial = real_bos(instance)
                shift = item['target'] - z_initial
                if abs(shift) > 0.000001:
                    DB.ElementTransformUtils.MoveElement(doc, item['id'],
                                                         DB.XYZ(0, 0, shift))
            except Exception as ex:
                item['error'] = 'alignment failed: {}'.format(ex)
        doc.Regenerate()
        accepted = []
        for item in created:
            if 'error' not in item:
                try:
                    actual = real_bos(doc.GetElement(item['id']))
                    delta = actual - item['target']
                    if abs(delta) > BOS_TOL:
                        raise ValueError('verification error {:.3f} in'.format(delta*12.0))
                    item['actual'] = actual
                    write_metadata(doc.GetElement(item['id']), item['target'])
                    accepted.append(item)
                except Exception as ex:
                    item['error'] = str(ex)
            if 'error' in item:
                bad.append('Beam {}: {}'.format(item['index'], item['error']))
                # Safety: remove inaccurate/unsupported beam rather than leaving
                # misleading hanger attachment geometry in the model.
                doc.Delete(item['id'])
        if not accepted:
            trans.RollBack()
            return [], bad
        trans.Commit()
        return accepted, bad
    except Exception as ex:
        try:
            trans.RollBack()
        except Exception:
            pass
        return [], ['Transaction rolled back: {}'.format(ex), traceback.format_exc()]


def main():
    dlg = SetupDialog()
    dlg.ShowDialog()
    if not dlg.settings:
        return
    state = dlg.settings
    if state['use_3d'] and view.ViewType != DB.ViewType.ThreeD:
        forms.alert('3D object-point mode needs a 3D view.', title='STEELTOOLS')
        return
    try:
        if prepare_workplane(state) is False:
            return
        proposed, spacing = (get_array(state) if state['mode'] == 1 else
                             get_trace(state))
    except OperationCanceledException:
        forms.alert('Cancelled. No framing created.', title='STEELTOOLS')
        return
    except Exception as ex:
        forms.alert('Cannot pick these NWD reference points: {}\n\n'
                    'Try XY picking from a floor plan. NWD snaps are limited.'.format(ex),
                    title='STEELTOOLS')
        return
    if not proposed:
        forms.alert('No complete beam picks. Nothing created.', title='STEELTOOLS')
        return
    candidates, skipped = distinct_proposals(proposed)
    if not candidates:
        forms.alert('All proposed beams match existing structural axes.',
                    title='STEELTOOLS')
        return
    unique_bos = sorted(set(round(item[2], 4) for item in candidates))
    target_desc = (fmt_z(unique_bos[0]) if len(unique_bos) == 1 else
                   '{} different elevations'.format(len(unique_bos)))
    msg = ('Create {} native Structural Framing proxies?\n\n'
           'Type: {}\nReference level: {}\n'
           'Target underside (BOS): {}\n'
           'Duplicate axes skipped: {}\n').format(
               len(candidates), symbol_label(state['symbol']),
               elem_name(state['level']), target_desc, skipped)
    if state['mode'] == 1:
        msg += 'Array spacing: {:.3f} ft\n'.format(spacing)
    msg += ('\nActual solid geometry will be measured and moved to BOS. '
            'Any beam that fails 1/32-inch BOS verification will be removed.\n\n'
            'IMPORTANT: BOS is USER-SUPPLIED; the tool cannot read it directly '
            'from the locked NWD. Confirm NWD coordinate alignment and beam '
            'XY positions before using hangers.')
    if not forms.alert(msg + '\n\nCreate now?', title='STEELTOOLS | Verify Inputs',
                       yes=True, no=True):
        return
    accepted, bad = build(state, candidates)
    if accepted:
        try:
            from System.Collections.Generic import List
            ids = List[DB.ElementId]()
            for item in accepted:
                ids.Add(item['id'])
            uidoc.Selection.SetElementIds(ids)
        except Exception:
            pass
    lines = ['Created and BOS-verified: {}'.format(len(accepted)),
             'Duplicate axes skipped: {}'.format(skipped),
             'Creation / BOS failures: {}'.format(len(bad))]
    if accepted:
        lines.extend(['', 'Sample verified framing (project coordinates):'])
        for item in accepted[:8]:
            lines.append('ID {} | target {} | actual {} | error {:.4f} in'.format(
                item['id'].IntegerValue, fmt_z(item['target']),
                fmt_z(item['actual']), (item['actual']-item['target'])*12.0))
    if bad:
        lines.extend(['', 'Failed items (deleted or rolled back):'])
        lines.extend(bad[:10])
    lines.extend(['', 'NEXT: Inspect a beam in section; confirm its underside '
                  'against NWD. Place ONE fabrication hanger and check both '
                  'rod attachments before continuing.'])
    forms.alert('\n'.join(lines), title='STEELTOOLS v0.2 | BOS Verification')
    try:
        out = script.get_output()
        out.print_md('### STEELTOOLS BOS reconstruction report')
        for ln in lines:
            out.print_md(ln.replace('|', '\\|'))
    except Exception:
        pass


main()
