"""Compare the supplied Review 4 rerun, prior automatic output and human tags."""
import argparse
import collections
import csv
import hashlib
import json
from pathlib import Path
import fitz
from build_autotag_human_oct15 import spans, tag_records, text, BLUE, RED, GRAY


def main():
    ap = argparse.ArgumentParser()
    for key in ('human', 'auto', 'prior'):
        ap.add_argument('--'+key, required=True)
    ap.add_argument('--output', default='downloads')
    args = ap.parse_args()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    docs = {key: fitz.open(getattr(args, key)) for key in ('human', 'auto', 'prior')}
    ss = {key: spans(doc[0]) for key, doc in docs.items()}
    for i in range(150):
        assert len({ss[key][i]['text'] for key in docs}) == 1
        assert all(max(abs(a-b) for a, b in zip(ss['human'][i]['bbox'], ss[key][i]['bbox'])) < .001 for key in docs)
    tags = {key: tag_records(items) for key, items in ss.items()}
    assert (len(tags['human']), len(tags['auto']), len(tags['prior'])) == (68, 80, 79)
    counts = {key: collections.Counter(item['label'] for item in records) for key, records in tags.items()}
    available = set(range(len(tags['auto'])))
    differences = []
    for human in sorted(tags['human'], key=lambda r: (counts['auto'][r['label']], r['bbox'][1])):
        same = [i for i in available if tags['auto'][i]['label'] == human['label']]
        if same:
            i = min(same, key=lambda i: abs(fitz.Rect(tags['auto'][i]['bbox']).tl-fitz.Rect(human['bbox']).tl))
            available.remove(i)
        else:
            differences.append(dict(human))
    differences.sort(key=lambda r: (r['bbox'][1], r['bbox'][0]))
    for i, item in enumerate(differences, 1):
        item['mark'] = 'R'+str(i)
    cfm = {key: collections.Counter(s['text'] for s in items if 'CFM' in s['text']) for key, items in ss.items()}
    report = fitz.open()

    def page(title, subtitle):
        p = report.new_page(width=1440, height=1020)
        p.draw_rect(fitz.Rect(0, 0, 1440, 105), fill=(.95, .97, .99), color=None)
        text(p, (32, 15, 1405, 62), title, 25, BLUE, True)
        text(p, (32, 66, 1405, 100), subtitle, 13, GRAY)
        return p

    def show(p, key, target, clip, marked=False):
        target, clip = fitz.Rect(target), fitz.Rect(clip)
        p.show_pdf_page(target, docs[key], 0, clip=clip)
        scale = min(target.width/clip.width, target.height/clip.height)
        dx = target.x0+(target.width-clip.width*scale)/2-clip.x0*scale
        dy = target.y0+(target.height-clip.height*scale)/2-clip.y0*scale
        for item in differences if marked else []:
            box = fitz.Rect(item['bbox'])
            if not clip.contains(box):
                continue
            r = fitz.Rect(box.x0*scale+dx-3, box.y0*scale+dy-3, box.x1*scale+dx+3, box.y1*scale+dy+3)
            p.draw_rect(r, color=RED, width=1.3)
            label = fitz.Rect(r.x1+2, r.y0-1, r.x1+40, r.y0+19)
            if label.x1 > target.x1:
                label = fitz.Rect(r.x0-40, r.y0-1, r.x0-2, r.y0+19)
            p.draw_rect(label, color=None, fill=(1, 1, 1))
            text(p, label, item['mark'], 11, RED, True)
        p.draw_rect(target, color=(.75, .79, .83), width=.6)

    p = page('AutoTag Review 4 rerun versus your human tags',
             'October 15, 2026 | User confirmed Review 4 | Human PDF is identical to the prior benchmark')
    rows = [('PDF text inventory', 'Human', 'Review 3', 'Review 4'),
            ('BOD spans', '68', '79', '80'), ('CFM spans', '35', '39', '31'),
            ('6x4 OA / BOD 11 ft 2 in', '3', '1', '1')]
    for i, row in enumerate(rows):
        y = 137+i*55
        for x, cell in zip((42, 750, 930, 1130), row):
            text(p, (x, y, x+690 if x==42 else x+170, y+43), cell, 18, BLUE if i==0 else (.08,.12,.17), i==0)
    text(p, (42, 390, 1385, 510),
         'The component boxes now sit outside many terminal symbols: a visible improvement over Review 3. '
         'Coverage is still incomplete. Review 4 has fewer CFM text spans and still prints only one of the three '
         'human 6x4 OA / BOD 11 ft 2 in callouts. Printed inventories do not identify which Revit source or '
         'placement check caused an omission.', 19)
    text(p, (42, 555, 1385, 720),
         'LATEST USER RULE: every visible straight duct must be a BOD target, even without a change event. '
         'Skip elbow and angled-fitting BOD targets for now; the user will create a compatible tag family later. '
         'Review 5 therefore adds an independent all-straight target inventory, including diagonal, sloped and '
         'vertical straights. Do not reduce the target set just to match the human tag count.', 20, BLUE, True)
    text(p, (42, 770, 1385, 928),
         'Red R markers identify human callout text without a remaining equal-label match in Review 4. They '
         'are tag-text locations, not duct source points. Some differences may refer to fittings now deliberately '
         'deferred, or different values. The new code has not generated these PDFs; a fresh Review 5 PDF and '
         'JSON are needed to verify actual target coverage, family text and placement.', 17, RED)

    p = page('What changed in the supplied rerun', 'Prior automatic export - left | latest Review 4 export - right | identical crop')
    text(p, (35, 118, 700, 151), 'PRIOR REVIEW 3', 18, BLUE, True)
    text(p, (745, 118, 1410, 151), 'LATEST REVIEW 4', 18, BLUE, True)
    show(p, 'prior', (35,158,700,809), (330,337,414,397))
    show(p, 'auto', (745,158,1410,809), (330,337,414,397))
    text(p, (42, 835, 1388, 950),
         'Boxes move off the diffuser symbols and acquire leaders. The office branch BOD omissions remain, '
         'and some component callouts are absent. Review 5 requires every straight, broadens safe diagonal '
         'component positions, and records placement diagnostics for the next audit.', 18)

    regions = [
        ('North rooms and quiet-study branches', (326,140,448,236),
         'External component placement is visible here. Different printed BOD values must be associated with '
         'their real Revit sources before judging numerical correctness. Elbow BOD tags are deferred.'),
        ('Restroom branch and component coverage', (344,232,408,282),
         'The human sheet has 100 CFM callouts in this area that are absent from the latest automatic crop. '
         'A narrower search can exhaust nearby positions; the new search adds diagonal pockets while retaining '
         'the 1.10-inch paper leader limit and protected-text/crop checks.'),
        ('Cafe and telecom callout differences', (344,269,408,326),
         'The human sheet contains different exhaust sizes/BOD values here. Some labels point to bends or '
         'other pieces. Review 5 does not copy those values or try to tag fittings with an incompatible family.'),
        ('Office takeoffs: all straights now required', (330,325,397,384),
         'Two extra human office 6x4 OA callouts remain unmatched. The new all-straight inventory removes the '
         'change-event requirement, so those actual straight pieces must enter the target set. Physical branch '
         'paths through inline dampers/fittings are separately audited.'),
        ('Return-air and supply component positions', (398,295,455,350),
         'External boxes and short leaders improve readability. The Review 4 export has four 675 CFM text spans '
         'across the sheet versus three human spans. TYP grouping and different source choices require model '
         'evidence; equal text alone does not justify deleting tags.'),
        ('South and east straight-duct coverage', (330,390,477,478),
         'All visible straights are targets, including unchanged pieces between events. Vertical straights that '
         'project to a point use an external leader to their real source. Cropped, unreadable or blocked targets '
         'remain in the unresolved audit; no unchecked forced placement is added.')]
    for title, clip, note in regions:
        p = page(title, 'LATEST AUTO - left | HUMAN - right | identical coordinates and scale | R markers refer to the register')
        text(p, (35,118,700,151), 'AUTOTAG REVIEW 4', 18, BLUE, True)
        text(p, (745,118,1410,151), 'YOUR HUMAN TAGS', 18, BLUE, True)
        show(p, 'auto', (35,158,700,804), clip)
        show(p, 'human', (745,158,1410,804), clip, True)
        text(p, (42,828,1395,957), note, 18)

    p = page('Remaining printed-callout differences',
             'Equal-label inventory matching only | These are not certified missing straight-duct element counts')
    for i, item in enumerate(differences):
        y = 145+i*39
        text(p, (42,y,105,y+32), item['mark'], 16, RED, True)
        text(p, (117,y,1050,y+32), item['label'], 16)
        text(p, (1080,y,1395,y+32), 'PDF x %.2f / y %.2f' % tuple(item['bbox'][:2]), 13, GRAY)
    text(p, (42,660,1390,824),
         'CFM span differences: 100 CFM - human 6 / latest auto 3; 50 CFM - human 6 / auto 4; '
         '675 CFM - human 3 / auto 4. These figures describe printed text, not confirmed component failures. '
         'The Review 5 component audit records source ID, text, footprint, candidate count, and status so the '
         'next run can explain each omitted component without guessing from the PDF.', 17)
    text(p, (42,853,1390,958),
         'Version to verify: Duct AutoTag Review 5 - all straight duct targets. Use All visible straight ducts '
         '(BOD). Existing tags are preserved; compare in a clean copy or undo/remove only the previous automatic '
         'run. Elbow/angled-fitting BOD tagging remains deferred.', 17, BLUE, True)

    for i, p in enumerate(report):
        text(p, (1250,984,1407,1010), '%d / %d' % (i+1,len(report)), 11, GRAY)
    prefix = 'Human-vs-AutoTag-Review-4-Rerun'
    dest = out/(prefix+'-Comparison.pdf')
    report.set_metadata({'title': 'AutoTag Review 4 rerun versus human tags',
                         'subject': 'Same-area observations and Review 5 all-straight target scope'})
    report.save(dest, garbage=4, deflate=True)
    evidence = {'source_sha256': {key: hashlib.sha256(Path(getattr(args,key)).read_bytes()).hexdigest() for key in docs},
                'uploaded_version': 'Review 4 (confirmed by user)', 'counts': {
                    key: {'bod_spans': len(tags[key]), 'cfm_spans': sum(cfm[key].values()),
                           'cfm_labels': dict(cfm[key])} for key in docs},
                'human_only_printed_callouts': differences,
                'new_printed_signatures_vs_prior': dict(counts['auto']-counts['prior']),
                'fewer_printed_signatures_vs_prior': dict(counts['prior']-counts['auto']),
                'user_scope': 'All visible straight ducts; defer elbow and angled-fitting BOD tags.',
                'limitations': ['PDF text matching is not a Revit source/coverage certificate.',
                                'Review 5 output must be validated by a fresh Revit export and JSON.']}
    (out/(prefix+'-Evidence.json')).write_text(json.dumps(evidence,indent=2)+'\n')
    with (out/(prefix+'-Differences.csv')).open('w',newline='') as stream:
        w = csv.writer(stream)
        w.writerow(['mark','human_printed_callout','pdf_x_pt','pdf_y_pt'])
        w.writerows((r['mark'],r['label'],r['bbox'][0],r['bbox'][1]) for r in differences)
    print(json.dumps({'pdf':str(dest),'pages':len(report),'marked_callouts':len(differences),'bytes':dest.stat().st_size}))


if __name__ == '__main__':
    main()
