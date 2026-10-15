# -*- coding: utf-8 -*-
"""Exact station-to-native-connector adapter; no creation or transaction API."""
import runpy

from robmep_core.revit_connector_snapshot import capture_selection
from robmep_core.station_review import exact_axis_distance


def load_probe_runtime(path):
    # script.py's guarded entrypoint prevents normal placement on this import.
    return runpy.run_path(path,run_name='robmep_station_probe_runtime')


def exact_probe_piece(document,part,request,api=None):
    snapshot = capture_selection(document,[part],api)
    if (snapshot['source'] != request['source'] or len(snapshot['parts']) != 1 or
            snapshot['parts'][0] != request['host_record'] or
            snapshot['route_geometry'].get(request['host_key']) != request['host_geometry']):
        raise ValueError('Candidate host/geometry changed; rerun route preview')
    record = snapshot['parts'][0]
    if record['kind'] != 'straight' or snapshot['route_geometry'][record['key']]['category'] != 'duct':
        raise ValueError('Exact station test requires eligible straight host duct')
    ports = dict((int(p.Id),p) for p in part.ConnectorManager.Connectors)
    ca,cb = [ports[cid] for cid in record['end_connector_ids']]
    a,b = record['axis_start_ft'],record['axis_end_ft']
    distance = exact_axis_distance(a,b,request['point_ft'])
    size = record['size']
    piece = dict(id=record['element_id'],part=part,a=a,b=b,ca=ca,cb=cb,
                 shape=record['shape'],w=size[0],h=size[-1],service_id=int(record['service']),
                 service_name=str(part.ServiceName))
    return piece,distance
