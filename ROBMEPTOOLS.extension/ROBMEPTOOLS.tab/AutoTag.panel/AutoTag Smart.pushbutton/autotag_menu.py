# -*- coding: utf-8 -*-
"""Unified ROBMEPTOOLS AutoTag menu for Duct + Pipe."""
import os
import clr
clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
from pyrevit import forms, script, DB

BUNDLE_DIR = os.path.dirname(__file__)


def _eid_value(eid):
    try:
        return int(eid.Value)
    except Exception:
        try:
            return int(eid.IntegerValue)
        except Exception:
            return None


def _bic_id(bic):
    try:
        return _eid_value(DB.ElementId(bic))
    except Exception:
        try:
            return int(bic)
        except Exception:
            return None


def _type_name(elem):
    family = ''
    typ = ''
    try:
        family = str(elem.FamilyName or '')
    except Exception:
        pass
    if not family:
        try:
            p = elem.get_Parameter(DB.BuiltInParameter.SYMBOL_FAMILY_NAME_PARAM)
            if p:
                family = p.AsString() or ''
        except Exception:
            pass
    try:
        typ = str(elem.Name or '')
    except Exception:
        pass
    if not typ:
        try:
            typ = DB.Element.Name.GetValue(elem)
        except Exception:
            pass
    if family and typ:
        return '{0} : {1}'.format(family, typ)
    return typ or family or 'Tag Type {0}'.format(_eid_value(elem.Id))


def _choice_identity(choice):
    if not choice:
        return ''
    return '{0}|{1}|{2}'.format(choice.get('mode', ''), choice.get('category_id', ''), choice.get('label', ''))


def _collect_tag_choices(doc, specs):
    choices = []
    seen = set()
    for bic_name, mode in specs:
        try:
            bic = getattr(DB.BuiltInCategory, bic_name)
            cid = _bic_id(bic)
            col = DB.FilteredElementCollector(doc).WhereElementIsElementType().OfCategory(bic)
            for elem in col:
                eid = _eid_value(elem.Id)
                if eid is None or eid in seen:
                    continue
                seen.add(eid)
                choices.append({'id': eid, 'label': _type_name(elem), 'mode': mode, 'category_id': cid})
        except Exception:
            pass
    choices.sort(key=lambda x: x['label'].lower())
    return choices


def _specs(discipline):
    if discipline == 'duct':
        return {
            'event': [('OST_DuctTags', 'native'), ('OST_FabricationDuctworkTags', 'fabrication')],
            'transition': [('OST_DuctFittingTags', 'native'), ('OST_FabricationDuctworkTags', 'fabrication')],
            'terminal': [('OST_DuctTerminalTags', 'native')],
            'equipment': [('OST_MechanicalEquipmentTags', 'native')],
            'accessory': [('OST_DuctAccessoryTags', 'native')],
            'extra': [],
        }
    return {
        'event': [('OST_PipeTags', 'native'), ('OST_FabricationPipeworkTags', 'fabrication')],
        'transition': [('OST_PipeFittingTags', 'native'), ('OST_FabricationPipeworkTags', 'fabrication')],
        'terminal': [('OST_PlumbingFixtureTags', 'native')],
        'equipment': [('OST_MechanicalEquipmentTags', 'native')],
        'accessory': [('OST_PipeAccessoryTags', 'native')],
        'extra': [('OST_PlumbingEquipmentTags', 'native')],
    }


class AutoTagSmartWindow(forms.WPFWindow):
    resolve_theme = True

    def __init__(self, doc, forced_discipline=None):
        self.doc = doc
        self.forced_discipline = forced_discipline
        self.run_requested = False
        self.result = None
        self._page = 'overview'
        self._choice_maps = {}
        forms.WPFWindow.__init__(self, os.path.join(BUNDLE_DIR, 'autotag.xaml'))
        self._load_choices()
        self._wire()
        self._load_saved()
        if forced_discipline in ('duct', 'pipe'):
            self.DisciplineDuct.IsChecked = forced_discipline == 'duct'
            self.DisciplinePipe.IsChecked = forced_discipline == 'pipe'
            self.DisciplineBoth.IsChecked = False
            self.DisciplineDuct.IsEnabled = False
            self.DisciplinePipe.IsEnabled = False
            self.DisciplineBoth.IsEnabled = False
        self._show_page('overview')
        self._refresh()
        try:
            from System import Uri, UriKind
            from System.Windows.Media.Imaging import BitmapImage
            p = os.path.join(BUNDLE_DIR, 'icon.png')
            if os.path.isfile(p):
                self.Icon = BitmapImage(Uri(p, UriKind.Absolute))
        except Exception:
            pass

    def _visible(self, yes):
        try:
            from System.Windows import Visibility
            return Visibility.Visible if yes else Visibility.Collapsed
        except Exception:
            return None

    def _active_disciplines(self):
        if bool(self.DisciplineBoth.IsChecked):
            return ['duct', 'pipe']
        if bool(self.DisciplinePipe.IsChecked):
            return ['pipe']
        return ['duct']

    def _load_combo(self, discipline, key, combo):
        real_choices = _collect_tag_choices(self.doc, _specs(discipline).get(key, []))
        skip_label = 'NONE / SKIP' if real_choices else 'NONE / SKIP  (no compatible loaded tag types)'
        choices = [{'id': None, 'label': skip_label, 'mode': 'skip', 'category_id': None, 'skip': True}] + real_choices
        self._choice_maps[(discipline, key)] = choices
        try:
            combo.Items.Clear()
        except Exception:
            pass
        for c in choices:
            prefix = ''
            if c.get('mode') == 'fabrication':
                prefix = '[FAB] '
            elif c.get('mode') == 'native' and key in ('event', 'transition'):
                prefix = '[NATIVE] '
            combo.Items.Add(prefix + c['label'])
        combo.SelectedIndex = 0
        combo.IsEnabled = True

    def _load_choices(self):
        pairs = [
            ('duct', 'event', self.DuctEventTagCombo),
            ('duct', 'transition', self.DuctTransitionTagCombo),
            ('duct', 'terminal', self.DuctTerminalTagCombo),
            ('duct', 'equipment', self.DuctEquipmentTagCombo),
            ('duct', 'accessory', self.DuctAccessoryTagCombo),
            ('pipe', 'event', self.PipeEventTagCombo),
            ('pipe', 'transition', self.PipeTransitionTagCombo),
            ('pipe', 'terminal', self.PipeTerminalTagCombo),
            ('pipe', 'equipment', self.PipeEquipmentTagCombo),
            ('pipe', 'accessory', self.PipeAccessoryTagCombo),
            ('pipe', 'extra', self.PipeExtraTagCombo),
        ]
        for discipline, key, combo in pairs:
            self._load_combo(discipline, key, combo)

    def _wire(self):
        self.NavOverview.Click += lambda s, e: self._show_page('overview')
        self.NavTargets.Click += lambda s, e: self._show_page('targets')
        self.NavTags.Click += lambda s, e: self._show_page('tags')
        self.NavPlacement.Click += lambda s, e: self._show_page('placement')
        self.ProfileEvents.Click += lambda s, e: self._apply_profile('events')
        self.ProfileCD.Click += lambda s, e: self._apply_profile('cd')
        self.ProfileComponents.Click += lambda s, e: self._apply_profile('components')
        self.ProfileAll.Click += lambda s, e: self._apply_profile('all')
        controls = [
            self.DisciplineDuct, self.DisciplinePipe, self.DisciplineBoth,
            self.DuctEventDirection, self.DuctEventElevation, self.DuctEventSize, self.DuctEventShape, self.DuctEventEndcap, self.DuctEventBranch, self.DuctAllStraights,
            self.DuctComponentTransition, self.DuctComponentTerminal, self.DuctComponentEquipment, self.DuctComponentAccessory,
            self.PipeEventDirection, self.PipeEventElevation, self.PipeEventSize, self.PipeEventShape, self.PipeEventEndcap,
            self.PipeComponentTransition, self.PipeComponentTerminal, self.PipeComponentEquipment, self.PipeComponentAccessory, self.PipeComponentExtra,
            self.EngineBalanced, self.EngineFast, self.EngineClean,
            self.ScopeView, self.ScopeSelection,
            self.AllowDoglegs, self.ForceLeaders, self.ExtraCleanup, self.DetailedReport,
        ]
        for ctrl in controls:
            try:
                ctrl.Checked += self._changed
                ctrl.Unchecked += self._changed
            except Exception:
                pass
        for discipline, keys in (('duct', ['event', 'transition', 'terminal', 'equipment', 'accessory']), ('pipe', ['event', 'transition', 'terminal', 'equipment', 'accessory', 'extra'])):
            for key in keys:
                try:
                    self._combo_for(discipline, key).SelectionChanged += self._changed
                except Exception:
                    pass
        self.RunButton.Click += self._run
        self.CancelButton.Click += self._cancel

    def _show_page(self, name):
        pages = {'overview': self.PageOverview, 'targets': self.PageTargets, 'tags': self.PageTags, 'placement': self.PagePlacement}
        navs = {'overview': self.NavOverview, 'targets': self.NavTargets, 'tags': self.NavTags, 'placement': self.NavPlacement}
        for key, page in pages.items():
            page.Visibility = self._visible(key == name)
        for key, button in navs.items():
            try:
                button.Style = self.FindResource('NavButtonActive' if key == name else 'NavButton')
            except Exception:
                pass
        self._page = name

    def _engine_key(self):
        if bool(self.EngineFast.IsChecked):
            return 'fast'
        if bool(self.EngineClean.IsChecked):
            return 'clean'
        return 'balanced'

    def _event_controls(self, discipline):
        if discipline == 'duct':
            return [self.DuctEventDirection, self.DuctEventElevation, self.DuctEventSize, self.DuctEventShape, self.DuctEventEndcap, self.DuctEventBranch, self.DuctAllStraights]
        return [self.PipeEventDirection, self.PipeEventElevation, self.PipeEventSize, self.PipeEventShape, self.PipeEventEndcap]

    def _component_controls(self, discipline):
        if discipline == 'duct':
            return [self.DuctComponentTransition, self.DuctComponentTerminal, self.DuctComponentEquipment, self.DuctComponentAccessory]
        return [self.PipeComponentTransition, self.PipeComponentTerminal, self.PipeComponentEquipment, self.PipeComponentAccessory, self.PipeComponentExtra]

    def _apply_profile_to(self, discipline, profile):
        events_on = profile in ('events', 'cd', 'all')
        components_on = profile in ('components', 'all')
        for ctrl in self._event_controls(discipline):
            ctrl.IsChecked = events_on
        comps = self._component_controls(discipline)
        for i, ctrl in enumerate(comps):
            if profile == 'cd':
                ctrl.IsChecked = i < 3
            else:
                ctrl.IsChecked = components_on

    def _apply_profile(self, profile):
        for discipline in self._active_disciplines():
            self._apply_profile_to(discipline, profile)
        self._refresh()

    def _profile_for(self, discipline):
        events = tuple(bool(x.IsChecked) for x in self._event_controls(discipline))
        comps = tuple(bool(x.IsChecked) for x in self._component_controls(discipline))
        all_events = tuple(True for _ in events)
        no_events = tuple(False for _ in events)
        no_comps = tuple(False for _ in comps)
        all_comps = tuple(True for _ in comps)
        cd_comps = tuple(i < 3 for i in range(len(comps)))
        if events == all_events and comps == no_comps:
            return 'events'
        if events == all_events and comps == cd_comps:
            return 'cd'
        if events == no_events and comps == all_comps:
            return 'components'
        if events == all_events and comps == all_comps:
            return 'all'
        return None

    def _active_profile(self):
        profiles = [self._profile_for(x) for x in self._active_disciplines()]
        if profiles and profiles[0] and all(x == profiles[0] for x in profiles):
            return profiles[0]
        return None

    def _sync_profile_highlight(self):
        active = self._active_profile()
        buttons = {'events': self.ProfileEvents, 'cd': self.ProfileCD, 'components': self.ProfileComponents, 'all': self.ProfileAll}
        for key, button in buttons.items():
            try:
                button.Style = self.FindResource('PrimaryButton' if key == active else 'ActionButton')
            except Exception:
                pass

    def _selected_choice(self, discipline, key, combo):
        choices = self._choice_maps.get((discipline, key), [])
        try:
            idx = int(combo.SelectedIndex)
        except Exception:
            idx = -1
        if 0 <= idx < len(choices):
            return choices[idx]
        return None

    def _combo_for(self, discipline, key):
        mapping = {
            ('duct', 'event'): self.DuctEventTagCombo,
            ('duct', 'transition'): self.DuctTransitionTagCombo,
            ('duct', 'terminal'): self.DuctTerminalTagCombo,
            ('duct', 'equipment'): self.DuctEquipmentTagCombo,
            ('duct', 'accessory'): self.DuctAccessoryTagCombo,
            ('pipe', 'event'): self.PipeEventTagCombo,
            ('pipe', 'transition'): self.PipeTransitionTagCombo,
            ('pipe', 'terminal'): self.PipeTerminalTagCombo,
            ('pipe', 'equipment'): self.PipeEquipmentTagCombo,
            ('pipe', 'accessory'): self.PipeAccessoryTagCombo,
            ('pipe', 'extra'): self.PipeExtraTagCombo,
        }
        return mapping.get((discipline, key))

    def _read_discipline(self, discipline):
        event_names = ['turn', 'elevation', 'size', 'shape', 'endcap'] + (['branch', 'all_straights'] if discipline == 'duct' else [])
        reasons = []
        for name, ctrl in zip(event_names, self._event_controls(discipline)):
            if bool(ctrl.IsChecked):
                reasons.append(name)
        if discipline == 'duct':
            keys = ['transition', 'terminal', 'equipment', 'accessory']
        else:
            keys = ['transition', 'terminal', 'equipment', 'accessory', 'extra']
        comps = {}
        tag_types = {}
        for key, ctrl in zip(keys, self._component_controls(discipline)):
            comps[key] = bool(ctrl.IsChecked)
            tag_types[key] = self._selected_choice(discipline, key, self._combo_for(discipline, key))
        if discipline == 'duct':
            comps['extra'] = False
            tag_types['extra'] = None
        engine_key = self._engine_key()
        if discipline == 'duct':
            engine = {'balanced': 'Smart V9 Balanced (recommended)', 'fast': 'Smart V9 Fast', 'clean': 'Smart V9 Clean'}[engine_key]
            selection_key = 'Only selected qualifying ducts'
        else:
            engine = {'balanced': 'Smart Pipe V1 Balanced (recommended)', 'fast': 'Smart Pipe V1 Fast', 'clean': 'Smart Pipe V1 Clean'}[engine_key]
            selection_key = 'Only selected qualifying pipes'
        switches = {
            'Allow doglegs even when straight is clear': bool(self.AllowDoglegs.IsChecked),
            'Force leaders (no on-host text)': bool(self.ForceLeaders.IsChecked),
            'Run extra cleanup pass (slower)': bool(self.ExtraCleanup.IsChecked),
            selection_key: bool(self.ScopeSelection.IsChecked),
            'Detailed console report': bool(self.DetailedReport.IsChecked),
        }
        return {
            'event_reasons': reasons,
            'event_tag_type': self._selected_choice(discipline, 'event', self._combo_for(discipline, 'event')),
            'components': comps,
            'tag_types': tag_types,
            'engine': engine,
            'switches': switches,
            'scope': 'selection' if bool(self.ScopeSelection.IsChecked) else 'view',
        }

    def _read(self):
        active = self._active_disciplines()
        return {
            'discipline': 'both' if len(active) == 2 else active[0],
            'active_disciplines': active,
            'duct': self._read_discipline('duct'),
            'pipe': self._read_discipline('pipe'),
            'engine_key': self._engine_key(),
            'scope': 'selection' if bool(self.ScopeSelection.IsChecked) else 'view',
        }

    def _validate(self, result):
        any_runnable = False
        for discipline in result['active_disciplines']:
            opts = result[discipline]
            event_choice = opts.get('event_tag_type') or {}
            if opts['event_reasons'] and event_choice.get('id') is not None:
                any_runnable = True
            for key, enabled in opts.get('components', {}).items():
                choice = opts.get('tag_types', {}).get(key) or {}
                if enabled and choice.get('id') is not None:
                    any_runnable = True
        if not any_runnable:
            forms.alert(
                'Nothing is currently mapped to a tag type. Choose a BOD/BOP event tag or a component tag type, or turn off the targets you want to skip.',
                title='ROBMEPTOOLS AutoTag Smart'
            )
            return False
        return True

    def _g(self, cfg, name, default):
        try:
            return getattr(cfg, name, default)
        except Exception:
            return default

    def _load_saved(self):
        try:
            cfg = script.get_config()
        except Exception:
            cfg = None
        discipline = str(self._g(cfg, 'discipline', 'duct'))
        self.DisciplinePipe.IsChecked = discipline == 'pipe'
        self.DisciplineBoth.IsChecked = discipline == 'both'
        self.DisciplineDuct.IsChecked = discipline not in ('pipe', 'both')
        for d in ('duct', 'pipe'):
            ctrls = self._event_controls(d)
            for suffix, ctrl in zip(('direction', 'elevation', 'size', 'shape', 'endcap') + (('branch', 'all_straights') if d == 'duct' else ()), ctrls):
                default = (any(bool(x.IsChecked) for x in ctrls[:5])
                           if suffix in ('branch', 'all_straights') else True)
                ctrl.IsChecked = bool(self._g(cfg, d + '_event_' + suffix, default))
            comp_keys = ['transition', 'terminal', 'equipment', 'accessory'] + (['extra'] if d == 'pipe' else [])
            for key, ctrl in zip(comp_keys, self._component_controls(d)):
                ctrl.IsChecked = bool(self._g(cfg, d + '_component_' + key, False))
        engine = str(self._g(cfg, 'engine_mode', 'balanced'))
        self.EngineFast.IsChecked = engine == 'fast'
        self.EngineClean.IsChecked = engine == 'clean'
        self.EngineBalanced.IsChecked = engine not in ('fast', 'clean')
        scope = str(self._g(cfg, 'scope', 'view'))
        self.ScopeSelection.IsChecked = scope == 'selection'
        self.ScopeView.IsChecked = scope != 'selection'
        self.AllowDoglegs.IsChecked = bool(self._g(cfg, 'allow_doglegs', False))
        self.ForceLeaders.IsChecked = bool(self._g(cfg, 'force_leaders', False))
        self.ExtraCleanup.IsChecked = bool(self._g(cfg, 'extra_cleanup', False))
        self.DetailedReport.IsChecked = bool(self._g(cfg, 'detailed_report', False))
        for discipline in ('duct', 'pipe'):
            keys = ['event', 'transition', 'terminal', 'equipment', 'accessory'] + (['extra'] if discipline == 'pipe' else [])
            for key in keys:
                combo = self._combo_for(discipline, key)
                saved_key = str(self._g(cfg, discipline + '_tagchoice2_' + key, ''))
                saved_label = str(self._g(cfg, discipline + '_tagchoice_' + key, ''))
                choices = self._choice_maps.get((discipline, key), [])
                matched = False
                if saved_key:
                    for i, choice in enumerate(choices):
                        if _choice_identity(choice) == saved_key:
                            combo.SelectedIndex = i
                            matched = True
                            break
                if not matched and saved_label:
                    for i, choice in enumerate(choices):
                        if choice['label'] == saved_label:
                            combo.SelectedIndex = i
                            break

    def _save(self):
        try:
            cfg = script.get_config()
            cfg.discipline = self._read()['discipline']
            cfg.engine_mode = self._engine_key()
            cfg.scope = 'selection' if bool(self.ScopeSelection.IsChecked) else 'view'
            cfg.allow_doglegs = bool(self.AllowDoglegs.IsChecked)
            cfg.force_leaders = bool(self.ForceLeaders.IsChecked)
            cfg.extra_cleanup = bool(self.ExtraCleanup.IsChecked)
            cfg.detailed_report = bool(self.DetailedReport.IsChecked)
            for d in ('duct', 'pipe'):
                for suffix, ctrl in zip(('direction', 'elevation', 'size', 'shape', 'endcap') + (('branch', 'all_straights') if d == 'duct' else ()), self._event_controls(d)):
                    setattr(cfg, d + '_event_' + suffix, bool(ctrl.IsChecked))
                comp_keys = ['transition', 'terminal', 'equipment', 'accessory'] + (['extra'] if d == 'pipe' else [])
                for key, ctrl in zip(comp_keys, self._component_controls(d)):
                    setattr(cfg, d + '_component_' + key, bool(ctrl.IsChecked))
                for key in ['event'] + comp_keys:
                    choice = self._selected_choice(d, key, self._combo_for(d, key))
                    setattr(cfg, d + '_tagchoice_' + key, choice['label'] if choice else '')
                    setattr(cfg, d + '_tagchoice2_' + key, _choice_identity(choice))
            script.save_config()
        except Exception:
            pass

    def _refresh(self):
        try:
            active = self._active_disciplines()
            show_duct = 'duct' in active
            show_pipe = 'pipe' in active
            self.DuctTargetsCard.Visibility = self._visible(show_duct)
            self.PipeTargetsCard.Visibility = self._visible(show_pipe)
            self.DuctTagTypesCard.Visibility = self._visible(show_duct)
            self.PipeTagTypesCard.Visibility = self._visible(show_pipe)
            self._sync_profile_highlight()
            result = self._read()
            event_n = 0
            comp_n = 0
            skipped_map_n = 0
            for discipline in active:
                opts = result[discipline]
                event_n += len(opts['event_reasons'])
                comp_n += len([x for x in opts['components'].values() if x])
                event_choice = opts.get('event_tag_type') or {}
                if opts['event_reasons'] and event_choice.get('id') is None:
                    skipped_map_n += 1
                for key, enabled in opts['components'].items():
                    choice = opts.get('tag_types', {}).get(key) or {}
                    if enabled and choice.get('id') is None:
                        skipped_map_n += 1
            self.SummaryEvents.Text = str(event_n)
            self.SummaryComponents.Text = str(comp_n)
            label = 'DUCT + PIPE' if len(active) == 2 else active[0].upper()
            self.ModeBadge.Text = '{0} • {1}'.format(label, self._engine_key().upper())
            if len(active) == 2:
                self.EventSampleHelp.Text = 'Choose the Duct BOD and Pipe BOP event tag types on Tag Types. Run starts immediately; no sample tag placement or pick is required.'
            elif active[0] == 'duct':
                self.EventSampleHelp.Text = 'Choose the BOD event tag type on Tag Types. Run starts immediately; no sample tag placement or pick is required.'
            else:
                self.EventSampleHelp.Text = 'Choose the BOP event tag type on Tag Types. Run starts immediately; no sample tag placement or pick is required.'
            footer = '{0} event trigger(s) • {1} direct component category(s) • {2}'.format(event_n, comp_n, result['scope'].upper())
            if skipped_map_n:
                footer += ' • {0} TAG MAP(S) SKIPPED'.format(skipped_map_n)
            self.FooterHelp.Text = footer
        except Exception:
            pass

    def _changed(self, sender, args):
        self._refresh()

    def _run(self, sender, args):
        result = self._read()
        if not self._validate(result):
            return
        self.result = result
        self._save()
        self.run_requested = True
        self.Close()

    def _cancel(self, sender, args):
        self.run_requested = False
        self.Close()


def show_autotag_menu(doc, discipline=None):
    win = AutoTagSmartWindow(doc, discipline)
    win.ShowDialog()
    if not win.run_requested:
        return None
    if discipline in ('duct', 'pipe'):
        return win.result.get(discipline)
    return win.result
