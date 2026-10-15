# -*- coding: utf-8 -*-
"""Shift-click: read-only physical connector diagnostics; never place hangers."""
from pyrevit import forms, revit, script
from robmep_core.connector_graph import build_runs
from robmep_core.revit_connector_snapshot import capture_selection


def main():
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


if __name__ == '__main__':
    main()
