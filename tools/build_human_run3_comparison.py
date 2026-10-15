"""Vector, same-area human/AutoDim comparison with audit-backed unresolved marks."""
import argparse,collections,csv,hashlib,json,re
from pathlib import Path
import fitz,numpy as np
from build_duct_run_review import text,show,RED,BLUE,GRAY
PURPLE=(.53,.16,.64)


def main():
    ap=argparse.ArgumentParser()
    for k in ['human','auto','audit']:ap.add_argument('--'+k,required=True)
    ap.add_argument('--output',default='downloads');args=ap.parse_args()
    human=fitz.open(args.human);auto=fitz.open(args.auto);audit=json.loads(Path(args.audit).read_text());out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
    def spans(doc):
        return [{'text':s['text'],'bbox':s['bbox'],'direction':l['dir']}for b in doc[0].get_text('dict')['blocks']for l in b.get('lines',[])for s in l['spans']if re.fullmatch(r'\d+\x27-\d+(?: \d+/\d+)?"',s['text'])]
    hs,as_=spans(human),spans(auto)
    assert len(hs)==76 and len(as_)==58 and audit['summary']['created']==58
    def main_grid_x(doc):
        sums=collections.defaultdict(float)
        for d in doc[0].get_drawings():
            if d['color']!=(1,0,0):continue
            for item in d['items']:
                if item[0]=='l'and abs(item[1].x-item[2].x)<1e-4:sums[round(item[1].x,3)]+=abs(item[1].y-item[2].y)
        return sorted(x for x,n in sorted(sums.items(),key=lambda p:p[1],reverse=True)[:3])
    hx,ax=main_grid_x(human),main_grid_x(auto);dx=float(np.mean(np.array(ax)-hx));assert max(abs(np.array(ax)-hx-dx))<.01
    prior=json.loads((out/'Duct-AutoDim-Run-1-Evidence.json').read_text());xf,yf=prior['registration']['x'],prior['registration']['y']
    def project(p):return [float(np.polyval(xf,p[0])),float(np.polyval(yf,p[1]))]
    records=[];seen={};n=collections.Counter()
    for t in audit['targets']:
        if t['covered']or t['role']not in ('straight_locator','branch_connector'):continue
        role='run'if t['role']=='straight_locator'else'branch';key=(role,t.get('branch_key',t['source_id']))
        if key in seen:seen[key]['audit_rows']+=1;continue
        n[role]+=1;p=t.get('expected_target')or t.get('source_midpoint')or t.get('point')
        if role=='run':
            failure=next(f['reason']for f in audit['failures']if f['source_id']==t['source_id'])
            cause='No parallel grid'if'no-grid'in failure else ('Annotation corridor blocked'if'intersect annotation'in failure else'Text pocket blocked by MEP')
            grid=t.get('assigned_grid_name')or'none'
        else:
            attempt=next(a for a in audit['attempts']if a['phase']=='direct-branch:'+t['branch_key']);failure=attempt['detail'];cause='No readable bounded branch corridor';grid=attempt['grid_name']or'none'
        r={'mark':('R'if role=='run'else'B')+str(n[role]).zfill(2),'role':role,'source_id':t['source_id'],
           'grid':grid,'cause':cause,'reason':failure,'branch_key':t.get('branch_key'),
           'physical_member_ids':t.get('physical_member_ids',[]),'point':p,'pdf_point':project(p),'audit_rows':1}
        records.append(r);seen[key]=r
    assert n=={'run':35,'branch':34}
    zones=[
      ('Z1','Upper teal / orange branches',(289,62,420,196),'Your teal branch has a clear 14\'-10 1/8" primary-grid locator. AutoDim uses Grid 1.8 and adds two 0\'-2 7/8" strings at the same measurement coordinate. The orange branch stations also need clearer vertical placement.'),
      ('Z2','Forum 200D / Quiet Study 210',(414,122,491,200),'Your right-hand teal terminal turns have additional local/grid coordinates, including 4\'-2 1/2" and 3\'-7 1/8". AutoDim keeps selected locators but omits those separate stations.'),
      ('Z3','Group Restroom 206',(323,191,421,245),'Your drawing uses an overall grid locator and local branch-spacing strings. AutoDim repeats main offsets while leaving the individual orange drop/header locations unresolved. These rows have real references; layout is blocking them.'),
      ('Z4','Cafe 203 / central offsets',(306,241,432,333),'Your dimensions describe the teal/orange turns and offsets with several separate local coordinates. AutoDim leaves most of that intent missing and repeats some main-run offsets. New text-pocket placement addresses clearance; it does not automatically recreate your chains.'),
      ('Z5','East green branch / cross-over',(400,281,496,338),'Your green route is located in both directions with clear values. AutoDim supplies only selected main/connection offsets. Inspect the red/purple source marks for the remaining locating obligations.'),
      ('Z6','Faculty Hub / office / elevator',(289,328,434,409),'Your local horizontal branches have vertical grid locations and shorter related strings. AutoDim remains dominated by horizontal main locators, including several repeated 8\'-9" and 7\'-8 1/4" values.'),
      ('Z7','Lower west / storage / stair',(287,398,423,552),'The human print establishes the west-going branches and local changes individually. The AutoDim print has repeated main offsets and comparatively little vertical locating information for those branches.'),
      ('Z8','Lower east blue / green systems',(405,423,525,552),'Your blue/green terminal routes have multiple independent vertical locators: 7\'-10 7/8", 15\'-1 3/8", 15\'-10 1/8", 5\'-9" and others. AutoDim leaves most of these station requirements unresolved.')]
    outside=[(r['mark'],r['pdf_point']) for r in records if not any(fitz.Rect(z[2]).contains(fitz.Point(r['pdf_point'])) for z in zones)]
    assert not outside, str(outside)
    d=fitz.open()
    def page(title,sub=''):
        p=d.new_page(width=1440,height=1000);p.draw_rect(fitz.Rect(0,0,1440,12),fill=BLUE,color=BLUE);text(p,(35,29,1405,80),title,25,bold=True)
        if sub:text(p,(35,81,1405,115),sub,11,GRAY)
        return p
    p=page('Human dimensions versus AutoDim Run 3','Same model and area | Uploaded run: duct-6.7-source-endpoints | Revit 2025 | October 12, 2026')
    text(p,(40,138,1390,199),'The reference regression is fixed. The remaining gap is placement and drafting intent.',23,RED,True)
    rows=[('58','Actual dimensions created and certified: 42 run locators + 16 branch dimensions.'),('76 / 58','Human / AutoDim dimension-value spans in the PDFs. These are annotation inventories, not an exact target match.'),('37 / 14','Human / AutoDim vertical value spans. The human drawing gives substantially more coverage in that direction.'),('35 + 35','Unresolved run / required branch records in the JSON. The 35 branch rows contain 34 unique branch keys.'),('0','Edge-reference failures and helper planes created. Remaining blocking is chiefly text/annotation clearance.')]
    for i,(num,words)in enumerate(rows):
        y=224+i*99;p.draw_rect(fitz.Rect(40,y,1400,y+84),fill=(.96,.97,.98),color=None);text(p,(55,y+15,235,y+70),num,24,BLUE,True);text(p,(255,y+21,1375,y+72),words,15)
    text(p,(40,754,1385,859),'Your drawing is now the direct same-area benchmark. It demonstrates separate branch/offset coordinates, fewer repeated main locators, and deliberate text lanes. Different values can be correct when the datum or local chain is different; the review does not label a value wrong solely because it differs.',17)
    text(p,(40,905,1395,961),'69 distinct unresolved identifiers are marked: 35 runs + 34 branch keys. They overlap with the 40 uncovered physical pieces, which must not be added as extra independent misses. Version 6.8 changes are for the next test, not the plotted Run 3 result.',12,GRAY)
    p=page('Same-area overview','HUMAN DIMS on the left | AUTO DIM RUN 3 on the right | All view crops below are aligned from the physical grid strokes.')
    text(p,(50,128,690,162),'HUMAN DIMS',18,BLUE,True);text(p,(752,128,1398,162),'AUTO DIM RUN 3',18,BLUE,True)
    show(p,human,(278,59,530,559),(40,173,700,847));f=show(p,auto,(278+dx,59,530+dx,559),(740,173,1400,847))
    for r in records:p.draw_circle(f((r['pdf_point'][0]+dx,r['pdf_point'][1])),2.5,color=RED if r['role']=='run'else PURPLE,width=.9)
    text(p,(40,881,1390,959),'Red = unresolved run locator. Purple = unresolved required branch target. The labels in both source drawings remain original. The human and AutoDim PDF geometries align with an X translation of {:.3f} points; no source measurements are modified.'.format(dx),14)
    for z,title,clip,note in zones:
        p=page(z+' - '+title,'Aligned vector crops. Red/purple circles mark audit-backed unresolved sources in AutoDim; they are not proposed dimensions.')
        text(p,(40,127,700,161),'HUMAN DIMS',17,BLUE,True);text(p,(740,127,1400,161),'AUTO DIM RUN 3',17,BLUE,True)
        show(p,human,clip,(40,177,700,778))
        shifted=(clip[0]+dx,clip[1],clip[2]+dx,clip[3]);f=show(p,auto,shifted,(740,177,1400,778))
        region=[r for r in records if fitz.Rect(clip).contains(fitz.Point(r['pdf_point']))]
        for r in region:p.draw_circle(f((r['pdf_point'][0]+dx,r['pdf_point'][1])),5,color=RED if r['role']=='run'else PURPLE,width=1.3)
        text(p,(40,802,1390,888),note,16)
        text(p,(40,923,1390,972),str(len(region))+' unresolved identifiers in this crop. All 69 identifiers occur in at least one zoom and in the register. Number differences across datums/chains are not by themselves proof of an incorrect duct edge.',11,GRAY)
    p=page('A confirmed duplicate and a valid datum difference','Upper teal branch | Source run 4115080 | Grid 1.8 | same-area human reference')
    clip=(302,100,415,145);show(p,human,clip,(40,143,700,491));show(p,auto,(clip[0]+dx,clip[1],clip[2]+dx,clip[3]),(740,143,1400,491))
    text(p,(40,536,1395,671),'The audit records two 0\'-2 7/8" measurements with the same exact unrounded value: 0.2439942528996255 ft. Dimension 4152948 is the locating run, hosted by physical member 4115092. Dimension 4152970 is the branch record on source 4115080. Both reference Grid 1.8 and the same Y edge coordinate: 183.72486126292048 ft.',16)
    text(p,(40,709,1395,819),'The run inventory groups 4115080 and 4115092 as the same physically connected inline run. This supports reusing the measured coordinate for that branch requirement. Equal printed values on separate or disconnected branches do not qualify.',16,RED)
    text(p,(40,854,1395,958),'Your 14\'-10 1/8" primary-grid locator describes the same upper branch through another datum. AutoDim\'s shorter intermediate-grid value is not automatically numerically wrong; duplicating it and crowding its labels is the drafting problem. Primary-grid preference and full chain replication remain further refinements.',14)
    p=page('What version 6.8 changes - next Revit test','The uploaded JSON and PDF belong to 6.7. The new source has not yet produced an exported Revit result.')
    steps=[('Measure the label from the dimension style','Use the default linear dimension font, text size, width factor and unit format. Windows font metrics are used when available, with a font-sized estimate or conservative fallback otherwise. The old fixed oversized box no longer controls every value.'),('Find space beyond a short string','Add text pockets before the grid end and after the duct end. Check an enabled annotation crop when its API is available. The duct reference and measured geometry remain unchanged.'),('Require the text to clear its own duct','The witness can touch its source. The label must clear all MEP and hard annotation, including its own duct. After Revit regeneration, check the actual TextPosition rather than assuming the planned position was retained.'),('Reuse only a verified connected measurement','A run can satisfy a branch coordinate only when physical inline membership, source validity, grid, mode and actual measured target agree. Disconnected parallel runs, another axis/grid, overrides or deleted dimensions are rejected.')]
    for i,(title,body)in enumerate(steps):
        y=139+i*184;text(p,(45,y,1390,y+42),str(i+1)+'. '+title,19,BLUE,True);text(p,(45,y+46,1385,y+150),body,16)
    text(p,(45,906,1390,966),'Still to prove in Revit: restored target coverage, actual printed text positions, annotation-crop behavior, and fidelity to your human lanes. This release does not implement complete dimension chains or remove arbitrary repeated values. No substitute reference lines or planes.',13,RED)
    for offset in range(0,len(records),24):
        group=records[offset:offset+24];p=page('Unresolved target register '+str(offset//24+1),'Run 3 audit | One repeated branch row is folded into its unique key | All positions are source locations, not proposed dimension endpoints.')
        xs=[40,112,260,342,489,767];head=['Mark','Source ID','Grid','Role','Members / rows','Recorded cause']
        for x,t in zip(xs,head):text(p,(x,139,x+210,169),t,12,BLUE,True)
        for j,r in enumerate(group):
            y=184+j*29
            if j%2==0:p.draw_rect(fitz.Rect(35,y-4,1405,y+24),fill=(.96,.97,.98),color=None)
            vals=[r['mark'],str(r['source_id']),r['grid'],r['role'],str(len(r['physical_member_ids']))+' pieces'if r['role']=='run'else str(r['audit_rows'])+' row(s)',r['cause']]
            for x,v in zip(xs,vals):text(p,(x,y,x+620 if x==767 else x+185,y+25),v,11)
        text(p,(40,929,1395,971),'CSV/Evidence JSON retain exact reasons, branch keys, physical member IDs and source coordinates. The human PDF does not contain Revit reference IDs, so the review cannot certify every human-value-to-AutoDim-object match.',11,GRAY)
    for i,p in enumerate(d):text(p,(1285,973,1400,997),str(i+1)+' / '+str(len(d)),11,GRAY)
    name=out/'Human-vs-AutoDim-Run-3-Comparison.pdf';d.set_metadata({'title':'Human versus AutoDim Run 3 - same-area comparison','subject':'Direct human benchmark, missing target register and drafting layout corrections'});d.save(name,garbage=4,deflate=True)
    with(out/'Human-vs-AutoDim-Run-3-Unresolved.csv').open('w',newline='')as f:
        w=csv.DictWriter(f,fieldnames=list(records[0]));w.writeheader();w.writerows(records)
    ev={'source_hashes':{Path(p).name:hashlib.sha256(Path(p).read_bytes()).hexdigest()for p in [args.human,args.auto,args.audit]},'uploaded_engine':audit['engine'],'human_value_spans':hs,'auto_value_spans':as_,'human_vertical_spans':37,'auto_vertical_spans':14,'created_dimensions':58,'missing_run_records':35,'missing_branch_records':35,'missing_unique_branch_keys':34,'pdf_alignment_x_pt':dx,'unresolved_records':records,'confirmed_equivalent_coordinate_dimension_ids':[4152948,4152970],'limitations':['Different grids/chains can yield valid different values.','The next build needs an exported Revit run.','PDFs do not expose the human Revit reference IDs.']}
    (out/'Human-vs-AutoDim-Run-3-Evidence.json').write_text(json.dumps(ev,indent=2)+'\n')
    print(json.dumps({'pdf':str(name),'pages':len(d),'unresolved_unique_ids':len(records),'bytes':name.stat().st_size}))

if __name__=='__main__':main()
