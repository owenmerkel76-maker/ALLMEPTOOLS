# -*- coding: utf-8 -*-
"""Direct component tagging helpers for ROBMEPTOOLS AutoTag.

This module stays separate from the straight-run event engine. The duct engine
can supply an external layout handler for boxed terminal/equipment callouts.
"""
import time
import System
from pyrevit import DB


def _eid_value(eid):
    try:
        return int(eid.Value)
    except Exception:
        try:
            return int(eid.IntegerValue)
        except Exception:
            return None


def _physical_connector(c):
    try:
        t = str(c.ConnectorType).lower()
        return ('end' in t) or ('curve' in t) or ('physical' in t)
    except Exception:
        return True


def _connectors(elem):
    out = []
    try:
        cm = elem.ConnectorManager
        for c in cm.Connectors:
            if _physical_connector(c):
                out.append(c)
        return out
    except Exception:
        pass
    try:
        cm = elem.MEPModel.ConnectorManager
        for c in cm.Connectors:
            if _physical_connector(c):
                out.append(c)
    except Exception:
        pass
    return out


def _profile(c):
    shape = ''
    vals = []
    try:
        shape = str(c.Shape).lower()
    except Exception:
        pass
    try:
        if 'round' in shape:
            vals = [float(c.Radius) * 2.0]
        else:
            vals = sorted([float(c.Width), float(c.Height)])
    except Exception:
        try:
            vals = [float(c.Radius) * 2.0]
        except Exception:
            vals = []
    return shape, vals


def _profiles_differ(a, b, tol=1.0 / 192.0):
    sa, da = _profile(a)
    sb, db = _profile(b)
    if sa and sb and sa != sb:
        return True
    if len(da) != len(db):
        return True
    for x, y in zip(da, db):
        if abs(x - y) > tol:
            return True
    return False


def _shape_bucket(shape):
    """Normalize Revit/Fabrication connector shape text for transition tests.

    Fabrication databases do not always expose the exact same enum text between
    Revit releases/catalogs.  For square-to-round detection we only need the
    broad physical family, not the exact enum spelling.
    """
    low = str(shape or '').lower()
    if 'round' in low or 'circular' in low:
        return 'round'
    if 'rect' in low or 'square' in low or 'oval' in low:
        return 'rect'
    return ''


def _cross_shape_pair(conns):
    """True when two fitting connectors prove rect/square/oval <-> round."""
    if len(conns) != 2:
        return False
    sa, _da = _profile(conns[0])
    sb, _db = _profile(conns[1])
    ba = _shape_bucket(sa)
    bb = _shape_bucket(sb)
    return bool(ba and bb and ba != bb)


def _connected_straight_profile(elem, conn):
    """Best-effort profile of a straight physically connected to ``conn``.

    Some Fabrication square-to-round parts report connector orientation or even
    connector shape inconsistently.  The attached straight runs are a second,
    highly useful source of truth.
    """
    try:
        own_id = _eid_value(elem.Id)
    except Exception:
        own_id = None
    try:
        refs = conn.AllRefs
    except Exception:
        refs = []
    for r in refs:
        try:
            owner = r.Owner
            if owner is None:
                continue
            oid = _eid_value(owner.Id)
            if own_id is not None and oid == own_id:
                continue
            if _owner_straight_axis3d(owner) is None:
                continue
            oconns = _connectors(owner)
            if not oconns:
                continue
            best = None
            best_d = None
            for oc in oconns:
                try:
                    d = (oc.Origin - conn.Origin).GetLength()
                except Exception:
                    d = 1e99
                if best is None or d < best_d:
                    best = oc
                    best_d = d
            if best is not None:
                return _profile(best)
        except Exception:
            pass
    return ('', [])


def _connected_run_cross_shape(elem, conns):
    """True when attached straight runs prove square/rect/oval <-> round."""
    if len(conns) != 2:
        return False
    sa, _da = _connected_straight_profile(elem, conns[0])
    sb, _db = _connected_straight_profile(elem, conns[1])
    ba = _shape_bucket(sa)
    bb = _shape_bucket(sb)
    return bool(ba and bb and ba != bb)


def _cross_shape_transition(elem):
    """True when the fitting is a rect/square/oval <-> round profile change.

    v1.12 drafting rule: these fittings are still detected correctly, but they
    are intentionally excluded from *direct transition component tags* for
    ductwork.  The adjacent straight-run event engine remains responsible for
    size/BOD communication on each side of the profile change.
    """
    conns = _connectors(elem)
    if len(conns) != 2:
        return False
    return bool(_cross_shape_pair(conns) or _connected_run_cross_shape(elem, conns))


def _native_transition(elem):
    """Use the native PartType enum first; retain a string fallback."""
    try:
        mep = elem.MEPModel
        if mep is not None:
            pt = mep.PartType
            try:
                if pt == DB.PartType.Transition:
                    return True
            except Exception:
                pass
            if 'transition' in str(pt).lower():
                return True
    except Exception:
        pass
    return False


def _fab_identity_text(elem):
    parts = []
    for attr in ('PartType', 'ProductName', 'ProductShortDescription',
                 'ProductLongDescription', 'Alias', 'Name'):
        try:
            value = getattr(elem, attr)
            if value is not None:
                parts.append(str(value))
        except Exception:
            pass
    try:
        parts.append(str(elem.Category.Name))
    except Exception:
        pass
    return ' '.join(parts).lower()


def _owner_straight_axis3d(owner):
    """Best-effort 3D axis for a connected straight owner."""
    if owner is None:
        return None
    try:
        loc = owner.Location
        crv = getattr(loc, 'Curve', None)
        if isinstance(crv, DB.Line):
            return crv.Direction.Normalize()
    except Exception:
        pass
    try:
        if isinstance(owner, DB.FabricationPart):
            try:
                if not bool(owner.IsAStraight()):
                    return None
            except Exception:
                pass
            cs = _connectors(owner)
            best = None; best_d = -1.0
            for i in range(len(cs)):
                for j in range(i + 1, len(cs)):
                    try:
                        v = cs[j].Origin - cs[i].Origin
                        d = v.GetLength()
                        if d > best_d and d > 1e-6:
                            best = v.Normalize(); best_d = d
                    except Exception:
                        pass
            return best
    except Exception:
        pass
    return None


def _connected_owner_axis_veto(elem, conns):
    """Detect a cut-in branch even when HETO metadata is unhelpful.

    On a true transition, a straight connected at either end runs parallel to
    that transition connector.  At a HETO/takeoff's trunk-side connector the
    connected main is typically perpendicular/non-parallel to the branch axis.
    """
    try:
        own_id = _eid_value(elem.Id)
    except Exception:
        own_id = None
    for c in conns:
        try:
            ca = c.CoordinateSystem.BasisZ.Normalize()
        except Exception:
            continue
        try:
            refs = c.AllRefs
        except Exception:
            refs = []
        for r in refs:
            try:
                owner = r.Owner
                if owner is None:
                    continue
                oid = _eid_value(owner.Id)
                if own_id is not None and oid == own_id:
                    continue
                oa = _owner_straight_axis3d(owner)
                if oa is None:
                    continue
                if abs(float(ca.DotProduct(oa))) < 0.70:
                    return True
            except Exception:
                pass
    return False


def _fabrication_branch_fitting(elem):
    """True for branch/takeoff parts that must NEVER be transition-tagged.

    HETO-style Fabrication takeoffs are not consistently reported by IsATap()
    in every fabrication database.  Reject them through several independent
    signals BEFORE connector shape/size is considered.
    """
    try:
        if bool(elem.IsATap()):
            return True
    except Exception:
        pass

    # Fabrication PartType often exposes HETO-style parts as TapPerpendicular
    # or TapAdjustable even when IsATap() is false.  Match those enum names
    # explicitly; do not use a raw "tap" substring because "taper" is a real
    # transition keyword.
    try:
        pt = str(elem.PartType).lower()
    except Exception:
        pt = ''
    pt_compact = ''.join(ch for ch in pt if ch.isalnum())
    if any(word in pt_compact for word in (
            'tapperpendicular', 'tapadjustable', 'takeoff', 'heto',
            'tee', 'wye', 'branch', 'saddle', 'shoe', 'startcollar')):
        return True

    text = _fab_identity_text(elem)
    padded = ' {0} '.format(text)
    branch_words = (
        'takeoff', 'take-off', 'take off',
        'heto', 'high efficiency takeoff', 'high-efficiency takeoff',
        'high efficiency take-off', 'high-efficiency take-off',
        'tapperpendicular', 'tap perpendicular',
        'tapadjustable', 'tap adjustable',
        ' tap ', 'tap-', '-tap', 'spin-in', 'spin in',
        'tee', 'wye', 'branch', 'saddle', 'shoe',
        'start collar', 'starting collar'
    )
    if any(word in padded for word in branch_words):
        return True

    conns = _connectors(elem)
    if _connected_owner_axis_veto(elem, conns):
        return True

    # Square/rect/oval-to-round Fabrication transitions are a special case.
    # Certain databases expose the two fitting connector BasisZ vectors with
    # the same sign (or otherwise not perfectly opposing) even though both ends
    # are correctly attached inline to straight duct.  The old hard axis veto
    # rejected those legitimate transitions.  Metadata/tap checks above plus
    # the connected-owner alignment veto are still retained, so HETO/takeoff
    # parts do not get promoted merely because they also change profile shape.
    cross_shape = _cross_shape_pair(conns) or _connected_run_cross_shape(elem, conns)
    if cross_shape:
        return False

    # Same-shape fittings retain the strict straight-through geometry veto.
    if len(conns) == 2:
        try:
            a0 = conns[0].CoordinateSystem.BasisZ.Normalize()
            a1 = conns[1].CoordinateSystem.BasisZ.Normalize()
            if a0.DotProduct(a1) > -0.72:
                return True
        except Exception:
            pass

    return False


def _transition_axis(elem):
    """Best-effort centerline axis through a two-port transition fitting.

    Connector origin-to-origin geometry is more stable for this purpose than
    relying only on Fabrication BasisZ, which varies by database/catalog.
    """
    conns = _connectors(elem)
    if len(conns) != 2:
        return None
    try:
        v = conns[1].Origin - conns[0].Origin
        if v.GetLength() > 1e-5:
            return v.Normalize()
    except Exception:
        pass

    # Rare fallback for very short fittings whose connector origins collapse
    # to nearly the same point.  Require both connector axes to agree before
    # trusting BasisZ as the fitting axis.
    try:
        a0 = conns[0].CoordinateSystem.BasisZ.Normalize()
        a1 = conns[1].CoordinateSystem.BasisZ.Normalize()
        if abs(float(a0.DotProduct(a1))) >= 0.80:
            return a0
    except Exception:
        pass
    return None


def _transition_out_of_view_plane(elem, view, threshold=0.88):
    """True when a transition runs almost perpendicular to the view plane.

    In a floor/RCP this is the common vertical drop/rise condition.  Human duct
    plans communicate that condition with the rise/drop graphic plus the
    adjoining run/terminal annotation; a separate on-host transition tag adds
    clutter and is usually not useful.

    The test is view-relative rather than hard-coded to model Z, so a section
    or elevation can still tag the same fitting when its axis lies in that
    view's plane.  Only near-perpendicular fittings are suppressed so ordinary
    sloped/offset transitions remain eligible.
    """
    axis = _transition_axis(elem)
    if axis is None:
        return False
    try:
        vd = view.ViewDirection.Normalize()
        return abs(float(axis.DotProduct(vd))) >= float(threshold)
    except Exception:
        return False


def _fabrication_transition(elem):
    """Strict Fabrication transition/reducer detection.

    Branch fittings are explicitly excluded.  A cross-shape two-port fitting
    (rect/oval <-> round) is accepted from connector geometry.  Same-shape
    size changes are accepted only when the part identity itself says it is a
    transition/reducer/increaser/taper, preventing reducing elbows and taps
    from being mislabeled as transitions.
    """
    try:
        if bool(elem.IsAStraight()):
            return False
    except Exception:
        pass

    if _fabrication_branch_fitting(elem):
        return False

    conns = _connectors(elem)
    if len(conns) != 2:
        return False

    # Cross-profile duct transitions get a dedicated proof path.  We accept the
    # fitting when either its own connectors OR the two attached straight runs
    # prove square/rect/oval <-> round.  Do this before the legacy connector-axis
    # gate because some Fabrication catalogs report valid inline transition
    # connector BasisZ vectors as non-opposing.  _fabrication_branch_fitting()
    # has already rejected taps/HETOs/tees/wyes and owner-axis branch geometry.
    cross_shape = _cross_shape_pair(conns) or _connected_run_cross_shape(elem, conns)
    if cross_shape:
        return True

    # Same-shape reducers/transitions remain intentionally strict.
    try:
        a0 = conns[0].CoordinateSystem.BasisZ.Normalize()
        a1 = conns[1].CoordinateSystem.BasisZ.Normalize()
        if a0.DotProduct(a1) > -0.72:
            return False
    except Exception:
        pass

    if not _profiles_differ(conns[0], conns[1]):
        return False

    text = _fab_identity_text(elem)
    transition_words = (
        'transition', 'reducer', 'increaser', 'taper',
        'concentric', 'eccentric'
    )
    return any(word in text for word in transition_words)


def _center(elem, view):
    try:
        bb = elem.get_BoundingBox(view)
        if bb is not None:
            return DB.XYZ(
                (bb.Min.X + bb.Max.X) * 0.5,
                (bb.Min.Y + bb.Max.Y) * 0.5,
                (bb.Min.Z + bb.Max.Z) * 0.5,
            )
    except Exception:
        pass
    try:
        loc = elem.Location
        p = getattr(loc, 'Point', None)
        if p is not None:
            return p
    except Exception:
        pass
    return None


def _project_to_view_plane(point, view):
    """Keep direct tag heads on the owning view plane when possible."""
    if point is None:
        return None
    try:
        n = view.ViewDirection.Normalize()
        o = view.Origin
        d = (point - o).DotProduct(n)
        return point - n.Multiply(d)
    except Exception:
        return point


def _tagged_ids(tag):
    out = []
    try:
        for eid in tag.GetTaggedLocalElementIds():
            out.append(_eid_value(eid))
        return [x for x in out if x is not None]
    except Exception as ex:
        if _is_regeneration_failure(ex):
            raise
        pass
    try:
        for ref in tag.GetTaggedReferences():
            out.append(_eid_value(ref.ElementId))
    except Exception as ex:
        if _is_regeneration_failure(ex):
            raise
        pass
    return [x for x in out if x is not None]


def _tag_matches_component(tag, view, source_id, type_id):
    """Proof of the selected component annotation, not just any tag on a host."""
    try:
        return (tag is not None and not tag.IsOrphaned and
                _eid_value(tag.OwnerViewId) == _eid_value(view.Id) and
                _eid_value(tag.GetTypeId()) == int(type_id) and
                int(source_id) in _tagged_ids(tag))
    except Exception as ex:
        if _is_regeneration_failure(ex):
            raise
        return False


def _is_regeneration_failure(error):
    names = [type(error).__name__]
    try:
        names.append(str(error.GetType().FullName).split('.')[-1])
    except Exception:
        pass
    return any(name in ('RegenerationFailedException', 'ModificationForbiddenException') for name in names)


def _create_tag(doc, view, elem, tag_type_id, point):
    try:
        tid = DB.ElementId(System.Int64(tag_type_id))
    except Exception:
        tid = DB.ElementId(int(tag_type_id))
    ref = DB.Reference(elem)

    # Revit 2025 exposes the FamilySymbol-specific overload.  Prefer it because
    # it creates the requested type directly instead of relying on the current
    # category default and then changing type.
    try:
        return DB.IndependentTag.Create(
            doc, tid, view.Id, ref, False, DB.TagOrientation.Horizontal, point
        )
    except Exception as ex:
        if _is_regeneration_failure(ex):
            raise
        tag = DB.IndependentTag.Create(
            doc,
            view.Id,
            ref,
            False,
            DB.TagMode.TM_ADDBY_CATEGORY,
            DB.TagOrientation.Horizontal,
            point,
        )
        if tag.GetTypeId() != tid:
            replacement = tag.ChangeTypeId(tid)
            if replacement is not None and _eid_value(replacement) not in (None, -1):
                tag = doc.GetElement(replacement)
        return tag


def _collect(doc, view, bic_name):
    try:
        bic = getattr(DB.BuiltInCategory, bic_name)
        return list(
            DB.FilteredElementCollector(doc, view.Id)
            .OfCategory(bic)
            .WhereElementIsNotElementType()
        )
    except Exception as ex:
        if _is_regeneration_failure(ex):
            raise
        return []


def _transition_elements(doc, view, discipline, mode):
    if discipline == 'duct':
        if mode == 'fabrication':
            vals = _collect(doc, view, 'OST_FabricationDuctwork')
            # v1.12 temporary office-style rule: do not direct-tag any
            # square/rect/oval <-> round profile-change fitting.  These are
            # intentionally left to the adjacent straight-run size/BOD tags.
            # Same-profile reducers/transitions remain eligible.  Keep the
            # v1.11 out-of-view-plane filter for all remaining transitions.
            return [x for x in vals
                    if _fabrication_transition(x)
                    and not _cross_shape_transition(x)
                    and not _transition_out_of_view_plane(x, view)]
        vals = _collect(doc, view, 'OST_DuctFitting')
        return [x for x in vals
                if _native_transition(x)
                and not _cross_shape_transition(x)
                and not _transition_out_of_view_plane(x, view)]

    if mode == 'fabrication':
        vals = _collect(doc, view, 'OST_FabricationPipework')
        return [x for x in vals if _fabrication_transition(x)]
    vals = _collect(doc, view, 'OST_PipeFitting')
    return [x for x in vals if _native_transition(x)]


def _failure(stats, label, elem, message):
    stats['failed'] += 1
    if len(stats['failures']) < 12:
        try:
            eid = _eid_value(elem.Id)
        except Exception:
            eid = None
        stats['failures'].append((label, eid, str(message)))


def run_direct_component_tags(doc, view, uidoc, discipline, options, layout_handler=None):
    started = time.time()
    stats = {
        'created': 0,
        'skipped': 0,
        'failed': 0,
        'unmapped': 0,
        'runtime': 0.0,
        'by_category': {},
        'failures': [],
        'created_ids': [],
        'created_records': [],
        'post_commit_rejected': 0,
        'external_leader_layouts': 0,
    }
    comps = options.get('components', {})
    tag_types = options.get('tag_types', {})
    if not any(comps.values()):
        return stats

    selected = None
    if options.get('scope') == 'selection':
        try:
            selected = set(_eid_value(x) for x in uidoc.Selection.GetElementIds())
        except Exception:
            selected = set()

    jobs = []
    if comps.get('transition'):
        choice = tag_types.get('transition') or {}
        if choice.get('id') is None:
            elems = []
        else:
            elems = _transition_elements(doc, view, discipline, choice.get('mode', 'native'))
        jobs.append(('Transitions / reducers', elems, choice))

    if comps.get('terminal'):
        choice = tag_types.get('terminal') or {}
        if choice.get('id') is None:
            elems = []
        elif discipline == 'duct':
            elems = _collect(doc, view, 'OST_DuctTerminal')
        else:
            elems = _collect(doc, view, 'OST_PlumbingFixtures')
        jobs.append(
            ('Air terminals / diffusers' if discipline == 'duct' else 'Plumbing fixtures', elems, choice)
        )

    if comps.get('equipment'):
        choice = tag_types.get('equipment') or {}
        elems = _collect(doc, view, 'OST_MechanicalEquipment') if choice.get('id') is not None else []
        jobs.append(('Mechanical equipment', elems, choice))

    if comps.get('accessory'):
        choice = tag_types.get('accessory') or {}
        bic = 'OST_DuctAccessory' if discipline == 'duct' else 'OST_PipeAccessory'
        elems = _collect(doc, view, bic) if choice.get('id') is not None else []
        jobs.append(
            ('Duct accessories' if discipline == 'duct' else 'Pipe accessories / valves', elems, choice)
        )

    if comps.get('extra') and discipline == 'pipe':
        choice = tag_types.get('extra') or {}
        elems = _collect(doc, view, 'OST_PlumbingEquipment') if choice.get('id') is not None else []
        jobs.append(('Plumbing equipment', elems, choice))

    # Pipe duplicates require the selected type, source, view and a live tag.
    # Keep Duct's established any-tag-on-host component suppression unchanged.
    existing_any = set()
    existing_requested = set()
    try:
        for tag in (
            DB.FilteredElementCollector(doc, view.Id)
            .OfClass(DB.IndependentTag)
            .WhereElementIsNotElementType()
        ):
            for eid in _tagged_ids(tag):
                existing_any.add(eid)
                if discipline == 'pipe':
                    try:
                        type_id = _eid_value(tag.GetTypeId())
                        if _tag_matches_component(tag, view, eid, type_id):
                            existing_requested.add((eid, type_id))
                    except Exception as ex:
                        if _is_regeneration_failure(ex):
                            raise
                        pass
    except Exception as ex:
        if _is_regeneration_failure(ex):
            raise
        pass

    tx = DB.Transaction(doc, 'ROBMEPTOOLS AutoTag Components')
    tx.Start()
    try:
        for label, elems, choice in jobs:
            subtotal = {'created': 0, 'skipped': 0, 'failed': 0, 'unmapped': 0}
            tid = choice.get('id')
            if tid is None:
                if choice.get('skip'):
                    subtotal['skipped_by_mapping'] = 1
                else:
                    subtotal['unmapped'] = 1
                    stats['unmapped'] += 1
                stats['by_category'][label] = subtotal
                continue

            for elem in elems:
                eid = _eid_value(elem.Id)
                if selected is not None and eid not in selected:
                    continue
                already_tagged = ((eid, int(tid)) in existing_requested
                                  if discipline == 'pipe' else eid in existing_any)
                if already_tagged:
                    subtotal['skipped'] += 1
                    stats['skipped'] += 1
                    continue

                p = _project_to_view_plane(_center(elem, view), view)
                if p is None:
                    subtotal['failed'] += 1
                    _failure(stats, label, elem, 'No usable placement point')
                    continue

                st = None
                layout_record = None
                tag = None
                try:
                    if discipline == 'pipe' or layout_handler is not None:
                        st = DB.SubTransaction(doc)
                        st.Start()
                    tag = _create_tag(doc, view, elem, tid, p)
                    if (discipline == 'pipe' or layout_handler is not None) and not _tag_matches_component(tag, view, eid, tid):
                        raise ValueError('Created tag does not match selected type, source, and view.')
                    try:
                        tag.HasLeader = False
                    except Exception as ex:
                        if _is_regeneration_failure(ex):
                            raise
                        pass
                    if layout_handler is not None and label in (
                            'Air terminals / diffusers', 'Mechanical equipment'):
                        layout_record = layout_handler(tag, elem, label, p)
                        if not layout_record:
                            raise ValueError('No clear external component tag position.')
                    if st is not None:
                        st.Commit()
                    existing_any.add(eid)
                    existing_requested.add((eid, int(tid)))
                    subtotal['created'] += 1
                    stats['created'] += 1
                    if discipline == 'pipe' or layout_handler is not None:
                        record = {
                            'tag_id': _eid_value(tag.Id), 'source_id': eid,
                            'type_id': int(tid), 'category_label': label}
                        if layout_record:
                            record.update(layout_record)
                            stats['external_leader_layouts'] += 1
                        stats['created_records'].append(record)
                except Exception as ex:
                    if layout_record and layout_handler is not None:
                        layout_handler.release(_eid_value(tag.Id))
                    if st is not None:
                        try:
                            st.RollBack()
                        except Exception:
                            pass
                    if _is_regeneration_failure(ex):
                        raise
                    subtotal['failed'] += 1
                    _failure(stats, label, elem, ex)

            stats['by_category'][label] = subtotal
        tx.Commit()
    except Exception:
        try:
            tx.RollBack()
        except Exception:
            pass
        raise

    if discipline == 'pipe' or layout_handler is not None:
        surviving = []
        for record in stats['created_records']:
            try:
                tag = doc.GetElement(DB.ElementId(System.Int64(record['tag_id'])))
            except Exception as ex:
                if _is_regeneration_failure(ex):
                    raise
                tag = None
            if _tag_matches_component(tag, view, record['source_id'], record['type_id']):
                surviving.append(record)
            else:
                stats['created'] -= 1
                subtotal = stats['by_category'][record['category_label']]
                subtotal['created'] -= 1
                subtotal['failed'] += 1
                stats['failed'] += 1
                stats['post_commit_rejected'] += 1
                if layout_handler is not None:
                    layout_handler.release(record['tag_id'])
                    if record.get('has_leader'):
                        stats['external_leader_layouts'] -= 1
                stats['failures'].append((record['category_label'], record['source_id'],
                                          'Tag missing or wrong source/type after commit'))
        stats['created_records'] = surviving
        stats['created_ids'] = [record['tag_id'] for record in surviving]

    stats['runtime'] = time.time() - started
    return stats


def component_summary(stats):
    if not stats or not stats.get('by_category'):
        return ''
    lines = ['Direct component tags:']
    for label in sorted(stats['by_category'].keys()):
        s = stats['by_category'][label]
        if s.get('skipped_by_mapping', 0):
            lines.append('  {0}: skipped by Tag Types mapping'.format(label))
        elif s.get('unmapped', 0):
            lines.append('  {0}: skipped - no compatible loaded tag type selected'.format(label))
        else:
            lines.append(
                '  {0}: {1} created | {2} already tagged | {3} failed'.format(
                    label, s.get('created', 0), s.get('skipped', 0), s.get('failed', 0)
                )
            )
    if stats.get('failures'):
        label, eid, reason = stats['failures'][0]
        lines.append('  First component failure: {0} [{1}] - {2}'.format(label, eid, reason))
    lines.append('  Component tagging runtime: {0:.1f}s'.format(stats.get('runtime', 0.0)))
    return '\n'.join(lines)
