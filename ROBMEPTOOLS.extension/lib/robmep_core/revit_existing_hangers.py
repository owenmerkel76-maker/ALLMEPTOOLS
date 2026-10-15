# -*- coding: utf-8 -*-
"""Read-only host-ID/Origin inventory. No bbox or native attachment guesses."""
from robmep_core.revit_connector_snapshot import _number, _finite


def capture_existing_hangers(document, parts, api=None, elements=None):
    """Unreadable host identity blocks planning; unknown Origin blocks its route.

    Host IDs and origins support coordination only. Neither establishes rod
    attachment, support capacity, valid spacing or engineer-approved coverage.
    ``elements`` allows testing the same read path without a Revit collector.
    """
    if api is None:
        from Autodesk.Revit import DB as api
    keys = dict((p['element_id'],p['key']) for p in parts)
    hangers, issues, global_issues = [], [], []
    if elements is None:
        try:
            elements = list(api.FilteredElementCollector(document).OfCategory(
                api.BuiltInCategory.OST_FabricationHangers).WhereElementIsNotElementType())
        except Exception:
            return dict(hangers=[],issues=[],global_issues=['EXISTING_HANGER_COLLECTION_UNREADABLE'])
    seen = set()
    for hanger in elements:
        if not isinstance(hanger,api.FabricationPart):
            continue
        try:
            eid = _number(hanger.Id)
            if eid in seen:
                continue
            seen.add(eid)
            if hanger.Document != document:
                raise ValueError('Foreign hanger document')
            info = hanger.GetHostedInfo()
            if info is None:
                raise ValueError('Unknown hanger host')
            host_id = _number(info.HostId)
        except Exception:
            global_issues.append('EXISTING_HANGER_HOST_UNREADABLE')
            continue
        if host_id not in keys:
            continue
        key = keys[host_id]
        try:
            origin = hanger.Origin
            point = tuple(_finite(v) for v in (origin.X,origin.Y,origin.Z))
            hangers.append(dict(element_id=eid,host_key=key,point_ft=point,
                                structural_support_verified=False))
        except Exception:
            issues.append(dict(element_id=eid,host_key=key,reason='EXISTING_HANGER_ORIGIN_UNREADABLE'))
    return dict(hangers=sorted(hangers,key=lambda r:r['element_id']),
                issues=issues,global_issues=sorted(set(global_issues)))
