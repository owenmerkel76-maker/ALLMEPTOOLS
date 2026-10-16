"""Compare exported drawings and an AutoDim audit without running Revit.

Developer-side CPython only. PDF support is imported lazily from
requirements-reports.txt. Inputs and generated project reports belong outside
the public repository. A private JSON config supplies grid anchors and review
crops; it never executes code. Text boxes and counts do not prove source truth.
"""
import argparse
from collections import Counter, defaultdict
import csv
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import re
import statistics


DIMENSION = re.compile(r"^(\d+)\s*'\s*-\s*(\d+)(?:\s+(\d+)/(\d+))?\s*\"$")


def feet_inches(label):
    match = DIMENSION.fullmatch(label.strip())
    if match is None:
        return None
    feet, inches, numerator, denominator = match.groups()
    if denominator is not None and int(denominator) == 0:
        return None
    fraction = Fraction(int(numerator), int(denominator)) if numerator else 0
    return float(int(feet) + (int(inches) + fraction) / 12)


def coverage(audit):
    """Keep row totals, repeated keys and downstream context visibly separate.

    A repeated projected branch key is a collision warning, never permission
    to merge physical connectors whose native IDs are absent from this schema.
    """
    required = [t for t in audit['targets'] if t['role'] == 'straight_locator'
                or (t['role'] == 'branch_connector'
                    and t.get('requires_separate_connector_target', True))]
    groups = defaultdict(list)
    for target in required:
        key = (target['role'], target.get('branch_key', target['source_id']))
        groups[key].append(target)
    repeated = [{'role': k[0], 'key': k[1], 'rows': len(v),
                 'identical_audit_rows': all(t == v[0] for t in v)}
                for k, v in groups.items() if len(v) > 1]
    covered = sum(bool(t['covered']) for t in required)
    summary = audit.get('summary', {})
    checks = {'cert_required': len(required), 'certified_targets': covered}
    mismatches = {k: {'reported': summary[k], 'computed': v}
                  for k, v in checks.items() if k in summary and summary[k] != v}
    return {'required_rows': len(required), 'covered_rows': covered,
            'uncovered_rows': len(required) - covered,
            'required_rows_by_role': dict(Counter(t['role'] for t in required)),
            'covered_rows_by_role': dict(Counter(t['role'] for t in required if t['covered'])),
            'context_rows': len(audit['targets']) - len(required),
            'repeated_keys': repeated, 'summary_mismatches': mismatches}


def overlaps(spans):
    """Positive-area PDF text-box intersections, not a glyph collision verdict."""
    result = []
    for i, first in enumerate(spans):
        a = first['bbox']
        for j in range(i):
            b = spans[j]['bbox']
            width = min(a[2], b[2]) - max(a[0], b[0])
            height = min(a[3], b[3]) - max(a[1], b[1])
            if width > 0 and height > 0:
                result.append({'labels': [j + 1, i + 1],
                               'texts': [spans[j]['text'], first['text']],
                               'area_pt2': width * height,
                               'intersection': [max(a[0], b[0]), max(a[1], b[1]),
                                                min(a[2], b[2]), min(a[3], b[3])]})
    return result


def metric_ratios(spans, metrics, points_per_paper_inch):
    if not math.isfinite(points_per_paper_inch) or points_per_paper_inch <= 0:
        raise ValueError('A positive registered paper scale is required')
    by_label = {m['label']: m for m in metrics}
    result = []
    for span in spans:
        metric = by_label.get(span['text'])
        if metric is None:
            continue
        dx, dy = span['direction']
        if abs(abs(dx) - 1) < 1e-6 and abs(dy) < 1e-6:
            width_axis, height_axis = (0, 2), (1, 3)
        elif abs(abs(dy) - 1) < 1e-6 and abs(dx) < 1e-6:
            width_axis, height_axis = (1, 3), (0, 2)
        else:
            continue  # A rotated AABB is not a glyph width measurement.
        bbox = span['bbox']
        measured_width = bbox[width_axis[1]] - bbox[width_axis[0]]
        measured_height = bbox[height_axis[1]] - bbox[height_axis[0]]
        predicted_width = metric['width_paper_in'] * points_per_paper_inch
        predicted_height = metric['height_paper_in'] * points_per_paper_inch
        if predicted_width <= 0 or predicted_height <= 0:
            continue
        result.append({'label': span['text'],
                       'width_ratio': measured_width / predicted_width,
                       'height_ratio': measured_height / predicted_height})
    return result


def fit_axis(anchors):
    if len(anchors) < 2:
        raise ValueError('At least two distinct grid anchors are required')
    x = [float(a['model']) for a in anchors]
    y = [float(a['pdf']) for a in anchors]
    if not all(math.isfinite(v) for v in x + y):
        raise ValueError('Grid anchors must be finite')
    xm, ym = statistics.mean(x), statistics.mean(y)
    denominator = sum((v - xm) ** 2 for v in x)
    if denominator < 1e-12:
        raise ValueError('Grid anchors must have distinct model coordinates')
    slope = sum((a - xm) * (b - ym) for a, b in zip(x, y)) / denominator
    if abs(slope) < 1e-12:
        raise ValueError('Collapsed PDF registration')
    offset = ym - slope * xm
    return {'slope': slope, 'offset': offset,
            'max_residual_pt': max(abs(a * slope + offset - b) for a, b in zip(x, y))}


def ordered_value_agreement(spans, dimensions, grids, tolerance_ft=1 / 192):
    """Corroborate export order; never expose it as certified Revit identity."""
    if len(spans) != len(dimensions):
        return False
    for span, dim in zip(spans, dimensions):
        value = feet_inches(span['text'])
        actual = dim.get('actual_value_ft')
        axis = grids.get(dim.get('grid_id'), {}).get('axis')
        if value is None or actual is None or not axis:
            return False
        if not math.isfinite(actual) or abs(value - actual) > tolerance_ft + 1e-9:
            return False
        # A grid-to-source string measures perpendicular to its grid axis.
        normal = (-axis[1], axis[0])
        direction = span['direction']
        if abs(normal[0] * direction[0] + normal[1] * direction[1]) < .999:
            return False
    return True


def extract_spans(page):
    return [{'text': s['text'], 'bbox': list(s['bbox']), 'direction': list(line['dir']),
             'font': s['font'], 'size': s['size']}
            for block in page.get_text('dict')['blocks'] for line in block.get('lines', [])
            for s in line['spans']]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ('human', 'auto', 'audit', 'config', 'output'):
        parser.add_argument('--' + argument, required=True)
    args = parser.parse_args()
    import fitz
    from build_duct_run_review import text, show, RED, BLUE, GRAY

    inputs = [Path(args.human), Path(args.auto), Path(args.audit)]
    output = Path(args.output).resolve()
    repository = Path(__file__).resolve().parents[1]
    if output == repository or repository in output.parents:
        raise ValueError('Keep private project reports outside the repository')
    output.mkdir(parents=True, exist_ok=True)
    human, auto = fitz.open(args.human), fitz.open(args.auto)
    if len(human) != 1 or len(auto) != 1:
        raise ValueError('This report requires single-page exports')
    if human[0].rect != auto[0].rect:
        raise ValueError('Page extents differ; register the exports independently first')
    audit = json.loads(Path(args.audit).read_text(encoding='utf-8-sig'))
    config = json.loads(Path(args.config).read_text())
    transforms = {axis: fit_axis(config['anchors'][axis]) for axis in ('x', 'y')}
    if max(t['max_residual_pt'] for t in transforms.values()) > .1:
        raise ValueError('Grid fit exceeds 0.1 PDF points')
    scales = [abs(t['slope']) * audit['view_scale'] / 12 for t in transforms.values()]
    if abs(scales[0] - scales[1]) > .01:
        raise ValueError('Anisotropic registration needs separate text-scale analysis')
    paper_scale = statistics.mean(scales)
    all_spans = {k: extract_spans(p[0]) for k, p in [('human', human), ('auto', auto)]}
    labels = {k: [s for s in spans if feet_inches(s['text']) is not None]
              for k, spans in all_spans.items()}
    # Require unshifted common text anchors; a matching page size alone is weak.
    def background(spans):
        return Counter((s['text'], tuple(s['bbox']), tuple(s['direction']))
                       for s in spans if feet_inches(s['text']) is None)
    backgrounds = {k: background(s) for k, s in all_spans.items()}
    if backgrounds['human'] != backgrounds['auto']:
        raise ValueError('Background text anchors differ; review registration/revision first')
    overlap = {k: overlaps(s) for k, s in labels.items()}
    def vector_signatures(page):
        return Counter(repr({k: v for k, v in drawing.items() if k not in ('seqno', 'layer')})
                       for drawing in page.get_drawings())
    human_vectors, auto_vectors = vector_signatures(human[0]), vector_signatures(auto[0])
    ratios = metric_ratios(labels['auto'], audit.get('text_metrics', []), paper_scale)
    grids = {g['id']: g for g in audit['grid_inventory']['grids']}
    agreement = ordered_value_agreement(labels['auto'], audit['dimensions'], grids)
    records = []
    for target in audit['targets']:
        if target['covered'] or target['role'] not in ('straight_locator', 'branch_connector'):
            continue
        point = target.get('expected_target') or target.get('source_midpoint') or target.get('point')
        if point is None:
            raise ValueError('An unresolved target lacks a source position')
        position = [point[i] * transforms[axis]['slope'] + transforms[axis]['offset']
                    for i, axis in enumerate(('x', 'y'))]
        key = target.get('branch_key')
        attempts = [a for a in audit.get('attempts', [])
                    if a['source_id'] == target['source_id']
                    and (not key or a['phase'] == 'direct-branch:' + key)
                    and a['status'] not in ('created', 'duplicate')]
        records.append({'mark': 'U' + str(len(records) + 1).zfill(2),
                        'source_id': target['source_id'], 'role': target['role'],
                        'branch_key': key, 'pdf_position': position,
                        'model_position': point,
                        'physical_member_ids': target.get('physical_member_ids', []),
                        'reason': attempts[-1]['detail'] if attempts else 'No specific attempt recorded',
                        'grid': target.get('assigned_grid_name') or
                                (attempts[-1].get('grid_name') if attempts else None)})
    report = {'source_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs},
              'engine': audit['engine'], 'summary': audit['summary'], 'coverage': coverage(audit),
              'registration': transforms, 'pdf_points_per_paper_inch': paper_scale,
              'common_background_text_spans': sum(backgrounds['human'].values()),
              'vector_paths': {'common': sum((human_vectors & auto_vectors).values()),
                               'human_only': sum((human_vectors - auto_vectors).values()),
                               'auto_only': sum((auto_vectors - human_vectors).values())},
              'label_counts': {k: len(v) for k, v in labels.items()},
              'directions': {k: dict(Counter('horizontal' if abs(s['direction'][0]) > .999
                                             else 'vertical' for s in v)) for k, v in labels.items()},
              'ordered_value_and_axis_agreement': agreement,
              'label_overlaps': overlap, 'metric_ratios': ratios,
              'labels': labels, 'unresolved': records, 'review': config['findings'],
              'limitations': ['PDF text boxes are not glyph silhouettes or native Revit references.',
                              'Order/value/axis agreement corroborates run linkage, not certified PDF object IDs.',
                              'Repeated projected branch keys are warnings; connector IDs/Z are unavailable.',
                              'No human coverage percentage, native model validation or speed gain is inferred.']}
    (output / 'AutoDim-Comparison-Evidence.json').write_text(json.dumps(report, indent=2) + '\n')
    with (output / 'AutoDim-Unresolved-Targets.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]) if records else ['mark'])
        writer.writeheader(); writer.writerows(records)

    doc = fitz.open()
    def page(title, subtitle):
        p = doc.new_page(width=1440, height=1000)
        p.draw_rect(fitz.Rect(0, 0, 1440, 10), color=BLUE, fill=BLUE)
        text(p, (35, 29, 1400, 74), title, 25, BLUE, True)
        text(p, (35, 80, 1400, 117), subtitle, 12, GRAY)
        return p

    p = page('Human versus AutoDim - evidence review', 'Same-area supplied PDFs and duct audit | 2026-10-16 | Revit 2025 / duct-6.8-text-pockets')
    stats = [('Human / AutoDim labels', str(len(labels['human'])) + ' / ' + str(len(labels['auto']))),
             ('Required targets covered (audit rows)', str(report['coverage']['covered_rows']) + ' / ' + str(report['coverage']['required_rows'])),
             ('Uncovered required target rows', str(report['coverage']['uncovered_rows'])),
             ('Intersecting label-box pairs: human / auto', str(len(overlap['human'])) + ' / ' + str(len(overlap['auto']))),
             ('Reported engine runtime', '{:.2f} sec'.format(audit['summary']['runtime']))]
    for i, (name, value) in enumerate(stats):
        y = 139 + i * 70
        text(p, (45, y, 925, y + 48), name, 18)
        text(p, (940, y, 1395, y + 48), value, 23, BLUE, True)
    text(p, (45, 521, 1395, 654), config['summary'], 18)
    text(p, (45, 683, 1395, 825), 'Scope and confidence\n' + '\n'.join(report['limitations']), 14, GRAY)
    text(p, (45, 852, 1395, 960), 'The saved font estimates are smaller than the plotted labels. A font-specific bounds fix needs a Revit rerun; this review does not apply a blanket scaling factor or change source/grid geometry. All report marks are review notes, not construction dimensions.', 16, RED)

    for zone in config['zones']:
        p = page(zone['title'], 'Human (left) | AutoDim (right) | Identical crop and scale | Orange circles: unresolved source positions')
        clip = fitz.Rect(zone['clip'])
        show(p, human, clip, (35, 135, 700, 740))
        project = show(p, auto, clip, (740, 135, 1405, 740))
        for record in records:
            if clip.contains(fitz.Point(record['pdf_position'])):
                q = project(record['pdf_position']); p.draw_circle(q, 7, color=(.85, .35, 0), width=1.3)
                text(p, (q.x + 8, q.y - 14, q.x + 70, q.y + 5), record['mark'], 10, RED, True)
        for pair in overlap['auto']:
            for index in pair['labels']:
                bbox = fitz.Rect(labels['auto'][index - 1]['bbox'])
                if clip.contains(bbox):
                    p.draw_rect(fitz.Rect(project(bbox.tl), project(bbox.br)), color=RED, width=1)
        text(p, (40, 775, 1400, 960), zone['notes'], 16)

    p = page('Prioritized development - preserve the physical references', 'Review findings and acceptance gates | No Auto Hanger changes | No human annotations removed')
    for i, finding in enumerate(config['findings']):
        y = 136 + i * 151
        text(p, (40, y, 1395, y + 37), finding['title'], 18, BLUE, True)
        text(p, (40, y + 40, 1395, y + 140), finding['body'], 14)

    for offset in range(0, len(records), 15):
        p = page('Unresolved required target register', 'Separate source obligations; nearby marks can coincide. Downstream context rows do not add another required target.')
        for i, record in enumerate(records[offset:offset + 15]):
            y = 136 + i * 51
            line = '{mark} | source {source_id} | {role} | grid {grid}\n{reason}'.format(**record)
            text(p, (40, y, 1395, y + 49), line, 12)
        text(p, (40, 932, 1395, 975), 'Exact coordinates, branch keys and member IDs are retained in the companion private CSV/JSON. A projected point identifies a source region; it does not propose a dimension witness.', 11, GRAY)
    for i, p in enumerate(doc):
        text(p, (1320, 978, 1420, 998), str(i + 1) + ' / ' + str(len(doc)), 9, GRAY)
    dest = output / 'Human-vs-AutoDim-Comparison.pdf'
    doc.set_metadata({'title': 'Human versus AutoDim - registered evidence review',
                      'subject': 'Coverage, text bounds, source-linked omissions and development priorities'})
    doc.save(dest, garbage=4, deflate=True)
    print(json.dumps({'pdf': str(dest), 'pages': len(doc), 'coverage': report['coverage'],
                      'label_counts': report['label_counts'], 'ordered_agreement': agreement}))


if __name__ == '__main__':
    main()
