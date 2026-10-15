"""Build a vector PDF review from before/after exports and an AutoDim audit.

Requires PyMuPDF and numpy for developer-side report generation only.
Markers identify source locations, not new or approved construction dimensions.
"""
import argparse
import collections
import csv
import hashlib
import json
from pathlib import Path
import re
import fitz
import numpy as np

RED=(.78,.10,.10); BLUE=(.08,.25,.55); DARK=(.12,.16,.21); GRAY=(.35,.4,.45)


def text(page, box, words, size=12, color=DARK, bold=False):
    r=page.insert_textbox(fitz.Rect(box), words, fontsize=size, fontname='hebo' if bold else 'helv', color=color)
    if r < 0:
        raise ValueError('Text overflow: '+words[:100])


def show(page, src, clip, dest):
    clip=fitz.Rect(clip); dest=fitz.Rect(dest)
    k=min(dest.width/clip.width,dest.height/clip.height)
    actual=fitz.Rect(dest.x0+(dest.width-clip.width*k)/2,dest.y0+(dest.height-clip.height*k)/2,
                     dest.x0+(dest.width+clip.width*k)/2,dest.y0+(dest.height+clip.height*k)/2)
    page.show_pdf_page(actual,src,0,clip=clip)
    return lambda p:fitz.Point(actual.x0+(p[0]-clip.x0)*k,actual.y0+(p[1]-clip.y0)*k)


def value(ft):
    ticks=int(np.floor(ft*96+.5));feet,inch=divmod(ticks,96);inch,part=divmod(inch,8)
    fraction=(' '+str(part//__import__('math').gcd(part,8))+'/'+str(8//__import__('math').gcd(part,8)))if part else ''
    return str(feet)+"'-"+str(inch)+fraction+'"'


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--before',required=True);ap.add_argument('--after',required=True);ap.add_argument('--audit',required=True);ap.add_argument('--human-example',required=True);ap.add_argument('--output',default='downloads');args=ap.parse_args()
    before=fitz.open(args.before);after=fitz.open(args.after);a=json.loads(Path(args.audit).read_text());out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
    assert len(before)==len(after)==1
    base=collections.Counter(s['text']for b in before[0].get_text('dict')['blocks']for l in b.get('lines',[])for s in l['spans'])
    labels=[]
    for b in after[0].get_text('dict')['blocks']:
        for l in b.get('lines',[]):
            for s in l['spans']:
                if base[s['text']]:base[s['text']]-=1
                else:labels.append({'text':s['text'],'bbox':s['bbox'],'direction':l['dir']})
    assert len(labels)==33 and all(x['direction']==(1.,0.)for x in labels)
    grids={g['id']:g for g in a['grid_inventory']['grids']}
    helper_runs={(x['source_id'],x['grid_name'])for x in a['attempts']if x['status']=='created' and x['phase'].startswith('helper:')and not x['phase'].startswith('helper:BL_')}
    helper_branches={x['phase'][10:]for x in a['attempts']if x['status']=='created'and x['phase'].startswith('helper:BL_')}
    # Fit independently to three lettered and five numbered grid intersections.
    # Grid coordinates inferred from repeated target +/- measured-value consensus.
    # PDF coordinates are the exported grid-bubble centers. Residuals quantify fit.
    mx=[89.461504,118.190671,138.440671];px=[309.0101,402.1368,467.6603]
    my=[159.647534,137.397534,123.647534,97.647485,81.334985];py=[196.65504,268.77385,313.29244,397.41127,450.32909]
    xf=np.polyfit(mx,px,1);yf=np.polyfit(my,py,1)
    def project(p):return [float(np.polyval(xf,p[0])),float(np.polyval(yf,p[1]))]
    records=[]
    for d in a['dimensions']:
        g=grids[d['grid_id']];key=d.get('branch_key')
        if key in helper_branches or (not key and (d['source_id'],g['name'])in helper_runs):
            if key:
                t=next(t for t in a['targets']if t.get('branch_key')==key);pos=t['point'];role='branch'
            else:
                t=next(t for t in a['targets']if t['role']=='straight_locator'and(d['source_id']==t['source_id']or d['source_id']in t['physical_member_ids']));pos=t.get('expected_target')or t['source_midpoint'];role='run'
            records.append(dict(d, grid_name=g['name'],role=role,source_location=pos,pdf_location=project(pos)))
    records.sort(key=lambda d:(d['pdf_location'][1],d['pdf_location'][0],d['dimension_id']))
    for i,d in enumerate(records):d['review_id']='M'+str(i+1).zfill(2)
    assert len(records)==89
    count=collections.Counter('numbered'if d['grid_name'][0].isdigit()else'lettered'for d in records)
    assert count=={'numbered':57,'lettered':32}
    zones=[
        ('Z1','Executive Seminar 208 / upper branches',(303,77,415,196),
         'The teal west-going branch and the orange terminal branch have no visible vertical grid offset. Repeated horizontal main locators do not establish these branch stations.'),
        ('Z2','Forum 200D / Quiet Study 210',(410,121,480,196),
         'The right-side teal branches turn into separate terminals. The horizontal 7\'-8 1/2" value locates the vertical segment; it does not locate each horizontal branch from the numbered grids.'),
        ('Z3','Group Restroom 206',(336,197,414,245),
         'The orange header and multiple individual drops need distinct installation locations. The visible main offsets do not locate every branch/drop station. All branch marks here are helper-dependent audit records.'),
        ('Z4','Cafe 203 / central offset and east green branch',(333,242,480,333),
         'The teal diagonal offset and horizontal cross-over change the route. The orange west branch and green east branches also need their own grid coordinates. No vertical locating values appear in this exported region.'),
        ('Z5','Faculty Hub 202 / Office and elevator area',(304,330,416,404),
         'The west-going teal and orange branches, including the short return around the elevator machine room, are not established by horizontal main-run values. Compare the marked branch stations with the numbered grids.'),
        ('Z6','Office 202C / Storage 202D / lower west',(304,393,426,540),
         'The vertical teal main has horizontal locators, but its individual west-going branches and lower east-going cross-over have no visible vertical offset values to numbered grids.'),
        ('Z7','Lower east blue / green systems',(400,431,510,540),
         'The blue and green routes contain separate offsets, horizontal branches and terminal turns. A few horizontal main locators remain; the marked branch/run records depend on independent helper planes.')]
    assert all(any(fitz.Rect(z[2]).contains(fitz.Point(d['pdf_location'])) for z in zones) for d in records), 'Every registered source needs a zoom crop'
    doc=fitz.open()
    def page(title,subtitle=''):
        p=doc.new_page(width=1200,height=900)
        p.draw_rect(fitz.Rect(0,0,1200,11),fill=BLUE,color=BLUE)
        text(p,(35,28,1165,75),title,24,bold=True)
        if subtitle:text(p,(35,67,1165,104),subtitle,11,GRAY)
        return p
    p=page('Duct AutoDim Run 1 - missing-dimension review','WASC-26 | SECOND FLOOR SHEET METAL FLOOR PLAN TEST | Revit 2025 | Review: October 12, 2026')
    text(p,(40,122,1130,177),'The plotted sheet is incomplete even though the audit reports full coverage.',22,RED,True)
    rows=[('122','Dimensions recorded as created and certified in the run JSON.'),('89','Helper-dependent dimension records: 57 to numbered grids + 32 to lettered grids.'),('33','Added dimension-value text spans in the exported PDF. All have horizontal reading direction.'),('0 observed','Vertical locating dimensions to the numbered grids in the reviewed export.')]
    for i,(n,desc)in enumerate(rows):
        y=205+i*91;p.draw_rect(fitz.Rect(40,y,1160,y+78),fill=(.96,.97,.98),color=(.9,.92,.94));text(p,(55,y+12,200,y+66),n,23,BLUE,True);text(p,(215,y+18,1135,y+70),desc,15)
    text(p,(40,595,1140,690),'Required result, based on the earlier human examples: locate each distinct main, branch, offset and terminal connection from the appropriate grid; cover both directions; rectangular/oval duct uses its actual edge and round duct its actual center. Suppress only proven equivalent measurements and keep text/witnesses readable.',15)
    text(p,(40,711,1140,801),'Your correction is explicit: no substitute reference lines or reference planes. A connector coordinate or a hidden helper plane is not an acceptable duct reference. Targets lacking a stable physical reference must remain listed as unresolved.',15,RED)
    text(p,(40,811,1140,864),'Evidence scope: this report compares the two supplied PDFs and the supplied JSON. PDF text spans are not a Revit object count. The numeric-grid direction is visibly absent; the 89-record register identifies helper-dependent measurements for replacement, rather than claiming 89 independently counted missing PDF objects.',11,GRAY)
    p=page('Where the missing measurements are','Blue boxes locate the zoomed pages. Existing dimensions remain black; original model/grid colors are preserved.')
    mappt=show(p,after,(295,58,514,560),(55,120,485,840))
    for z,title,clip,desc in zones:
        r=fitz.Rect(mappt((clip[0],clip[1])),mappt((clip[2],clip[3])));p.draw_rect(r,color=BLUE,width=1);text(p,(r.x0+2,r.y0+2,r.x0+35,r.y0+22),z,11,BLUE,True)
    for i,(z,title,clip,desc)in enumerate(zones):text(p,(550,128+i*83,1145,204+i*83),z+'  '+title+'\n'+desc,12)
    text(p,(550,735,1150,849),'All 18 host-grid records are present, with no rejected grids or lookup errors. This run therefore provides no evidence that an entire grid axis was omitted from collection. The failure is between recorded dimension coverage and visible/exported coverage.',13,RED)
    for z,title,clip,desc in zones:
        p=page(z+' - '+title,'Zoomed vector export: red circles identify helper-dependent source locations. Callouts name audit records; they are not proposed dimensions.')
        f=show(p,after,clip,(35,120,775,736))
        zone=[d for d in records if fitz.Rect(clip).contains(fitz.Point(d['pdf_location']))]
        for d in zone:
            q=f(d['pdf_location']);p.draw_circle(q,5.5,color=RED,width=1.25)
        # Label a readable subset; all records are preserved in the appendix/CSV.
        selected=[]
        for d in zone:
            q=f(d['pdf_location'])
            if all(abs(q.y-f(x['pdf_location']).y)>24 or abs(q.x-f(x['pdf_location']).x)>70 for x in selected):selected.append(d)
            if len(selected)==8:break
        for i,d in enumerate(selected):
            q=f(d['pdf_location']);tx=800;ty=133+i*69
            p.draw_line(q,fitz.Point(tx-9,ty+9),color=RED,width=.7)
            text(p,(tx,ty,1160,ty+56),d['review_id']+' | '+d['role']+' | Grid '+d['grid_name']+'\nSource '+str(d['source_id'])+' | Revit dim '+str(d['dimension_id']),11,RED)
        text(p,(40,757,1150,822),desc,15)
        text(p,(40,831,1150,864),str(len(zone))+' helper-dependent records in this crop. Circle centers are approximate source positions registered from the host grids; helper witness endpoints can be shifted along the run. See the register for every record.',10,GRAY)
    p=page('Before and after - same locations, same scale','The before PDF is shifted about 4 points to the right; crops below align the architecture and duct geometry.')
    text(p,(50,113,575,145),'NO DIMS - upper plan',16,BLUE,True);text(p,(625,113,1150,145),'AUTO DIM RUN 1 - upper plan',16,BLUE,True)
    # Exact red grid stroke medians differ by +4.08 PDF points horizontally.
    show(p,before,(307.08,77,484.08,243),(40,158,576,690));show(p,after,(303,77,480,243),(624,158,1160,690))
    text(p,(40,734,1150,824),'The after export adds horizontal main-run locating dimensions. The horizontal branches and restroom drops remain without the vertical grid-offset values needed to set their positions. This is the same measurement-intent problem seen in the earlier human-versus-auto comparison.',15)
    p=page('The earlier human example - what we are aiming for','Earlier uploaded SECOND FLOOR AREA A.pdf | Room 6-2002 crop from the previous visual comparison | different project, measurement-intent benchmark')
    p.insert_image(fitz.Rect(45,115,637,796),filename=args.human_example,keep_proportion=True)
    text(p,(690,130,1145,269),'The human drawing supplies both directions:\n\nHorizontal offsets locate vertical runs. Vertical offsets locate horizontal branches. Each separate terminal/branch has its own intentional station.',17)
    text(p,(690,302,1145,502),'The benchmark is target intent, not equal dimension counts or identical values across projects. A main locator cannot satisfy an unrelated branch. An offset, elbow or terminal change can introduce another required coordinate.',16)
    text(p,(690,552,1145,767),'For the fresh project, replace the red-marked helper-dependent measurements with genuine duct-edge/center references where Revit permits them. Report the remaining unresolved sources and branch targets. Never award full completion from helper-plane geometry.',16,RED)
    p=page('What the evidence proves - and what needs the next Revit run')
    text(p,(45,120,1150,253),'Confirmed in these files\nThe JSON has 122 created dimension records and marks all 124 required targets certified. It also records 89 created/hidden helper planes. Matching successful helper attempts to dimension records yields exactly 89 helper-dependent dimensions and 33 remaining direct-placement records.',16)
    text(p,(45,281,1150,405),'Confirmed in the plot\nThe before/after text difference has 33 added dimension-value spans, all horizontal. Detailed vector crops show the missing vertical locating direction and unlocated branch/drop stations. The grids from both orientations are drawn and inventoried.',16)
    text(p,(45,434,1150,566),'Strong diagnostic lead\n122 - 33 = 89, the same as the helper-dependent record count. This supports your diagnosis, but PDF objects do not retain Revit dimension IDs. The report does not claim a one-to-one plotted-object match or that hiding a plane is the only possible cause.',16)
    text(p,(45,595,1150,784),'Tool change for the next test\nDuct AutoDim 6.5 removes all reference-plane creation, movement and hiding. Recovery retries genuine duct references only. Known old helper dimensions cannot satisfy source coverage. The audit includes actual reference element IDs. Connector-only branches without an available physical reference remain unresolved. Test on a clean duplicate of the undimensioned view and export at the same scale.',16,BLUE)
    # Complete register of helper-dependent dimensions, grouped spatially.
    for offset in range(0,len(records),25):
        group=records[offset:offset+25];p=page('Helper-dependent measurement register '+str(offset//25+1),'These are old-run audit values, not approved replacement dimensions. Every record needs a genuine source reference or an explicit unresolved outcome.')
        xs=[40,92,168,284,402,490,620,820]
        heads=['Mark','Role','Source ID','Dim ID','Grid','Audit value','Source X, Y (ft)','Observed issue']
        for x,h in zip(xs,heads):text(p,(x,119,x+150,148),h,10,BLUE,True)
        for j,d in enumerate(group):
            y=157+j*25
            if j%2==0:p.draw_rect(fitz.Rect(35,y-3,1165,y+21),fill=(.96,.97,.98),color=None)
            axis='vertical locating direction absent'if d['grid_name'][0].isdigit()else'helper-backed; plot not ID-verifiable'
            vals=[d['review_id'],d['role'],str(d['source_id']),str(d['dimension_id']),d['grid_name'],value(d['actual_value_ft']),'{:.2f}, {:.2f}'.format(*d['source_location'][:2]),axis]
            for x,v in zip(xs,vals):text(p,(x,y,x+345 if x==820 else x+170,y+21),v,9)
        text(p,(40,818,1140,865),'Source locations use straight-edge target/midpoint or recorded branch connector location. Model-to-PDF grid fit: max X residual {:.3f} pt; max Y residual {:.3f} pt. No exported PDF identity mapping to Revit dimensions is available.'.format(max(abs(np.polyval(xf,mx)-px)),max(abs(np.polyval(yf,my)-py))),10,GRAY)
    for i,p in enumerate(doc):text(p,(1060,874,1170,895),str(i+1)+' / '+str(len(doc)),10,GRAY)
    doc.set_metadata({'title':'Duct AutoDim Run 1 - Missing Dimensions and Direct Source Review','author':'MEPTOOLS review','subject':'Before/after vector inspection with complete helper-dependent dimension register'})
    dest=out/'Duct-AutoDim-Run-1-Missed-Dimensions.pdf';doc.save(dest,garbage=4,deflate=True)
    fields=['review_id','role','source_id','dimension_id','grid_name','actual_value_ft','source_location','pdf_location','branch_key']
    with (out/'Duct-AutoDim-Run-1-Helper-Register.csv').open('w',newline='')as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(records)
    evidence={'source_hashes':{Path(fn).name:hashlib.sha256(Path(fn).read_bytes()).hexdigest()for fn in [args.before,args.after,args.audit]},'recorded_dimensions':len(a['dimensions']),'helper_dependent_records':len(records),'helper_axes':dict(count),'added_pdf_value_spans':labels,'records':records,'registration':{'x':xf.tolist(),'y':yf.tolist(),'x_residual_pt':max(abs(np.polyval(xf,mx)-px)),'y_residual_pt':max(abs(np.polyval(yf,my)-py))},'limitations':['PDF text spans are not Revit object counts.','Helper dependence is derived from successful audit attempt/source/grid/branch matches.','Source marks are approximate locations, not construction dimension proposals.']}
    (out/'Duct-AutoDim-Run-1-Evidence.json').write_text(json.dumps(evidence,indent=2)+'\n')
    print(json.dumps({'pdf':str(dest),'pages':len(doc),'helper_records':len(records),'added_pdf_spans':len(labels),'bytes':dest.stat().st_size}))

if __name__=='__main__':main()
