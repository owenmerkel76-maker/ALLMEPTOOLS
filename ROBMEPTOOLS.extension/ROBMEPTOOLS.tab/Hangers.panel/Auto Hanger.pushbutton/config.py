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
        analysis = build_runs(snapshot['parts'], snapshot['connections'])
    except Exception:
        output.print_md('Connector diagnostics could not read this selection. No model changes were made.')
        script.get_logger().exception('Read-only connector diagnostic failed')
        return
    output.print_md('## ROBMEPTOOLS - read-only connector diagnostic')
    output.print_md('Selected: **{}**; readable parts: **{}**; linear runs: **{}**.'.format(
        snapshot['selected_count'], len(snapshot['parts']), len(analysis['runs'])))
    output.print_md('Topology only: no hangers placed, no rod lengths or structural attachment verified. '
                    'Host-model fabrication duct/pipe only; linked-document geometry is not collected.')
    output.print_md('Snapshot issues: **{}**; unresolved scope/loop records: **{}**.'.format(
        len(snapshot['diagnostics']), len(analysis['unresolved'])))
    labels = dict((p['key'], str(p['element_id'])) for p in snapshot['parts'])
    if analysis['runs']:
        output.print_table(table_data=[
            [', '.join(labels[k] for k in run['keys']), '{:.6f}'.format(run['length_ft'])]
            for run in analysis['runs']], columns=['Ordered source element IDs', 'Run length (feet)'])
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
