# -*- coding: utf-8 -*-
"""Project-specific IFC/type approval UI for the existing Auto Hanger button."""
import json
import os

import structure_catalog as catalog
import structure_discovery as discovery

_PRIORITIES = ('preferred_first', 'preferred_only', 'fallback_only')


def build_sources(models, selections, explicit_picks=None):
    """Resolve approved stable types/member tokens into current runtime elements.

    Individual picks override the role of a type-selected element. A type is
    never approved solely because it was detected or classified as IFC.
    """
    result = []
    explicit_picks = explicit_picks or {}
    for model in models:
        if not model.get('loaded'):
            continue
        preferred, fallback = {}, {}
        roles = selections.get(model['key'], {})
        picks = explicit_picks.get(model['key'], {})
        for group in model.get('groups', []):
            group_role = roles.get(group['key'])
            for record in group.get('records', []):
                role = picks.get(catalog.element_token(record), group_role)
                element = record.get('element')
                if element is None or role not in ('preferred', 'fallback'):
                    continue
                destination = preferred if role == 'preferred' else fallback
                destination[record['id']] = element
        if preferred or fallback:
            result.append({'key': model['key'], 'label': model['label'],
                           'link': model.get('link'), 'preferred': preferred,
                           'fallback': fallback})
    return result


def selection_counts(models, selections, explicit_picks=None):
    sources = build_sources(models, selections, explicit_picks)
    return (len(sources), sum(len(source['preferred']) for source in sources),
            sum(len(source['fallback']) for source in sources))


def _framing_group(group):
    """Bulk framing approval omits columns, proxies and ambiguous objects."""
    classification = group.get('ifc_class', '').lower()
    category = group.get('category', '').lower()
    if 'column' in classification or 'column' in category:
        return False
    if 'proxy' in classification:
        return False
    if classification:
        return classification in ('ifcbeam', 'ifcmember')
    return (bool(group.get('framing_hint')) or 'structural framing' in category or
            any(record.get('category_role') == 'framing' for record in group.get('records', [])))


def _surface_group(group):
    if any(record.get('category_role') == 'surface' for record in group.get('records', [])):
        return True
    if 'proxy' in group.get('ifc_class', '').lower():
        return False
    return bool(group.get('surface_hint'))


def _read_preferences():
    from pyrevit import script
    config = script.get_config('universal_ifc_structure')
    try:
        data = json.loads(config.project_preferences_json)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_preferences(project, models, selections, picks, max_rod, priority):
    from pyrevit import script
    data = _read_preferences()
    data[catalog.project_key(project)] = catalog.make_preferences(
        project, models, selections, max_rod, priority_mode=priority,
        explicit_picks=picks)
    config = script.get_config('universal_ifc_structure')
    config.project_preferences_json = json.dumps(data, sort_keys=True,
                                                  ensure_ascii=True)
    script.save_config()


def _choose_link_ids(doc, saved):
    """Choose sources before inventorying thousands of unrelated elements."""
    from pyrevit import forms
    options = discovery.link_options(doc)
    if not options:
        return set()
    previous = saved.get('models', {}) if isinstance(saved, dict) else {}
    unloaded = [row['label'] for row in options if not row['loaded']]
    if unloaded:
        forms.alert(u'Unloaded structural/model links: {}. Load the required IFC link '
                    u'or choose another source.'.format(u', '.join(unloaded)))

    class SourceOption(forms.TemplateListItem):
        @property
        def name(self):
            return self.item['label']

    native = {'id': None, 'label': 'Native roof/deck only (no IFC link)'}
    rows = [SourceOption(native, checked=False)]
    for row in options:
        if row['loaded']:
            rows.append(SourceOption(row, checked=row['key'] in previous))
    if len(rows) == 1:
        return set()
    selected = forms.SelectFromList.show(rows, multiselect=True,
        title='ROB MEP | Choose IFC structural model(s)',
        button_name='Load selected structure')
    if not selected:
        return None
    ids = set()
    for row in selected:
        item = getattr(row, 'item', row)
        if item['id'] is not None:
            ids.add(item['id'])
    return ids


def visible_groups(model, include_other=False):
    """Framing and deck only by default; custom IFC remains explicit review."""
    if include_other:
        return list(model.get('groups', []))
    return [group for group in model.get('groups', [])
            if _framing_group(group) or _surface_group(group)]


def _direct_pick(uidoc, models, selections, picks, role):
    from Autodesk.Revit.DB import RevitLinkInstance
    from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
    from Autodesk.Revit.Exceptions import OperationCanceledException
    from pyrevit import forms

    mode = forms.CommandSwitchWindow.show(
        ['Linked structural members', 'Native / imported structural members'],
        message='Pick individual beams, joists or approved structural surfaces')
    if not mode:
        return
    linked = mode.startswith('Linked')
    by_link_id = {}
    host_model = None
    record_maps = {}
    for model in models:
        if not model.get('loaded'):
            continue
        record_maps[model['key']] = dict((record['id'], record)
                                        for record in model['records'])
        if model.get('link') is None:
            host_model = model
        else:
            by_link_id[discovery.eidnum(model['link'].Id)] = model

    class StructureFilter(ISelectionFilter):
        def AllowElement(self, element):
            try:
                if linked:
                    return (isinstance(element, RevitLinkInstance) and
                            discovery.eidnum(element.Id) in by_link_id)
                return (host_model is not None and
                        discovery.eidnum(element.Id) in record_maps[host_model['key']])
            except Exception:
                return False

        def AllowReference(self, reference, point):
            try:
                if not linked:
                    return True
                model = by_link_id.get(discovery.eidnum(reference.ElementId))
                return (model is not None and discovery.eidnum(reference.LinkedElementId)
                        in record_maps[model['key']])
            except Exception:
                return False

    try:
        references = uidoc.Selection.PickObjects(
            ObjectType.LinkedElement if linked else ObjectType.Element,
            StructureFilter(),
            'ROB MEP: select approved structure, then Finish (Esc keeps prior selection)')
    except OperationCanceledException:
        return
    pending = []
    for reference in references:
        if linked:
            model = by_link_id.get(discovery.eidnum(reference.ElementId))
            element_id = discovery.eidnum(reference.LinkedElementId)
        else:
            model = host_model
            element_id = discovery.eidnum(reference.ElementId)
        if model is None:
            continue
        record = record_maps[model['key']].get(element_id)
        token = catalog.element_token(record) if record else ''
        if token:
            pending.append((model['key'], token))
    # Finish commits the additions; cancellation leaves the existing picks intact.
    for model_key, token in pending:
        picks.setdefault(model_key, {})[token] = role


def choose_structure(doc, uidoc, startup_ids=None):
    """Always confirm current project discovery; return None on cancellation.

    The returned save_preferences(max_rod) callback is invoked by the main
    settings window only after Run is confirmed, so both windows save the final
    rod limit together. Existing duct/service/planning settings stay independent.
    """
    from pyrevit import forms
    from System.Windows import Thickness
    from System.Windows.Controls import (TreeViewItem, StackPanel, TextBlock,
                                         CheckBox, ComboBox, Orientation)
    project = discovery.project_identity(doc)
    saved = _read_preferences().get(catalog.project_key(project))
    selected_ids = _choose_link_ids(doc, saved)
    if selected_ids is None:
        return None
    if hasattr(forms, 'ProgressBar'):
        with forms.ProgressBar(title='Reading selected structure', step=1) as bar:
            def report(label, current, total):
                bar.title = u'Reading structure: {} — {{value}}/{{max_value}}'.format(label)
                bar.update_progress(current, total)
            models = discovery.discover_structure(doc, selected_link_ids=selected_ids,
                                                   focused=True, progress=report)
    else:
        models = discovery.discover_structure(doc, selected_link_ids=selected_ids, focused=True)
    restored = catalog.restore_preferences(project, models, saved)
    selections = restored.get('selections', {})
    picks = restored.get('explicit_picks', {})
    # Old broad model/category approvals must not silently reapprove custom
    # host objects after the focused-menu upgrade. Specific member picks stay
    # explicit, but general roles are limited to framing/deck until reviewed.
    for model in models:
        allowed = set(group['key'] for group in visible_groups(model))
        selections[model['key']] = dict((key, role) for key, role in
            selections.get(model['key'], {}).items() if key in allowed)
    # Existing native framing/deck preselection remains a pending approval in
    # this window. Unknown objects never acquire a role from mere preselection.
    native_ids = set(discovery.eidnum(value) for value in (startup_ids or []))
    for model in models:
        if model.get('link') is None:
            for group in model.get('groups', []):
                for record in group['records']:
                    if record['id'] in native_ids and (group.get('framing_hint') or group.get('surface_hint')):
                        token = catalog.element_token(record)
                        if token:
                            picks.setdefault(model['key'], {})[token] = 'fallback' if group.get('surface_hint') else 'preferred'
    warnings = list(restored.get('warnings', []))
    for model in models:
        warnings.extend(u'{}: {}'.format(model['label'], warning)
                        for warning in model.get('warnings', []))
    if not any(model.get('records') for model in models):
        forms.alert('No loaded structural/imported model geometry could be inventoried. '
                    'Load the structural model and run Auto Hanger again.')
        return None

    class StructureWindow(forms.WPFWindow):
        def __init__(self):
            forms.WPFWindow.__init__(self, os.path.join(os.path.dirname(__file__),
                                                       'structure_picker.xaml'))
            self.result = None
            self.pick_requested = False
            self.model_checks = []
            self.category_checks = []
            self.type_checks = []
            self.parent_checks = []
            self.maxRodBox.Text = str(restored.get('max_rod', 20.0))
            priority = restored.get('priority_mode', 'preferred_first')
            self.priorityBox.SelectedIndex = _PRIORITIES.index(priority) if priority in _PRIORITIES else 0
            self.pickRoleBox.SelectedIndex = 0
            self.warningText.Text = (u'\n'.join(warnings) if warnings else
                                     'Confirm the approved structural types for this project. '
                                     'No discovered Generic Model or proxy is approved automatically.')
            self.allFramingButton.Click += self.select_framing
            self.clearButton.Click += self.clear_selection
            self.showOtherCheck.Checked += self.on_filter
            self.showOtherCheck.Unchecked += self.on_filter
            self.pickButton.Click += self.request_pick
            self.cancelButton.Click += self.cancel
            self.confirmButton.Click += self.confirm
            self.refresh_tree()

        def on_filter(self, sender, args):
            self.refresh_tree()

        def check(self, label, enabled=True):
            checkbox = CheckBox()
            checkbox.Content = label
            checkbox.IsEnabled = enabled
            checkbox.Margin = Thickness(0, 2, 10, 2)
            return checkbox

        def bulk(self, model, groups, enable):
            roles = selections.setdefault(model['key'], {})
            for group in groups:
                if enable:
                    # A model/section checkbox never authorizes all proxies.
                    if _framing_group(group) or _surface_group(group):
                        roles.setdefault(group['key'], 'fallback' if group.get('surface_hint') else 'preferred')
                else:
                    roles.pop(group['key'], None)
                    tokens = set(catalog.element_token(record) for record in group['records'])
                    selected = picks.get(model['key'], {})
                    for token in tokens:
                        selected.pop(token, None)
            self.refresh_tree()

        def group_state(self, model, groups):
            roles = selections.get(model['key'], {})
            states = [group['key'] in roles for group in groups]
            if states and all(states):
                return True
            tokens = set(catalog.element_token(record) for group in groups for record in group['records'])
            if any(states) or any(token in tokens for token in picks.get(model['key'], {})):
                return None
            return False

        def refresh_tree(self):
            self.modelTree.Items.Clear()
            self.model_checks, self.category_checks, self.type_checks = [], [], []
            self.parent_checks = []
            for model in models:
                shown = visible_groups(model, bool(self.showOtherCheck.IsChecked))
                if not shown and model['loaded']:
                    continue
                count = sum(group['count'] for group in shown)
                label = u'{}  |  {} support elements'.format(model['label'], count)
                model_item = TreeViewItem()
                model_check = self.check(label, model['loaded'])
                model_check.IsThreeState = True
                model_check.IsChecked = self.group_state(model, shown)
                self.parent_checks.append((model_check, model, shown))
                model_item.Header = model_check
                def model_click(sender, args, current=model, current_groups=shown):
                    self.bulk(current, current_groups, sender.IsChecked == True)
                model_check.Click += model_click
                categories = {}
                for group in shown:
                    section = ('Beams / joists' if _framing_group(group) else
                               'Roof / deck fallback' if _surface_group(group) else
                               'Custom IFC — review individually')
                    categories.setdefault(section, []).append(group)
                for category in sorted(categories):
                    groups = categories[category]
                    category_item = TreeViewItem()
                    category_check = self.check(u'{}  |  {} elements'.format(
                        category, sum(group['count'] for group in groups)))
                    category_check.IsThreeState = True
                    category_check.IsChecked = self.group_state(model, groups)
                    self.parent_checks.append((category_check, model, groups))
                    category_item.Header = category_check
                    def category_click(sender, args, current=model, current_groups=groups):
                        self.bulk(current, current_groups, sender.IsChecked == True)
                    category_check.Click += category_click
                    for group in groups:
                        row = StackPanel()
                        row.Orientation = Orientation.Horizontal
                        type_check = self.check(u'{}  |  {} elements'.format(group['label'], group['count']))
                        type_check.MinWidth = 355
                        type_check.IsThreeState = True
                        type_check.IsChecked = self.group_state(model, [group])
                        self.type_checks.append((type_check, model, [group]))
                        row.Children.Add(type_check)
                        role_box = ComboBox()
                        role_box.Width = 160
                        role_box.Margin = Thickness(5, 0, 8, 0)
                        role_box.Items.Add('Preferred framing')
                        role_box.Items.Add('Fallback surface')
                        selected_role = selections.get(model['key'], {}).get(group['key'])
                        role_box.SelectedIndex = 1 if selected_role == 'fallback' or (not selected_role and group.get('surface_hint')) else 0
                        row.Children.Add(role_box)
                        def type_click(sender, args, current=model, current_group=group, current_role=role_box):
                            roles = selections.setdefault(current['key'], {})
                            if sender.IsChecked == True:
                                roles[current_group['key']] = 'fallback' if current_role.SelectedIndex == 1 else 'preferred'
                            else:
                                roles.pop(current_group['key'], None)
                                direct = picks.get(current['key'], {})
                                for record in current_group['records']:
                                    direct.pop(catalog.element_token(record), None)
                            self.update_counts()
                        type_check.Click += type_click
                        def role_change(sender, args, current=model, current_group=group, current_check=type_check):
                            if current_check.IsChecked == True:
                                selections.setdefault(current['key'], {})[current_group['key']] = 'fallback' if sender.SelectedIndex == 1 else 'preferred'
                                self.update_counts()
                        role_box.SelectionChanged += role_change
                        detail = TextBlock()
                        names = sorted(set(record.get('name', '') for record in group['records'] if record.get('name')))
                        direct_count = sum(catalog.element_token(record) in picks.get(model['key'], {}) for record in group['records'])
                        detail.Text = u'{}'.format(group.get('ifc_class') or '')
                        type_check.ToolTip = u'{} | {}{} | {}{}'.format(
                            group.get('category', ''),
                            group.get('ifc_class') or 'IFC class unavailable',
                            ' | ' + group['profile'] if group.get('profile') else '',
                            u', '.join(names[:2]) or u'Unnamed geometry',
                            u' | {} direct picks'.format(direct_count) if direct_count else '')
                        detail.Margin = Thickness(0, 5, 0, 0)
                        row.Children.Add(detail)
                        type_item = TreeViewItem()
                        type_item.Header = row
                        category_item.Items.Add(type_item)
                    model_item.Items.Add(category_item)
                self.modelTree.Items.Add(model_item)
            self.update_counts()

        def update_counts(self):
            for checkbox, model, groups in self.parent_checks + self.type_checks:
                checkbox.IsChecked = self.group_state(model, groups)
            model_count, preferred, fallback = selection_counts(models, selections, picks)
            self.countText.Text = (u'APPROVED: {} models / {} preferred members / {} fallback elements '
                                   '({} direct member picks)').format(
                                       model_count, preferred, fallback,
                                       sum(len(values) for values in picks.values()))

        def select_framing(self, sender, args):
            for model in models:
                if model['loaded']:
                    roles = selections.setdefault(model['key'], {})
                    for group in model['groups']:
                        if _framing_group(group):
                            roles[group['key']] = 'preferred'
            self.refresh_tree()

        def clear_selection(self, sender, args):
            selections.clear()
            picks.clear()
            self.refresh_tree()

        def request_pick(self, sender, args):
            self.pick_requested = True
            self.Hide()

        def cancel(self, sender, args):
            self.result = None
            self.Close()

        def confirm(self, sender, args):
            try:
                max_rod = catalog.validate_max_rod(self.maxRodBox.Text)
            except Exception:
                forms.alert('Maximum rod length must be a finite number from 1 to 60 feet.')
                return
            priority = _PRIORITIES[max(0, self.priorityBox.SelectedIndex)]
            sources = build_sources(models, selections, picks)
            required_role = 'preferred' if priority == 'preferred_only' else 'fallback' if priority == 'fallback_only' else None
            if not sources or (required_role and not any(source[required_role] for source in sources)):
                forms.alert('Approve at least one structural type or member for the selected targeting priority.')
                return
            def save_final_preferences(final_max_rod):
                _save_preferences(project, models, selections, picks, final_max_rod, priority)
            self.result = {'sources': sources, 'max_rod': max_rod,
                           'priority_mode': priority, 'warnings': warnings,
                           'save_preferences': save_final_preferences}
            self.Close()

    window = StructureWindow()
    while True:
        window.ShowDialog()
        if not window.pick_requested:
            return window.result
        window.pick_requested = False
        try:
            _direct_pick(uidoc, models, selections, picks,
                         'fallback' if window.pickRoleBox.SelectedIndex == 1 else 'preferred')
        except Exception as error:
            forms.alert(u'Structural selection could not be completed: {}'.format(error))
        window.refresh_tree()
