# -*- coding: utf-8 -*-
"""Read-only host FabricationPart snapshot for connector_graph (Revit 2025).

Autodesk imports are lazy. Tests inject an API double; they cannot prove live
Revit behavior. Linked-document geometry is intentionally rejected, not assumed
in host coordinates. No transactions, geometry edits, hosting or placement occur.
"""
import math

try:
    text_type = unicode
except NameError:
    text_type = str


class SnapshotError(ValueError):
    pass


def _number(value):
    try:
        return int(value.Value)
    except AttributeError:
        return int(value.IntegerValue)


def _finite(value):
    value = float(value)
    if math.isnan(value) or math.isinf(value):
        raise SnapshotError('NONFINITE_GEOMETRY')
    return value


def _point(connector):
    point = connector.Origin
    return tuple(_finite(v) for v in (point.X, point.Y, point.Z))


def _distance(a, b):
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


def _key(element, source, document):
    if element.Document != document:
        raise SnapshotError('FOREIGN_DOCUMENT')
    identity = text_type(element.UniqueId)
    if not identity or identity == 'None':
        raise SnapshotError('MISSING_ELEMENT_IDENTITY')
    return source + '/' + identity


def _physical(connector, api):
    return (connector.ConnectorType in (api.ConnectorType.End,
                                       api.ConnectorType.Curve,
                                       api.ConnectorType.Physical) and
            connector.Domain in (api.Domain.DomainHvac, api.Domain.DomainPiping))


def _profile(connector, api):
    if connector.Shape == api.ConnectorProfileType.Round:
        shape, size = 'round', (2. * _finite(connector.Radius),)
    elif connector.Shape == api.ConnectorProfileType.Rectangular:
        shape, size = 'rectangular', (_finite(connector.Width), _finite(connector.Height))
    elif connector.Shape == api.ConnectorProfileType.Oval:
        shape, size = 'oval', (_finite(connector.Width), _finite(connector.Height))
    else:
        raise SnapshotError('UNKNOWN_PROFILE')
    if any(v <= 0 for v in size):
        raise SnapshotError('INVALID_SIZE')
    return shape, size


def _record(element, source, document, api):
    key = _key(element, source, document)
    ports = list(element.ConnectorManager.Connectors)
    physical = []
    for port in ports:
        # Logical connector references must never authorize physical topology.
        if port.ConnectorType == api.ConnectorType.Logical:
            continue
        if not _physical(port, api):
            raise SnapshotError('UNSUPPORTED_CONNECTOR')
        if _key(port.Owner, source, document) != key:
            raise SnapshotError('CONNECTOR_OWNER_MISMATCH')
        physical.append(port)
    if not physical:
        raise SnapshotError('NO_PHYSICAL_CONNECTORS')
    row = {'key': key, 'source': source, 'element_id': _number(element.Id),
           'kind': 'fitting'}
    if element.IsAStraight() and not element.IsATap():
        ends = sorted((p for p in physical if p.ConnectorType == api.ConnectorType.End),
                      key=lambda p: int(p.Id))
        if len(ends) != 2:
            raise SnapshotError('AMBIGUOUS_END_CONNECTORS')
        a, b = _point(ends[0]), _point(ends[1])
        length = _distance(a, b)
        if not length > 1e-9 or math.isinf(length):
            raise SnapshotError('INVALID_AXIS')
        shape, size = _profile(ends[0], api)
        other_shape, other_size = _profile(ends[1], api)
        if shape != other_shape or any(abs(x-y) > 1e-6 for x, y in zip(size, other_size)):
            raise SnapshotError('END_PROFILE_MISMATCH')
        service = int(element.ServiceId)
        if service < 0:
            raise SnapshotError('MISSING_SERVICE')
        row.update(kind='straight', shape=shape, size=size,
                   service=text_type(service), length_ft=length,
                   axis_start_ft=a, axis_end_ft=b,
                   end_connector_ids=tuple(int(p.Id) for p in ends),
                   direction=tuple((b[i]-a[i])/length for i in range(3)))
    return row, physical


def _route_geometry(element, physical, api):
    """Optional planning metadata; failure never erases diagnostic topology."""
    try:
        ports = []
        for port in sorted(physical, key=lambda p: int(p.Id)):
            kind = 'end' if port.ConnectorType == api.ConnectorType.End else 'branch'
            normal = None
            try:
                vector = port.CoordinateSystem.BasisZ
                normal = tuple(_finite(v) for v in (vector.X, vector.Y, vector.Z))
            except Exception:
                pass
            ports.append({'id':int(port.Id), 'type':kind,
                          'origin_ft':_point(port), 'normal':normal})
        service = int(element.ServiceId)
        if service < 0:
            raise SnapshotError('MISSING_ROUTE_SERVICE')
        labels = []
        for name in ('ProductName','ProductLongDescription','ProductShortDescription','Alias','Name'):
            try:
                value = getattr(element, name)
                if value:
                    labels.append(text_type(value))
            except Exception:
                pass
        return {'ports':ports, 'service':text_type(service), 'product_labels':labels,
                'category':'duct' if _number(element.Category.Id) ==
                _number(api.ElementId(api.BuiltInCategory.OST_FabricationDuctwork)) else 'pipe'}
    except Exception:
        return {'reason':'ROUTE_GEOMETRY_UNAVAILABLE'}


def capture_selection(document, elements, api=None, connection_tolerance_ft=1e-4):
    """Snapshot only the selected host fabrication duct/pipe and their edges.

    Unselected connected owners are preserved as OUTSIDE_SCOPE edges. Invalid
    records are omitted and reported separately from unselected owners. Origin
    differences are measured warnings, not a replacement for reciprocal API proof.
    The tolerance is a warning threshold, not permission to infer connections.
    IsAStraight is a topology label, NOT approval for supporting an inline device.
    Structural attachment, hanger eligibility and spacing rules are separate.
    """
    if api is None:
        from Autodesk.Revit import DB as api
    tolerance = _finite(connection_tolerance_ft)
    if tolerance <= 0:
        raise ValueError('Connection tolerance must be positive feet')
    if document is None or document.IsFamilyDocument:
        raise ValueError('An open project document is required')
    identity = text_type(document.ProjectInformation.UniqueId)
    if not identity or identity == 'None':
        raise ValueError('Project identity unavailable')
    source = 'host:' + identity
    categories = set(_number(api.ElementId(cat)) for cat in
                     (api.BuiltInCategory.OST_FabricationDuctwork,
                      api.BuiltInCategory.OST_FabricationPipework))
    records, ports, invalid, reasons = {}, {}, set(), set()
    element_ids, selected_keys, unsupported = {}, set(), set()
    gaps, port_edges = {}, {}
    selected = list(elements)

    def report(element, code):
        try:
            eid = _number(element.Id)
        except Exception:
            eid = None
        reasons.add((eid, code))

    for element in selected:
        key = None
        try:
            key = _key(element, source, document)
            selected_keys.add(key)
            element_ids[key] = _number(element.Id)
            if key in records or key in invalid:
                continue
            if (not isinstance(element, api.FabricationPart) or
                    _number(element.Category.Id) not in categories or element.IsAHanger()):
                unsupported.add(key)
                report(element, 'UNSUPPORTED_SELECTION')
                continue
            records[key], ports[key] = _record(element, source, document, api)
        except Exception as ex:
            if key is not None:
                invalid.add(key)
            report(element, text_type(ex) if isinstance(ex, SnapshotError)
                   else 'UNREADABLE_PART')

    edges, connector_pairs = set(), {}
    for key in sorted(ports):
        element = ports[key][0].Owner
        try:
            for port in ports[key]:
                count = 0
                for other in list(port.AllRefs):
                    if other.ConnectorType == api.ConnectorType.Logical:
                        continue
                    if not _physical(other, api):
                        raise SnapshotError('UNSUPPORTED_REFERENCE')
                    target = _key(other.Owner, source, document)
                    if target == key:
                        continue
                    if (not port.IsConnected or not other.IsConnected or
                            not port.IsConnectedTo(other) or not other.IsConnectedTo(port)):
                        raise SnapshotError('UNVERIFIED_CONNECTION')
                    if port.Domain != other.Domain:
                        raise SnapshotError('CONNECTION_DOMAIN_MISMATCH')
                    element_ids[target] = _number(other.Owner.Id)
                    gap_ft = _distance(_point(port), _point(other))
                    edge = tuple(sorted((key, target)))
                    tokens = tuple(sorted(((key, int(port.Id)), (target, int(other.Id)))))
                    port_edges[tokens] = {'keys':[k for k, cid in tokens],
                                          'port_ids':[cid for k, cid in tokens], 'gap_ft':gap_ft}
                    if gap_ft > tolerance:
                        gaps[tokens] = {'element_ids': [element_ids[k] for k, cid in tokens],
                                        'connector_ids': [cid for k, cid in tokens],
                                        'gap_ft': gap_ft, 'threshold_ft': tolerance,
                                        'reason': 'CONNECTED_ORIGIN_GAP',
                                        'topology_proof': 'RECIPROCAL_PHYSICAL_API'}
                    connector_pairs.setdefault(edge, set()).add(tokens)
                    edges.add(edge)
                    count += 1
                if port.IsConnected and count == 0:
                    raise SnapshotError('CONNECTED_WITHOUT_PHYSICAL_REFERENCE')
        except Exception as ex:
            invalid.add(key)
            report(element, text_type(ex) if isinstance(ex, SnapshotError)
                   else 'UNREADABLE_CONNECTION')
    for edge, pairs in connector_pairs.items():
        if len(pairs) > 1:
            # Owner-level graph edges cannot represent a two-part closed loop.
            invalid.update(edge)
            for key in edge:
                if key in records:
                    reasons.add((records[key]['element_id'], 'MULTIPLE_PART_CONNECTIONS'))
    return {'source': source, 'selected_count': len(selected),
            'parts': [records[k] for k in sorted(records) if k not in invalid],
            'connections': sorted(edges),
            'connection_ports':[port_edges[k] for k in sorted(port_edges)],
            'route_geometry':dict((k,_route_geometry(ports[k][0].Owner,ports[k],api))
                                  for k in sorted(records) if k not in invalid),
            'element_ids': element_ids,
            'excluded_parts': dict((key, 'UNSUPPORTED_SELECTED_PART' if key in unsupported
                                    else 'SELECTED_PART_REJECTED')
                                   for key in sorted(selected_keys) if key not in records or key in invalid),
            'connection_gaps': [gaps[key] for key in sorted(gaps)],
            'diagnostics': [{'element_id': eid, 'reason': reason}
                            for eid, reason in sorted(reasons, key=lambda r: (r[0] is None, r[0] or 0, r[1]))]}
