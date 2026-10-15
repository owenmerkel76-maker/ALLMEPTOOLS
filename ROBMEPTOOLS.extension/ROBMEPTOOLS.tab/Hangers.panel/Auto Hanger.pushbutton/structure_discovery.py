# -*- coding: utf-8 -*-
"""Reviewable structure inventory; discovery never grants target approval.

The module imports Revit only inside discovery, so metadata normalization and
coordinate fingerprints can be exercised by offline tests. Geometry is screened
with element bounds here; actual rod intersections belong to structure_priority.
"""
import hashlib
import json
import os
import re
import uuid

import structure_catalog as catalog

_SESSION = str(uuid.uuid4())
_IFC_PARAMETERS = ('IfcEntity', 'IfcExportAs', 'IfcType', 'IfcName',
                   'IfcObjectType', 'IFC Object Type', 'ObjectType',
                   'IFC Export As', 'IFC Class', 'IFC Entity', 'IfcGUID',
                   'IFC GUID', 'IfcGlobalId', 'GlobalId', 'IFC Predefined Type')
_PROFILE_PARAMETERS = ('Structural Section Name', 'Section Name', 'Profile',
                       'Profile Name', 'IfcProfile', 'Type Comments',
                       'Description')
_PROFILE_PATTERN = re.compile(
    r'\b(?:HSS|MC|WT|ST|MT|HP|TS|W|S|M|C|L)\s*\d[\d./]*'
    r'(?:\s*x\s*\d[\d./]*){1,3}\b|\b\d+(?:\.\d+)?(?:DLH|LH|K)\d+\b', re.I)


def eidnum(value):
    try:
        return int(value.Value)
    except Exception:
        try:
            return int(value.IntegerValue)
        except Exception:
            return int(value)


def _text(value):
    try:
        return unicode(value).strip()
    except NameError:
        return str(value).strip()
    except Exception:
        return ''


def _attr(obj, name, default=''):
    try:
        value = getattr(obj, name)
        return default if value is None else value
    except Exception:
        return default


def _element_name(element):
    if element is None:
        return ''
    value = _attr(element, 'Name')
    if value:
        return _text(value)
    # ElementType.Name can expose only the setter to IronPython because the
    # derived .NET type shadows Element.Name. Read the base property explicitly.
    try:
        from Autodesk.Revit.DB import Element
        return _text(Element.Name.GetValue(element))
    except Exception:
        return ''


def _parameter_value(parameter):
    for method in ('AsString', 'AsValueString'):
        try:
            value = getattr(parameter, method)()
            if value:
                return _text(value)
        except Exception:
            pass
    return ''


def metadata_values(element):
    """Read classification/section fields from an instance OR its type.

    IFC exporters use both named shared parameters and differently named IFC
    property fields. Only classifier/profile fields are inspected; arbitrary
    parameter dumps are deliberately avoided.
    """
    result = {}
    try:
        parameters = list(element.Parameters)
    except Exception:
        parameters = None
    if parameters is None:
        # Some imported representations expose named fields only.
        for name in _IFC_PARAMETERS + _PROFILE_PARAMETERS:
            try:
                value = _parameter_value(element.LookupParameter(name))
                if value:
                    result[name] = value
            except Exception:
                pass
        return result
    # One parameter pass replaces dozens of repeated Revit LookupParameter
    # searches per object. Keep exporter-specific classifier names supported.
    for parameter in parameters:
        name = _text(_attr(_attr(parameter, 'Definition', None), 'Name'))
        normalized = name.lower().replace(' ', '').replace('_', '')
        if (name in _IFC_PARAMETERS + _PROFILE_PARAMETERS or
            ('ifc' in normalized and any(word in normalized for word in
             ('class', 'entity', 'exportas', 'type', 'name', 'guid', 'globalid', 'profile')))):
            value = _parameter_value(parameter)
            if value:
                result[name] = value
    return result


def has_ifc_metadata(metadata):
    neutral = ('default', 'notdefined', 'undefined', 'none', '<none>', 'null', '-', '')
    return any(('ifc' in name.lower() or name.lower().replace(' ', '') == 'globalid')
               and _text(value).lower().replace(' ', '') not in neutral
               for name, value in metadata.items())


def profile_hint(*values):
    """Recognizable section/joist tokens, not arbitrary instance names or IDs."""
    for value in values:
        match = _PROFILE_PATTERN.search(_text(value))
        if match:
            return re.sub(r'\s+', '', match.group(0)).upper()
    return ''


def exporter_type_hint(metadata):
    for name in ('IfcObjectType', 'IFC Object Type', 'ObjectType', 'IfcType'):
        value = metadata.get(name, '')
        if value and not re.match(r'^ifc[a-z0-9_]+$', value.strip(), re.I):
            return value
    return ''


def record_for(element, doc, type_cache=None):
    """Build a stable metadata record without requesting tessellated geometry."""
    try:
        type_id = element.GetTypeId()
        type_key = eidnum(type_id)
    except Exception:
        type_id, type_key = None, -1
    element_type = None
    if type_cache is None or type_key not in type_cache:
        try:
            element_type = doc.GetElement(type_id)
        except Exception:
            pass
    instance_metadata = metadata_values(element)
    if type_cache is not None and type_key >= 0:
        if type_key not in type_cache:
            type_cache[type_key] = (metadata_values(element_type) if element_type else {},
                                   _element_name(element_type),
                                   _text(_attr(element_type, 'FamilyName')))
        type_metadata, cached_name, cached_family = type_cache[type_key]
    else:
        type_metadata = metadata_values(element_type) if element_type else {}
        cached_name = _element_name(element_type)
        cached_family = _text(_attr(element_type, 'FamilyName'))
    metadata = dict(type_metadata)
    metadata.update(instance_metadata)
    category = _attr(element, 'Category', None)
    category_name = _text(_attr(category, 'Name', 'Uncategorized geometry'))
    try:
        category_key = str(eidnum(category.Id))
    except Exception:
        category_key = category_name.lower()
    ifc_guid = ''
    for name in ('IfcGUID', 'IFC GUID', 'IfcGlobalId', 'GlobalId'):
        if metadata.get(name):
            ifc_guid = metadata[name]
            break
    profile = ''
    # Free-text instance notes are not structural profiles. Using a unique
    # Description for each beam previously created thousands of WPF type rows.
    for name in _PROFILE_PARAMETERS[:5]:
        if metadata.get(name):
            profile = metadata[name]
            break
    if not profile:
        for name, value in metadata.items():
            if 'profile' in name.lower() or 'section name' in name.lower():
                profile = value
                break
    instance_name = _element_name(element)
    type_name = cached_name or exporter_type_hint(metadata)
    if not profile:
        profile = profile_hint(type_name, metadata.get('IfcName', ''), instance_name,
                               metadata.get('Type Comments', ''), metadata.get('Description', ''))
    record = {'id': eidnum(element.Id),
              'unique_id': _text(_attr(element, 'UniqueId')),
              'ifc_guid': ifc_guid,
              'name': instance_name,
              'category': category_name,
              'category_key': category_key,
              'type_name': type_name,
              'family': cached_family,
              'profile': profile,
              'ifc_metadata': metadata,
              'element': element}
    classified = catalog.classify_metadata(record)
    if isinstance(classified, dict):
        record.update(classified)
    else:
        record['ifc_class'] = classified or ''
    try:
        bounds = element.get_BoundingBox(None)
        record['geometry_signature'] = [
            [round(float(getattr(point, axis)), 8) for axis in ('X', 'Y', 'Z')]
            for point in (bounds.Min, bounds.Max)] + [transform_values(bounds.Transform)]
    except Exception:
        record['geometry_signature'] = []
    return record


def transform_values(transform):
    """A reload/moved-link signature, including origin and all three bases."""
    if transform is None:
        return []
    result = []
    for name in ('Origin', 'BasisX', 'BasisY', 'BasisZ'):
        vector = _attr(transform, name, None)
        for axis in ('X', 'Y', 'Z'):
            try:
                result.append(round(float(getattr(vector, axis)), 9))
            except Exception:
                result.append(None)
    return result


def _document_identity(doc):
    result = {'path': _text(_attr(doc, 'PathName'))}
    try:
        cloud = doc.GetCloudModelPath()
        result['cloud_project_guid'] = _text(cloud.GetProjectGUID())
        result['cloud_model_guid'] = _text(cloud.GetModelGUID())
    except Exception:
        pass
    try:
        from Autodesk.Revit.DB import WorksharingUtils
        guid = WorksharingUtils.GetCentralGUID(doc)
        if _text(guid) != '00000000-0000-0000-0000-000000000000':
            result['central_guid'] = _text(guid)
    except Exception:
        pass
    return result


def project_identity(doc):
    result = _document_identity(doc)
    try:
        session_doc = str(doc.GetHashCode())
    except Exception:
        session_doc = str(id(doc))
    result['session_id'] = _SESSION + ':' + session_doc
    return result


def _document_version(doc):
    try:
        version = doc.GetDocumentVersion()
        return [_text(version.VersionGUID), int(version.NumberOfSaves)]
    except Exception:
        return []


def fingerprint(doc, records, transform=None, include_version=True):
    payload = [catalog.fingerprint_records(records), _document_version(doc) if include_version else [],
               transform_values(transform),
               sorted((catalog.element_token(record), record.get('geometry_signature', []))
                      for record in records)]
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest()


def _link_reference(doc, link):
    try:
        from Autodesk.Revit.DB import ExternalFileUtils, ModelPathUtils
        reference = ExternalFileUtils.GetExternalFileReference(doc, link.GetTypeId())
        return _text(ModelPathUtils.ConvertModelPathToUserVisiblePath(
            reference.GetAbsolutePath()))
    except Exception:
        return ''


def _ifc_signal(path, records):
    values = []
    if '.ifc' in path.lower():
        values.append('IFC external reference')
    if any(record.get('ifc_class') or has_ifc_metadata(record.get('ifc_metadata', {}))
           for record in records):
        values.append('IFC metadata')
    return '; '.join(values)


def _eligible(element, host, structural_categories, direct_shape, import_instance):
    category = _attr(element, 'Category', None)
    # Reject view-specific/annotation/internal objects early. Category-less
    # DirectShape/import geometry remains reviewable.
    if bool(_attr(element, 'ViewSpecific', False)):
        return False
    if category is not None:
        try:
            if _text(category.CategoryType).lower() != 'model':
                return False
        except Exception:
            pass
    try:
        if eidnum(category.Id) in structural_categories:
            return True
    except Exception:
        pass
    if isinstance(element, direct_shape) or isinstance(element, import_instance):
        return True
    # IFC can be exported into any model category, including host Generic Models.
    if has_ifc_metadata(metadata_values(element)) or has_ifc_metadata(metadata_values(_type_of(element))):
        return True
    if host:
        return False
    # Bounds only screen unclassified objects in unknown categories. Recognized
    # structure/IFC/import geometry above remains reviewable without a bbox.
    try:
        return element.get_BoundingBox(None) is not None
    except Exception:
        return False


def _type_of(element):
    try:
        return element.Document.GetElement(element.GetTypeId())
    except Exception:
        return None


def link_options(doc):
    """Cheap source list: no element inventory or geometry/parameter scanning."""
    from Autodesk.Revit.DB import FilteredElementCollector, RevitLinkInstance
    result = []
    for link in FilteredElementCollector(doc).OfClass(RevitLinkInstance):
        try:
            source_doc = link.GetLinkDocument()
        except Exception:
            source_doc = None
        path = _link_reference(doc, link)
        identity = _document_identity(source_doc) if source_doc else {'path': path}
        if path:
            identity['source_path'] = path
        identity['kind'] = 'link'
        identity['unique_id'] = _text(_attr(link, 'UniqueId'))
        result.append({'key': catalog.model_key(identity), 'id': eidnum(link.Id),
                       'loaded': source_doc is not None,
                       'label': _text(_attr(source_doc, 'Title', _attr(link, 'Name', 'Link'))),
                       'link': link})
    return sorted(result, key=lambda row: (row['label'].lower(), row['id']))


def support_record(record, host=False):
    """Focused inventory excludes MEP/architecture from target approval.

    Generic IFC objects remain available for deliberate custom picking/review.
    Native host framing is not bulk-discovered unless it carries IFC evidence;
    the normal host contribution is roof/deck fallback.
    """
    classification = record.get('ifc_class', '').lower()
    if classification.startswith(('ifcflow', 'ifcduct', 'ifcpipe', 'ifcdistribution')):
        return False
    if record.get('category_role') == 'surface':
        return True
    evidence = has_ifc_metadata(record.get('ifc_metadata', {}))
    if host:
        return evidence or record.get('representation') in ('DirectShape', 'ImportInstance')
    return (bool(record.get('framing_hint') or record.get('surface_hint')) or evidence or
            record.get('category', '').lower() in ('generic models', 'generic model') or
            record.get('representation') in ('DirectShape', 'ImportInstance'))


def discover_structure(doc, selected_link_ids=None, focused=False, progress=None):
    """Inventory all loaded links, unloaded link instances and supported host geometry.

    Other RVT links are deliberately reviewable too: cached/renamed IFC imports
    can lack both a .ifc reference and useful classification data. User approval
    is always required before any discovered group becomes a rod target.
    """
    from Autodesk.Revit.DB import (BuiltInCategory, ElementId,
                                   FilteredElementCollector, RevitLinkInstance,
                                   DirectShape, ImportInstance)
    structural = set(eidnum(ElementId(category)) for category in
                     (BuiltInCategory.OST_StructuralFraming,
                      BuiltInCategory.OST_StructuralColumns,
                      BuiltInCategory.OST_Columns,
                      BuiltInCategory.OST_GenericModel,
                      BuiltInCategory.OST_Roofs,
                      BuiltInCategory.OST_Floors))
    framing_categories = set([eidnum(ElementId(BuiltInCategory.OST_StructuralFraming))])
    surface_categories = set(eidnum(ElementId(category)) for category in
                             (BuiltInCategory.OST_Roofs, BuiltInCategory.OST_Floors))
    framing_keys = set(str(value) for value in framing_categories)
    surface_keys = set(str(value) for value in surface_categories)
    models = []
    links = list(FilteredElementCollector(doc).OfClass(RevitLinkInstance))
    sources = [(None, doc)]
    for link in links:
        if selected_link_ids is not None and eidnum(link.Id) not in selected_link_ids:
            continue
        try:
            linked_doc = link.GetLinkDocument()
        except Exception:
            linked_doc = None
        sources.append((link, linked_doc))
    for link, source_doc in sources:
        host = link is None
        path = _text(_attr(source_doc, 'PathName')) if host else _link_reference(doc, link)
        identity = _document_identity(source_doc) if source_doc else {'path': path}
        if not host and path:
            identity['source_path'] = path
        identity['kind'] = 'host' if host else 'link'
        identity['unique_id'] = _text(_attr(link, 'UniqueId')) if link else 'host'
        model = {'key': catalog.model_key(identity), 'link': link,
                 'loaded': source_doc is not None, 'groups': [], 'records': [],
                 'label': (u'Native roof/deck & imported IFC - ' if focused and host else
                           u'Host project - ' if host else u'IFC / structural link - ' if focused else u'Link - ') +
                          _text(_attr(source_doc, 'Title', _attr(link, 'Name',
                                                               'Unloaded link'))),
                 'ifc_evidence': '', 'fingerprint': '', 'warnings': []}
        if source_doc is None:
            model['warnings'].append('This structural link is unloaded; reload or reselect it.')
            model['ifc_evidence'] = 'IFC external reference' if '.ifc' in path.lower() else ''
            models.append(model)
            continue
        records = []
        type_cache = {}
        skipped = 0
        nested = 0
        elements = list(FilteredElementCollector(source_doc).WhereElementIsNotElementType())
        total = max(1, len(elements))
        for index, element in enumerate(elements):
            if progress is not None and index % 100 == 0:
                progress(model['label'], index, total)
            if isinstance(element, RevitLinkInstance):
                # Nested links have a separate transform chain and cannot be
                # approved accidentally as an opaque bounding box.
                nested += 1
                continue
            if _eligible(element, host, structural, DirectShape, ImportInstance):
                try:
                    record = record_for(element, source_doc, type_cache)
                    if record['category_key'] in framing_keys:
                        record['category_role'] = 'framing'
                    elif record['category_key'] in surface_keys:
                        record['category_role'] = 'surface'
                    record['model_identity'] = model['key']
                    record['representation'] = ('DirectShape' if isinstance(element, DirectShape)
                                                else 'ImportInstance' if isinstance(element, ImportInstance)
                                                else 'Element')
                    if focused and not support_record(record, host):
                        continue
                    records.append(record)
                except Exception:
                    skipped += 1
        if progress is not None:
            progress(model['label'], total, total)
        model['records'] = records
        model['groups'] = catalog.group_records(records)
        model['ifc_evidence'] = _ifc_signal(path, records)
        transform = None
        if link:
            try:
                transform = link.GetTotalTransform()
            except Exception:
                transform = link.GetTransform()
        # A host save caused by unrelated duct edits must not invalidate its
        # unchanged structural types. Linked document versions additionally
        # detect IFC reloads whose shape changes retain identical outer bounds.
        model['fingerprint'] = fingerprint(source_doc, records, transform,
                                            include_version=not host)
        if not host and not model['ifc_evidence']:
            model['warnings'].append('No IFC signature was found; this link is offered for explicit review.')
        if skipped:
            model['warnings'].append(u'{} elements could not be inventoried; inspect model geometry.'.format(skipped))
        if nested:
            model['warnings'].append(u'{} nested link instances are not direct target sources; '
                                     'link the required structural models directly into the host.'.format(nested))
        if any(record['representation'] == 'ImportInstance' for record in records):
            model['warnings'].append('Imported geometry is reviewable; rod targeting requires readable faces, solids or meshes. Verify the imported representation in Revit.')
        models.append(model)
    return models
