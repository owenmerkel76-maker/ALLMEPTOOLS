"""Review the supplied helper-free rerun; retain source-space and plot evidence."""
import argparse
import collections
import csv
import hashlib
import json
from pathlib import Path
import fitz
import numpy as np
from build_duct_run_review import text,show,RED,BLUE,DARK,GRAY
PURPLE=(.52,.16,.64)


def main():
    ap=argparse.ArgumentParser()
    for name in ['before','after','audit','human-example']:ap.add_argument('--'+name,required=True)
    ap.add_argument('--output',default='downloads');args=ap.parse_args()
    b=fitz.open(args.before);a=fitz.open(args.after);data=json.loads(Path(args.audit).read_text());out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
    assert data['engine']=='duct-6.5-direct-source'
    base=collections.Counter(b[0].get_text().splitlines());labels=[]
    for t in a[0].get_text().splitlines():
        if base[t]:base[t]-=1
        else:labels.append(t)
    assert len(labels)==33 and len(data['dimensions'])==33
    prior=json.loads((out/'Duct-AutoDim-Run-1-Evidence.json').read_text())
    assert hashlib.sha256(Path(args.before).read_bytes()).hexdigest()==prior['source_hashes']['NO DIMS.pdf'], 'Grid registration requires the unchanged base export'
    xf=prior['registration']['x'];yf=prior['registration']['y']
    def project(p):return [float(np.polyval(xf,p[0])),float(np.polyval(yf,p[1]))]
    missing_runs=[t for t in data['targets']if t['role']=='straight_locator'and not t['covered']]
    branches=[t for t in data['targets']if t['role']=='branch_connector'and not t['covered']]
    records=[]
    causes=collections.Counter()
    for t in missing_runs:
        failure=next(f for f in data['failures']if f['source_id']==t['source_id'])
        reason=failure['reason']
        cause='No accepted duct-edge reference'if'no-edge-ref'in reason else ('Text blocked by MEP'if'blocked'in reason else 'No parallel grid')
        causes[cause]+=1
        p=t.get('expected_target')or t.get('source_midpoint')
        records.append({'role':'run','source_id':t['source_id'],'grid':t['assigned_grid_name']or'none',
            'cause':cause,'reason':reason,'point':p,'pdf_point':project(p),'physical_member_ids':t['physical_member_ids'],
            'branch_key':None,'audit_rows':1})
    grouped={}
    for t in branches:
        key=t['branch_key']
        if key in grouped:grouped[key]['audit_rows']+=1;continue
        attempt=next(x for x in data['attempts']if x['phase']=='direct-branch:'+key)
        grouped[key]={'role':'branch','source_id':t['source_id'],'grid':attempt['grid_name']or'none',
            'cause':'Physical fitting path not attempted in 6.5','reason':attempt['detail'],
            'point':t['point'],'pdf_point':project(t['point']),'physical_member_ids':[],
            'branch_key':key,'audit_rows':1}
    records+=list(grouped.values())
    records.sort(key=lambda r:(r['role'],r['pdf_point'][1],r['pdf_point'][0]))
    n=collections.Counter()
    for r in records:n[r['role']]+=1;r['mark']=('R'if r['role']=='run'else'B')+str(n[r['role']]).zfill(2)
    assert len(missing_runs)==44 and len(branches)==53 and len(grouped)==51 and len(records)==95
    zones=[
      ('Z1','Executive Seminar 208 / upper west',(303,77,415,196),'The upper orange terminal branch and teal horizontal branches still lack vertical grid locations. The repeated horizontal main locators do not establish those stations.'),
      ('Z2','Forum 200D / Quiet Study 210',(410,121,480,196),'The two right-side teal terminal branches are missing their separate numbered-grid offsets. A horizontal main locator establishes only one coordinate.'),
      ('Z3','Group Restroom 206',(330,197,414,245),'The orange header and individual drops remain largely unlocated. Several straight-drop targets are also blocked by text clearance; connector-only targets were not physically attempted by version 6.5.'),
      ('Z4','Cafe 203 / central offsets and green branch',(303,242,480,333),'Missing references leave the horizontal cross-over and branch stations without vertical locating values. The diagonal target without a compatible parallel grid remains a separate unresolved case.'),
      ('Z5','Faculty Hub 202 / elevator and office',(304,330,426,404),'The west-going teal/orange branches and local offsets still need their own grid locations. Some nearby vertical pieces have horizontal locators, which cannot substitute for these branch coordinates.'),
      ('Z6','Office 202C / Storage 202D / lower west',(304,393,426,540),'The long teal main has horizontal locations. Its horizontal branches and lower cross-over remain missing from the numbered-grid direction. Red and purple marks distinguish missing runs from branch targets.'),
      ('Z7','Lower east blue / green systems',(400,431,510,540),'The blue and green terminal routes need multiple independent branch/offset stations. The few surviving horizontal main locators do not establish the whole system.')]
    outside=[r['mark']for r in records if not any(fitz.Rect(z[2]).contains(fitz.Point(r['pdf_point']))for z in zones)]
    assert not outside, 'Sources outside zoom crops: '+str(outside)
    d=fitz.open()
    def page(title,subtitle=''):
        p=d.new_page(width=1200,height=900);p.draw_rect(fitz.Rect(0,0,1200,11),fill=BLUE,color=BLUE)
        text(p,(35,28,1165,75),title,24,bold=True)
        if subtitle:text(p,(35,78,1165,111),subtitle,11,GRAY)
        return p
    p=page('Duct AutoDim - confirmed misses in the helper-free rerun','Supplied run: duct-6.5-direct-source | Revit 2025 | October 12, 2026 | Next build: 6.6')
    text(p,(40,125,1150,180),'The plotted result is still incomplete. Removing helpers did not restore the missing physical references.',21,RED,True)
    boxes=[('33','Created dimensions in the JSON; 33 added value labels in the PDF.'),('44','Unresolved locating runs: 35 reference failures + 8 text-clearance blocks + 1 incompatible grid.'),('53 / 51','Unresolved required branch records / unique branch keys. Two records are duplicates.'),('58','Physical straight pieces without certified locating coverage. Pieces and target roles overlap.'),('0','Helper planes created, reused or hidden in this run. Your no-helper requirement is met.')]
    for i,(num,words)in enumerate(boxes):
        y=205+i*88;p.draw_rect(fitz.Rect(40,y,1160,y+76),fill=(.96,.97,.98),color=None)
        text(p,(54,y+13,195,y+66),num,23,BLUE,True);text(p,(212,y+18,1138,y+68),words,14)
    text(p,(40,684,1150,763),'What you are seeing: the numbered-grid / vertical locating direction is still absent. The run certifies 33 of 77 logical runs and leaves every required connector-only branch unlocated. The PDF does not show a complete installation layout.',15,RED)
    text(p,(40,794,1150,858),'Counting correctly: 44 run IDs + 51 unique branch keys = 95 distinct listed target identifiers. The JSON summary has 97 unresolved records because two branch records repeat. Do not add the 58 physical pieces or 18 downstream branch records as extra independent misses.',12,GRAY)
    p=page('Overview and legend','Red circles = missing run locators. Purple circles = unique missing required branch targets. Blue boxes = detailed zoom pages.')
    mp=show(p,a,(295,58,514,560),(40,120,510,840))
    for r in records:p.draw_circle(mp(r['pdf_point']),2.2,color=RED if r['role']=='run'else PURPLE,width=.8)
    for z,title,clip,note in zones:
        box=fitz.Rect(mp((clip[0],clip[1])),mp((clip[2],clip[3])));p.draw_rect(box,color=BLUE,width=.8);text(p,(box.x0+2,box.y0+2,box.x0+38,box.y0+23),z,11,BLUE,True)
    for i,(z,title,clip,note)in enumerate(zones):text(p,(560,130+i*82,1148,203+i*82),z+'  '+title+'\n'+note,12)
    text(p,(560,728,1150,840),'All 18 host grids are inventoried, with no rejected grids or lookup errors. The miss is not explained by a missing collected grid axis. The source-reference filter and missing physical branch placement are the next code changes to test.',14,RED)
    for z,title,clip,note in zones:
        p=page(z+' - '+title,'Existing dimensions are black. Marked source locations identify confirmed unresolved targets; no construction dimensions are proposed here.')
        f=show(p,a,clip,(35,120,775,736));zone=[r for r in records if fitz.Rect(clip).contains(fitz.Point(r['pdf_point']))]
        for r in zone:p.draw_circle(f(r['pdf_point']),5,color=RED if r['role']=='run'else PURPLE,width=1.25)
        selected=[]
        for r in sorted(zone,key=lambda r:r['pdf_point'][1]):
            q=f(r['pdf_point'])
            if all(abs(q.y-f(x['pdf_point']).y)>24 or abs(q.x-f(x['pdf_point']).x)>70 for x in selected):selected.append(r)
            if len(selected)==8:break
        for i,r in enumerate(selected):
            y=134+i*69;c=RED if r['role']=='run'else PURPLE
            p.draw_line(f(r['pdf_point']),fitz.Point(790,y+8),color=c,width=.7)
            text(p,(800,y,1160,y+59),r['mark']+' | Grid '+r['grid']+' | Source '+str(r['source_id'])+'\n'+r['cause'],11,c)
        text(p,(40,758,1150,823),note,15)
        text(p,(40,836,1145,868),str(len(zone))+' distinct unresolved sources in this crop. Every one of the 95 registered source positions appears in at least one zoom. Marks are approximate source positions, not dimension-line endpoints.',10,GRAY)
    p=page('Before and after - physical duct layout is unchanged','The base export matches the prior uploaded NO DIMS.pdf byte for byte. The after plot again has 33 added dimension-value labels.')
    text(p,(45,120,570,154),'NO DIMS',16,BLUE,True);text(p,(626,120,1150,154),'LATEST AUTO DIM RUN 1',16,BLUE,True)
    show(p,b,(307.08,77,484.08,243),(40,158,575,690));show(p,a,(303,77,480,243),(625,158,1160,690))
    text(p,(40,737,1150,820),'The helper-free tool has made the audit more honest, but the plot is essentially the same set of 33 direct dimensions. These files establish the remaining misses; they do not validate the next 6.6 code changes.',16)
    p=page('The human benchmark remains the goal','Earlier human Room 6-2002 crop from SECOND FLOOR AREA A.pdf | different project, same measurement intent')
    p.insert_image(fitz.Rect(45,120,640,807),filename=args.human_example,keep_proportion=True)
    text(p,(695,135,1150,322),'Locate both directions\nA vertical run needs its horizontal grid offset. A horizontal branch needs its vertical grid offset. A main locator cannot satisfy a different branch station.',18)
    text(p,(695,366,1150,559),'Use actual duct geometry\nRectangular/oval duct: actual near edge. Round duct: actual center reference. Fitting/terminal changes can create distinct required installation coordinates.',17)
    text(p,(695,601,1150,791),'Preserve readability\nGroup related dimensions predictably, keep text clear of MEP/tags, and avoid unrelated duplicate locators. A stable measurement count alone is not a human-complete drawing.',17)
    p=page('Changes to test in Duct AutoDim 6.6','These are source changes for the NEXT run. They do not alter the supplied PDFs or prove restored Revit coverage.')
    text(p,(45,126,1150,280),'1. Validate fabrication references in model coordinates\nThe previous filter queried the raw referenced geometry and compared its tangent/normal directly with the host grid. Symbol geometry can be local to a rotated instance. The new path carries the complete nested instance transform into geometry evidence while preserving the original source Reference.',16)
    text(p,(45,318,1150,450),'2. Validate before taking the candidate limit\nVersion 6.5 limited candidates before strict checking. The new path checks physical geometry first, then limits accepted candidates. A valid edge beyond the first rejected candidates is retained. Slope, wrong owner and nonparallel references still fail.',16)
    text(p,(45,490,1150,647),'3. Attempt real fitting references for required branch stations\nVersion 6.5 returned unsupported for the connector-only path. Version 6.6 finds an actual fitting edge/face/center reference at the required connector coordinate, uses a bounded readable corridor, and certifies the actual owner, grid and measured geometry. Exact existing source references can be reused.',16)
    text(p,(45,684,1150,841),'Still unresolved when necessary\nNo substitute reference lines or planes. Wrong-offset or unavailable source references, incompatible angled grids and crowded text remain explicit misses. The uploaded JSON has no model-direction evidence, so the transform issue is a code diagnosis to confirm with the next run. New reference diagnostics record accepted/rejected geometry and reasons.',15,RED)
    for offset in range(0,len(records),25):
        group=records[offset:offset+25];p=page('Confirmed unresolved target register '+str(offset//25+1),'95 distinct identifiers: 44 run locators + 51 branch keys. The two repeated branch rows are folded into their existing key.')
        xs=[40,100,240,330,450,670];heads=['Mark','Source ID','Grid','Role','Members / rows','Reason']
        for x,h in zip(xs,heads):text(p,(x,123,x+190,153),h,11,BLUE,True)
        for j,r in enumerate(group):
            y=162+j*25
            if j%2==0:p.draw_rect(fitz.Rect(35,y-4,1165,y+20),fill=(.96,.97,.98),color=None)
            vals=[r['mark'],str(r['source_id']),r['grid'],r['role'],str(len(r['physical_member_ids']))+' parts'if r['role']=='run'else str(r['audit_rows'])+' audit row(s)',r['cause']]
            for x,v in zip(xs,vals):text(p,(x,y,x+485 if x==670 else x+170,y+22),v,9)
        text(p,(40,819,1150,870),'The CSV retains branch keys, physical member IDs, source and projected coordinates, and exact audit reasons. Text spans and target IDs are different inventories; this report does not claim an exact Revit-object-to-PDF-ID mapping.',11,GRAY)
    for i,p in enumerate(d):text(p,(1060,875,1170,897),str(i+1)+' / '+str(len(d)),10,GRAY)
    name=out/'Duct-AutoDim-Direct-Rerun-Misses.pdf';d.set_metadata({'title':'Duct AutoDim helper-free rerun - confirmed missing targets','subject':'44 runs and 51 unique required branch identifiers remain unlocated'});d.save(name,garbage=4,deflate=True)
    columns=['mark','role','source_id','grid','cause','reason','branch_key','physical_member_ids','audit_rows','point','pdf_point']
    with(out/'Duct-AutoDim-Direct-Rerun-Misses.csv').open('w',newline='')as f:
        w=csv.DictWriter(f,fieldnames=columns);w.writeheader();w.writerows(records)
    evidence={'source_hashes':{Path(p).name:hashlib.sha256(Path(p).read_bytes()).hexdigest()for p in [args.before,args.after,args.audit]},'engine':data['engine'],'created':33,'pdf_added_value_spans':labels,'missing_run_records':44,'missing_branch_records':53,'unique_missing_branch_keys':51,'raw_uncovered_pieces':58,'cause_counts':dict(causes),'records':records,'registration':prior['registration'],'limitations':['The next build requires actual Revit validation.','Raw pieces, logical runs and branch records are overlapping inventories.','PDFs have no Revit dimension-ID mapping.']}
    (out/'Duct-AutoDim-Direct-Rerun-Evidence.json').write_text(json.dumps(evidence,indent=2)+'\n')
    print(json.dumps({'pdf':str(name),'pages':len(d),'distinct_missing_target_ids':len(records),'bytes':name.stat().st_size}))

if __name__=='__main__':main()
