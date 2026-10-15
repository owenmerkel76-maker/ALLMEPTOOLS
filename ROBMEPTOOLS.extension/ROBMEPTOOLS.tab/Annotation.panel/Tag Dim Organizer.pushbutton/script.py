# -*- coding: utf-8 -*-
"""ROBMEPTOOLS Tag + Dim Organizer v0.4 Human Compact Dimensions Beta.

Post-process visible IndependentTag and Dimension elements in the active view.
Moves annotation only. Fabrication MEP is obstacle geometry and is never moved.
"""
import clr
import math
import os
import traceback

clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')

from pyrevit import revit, DB, forms, script
from System.Collections.Generic import List

BUNDLE_DIR = os.path.dirname(__file__)
doc = revit.doc
uidoc = revit.uidoc
view = doc.ActiveView
output = script.get_output()


def eid_int(eid):
    try:
        return int(eid.Value)
    except Exception:
        try:
            return int(eid.IntegerValue)
        except Exception:
            return -1


def bic_int(bic):
    try:
        return eid_int(DB.ElementId(bic))
    except Exception:
        try:
            return int(bic)
        except Exception:
            return -999999


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def dot2(a, b):
    return a[0] * b[0] + a[1] * b[1]


def length2(v):
    return math.sqrt(v[0] * v[0] + v[1] * v[1])


def norm2(v):
    d = length2(v)
    if d < 1e-12:
        return None
    return (v[0] / d, v[1] / d)


def add2(a, b):
    return (a[0] + b[0], a[1] + b[1])


def sub2(a, b):
    return (a[0] - b[0], a[1] - b[1])


def mul2(v, s):
    return (v[0] * s, v[1] * s)


def dist2(a, b):
    return length2(sub2(a, b))


def rect_intersects(a, b):
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def rect_expand(r, d):
    return (r[0] - d, r[1] - d, r[2] + d, r[3] + d)


def rect_translate(r, du, dv):
    return (r[0] + du, r[1] + dv, r[2] + du, r[3] + dv)


def rect_union(rects):
    vals = [r for r in rects if r is not None]
    if not vals:
        return None
    return (min(r[0] for r in vals), min(r[1] for r in vals),
            max(r[2] for r in vals), max(r[3] for r in vals))


def orient(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def on_segment(a, b, p):
    eps = 1e-9
    return (min(a[0], b[0]) - eps <= p[0] <= max(a[0], b[0]) + eps and
            min(a[1], b[1]) - eps <= p[1] <= max(a[1], b[1]) + eps)


def seg_intersects(a, b, c, d):
    o1 = orient(a, b, c)
    o2 = orient(a, b, d)
    o3 = orient(c, d, a)
    o4 = orient(c, d, b)
    eps = 1e-10
    if ((o1 > eps and o2 < -eps) or (o1 < -eps and o2 > eps)) and ((o3 > eps and o4 < -eps) or (o3 < -eps and o4 > eps)):
        return True
    if abs(o1) <= eps and on_segment(a, b, c):
        return True
    if abs(o2) <= eps and on_segment(a, b, d):
        return True
    if abs(o3) <= eps and on_segment(c, d, a):
        return True
    if abs(o4) <= eps and on_segment(c, d, b):
        return True
    return False


def point_seg_dist(p, a, b):
    ab = sub2(b, a)
    den = dot2(ab, ab)
    if den < 1e-12:
        return dist2(p, a)
    t = clamp(dot2(sub2(p, a), ab) / den, 0.0, 1.0)
    q = add2(a, mul2(ab, t))
    return dist2(p, q)


def seg_distance(a, b, c, d):
    if seg_intersects(a, b, c, d):
        return 0.0
    return min(point_seg_dist(a, c, d), point_seg_dist(b, c, d),
               point_seg_dist(c, a, b), point_seg_dist(d, a, b))


def seg_intersects_rect(a, b, r):
    if r[0] <= a[0] <= r[2] and r[1] <= a[1] <= r[3]:
        return True
    if r[0] <= b[0] <= r[2] and r[1] <= b[1] <= r[3]:
        return True
    p0 = (r[0], r[1]); p1 = (r[2], r[1]); p2 = (r[2], r[3]); p3 = (r[0], r[3])
    return (seg_intersects(a, b, p0, p1) or seg_intersects(a, b, p1, p2) or
            seg_intersects(a, b, p2, p3) or seg_intersects(a, b, p3, p0))


class OrganizerWindow(forms.WPFWindow):
    resolve_theme = True

    def __init__(self):
        forms.WPFWindow.__init__(self, os.path.join(BUNDLE_DIR, 'organizer.xaml'))
        self.run_requested = False
        self.settings = None
        try:
            from System import Uri, UriKind
            from System.Windows.Media.Imaging import BitmapImage
            ip = os.path.join(BUNDLE_DIR, 'icon.png')
            if os.path.isfile(ip):
                self.Icon = BitmapImage(Uri(ip, UriKind.Absolute))
        except Exception:
            pass
        self._load()
        self._wire()
        self._refresh()

    def _wire(self):
        for c in (self.ModeConservative, self.ModeBalanced, self.ModeClean, self.ScopeView, self.ScopeSelection):
            try:
                c.Checked += self._changed
            except Exception:
                pass
        for c in (self.DoTags, self.DoDims, self.CleanShoulders, self.SecondPass,
                  self.MultiLeader, self.BankDims, self.CompactDims, self.ResetDimText,
                  self.AvoidDuct, self.AvoidPipe, self.AvoidDwg, self.Detailed):
            try:
                c.Checked += self._changed
                c.Unchecked += self._changed
            except Exception:
                pass
        self.RunButton.Click += self._run
        self.CancelButton.Click += self._cancel

    def _load(self):
        try:
            cfg = script.get_config()
            mode = str(getattr(cfg, 'mode', 'balanced'))
            scope = str(getattr(cfg, 'scope', 'view'))
            if mode == 'conservative': self.ModeConservative.IsChecked = True
            elif mode == 'clean': self.ModeClean.IsChecked = True
            else: self.ModeBalanced.IsChecked = True
            self.ScopeSelection.IsChecked = (scope == 'selection')
            self.ScopeView.IsChecked = not bool(self.ScopeSelection.IsChecked)
            for name, default in (
                ('do_tags', True), ('do_dims', True), ('clean_shoulders', True), ('second_pass', True),
                ('multi_leader', True), ('bank_dims', True), ('compact_dims', True), ('reset_dim_text', True),
                ('avoid_duct', True), ('avoid_pipe', True), ('avoid_dwg', True), ('detailed', False)):
                ctrl = {
                    'do_tags': self.DoTags, 'do_dims': self.DoDims, 'clean_shoulders': self.CleanShoulders,
                    'second_pass': self.SecondPass, 'multi_leader': self.MultiLeader, 'bank_dims': self.BankDims,
                    'compact_dims': self.CompactDims, 'reset_dim_text': self.ResetDimText,
                    'avoid_duct': self.AvoidDuct, 'avoid_pipe': self.AvoidPipe,
                    'avoid_dwg': self.AvoidDwg, 'detailed': self.Detailed
                }[name]
                ctrl.IsChecked = bool(getattr(cfg, name, default))
        except Exception:
            pass

    def _read(self):
        if bool(self.ModeConservative.IsChecked): mode = 'conservative'
        elif bool(self.ModeClean.IsChecked): mode = 'clean'
        else: mode = 'balanced'
        scope = 'selection' if bool(self.ScopeSelection.IsChecked) else 'view'
        return {
            'mode': mode, 'scope': scope,
            'do_tags': bool(self.DoTags.IsChecked), 'do_dims': bool(self.DoDims.IsChecked),
            'clean_shoulders': bool(self.CleanShoulders.IsChecked), 'second_pass': bool(self.SecondPass.IsChecked),
            'multi_leader': bool(self.MultiLeader.IsChecked), 'bank_dims': bool(self.BankDims.IsChecked),
            'compact_dims': bool(self.CompactDims.IsChecked), 'reset_dim_text': bool(self.ResetDimText.IsChecked),
            'avoid_duct': bool(self.AvoidDuct.IsChecked), 'avoid_pipe': bool(self.AvoidPipe.IsChecked),
            'avoid_dwg': bool(self.AvoidDwg.IsChecked), 'detailed': bool(self.Detailed.IsChecked)
        }

    def _save(self, s):
        try:
            cfg = script.get_config()
            for k, v in s.items(): setattr(cfg, k, v)
            script.save_config()
        except Exception:
            pass

    def _refresh(self):
        try:
            s = self._read()
            self.ModeBadge.Text = '{0} • {1}'.format(s['mode'].upper(), 'SELECTED' if s['scope'] == 'selection' else 'ACTIVE VIEW')
            if s['mode'] == 'conservative':
                self.HelpText.Text = 'Conservative: resets dragged dimension text, then makes small whole-dimension moves toward the referenced MEP.'
            elif s['mode'] == 'clean':
                self.HelpText.Text = 'Clean: aggressively compacts witness-line stations around referenced MEP, banks parallel dimensions, and keeps text on the dimension line.'
            else:
                self.HelpText.Text = 'Balanced: resets long dimension-text leaders, pulls whole dimensions back toward their referenced MEP, then banks dimensions and cleans tag heads.'
            self.FooterHelp.Text = 'Selected Annotation moves only selected tags/dims.' if s['scope'] == 'selection' else 'Active View scans visible annotation, Fabrication MEP, and the local DWG work zone.'
        except Exception:
            pass

    def _changed(self, sender, args):
        self._refresh()

    def _run(self, sender, args):
        self.settings = self._read()
        self._save(self.settings)
        self.run_requested = True
        self.Close()

    def _cancel(self, sender, args):
        self.run_requested = False
        self.Close()


class StaticIndex(object):
    def __init__(self, cell):
        self.cell = max(float(cell), 0.01)
        self.rects = []
        self.rect_cells = {}
        self.cad_segments = []
        self.cad_cells = {}

    def _cell(self, p):
        return (int(math.floor(p[0] / self.cell)), int(math.floor(p[1] / self.cell)))

    def _rect_keys(self, r):
        a = self._cell((r[0], r[1])); b = self._cell((r[2], r[3]))
        for i in range(a[0], b[0] + 1):
            for j in range(a[1], b[1] + 1):
                yield (i, j)

    def add_rect(self, r, source_id, kind):
        idx = len(self.rects)
        self.rects.append((r, int(source_id), kind))
        for k in self._rect_keys(r):
            self.rect_cells.setdefault(k, []).append(idx)

    def add_cad(self, a, b, weight, source_id):
        idx = len(self.cad_segments)
        self.cad_segments.append((a, b, float(weight), int(source_id)))
        box = (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))
        keys = list(self._rect_keys(box))
        if len(keys) <= 120:
            for k in keys: self.cad_cells.setdefault(k, []).append(idx)
        else:
            length = max(dist2(a, b), self.cell)
            steps = int(math.ceil(length / (self.cell * 0.45)))
            seen = set()
            for n in range(steps + 1):
                t = float(n) / float(max(steps, 1))
                p = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
                ck = self._cell(p)
                for di in (-1, 0, 1):
                    for dj in (-1, 0, 1):
                        key = (ck[0] + di, ck[1] + dj)
                        if key not in seen:
                            seen.add(key); self.cad_cells.setdefault(key, []).append(idx)

    def rect_hits(self, r, ignore_ids=None):
        ignore_ids = ignore_ids or set()
        found = set(); out = []
        for k in self._rect_keys(r):
            for idx in self.rect_cells.get(k, []):
                if idx in found: continue
                found.add(idx)
                item = self.rects[idx]
                if item[1] in ignore_ids: continue
                if rect_intersects(r, item[0]): out.append(item)
        return out

    def cad_score_rect(self, r):
        found = set(); score = 0.0; count = 0
        for k in self._rect_keys(r):
            for idx in self.cad_cells.get(k, []):
                if idx in found: continue
                found.add(idx)
                a, b, w, sid = self.cad_segments[idx]
                if seg_intersects_rect(a, b, r):
                    score += w; count += 1
        return score, count

    def line_rect_hits(self, a, b, pad, ignore_ids=None):
        box = rect_expand((min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])), pad)
        ignore_ids = ignore_ids or set(); found = set(); out = []
        for k in self._rect_keys(box):
            for idx in self.rect_cells.get(k, []):
                if idx in found: continue
                found.add(idx)
                r, sid, kind = self.rects[idx]
                if sid in ignore_ids: continue
                if seg_intersects_rect(a, b, rect_expand(r, pad)): out.append((r, sid, kind))
        return out

    def cad_score_line(self, a, b, pad):
        box = rect_expand((min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])), pad)
        found = set(); score = 0.0; count = 0
        for k in self._rect_keys(box):
            for idx in self.cad_cells.get(k, []):
                if idx in found: continue
                found.add(idx)
                c, d, w, sid = self.cad_segments[idx]
                if seg_distance(a, b, c, d) <= pad:
                    score += w * 0.20; count += 1
        return score, count


class OrganizerEngine(object):
    def __init__(self, settings):
        self.settings = settings
        self.scale = float(max(1, int(view.Scale)))
        self.right = view.RightDirection
        self.up = view.UpDirection
        self.normal = view.ViewDirection
        self.cfg = self._mode_cfg(settings['mode'])
        self.static = StaticIndex(self.paper(0.65))
        self.states = []
        self.state_by_id = {}
        self.selected = set(eid_int(x) for x in uidoc.Selection.GetElementIds())
        self._moved_tags = set()
        self._moved_dims = set()
        self.stats = {
            'tags_total': 0, 'dims_total': 0, 'tags_movable': 0, 'dims_movable': 0, 'tags_moved': 0, 'dims_moved': 0,
            'dim_text_moved': 0, 'leaders_cleaned': 0, 'pinned_skipped': 0,
            'fab_duct': 0, 'fab_pipe': 0, 'dwgs': 0, 'dwg_segments': 0, 'dwg_failed': 0,
            'dwg_capped': False, 'passes': 0, 'failures': 0,
            'multileader_groups': 0, 'multileader_hosts_added': 0,
            'multileader_tags_removed': 0, 'multileader_unsupported': 0,
            'dim_bank_snaps': 0, 'compact_dim_moves': 0, 'dim_text_resets': 0,
            'long_dim_stations_before': 0, 'long_dim_stations_after': 0,
            'dim_leaders_before': 0, 'dim_leaders_after': 0
        }
        self._unsupported_multileader_types = set()

    def _mode_cfg(self, mode):
        if mode == 'conservative':
            return {'tag_steps': [0.0, .10, .18, .27, .35], 'dim_steps': [0.0, .10, .18, .26],
                    'text_steps': [0.0, .08, .15, .24, .30], 'tag_pen': 520.0, 'dim_pen': 600.0,
                    'text_pen': 420.0, 'passes': 1, 'gain': 180.0, 'shoulder': .18}
        if mode == 'clean':
            return {'tag_steps': [0.0, .10, .18, .28, .42, .58, .76, .96, 1.15],
                    'dim_steps': [0.0, .10, .18, .28, .42, .60, .80],
                    'text_steps': [0.0, .08, .15, .24, .34, .48, .62], 'tag_pen': 210.0, 'dim_pen': 270.0,
                    'text_pen': 180.0, 'passes': 2, 'gain': 45.0, 'shoulder': .20}
        return {'tag_steps': [0.0, .10, .18, .28, .42, .58, .72],
                'dim_steps': [0.0, .10, .18, .28, .40, .55],
                'text_steps': [0.0, .08, .15, .24, .34, .45], 'tag_pen': 340.0, 'dim_pen': 390.0,
                'text_pen': 270.0, 'passes': 2, 'gain': 85.0, 'shoulder': .18}

    def paper(self, inches):
        return float(inches) * self.scale / 12.0

    def uv(self, p):
        return (p.DotProduct(self.right), p.DotProduct(self.up))

    def move_xyz(self, p, du, dv):
        return DB.XYZ(p.X + self.right.X * du + self.up.X * dv,
                      p.Y + self.right.Y * du + self.up.Y * dv,
                      p.Z + self.right.Z * du + self.up.Z * dv)

    def element_rect(self, elem):
        try:
            bb = elem.get_BoundingBox(view)
            if bb is None: return None
            tr = bb.Transform
            pts = []
            for x in (bb.Min.X, bb.Max.X):
                for y in (bb.Min.Y, bb.Max.Y):
                    for z in (bb.Min.Z, bb.Max.Z):
                        p = tr.OfPoint(DB.XYZ(x, y, z)) if tr is not None else DB.XYZ(x, y, z)
                        pts.append(self.uv(p))
            return (min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts))
        except Exception:
            return None

    def center_of_element(self, elem):
        r = self.element_rect(elem)
        if r is None: return None
        return ((r[0] + r[2]) * 0.5, (r[1] + r[3]) * 0.5)

    def _is_mep_dimension_host(self, elem):
        if elem is None:
            return False
        try:
            cid = eid_int(elem.Category.Id) if elem.Category is not None else -1
        except Exception:
            cid = -1
        allowed = set()
        for name in ('OST_FabricationDuctwork', 'OST_FabricationPipework', 'OST_DuctCurves', 'OST_PipeCurves'):
            try:
                allowed.add(bic_int(getattr(DB.BuiltInCategory, name)))
            except Exception:
                pass
        return cid in allowed

    def _dim_host_data(self, dim):
        rects = []
        ids = set()
        try:
            for ref in dim.References:
                try:
                    e = doc.GetElement(ref.ElementId)
                except Exception:
                    e = None
                if e is None or not self._is_mep_dimension_host(e):
                    continue
                r = self.element_rect(e)
                if r is not None:
                    rects.append(r); ids.add(eid_int(e.Id))
        except Exception:
            pass
        rr = rect_union(rects)
        cc = None if rr is None else ((rr[0] + rr[2]) * .5, (rr[1] + rr[3]) * .5)
        return rr, cc, ids

    def _point_rect_dist(self, p, r):
        if r is None:
            return 1.0e30
        dx = 0.0 if r[0] <= p[0] <= r[2] else min(abs(p[0]-r[0]), abs(p[0]-r[2]))
        dy = 0.0 if r[1] <= p[1] <= r[3] else min(abs(p[1]-r[1]), abs(p[1]-r[3]))
        return math.sqrt(dx*dx + dy*dy)

    def assign_nearest_dim_hosts(self):
        # Managed helper references used by AutoDim may hide the physical MEP host.
        # Recover only when one endpoint of the dimension curve is genuinely local
        # to visible fabrication geometry. This is a local geometric fallback, not
        # a graph/topology walk.
        mep_rects = [x for x in self.static.rects if x[2] in ('fab_duct', 'fab_pipe')]
        if not mep_rects:
            return
        max_d = self.paper(.42)
        for s in self.states:
            if s['kind'] != 'dim' or s.get('host_rect') is not None or s.get('line') is None:
                continue
            a, b = s['line']
            best = None
            for r, sid, kind in mep_rects:
                d = min(self._point_rect_dist(a, r), self._point_rect_dist(b, r))
                if d <= max_d and (best is None or d < best[0]):
                    best = (d, r, sid)
            if best is not None:
                s['host_rect'] = best[1]
                s['host_center'] = ((best[1][0]+best[1][2])*.5, (best[1][1]+best[1][3])*.5)
                s['host_ids'] = set([best[2]])

    def _dim_station_data(self, s, du=0.0, dv=0.0):
        if s.get('line') is None or s.get('host_rect') is None:
            return None
        a = (s['line'][0][0]+du, s['line'][0][1]+dv)
        b = (s['line'][1][0]+du, s['line'][1][1]+dv)
        axis = norm2(sub2(b, a))
        if axis is None:
            return None
        normal = (-axis[1], axis[0])
        mid = ((a[0]+b[0])*.5, (a[1]+b[1])*.5)
        station = dot2(mid, normal)
        r = s['host_rect']
        corners = ((r[0],r[1]),(r[2],r[1]),(r[2],r[3]),(r[0],r[3]))
        vals = [dot2(q, normal) for q in corners]
        lo, hi = min(vals), max(vals)
        if station < lo:
            gap = lo - station; side = -1.0
        elif station > hi:
            gap = station - hi; side = 1.0
        else:
            gap = 0.0; side = 0.0
        return {'a':a,'b':b,'axis':axis,'normal':normal,'station':station,'lo':lo,'hi':hi,'gap':gap,'side':side}

    def _dim_compact_score(self, s, du=0.0, dv=0.0):
        if not self.settings.get('compact_dims', True):
            return 0.0
        d = self._dim_station_data(s, du, dv)
        if d is None:
            return 0.0
        p1 = max(self.paper(1.0), 1e-9)
        gap = d['gap'] / p1
        # Human drafting preference: dimension line sits just outside the host
        # instead of creating a long witness-line tail. Too close is also bad.
        if gap < .08:
            return 1800.0 + (.08-gap)*4000.0
        score = abs(gap - .24) * 430.0
        if gap > .60:
            score += (gap - .60) * 1800.0
        if gap > 1.00:
            score += (gap - 1.00) * 2400.0
        return score

    def _long_dim_station(self, s):
        d = self._dim_station_data(s, 0.0, 0.0)
        if d is None:
            return False
        return (d['gap'] / max(self.paper(1.0), 1e-9)) > .70

    def _count_dim_leaders(self):
        n = 0
        for s in self.states:
            if s['kind'] != 'dim':
                continue
            try:
                if bool(s['elem'].HasLeader): n += 1
            except Exception:
                pass
        return n

    def reset_dimension_text(self):
        if not self.settings.get('reset_dim_text', True):
            return
        for s in self.states:
            if s['kind'] != 'dim' or not s.get('movable'):
                continue
            e = s['elem']
            try:
                nseg = int(e.NumberOfSegments)
            except Exception:
                nseg = 0
            try:
                if nseg > 0:
                    for seg in e.Segments:
                        try:
                            seg.ResetTextPosition(); self.stats['dim_text_resets'] += 1
                        except Exception:
                            pass
                else:
                    try:
                        e.ResetTextPosition(); self.stats['dim_text_resets'] += 1
                    except Exception:
                        pass
            except Exception:
                pass


    def _allowed_multileader_host(self, elem):
        try:
            cid = eid_int(elem.Category.Id) if elem is not None and elem.Category is not None else -1
        except Exception:
            cid = -1
        allowed = set()
        for name in ('OST_FabricationDuctwork', 'OST_FabricationPipework', 'OST_DuctCurves', 'OST_PipeCurves'):
            try:
                allowed.add(bic_int(getattr(DB.BuiltInCategory, name)))
            except Exception:
                pass
        return cid in allowed

    def _host_service_key(self, elem):
        if elem is None:
            return ''
        vals = []
        for name in ('ServiceName', 'ServiceAbbreviation'):
            try:
                v = getattr(elem, name)
                if v:
                    vals.append(str(v).strip().lower())
            except Exception:
                pass
        return '|'.join(vals)

    def _tag_merge_record(self, tag):
        """Return a conservative single-host tag record eligible for local grouping."""
        try:
            if not self.settings.get('multi_leader', True):
                return None
            if self.settings['scope'] == 'selection' and eid_int(tag.Id) not in self.selected:
                return None
            try:
                if bool(tag.Pinned):
                    return None
            except Exception:
                pass
            try:
                if bool(tag.MultiLeader):
                    return None
            except Exception:
                pass
            try:
                if not bool(tag.HasTagBehavior()):
                    return None
            except Exception:
                pass

            refs = list(tag.GetTaggedReferences())
            hosts = list(tag.GetTaggedLocalElements())
            if len(refs) != 1 or len(hosts) != 1:
                return None
            host = hosts[0]
            if host is None or not self._allowed_multileader_host(host):
                return None
            center = self.center_of_element(host)
            if center is None:
                return None
            head_xyz = tag.TagHeadPosition
            if head_xyz is None:
                return None
            head = self.uv(head_xyz)
            try:
                tag_text = ' '.join(str(tag.TagText or '').split()).lower()
            except Exception:
                tag_text = ''
            # Empty tags should not be merged; they often indicate incompatible tag behavior.
            if not tag_text:
                return None
            try:
                type_id = eid_int(tag.GetTypeId())
            except Exception:
                type_id = -1
            try:
                tag_cat = eid_int(tag.Category.Id)
            except Exception:
                tag_cat = -1
            try:
                host_cat = eid_int(host.Category.Id)
            except Exception:
                host_cat = -1
            key = (type_id, tag_cat, host_cat, tag_text, self._host_service_key(host))
            return {
                'tag': tag, 'tag_id': eid_int(tag.Id), 'ref': refs[0], 'host': host,
                'host_id': eid_int(host.Id), 'center': center, 'head': head, 'key': key,
                'type_id': type_id
            }
        except Exception:
            return None

    def _cluster_merge_records(self, records):
        """Greedy local clusters; intentionally capped to avoid long multi-leader spider tags."""
        if len(records) < 2:
            return []
        radius = self.paper(.55 if self.settings['mode'] == 'conservative' else
                            (.82 if self.settings['mode'] == 'clean' else .68))
        max_span = self.paper(1.20 if self.settings['mode'] == 'conservative' else
                              (1.65 if self.settings['mode'] == 'clean' else 1.40))
        max_hosts = 3 if self.settings['mode'] == 'conservative' else 4
        unused = list(records)
        out = []
        while unused:
            seed = unused.pop(0)
            cluster = [seed]
            changed = True
            while changed and len(cluster) < max_hosts:
                changed = False
                cx = sum(r['center'][0] for r in cluster) / float(len(cluster))
                cy = sum(r['center'][1] for r in cluster) / float(len(cluster))
                cand = sorted(unused, key=lambda r: dist2(r['center'], (cx, cy)))
                for r in cand:
                    if len(cluster) >= max_hosts:
                        break
                    if min(dist2(r['center'], q['center']) for q in cluster) > radius:
                        continue
                    pts = [q['center'] for q in cluster] + [r['center']]
                    span = max(dist2(a, b) for a in pts for b in pts)
                    if span > max_span:
                        continue
                    # Keep the visual consolidation local too; distant existing heads are likely intentional.
                    if min(dist2(r['head'], q['head']) for q in cluster) > self.paper(1.35):
                        continue
                    cluster.append(r)
                    unused.remove(r)
                    changed = True
                    break
            if len(cluster) >= 2:
                out.append(cluster)
        return out

    def _try_add_multileader_host(self, keeper_rec, donor_rec):
        """Delete one duplicate tag and add its host reference to keeper in a guarded subtransaction."""
        type_id = keeper_rec.get('type_id', -1)
        if type_id in self._unsupported_multileader_types:
            return False
        st = DB.SubTransaction(doc)
        st.Start()
        try:
            donor_ref = donor_rec['ref']
            donor_id = donor_rec['tag'].Id
            doc.Delete(donor_id)
            doc.Regenerate()

            refs = List[DB.Reference]()
            refs.Add(donor_ref)
            keeper = keeper_rec['tag']
            keeper.AddReferences(refs)

            try:
                keeper.HasLeader = True
            except Exception:
                pass
            try:
                keeper.LeadersPresentationMode = DB.LeadersPresentationMode.ShowAll
            except Exception:
                pass
            try:
                keeper.MergeElbows = True
            except Exception:
                pass

            doc.Regenerate()
            try:
                if not bool(keeper.MultiLeader):
                    raise Exception('Tag did not become multi-leader.')
            except Exception:
                # If the property is unavailable, GetTaggedReferences() still proves success.
                if len(list(keeper.GetTaggedReferences())) < 2:
                    raise
            st.Commit()
            self.stats['multileader_hosts_added'] += 1
            self.stats['multileader_tags_removed'] += 1
            return True
        except Exception:
            try:
                st.RollBack()
            except Exception:
                pass
            self._unsupported_multileader_types.add(type_id)
            self.stats['multileader_unsupported'] += 1
            return False

    def _visible_class_elements(self, cls):
        """Return class elements whose graphics may be visible in the active view.

        View-scoped FEC is the primary path so copied/dependent views are not limited
        to elements strictly owned by the active view. OwnedByView remains a fallback
        for compatibility with unusual view/API conditions.
        """
        out = []
        seen = set()
        try:
            col = DB.FilteredElementCollector(doc, view.Id).OfClass(cls).WhereElementIsNotElementType()
            for e in col:
                k = eid_int(e.Id)
                if k in seen:
                    continue
                seen.add(k); out.append(e)
        except Exception:
            pass
        if out:
            return out
        try:
            col = DB.FilteredElementCollector(doc).OwnedByView(view.Id).OfClass(cls).WhereElementIsNotElementType()
            for e in col:
                k = eid_int(e.Id)
                if k in seen:
                    continue
                seen.add(k); out.append(e)
        except Exception:
            pass
        return out

    def consolidate_matching_tags(self):
        """Convert nearby identical single-host MEP tags into one guarded multi-leader tag when supported."""
        if not self.settings.get('multi_leader', True) or not self.settings.get('do_tags', True):
            return
        grouped = {}
        try:
            for e in self._visible_class_elements(DB.IndependentTag):
                rec = self._tag_merge_record(e)
                if rec is not None:
                    grouped.setdefault(rec['key'], []).append(rec)
        except Exception:
            return

        for key, records in grouped.items():
            if len(records) < 2:
                continue
            for cluster in self._cluster_merge_records(records):
                # Preserve the head closest to the host centroid; this usually gives the optimizer the shortest fan.
                cx = sum(r['center'][0] for r in cluster) / float(len(cluster))
                cy = sum(r['center'][1] for r in cluster) / float(len(cluster))
                keeper = min(cluster, key=lambda r: dist2(r['head'], (cx, cy)))
                merged = 0
                for donor in cluster:
                    if donor is keeper:
                        continue
                    if self._try_add_multileader_host(keeper, donor):
                        merged += 1
                    else:
                        # One failed AddReferences normally means this loaded tag type does not support UI multi-leader.
                        break
                if merged:
                    self.stats['multileader_groups'] += 1

    def _tag_lane_adjustment(self, s, new_head):
        """Small visual reward for local human-style tag rows/columns without forcing long leaders."""
        if not self.settings.get('do_tags', True):
            return 0.0
        best = 0.0
        near = self.paper(1.35)
        tol = self.paper(.035)
        for o in self.states:
            if o['id'] == s['id'] or o['kind'] != 'tag':
                continue
            if dist2(new_head, o['head']) > near:
                continue
            dx = abs(new_head[0] - o['head'][0])
            dy = abs(new_head[1] - o['head'][1])
            if dx <= tol or dy <= tol:
                best = min(best, -95.0)
        return best

    def _dim_bank_adjustment(self, s, a, b):
        """Reward parallel dimensions that settle into consistent local drafting banks."""
        if not self.settings.get('bank_dims', True):
            return 0.0
        axis = norm2(sub2(b, a))
        if axis is None:
            return 0.0
        normal = (-axis[1], axis[0])
        mid = ((a[0] + b[0]) * .5, (a[1] + b[1]) * .5)
        pa0 = dot2(a, axis); pa1 = dot2(b, axis)
        amin, amax = min(pa0, pa1), max(pa0, pa1)
        p1 = max(self.paper(1.0), 1e-9)
        score = 0.0
        for ln in self.other_dim_lines(s):
            oaxis = norm2(sub2(ln[1], ln[0]))
            if oaxis is None or abs(dot2(axis, oaxis)) < .995:
                continue
            pb0 = dot2(ln[0], axis); pb1 = dot2(ln[1], axis)
            bmin, bmax = min(pb0, pb1), max(pb0, pb1)
            if min(amax, bmax) < max(amin, bmin) - self.paper(.20):
                continue
            omid = ((ln[0][0] + ln[1][0]) * .5, (ln[0][1] + ln[1][1]) * .5)
            sep = abs(dot2(sub2(omid, mid), normal)) / p1
            if sep < .085:
                score += 900.0
                continue
            for idx, target in enumerate((.18, .36, .54, .72, .90)):
                err = abs(sep - target)
                if err <= .025:
                    score -= 150.0 / float(idx + 1)
                    break
                elif err <= .050:
                    score -= 60.0 / float(idx + 1)
                    break
        return score

    def _is_banked_dim(self, s):
        if s.get('line') is None:
            return False
        a, b = s['line']
        return self._dim_bank_adjustment(s, a, b) < -1.0

    def movable(self, elem, kind):
        if self.settings['scope'] == 'selection' and eid_int(elem.Id) not in self.selected:
            return False
        if kind == 'tag' and not self.settings['do_tags']: return False
        if kind == 'dim' and not self.settings['do_dims']: return False
        try:
            if bool(elem.Pinned):
                self.stats['pinned_skipped'] += 1; return False
        except Exception:
            pass
        return True

    def tag_metrics(self, tag):
        head = self.uv(tag.TagHeadPosition)
        fallback_w = .60
        try:
            txt = str(tag.TagText or '')
            fallback_w = clamp(.20 + .035 * len(txt), .42, 1.10)
        except Exception:
            pass
        halfw = self.paper(fallback_w * .5)
        halfh = self.paper(.10)
        use_bbox = True
        try: use_bbox = not bool(tag.HasLeader)
        except Exception: pass
        if use_bbox:
            r = self.element_rect(tag)
            if r is not None:
                safety = self.paper(.025)
                left = clamp(head[0] - r[0] + safety, self.paper(.04), self.paper(1.20))
                right = clamp(r[2] - head[0] + safety, self.paper(.04), self.paper(1.20))
                bottom = clamp(head[1] - r[1] + safety, self.paper(.035), self.paper(.65))
                top = clamp(r[3] - head[1] + safety, self.paper(.035), self.paper(.65))
                return (left, right, bottom, top)
        return (halfw, halfw, halfh, halfh)

    def tag_rect(self, head, metrics):
        pad = self.paper(.025)
        return (head[0] - metrics[0] - pad, head[1] - metrics[2] - pad,
                head[0] + metrics[1] + pad, head[1] + metrics[3] + pad)

    def dim_text_rect(self, p, axis=None):
        # Approximate the visible text footprint in its dimension orientation.
        # The old always-horizontal box badly under-estimated vertical dimension text.
        if axis is not None and abs(axis[1]) > abs(axis[0]):
            hw = self.paper(.075); hh = self.paper(.18)
        else:
            hw = self.paper(.18); hh = self.paper(.075)
        return (p[0] - hw, p[1] - hh, p[0] + hw, p[1] + hh)

    def tagged_ids(self, tag):
        ids = set()
        try:
            for e in tag.GetTaggedLocalElements():
                if e is not None: ids.add(eid_int(e.Id))
        except Exception:
            try:
                for e in tag.GetTaggedLocalElementIds(): ids.add(eid_int(e))
            except Exception: pass
        return ids

    def dim_ref_ids(self, dim):
        ids = set()
        try:
            for r in dim.References:
                try: ids.add(eid_int(r.ElementId))
                except Exception: pass
        except Exception: pass
        return ids

    def leader_data(self, tag, anchor):
        data = []
        try:
            if not bool(tag.HasLeader): return data
        except Exception:
            return data
        refs = []
        try: refs = list(tag.GetTaggedReferences())
        except Exception: pass
        for ref in refs:
            end = None; elbow = None
            try: end = self.uv(tag.GetLeaderEnd(ref))
            except Exception: end = anchor
            try: elbow = self.uv(tag.GetLeaderElbow(ref))
            except Exception: elbow = None
            if end is None: end = anchor
            data.append({'ref': ref, 'end': end, 'elbow': elbow})
        if not data and anchor is not None:
            data.append({'ref': None, 'end': anchor, 'elbow': None})
        return data

    def collect_annotations(self):
        # Tags: collect by active-view visibility, not only OwnerViewId.
        for e in self._visible_class_elements(DB.IndependentTag):
            try:
                head_xyz = e.TagHeadPosition
                if head_xyz is None:
                    continue
                h = self.uv(head_xyz); metrics = self.tag_metrics(e); rect = self.tag_rect(h, metrics)
                tids = self.tagged_ids(e)
                anchor = None
                try:
                    els = list(e.GetTaggedLocalElements())
                    centers = [self.center_of_element(x) for x in els if x is not None]
                    centers = [x for x in centers if x is not None]
                    if centers:
                        anchor = (sum(x[0] for x in centers) / float(len(centers)),
                                  sum(x[1] for x in centers) / float(len(centers)))
                except Exception:
                    pass
                if anchor is None:
                    anchor = h
                movable = self.movable(e, 'tag')
                st = {'id': eid_int(e.Id), 'kind': 'tag', 'elem': e, 'movable': movable,
                      'head_xyz': head_xyz, 'head': h, 'base_head': h, 'metrics': metrics, 'rect': rect,
                      'ignore_ids': tids, 'anchor': anchor, 'leaders': self.leader_data(e, anchor)}
                self.states.append(st); self.state_by_id[st['id']] = st; self.stats['tags_total'] += 1
                if movable:
                    self.stats['tags_movable'] += 1
            except Exception:
                self.stats['failures'] += 1

        # Dimensions: same active-view visibility rule.
        for e in self._visible_class_elements(DB.Dimension):
            try:
                line = None
                try:
                    c = e.Curve
                    if isinstance(c, DB.Line):
                        line = (self.uv(c.GetEndPoint(0)), self.uv(c.GetEndPoint(1)))
                except Exception:
                    pass
                axis = None
                if line is not None:
                    axis = norm2(sub2(line[1], line[0]))
                host_rect, host_center, host_ids = self._dim_host_data(e)
                texts = []
                try:
                    nseg = int(e.NumberOfSegments)
                except Exception:
                    nseg = 0
                if nseg > 0:
                    try:
                        for seg in e.Segments:
                            adjustable = True
                            try: adjustable = bool(seg.IsTextPositionAdjustable())
                            except Exception: pass
                            try: pxyz = seg.TextPosition
                            except Exception: pxyz = None
                            if pxyz is not None:
                                puv = self.uv(pxyz)
                                texts.append({'owner': seg, 'xyz': pxyz, 'uv': puv, 'rect': self.dim_text_rect(puv, axis), 'adjustable': adjustable})
                    except Exception:
                        pass
                else:
                    adjustable = True
                    try: adjustable = bool(e.IsTextPositionAdjustable())
                    except Exception: pass
                    try: pxyz = e.TextPosition
                    except Exception: pxyz = None
                    if pxyz is not None:
                        puv = self.uv(pxyz)
                        texts.append({'owner': e, 'xyz': pxyz, 'uv': puv, 'rect': self.dim_text_rect(puv, axis), 'adjustable': adjustable})
                if line is None and not texts:
                    continue
                movable = self.movable(e, 'dim')
                st = {'id': eid_int(e.Id), 'kind': 'dim', 'elem': e, 'movable': movable,
                      'line': line, 'base_line': line, 'texts': texts, 'ignore_ids': self.dim_ref_ids(e),
                      'host_rect': host_rect, 'host_center': host_center, 'host_ids': host_ids}
                self.states.append(st); self.state_by_id[st['id']] = st; self.stats['dims_total'] += 1
                if movable:
                    self.stats['dims_movable'] += 1
            except Exception:
                self.stats['failures'] += 1

    def collect_mep(self):
        pad = self.paper(.018)
        if self.settings['avoid_duct']:
            try:
                bic = DB.BuiltInCategory.OST_FabricationDuctwork
                for e in DB.FilteredElementCollector(doc, view.Id).OfCategory(bic).WhereElementIsNotElementType():
                    r = self.element_rect(e)
                    if r is not None:
                        self.static.add_rect(rect_expand(r, pad), eid_int(e.Id), 'fab_duct'); self.stats['fab_duct'] += 1
            except Exception: pass
        if self.settings['avoid_pipe']:
            try:
                bic = DB.BuiltInCategory.OST_FabricationPipework
                for e in DB.FilteredElementCollector(doc, view.Id).OfCategory(bic).WhereElementIsNotElementType():
                    r = self.element_rect(e)
                    if r is not None:
                        self.static.add_rect(rect_expand(r, pad), eid_int(e.Id), 'fab_pipe'); self.stats['fab_pipe'] += 1
            except Exception: pass

    def work_rect(self):
        rs = []
        for s in self.states:
            if s['kind'] == 'tag': rs.append(s['rect'])
            else:
                if s['line'] is not None:
                    a, b = s['line']; rs.append((min(a[0],b[0]), min(a[1],b[1]), max(a[0],b[0]), max(a[1],b[1])))
                for t in s['texts']: rs.append(t['rect'])
        r = rect_union(rs)
        return rect_expand(r, self.paper(1.75)) if r is not None else None

    def cad_weight(self, layer, paper_len):
        name = (layer or '').lower()
        if any(w in name for w in ('hatch','patt','pattern','fill','poche','poch','solid','tile','insul')): return 1.0
        if any(w in name for w in ('wall','door','window','wind','glaz','partition','shaft','column','colu','case','mill','stair','beam','struct','curb','arch')): return 155.0
        if paper_len >= 1.00: return 42.0
        if paper_len >= .45: return 20.0
        if paper_len >= .18: return 8.0
        return 1.0

    def graphics_style(self, obj, cache):
        try:
            sid = obj.GraphicsStyleId; key = eid_int(sid)
            if key in cache: return cache[key]
            gs = doc.GetElement(sid)
            if gs is None or gs.GraphicsStyleCategory is None: info = (True, '')
            else:
                try: visible = not view.GetCategoryHidden(gs.GraphicsStyleCategory.Id)
                except Exception: visible = True
                try: name = str(gs.GraphicsStyleCategory.Name or '')
                except Exception: name = ''
                info = (visible, name)
            cache[key] = info; return info
        except Exception:
            return (True, '')

    def scan_geo(self, geo, source_id, scan_rect, counter, style_cache, cap):
        if geo is None or counter[0] >= cap: return
        for obj in geo:
            if counter[0] >= cap: return
            try:
                if isinstance(obj, DB.GeometryInstance):
                    self.scan_geo(obj.GetInstanceGeometry(), source_id, scan_rect, counter, style_cache, cap)
                elif isinstance(obj, DB.PolyLine):
                    vis, layer = self.graphics_style(obj, style_cache)
                    if not vis: continue
                    pts = list(obj.GetCoordinates())
                    self.add_cad_points(pts, source_id, layer, scan_rect, counter, cap)
                elif isinstance(obj, DB.Curve):
                    vis, layer = self.graphics_style(obj, style_cache)
                    if not vis: continue
                    pts = list(obj.Tessellate())
                    self.add_cad_points(pts, source_id, layer, scan_rect, counter, cap)
            except Exception:
                pass

    def add_cad_points(self, pts, source_id, layer, scan_rect, counter, cap):
        if len(pts) < 2: return
        min_len = self.paper(.006)
        for i in range(len(pts) - 1):
            if counter[0] >= cap: return
            a = self.uv(pts[i]); b = self.uv(pts[i+1]); d = dist2(a,b)
            if d < min_len: continue
            box = (min(a[0],b[0]), min(a[1],b[1]), max(a[0],b[0]), max(a[1],b[1]))
            if scan_rect is not None and not rect_intersects(box, scan_rect): continue
            w = self.cad_weight(layer, d / max(self.paper(1.0), 1e-9))
            self.static.add_cad(a, b, w, source_id); counter[0] += 1

    def collect_dwg(self):
        if not self.settings['avoid_dwg']: return
        scan_rect = self.work_rect(); cap = 60000; counter = [0]; cache = {}
        opts = DB.Options(); opts.IncludeNonVisibleObjects = False; opts.ComputeReferences = False
        try: opts.View = view
        except Exception: pass
        try:
            imports = DB.FilteredElementCollector(doc, view.Id).OfClass(DB.ImportInstance).WhereElementIsNotElementType()
            for imp in imports:
                if counter[0] >= cap: break
                try:
                    if imp.IsHidden(view): continue
                except Exception: pass
                r = self.element_rect(imp)
                if scan_rect is not None and r is not None and not rect_intersects(r, scan_rect): continue
                self.stats['dwgs'] += 1
                try:
                    geo = imp.get_Geometry(opts)
                    if geo is None:
                        self.stats['dwg_failed'] += 1; continue
                    self.scan_geo(geo, eid_int(imp.Id), scan_rect, counter, cache, cap)
                except Exception:
                    self.stats['dwg_failed'] += 1
        except Exception:
            self.stats['dwg_failed'] += 1
        self.stats['dwg_segments'] = counter[0]; self.stats['dwg_capped'] = counter[0] >= cap

    def other_rects(self, s):
        for o in self.states:
            if o['id'] == s['id']: continue
            if o['kind'] == 'tag':
                yield ('tag', o['rect'])
            else:
                for t in o['texts']: yield ('dim_text', t['rect'])

    def other_dim_lines(self, s):
        for o in self.states:
            if o['id'] == s['id'] or o['kind'] != 'dim' or o['line'] is None: continue
            yield o['line']

    def rect_score(self, s, r):
        score = 0.0; hits = 0
        for kind, rr in self.other_rects(s):
            if rect_intersects(r, rr):
                score += 12000.0; hits += 1
        line_pad = self.paper(.018)
        for ln in self.other_dim_lines(s):
            if seg_intersects_rect(ln[0], ln[1], rect_expand(r, line_pad)):
                score += 2600.0; hits += 1
        for item in self.static.rect_hits(r, s.get('ignore_ids')):
            score += 7600.0; hits += 1
        cad_score, cad_hits = self.static.cad_score_rect(r)
        score += cad_score; hits += cad_hits
        return score, hits

    def line_score(self, s, a, b, leader=False):
        score = 0.0; hits = 0; pad = self.paper(.018 if leader else .025)
        for kind, rr in self.other_rects(s):
            if seg_intersects_rect(a, b, rect_expand(rr, pad)):
                score += (1800.0 if leader else 2300.0); hits += 1
        for ln in self.other_dim_lines(s):
            if seg_distance(a, b, ln[0], ln[1]) <= self.paper(.035):
                score += (750.0 if leader else 2100.0); hits += 1
        for item in self.static.line_rect_hits(a, b, pad, s.get('ignore_ids')):
            score += (430.0 if leader else 720.0); hits += 1
        cad_score, cad_hits = self.static.cad_score_line(a, b, pad)
        score += cad_score; hits += cad_hits
        return score, hits

    def tag_candidate(self, s, new_head, penalty=True):
        du = new_head[0] - s['head'][0]; dv = new_head[1] - s['head'][1]
        r = self.tag_rect(new_head, s['metrics'])
        score, hits = self.rect_score(s, r)
        lead_segs = []
        for ld in s['leaders']:
            end = ld['end']
            elbow = ld['elbow']
            if elbow is not None:
                ne = (elbow[0] + du, elbow[1] + dv)
                lead_segs.append((new_head, ne)); lead_segs.append((ne, end))
            elif end is not None:
                lead_segs.append((new_head, end))
        for a, b in lead_segs:
            sc, hh = self.line_score(s, a, b, True); score += sc; hits += hh
        if s['anchor'] is not None and lead_segs:
            lp = dist2(new_head, s['anchor']) / max(self.paper(1.0), 1e-9)
            if lp > .85: score += (lp - .85) * 430.0
        score += self._tag_lane_adjustment(s, new_head)
        if penalty:
            move_p = dist2(new_head, s['head']) / max(self.paper(1.0), 1e-9)
            score += move_p * self.cfg['tag_pen']
        return score, hits, r

    def tag_candidates(self, s):
        dirs = [(1,0),(-1,0),(0,1),(0,-1)]
        av = norm2(sub2(s['head'], s['anchor'])) if s['anchor'] is not None else None
        if av is not None:
            dirs = [av, (-av[0],-av[1]), (-av[1],av[0]), (av[1],-av[0])] + dirs
        unique = []; seen = set()
        for p in self.cfg['tag_steps']:
            d = self.paper(p)
            if p == 0.0:
                cand = s['head']; key = (round(cand[0],5), round(cand[1],5)); seen.add(key); unique.append(cand); continue
            for v in dirs:
                cand = (s['head'][0] + v[0]*d, s['head'][1] + v[1]*d)
                key = (round(cand[0],5), round(cand[1],5))
                if key not in seen: seen.add(key); unique.append(cand)
            if p <= .42:
                dd = d * .70710678
                for v in ((1,1),(1,-1),(-1,1),(-1,-1)):
                    cand = (s['head'][0] + v[0]*dd, s['head'][1] + v[1]*dd)
                    key = (round(cand[0],5), round(cand[1],5))
                    if key not in seen: seen.add(key); unique.append(cand)
        return unique[:56]

    def apply_tag_move(self, s, new_head):
        du = new_head[0] - s['head'][0]; dv = new_head[1] - s['head'][1]
        if abs(du) + abs(dv) < 1e-9: return False
        try:
            new_xyz = self.move_xyz(s['head_xyz'], du, dv)
            s['elem'].TagHeadPosition = new_xyz
            for ld in s['leaders']:
                if ld['ref'] is None or ld['elbow'] is None: continue
                ne = (ld['elbow'][0] + du, ld['elbow'][1] + dv)
                if self.settings['clean_shoulders']:
                    vv = sub2(ne, new_head); lp = length2(vv) / max(self.paper(1.0),1e-9)
                    if lp > .32:
                        nv = norm2(vv)
                        if nv is not None:
                            target = self.paper(self.cfg['shoulder'])
                            ne = (new_head[0] + nv[0]*target, new_head[1] + nv[1]*target)
                            self.stats['leaders_cleaned'] += 1
                try:
                    old_elbow_xyz = s['elem'].GetLeaderElbow(ld['ref'])
                    new_elbow_xyz = self.move_xyz(old_elbow_xyz, ne[0] - self.uv(old_elbow_xyz)[0], ne[1] - self.uv(old_elbow_xyz)[1])
                    s['elem'].SetLeaderElbow(ld['ref'], new_elbow_xyz)
                    ld['elbow'] = ne
                except Exception: pass
            s['head'] = new_head; s['head_xyz'] = new_xyz; s['rect'] = self.tag_rect(new_head, s['metrics'])
            self._moved_tags.add(s['id']); self.stats['tags_moved'] = len(self._moved_tags); return True
        except Exception:
            self.stats['failures'] += 1; return False

    def dim_geometry_score(self, s, du, dv, penalty=True):
        score = 0.0; hits = 0
        if s['line'] is not None:
            a = (s['line'][0][0]+du, s['line'][0][1]+dv); b = (s['line'][1][0]+du, s['line'][1][1]+dv)
            sc, hh = self.line_score(s, a, b, False); score += sc; hits += hh
        for t in s['texts']:
            r = rect_translate(t['rect'], du, dv)
            sc, hh = self.rect_score(s, r); score += sc; hits += hh
        if s['line'] is not None:
            a = (s['line'][0][0]+du, s['line'][0][1]+dv)
            b = (s['line'][1][0]+du, s['line'][1][1]+dv)
            score += self._dim_bank_adjustment(s, a, b)
            score += self._dim_compact_score(s, du, dv)
        if penalty:
            move_p = math.sqrt(du*du+dv*dv)/max(self.paper(1.0),1e-9)
            score += move_p*self.cfg['dim_pen']
        return score, hits

    def dim_candidates(self, s):
        if s['line'] is None: return [(0.0,0.0)]
        d = sub2(s['line'][1], s['line'][0]); nv = norm2((-d[1], d[0]))
        if nv is None: return [(0.0,0.0)]
        out = [(0.0,0.0)]
        seen = set([(0,0)])
        def add(du,dv):
            key=(round(du,5),round(dv,5))
            if key not in seen:
                seen.add(key); out.append((du,dv))
        for p in self.cfg['dim_steps'][1:]:
            m = self.paper(p); add(nv[0]*m,nv[1]*m); add(-nv[0]*m,-nv[1]*m)

        # Human-compact candidates: put the dimension line just outside the
        # referenced MEP's projected footprint. This shortens witness lines
        # without changing references or measured values.
        if self.settings.get('compact_dims', True) and s.get('host_rect') is not None:
            sd = self._dim_station_data(s,0.0,0.0)
            if sd is not None:
                normal = sd['normal']; cur = sd['station']
                offsets = (.14,.22,.32,.46,.62)
                max_move = {'conservative':.65,'balanced':1.10,'clean':1.60}.get(self.settings['mode'],1.10)
                max_ft = self.paper(max_move)
                for p in offsets:
                    off=self.paper(p)
                    for target in (sd['lo']-off, sd['hi']+off):
                        delta=target-cur
                        if abs(delta) <= max_ft:
                            add(normal[0]*delta, normal[1]*delta)
        return out[:40]

    def apply_dim_move(self, s, du, dv):
        if abs(du)+abs(dv)<1e-9: return False
        try:
            vec = DB.XYZ(self.right.X*du+self.up.X*dv, self.right.Y*du+self.up.Y*dv, self.right.Z*du+self.up.Z*dv)
            DB.ElementTransformUtils.MoveElement(doc, s['elem'].Id, vec)
            if s['line'] is not None:
                s['line'] = ((s['line'][0][0]+du,s['line'][0][1]+dv),(s['line'][1][0]+du,s['line'][1][1]+dv))
            for t in s['texts']:
                t['uv'] = (t['uv'][0]+du,t['uv'][1]+dv); t['xyz'] = self.move_xyz(t['xyz'],du,dv); t['rect'] = rect_translate(t['rect'],du,dv)
            self._moved_dims.add(s['id']); self.stats['dims_moved'] = len(self._moved_dims)
            if self.settings.get('compact_dims', True):
                self.stats['compact_dim_moves'] += 1
            if self.settings.get('bank_dims', True) and self._is_banked_dim(s):
                self.stats['dim_bank_snaps'] += 1
            return True
        except Exception:
            self.stats['failures'] += 1; return False

    def optimize_dim_text(self, s):
        moved = 0
        if not s['texts']: return 0
        axis = None
        if s['line'] is not None: axis = norm2(sub2(s['line'][1],s['line'][0]))
        if axis is None: axis = (1.0,0.0)
        # Keep dimension text on/near its dimension line. Perpendicular dragging
        # is what creates the huge dimension-text leaders seen in field tests.
        steps = (.05,.09,.13,.18) if self.settings.get('reset_dim_text', True) else tuple(self.cfg['text_steps'][1:])
        for t in s['texts']:
            if not t.get('adjustable',True): continue
            base_score, _ = self.rect_score(s,t['rect'])
            best = (base_score,0.0,0.0,t['uv'],t['rect'])
            for p in steps:
                m = self.paper(p)
                for v in (axis,(-axis[0],-axis[1])):
                    q=(t['uv'][0]+v[0]*m,t['uv'][1]+v[1]*m); r=self.dim_text_rect(q,axis)
                    sc,_=self.rect_score(s,r); sc += p*self.cfg['text_pen']
                    if sc < best[0]: best=(sc,v[0]*m,v[1]*m,q,r)
            if best[0] + self.cfg['gain'] < base_score:
                try:
                    qxyz = self.move_xyz(t['xyz'],best[1],best[2])
                    t['owner'].TextPosition = qxyz
                    t['xyz']=qxyz; t['uv']=best[3]; t['rect']=best[4]; moved += 1; self.stats['dim_text_moved'] += 1
                except Exception:
                    self.stats['failures'] += 1
        return moved

    def refresh_states(self):
        for s in self.states:
            try:
                if s['kind'] == 'tag':
                    hp = s['elem'].TagHeadPosition
                    if hp is not None:
                        s['head_xyz'] = hp
                        s['head'] = self.uv(hp)
                        s['rect'] = self.tag_rect(s['head'], s['metrics'])
                    for ld in s['leaders']:
                        ref = ld.get('ref')
                        if ref is None:
                            continue
                        try: ld['elbow'] = self.uv(s['elem'].GetLeaderElbow(ref))
                        except Exception: ld['elbow'] = None
                        try: ld['end'] = self.uv(s['elem'].GetLeaderEnd(ref))
                        except Exception: pass
                else:
                    try:
                        c = s['elem'].Curve
                        if isinstance(c, DB.Line):
                            s['line'] = (self.uv(c.GetEndPoint(0)), self.uv(c.GetEndPoint(1)))
                    except Exception:
                        pass
                    for t in s['texts']:
                        try:
                            pxyz = t['owner'].TextPosition
                            if pxyz is not None:
                                puv = self.uv(pxyz)
                                axis = norm2(sub2(s['line'][1],s['line'][0])) if s.get('line') is not None else None
                                t['xyz'] = pxyz; t['uv'] = puv; t['rect'] = self.dim_text_rect(puv, axis)
                        except Exception:
                            pass
            except Exception:
                pass

    def conflict_breakdown(self, s):
        """Return whether this annotation currently conflicts with annotation, MEP, or DWG geometry."""
        flags = {'annotation': False, 'mep': False, 'dwg': False}

        def check_rect(r):
            if r is None:
                return
            for kind, rr in self.other_rects(s):
                if rect_intersects(r, rr):
                    flags['annotation'] = True; break
            if not flags['annotation']:
                pad = self.paper(.018)
                for ln in self.other_dim_lines(s):
                    if seg_intersects_rect(ln[0], ln[1], rect_expand(r, pad)):
                        flags['annotation'] = True; break
            try:
                for item in self.static.rect_hits(r, s.get('ignore_ids')):
                    if item[2] in ('fab_duct', 'fab_pipe'):
                        flags['mep'] = True; break
            except Exception:
                pass
            try:
                if self.static.cad_score_rect(r)[1] > 0:
                    flags['dwg'] = True
            except Exception:
                pass

        def check_line(a, b, leader=False):
            if a is None or b is None:
                return
            pad = self.paper(.018 if leader else .025)
            for kind, rr in self.other_rects(s):
                if seg_intersects_rect(a, b, rect_expand(rr, pad)):
                    flags['annotation'] = True; break
            if not flags['annotation']:
                for ln in self.other_dim_lines(s):
                    if seg_distance(a, b, ln[0], ln[1]) <= self.paper(.035):
                        flags['annotation'] = True; break
            try:
                for item in self.static.line_rect_hits(a, b, pad, s.get('ignore_ids')):
                    if item[2] in ('fab_duct', 'fab_pipe'):
                        flags['mep'] = True; break
            except Exception:
                pass
            try:
                if self.static.cad_score_line(a, b, pad)[1] > 0:
                    flags['dwg'] = True
            except Exception:
                pass

        if s['kind'] == 'tag':
            check_rect(s.get('rect'))
            head = s.get('head')
            for ld in s.get('leaders', []):
                end = ld.get('end'); elbow = ld.get('elbow')
                if elbow is not None:
                    check_line(head, elbow, True); check_line(elbow, end, True)
                elif end is not None:
                    check_line(head, end, True)
        else:
            if s.get('line') is not None:
                check_line(s['line'][0], s['line'][1], False)
            for t in s.get('texts', []):
                check_rect(t.get('rect'))
        return flags

    def conflict_summary(self):
        out = {'annotation': 0, 'mep': 0, 'dwg': 0}
        for s in self.states:
            f = self.conflict_breakdown(s)
            for k in out:
                if f.get(k):
                    out[k] += 1
        return out

    def conflict_score(self, s):
        if s['kind']=='tag': return self.tag_candidate(s,s['head'],False)[0]
        return self.dim_geometry_score(s,0.0,0.0,False)[0]

    def hard_conflict_count(self):
        count=0
        for s in self.states:
            if self.conflict_score(s) >= 2000.0: count += 1
        return count

    def optimize_dimensions(self):
        dims=[s for s in self.states if s['kind']=='dim' and s['movable']]
        dims.sort(key=lambda s:self.conflict_score(s), reverse=True)
        for s in dims:
            base=self.dim_geometry_score(s,0.0,0.0,False)[0]
            best=(base,0.0,0.0)
            for du,dv in self.dim_candidates(s):
                sc,_=self.dim_geometry_score(s,du,dv,True)
                if sc < best[0]: best=(sc,du,dv)
            if best[0]+self.cfg['gain'] < base:
                self.apply_dim_move(s,best[1],best[2])
            self.optimize_dim_text(s)

    def optimize_tags(self):
        tags=[s for s in self.states if s['kind']=='tag' and s['movable']]
        tags.sort(key=lambda s:self.conflict_score(s), reverse=True)
        for s in tags:
            base=self.tag_candidate(s,s['head'],False)[0]
            best=(base,s['head'])
            for q in self.tag_candidates(s):
                sc,hh,r=self.tag_candidate(s,q,True)
                if sc < best[0]: best=(sc,q)
            if best[0]+self.cfg['gain'] < base:
                self.apply_tag_move(s,best[1])

    def cleanup_tag_shoulders(self):
        if not self.settings['clean_shoulders']:
            return
        max_paper = .42 if self.settings['mode'] == 'conservative' else .36
        target = self.paper(self.cfg['shoulder'])
        for s in self.states:
            if s['kind'] != 'tag' or not s['movable']:
                continue
            for ld in s['leaders']:
                if ld.get('ref') is None or ld.get('elbow') is None:
                    continue
                vv = sub2(ld['elbow'], s['head'])
                paper_len = length2(vv) / max(self.paper(1.0), 1e-9)
                if paper_len <= max_paper:
                    continue
                nv = norm2(vv)
                if nv is None:
                    continue
                desired = (s['head'][0] + nv[0] * target, s['head'][1] + nv[1] * target)
                try:
                    current_xyz = s['elem'].GetLeaderElbow(ld['ref'])
                    current_uv = self.uv(current_xyz)
                    desired_xyz = self.move_xyz(current_xyz, desired[0] - current_uv[0], desired[1] - current_uv[1])
                    s['elem'].SetLeaderElbow(ld['ref'], desired_xyz)
                    ld['elbow'] = desired
                    self.stats['leaders_cleaned'] += 1
                except Exception:
                    pass

    def run(self):
        group = DB.TransactionGroup(doc, 'ROBMEPTOOLS Tag + Dim Organizer')
        group.Start()
        try:
            if self.settings.get('multi_leader', True) and self.settings.get('do_tags', True):
                t0 = DB.Transaction(doc, 'Consolidate matching MEP tags')
                t0.Start()
                try:
                    self.consolidate_matching_tags()
                    doc.Regenerate()
                    t0.Commit()
                except Exception:
                    try:
                        t0.RollBack()
                    except Exception:
                        pass
                    raise

            self.collect_annotations()
            if not self.states:
                group.Assimilate()
                return {'message':'No supported tags or dimensions were found in the active view.'}
            self.collect_mep(); self.assign_nearest_dim_hosts(); self.collect_dwg()
            before=self.hard_conflict_count()
            before_breakdown = self.conflict_summary()
            self.stats['long_dim_stations_before'] = sum(1 for x in self.states if x['kind']=='dim' and self._long_dim_station(x))
            self.stats['dim_leaders_before'] = self._count_dim_leaders()

            tx=DB.Transaction(doc,'Organize tags and dimensions')
            tx.Start()
            try:
                self.reset_dimension_text()
                doc.Regenerate(); self.refresh_states()
                passes=self.cfg['passes'] if self.settings['second_pass'] else 1
                if self.settings['mode']=='conservative': passes=1
                for i in range(passes):
                    self.optimize_dimensions(); self.optimize_tags(); self.stats['passes'] += 1
                    doc.Regenerate(); self.refresh_states()
                self.cleanup_tag_shoulders()
                doc.Regenerate(); self.refresh_states(); tx.Commit()
            except Exception:
                try: tx.RollBack()
                except Exception: pass
                raise

            after=self.hard_conflict_count()
            after_breakdown = self.conflict_summary()
            self.stats['long_dim_stations_after'] = sum(1 for x in self.states if x['kind']=='dim' and self._long_dim_station(x))
            self.stats['dim_leaders_after'] = self._count_dim_leaders()
            self.stats['hard_before']=before; self.stats['hard_after']=after
            self.stats['annotation_conflicts_before'] = before_breakdown.get('annotation', 0)
            self.stats['annotation_conflicts_after'] = after_breakdown.get('annotation', 0)
            self.stats['mep_conflicts_before'] = before_breakdown.get('mep', 0)
            self.stats['mep_conflicts_after'] = after_breakdown.get('mep', 0)
            self.stats['dwg_conflicts_before'] = before_breakdown.get('dwg', 0)
            self.stats['dwg_conflicts_after'] = after_breakdown.get('dwg', 0)
            group.Assimilate()
            return self.stats
        except Exception:
            try:
                group.RollBack()
            except Exception:
                pass
            raise


def valid_view():
    try:
        if view is None or bool(view.IsTemplate): return False
        name = str(view.ViewType)
        return name not in ('Schedule', 'ProjectBrowser', 'SystemBrowser', 'Report', 'DrawingSheet')
    except Exception:
        return True


def detailed_report(stats, settings):
    output.print_md('## Tag + Dim Organizer v0.4 Human Compact Dimensions Beta')
    output.print_md('Mode: `{0}`  |  Scope: `{1}`'.format(settings['mode'], settings['scope']))
    output.print_md('Detected tags: `{0}` (movable `{1}`) | Detected dimensions: `{2}` (movable `{3}`)'.format(stats.get('tags_total',0),stats.get('tags_movable',0),stats.get('dims_total',0),stats.get('dims_movable',0)))
    output.print_md('Tags moved: `{0}` | Dimensions moved: `{1}` | Dimension text nudges: `{2}` | Leader shoulders cleaned: `{3}`'.format(
        stats.get('tags_moved',0),stats.get('dims_moved',0),stats.get('dim_text_moved',0),stats.get('leaders_cleaned',0)))
    output.print_md('Multi-leader groups: `{0}` | Hosts consolidated: `{1}` | Redundant tag heads removed: `{2}` | Unsupported tag types encountered: `{3}`'.format(
        stats.get('multileader_groups',0),stats.get('multileader_hosts_added',0),
        stats.get('multileader_tags_removed',0),stats.get('multileader_unsupported',0)))
    output.print_md('Whole dimensions compacted: `{0}` | Dimension bank snaps: `{1}` | Text positions reset: `{2}`'.format(stats.get('compact_dim_moves',0),stats.get('dim_bank_snaps',0),stats.get('dim_text_resets',0)))
    output.print_md('Long witness-line stations: `{0}` → `{1}` | Dimension text leaders: `{2}` → `{3}`'.format(stats.get('long_dim_stations_before',0),stats.get('long_dim_stations_after',0),stats.get('dim_leaders_before',0),stats.get('dim_leaders_after',0)))
    output.print_md('High-conflict annotations: `{0}` → `{1}`'.format(stats.get('hard_before',0),stats.get('hard_after',0)))
    output.print_md('Annotation conflicts: `{0}` → `{1}` | MEP conflicts: `{2}` → `{3}` | DWG conflicts: `{4}` → `{5}`'.format(
        stats.get('annotation_conflicts_before',0),stats.get('annotation_conflicts_after',0),
        stats.get('mep_conflicts_before',0),stats.get('mep_conflicts_after',0),
        stats.get('dwg_conflicts_before',0),stats.get('dwg_conflicts_after',0)))
    output.print_md('Fab duct obstacles: `{0}` | Fab pipe obstacles: `{1}`'.format(stats.get('fab_duct',0),stats.get('fab_pipe',0)))
    output.print_md('DWGs scanned: `{0}` | DWG segments: `{1}` | DWG parse failures: `{2}` | capped: `{3}`'.format(
        stats.get('dwgs',0),stats.get('dwg_segments',0),stats.get('dwg_failed',0),stats.get('dwg_capped',False)))
    output.print_md('Pinned skipped: `{0}` | caught move/read failures: `{1}`'.format(stats.get('pinned_skipped',0),stats.get('failures',0)))


def main():
    if not valid_view():
        forms.alert('Open a graphical project view before running Tag + Dim Organizer.', title='TAG + DIM ORGANIZER')
        return
    win=OrganizerWindow(); win.ShowDialog()
    if not win.run_requested or not win.settings: return
    if not win.settings['do_tags'] and not win.settings['do_dims']:
        forms.alert('Turn on Tags, Dimensions, or both.', title='TAG + DIM ORGANIZER'); return
    if win.settings['scope']=='selection':
        selected=list(uidoc.Selection.GetElementIds())
        if not selected:
            forms.alert('Selected Annotation scope is active, but nothing is selected.', title='TAG + DIM ORGANIZER'); return
    try:
        result=OrganizerEngine(win.settings).run()
    except Exception as ex:
        try:
            output.print_md('## Tag + Dim Organizer error')
            output.print_md('```text\n{0}\n```'.format(traceback.format_exc()))
        except Exception: pass
        forms.alert('Organizer stopped because of an error:\n\n{0}'.format(ex), title='TAG + DIM ORGANIZER')
        return
    if 'message' in result:
        forms.alert(result['message'], title='TAG + DIM ORGANIZER'); return
    summary=(
        'Tag + Dim Organizer complete.\n\n'
        'Detected: {0} tags ({1} movable), {2} dimensions ({3} movable)\n'
        'High-conflict annotations: {4} -> {5}\n'
        'Annotation conflicts: {6} -> {7}\n'
        'MEP conflicts: {8} -> {9}\n'
        'DWG conflicts: {10} -> {11}\n\n'
        'Tags moved: {12}\n'
        'Dimensions moved: {13}\n'
        'Dimension text nudges: {14}\n'
        'Leader shoulders cleaned: {15}\n'
        'Multi-leader groups created: {16}\n'
        'Redundant tag heads consolidated: {17}\n'
        'Dimension bank snaps: {18}\n'
        'Whole dimensions compacted: {19}\n'
        'Dimension text positions reset: {20}\n'
        'Long witness-line stations: {21} -> {22}\n'
        'Dimension text leaders: {23} -> {24}\n\n'
        'Fabrication obstacles: {25} duct + {26} pipe\n'
        'DWGs scanned: {27} ({28} indexed segments)\n\n'
        'MEP Fabrication geometry was not moved.'
    ).format(result.get('tags_total',0),result.get('tags_movable',0),result.get('dims_total',0),result.get('dims_movable',0),
             result.get('hard_before',0),result.get('hard_after',0),
             result.get('annotation_conflicts_before',0),result.get('annotation_conflicts_after',0),
             result.get('mep_conflicts_before',0),result.get('mep_conflicts_after',0),
             result.get('dwg_conflicts_before',0),result.get('dwg_conflicts_after',0),
             result.get('tags_moved',0),result.get('dims_moved',0),result.get('dim_text_moved',0),result.get('leaders_cleaned',0),
             result.get('multileader_groups',0),result.get('multileader_tags_removed',0),result.get('dim_bank_snaps',0),
             result.get('compact_dim_moves',0),result.get('dim_text_resets',0),
             result.get('long_dim_stations_before',0),result.get('long_dim_stations_after',0),
             result.get('dim_leaders_before',0),result.get('dim_leaders_after',0),
             result.get('fab_duct',0),result.get('fab_pipe',0),result.get('dwgs',0),result.get('dwg_segments',0))
    forms.alert(summary,title='TAG + DIM ORGANIZER')
    if win.settings['detailed']:
        detailed_report(result,win.settings)


if __name__=='__main__':
    main()
