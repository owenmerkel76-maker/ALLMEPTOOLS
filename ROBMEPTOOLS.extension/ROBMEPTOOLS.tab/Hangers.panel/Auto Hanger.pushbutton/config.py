# -*- coding: utf-8 -*-
"""Shift-click diagnostics, transient station review and explicit rolled-back probes."""
from pyrevit import forms, revit, script
from robmep_core.connector_graph import build_runs
from robmep_core.revit_connector_snapshot import capture_selection


def main(preview=False,visual=False):
    doc = revit.doc
    if doc is None or doc.IsFamilyDocument:
        forms.alert('Open a project and select fabrication duct/pipe parts first.')
        return
    ids = list(revit.uidoc.Selection.GetElementIds())
    if not ids:
        forms.alert('Select a fabrication run, including fittings, then Shift-click Auto Hanger.')
        return
    output = script.get_output()
    try:
        snapshot = capture_selection(doc, [doc.GetElement(eid) for eid in ids])
        analysis = build_runs(snapshot['parts'], snapshot['connections'],
                              excluded_parts=snapshot['excluded_parts'])
    except Exception:
        output.print_md('Connector diagnostics could not read this selection. No model changes were made.')
        script.get_logger().exception('Read-only connector diagnostic failed')
        return
    output.print_md('## ROBMEPTOOLS - read-only connector diagnostic')
    output.print_md('Selected: **{}**; readable parts: **{}**; connected selected networks: **{}**; uniform straight spans: **{}**.'.format(
        snapshot['selected_count'], len(snapshot['parts']),
        len(analysis['connected_components']), len(analysis['runs'])))
    output.print_md('Topology only: no hangers placed, no rod lengths or structural attachment verified. '
                    'Host-model fabrication duct/pipe only; linked-document geometry is not collected.')
    output.print_md('Snapshot issues: **{}**; unresolved scope/loop records: **{}**.'.format(
        len(snapshot['diagnostics']), len(analysis['unresolved'])))
    labels = dict((key, str(eid)) for key, eid in snapshot['element_ids'].items())
    if analysis['connected_components']:
        output.print_table(table_data=[
            [', '.join(labels[k] for k in component['keys']),
             'Selected scope complete' if component['scope_complete'] else 'Incomplete selection/data']
            for component in analysis['connected_components']],
            columns=['Connected selected element IDs (includes fittings)', 'Scope only'])
    output.print_md('Uniform spans stop at fittings and size changes. Part lengths exclude connection gaps; '
                    'they are not certified continuous support-station distances.')
    if snapshot['connection_gaps']:
        output.print_md('**{} connector origin-gap warnings.** Reciprocal physical API connections are retained; '
                        'geometry continuity is unverified. No connectors were moved.'.format(
                            len(snapshot['connection_gaps'])))
        output.print_table(table_data=[
            [str(row['element_ids'][0]), str(row['connector_ids'][0]),
             str(row['element_ids'][1]), str(row['connector_ids'][1]),
             '{:.6f}'.format(row['gap_ft']), '{:.6f}'.format(row['gap_ft'] * 12.),
             '{:.6f}'.format(row['gap_ft'] * 304.8)]
            for row in snapshot['connection_gaps']],
            columns=['Element A', 'Connector A', 'Element B', 'Connector B',
                     'Origin gap (feet)', 'Origin gap (inches)', 'Origin gap (mm)'])
    if analysis['runs']:
        output.print_table(table_data=[
            [', '.join(labels[k] for k in run['keys']), '{:.6f}'.format(run['length_ft'])]
            for run in analysis['runs']], columns=['Uniform straight span element IDs (ordered)', 'Sum of part lengths (feet)'])
    if snapshot['diagnostics']:
        output.print_table(table_data=[
            [row['element_id'], row['reason']] for row in snapshot['diagnostics']],
            columns=['Source element ID', 'Read/scope issue'])
    if analysis['boundaries']:
        output.print_table(table_data=[
            [labels.get(key, key), ', '.join(reasons)]
            for key, reasons in sorted(analysis['boundaries'].items())],
            columns=['Source element ID', 'Topology boundary'])
    if analysis['unresolved']:
        output.print_table(table_data=[
            [row[0], ', '.join(labels.get(k, k) for k in row[1:])]
            for row in analysis['unresolved']], columns=['Unresolved reason', 'Source identities'])

    if preview or visual:
        show_route_preview(doc, snapshot, output,visual=visual)


def show_route_preview(doc, snapshot, output, visual=False):
    # Use the unchanged planner as a pure library. Never import script.py, whose
    # entrypoint starts the production command and Revit transactions.
    import os
    import sys
    bundle = os.path.dirname(__file__)
    if bundle not in sys.path:
        sys.path.insert(0, bundle)
    import planner
    from robmep_core.hanger_route_preview import build_route_preview
    from robmep_core.revit_existing_hangers import capture_existing_hangers
    value = forms.ask_for_string(default='8, 1.5',
        prompt='Read-only geometric preview: spacing cap (2-12 ft), end target (0.5-2 ft). '
               'Enter two numbers separated by a comma. Existing preliminary size caps, '
               '4 ft branch proximity and 0.5 ft branch keep-out apply. '
               'These are NOT an approved company profile.', title='Route layout preview')
    if value is None:
        return
    try:
        numbers = [float(v.strip()) for v in value.split(',')]
        if len(numbers) != 2:
            raise ValueError('Enter spacing cap and end target, separated by a comma')
        existing = capture_existing_hangers(doc,snapshot['parts'])
        result = build_route_preview(snapshot,existing,planner,numbers[0],numbers[1])
    except Exception as ex:
        output.print_md('Route preview could not be completed. No model changes: {}'.format(ex))
        script.get_logger().exception('Read-only route preview failed')
        return
    labels = dict((k,str(v)) for k,v in snapshot['element_ids'].items())
    output.print_md('## Read-only route station preview - geometric candidates only')
    output.print_md('No hangers created; no transactions, rods, structure, exact hardware clearance or '
                    'native attachment checked. Existing hangers count for coordination/duplicate '
                    'avoidance only, including unverified drafts. Only host-model fabrication hangers '
                    'are inventoried; RFA/manual support families and linked hangers are not collected. '
                    'This is NOT an apply-ready layout.')
    output.print_md('Limits: cap {:.3f} ft; end target {:.3f} ft; existing planner end acceptance 2 ft; '
                    'branch proximity 4 ft and branch keep-out 0.5 ft. Size caps remain preliminary. '
                    'Only horizontal, aligned straight-through routes are supported; turns/offsets '
                    'and uncertain geometry are explicit boundaries.'.format(numbers[0],numbers[1]))
    if result['routes']:
        output.print_table(table_data=[
            [i+1, ', '.join(labels[k] for k in r['keys']), '{:.6f}'.format(r['length_ft']),
             '{:.3f}'.format(r['maximum_ft']) if r['maximum_ft'] is not None else 'Unresolved',
             len(r['existing']), len(r['stations']),
             'Distances covered; clearance unverified' if r['coordination_coverage_complete'] else 'DISTANCES UNRESOLVED']
            for i,r in enumerate(result['routes'])],
            columns=['Route','Ordered source IDs','Axis length (ft)','Max spacing (ft)',
                     'Existing (unverified)','Proposed candidates','Coordination coverage'])
        stations = [[i+1, row['element_id'], '{:.6f}'.format(row['station_ft']),
                     '{:.6f}'.format(row['from_a_ft']),
                     ', '.join('{:.6f}'.format(v) for v in row['point_ft'])]
                    for i,r in enumerate(result['routes']) for row in r['stations']]
        if stations:
            output.print_table(table_data=stations,
                columns=['Route','Candidate host ID','Route station (ft)',
                         'Distance from host axis start (ft)','Host-world XYZ (ft)'])
        old = [[i+1,row['element_id'],labels[row['host_key']],'{:.6f}'.format(row['station_ft']),
                'Host ID / Origin projection only; support unverified']
               for i,r in enumerate(result['routes']) for row in r['existing']]
        if old:
            output.print_table(table_data=old,
                columns=['Route','Existing hanger ID','Host ID','Route station (ft)','Evidence'])
        branch_rows = []
        for i,r in enumerate(result['routes']):
            for branch in sorted(set(r['branch_stations'])):
                nearest = min(r['existing'],key=lambda row:abs(row['station_ft']-branch)) if r['existing'] else None
                branch_rows.append([i+1,'{:.6f}'.format(branch),
                    nearest['element_id'] if nearest is not None else 'None',
                    '{:.6f}'.format(abs(nearest['station_ft']-branch)) if nearest is not None else 'Unresolved'])
        if branch_rows:
            output.print_table(table_data=branch_rows,
                columns=['Route','Branch station (ft)','Nearest existing hanger ID',
                         'Nearest existing axial distance (ft; clearance unverified)'])
        conflicts = [[i+1,row['element_id'],'{:.6f}'.format(row['station_ft']),
                      '{:.6f}'.format(row['branch_station_ft']),'{:.6f}'.format(row['separation_ft'])]
                     for i,r in enumerate(result['routes']) for row in r['existing_branch_conflicts']]
        if conflicts:
            output.print_table(table_data=conflicts,
                columns=['Route','Existing hanger ID','Hanger station (ft)','Branch station (ft)',
                         'Axial separation below 0.75 ft (ft)'])
        output.print_table(table_data=[[i+1,'; '.join(r['reasons'])] for i,r in enumerate(result['routes'])],
                           columns=['Route','Planning notes / unresolved reasons'])
    unresolved = [[', '.join(labels.get(k,k) for k in row['keys']),row['reason']] for row in result['issues']]
    unresolved += [[labels.get(row.get('host_key'), 'Unknown host'),row['reason']]
                   for row in existing['issues']]
    unresolved += [['Inventory',reason] for reason in existing['global_issues']]
    if unresolved:
        output.print_table(table_data=unresolved,columns=['Source IDs / scope','Withheld / inventory reason'])
    # This comparison isolates geometric grouping, with the same two limits. It
    # is not the full normal-click preview (which adds chosen structure/settings).
    output.print_md('Legacy geometric baseline: **{} groups / {} raw stations**, using the same cap/end target '
                    'but before existing-hanger pruning, branch keep-outs, structure or collision checks. '
                    'Straight-through preview: **{} routes**. These counts are not the full normal-click result; selected '
                    'structure, 3D clearances and hanger hardware still need separate verification.'.format(
                        result['baseline_geometric_groups'],result['baseline_raw_station_count'],
                        len(result['routes'])))

    if visual:
        review_and_test(doc,snapshot,result,output,numbers)


def review_and_test(doc,snapshot,result,output,numbers):
    import os
    import planner
    from Autodesk.Revit.DB import ElementId
    from robmep_core.station_review import review_records,validate_snapshot,validate_candidate
    from robmep_core.revit_station_review import choose_station
    from robmep_core.revit_station_probe import load_probe_runtime
    from robmep_core.revit_existing_hangers import capture_existing_hangers
    from robmep_core.hanger_route_preview import build_route_preview
    try:
        records,total=review_records(snapshot,result)
        if not records:
            output.print_md('No new candidates to mark or test. No hanger test started.')
            return
        output.print_md('## Visual station review')
        output.print_md('Showing {} of {} candidate markers in the active view; maximum 200. '
                        'Markers are screen-sized numbers anchored at the candidate XYZ, not hanger geometry. '
                        'They may be obscured or outside the view/section box. Pan/zoom during the pick step; '
                        'Esc finishes without a hanger test.'.format(len(records),total))
        output.print_table(table_data=[[r['number'],r['route_number'],r['element_id'],
                                       '{:.6f}'.format(r['station_ft'])] for r in records],
                           columns=['Marker','Route','Host ID','Route station (ft)'])
        record=choose_station(revit.uidoc,records,forms)
        output.print_md('Visual review finished; this command removed its temporary markers.')
        revit.uidoc.RefreshActiveView()
        if record is None:
            return
        def preflight():
            if revit.doc != doc:
                raise ValueError('Active document changed; rerun route preview')
            selected_keys=set(p['key'] for p in snapshot['parts'])
            selected_keys.update(snapshot['excluded_parts'])
            elements=[doc.GetElement(ElementId(snapshot['element_ids'][key])) for key in sorted(selected_keys)]
            fresh=capture_selection(doc,elements)
            validate_snapshot(snapshot,fresh)
            inventory=capture_existing_hangers(doc,fresh['parts'])
            fresh_result=build_route_preview(fresh,inventory,planner,numbers[0],numbers[1])
            validate_candidate(fresh_result,record)
        preflight()
        if not forms.alert('Test marker #{} on duct {} at the exact preview station?\n'
                'Choose structural targets and the service hanger next.\n'
                'One temporary hanger will be inspected and always rolled back. No hanger is kept.'
                .format(record['number'],record['element_id']),yes=True,no=True):
            return
        runtime=load_probe_runtime(os.path.join(os.path.dirname(__file__),'script.py'))
        runtime['run_route_station_probe'](doc.GetElement(ElementId(record['element_id'])),record,preflight)
    except Exception as ex:
        output.print_md('Visual review / exact-station test stopped: {}'.format(ex))
        script.get_logger().exception('Visual station review or rolled-back test failed')
        forms.alert('Station review/test stopped: {}. Check the output for cleanup status.'.format(ex))


if __name__ == '__main__':
    mode = forms.CommandSwitchWindow.show(['Connector diagnostic', 'Route layout preview (read-only)',
                                          'Visual stations + single test (rolled back)'],
                                          message='Auto Hanger - diagnostics')
    if mode:
        main(preview=(mode == 'Route layout preview (read-only)'),
             visual=(mode == 'Visual stations + single test (rolled back)'))
