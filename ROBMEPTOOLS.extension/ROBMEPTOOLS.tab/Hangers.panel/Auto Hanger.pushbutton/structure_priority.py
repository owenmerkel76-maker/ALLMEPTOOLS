# -*- coding: utf-8 -*-
"""Approved multi-model structural targeting and attachment verification.

Reference selection uses Revit's ObjectType.LinkedElement and reads
Reference.LinkedElementId. Native fabrication rods must report the actual
LinkElementId to be counted as attached. Never equate geometric proximity
or manual rod length to a verified structural attachment.
"""
try:
    from Autodesk.Revit.UI.Selection import ISelectionFilter
except ImportError:
    # Pure geometry/selection-policy tests load this file without Revit.
    ISelectionFilter=object

try:
    text_type=unicode
except NameError:
    text_type=str


def eidnum(eid):
    try:
        return int(eid.Value)
    except Exception:
        try:
            return int(eid.IntegerValue)
        except Exception:
            return int(eid)


def catnum(el):
    try:
        return eidnum(el.Category.Id)
    except Exception:
        return None


def nums(*bics):
    from Autodesk.Revit.DB import ElementId
    return set(eidnum(ElementId(b)) for b in bics)

# IFC beams and joists are frequently converted to DirectShape/Generic Models.
# Generic Models are accepted on deliberate member picks. An entire link
# includes Generic Models only when their IFC metadata identifies framing.
FRAMING_CATS=set()
GENERIC_CATS=set()
FRAME_WORDS = ('ifcbeam','ifccolumn','ifcmember',
               'beam','joist','girder','truss','purlin','rafter','column',
               'steel frame','steel framing','wide flange','channel')


def name_for(el):
    parts=[]
    for name in ('Name','FamilyName'):
        try:
            val=getattr(el,name)
            if val: parts.append(text_type(val))
        except Exception:
            pass
    for name in ('IfcEntity','IfcExportAs','IfcType','IfcName','IFC Export As',
                 'IFC Class','IFC Entity','Description'):
        try:
            p=el.LookupParameter(name)
            if p:
                val=p.AsString() or p.AsValueString()
                if val: parts.append(text_type(val))
        except Exception:
            pass
    return u' '.join(parts).lower()


def candidate_link_part(el, explicit=False):
    if not FRAMING_CATS:
        from Autodesk.Revit.DB import BuiltInCategory
        FRAMING_CATS.update(nums(BuiltInCategory.OST_StructuralFraming,
                                BuiltInCategory.OST_StructuralColumns,
                                BuiltInCategory.OST_Columns))
        GENERIC_CATS.update(nums(BuiltInCategory.OST_GenericModel))
    c=catnum(el)
    if c in FRAMING_CATS:
        return True
    if c in GENERIC_CATS:
        return bool(explicit or any(t in name_for(el) for t in FRAME_WORDS))
    return False


class LinkedFrameFilter(ISelectionFilter):
    def __init__(self, link):
        self.link=link
        self.doc=link.GetLinkDocument()
        self.link_id=eidnum(link.Id)

    def AllowElement(self, el):
        from Autodesk.Revit.DB import RevitLinkInstance
        return isinstance(el,RevitLinkInstance) and eidnum(el.Id)==self.link_id

    def AllowReference(self, ref, position):
        try:
            if eidnum(ref.ElementId)!=self.link_id:
                return False
            candidate=self.doc.GetElement(ref.LinkedElementId)
            return candidate is not None and candidate_link_part(candidate,True)
        except Exception:
            return False


def readable_link(link):
    try:
        doc=link.GetLinkDocument()
        name=doc.Title if doc else '(UNLOADED)'
    except Exception:
        name='(UNLOADED)'
    return u'{} | instance #{}'.format(name,eidnum(link.Id))


def choose_link(doc):
    from Autodesk.Revit.DB import FilteredElementCollector, RevitLinkInstance
    from pyrevit import forms
    links=[x for x in FilteredElementCollector(doc).OfClass(RevitLinkInstance)
           if x.GetLinkDocument() is not None]
    if not links:
        forms.alert('No loaded Revit/IFC link was found. Link the IFC into Revit '
                    'first, or run again using native structure only.')
        return None
    choices={readable_link(x):x for x in links}
    names=sorted(choices)
    chosen=forms.SelectFromList.show(names,title='AUTO HANGER - choose linked IFC framing',
                                     button_name='Use selected link',multiselect=False)
    return choices.get(chosen)


def select_linked_members(uidoc,link):
    from Autodesk.Revit.DB import FilteredElementCollector
    from Autodesk.Revit.UI.Selection import ObjectType
    from pyrevit import forms
    mode=forms.CommandSwitchWindow.show(
        ['Use all recognized framing in this IFC link',
         'Pick specific beams / joists from this IFC link'],
        message='Preferred structure selection (linked IFC)')
    if not mode:
        return None
    link_doc=link.GetLinkDocument()
    if link_doc is None:
        forms.alert('The chosen link is not loaded.')
        return None
    if mode.startswith('Use all'):
        chosen={}
        n=0
        for el in FilteredElementCollector(link_doc).WhereElementIsNotElementType():
            n+=1
            if n>70000:
                forms.alert('Linked IFC contains more than 70,000 elements. '
                            'Use Pick specific beams/joists for performance.')
                return None
            if candidate_link_part(el,False):
                chosen[eidnum(el.Id)]=el
                if len(chosen)>20000:
                    forms.alert('More than 20,000 recognized framing members in the IFC. '
                                'Pick only the framing members needed for your duct area.')
                    return None
    else:
        refs=uidoc.Selection.PickObjects(ObjectType.LinkedElement,LinkedFrameFilter(link),
                     'AUTO HANGER: select IFC beam/joist MEMBERS, then Finish')
        chosen={}
        for r in refs:
            if eidnum(r.ElementId)!=eidnum(link.Id):
                continue
            el=link_doc.GetElement(r.LinkedElementId)
            if el is not None and candidate_link_part(el,True):
                chosen[eidnum(el.Id)]=el
    if not chosen:
        forms.alert('No usable linked framing members were selected/detected. '
                    'For IFC objects listed as Generic Models, use Pick specific '
                    'beams/joists and click the members directly.')
        return None
    return chosen


def box_world(bbox,trans):
    """Bounding box extents in host coordinates, including transform of link."""
    # Revit element BoundingBox's local Transform may be non-identity.
    from Autodesk.Revit.DB import XYZ
    btrans=bbox.Transform
    pts=[]
    for x in (bbox.Min.X,bbox.Max.X):
        for y in (bbox.Min.Y,bbox.Max.Y):
            for z in (bbox.Min.Z,bbox.Max.Z):
                p=btrans.OfPoint(XYZ(x,y,z))
                pts.append(trans.OfPoint(p) if trans is not None else p)
    return (min(p.X for p in pts),max(p.X for p in pts),
            min(p.Y for p in pts),max(p.Y for p in pts),
            min(p.Z for p in pts),max(p.Z for p in pts))


def each_solid(geometry,depth=0):
    from Autodesk.Revit.DB import Solid, GeometryInstance
    if geometry is None or depth>5:
        return
    for obj in geometry:
        if isinstance(obj,Solid):
            try:
                if obj.Volume>1e-9:
                    yield obj
            except Exception:
                pass
        elif isinstance(obj,GeometryInstance):
            try:
                for s in each_solid(obj.GetInstanceGeometry(),depth+1):
                    yield s
            except Exception:
                pass


def intersect_vertical_solid(element,local_start,local_end):
    """True on solid hit; None if geometry was uncheckable (fail closed)."""
    from Autodesk.Revit.DB import Options, Line, SolidCurveIntersectionOptions
    opts=Options()
    opts.IncludeNonVisibleObjects=False
    opts.ComputeReferences=False
    try:
        geometry=element.get_Geometry(opts)
    except Exception:
        return None
    if geometry is None:
        return None
    try:
        line=Line.CreateBound(local_start,local_end)
    except Exception:
        return None
    solids=0
    failures=0
    intersects=SolidCurveIntersectionOptions()
    try:
        for solid in each_solid(geometry):
            solids+=1
            try:
                segments=solid.IntersectWithCurve(line,intersects)
                if segments is not None and segments.SegmentCount>0:
                    return True
            except Exception:
                failures+=1
    finally:
        try: intersects.Dispose()
        except Exception: pass
    if not solids or failures:
        return None
    return False


def _transform_signature(transform):
    """Affine origin/basis in host coordinates, without API property aliases."""
    from Autodesk.Revit.DB import XYZ
    values=[]
    for coords in ((0,0,0),(1,0,0),(0,1,0),(0,0,1)):
        point=transform.OfPoint(XYZ(*coords))
        values.extend((point.X,point.Y,point.Z))
    return tuple(values)


def geometry_world_bounds(primitives, transform):
    """Build only a broad-phase box from readable primitive extents.

    Every primitive must supply bounds; partial bounds could hide a real hit.
    Elevations still come exclusively from ray/Solid/Mesh intersections.
    """
    boxes=[]
    for primitive in primitives:
        try:
            box=primitive.GetBoundingBox()
            if box is not None:
                boxes.append(box_world(box,transform))
                continue
        except Exception:
            pass
        try:
            vertices=list(primitive.Vertices)
            if not vertices:
                return None
            points=[transform.OfPoint(point) if transform is not None else point
                    for point in vertices]
            boxes.append((min(p.X for p in points),max(p.X for p in points),
                          min(p.Y for p in points),max(p.Y for p in points),
                          min(p.Z for p in points),max(p.Z for p in points)))
        except Exception:
            return None
    if not boxes:
        return None
    return (min(b[0] for b in boxes),max(b[1] for b in boxes),
            min(b[2] for b in boxes),max(b[3] for b in boxes),
            min(b[4] for b in boxes),max(b[5] for b in boxes))


class StructureSource(object):
    """One approved linked or native/imported model, in its own coordinates."""
    def __init__(self, data):
        self.key=text_type(data.get('key') or '')
        self.label=text_type(data.get('label') or self.key or 'Selected structure')
        self.link=data.get('link')
        self.link_id=eidnum(self.link.Id) if self.link is not None else None
        self.transform=None
        self.inverse=None
        self.link_document=None
        self.transform_signature=None
        if self.link is not None:
            try:
                self.link_document=self.link.GetLinkDocument()
                if self.link_document is None:
                    raise ValueError('Structural link is unloaded')
                self.transform=self.link.GetTotalTransform()
                self.inverse=self.transform.Inverse
                self.transform_signature=_transform_signature(self.transform)
            except Exception as ex:
                raise ValueError(u'{}: link coordinates unavailable: {}'.format(self.label,ex))
        self.preferred=self._members(data.get('preferred'))
        self.fallback=self._members(data.get('fallback'))
        self.bounds={'preferred':{},'fallback':{}}
        self.bad_boxes=0
        self.reindex()

    @staticmethod
    def _members(values):
        if not values:
            return {}
        if hasattr(values,'items'):
            return dict((eidnum(k),v) for k,v in values.items())
        # Legacy native fallback constructor contains IDs, resolved when the
        # caller supplies its host document via bind_document / verify.
        return dict((eidnum(k),None) for k in values)

    def reindex(self):
        self.bad_boxes=0
        self.bounds={'preferred':{},'fallback':{}}
        for role in ('preferred','fallback'):
            for member_id,element in getattr(self,role).items():
                try:
                    if element is None:
                        self.bad_boxes+=1
                        continue
                    box=element.get_BoundingBox(None)
                    if box is None:
                        self.bad_boxes+=1
                        continue
                    self.bounds[role][member_id]=box_world(box,self.transform)
                except Exception:
                    self.bad_boxes+=1


class StructureChoice(object):
    """Geometry-backed priorities across all explicitly approved models.

    Positional (link, preferred, fallback_ids) remains supported for Repair
    Draft Rods. New callers pass source dictionaries with element maps.
    Bounding boxes only skip impossible rays; they never supply rod lengths.
    """
    def __init__(self,link=None,preferred=None,fallback=None,sources=None,
                 priority_mode='preferred_first', exact_small_selection=False):
        if priority_mode not in ('preferred_first','preferred_only','fallback_only'):
            raise ValueError('Unknown structural targeting priority')
        self.priority_mode=priority_mode
        self.exact_small_selection=bool(exact_small_selection)
        self.screen_mismatch_warnings=[]
        self.path_validator=None
        self.path_warnings=[]
        self.last_target_diagnostics=[]
        self._legacy=sources is None
        if sources is None:
            sources=[]
            if link is not None or preferred:
                sources.append({'key':'legacy-link-{}'.format(eidnum(link.Id))
                                if link is not None else 'legacy-native-preferred',
                                'label':readable_link(link) if link is not None
                                else 'Selected native framing',
                                'link':link,'preferred':preferred or {},'fallback':{}})
            if fallback:
                sources.append({'key':'legacy-native-fallback',
                                'label':'Selected native roof/deck','link':None,
                                'preferred':{},'fallback':fallback})
        self.sources=[source if isinstance(source,StructureSource)
                      else StructureSource(source) for source in sources]
        keys=[source.key for source in self.sources]
        if len(keys)!=len(set(keys)):
            raise ValueError('Structural model keys must be unique')
        self.link=link
        self.preferred=preferred or {}
        self.fallback=set(eidnum(k) for k in (fallback or []))
        # Legacy fields retain their exact per-link/native meaning. They must
        # never merge ElementIds from different model instances.
        if not self._legacy:
            linked=[s for s in self.sources if s.link is not None and s.preferred]
            if len(linked)==1:
                self.link=linked[0].link
                self.preferred=linked[0].preferred
            for source in self.sources:
                if source.link is None:
                    self.fallback.update(source.fallback)
        self.link_id=eidnum(self.link.Id) if self.link is not None else None
        self.transform=self.link.GetTotalTransform() if self.link is not None else None
        self.inverse=self.transform.Inverse if self.transform is not None else None
        self._refresh_legacy_index()

    @property
    def preferred_count(self):
        return sum(len(source.preferred) for source in self.sources)

    @property
    def fallback_count(self):
        return sum(len(source.fallback) for source in self.sources)

    def _refresh_legacy_index(self):
        self.bad_boxes=sum(source.bad_boxes for source in self.sources)
        self.bounds=[]
        self.indexed_ids=set()
        for source in self.sources:
            if source.link_id==self.link_id and source.preferred:
                for member_id,bounds in source.bounds['preferred'].items():
                    self.bounds.append((member_id,source.preferred[member_id],bounds))
                    self.indexed_ids.add(member_id)
                break

    def bind_document(self,doc):
        """Resolve legacy fallback IDs without hiding missing model elements."""
        from Autodesk.Revit.DB import ElementId
        changed=False
        for source in self.sources:
            if source.link is not None:
                continue
            for role in ('preferred','fallback'):
                members=getattr(source,role)
                for member_id,element in list(members.items()):
                    if element is None:
                        resolved=doc.GetElement(ElementId(member_id))
                        if resolved is None:
                            raise ValueError(u'{}: selected element {} is missing; reselect structure'
                                             .format(source.label,member_id))
                        members[member_id]=resolved
                        changed=True
            if changed:
                source.reindex()
        if changed:
            self._refresh_legacy_index()

    def preflight_unlocated(self):
        """Find unlocatable/unreadable selections once, before any placement.

        Missing boxes are allowed when actual Solid/Mesh geometry is readable.
        Unsupported selected objects require reselection, never guessed rods.
        """
        import rod_geometry
        from Autodesk.Revit.DB import Options
        issues=[]
        roles={'preferred_first':('preferred','fallback'),
               'preferred_only':('preferred',),
               'fallback_only':('fallback',)}[self.priority_mode]
        for source in self.sources:
            for role in roles:
                for member_id,element in getattr(source,role).items():
                    if member_id in source.bounds[role]:
                        continue
                    try:
                        primitives,failed=rod_geometry._checked_primitives(
                            element.get_Geometry(Options()))
                    except Exception:
                        primitives,failed=[],True
                    if failed or not primitives:
                        issues.append(u'{} / {} element {} has no readable location or Solid/Mesh geometry'
                                      .format(source.label,role,member_id))
                    else:
                        bounds=geometry_world_bounds(primitives,source.transform)
                        if bounds is not None:
                            source.bounds[role][member_id]=bounds
            source.bad_boxes=sum(len(getattr(source,role))-len(source.bounds[role])
                                 for role in ('preferred','fallback'))
        self._refresh_legacy_index()
        return issues

    def _role_target(self,base,max_length,role):
        import rod_geometry
        from Autodesk.Revit.DB import XYZ
        ceiling=base.Z+float(max_length)
        targets=[]
        unknown=[]
        # Auto Hanger's bounded field check: small approvals receive actual
        # intersections even when a supplied box would exclude the ray. Larger
        # inventories keep the screen to avoid unbounded IFC geometry scans.
        exact = self.exact_small_selection and 0 < sum(
            len(getattr(source, role)) for source in self.sources) <= 12
        for source in self.sources:
            counts = dict(selected=len(getattr(source, role)), xy=0, below=0,
                          beyond_limit=0, tested=0, miss=0, unknown=0, hit=0,
                          screen_bypassed=0, exact=exact, nearest=None)
            self.last_target_diagnostics.append((source.label, role, counts))
            # IFC reload/unload while the picker is open must not silently
            # switch this run to another link or its fallback roof.
            if source.link is not None:
                try:
                    current_doc=source.link.GetLinkDocument()
                    if current_doc is None:
                        raise ValueError('link is unloaded')
                    try:
                        same_doc=current_doc.Equals(source.link_document)
                    except AttributeError:
                        same_doc=current_doc is source.link_document
                    if not same_doc:
                        raise ValueError('link document changed')
                    current_signature=_transform_signature(source.link.GetTotalTransform())
                    if any(abs(a-b)>1e-7 for a,b in zip(current_signature,source.transform_signature)):
                        raise ValueError('link placement changed')
                except Exception:
                    raise ValueError(u'{} is missing, unloaded or changed; reselect structure'.format(source.label))
            a=XYZ(base.X,base.Y,base.Z)
            b=XYZ(base.X,base.Y,ceiling)
            if source.inverse is not None:
                a=source.inverse.OfPoint(a)
                b=source.inverse.OfPoint(b)
            counts['local_base']=(a.X,a.Y,a.Z)
            for member_id,element in getattr(source,role).items():
                if element is not None:
                    try:
                        if not element.IsValidObject:
                            raise ValueError(u'{} #{} changed during selection; reselect structure'
                                             .format(source.label,member_id))
                    except AttributeError:
                        pass
                bounds=source.bounds[role].get(member_id)
                excluded=False
                if bounds is not None:
                    dx=max(bounds[0]-base.X, 0.0, base.X-bounds[1])
                    dy=max(bounds[2]-base.Y, 0.0, base.Y-bounds[3])
                    gap=(dx*dx+dy*dy)**.5
                    nearest=counts['nearest']
                    if nearest is None or (gap,member_id)<(nearest[0],nearest[1]):
                        counts['nearest']=(gap,member_id,bounds)
                    if not rod_geometry._contains_world_xy(bounds,base):
                        excluded=True
                    else:
                        counts['xy'] += 1
                        if bounds[5]<base.Z-1e-8:
                            counts['below'] += 1
                            excluded=True
                        elif bounds[4]>ceiling+1e-8:
                            counts['beyond_limit'] += 1
                            excluded=True
                    if excluded and not exact:
                        continue
                    if excluded:
                        counts['screen_bypassed'] += 1
                if element is None:
                    unknown.append(u'{} #{}'.format(source.label,member_id))
                    continue
                counts['tested'] += 1
                state,z=rod_geometry._intersection_result(element,a,b,source.transform,base.Z)
                if state=='unknown':
                    counts['unknown'] += 1
                    unknown.append(u'{} #{}'.format(source.label,member_id))
                    continue
                if state!='hit':
                    counts['miss'] += 1
                    continue
                counts['hit'] += 1
                if excluded:
                    warning=u'BOUND SCREEN MISMATCH: {} / {} #{} has an actual rod hit at host Z {:.3f} ft despite its supplied bounds. Inspect IFC coordinates/bounds.'.format(
                        source.label,role,member_id,z)
                    if warning not in self.screen_mismatch_warnings and len(self.screen_mismatch_warnings)<8:
                        self.screen_mismatch_warnings.append(warning)
                try:
                    length=rod_geometry.target_length(base.Z,z,max_length)
                except ValueError:
                    # A measured but too-close first face is not a usable
                    # target. Try other approved members, then allowed fallback.
                    continue
                targets.append({'tier':'IFC' if role=='preferred' else 'ROOF',
                                'role':role,'source_key':source.key,
                                'source_label':source.label,'link_id':source.link_id,
                                'id':member_id,'z':float(z),'length':length})
        if unknown:
            raise ValueError(u'Approved {} geometry cannot be evaluated on this rod path: {}. '
                             u'Reselect or repair the structural model; fallback is withheld.'
                             .format(role,u', '.join(unknown[:5])))
        if not targets:
            return None
        targets.sort(key=lambda target:(target['z'],target['source_key'],target['id']))
        return targets[0]

    def target_for_rod(self,base,max_rod_ft):
        """Select an actual first-hit target independently for this rod XY."""
        if float(max_rod_ft)<.10:
            raise ValueError('Maximum rod length must be at least 0.10 ft')
        roles={'preferred_first':('preferred','fallback'),
               'preferred_only':('preferred',),
               'fallback_only':('fallback',)}[self.priority_mode]
        self.path_warnings=[]
        self.last_target_diagnostics=[]
        for role in roles:
            target=self._role_target(base,max_rod_ft,role)
            if target is not None:
                if self.path_validator is not None:
                    issues=self.path_validator(base,target)
                    if issues:
                        self.path_warnings.extend(text_type(issue) for issue in issues)
                        continue
                return target
        if self.path_warnings:
            raise ValueError(u'Approved rod paths are obstructed: {}'.format(
                u'; '.join(self.path_warnings[:5])))
        return None

    def target_diagnostic_text(self, base, max_length):
        lines=[u'Host rod base XYZ ({:.3f}, {:.3f}, {:.3f}) ft; limit {:.2f} ft; mode {}'.format(
            base.X, base.Y, base.Z, max_length, self.priority_mode)]
        for label, role, counts in self.last_target_diagnostics:
            lines.append(u'{} / {}: selected {}, XY-overlap {}, below {}, beyond limit {}, '
                         u'actual geometry tested {}, misses {}, unreadable {}, hits {}'.format(
                label, role, counts['selected'], counts['xy'], counts['below'],
                counts['beyond_limit'], counts['tested'], counts['miss'],
                counts['unknown'], counts['hit']))
            lines.append(u'Small-selection exact check {}; box exclusions tested {}'.format(
                'ON' if counts['exact'] else 'OFF (limit 12 approved members per role)',
                counts['screen_bypassed']))
            nearest=counts['nearest']
            if nearest is not None:
                gap,member_id,bounds=nearest
                lines.append(u'Nearest screen box #{}: plan gap {:.3f} ft; host X [{:.3f}, {:.3f}], '
                             u'Y [{:.3f}, {:.3f}], Z [{:.3f}, {:.3f}] ft (screen only)'.format(
                                 member_id,gap,*bounds))
            if 'local_base' in counts:
                lines.append(u'Source-local rod base XYZ ({:.3f}, {:.3f}, {:.3f}) ft'.format(
                    *counts['local_base']))
        return u'; '.join(lines)

    def over_preferred(self,origin,max_length):
        """Legacy status API, now based on measured multi-source geometry."""
        try:
            target=self._role_target(origin,max_length,'preferred')
        except ValueError:
            return 'unknown',None
        return ('yes',target['id']) if target is not None else ('no',None)

    def verify(self,hanger,max_rod_ft):
        """Every native attachment must match its measured chosen target."""
        from Autodesk.Revit.DB import XYZ
        info=None
        try:
            if hasattr(hanger,'Document'):
                self.bind_document(hanger.Document)
            info=hanger.GetRodInfo()
            if info is None or info.RodCount<1 or not info.IsAttachedToStructure:
                return False,'No native structural rod attachment',None
            levels=[]
            for i in range(info.RodCount):
                length=float(info.GetRodLength(i))
                if length<.10 or length>max_rod_ft:
                    return False,'Rod {} length {:.2f} ft outside 0.10-{:.1f} ft'.format(i,length,max_rod_ft),None
                top=info.GetRodEndPosition(i)
                base=XYZ(top.X,top.Y,top.Z-length)
                target=self.target_for_rod(base,max_rod_ft)
                if target is None:
                    return False,'Rod {} has no measurable approved structural target'.format(i),None
                attached=info.GetRodAttachedElementId(i)
                if attached is None:
                    return False,'Rod {} did not report a structural attachment'.format(i),None
                if target['link_id'] is None:
                    actual_link=eidnum(attached.LinkInstanceId)
                    actual_id=eidnum(attached.HostElementId)
                    correct=actual_link<0 and actual_id==target['id']
                else:
                    actual_link=eidnum(attached.LinkInstanceId)
                    actual_id=eidnum(attached.LinkedElementId)
                    correct=(actual_link==target['link_id'] and actual_id==target['id'])
                if not correct:
                    return False,(u'Rod {} attached to a different source/member than measured {} '
                                  u'{} #{} ({}); reselect or use an aligned unattached draft'
                                  .format(i,target['tier'],target['source_label'],target['id'],
                                          target['source_key'])),None
                if abs(top.Z-target['z'])>.08 or abs(length-target['length'])>.08:
                    return False,'Rod {} native tip does not match the measured structural underside'.format(i),None
                levels.append(target['tier'])
            return True,'Verified {} rods against their approved measured targets'.format(info.RodCount),'+'.join(sorted(set(levels)))
        except Exception as ex:
            return False,u'Rod attachment verification failed: {}'.format(ex),None
        finally:
            if info is not None:
                try: info.Dispose()
                except Exception: pass
