# -*- coding: utf-8 -*-
"""Pure metadata catalog and conservative project preference restoration.

IronPython 2.7 compatible. Revit objects may occur in records, but this module
never inspects them. Hints help a user review structure; they never approve it.
Runtime ElementIds are deliberately excluded from persistent identities.
"""
from __future__ import division

import hashlib
import json
import math
import re


SCHEMA_VERSION = 1
ROLES = ('preferred', 'fallback')
PRIORITY_MODES = ('preferred_first', 'preferred_only', 'fallback_only')

try:
    text_type = unicode
    string_types = (basestring,)
except NameError:
    text_type = str
    string_types = (str,)


def _text(value):
    if value is None:
        return ''
    try:
        return re.sub(r'\s+', ' ', text_type(value)).strip()
    except Exception:
        return ''


def _norm(value):
    return _text(value).lower()


def _hash(parts):
    payload = json.dumps(parts, sort_keys=True, ensure_ascii=True,
                         separators=(',', ':'))
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def _metadata_text(value):
    if isinstance(value, dict):
        return ' '.join(_text(key) + ' ' + _metadata_text(value[key])
                        for key in sorted(value, key=lambda item: _text(item)))
    if isinstance(value, (list, tuple, set)):
        return ' '.join(_metadata_text(item) for item in value)
    return _text(value)


def _metadata_values(value):
    """Unknown IFC classes may come from values, never parameter field names."""
    if isinstance(value, dict):
        ignored = ('ifcguid', 'ifcglobalid', 'globalid', 'ifcname')
        return ' '.join(_metadata_values(value[key])
                        for key in sorted(value, key=lambda item: _text(item))
                        if re.sub(r'[^a-z]', '', _norm(key)) not in ignored)
    if isinstance(value, (list, tuple, set)):
        return ' '.join(_metadata_values(item) for item in value)
    return _text(value)


_IFC_NAMES = dict((name.lower(), name) for name in (
    'IfcBeam', 'IfcMember', 'IfcColumn', 'IfcSlab', 'IfcRoof',
    'IfcPlate', 'IfcBuildingElementProxy', 'IfcBuildingElementPart',
    'IfcElementAssembly', 'IfcFooting', 'IfcPile', 'IfcWall',
    'IfcCurtainWall', 'IfcCovering', 'IfcRailing', 'IfcStair',
    'IfcOpeningElement', 'IfcDistributionElement'))


def _ifc_class(record):
    # Exporters place these fields in arbitrary parameter dictionaries. Prefer
    # an explicit class, but also support values such as "IFC Export As:
    # IfcBeamType" and standard-case aliases without requiring exact spelling.
    values = [record.get('ifc_class', ''), record.get('ifc_metadata', ''),
              record.get('classification', ''), record.get('metadata', '')]
    for value in values:
        matches = re.findall(r'\bifc[a-z][a-z0-9_]*', _metadata_text(value), re.I)
        for match in matches:
            normalized = match.lower()
            for suffix in ('standardcase', 'type'):
                if normalized.endswith(suffix):
                    normalized = normalized[:-len(suffix)]
            if normalized in _IFC_NAMES:
                return _IFC_NAMES[normalized]
    # Keep unknown class evidence visible, without mistaking exported parameter
    # names (IfcGUID, IfcName, IfcExportAs) for the element's IFC classification.
    ignored = ('ifcguid', 'ifcname', 'ifcexportas', 'ifcclass', 'ifctype',
               'ifcentity', 'ifcpredefinedtype', 'ifcglobalid', 'ifcobjecttype')
    for value in values:
        matches = re.findall(r'\bifc[a-z][a-z0-9_]*', _metadata_values(value), re.I)
        for match in matches:
            if match.lower() not in ignored:
                return 'Ifc' + match[3:4].upper() + match[4:]
    return ''


def _display_type(value):
    value = _text(value)
    normalized = value.lower()
    placeholders = ('', '-', '?', 'none', '<none>', 'null', 'unknown',
                    'unclassified', 'generic model', 'generic models',
                    'directshape', 'direct shape', 'default',
                    'ifcbuildingelementproxy', 'ifc building element proxy')
    return 'Unclassified' if normalized in placeholders else value


def classify_metadata(record):
    """Return review hints and normalized IFC class, never implicit approval."""
    ifc_class = _ifc_class(record)
    category = _norm(record.get('category', ''))
    category_role = _norm(record.get('category_role', ''))
    type_name = _display_type(record.get('type_name', ''))
    text = ' '.join(_norm(record.get(field, ''))
                    for field in ('name', 'type_name', 'family', 'profile'))
    framing_hint = (category_role == 'framing' or
                    ifc_class in ('IfcBeam', 'IfcMember') or
                    'structural framing' in category or
                    bool(re.search(r'\b(beam|joist|girder|channel|angle)\b', text)) or
                    bool(re.search(r'\bw\s*\d+(?:\s*[xX]\s*\d+)', text)))
    surface_hint = (category_role == 'surface' or
                    ifc_class in ('IfcSlab', 'IfcRoof', 'IfcPlate') or
                    any(term in category for term in ('roof', 'floor', 'slab')) or
                    bool(re.search(r'\b(deck|slab|roof)\b', text)))
    # A column is not part of Select All Framing. Users can still explicitly
    # approve its group as an alternate structural member.
    if ifc_class == 'IfcColumn' or 'structural columns' in category:
        framing_hint = False
    return {'ifc_class': ifc_class, 'framing_hint': framing_hint,
            'surface_hint': surface_hint, 'display_type': type_name,
            'approved': False}


def type_key(record):
    """Stable type identity, independent of instance/type ElementIds."""
    classified = classify_metadata(record)
    category = record.get('category_key') or record.get('category', '')
    return 'type:' + _hash([
        _norm(category), _norm(classified['ifc_class']),
        _norm(classified['display_type']), _norm(record.get('family', '')),
        _norm(record.get('profile', ''))])


def element_token(record):
    """Return an explicit-pick token, or empty when only runtime IDs exist."""
    guid = _text(record.get('ifc_guid', ''))
    if guid:
        return 'ifc:' + guid
    unique_id = _text(record.get('unique_id', ''))
    return 'uid:' + unique_id if unique_id else ''


def group_records(records):
    """Group metadata without losing the actual instance records/components."""
    grouped = {}
    for record in records:
        key = type_key(record)
        classified = classify_metadata(record)
        if key not in grouped:
            group = {'key': key,
                     'category': _text(record.get('category', '')) or 'Uncategorized',
                     'category_key': _text(record.get('category_key', '')),
                     'ifc_class': classified['ifc_class'],
                     'type_name': classified['display_type'],
                     'family': _text(record.get('family', '')),
                     'profile': _text(record.get('profile', '')),
                     'framing_hint': False, 'surface_hint': False,
                     'approved': False, 'records': []}
            grouped[key] = group
        group = grouped[key]
        group['framing_hint'] = group['framing_hint'] or classified['framing_hint']
        group['surface_hint'] = group['surface_hint'] or classified['surface_hint']
        group['records'].append(record)
    result = []
    for group in grouped.values():
        group['records'].sort(key=lambda record: (
            element_token(record), _norm(record.get('name', ''))))
        group['count'] = len(group['records'])
        details = [group['type_name']]
        if group['profile'] and _norm(group['profile']) != _norm(group['type_name']):
            details.append(group['profile'])
        if group['family'] and _norm(group['family']) != _norm(group['type_name']):
            details.append(group['family'])
        group['label'] = ' / '.join(details)
        result.append(group)
    result.sort(key=lambda group: (_norm(group['category']),
                _norm(group['ifc_class']), _norm(group['label']), group['key']))
    return result


def fingerprint_records(records):
    """Metadata reload fingerprint; adapters should also include model geometry.

    This is separate from model_key: reload changes must trigger confirmation,
    rather than appearing to be a new source with no explanation.
    """
    rows = []
    for record in records:
        rows.append([type_key(record), element_token(record),
                     _norm(record.get('name', ''))])
    return _hash(sorted(rows))


def _path(value):
    return _text(value).replace('\\', '/').lower().rstrip('/')


def _document_identity(info):
    cloud_model = _text(info.get('cloud_model_guid', ''))
    if cloud_model:
        return ['cloud', _norm(info.get('cloud_project_guid', '')), cloud_model.lower()]
    for field in ('central_guid', 'project_guid', 'doc_guid', 'document_key'):
        value = _text(info.get(field, ''))
        if value:
            return [field, value.lower()]
    for field in ('central_path', 'path', 'source_path', 'document_path'):
        value = _path(info.get(field, ''))
        if value:
            return ['path', value]
    return []


def model_key(info):
    """Identify a source document and its link instance, not an IFC filename."""
    identity = _document_identity(info)
    instance = _text(info.get('link_unique_id') or info.get('unique_id', ''))
    kind = _norm(info.get('kind', 'host' if info.get('host') else 'link'))
    # A session identity is required when no stable document identity exists.
    if not identity:
        identity = ['session', _text(info.get('session_id')) or _text(id(info))]
    return 'model:' + _hash([kind, identity, instance])


def project_key(info):
    """Saved project identity; unsaved documents never use their display title."""
    if isinstance(info, string_types):
        return info
    key = _text(info.get('key', ''))
    if key:
        return key
    identity = _document_identity(info)
    if identity and info.get('saved', True):
        return 'project:' + _hash(identity)
    return 'session:' + _hash([_text(info.get('session_id')) or _text(id(info))])


def validate_max_rod(value):
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError('Maximum rod length must be a finite number from 1 to 60 feet.')
    if math.isnan(value) or math.isinf(value) or not 1.0 <= value <= 60.0:
        raise ValueError('Maximum rod length must be a finite number from 1 to 60 feet.')
    return value


def _model_map(models):
    return dict((model['key'], model) for model in models)


def _group_map(model):
    return dict((group['key'], group) for group in model.get('groups', []))


def _tokens(model):
    return set(element_token(record) for group in model.get('groups', [])
               for record in group.get('records', []) if element_token(record))


def make_preferences(project, models, selections, max_rod,
                     priority_mode='preferred_first', explicit_picks=None):
    """Build JSON-safe preferences from the user's reviewed selections."""
    if priority_mode not in PRIORITY_MODES:
        raise ValueError('Unknown structural priority mode.')
    preferences = {'schema_version': SCHEMA_VERSION,
                   'project_key': project_key(project),
                   'max_rod': validate_max_rod(max_rod),
                   'priority_mode': priority_mode, 'models': {}}
    model_map = _model_map(models)
    explicit_picks = explicit_picks or {}
    for key in sorted(set(selections) | set(explicit_picks)):
        if not selections.get(key) and not explicit_picks.get(key):
            continue
        model = model_map.get(key)
        if model is None or not model.get('loaded', True):
            raise ValueError('Cannot save a missing or unloaded structural model.')
        groups = _group_map(model)
        selected = {}
        for group_key, role in selections.get(key, {}).items():
            if role not in ROLES or group_key not in groups:
                raise ValueError('Cannot save an unknown structural type or role.')
            selected[group_key] = role
        picks = {}
        available = _tokens(model)
        for token, role in explicit_picks.get(key, {}).items():
            if role not in ROLES or token not in available:
                raise ValueError('Explicit structure picks require stable existing identities.')
            picks[token] = role
        if not selected and not picks:
            continue
        preferences['models'][key] = {'label': _text(model.get('label', key)),
                                     'fingerprint': _text(model.get('fingerprint', '')),
                                     'selections': selected, 'explicit_picks': picks}
    return preferences


def restore_preferences(project, models, preferences):
    """Restore only matching reviewed sources; return warnings for all losses."""
    result = {'selections': {}, 'explicit_picks': {}, 'warnings': [],
              'confirmation_required': False, 'max_rod': 20.0,
              'priority_mode': 'preferred_first'}

    def warn(message):
        result['warnings'].append(message)
        result['confirmation_required'] = True

    if not isinstance(preferences, dict) or not preferences:
        result['confirmation_required'] = True
        return result
    if preferences.get('schema_version') != SCHEMA_VERSION:
        warn('Structural settings use an unsupported version. Review and select structure again.')
        return result
    current_project = project_key(project)
    if current_project.startswith('session:'):
        warn('This project is unsaved. Structural selections must be confirmed for this session.')
        return result
    if preferences.get('project_key') != current_project:
        warn('A different project is open. Review its discovered structure before placement.')
        return result
    try:
        result['max_rod'] = validate_max_rod(preferences.get('max_rod'))
    except ValueError:
        warn('Saved maximum rod length is invalid. The default 20 feet is shown for review.')
    mode = preferences.get('priority_mode')
    if mode in PRIORITY_MODES:
        result['priority_mode'] = mode
    else:
        warn('Saved structural priority is invalid. Review the preferred-first default.')
    model_map = _model_map(models)
    saved_models = preferences.get('models', {})
    if not isinstance(saved_models, dict):
        warn('Saved structural models are invalid. Select structure again.')
        return result
    for key in sorted(saved_models):
        saved = saved_models[key]
        if not isinstance(saved, dict):
            warn('A saved structural source is invalid. Select structure again.')
            continue
        label = _text(saved.get('label', key))
        model = model_map.get(key)
        if model is None:
            warn('%s is missing. Reselect the structural source.' % label)
            continue
        if not model.get('loaded', True):
            warn('%s is unloaded. Load it and confirm its structural types.' % label)
            continue
        old = _text(saved.get('fingerprint', ''))
        new = _text(model.get('fingerprint', ''))
        if not old or not new or old != new:
            warn('%s has changed or cannot be verified. Confirm its structural types again.' % label)
            continue
        groups = _group_map(model)
        restored = {}
        selections = saved.get('selections', {})
        if not isinstance(selections, dict):
            warn('%s has invalid saved type selections. Review them again.' % label)
            selections = {}
        for group_key, role in selections.items():
            if group_key not in groups:
                warn('%s contains a missing structural type. Review its current types.' % label)
            elif role not in ROLES:
                warn('%s contains an invalid structural role. Review its current types.' % label)
            else:
                restored[group_key] = role
        if restored:
            result['selections'][key] = restored
        picks = {}
        available = _tokens(model)
        saved_picks = saved.get('explicit_picks', {})
        if not isinstance(saved_picks, dict):
            warn('%s has invalid saved model picks. Select those elements again.' % label)
            saved_picks = {}
        for token, role in saved_picks.items():
            if token not in available or role not in ROLES:
                warn('%s contains an unavailable individual pick. Select that element again.' % label)
            else:
                picks[token] = role
        if picks:
            result['explicit_picks'][key] = picks
    return result
