# -*- coding: utf-8 -*-
"""ROBMEPTOOLS Schedule Auto Number v0.8 (Revit 2025 / pyRevit IronPython).

Number drawing notes, hanger groups, or individual schedule instances.
Supports both IsItemized states; schedule configuration is never persisted as changed.
Also supports key-schedule note rows when an editable marker field is available.

Known scope: ordinary model-element schedules with numeric Count detail rows or
one displayed body row per grouped result; schedules with complex subtotals,
embedded schedules or ambiguous row/element mapping are intentionally rejected.
"""
import re
from pyrevit import revit, forms, script, DB
from System import Enum

TITLE = 'ROBMEPTOOLS | Schedule Auto Number v0.8'
BIP_COMMENTS = int(DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
BIP_MARK = int(DB.BuiltInParameter.ALL_MODEL_MARK)
BIP_FAB_ITEM = int(DB.BuiltInParameter.FABRICATION_PART_ITEM_NUMBER)
MAX_ELEMENTS = 12000
MAX_ROWS = 15000


def txt(x):
    if x is None:
        return u''
    try:
        return unicode(x)
    except NameError:
        return str(x)


def norm(x):
    return txt(x).strip().lower()


def eidval(x):
    return int(x.IntegerValue)


def stop(message):
    forms.alert(txt(message), title=TITLE, warn_icon=True)
    script.exit()


def get_schedule(doc, sid):
    s = doc.GetElement(DB.ElementId(sid))
    if s is None or not s.IsValidObject or not isinstance(s, DB.ViewSchedule):
        raise ValueError('The schedule could not be reloaded after a temporary transaction.')
    return s


def get_element(doc, eid):
    e = doc.GetElement(DB.ElementId(eid))
    if e is None or not e.IsValidObject:
        raise ValueError('Element {} no longer exists.'.format(eid))
    return e


def schedule_fields(s):
    return [s.Definition.GetField(fid) for fid in s.Definition.GetFieldOrder()]


def fname(f):
    try:
        return txt(f.GetName())
    except Exception:
        return txt(f.ColumnHeading)


def snapshot(s):
    """Capture displayed schedule, including any header/footer rows in Body."""
    cols = [f for f in schedule_fields(s) if not f.IsHidden]
    body = s.GetTableData().GetSectionData(DB.SectionType.Body)
    if len(cols) != int(body.NumberOfColumns):
        raise ValueError('Embedded/merged or custom-column schedule is not supported.')
    start = int(body.FirstRowNumber)
    last = int(body.LastRowNumber)
    if last < start or last - start > MAX_ROWS:
        raise ValueError('Schedule contains no rows or exceeds the safe row limit.')
    first_col = int(body.FirstColumnNumber)
    rows = []
    for r in range(start, last + 1):
        rows.append(tuple(txt(s.GetCellText(DB.SectionType.Body, r, first_col + i))
                          for i in range(len(cols))))
    return ([eidval(f.FieldId) for f in cols], rows)


def projected(snap, excluded):
    fids, rows = snap
    inds = [i for i, fid in enumerate(fids) if fid not in excluded]
    return [tuple(row[i] for i in inds) for row in rows]


def parameter_on(e, pid):
    if pid == -1 or pid is None:
        return None
    try:
        if pid < -1:
            p = e.get_Parameter(Enum.ToObject(DB.BuiltInParameter, pid))
            if p is not None:
                return p
    except Exception:
        pass
    try:
        for p in e.Parameters:
            if eidval(p.Id) == pid:
                return p
    except Exception:
        pass
    return None


def param_by_name(e, name):
    if not name:
        return None
    try:
        matches = [p for p in e.GetParameters(txt(name))]
        if len(matches) == 1:
            return matches[0]
    except Exception:
        pass
    return None


def field_parameter(e, pid, source_name):
    # Exact parameter ID preferred. Field ParameterId -1 has no direct ID,
    # so use only ONE identically named instance parameter, never a type param.
    p = parameter_on(e, pid)
    if p is not None:
        return p
    # A schedule field ID is not always exposed as the same ID on an
    # abstract key-row element. Name fallback is accepted only if UNIQUE.
    return param_by_name(e, source_name)


def writable(p, allow_int=False):
    return (p is not None and not p.IsReadOnly and
            (p.StorageType == DB.StorageType.String or
             (allow_int and p.StorageType == DB.StorageType.Integer)))


def param_type(p):
    if p.StorageType == DB.StorageType.Integer:
        return 'integer'
    return 'string'


def field_by_id(s, fieldid):
    for f in schedule_fields(s):
        if eidval(f.FieldId) == fieldid:
            return f
    raise ValueError('Schedule field {} disappeared.'.format(fieldid))


def field_source_ids(f):
    """Return all parameter IDs that a field depends upon."""
    result = set()
    pid = eidval(f.ParameterId)
    if pid != -1:
        result.add(pid)
    try:
        if f.FieldType == DB.ScheduleFieldType.CombinedParameter:
            for part in f.GetCombinedParameters():
                result.add(eidval(part.ParamId))
    except Exception:
        pass
    return result


def candidate_targets(doc, sid, ids):
    s = get_schedule(doc, sid)
    found = []
    expected = ('note', 'note number', 'drawing note', 'note #',
                'tag', 'part number', 'item number', 'hanger number',
                'hanger tag', 'mark', 'number')
    all_fields = schedule_fields(s)
    for f in all_fields:
        names = (norm(fname(f)), norm(f.ColumnHeading))
        if not any(name in expected for name in names):
            continue
        pid = eidval(f.ParameterId)
        elements = [get_element(doc, element_id) for element_id in ids]
        native = (pid == BIP_FAB_ITEM and
                  all(isinstance(e, DB.FabricationPart) for e in elements))
        ordinary = not native
        storage_types = []
        source_name = fname(f)
        for e in elements:
            if native:
                storage_types.append('string')
                continue
            p = field_parameter(e, pid, source_name)
            if not writable(p, allow_int=True):
                ordinary = False
                break
            storage_types.append(param_type(p))
        if not native and not ordinary:
            continue
        if len(set(storage_types)) != 1:
            continue
        dtype = storage_types[0]
        kind = 'native' if native else 'parameter'
        label = '{}{} ({}; param id {})'.format(
            fname(f), ' [hidden]' if f.IsHidden else '', dtype, pid)
        rank = (0 if 'note' in names and not f.IsHidden else
                1 if 'tag' in names and not f.IsHidden else
                2 if 'item number' in names and not f.IsHidden else
                3 if 'part number' in names and not f.IsHidden else
                4 if 'mark' in names and not f.IsHidden else
                5 if not f.IsHidden else 6)
        found.append((rank, label, kind, pid, eidval(f.FieldId),
                      not f.IsHidden, source_name, dtype))
    unique = []
    used = set()
    for item in sorted(found, key=lambda x: (x[0], norm(x[1]))):
        k = (item[2], item[3], norm(item[6]))
        if k not in used:
            used.add(k)
            unique.append(item)
    return unique


def read_number(doc, eid, chosen):
    kind, pid = chosen[2], chosen[3]
    e = get_element(doc, eid)
    if kind == 'native':
        return txt(e.ItemNumber)
    p = field_parameter(e, pid, chosen[6])
    if not writable(p, allow_int=True):
        raise ValueError('Number source is not a writable INSTANCE text/integer '
                         'parameter on {}.'.format(eid))
    return txt(p.AsInteger()) if chosen[7] == 'integer' else txt(p.AsString())


def write_number(doc, eid, chosen, value):
    e = get_element(doc, eid)
    kind, pid = chosen[2], chosen[3]
    if kind == 'native':
        e.ItemNumber = txt(value)
    else:
        p = field_parameter(e, pid, chosen[6])
        if not writable(p, allow_int=True) or param_type(p) != chosen[7]:
            raise ValueError('Number source became unavailable on {}.'.format(eid))
        actual = int(value) if chosen[7] == 'integer' else txt(value)
        ok = p.Set(actual)
        if ok is False:
            current = txt(p.AsInteger()) if chosen[7] == 'integer' else txt(p.AsString())
            if current != txt(actual):
                raise ValueError('Parameter rejected value on {}.'.format(eid))


def find_marker(doc, sid, ids, target_pid):
    """Find a writable temporary Comments/Mark instance text source not
    referenced anywhere in a schedule filter or sort/group field.
    """
    s = get_schedule(doc, sid)
    blocked_fids = set(eidval(x.FieldId) for x in s.Definition.GetFilters())
    blocked_fids.update(eidval(x.FieldId) for x in s.Definition.GetSortGroupFields())
    blocked_pids = set()
    for fid in blocked_fids:
        blocked_pids.update(field_source_ids(field_by_id(s, fid)))
    for pid, label in ((BIP_COMMENTS, 'Comments'), (BIP_MARK, 'Mark')):
        if pid == target_pid or pid in blocked_pids:
            continue
        if not all(writable(parameter_on(get_element(doc, eid), pid)) for eid in ids):
            continue
        existing = None
        for f in schedule_fields(s):
            if pid in field_source_ids(f) and eidval(f.ParameterId) == pid:
                existing = eidval(f.FieldId)
                break
        if existing is not None:
            return (pid, existing, None, label)
        for schedulable in s.Definition.GetSchedulableFields():
            if eidval(schedulable.ParameterId) == pid:
                return (pid, None, schedulable, label)
    raise ValueError(
        'No safe temporary Comments/Mark field is available to identify the '
        'physical hangers. Both must be editable instance text fields, and '
        'the chosen marker cannot be used by filters or sorting. Nothing changed.')


def rollback_group(group, tx):
    if tx is not None:
        try:
            tx.RollBack()
        except Exception:
            pass
    status = group.RollBack()
    if status != DB.TransactionStatus.RolledBack:
        raise ValueError('Revit could not CONFIRM temporary rollback; check Undo history.')


def scan_group_members(doc, sid, ids, orig_snap, marker_info, original_itemized=False):
    """Expand an existing grouped schedule temporarily; identify every
    instance with a unique Comments/Mark stamp. Group based on exactly the
    schedule's sort/group field display values, including hidden fields.
    ALL edits made in a TransactionGroup that is rolled back.
    """
    pid, old_marker_fid, schedulable, label = marker_info
    stamps = {'ROBMEP08_ID_{}__'.format(eid): eid for eid in ids}
    group = DB.TransactionGroup(doc, 'ROBMEP v0.8 row scan - automatic rollback')
    if group.Start() != DB.TransactionStatus.Started:
        raise ValueError('Unable to start temporary row-mapping transaction.')
    tx = None
    groups = []
    try:
        tx = DB.Transaction(doc, 'Temporary itemization and instance IDs')
        if tx.Start() != DB.TransactionStatus.Started:
            raise ValueError('Unable to start temporary schedule edit.')
        s = get_schedule(doc, sid)
        if not s.Definition.IsItemized:
            s.Definition.IsItemized = True
        if old_marker_fid is None:
            marker_fid = eidval(s.Definition.AddField(schedulable).FieldId)
        else:
            marker_fid = old_marker_fid
        field_by_id(s, marker_fid).IsHidden = False
        sorts = [eidval(x.FieldId) for x in s.Definition.GetSortGroupFields()]
        for fid in sorts:
            field_by_id(s, fid).IsHidden = False
        for stamp, element_id in stamps.items():
            p = parameter_on(get_element(doc, element_id), pid)
            result = p.Set(stamp)
            if result is False and txt(p.AsString()) != stamp:
                raise ValueError('Could not create a temporary row marker on {}.'.format(element_id))
        doc.Regenerate()
        if tx.Commit() != DB.TransactionStatus.Committed:
            raise ValueError('Revit did not accept the temporary itemized schedule.')
        tx = None
        temporary = snapshot(get_schedule(doc, sid))
        cols = temporary[0]
        if marker_fid not in cols:
            raise ValueError('Temporary ID column was not displayed in schedule.')
        marker_col = cols.index(marker_fid)
        sort_columns = [cols.index(fid) for fid in sorts]
        found = []
        for row in temporary[1]:
            stamp = txt(row[marker_col]).strip()
            if stamp in stamps:
                key = tuple(txt(row[i]) for i in sort_columns)
                found.append((key, stamps[stamp]))
            elif stamp.startswith('ROBMEP08_ID_'):
                raise ValueError('Unexpected or duplicated temporary ID in schedule row.')
        if len(found) != len(ids) or set(eid for key, eid in found) != set(ids):
            raise ValueError('Only {} of {} hangers mapped from itemized rows. '
                             'Cannot safely number this grouped schedule.'.format(
                                 len(found), len(ids)))
        keys_seen = set()
        for key, element_id in found:
            if original_itemized:
                groups.append((key, [element_id]))
                continue
            if not groups or groups[-1][0] != key:
                if key in keys_seen:
                    raise ValueError('A grouping key recurred out of order. '
                                     'Unable to map its row safely.')
                keys_seen.add(key)
                groups.append((key, [element_id]))
            else:
                groups[-1][1].append(element_id)
    finally:
        rollback_group(group, tx)
    # All API elements/schedule fields must be re-acquired after rollback.
    if snapshot(get_schedule(doc, sid)) != orig_snap:
        raise ValueError('Temporary scan did not restore original schedule view.')
    if bool(get_schedule(doc, sid).Definition.IsItemized) != bool(original_itemized):
        raise ValueError('Original Itemize setting was not restored.')
    return groups


def count_column(doc, sid, original):
    s = get_schedule(doc, sid)
    candidates = []
    for f in schedule_fields(s):
        if f.IsHidden:
            continue
        if f.FieldType == DB.ScheduleFieldType.Count:
            candidates.append(eidval(f.FieldId))
    if len(candidates) == 1:
        return original[0].index(candidates[0])
    if len(candidates) > 1:
        raise ValueError('Multiple visible Count fields; grouped row mapping is ambiguous.')
    return None


def parse_count(text):
    s = txt(text).strip().replace(',', '')
    if not re.match(r'^\d+$', s):
        return None
    n = int(s)
    return n if n > 0 else None


def pair_rows_and_groups(original, groups, count_idx, original_itemized=False,
                         key_schedule=False):
    # Key schedules have one row per abstract key (never toggle itemization).
    if key_schedule:
        if len(groups) != len(original[1]):
            raise ValueError('Key row count mismatches visible table rows.')
        return list(range(len(groups)))
    if original_itemized:
        if len(groups) != len(original[1]):
            raise ValueError('Itemized schedule contains {} element rows but {} '
                             'displayed body rows; header/footer rows need special '
                             'handling. No changes.'.format(len(groups), len(original[1])))
        if any(len(members) != 1 for _, members in groups):
            raise ValueError('Itemized scan unexpectedly included grouped parts.')
        return list(range(len(groups)))
    if count_idx is not None:
        rows = [(i, parse_count(row[count_idx])) for i, row in enumerate(original[1])]
        detail = [(i, n) for i, n in rows if n is not None]
        if len(detail) != len(groups):
            raise ValueError('Expected {} grouped detail rows but schedule has {} '
                             'positive Count rows. Subtotals or unusual header '
                             'layout may be present; nothing changed.'.format(
                                 len(groups), len(detail)))
        for j, ((row_idx, count), (_, members)) in enumerate(zip(detail, groups)):
            if count != len(members):
                raise ValueError('Group {}: Count {} differs from {} physical '
                                 'elements.'.format(j + 1, count, len(members)))
        return [i for i, n in detail]
    if len(original[1]) != len(groups):
        raise ValueError('No Count column: {} grouped elements versus {} body '
                         'rows. Add Count or simplify headers/footers.'.format(
                             len(groups), len(original[1])))
    return list(range(len(groups)))


def validate_original_sort_values(doc, sid, original, groups, detail_rows):
    """Check every originally visible sort/group value against its grouped
    detail row. Never rely on Count alone for associating a physical group.
    """
    s = get_schedule(doc, sid)
    sort_fids = [eidval(x.FieldId) for x in s.Definition.GetSortGroupFields()]
    if not sort_fids:
        return
    for group_index, ((key, members), row_i) in enumerate(zip(groups, detail_rows)):
        for key_i, sort_fid in enumerate(sort_fids):
            if sort_fid not in original[0]:
                continue
            grouped = txt(original[1][row_i][original[0].index(sort_fid)]).strip()
            itemized = txt(key[key_i]).strip()
            if grouped != itemized:
                raise ValueError(
                    'Group {} has a different displayed sort value in grouped '
                    'vs itemized mode (field {}). Cannot prove row order. '
                    'Nothing changed.'.format(group_index + 1, sort_fid))


def diagnostics(doc, sid, ids):
    s = get_schedule(doc, sid)
    parts = ['Schedule: {}'.format(s.Name), 'Scheduled elements: {}'.format(len(ids)),
             'Grouped: {}'.format(not s.Definition.IsItemized), 'Fields:']
    for f in schedule_fields(s):
        parts.append('  {} | heading {} | field {} | parameter {} | {}'.format(
            fname(f), txt(f.ColumnHeading), eidval(f.FieldId),
            eidval(f.ParameterId), 'hidden' if f.IsHidden else 'visible'))
    if ids:
        e = get_element(doc, ids[0])
        parts.append('Sample {} | {}'.format(ids[0], txt(e.GetType().Name)))
        for p in e.Parameters:
            try:
                if norm(p.Definition.Name) in ('tag', 'part number', 'item number', 'mark',
                                               'hanger number', 'note', 'note number'):
                    parts.append('  {} | pid {} | text {} | editable {}'.format(
                        p.Definition.Name, eidval(p.Id),
                        p.StorageType == DB.StorageType.String, not p.IsReadOnly))
            except Exception:
                pass
    return '\n'.join(parts)[:2300]


def request_options(schedule, chosen, row_count):
    title = norm(schedule.Name)
    if chosen[7] == 'integer':
        prefix = ''
    else:
        default = ('H-' if 'hanger' in title else
                   '' if ('note' in title or 'drawing' in title) else 'FSD-')
        prefix = forms.ask_for_string(
            default=default, prompt='Prefix (blank gives 1, 2, 3, ...)', title=TITLE)
        if prefix is None:
            script.exit()
    start_s = forms.ask_for_string(default='1', prompt='Starting number', title=TITLE)
    if start_s is None:
        script.exit()
    if chosen[7] == 'integer':
        digits = 1
    else:
        digits_s = forms.ask_for_string(default='1', prompt='Minimum digits (1-8)', title=TITLE)
        if digits_s is None:
            script.exit()
        try:
            digits = int(digits_s)
        except (ValueError, TypeError):
            stop('Minimum digits must be a whole number.')
    try:
        start = int(start_s)
    except (ValueError, TypeError):
        stop('Starting number must be a whole number.')
    if start < 0 or digits < 1 or digits > 8 or start + row_count > 999999:
        stop('Start must be >= 0, digits 1-8, ending number <= 999999.')
    return txt(prefix), start, digits


def collect_normal_ids(doc, sid):
    return sorted(eidval(e.Id) for e in
                  DB.FilteredElementCollector(doc, DB.ElementId(sid))
                    .WhereElementIsNotElementType().ToElements())


def collect_key_ids(doc, sid):
    # Key-schedule rows are actual abstract database Elements whose owner
    # view is the key schedule. First try the view-scoped owner filter.
    result = []
    try:
        result = [eidval(e.Id) for e in DB.FilteredElementCollector(doc)
                  .OwnedByView(DB.ElementId(sid))
                  .WhereElementIsNotElementType().ToElements()]
    except Exception:
        pass
    if not result:
        # Safety fallback; filter strictly by OwnerViewId.
        result = [eidval(e.Id) for e in DB.FilteredElementCollector(doc)
                  .WhereElementIsNotElementType().ToElements()
                  if e.OwnerViewId is not None and
                  eidval(e.OwnerViewId) == sid]
    return sorted(set(result))


def find_key_marker(doc, sid, ids, target_fid):
    s = get_schedule(doc, sid)
    blocked = set(eidval(x.FieldId) for x in s.Definition.GetFilters())
    blocked.update(eidval(x.FieldId) for x in s.Definition.GetSortGroupFields())
    blocked.add(target_fid)
    choices = []
    for f in schedule_fields(s):
        fid = eidval(f.FieldId)
        if f.IsHidden or fid in blocked:
            continue
        pid = eidval(f.ParameterId)
        source = fname(f)
        if all(writable(field_parameter(get_element(doc, eid), pid, source))
               for eid in ids):
            choices.append((fid, pid, source))
    if not choices:
        raise ValueError('This key schedule has no spare visible, writable '
                         'text field to identify its rows safely. Add a spare '
                         'instance text column (e.g. Comments) and rerun; '
                         'nothing changed.')
    return choices[0]


def scan_key_members(doc, sid, ids, original, marker):
    fid, pid, source = marker
    stamps = {'ROBMEP08_KEY_{}__'.format(eid): eid for eid in ids}
    group = DB.TransactionGroup(doc, 'ROBMEP v0.8 key row scan - rollback')
    if group.Start() != DB.TransactionStatus.Started:
        raise ValueError('Cannot start temporary key scan.')
    tx = None
    mapped = []
    try:
        tx = DB.Transaction(doc, 'Temporary key row identification')
        if tx.Start() != DB.TransactionStatus.Started:
            raise ValueError('Could not create temporary key tags.')
        for stamp, eid in stamps.items():
            e = get_element(doc, eid)
            p = field_parameter(e, pid, source)
            if not writable(p):
                raise ValueError('Key row cannot be marked.')
            p.Set(stamp)
        doc.Regenerate()
        if tx.Commit() != DB.TransactionStatus.Committed:
            raise ValueError('Could not verify temporary key row marks.')
        tx = None
        snap = snapshot(get_schedule(doc, sid))
        if snap[0] != original[0] or fid not in snap[0]:
            raise ValueError('Key schedule structure changed during row scan.')
        idx = snap[0].index(fid)
        for row_idx, row in enumerate(snap[1]):
            stamp = txt(row[idx]).strip()
            if stamp in stamps:
                mapped.append((row_idx, stamps[stamp]))
            elif stamp.startswith('ROBMEP08_KEY_'):
                raise ValueError('Ambiguous key schedule row identification.')
        if len(mapped) != len(ids) or set(eid for r,eid in mapped) != set(ids):
            raise ValueError('Mapped {} of {} key schedule rows; cannot safely '
                             'number this schedule.'.format(len(mapped),len(ids)))
        if [i for i, e in mapped] != list(range(len(snap[1]))):
            raise ValueError('Key schedule contains unmapped header/subtotal rows.')
    finally:
        rollback_group(group, tx)
    if snapshot(get_schedule(doc, sid)) != original:
        raise ValueError('Original key schedule did not restore after scan.')
    return [(('key', row_idx), [eid]) for row_idx, eid in mapped]



# v0.8: no spare Comments/Mark is required if the number parameter itself
# is not referenced by any filter or sorting/grouping field. All temporary
# changes are made inside a TransactionGroup, which is rolled back.
def safe_target_marker(doc, sid, chosen):
    s = get_schedule(doc, sid)
    dest_fid = chosen[4]
    dest_pid = chosen[3]
    if dest_fid not in [eidval(f.FieldId) for f in schedule_fields(s)]:
        raise ValueError('Numbering field is not a field in this schedule.')
    for sg in list(s.Definition.GetSortGroupFields()) + list(s.Definition.GetFilters()):
        f = field_by_id(s, eidval(sg.FieldId))
        if eidval(f.FieldId) == dest_fid:
            raise ValueError('The numbering field is used by schedule sorting/filtering. '
                'Without a spare writable instance Comments/Mark parameter, its '
                'values cannot be temporarily stamped safely. Nothing changed. '
                'To enable this schedule, add a separate writable instance TEXT '
                'parameter such as ROBMEP Row ID and include it in the schedule, '
                'or change the schedule sort/filter to not reference the number.')
        if dest_pid != -1 and dest_pid in field_source_ids(f):
            raise ValueError('Another sort/filter field depends on the numbering '
                'parameter. Cannot temporarily identify rows safely; no changes.')
    return ('target', chosen)


def target_stamps(doc, ids, chosen):
    """Unique text or integer stamps, avoiding collisions with existing values."""
    existing = set(read_number(doc, eid, chosen) for eid in ids)
    stamps = {}
    offset = 0
    for eid in ids:
        while True:
            if chosen[7] == 'integer':
                # Fit in signed 32-bit storage and stay distinct from actual notes.
                marker = int(1600000000 + offset)
            else:
                marker = u'__ROBMEP08_TEMP_{}_{}__'.format(eid, offset)
            offset += 1
            if txt(marker) not in existing and txt(marker) not in stamps:
                break
        stamps[txt(marker)] = eid
    return stamps


def normalized_stamp_display(value, integer=False):
    raw = txt(value).strip()
    if integer:
        return raw.replace(',', '').replace(' ', '')
    return raw


def scan_group_members_target(doc, sid, ids, orig_snap, chosen, original_itemized=False):
    """Use numbering target as the temporary, reversible row-ID column.

    Only safe when it does NOT drive schedule filters or sorts (validated first).
    Existing target values are completely restored by TransactionGroup rollback.
    """
    safe_target_marker(doc, sid, chosen)
    stamps = target_stamps(doc, ids, chosen)
    outer = DB.TransactionGroup(doc, 'ROBMEP v0.8 target row scan - rollback')
    if outer.Start() != DB.TransactionStatus.Started:
        raise ValueError('Could not start temporary target scan.')
    tx = None
    groups = []
    try:
        tx = DB.Transaction(doc, 'Temporary number-field row identifiers')
        if tx.Start() != DB.TransactionStatus.Started:
            raise ValueError('Could not start temporary row scan transaction.')
        s = get_schedule(doc, sid)
        if not s.Definition.IsItemized:
            s.Definition.IsItemized = True
        target_fid = chosen[4]
        field_by_id(s, target_fid).IsHidden = False
        sort_fids = [eidval(x.FieldId) for x in s.Definition.GetSortGroupFields()]
        for fid in sort_fids:
            field_by_id(s, fid).IsHidden = False
        for stamp, eid in stamps.items():
            write_number(doc, eid, chosen, int(stamp) if chosen[7] == 'integer' else stamp)
        doc.Regenerate()
        if tx.Commit() != DB.TransactionStatus.Committed:
            raise ValueError('Revit rejected the temporary target row scan.')
        tx = None
        scanned = snapshot(get_schedule(doc, sid))
        cols = scanned[0]
        if target_fid not in cols:
            raise ValueError('Numbering target not displayed in temporary scan.')
        id_col = cols.index(target_fid)
        sort_cols = [cols.index(fid) for fid in sort_fids]
        seen = set()
        found = []
        for row in scanned[1]:
            stamp = normalized_stamp_display(row[id_col], chosen[7] == 'integer')
            if stamp in stamps:
                if stamp in seen:
                    raise ValueError('Duplicated target stamp during temporary scan.')
                seen.add(stamp)
                found.append((tuple(txt(row[i]) for i in sort_cols), stamps[stamp]))
        if len(found) != len(ids) or set(e for k, e in found) != set(ids):
            raise ValueError('Temporary number-field row scan matched {} of {} '
                'elements. This schedule needs a separate row-identification field.'
                .format(len(found), len(ids)))
        observed_keys = set()
        for key, element_id in found:
            if original_itemized:
                groups.append((key, [element_id]))
            elif not groups or groups[-1][0] != key:
                if key in observed_keys:
                    raise ValueError('Original grouping keys became noncontiguous.')
                observed_keys.add(key)
                groups.append((key, [element_id]))
            else:
                groups[-1][1].append(element_id)
    finally:
        rollback_group(outer, tx)
    if snapshot(get_schedule(doc, sid)) != orig_snap:
        raise ValueError('Temporary number-field scan did not restore the schedule.')
    if bool(get_schedule(doc,sid).Definition.IsItemized) != bool(original_itemized):
        raise ValueError('Temporary number scan did not restore Itemize option.')
    return groups


def scan_key_members_target(doc, sid, ids, original, chosen):
    safe_target_marker(doc, sid, chosen)
    stamps = target_stamps(doc, ids, chosen)
    outer = DB.TransactionGroup(doc, 'ROBMEP v0.8 key number scan - rollback')
    if outer.Start() != DB.TransactionStatus.Started:
        raise ValueError('Could not start temporary key scan.')
    tx = None
    mapped = []
    try:
        tx = DB.Transaction(doc, 'Temporary key number identifiers')
        if tx.Start() != DB.TransactionStatus.Started:
            raise ValueError('Could not start key scan transaction.')
        s = get_schedule(doc, sid)
        field_by_id(s, chosen[4]).IsHidden = False
        for stamp, eid in stamps.items():
            write_number(doc, eid, chosen, int(stamp) if chosen[7]=='integer' else stamp)
        doc.Regenerate()
        if tx.Commit() != DB.TransactionStatus.Committed:
            raise ValueError('Revit rejected temporary key scan.')
        tx = None
        scanned = snapshot(get_schedule(doc, sid))
        if chosen[4] not in scanned[0]:
            raise ValueError('Cannot find number field after temporary key scan.')
        col = scanned[0].index(chosen[4])
        seen = set()
        for row_idx, row in enumerate(scanned[1]):
            stamp = normalized_stamp_display(row[col], chosen[7]=='integer')
            if stamp in stamps:
                if stamp in seen:
                    raise ValueError('Duplicate key-row identifier.')
                seen.add(stamp)
                mapped.append((row_idx, stamps[stamp]))
        if len(mapped) != len(ids) or set(e for r,e in mapped) != set(ids):
            raise ValueError('Could not match every key schedule row to its element.')
        if [r for r,e in mapped] != list(range(len(scanned[1]))):
            raise ValueError('Key schedule contains unmapped row/headers.')
    finally:
        rollback_group(outer, tx)
    if snapshot(get_schedule(doc, sid)) != original:
        raise ValueError('Key row temporary scan did not restore original values.')
    return [(('key', i), [eid]) for i,eid in mapped]


def scan_members(doc, sid, ids, original, chosen, key_schedule, itemized):
    if key_schedule:
        try:
            marker = find_key_marker(doc, sid, ids, chosen[4])
        except ValueError:
            marker = safe_target_marker(doc, sid, chosen)
        groups = (scan_key_members_target(doc, sid, ids, original, chosen)
                  if marker[0] == 'target' else
                  scan_key_members(doc, sid, ids, original, marker))
        return groups, marker
    try:
        marker = find_marker(doc, sid, ids, chosen[3])
    except ValueError:
        marker = safe_target_marker(doc, sid, chosen)
    groups = (scan_group_members_target(doc, sid, ids, original, chosen,
                                       original_itemized=itemized)
              if marker[0] == 'target' else
              scan_group_members(doc, sid, ids, original, marker,
                                 original_itemized=itemized))
    return groups, marker


def run():
    doc = revit.doc
    active = doc.ActiveView
    if not isinstance(active, DB.ViewSchedule) or active.IsTemplate:
        stop('Open the desired drawing notes, hanger or fabrication schedule first.')
    sid = eidval(active.Id)
    s = get_schedule(doc, sid)
    key_schedule = bool(s.Definition.IsKeySchedule)
    itemized = bool(s.Definition.IsItemized) if not key_schedule else True
    if s.Definition.HasEmbeddedSchedule:
        stop('Embedded schedules are not supported by v0.8.')
    if not key_schedule and s.Definition.IncludeLinkedFiles:
        stop('Linked-file elements cannot be safely renumbered.')
    outer = None
    tx = None
    try:
        ids = collect_key_ids(doc, sid) if key_schedule else collect_normal_ids(doc, sid)
        if not ids:
            raise ValueError('No writable schedule row elements found.\n'
                             'Key schedule: {}. Make sure this is a model schedule '
                             'containing actual items.'.format(key_schedule))
        if len(ids) > MAX_ELEMENTS:
            raise ValueError('Schedule has {} rows/elements; limit is {}.'.format(
                len(ids), MAX_ELEMENTS))
        before = snapshot(get_schedule(doc, sid))
        candidates = candidate_targets(doc, sid, ids)
        if not candidates:
            raise ValueError('No editable instance Note/Note Number/Tag/Item Number/'
                             'Part Number field was found IN THIS SCHEDULE.\n'
                             'Use an instance TEXT or INTEGER Note parameter; '
                             'type parameters and calculated columns are not '
                             'supported for row numbering.\n\n' +
                             diagnostics(doc, sid, ids))
        if len(candidates) == 1:
            chosen = candidates[0]
        else:
            labels = [x[1] for x in candidates]
            selected = forms.SelectFromList.show(
                labels, title='Choose the parameter that holds the note/part number',
                button_name='Use this field')
            if selected is None:
                script.exit()
            chosen = candidates[labels.index(selected)]
        label, target_fid, target_visible = chosen[1], chosen[4], chosen[5]
        sortfieldids = set(eidval(x.FieldId) for x in
                           get_schedule(doc, sid).Definition.GetSortGroupFields())
        # Temporary itemization cannot preserve aggregated Count sorting.
        if not key_schedule and not itemized:
            for sort_fid in sortfieldids:
                if field_by_id(get_schedule(doc, sid), sort_fid).FieldType == DB.ScheduleFieldType.Count:
                    raise ValueError('Sorting by aggregated Count cannot be mapped '
                                     'safely in grouped mode.')
        groups, marker = scan_members(doc, sid, ids, before, chosen,
                                       key_schedule, itemized)
        if not groups:
            raise ValueError('No schedule detail rows could be mapped.')
        detail_rows = pair_rows_and_groups(
            before, groups, None if key_schedule else count_column(doc, sid, before),
            original_itemized=itemized, key_schedule=key_schedule)
        if not key_schedule:
            validate_original_sort_values(doc, sid, before, groups, detail_rows)
        prefix, start, digits = request_options(get_schedule(doc, sid),
                                                chosen, len(groups))
        changes = []
        for i, (key, members) in enumerate(groups):
            val = start + i
            assigned = (int(val) if chosen[7] == 'integer' else
                        prefix + txt(val).zfill(digits))
            changes.append((detail_rows[i], list(members), assigned))
        original_ids = set(ids)
        preview = '\n'.join('Row {} | {} {} -> {}'.format(
            r + 1, len(m), 'instance' if len(m) == 1 else 'instances', n)
            for r, m, n in changes[:12])
        mode = ('Key schedule (one key per row)' if key_schedule else
                'Itemize every instance: {}'.format('ON' if itemized else 'OFF (grouped)'))
        warning = ('\nNote: target field is used for Sorting/Grouping. Revit may '
                   'move rows; if so ALL numbering is rolled back.\n'
                   if target_fid in sortfieldids else '')
        if not forms.alert('Schedule: {}\nMode: {}\nNumbered rows: {}\n'
                           'Underlying elements: {}\nParameter: {}\n'
                           'No lasting schedule configuration changes.{}\n\n'
                           'Preview:\n{}\n\nWrite these numbers?'.format(
                               get_schedule(doc, sid).Name, mode,
                               len(changes), len(ids), label, warning, preview),
                           title='ROBMEPTOOLS | Confirm schedule numbering v0.8',
                           yes=True, no=True, ok=False):
            script.exit()
        outer = DB.TransactionGroup(doc, 'ROBMEP v0.8 schedule auto numbering')
        if outer.Start() != DB.TransactionStatus.Started:
            raise ValueError('Unable to start numbering transaction group.')
        tx = DB.Transaction(doc, 'Set note or part numbers by schedule row')
        if tx.Start() != DB.TransactionStatus.Started:
            raise ValueError('Unable to start numbering transaction.')
        for row_idx, member_ids, number in changes:
            for eid in member_ids:
                write_number(doc, eid, chosen, number)
        doc.Regenerate()
        if tx.Commit() != DB.TransactionStatus.Committed:
            raise ValueError('Revit rejected the numbering transaction.')
        tx = None
        for row_idx, members, number in changes:
            for eid in members:
                if read_number(doc, eid, chosen) != txt(number):
                    raise ValueError('Number verification failed on element {}.'.format(eid))
        after = snapshot(get_schedule(doc, sid))
        if before[0] != after[0] or len(before[1]) != len(after[1]):
            raise ValueError('Schedule columns or row count changed; rolling back.')
        if projected(before, set([target_fid])) != projected(after, set([target_fid])):
            raise ValueError('Schedule data/grouping/row order changed; '
                             'all numbers were rolled back.')
        post_ids = (set(collect_key_ids(doc, sid)) if key_schedule else
                    set(collect_normal_ids(doc, sid)))
        if post_ids != original_ids:
            raise ValueError('Scheduled element membership changed; rolling back.')
        if marker[0] == 'target':
            new_groups = (scan_key_members_target(doc, sid, ids, after, chosen)
                          if key_schedule else scan_group_members_target(
                              doc, sid, ids, after, chosen,
                              original_itemized=itemized))
        else:
            new_groups = (scan_key_members(doc, sid, ids, after, marker)
                          if key_schedule else scan_group_members(
                              doc, sid, ids, after, marker,
                              original_itemized=itemized))
        new_rows = pair_rows_and_groups(
            after, new_groups, None if key_schedule else count_column(doc,sid,after),
            original_itemized=itemized, key_schedule=key_schedule)
        if not key_schedule:
            validate_original_sort_values(doc, sid, after, new_groups, new_rows)
        if new_rows != detail_rows or len(new_groups) != len(groups):
            raise ValueError('Displayed row mapping changed after numbering.')
        for old, new in zip(groups, new_groups):
            if set(old[1]) != set(new[1]):
                raise ValueError('Elements moved to different schedule rows.')
        if target_visible:
            col_idx = before[0].index(target_fid)
            for row_idx, members, number in changes:
                displayed = txt(after[1][row_idx][col_idx]).strip()
                if displayed != txt(number):
                    raise ValueError('Row {} displays {!r}, expected {!r}; '
                                     'numbering cancelled.'.format(
                                         row_idx+1, displayed, txt(number)))
        if (not key_schedule and bool(get_schedule(doc,sid).Definition.IsItemized)
                != bool(itemized)):
            raise ValueError('Original Itemize option changed; rolling back.')
        if outer.Assimilate() != DB.TransactionStatus.Committed:
            raise ValueError('Unable to finalize schedule numbering.')
        outer = None
        forms.alert('Numbered {} rows / {} elements.\nFirst: {}\nLast: {}\n'
                    'Itemize mode and schedule settings preserved.'.format(
                        len(changes), len(ids), changes[0][2], changes[-1][2]),
                    title=TITLE, warn_icon=False)
    except Exception as error:
        if tx is not None:
            try:
                tx.RollBack()
            except Exception:
                pass
        if outer is not None:
            try:
                if outer.RollBack() != DB.TransactionStatus.RolledBack:
                    raise ValueError('Revit did not confirm rollback; inspect Undo history.')
            except Exception as rb_error:
                stop('Rollback could not be confirmed! Inspect Revit Undo.\n\n' +
                     txt(rb_error))
        stop('No numbering was saved.\n\n{}'.format(txt(error)[:3500]))


if __name__ == '__main__':
    run()
