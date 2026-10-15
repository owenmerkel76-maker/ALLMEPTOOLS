# -*- coding: utf-8 -*-
"""Per-run linked rod clearance checks; no planner or attachment decisions.

MEP boxes are conservative *potential* clashes. Other imported/structural
geometry is rejected only on an actual Solid/Mesh path intersection, or on an
unreadable local candidate that cannot establish clearance. All feet and
coordinates supplied to ``check`` are in the host document. Autodesk imports
are lazy so this deployed helper can also be exercised with offline doubles.
"""

import math
import re


try:
    text_type = unicode
except NameError:
    text_type = str


def _text(value):
    """Keep Revit/.NET and IFC labels Unicode under IronPython 2."""
    try:
        return text_type(value)
    except UnicodeError:
        try:
            return value.decode('utf-8', 'replace')
        except Exception:
            return u'(unreadable text)'


_MEP_CATEGORIES = (
    'OST_FabricationDuctwork', 'OST_FabricationPipework',
    'OST_DuctCurves', 'OST_PipeCurves', 'OST_FlexDuctCurves',
    'OST_FlexPipeCurves', 'OST_DuctFitting', 'OST_PipeFitting',
    'OST_DuctAccessory', 'OST_PipeAccessory', 'OST_MechanicalEquipment',
    'OST_DuctTerminal', 'OST_PlumbingFixtures', 'OST_Sprinklers',
    'OST_CableTray', 'OST_CableTrayFitting', 'OST_Conduit', 'OST_ConduitFitting')
_GEOMETRY_CATEGORIES = (
    'OST_StructuralFraming', 'OST_StructuralColumns', 'OST_Columns',
    'OST_Floors', 'OST_Roofs', 'OST_StructuralFoundation', 'OST_Walls',
    'OST_Ceilings', 'OST_Stairs', 'OST_GenericModel')
_METADATA_PARAMETERS = (
    'IfcEntity', 'IfcExportAs', 'IfcType', 'IfcName', 'IFC Export As',
    'IFC Class', 'IFC Entity', 'IFC Type', 'IFC Classification',
    'IfcObjectType', 'ObjectType', 'Description', 'Type Comments')
_MEP_IFC = ('ifcflowsegment', 'ifcflowfitting', 'ifcflowcontroller',
            'ifcflowterminal', 'ifcflowmovingdevice', 'ifcflowstoragedevice',
            'ifcflowtreatmentdevice', 'ifcenergyconversiondevice',
            'ifcdistributionelement', 'ifcductsegment', 'ifcpipesegment',
            'ifcductfitting', 'ifcpipefitting')
_GEOMETRY_IFC = ('ifcbeam', 'ifcmember', 'ifccolumn', 'ifcslab',
                 'ifcroof', 'ifcplate', 'ifcwall', 'ifcfooting',
                 'ifcbuildingelementproxy', 'ifcproxy', 'ifcstair', 'ifcramp')
_MEP_WORDS = re.compile(r'\b(duct(?:work)?|pipe(?:work)?|piping|diffuser|'
                        r'sprinkler|air\s+terminal|mechanical\s+equipment|'
                        r'air\s+handling|ahu|vav|fan\s+coil|conduit|cable\s+tray)\b',
                        re.I)


def _eid(value):
    try:
        return int(value.Value)
    except Exception:
        try:
            return int(value.IntegerValue)
        except Exception:
            return int(value)


def _point(value):
    try:
        result = (float(value.X), float(value.Y), float(value.Z))
    except AttributeError:
        result = tuple(float(value[i]) for i in range(3))
    if any(math.isnan(v) or math.isinf(v) for v in result):
        raise ValueError('non-finite rod coordinates')
    return result


def _xyz(value):
    from Autodesk.Revit.DB import XYZ
    return XYZ(*_point(value))


def _box_overlap(a, b, padding=0.):
    return all(a[i] <= b[i + 3] + padding and b[i] <= a[i + 3] + padding
               for i in range(3))


def _path_box(a, b, padding=0.):
    return tuple(min(a[i], b[i]) - padding for i in range(3)) + tuple(
        max(a[i], b[i]) + padding for i in range(3))


def _inset(a, b, distance, from_end=False):
    delta = tuple(b[i] - a[i] for i in range(3))
    length = math.sqrt(sum(v * v for v in delta))
    fraction = min(distance / length, .1) if length else 0.
    if from_end:
        return tuple(b[i] - delta[i] * fraction for i in range(3))
    return tuple(a[i] + delta[i] * fraction for i in range(3))


def world_bbox(element, link_transform):
    """All eight corners: element bbox transform, then link-to-host transform."""
    try:
        box = element.get_BoundingBox(None)
        if box is None:
            return None
        points = []
        for x in (box.Min.X, box.Max.X):
            for y in (box.Min.Y, box.Max.Y):
                for z in (box.Min.Z, box.Max.Z):
                    point = _xyz((x, y, z))
                    point = box.Transform.OfPoint(point)
                    if link_transform is not None:
                        point = link_transform.OfPoint(point)
                    points.append(_point(point))
        if not points:
            return None
        return tuple(min(p[i] for p in points) for i in range(3)) + tuple(
            max(p[i] for p in points) for i in range(3))
    except Exception:
        return None


def _category_sets():
    from Autodesk.Revit.DB import BuiltInCategory, ElementId
    result = []
    for names in (_MEP_CATEGORIES, _GEOMETRY_CATEGORIES):
        numbers = set()
        for name in names:
            try:
                numbers.add(_eid(ElementId(getattr(BuiltInCategory, name))))
            except Exception:
                pass
        result.append(numbers)
    return result


def _category(element):
    try:
        return _eid(element.Category.Id), _text(element.Category.Name)
    except Exception:
        return None, '(uncategorized)'


def _metadata_text(element, document):
    """Read classification/name metadata, including type-level IFC properties."""
    objects = [element]
    try:
        typ = document.GetElement(element.GetTypeId())
        if typ is not None:
            objects.append(typ)
    except Exception:
        pass
    parts = []
    for obj in objects:
        for name in ('Name', 'FamilyName'):
            try:
                value = getattr(obj, name)
                if value:
                    parts.append(_text(value))
            except Exception:
                pass
        for name in _METADATA_PARAMETERS:
            try:
                param = obj.LookupParameter(name)
                if param is not None:
                    value = param.AsString() or param.AsValueString()
                    if value:
                        parts.append(_text(value))
            except Exception:
                pass
        # Exporters also prefix or rename IFC class parameters. Do not rely
        # solely on one localized parameter spelling.
        try:
            for param in obj.Parameters:
                if 'ifc' in _text(param.Definition.Name).lower():
                    value = param.AsString() or param.AsValueString()
                    if value:
                        parts.append(_text(value))
        except Exception:
            pass
    return u' '.join(parts).lower()


def obstacle_kind(category_id, metadata, mep_categories, geometry_categories):
    """Generic models are geometry candidates, never automatically known MEP."""
    text = _text(metadata or u'').lower()
    if category_id in mep_categories or any(name in text for name in _MEP_IFC):
        return 'mep'
    is_proxy = 'ifcbuildingelementproxy' in text or 'ifcproxy' in text
    if is_proxy and _MEP_WORDS.search(text):
        return 'mep'
    if category_id in geometry_categories or any(name in text for name in _GEOMETRY_IFC):
        return 'geometry'
    return None


def _loaded_links(document):
    from Autodesk.Revit.DB import FilteredElementCollector, RevitLinkInstance
    return FilteredElementCollector(document).OfClass(RevitLinkInstance)


def _linked_elements(document):
    from Autodesk.Revit.DB import FilteredElementCollector
    return FilteredElementCollector(document).WhereElementIsNotElementType()


def _is_import_geometry(element):
    try:
        name = _text(element.GetType().Name)
    except Exception:
        name = type(element).__name__
    return name in ('DirectShape', 'ImportInstance')


def _runtime_type(element):
    try:
        return _text(element.GetType().Name)
    except Exception:
        return _text(type(element).__name__)


_REFERENCE_DB = None
_REFERENCE_TYPES = ()


def _reference_types():
    # Revit classes are immutable for the process; avoid repeated .NET class
    # resolution for every object in a large coordination document.
    global _REFERENCE_DB, _REFERENCE_TYPES
    try:
        import Autodesk.Revit.DB as db
        if _REFERENCE_DB is not db:
            names = ('DatumPlane', 'CurveElement', 'Sketch', 'SketchPlane', 'View',
                     'DataStorage', 'BasePoint', 'InternalOrigin', 'ReferencePoint',
                     'ProjectInfo', 'ProjectLocation', 'SiteLocation', 'Material',
                     'ParameterElement', 'GlobalParameter', 'PropertySetElement',
                     'AppearanceAssetElement', 'GraphicsStyle', 'LinePatternElement',
                     'FillPatternElement', 'Group', 'AssemblyInstance',
                     'RevitLinkInstance')
            _REFERENCE_TYPES = tuple(cls for cls in
                (getattr(db, name, None) for name in names) if cls is not None)
            _REFERENCE_DB = db
        return _REFERENCE_TYPES
    except Exception:
        return ()


def _reference_reason(element):
    """Positive Revit reference identity, never a filename or missing box."""
    if bool(getattr(element, 'ViewSpecific', False)):
        return 'view-specific reference'
    try:
        category_type = _text(element.Category.CategoryType).lower()
        if category_type in ('annotation', 'analyticalmodel'):
            return 'annotation/analytical reference'
    except Exception:
        pass
    # Containers and link instances are not physical members. Their actual
    # model members/direct linked documents are inventoried separately.
    try:
        types = _reference_types()
        if types and isinstance(element, types):
            return 'Revit reference/container: ' + _runtime_type(element)
    except Exception:
        pass
    return None


def _geometry_content(element):
    """Classify evidence for reference review; unreadable never means empty."""
    try:
        from Autodesk.Revit.DB import (Options, Curve, PolyLine, Point,
                                        GeometryInstance, Solid, Mesh)
        options = Options()
        try:
            from Autodesk.Revit.DB import ViewDetailLevel
            options.DetailLevel = ViewDetailLevel.Fine
        except ImportError:
            pass
        options.IncludeNonVisibleObjects = False
        geometry = element.get_Geometry(options)
    except Exception:
        return 'unknown'

    def inspect(items, depth=0):
        if items is None or depth>16:
            return False,0,True
        physical=False; count=0; failed=False
        try:
            for item in items:
                if isinstance(item, (Solid,Mesh)):
                    physical=True
                elif isinstance(item, GeometryInstance):
                    try:
                        found,nested,bad=inspect(item.GetInstanceGeometry(),depth+1)
                        physical=physical or found
                        count+=nested
                        failed=failed or bad
                    except Exception:
                        failed=True
                elif isinstance(item, (Curve,PolyLine,Point)):
                    count+=1
                else:
                    failed=True
        except Exception:
            failed=True
        return physical,count,failed
    physical,count,failed=inspect(geometry)
    if physical:
        return 'physical'
    return 'reference' if count>0 and not failed else 'unknown'


def _reference_geometry(element):
    return _geometry_content(element)=='reference'


def _intersection(element, start, end, transform, host_base):
    import rod_geometry
    return rod_geometry._intersection_result(element, start, end, transform, host_base)


def _matches_endpoint(target, candidate, path_index, tip):
    """Exact element AND link instance; a same-ID member in another link stays."""
    if target.get('index') != path_index:
        return False
    try:
        if _eid(target.get('id')) != candidate['id']:
            return False
        if candidate['link_id'] is None:
            # An explicit native identity is required; absent link information
            # must not accidentally exempt a same-ID host element.
            if target.get('link_id') is not None:
                return False
            if not ('link_id' in target or target.get('source_key') == 'HOST'):
                return False
        elif target.get('link_id') is not None:
            if _eid(target['link_id']) != candidate['link_id']:
                return False
        elif target.get('source_key'):
            if _text(target['source_key']) != candidate['source_key']:
                return False
        else:
            return False
        return abs(float(target['z']) - tip[2]) <= .01
    except Exception:
        return False


class LinkedObstructionChecker(object):
    """Cache one immutable obstacle inventory for one Auto Hanger run only.

    An unloaded link is recorded in ``warnings``; its absent geometry is never
    advertised as evaluated. The structural picker handles missing approved
    structure. Loaded unreadable sources instead reject checks explicitly.
    """

    def __init__(self, doc, structural_sources=None):
        self.doc = doc
        self.candidates = None
        self.warnings = []
        self.failures = []
        self.focused = structural_sources is not None
        self.approved_native = set()
        self.approved_by_link = {}
        self.reference_skips = {}
        self._reference_audits = set()
        self.reference_examples = []
        self.reviewable = set()
        self.reviewed_examples = []
        self.generic_category_id = None
        try:
            from Autodesk.Revit.DB import BuiltInCategory, ElementId
            self.generic_category_id = _eid(ElementId(BuiltInCategory.OST_GenericModel))
        except Exception:
            pass
        for source in structural_sources or []:
            if source.link_id is None:
                self.approved_native.update(source.preferred)
                self.approved_native.update(source.fallback)
            else:
                approved = self.approved_by_link.setdefault(source.link_id, set())
                approved.update(source.preferred)
                approved.update(source.fallback)

    def _record_reference(self, name, reason):
        key=(name,reason)
        self.reference_skips[key]=self.reference_skips.get(key,0)+1

    def reference_notes(self):
        totals={}
        details=[]
        for (name,reason),count in sorted(self.reference_skips.items()):
            if reason.startswith('Revit reference/container:') or reason in (
                    'view-specific reference','annotation/analytical reference'):
                totals[name]=totals.get(name,0)+count
                if reason.endswith('GraphicsStyle'):
                    details.append(u'Clearance display definitions: {} / GraphicsStyle: {} excluded.'
                                   .format(name,count))
            else:
                details.append(u'Clearance reference filter: {} / {}: {} objects excluded.'
                               .format(name,reason,count))
        summary=[u'Clearance reference filter: {} / {} proven reference, annotation or '
                 u'definition objects omitted; physical MEP and structural checks remain active.'
                 .format(name,count) for name,count in sorted(totals.items())]
        return summary+details+list(self.reference_examples)+list(self.reviewed_examples)

    def _audit_reference(self, candidate):
        key=(candidate['link_id'],candidate['id'])
        if key not in self._reference_audits:
            self._reference_audits.add(key)
            state=_geometry_content(candidate['element'])
            candidate['geometry_content']=state
            if state=='reference':
                candidate['reference_only']=True
                self._record_reference(candidate['link_name'],
                    'readable curve/point-only import or uncategorized object')
                if len(self.reference_examples)<8:
                    self.reference_examples.append(u'Clearance reference example: {} / {} '
                        u'element {} / Revit class {} has fully readable curves/points only.'
                        .format(candidate['link_name'],candidate['category'],
                                candidate['id'],candidate['runtime_type']))
        return candidate.get('geometry_content','unknown')

    def reference_review_candidates(self, progress=None):
        """Offer only ambiguous UNREADABLE objects for explicit run-only review.

        Known physical categories, MEP, approved targets and any readable
        Solid/Mesh are ineligible. Offering unreadable candidates does not
        classify them as references.
        """
        self._gather()
        eligible=[candidate for candidate in self.candidates
                  if candidate.get('reference_audit')]
        rows=[]
        for index,candidate in enumerate(eligible):
            if progress is not None:
                progress(index,len(eligible))
            if self._audit_reference(candidate)!='unknown':
                continue
            key=(candidate['link_id'],candidate['id'])
            self.reviewable.add(key)
            try:
                label=_text(candidate['element'].Name)
            except Exception:
                label=candidate['category']
            rows.append({'key':key,'label':u'{} | {} | {} | {} | ID {}'.format(
                candidate['link_name'],label,candidate['category'],
                candidate['runtime_type'],candidate['id'])})
        if progress is not None:
            progress(len(eligible),len(eligible))
        return rows

    def apply_reference_review(self, keys):
        """Apply deliberate classifications only to this checker/execution."""
        requested=set(keys)
        if not requested.issubset(self.reviewable):
            raise ValueError('Reference review cannot exclude physical or unreviewed candidates')
        for candidate in self.candidates:
            key=(candidate['link_id'],candidate['id'])
            if key not in requested or candidate.get('reviewed_reference'):
                continue
            candidate['reviewed_reference']=True
            self._record_reference(candidate['link_name'],
                'USER REVIEWED as drawing/coordination reference for this run only')
            self.reviewed_examples.append(u'USER REVIEWED reference scope: {} / {} / '
                u'Revit class {} / element {}; excluded from clearance this run by user classification.'
                .format(candidate['link_name'],candidate['category'],
                        candidate['runtime_type'],candidate['id']))

    def prepare(self):
        """Read the inventory before placement so warnings/failures are visible.

        Safe to repeat: preparation only reads documents and caches this run's
        candidates. ``check`` still prepares lazily for standalone callers.
        """
        self._gather()
        return self

    def _gather(self):
        if self.candidates is not None:
            return
        self.candidates = []
        try:
            mep_categories, geometry_categories = _category_sets()
            links = list(_loaded_links(self.doc))
        except Exception as ex:
            self.failures.append(u'Linked rod clearance inventory unavailable: {}'.format(_text(ex)))
            return
        # Native structural objects can also obstruct a rod that is targeted
        # to a higher linked beam. Existing native MEP checks are retained by
        # the caller; only non-MEP native categories/imported IFC objects are
        # added here, using the same exact geometric clearance test.
        try:
            self._gather_document(self.doc, None, 'HOST', 'host model', None,
                                  None, mep_categories, geometry_categories,
                                  native=True)
        except Exception as ex:
            self.failures.append(u'Native structural rod clearance inventory unavailable: {}'.format(_text(ex)))
        for link in links:
            try:
                link_id = _eid(link.Id)
                link_name = _text(link.Name)
            except Exception:
                link_id, link_name = None, '(unnamed linked model)'
            try:
                document = link.GetLinkDocument()
                if document is None:
                    self.warnings.append(u'Linked model {} is unloaded; its clearance geometry was not checked'.format(link_name))
                    continue
                transform = link.GetTotalTransform()
                inverse = transform.Inverse
                source_key = _text(getattr(link, 'UniqueId', '') or link_id)
                self._gather_document(document, link_id, source_key, link_name,
                    transform, inverse, mep_categories, geometry_categories)
            except Exception as ex:
                self.failures.append(u'Linked rod clearance inventory unavailable for {}: {}'.format(link_name, _text(ex)))

    def _gather_document(self, document, link_id, source_key, name, transform,
                         inverse, mep_categories, geometry_categories, native=False):
        for element in _linked_elements(document):
            reason = _reference_reason(element)
            if reason:
                self._record_reference(name, reason)
                continue
            category_id, category_name = _category(element)
            if native and category_id in mep_categories:
                continue
            metadata = _metadata_text(element, document)
            if native and self.focused and ((self.generic_category_id is not None and
                    category_id == self.generic_category_id) or
                    category_name.lower() in ('generic models', 'generic model')):
                known_ifc = any(token in metadata for token in
                    ('ifcbeam','ifcmember','ifccolumn','ifcslab','ifcroof','ifcplate'))
                if _eid(element.Id) not in self.approved_native and not known_ifc:
                    continue
            kind = obstacle_kind(category_id, metadata,
                                 mep_categories, geometry_categories)
            if kind is None and _is_import_geometry(element):
                kind = 'geometry'
            if kind is None:
                continue
            element_id = _eid(element.Id)
            approved = element_id in (self.approved_native if native else
                                       self.approved_by_link.get(link_id, set()))
            # Audit only ambiguous imports/uncategorized objects. Physical
            # categories, known IFC structure/MEP and approved targets retain
            # fail-closed behavior, including unsupported representations.
            strong_ifc = any(token in metadata for token in
                _MEP_IFC + tuple(token for token in _GEOMETRY_IFC
                                 if token not in ('ifcproxy','ifcbuildingelementproxy')))
            reference_audit = (not approved and not strong_ifc and kind != 'mep'
                               and category_id not in geometry_categories
                               and (_is_import_geometry(element) or category_id is None))
            self.candidates.append({
                'element': element, 'id': _eid(element.Id), 'link_id': link_id,
                'source_key': source_key, 'link_name': name,
                'category': category_name, 'kind': kind, 'transform': transform,
                'inverse': inverse, 'box': world_bbox(element, transform),
                'runtime_type': _runtime_type(element),
                'reference_audit': reference_audit, 'reference_only': False})

    def check(self, paths, approved_targets=None, host_id=None):
        """Return diagnostics; empty list means loaded inventory passed checks.

        ``paths`` contains {index, base, tip}, each point XYZ or 3-tuple in host
        coordinates. An approved target exempts only its precise endpoint,
        never the member's body or a different link with the same ElementId.
        """
        self._gather()
        diagnostics = list(self.failures)
        targets = approved_targets or []
        for path in paths:
            index = path.get('index', '?')
            try:
                base, tip = _point(path['base']), _point(path['tip'])
                if tip[2] <= base[2] or math.sqrt(sum((tip[i] - base[i]) ** 2 for i in range(3))) < .02:
                    raise ValueError('rod path is not a valid upward segment')
                start = _inset(base, tip, .01)
            except Exception as ex:
                diagnostics.append(u'Rod {} linked clearance path unavailable: {}'.format(index, _text(ex)))
                continue
            for candidate in self.candidates:
                if candidate.get('reference_only') or candidate.get('reviewed_reference'):
                    continue
                if candidate['link_id'] is None and host_id is not None and candidate['id'] == _eid(host_id):
                    continue
                scope = 'native' if candidate['link_id'] is None else 'linked'
                name = u'{} / {} element {}'.format(candidate['link_name'],
                                                    candidate['category'], candidate['id'])
                if candidate['kind'] == 'mep' and candidate['box'] is not None:
                    if _box_overlap(_path_box(start, tip, .10), candidate['box']):
                        diagnostics.append(u'Rod {} potential {} MEP clash with {} (bounding-box screening; verify in 3D)'.format(index, scope, name))
                    continue
                end = tip
                if any(_matches_endpoint(row, candidate, index, tip) for row in targets):
                    end = _inset(start, tip, .005, from_end=True)
                if candidate['box'] is not None and not _box_overlap(_path_box(start, end), candidate['box'], .001):
                    continue
                try:
                    local_start, local_end = _xyz(start), _xyz(end)
                    if candidate['inverse'] is not None:
                        local_start = candidate['inverse'].OfPoint(local_start)
                        local_end = candidate['inverse'].OfPoint(local_end)
                    state, height = _intersection(candidate['element'], local_start,
                        local_end, candidate['transform'], start[2])
                except Exception:
                    state, height = 'unknown', None
                if state == 'hit':
                    diagnostics.append(u'Rod {} intersects {} obstructing geometry {} (actual Solid/Mesh path intersection)'.format(index, scope, name))
                elif state != 'miss':
                    if candidate.get('reference_audit'):
                        self._audit_reference(candidate)
                    if candidate.get('reference_only'):
                        continue
                    location = 'intersecting bounding box' if candidate['box'] is not None else 'no readable bounding box'
                    diagnostics.append(u'Rod {} potential {} blockage at {} ({}; Revit class {}; geometry unavailable, clearance unverified)'.format(index, scope, name, location, candidate.get('runtime_type','unknown')))
        return diagnostics


def check_linked_paths(doc, paths, approved_targets=None, host_id=None):
    """Convenience API; use ``LinkedObstructionChecker`` to cache a whole run.

    ``host_id`` belongs to the HOST document, so it cannot exempt linked
    elements merely because their independent document IDs happen to match.
    """
    return LinkedObstructionChecker(doc).check(paths, approved_targets, host_id)
