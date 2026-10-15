# -*- coding: utf-8 -*-
"""ROB MEP - Repair v0.3.6+ Auto Hanger DRAFT rod lengths in place.

No new hangers, no deletion, no attachment claims. IFC selected framing is
primary at EACH rod, native selected deck secondary. Transactions per hanger.
"""
import os
import sys
import traceback
from pyrevit import revit, forms, script
from Autodesk.Revit.DB import (BuiltInCategory, BuiltInParameter,
    FabricationPart, FilteredElementCollector, Transaction, SubTransaction,
    XYZ, ElementId)
from Autodesk.Revit.UI.Selection import ObjectType, ISelectionFilter
from Autodesk.Revit.Exceptions import OperationCanceledException

_here=os.path.dirname(__file__)
if _here not in sys.path: sys.path.insert(0,_here)
import rod_geometry
import structure_priority

doc=revit.doc
uidoc=revit.uidoc
out=script.get_output()

def num(obj):
    try: return int(obj.Value)
    except Exception: return int(obj.IntegerValue)

def comment(h):
    for name in ('Comments','Fabrication Notes'):
        try:
            p=h.LookupParameter(name)
            if p and p.AsString(): return p.AsString()
        except Exception: pass
    try:
        p=h.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        return p.AsString() if p else ''
    except Exception: return ''

def is_draft(h):
    try:
        return isinstance(h,FabricationPart) and h.IsAHanger() and 'AUTO HANGER DRAFT' in comment(h).upper()
    except Exception: return False

class StructureFilter(ISelectionFilter):
    def __init__(self):
        self.categories=set(num(ElementId(c)) for c in (
            BuiltInCategory.OST_StructuralFraming,BuiltInCategory.OST_Floors,
            BuiltInCategory.OST_Roofs,BuiltInCategory.OST_Stairs))
    def AllowElement(self,el):
        try: return num(el.Category.Id) in self.categories
        except Exception: return False
    def AllowReference(self,ref,p): return False

def run():
    chosen=[]
    mode=forms.CommandSwitchWindow.show(
        ['Repair currently selected DRAFT hangers',
         'Repair ALL AUTO HANGER DRAFTs in this document'],
        message='Repair Draft Rods - no hangers are added or removed')
    if not mode: return
    if mode.startswith('Repair currently'):
        ids=list(uidoc.Selection.GetElementIds())
        chosen=[doc.GetElement(x) for x in ids if is_draft(doc.GetElement(x))]
        if not chosen:
            forms.alert('Preselect one or more AUTO HANGER DRAFT hangers first.\n'
                        'They must have the tool DRAFT marker in Comments.')
            return
    else:
        chosen=[h for h in FilteredElementCollector(doc)
                .OfCategory(BuiltInCategory.OST_FabricationHangers)
                .WhereElementIsNotElementType() if is_draft(h)]
    if not chosen:
        forms.alert('No AUTO HANGER DRAFT hangers found.')
        return
    target_mode=forms.CommandSwitchWindow.show(
        ['Use IFC beams/joists FIRST with selected roof/deck fallback',
         'Use selected native roof/deck ONLY'],
         message='Preferred per-rod structural target')
    if not target_mode: return
    link=None; preferred={}
    if target_mode.startswith('Use IFC'):
        link=structure_priority.choose_link(doc)
        if link is None: return
        try: preferred=structure_priority.select_linked_members(uidoc,link)
        except OperationCanceledException: return
        if not preferred: return
    fallback=set()
    native_mode=forms.CommandSwitchWindow.show(
        ['Pick fallback native roof/deck',
         'No native fallback (IFC only)'],
        message='Native roof or slab selection') if link else 'Pick fallback native roof/deck'
    if not native_mode: return
    if native_mode.startswith('Pick'):
        try:
            refs=uidoc.Selection.PickObjects(ObjectType.Element,StructureFilter(),
                'Select native roof/deck fallback objects, then click Finish')
            fallback=set(num(r.ElementId) for r in refs)
        except OperationCanceledException:
            if link is None: return
    if not preferred and not fallback:
        forms.alert('Select one IFC member or a native roof/deck before repair.')
        return
    choice=structure_priority.StructureChoice(link,preferred,fallback)
    raw=forms.ask_for_string(default='20',prompt='Maximum allowed rod length (ft), 1 to 60',
                              title='Repair Draft Rods')
    if raw is None: return
    try:
        limit=float(raw)
        if not (1<=limit<=60): raise ValueError('Length must be 1 to 60 ft')
    except Exception as e:
        forms.alert(str(e));return
    out.print_md('# ROB MEP - Repair Draft Rods | v0.3.7')
    out.print_md('**{} DRAFT hangers selected.** IFC chosen members {}; fallback roofs {}. Max rod {:.1f} ft.'.format(
        len(chosen),len(preferred),len(fallback),limit))
    out.print_md('An IFC solid hit at each rod XY wins over the deck; rods are **NOT attached** to structure.')
    # Calculate once before changing anything. Some rods can be unmeasurable.
    proposals=[]; errors=[]
    for h in chosen:
        try:
            proposals.append((h,rod_geometry.plan_rods(h,doc,choice,limit)))
        except Exception as ex:
            errors.append((num(h.Id),str(ex)))
    by_ifc=sum(1 for h,plan in proposals for target in plan if target['tier']=='IFC')
    by_roof=sum(1 for h,plan in proposals for target in plan if target['tier']=='ROOF')
    out.print_md('**Measurable hangers:** {}. **Unmeasurable:** {}. Rods targeting IFC: {}, roof: {}.'.format(
        len(proposals),len(errors),by_ifc,by_roof))
    for eid,reason in errors[:50]:
        out.print_md('- Hanger {} withheld: {}'.format(eid,reason))
    if not proposals:
        forms.alert('No hanger rods can be measured to the selected IFC/roof solids. No changes.')
        return
    if not forms.alert('Repair {} DRAFT hangers in place?\n'
        'No new hangers, no automatic attachment, and no deletion.\n'
        '{} hangers without measurable targets will remain unchanged.'.format(
            len(proposals),len(errors)),yes=True,no=True):
        return
    tx=Transaction(doc,'ROB MEP - Repair measured DRAFT rod lengths')
    tx.Start()
    fixed=[]; failed=[]
    try:
        for h,targets in proposals:
            sub=SubTransaction(doc); started=False
            try:
                sub.Start(); started=True
                rod_geometry.apply_lengths(h,targets,doc.Regenerate)
                label='AUTO HANGER ROD REPAIRED v0.3.7 / GEOMETRY-SIZED / UNATTACHED '
                label+=' '.join('{}:{}:R{}'.format(t['tier'],t['id'],t['index']) for t in targets)
                p=h.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
                if p is None or p.IsReadOnly:
                    raise ValueError('Cannot mark repaired draft in Comments')
                old=p.AsString() or ''
                if 'ROD REPAIRED v0.3.7' not in old:
                    p.Set((old+' | '+label)[:1000])
                sub.Commit(); started=False
                fixed.append(num(h.Id))
            except Exception as ex:
                if started:
                    try: sub.RollBack()
                    except Exception: pass
                failed.append((num(h.Id),str(ex)))
        tx.Commit()
    except Exception as ex:
        try: tx.RollBack()
        except Exception: pass
        out.print_md('**Transaction failed:** {}'.format(ex))
        return
    out.print_md('## Results: {} repaired, {} failed, {} unmeasurable / untouched'.format(
        len(fixed),len(failed),len(errors)))
    for eid,reason in failed[:75]:
        out.print_md('- Hanger {} NOT modified: {}'.format(eid,reason))
    if fixed:
        out.print_md('Repaired IDs: {}'.format(', '.join(str(n) for n in fixed[:200])))
    forms.alert('{} existing DRAFT hanger(s) updated; {} unchanged.\n'
        'Rod lengths match measured IFC framing/roof geometry, but rods are\n'
        'UNATTACHED. Verify clashes and use Attach to Structure manually.'.format(
        len(fixed),len(errors)+len(failed)))

try:
    run()
except Exception as ex:
    out.print_md('````\n{}\n````'.format(traceback.format_exc()))
    forms.alert('Repair Draft Rods failed: {}'.format(ex))
