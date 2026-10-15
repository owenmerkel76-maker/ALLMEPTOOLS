"""Build an aligned vector review from the October 15 AutoTag/human exports."""
import argparse
import collections
import csv
import hashlib
import json
import math
import re
from pathlib import Path
import fitz

BLUE = (.07, .29, .56)
RED = (.80, .16, .11)
GRAY = (.34, .39, .44)
INK = (.08, .12, .17)


def text(page, box, content, size=16, color=INK, bold=False):
    remaining = page.insert_textbox(fitz.Rect(box), content, fontsize=size,
                                    fontname='hebo' if bold else 'helv', color=color)
    if remaining < 0:
        raise ValueError('Text overflow: ' + content[:100])


def spans(page):
    return [dict(s, direction=list(line['dir'])) for block in page.get_text('dict')['blocks']
            for line in block.get('lines', []) for s in line['spans']]


def tag_records(items):
    bodies = [s for s in items if re.fullmatch(r'\d+"(?:x\d+"|[\u00f8\u00d8])-[A-Z]+', s['text'])]
    result = []
    def center(s):
        r = fitz.Rect(s['bbox'])
        return (r.tl + r.br) * .5
    for bod in [s for s in items if s['text'].startswith('BOD:')]:
        body = min(bodies, key=lambda s: abs(center(s)-center(bod)), default=None)
        if body is None or abs(center(body)-center(bod)) > 3:
            raise ValueError('Unpaired tag: ' + bod['text'])
        box = fitz.Rect(body['bbox']) | fitz.Rect(bod['bbox'])
        result.append({'label': body['text'] + ' / ' + bod['text'], 'bbox': list(box),
                       'bod_bbox': bod['bbox'], 'direction': bod['direction']})
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--human', required=True)
    ap.add_argument('--auto', required=True)
    ap.add_argument('--output', default='downloads')
    args = ap.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    docs = {'human': fitz.open(args.human), 'auto': fitz.open(args.auto)}
    assert all(len(d) == 1 and d[0].rect == fitz.Rect(0, 0, 792, 612) for d in docs.values())
    data = {k: spans(d[0]) for k, d in docs.items()}
    # The shared room/background prefix establishes an exact-coordinate review.
    assert len(data['human']) > 150 and len(data['auto']) > 150
    for human, auto in zip(data['human'][:150], data['auto'][:150]):
        assert human['text'] == auto['text']
        assert max(abs(a-b) for a, b in zip(human['bbox'], auto['bbox'])) < .001
    tags = {k: tag_records(items) for k, items in data.items()}
    assert len(tags['auto']) == 79 and len(tags['human']) == 68
    counts = {k: collections.Counter(t['label'] for t in items) for k, items in tags.items()}
    # Match equal printed labels by proximity only for review markers. These are
    # text observations, never a Revit host/reference or coverage certificate.
    unmatched_auto = set(range(len(tags['auto'])))
    human_only = []
    for h in sorted(tags['human'], key=lambda r: (counts['auto'][r['label']], r['bbox'][1])):
        same = [i for i in unmatched_auto if tags['auto'][i]['label'] == h['label']]
        if same:
            hc = fitz.Rect(h['bbox']).tl
            i = min(same, key=lambda i: abs(fitz.Rect(tags['auto'][i]['bbox']).tl-hc))
            unmatched_auto.remove(i)
        else:
            human_only.append(dict(h))
    human_only.sort(key=lambda r: (r['bbox'][1], r['bbox'][0]))
    for index, item in enumerate(human_only, 1):
        item['mark'] = 'M' + str(index)
    report = fitz.open()

    def page(title, subtitle):
        p = report.new_page(width=1440, height=1020)
        p.draw_rect(fitz.Rect(0, 0, 1440, 104), fill=(.95, .97, .99), color=None)
        text(p, (32, 15, 1408, 62), title, 25, BLUE, True)
        text(p, (32, 66, 1408, 98), subtitle, 13, GRAY)
        return p

    def show(p, kind, target, clip, marks=()):
        target, clip = fitz.Rect(target), fitz.Rect(clip)
        p.show_pdf_page(target, docs[kind], 0, clip=clip)
        scale = min(target.width / clip.width, target.height / clip.height)
        dx = target.x0 + (target.width-clip.width*scale)/2 - clip.x0*scale
        dy = target.y0 + (target.height-clip.height*scale)/2 - clip.y0*scale
        for record in marks:
            box = fitz.Rect(record['bbox'])
            if not clip.contains(box):
                continue
            mapped = fitz.Rect(box.x0*scale+dx-3, box.y0*scale+dy-3,
                               box.x1*scale+dx+3, box.y1*scale+dy+3)
            p.draw_rect(mapped, color=RED, width=1.3)
            # Keep marker text alongside the callout, with an opaque backing.
            label_box = fitz.Rect(mapped.x1+3, mapped.y0-1, mapped.x1+39, mapped.y0+19)
            if label_box.x1 > target.x1:
                label_box = fitz.Rect(mapped.x0-39, mapped.y0-1, mapped.x0-3, mapped.y0+19)
            p.draw_rect(label_box, color=None, fill=(1, 1, 1))
            text(p, label_box, record['mark'], 11, RED, True)
        p.draw_rect(target, color=(.75, .79, .83), width=.6)

    p = page('AutoTag versus your human tags - October 15, 2026',
             'Same-area vector comparison | AUTOTAG.pdf confirmed by user as Review 3 | New source: Review 4')
    text(p, (40, 128, 720, 180), '79 automatic BOD callouts / 68 human BOD callouts', 22, BLUE, True)
    text(p, (40, 190, 720, 310),
         'AutoTag prints 11 more BOD text spans overall, yet still omits some callouts present in your drawing. '
         'A larger total does not establish branch coverage. The human sheet moves terminal boxes into open space '
         'and uses short leaders; automatic boxes frequently cover their own diffuser or grille symbols.', 18)
    text(p, (40, 325, 720, 442),
         'Your two exports align exactly: the first 150 shared room/background text spans have matching content '
         'and coordinates within 0.001 PDF point. Crops on the following pages use identical coordinates and scale.', 16)
    text(p, (40, 460, 720, 665),
         'RED M markers identify human printed callouts without an equal-label counterpart after matching the two '
         'inventories. They mark tag text locations, not duct endpoints. A marker can indicate a missing branch '
         'callout, an extra human repetition, or a different size/BOD annotation. The PDFs contain no Revit host IDs '
         'or family bindings, so these differences must not be used to rewrite model values.', 16, RED)
    text(p, (40, 699, 720, 902),
         'Review 4 changes: physical branch-takeoff auditing; external terminal/equipment boxes; protection of '
         'existing tags even when Revit supplies no box; explicit branch and component audit records. '
         'The 106-tag missing-bounds recovery remains included.\n\n'
         'The new implementation has not produced these sheets. Actual Revit placement, family labels and '
         'remaining repeated main callouts still need a fresh exported run.', 16)
    text(p, (790, 125, 1390, 159), 'HUMAN - whole comparison area', 17, BLUE, True)
    show(p, 'human', (800, 163, 1385, 948), (324, 139, 476, 481))

    regions = [
        ('North rooms and quiet-study branches', (326, 140, 448, 236),
         'Human terminal boxes sit clear of the blue symbols, with readable leaders. AutoTag places many boxes '
         'directly on the terminals. Some repeated 12x6 / 16x10 main callouts remain automatic-only; equal text '
         'on its own is insufficient proof for deleting a tag.'),
        ('Restroom branches and corridor transition', (345, 232, 407, 283),
         'Compare the human branch labels and component leaders with the automatic terminal boxes. The human '
         '10x10 EA callout is rotated along the short vertical branch. The separate branch audit adds physically '
         'proved takeoff straights; ambiguous junctions are reported.'),
        ('Cafe and telecom: missing or different exhaust callouts', (344, 269, 408, 326),
         'The human sheet includes 20x12 EA at BOD 10 ft 8 in, 10x4 EA at 10 ft 0 in and 8x4 EA at 10 ft 2 in. '
         'Several signatures have no equal printed counterpart in the automatic sheet. These are visible '
         'differences, not proof that an existing automatic numeric value should be replaced.'),
        ('Faculty hub and office branch takeoffs', (330, 325, 397, 384),
         'The human drawing labels the small office branches individually. Three human 6x4 OA / BOD 11 ft 2 in '
         'callouts appear across the area; the automatic inventory has one. AutoTag also repeats nearby 16x10 OA '
         'main labels. Physical branch-port checks address the omitted takeoff class.'),
        ('Return-air branches and component boxes', (398, 295, 455, 350),
         'Human return grille boxes are external and separated from the green symbols. AutoTag overlays the '
         'symbols and repeats the 18x14 RA callout. The new component search checks both the text footprint '
         'and its short leader route against existing annotations.'),
        ('South and east return/supply branches', (398, 390, 477, 473),
         'Human LSD / return grille boxes sit outside the blue and green symbols. Automatic boxes sit directly '
         'on those symbols. Review 4 rejects a component placement when it cannot find a clear external position; '
         'the failed source is included in the component audit.'),
        ('South office/main connection', (330, 385, 411, 480),
         'The human sheet uses one useful callout at several main/branch areas and reserves room for leaders '
         'and fabrication notes. AutoTag still adds repeated routing callouts. This release does not arbitrarily '
         'collapse size, elevation, shape or endcap targets to match a text count.')]
    for title, clip, note in regions:
        p = page(title, 'AUTO - left | HUMAN - right | identical source crop | red markers refer to the printed-callout register')
        text(p, (35, 118, 700, 150), 'AUTOTAG / REVIEW 3', 18, BLUE, True)
        text(p, (745, 118, 1408, 150), 'YOUR HUMAN TAGS', 18, BLUE, True)
        show(p, 'auto', (35, 158, 700, 804), clip)
        show(p, 'human', (745, 158, 1410, 804), clip, human_only)
        text(p, (40, 828, 1398, 950), note, 18)

    p = page('Human printed-callout differences',
             'Inventory differences after equal-label matching | Callout text counts, not certified missing Revit element counts')
    text(p, (42, 122, 1390, 205),
         'The rows below have no remaining equal-label automatic text span. A nearby automatic callout with a '
         'different value may refer to another piece. Use a fresh Review 4 JSON to establish source/type associations.', 16)
    for j, item in enumerate(human_only):
        y = 220 + j*36
        if j % 2 == 0:
            p.draw_rect(fitz.Rect(35, y-3, 1400, y+31), color=None, fill=(.96, .97, .98))
        text(p, (45, y, 100, y+30), item['mark'], 15, RED, True)
        text(p, (112, y, 1040, y+30), item['label'], 15)
        text(p, (1060, y, 1400, y+30), 'PDF x %.2f / y %.2f' % tuple(item['bbox'][:2]), 13, GRAY)
    y = 250 + len(human_only)*36
    text(p, (45, y, 1390, min(962, y+115)),
         'Additional visible differences: human BOD labels include two rotated callouts; automatic BOD text is '
         'horizontal. CFM text spans: 39 automatic / 35 human. Human TYP notes and other drafting choices can '
         'account for grouping; these totals are not a component coverage certificate.', 15)

    p = page('What Review 4 changes, and what the next run must prove',
             'The report shows the supplied Review 3 result. Source changes and host tests do not establish a plotted Revit outcome.')
    notes = [
        ('Branch callouts have their own coverage audit',
         'The existing change walker stops at tees. A new Branch takeoffs target option checks the physical branch '
         'port and actual connected horizontal straight. Tee/wye main ports are excluded when a unique opposed '
         'main pair is proved. Ambiguous crosses and query failures remain explicit in JSON.'),
        ('Terminal and equipment boxes clear their own symbols',
         'Search all four sides with short staggered candidates. Check crop, MEP, existing annotations and leader '
         'routes. Apply a real Revit leader, regenerate and check the retained head. If no candidate clears, roll '
         'back that new tag and report its source instead of printing over the symbol.'),
        ('Missing Revit boxes do not erase readable tags',
         'Review 3 recovery is retained. Readable source/type-verified tags can use conservative estimated '
         'footprints. Existing unmeasurable tags also reserve estimated space so new component boxes do not '
         'overprint them. Estimates remain distinct from measured family bounds.'),
        ('Next Revit acceptance',
         'Run on a disposable copy without the previous automatic run. Enable Branch takeoffs and map the terminal '
         'tag family. The dialog must identify Review 4. Export the result PDF and its JSON; inspect missed '
         'branches, component boxes, labels, leaders, remaining repeated calls and Undo behavior. '
         'Printed equality does not authorize suppressing separate branches or changing BOD values.')]
    for index, (title, body) in enumerate(notes):
        y = 135 + index*195
        text(p, (42, y, 1390, y+40), '%d. %s' % (index+1, title), 21, BLUE, True)
        text(p, (42, y+48, 1390, y+174), body, 17)
    for i, p in enumerate(report):
        text(p, (1260, 984, 1407, 1010), '%d / %d' % (i+1, len(report)), 11, GRAY)
    dest = output/'Human-vs-AutoTag-October-15-Comparison.pdf'
    report.set_metadata({'title': 'Human versus AutoTag - October 15, 2026',
                         'subject': 'Aligned same-area crops, printed differences and Review 4 changes'})
    report.save(dest, garbage=4, deflate=True)
    evidence = {'sources': {Path(p).name: {'sha256': hashlib.sha256(Path(p).read_bytes()).hexdigest()}
                             for p in (args.human, args.auto)},
                'uploaded_auto_version': 'Review 3 (confirmed by user)',
                'alignment': {'shared_prefix_spans': 150, 'maximum_coordinate_error_pt': .001},
                'counts': {k: {'bod_spans': len(tags[k]), 'unique_label_signatures': len(counts[k]),
                                'cfm_spans': sum('CFM' in s['text'] for s in data[k]),
                                'rotated_bod_spans': sum(abs(t['direction'][1]) > .5 for t in tags[k])}
                           for k in docs},
                'human_only_after_equal_label_matching': human_only,
                'auto_unmatched_after_equal_label_matching': [tags['auto'][i] for i in sorted(unmatched_auto)],
                'tags': tags,
                'limitations': ['PDF text inventories are not Revit element/coverage proofs.',
                                'Different printed values are not used to rewrite family labels.',
                                'Review 4 must be rerun and exported in Revit.']}
    (output/'Human-vs-AutoTag-October-15-Evidence.json').write_text(json.dumps(evidence, indent=2)+'\n')
    with (output/'Human-vs-AutoTag-October-15-Callout-Differences.csv').open('w', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['mark', 'human_printed_label', 'pdf_x_pt', 'pdf_y_pt'])
        writer.writerows((r['mark'], r['label'], r['bbox'][0], r['bbox'][1]) for r in human_only)
    print(json.dumps({'pdf': str(dest), 'pages': len(report), 'human_only_rows': len(human_only),
                      'counts': evidence['counts'], 'bytes': dest.stat().st_size}))


if __name__ == '__main__':
    main()
