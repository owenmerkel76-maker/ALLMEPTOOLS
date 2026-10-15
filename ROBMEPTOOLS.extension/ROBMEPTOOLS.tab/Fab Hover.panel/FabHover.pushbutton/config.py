# -*- coding: utf-8 -*-
import clr
import os
import sys
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
from pyrevit import forms

BUNDLE_DIR = os.path.dirname(__file__)
if BUNDLE_DIR not in sys.path:
    sys.path.insert(0, BUNDLE_DIR)

from fabhover_settings import (
    DEFAULTS, FIELD_GROUPS, CATEGORY_GROUPS, FIELD_KEYS, CATEGORY_KEYS,
    PRESETS, load_settings, save_settings,
)


class DisplayOptions(forms.WPFWindow):
    resolve_theme = True

    def __init__(self):
        xaml_path = os.path.join(BUNDLE_DIR, "config.xaml")
        forms.WPFWindow.__init__(self, xaml_path)

        try:
            from System import Uri, UriKind
            from System.Windows.Media.Imaging import BitmapImage
            icon_path = os.path.join(BUNDLE_DIR, "icon.png")
            if os.path.isfile(icon_path):
                self.Icon = BitmapImage(Uri(icon_path, UriKind.Absolute))
        except:
            pass

        self._suspend_events = True
        self._field_controls = {}
        self._field_aliases = {}
        self._category_controls = {}
        self._current_page = "overview"
        self._current_group = "common"
        self._field_rows = {"common": [], "hvac": [], "plumbing": [], "equipment": [], "fabrication": [], "qa": []}
        self._dirty = False
        self._active_preset = None
        self._appearance_bool_controls = {
            "popup_show_header": self.PopupShowHeader,
            "popup_show_subtitle": self.PopupShowSubtitle,
            "popup_show_icon": self.PopupShowIcon,
            "popup_show_accent_bar": self.PopupShowAccentBar,
            "popup_hide_when_no_target": self.PopupHideNoTarget,
        }
        self._numeric_controls = {
            "popup_opacity": self.PopupOpacity,
            "popup_corner_radius": self.PopupCornerRadius,
            "popup_text_size": self.PopupTextSize,
            "popup_width": self.PopupWidth,
            "popup_hide_delay_ms": self.PopupHideDelay,
            "popup_offset_x": self.PopupOffsetX,
            "popup_offset_y": self.PopupOffsetY,
            "hover_move_interval_ms": self.HoverMoveInterval,
            "hover_read_interval_ms": self.HoverReadInterval,
            "hover_idle_refresh_ms": self.HoverIdleRefresh,
        }
        self._theme_choices = {
            "Navy": self.ThemeNavy,
            "Graphite": self.ThemeGraphite,
            "Light": self.ThemeLight,
        }
        self._accent_choices = {
            "#168CF3": self.AccentBlue,
            "#4DA3FF": self.AccentAzure,
            "#35CBEF": self.AccentSky,
            "#24B7A5": self.AccentTeal,
            "#50B97B": self.AccentMint,
            "#36A957": self.AccentGreen,
            "#8FBF4D": self.AccentLime,
            "#F5A623": self.AccentAmber,
            "#F47A3C": self.AccentOrange,
            "#F0655B": self.AccentCoral,
            "#E65454": self.AccentRed,
            "#E45BA8": self.AccentRose,
            "#F078C4": self.AccentPink,
            "#8B6CE8": self.AccentPurple,
            "#6F59C9": self.AccentViolet,
            "#6F9DC7": self.AccentSteel,
            "#8797A5": self.AccentSlate,
            "#B8C5CE": self.AccentSilver,
        }

        self._preset_buttons = {
            "General": self.PresetGeneral,
            "HVAC Fabrication": self.PresetHVAC,
            "Plumbing": self.PresetPlumbing,
            "Coordination": self.PresetCoordination,
            "Minimal": self.PresetMinimal,
            "Equipment": self.PresetEquipment,
        }

        self._page_map = {
            "overview": (self.PageOverview, self.NavOverview, "Overview", "HVAC + plumbing hover setup at a glance."),
            "fields": (self.PageFields, self.NavFields, "Display Fields", "Choose exactly what the hover card reads and shows."),
            "presets": (self.PagePresets, self.NavPresets, "Preset Profiles", "Switch quickly between common HVAC + plumbing workflows."),
            "appearance": (self.PageAppearance, self.NavAppearance, "Popup Appearance", "Customize the real hover card without affecting data acquisition."),
            "behavior": (self.PageBehavior, self.NavBehavior, "Behavior & Positioning", "Tune hover response, no-target hiding and cursor placement."),
            "categories": (self.PageCategories, self.NavCategories, "Categories", "Choose which Revit MEP categories can trigger Fab Hover."),
            "advanced": (self.PageAdvanced, self.NavAdvanced, "Advanced", "Optional diagnostic parameter coverage."),
        }
        self._field_group_map = {
            "common": (self.FieldsCommon, self.GroupCommon),
            "hvac": (self.FieldsHVAC, self.GroupHVAC),
            "plumbing": (self.FieldsPlumbing, self.GroupPlumbing),
            "equipment": (self.FieldsEquipment, self.GroupEquipment),
            "fabrication": (self.FieldsFabrication, self.GroupFabrication),
            "qa": (self.FieldsQA, self.GroupQA),
        }

        self._setup_debounce_timers()
        self._build_dynamic_fields()
        self._build_dynamic_categories()
        self._wire_events()
        self._apply(load_settings())
        self._suspend_events = False
        self._show_page("overview")
        self._show_field_group("common")
        self._update_count()
        self._set_dirty(False)
        try:
            self.Closed += self._on_closed
        except:
            pass

    def _setup_debounce_timers(self):
        try:
            from System.Windows.Threading import DispatcherTimer
            from System import TimeSpan
            self._preview_timer = DispatcherTimer()
            self._preview_timer.Interval = TimeSpan.FromMilliseconds(70)
            self._preview_timer.Tick += self._preview_timer_tick
            self._search_timer = DispatcherTimer()
            self._search_timer.Interval = TimeSpan.FromMilliseconds(120)
            self._search_timer.Tick += self._search_timer_tick
        except:
            self._preview_timer = None
            self._search_timer = None

    def _on_closed(self, sender, args):
        for timer in (getattr(self, "_preview_timer", None), getattr(self, "_search_timer", None)):
            try:
                if timer is not None:
                    timer.Stop()
            except:
                pass

    def _new_toggle(self, key, label):
        try:
            from System.Windows.Controls import CheckBox
            cb = CheckBox()
            cb.Content = label
            cb.Style = self.FindResource("FieldToggle")
            cb.Checked += self._option_changed
            cb.Unchecked += self._option_changed
            return cb
        except:
            return None

    def _build_dynamic_fields(self):
        targets = {
            "common": self.FieldsCommonGrid, "hvac": self.FieldsHVACGrid,
            "plumbing": self.FieldsPlumbingGrid, "equipment": self.FieldsEquipmentGrid,
            "fabrication": self.FieldsFabricationGrid, "qa": self.FieldsQAGrid,
        }
        for group_name, items in FIELD_GROUPS.items():
            target = targets.get(group_name)
            if target is None:
                continue
            for key, label in items:
                cb = self._new_toggle(key, label)
                if cb is None:
                    continue
                target.Children.Add(cb)
                try:
                    cb.ToolTip = "{0} • {1}".format(group_name.upper(), label)
                except:
                    pass
                self._field_rows.setdefault(group_name, []).append((cb, str(label), str(key)))
                if key not in self._field_controls:
                    self._field_controls[key] = cb
                else:
                    self._field_aliases.setdefault(key, []).append(cb)

    def _build_dynamic_categories(self):
        targets = {
            "hvac": self.CategoriesHVAC,
            "plumbing": self.CategoriesPlumbing,
            "equipment": self.CategoriesEquipment,
        }
        for group_name, items in CATEGORY_GROUPS.items():
            target = targets.get(group_name)
            if target is None:
                continue
            for key, label in items:
                cb = self._new_toggle(key, label)
                if cb is not None:
                    target.Children.Add(cb)
                    self._category_controls[key] = cb

        # QA diagnostic toggles are surfaced again on Advanced for convenience.
        for key, label in FIELD_GROUPS.get("qa", []):
            if key not in ("show_all_instance_parameters", "show_all_type_parameters"):
                continue
            cb = self._field_controls.get(key)
            if cb is not None:
                # WPF controls can only have one parent; create a second control and
                # synchronize it in _read/_apply through a dedicated alias list.
                alias = self._new_toggle(key, label)
                if alias is not None:
                    self.AdvancedDiagnosticFields.Children.Add(alias)
                    self._field_aliases.setdefault(key, []).append(alias)

    def _wire_events(self):
        self.NavOverview.Click += lambda s, e: self._show_page("overview")
        self.NavFields.Click += lambda s, e: self._show_page("fields")
        self.NavPresets.Click += lambda s, e: self._show_page("presets")
        self.NavAppearance.Click += lambda s, e: self._show_page("appearance")
        self.NavBehavior.Click += lambda s, e: self._show_page("behavior")
        self.NavCategories.Click += lambda s, e: self._show_page("categories")
        self.NavAdvanced.Click += lambda s, e: self._show_page("advanced")
        self.GoFieldsButton.Click += lambda s, e: self._show_page("fields")
        self.GoPresetsButton.Click += lambda s, e: self._show_page("presets")
        self.GoAppearanceButton.Click += lambda s, e: self._show_page("appearance")

        self.GroupCommon.Click += lambda s, e: self._show_field_group("common")
        self.GroupHVAC.Click += lambda s, e: self._show_field_group("hvac")
        self.GroupPlumbing.Click += lambda s, e: self._show_field_group("plumbing")
        self.GroupEquipment.Click += lambda s, e: self._show_field_group("equipment")
        self.GroupFabrication.Click += lambda s, e: self._show_field_group("fabrication")
        self.GroupQA.Click += lambda s, e: self._show_field_group("qa")
        self.FieldSearchBox.TextChanged += self._field_search_changed
        self.FieldSearchClear.Click += self._clear_field_search

        self.PresetGeneral.Click += lambda s, e: self._apply_preset("General")
        self.PresetHVAC.Click += lambda s, e: self._apply_preset("HVAC Fabrication")
        self.PresetPlumbing.Click += lambda s, e: self._apply_preset("Plumbing")
        self.PresetCoordination.Click += lambda s, e: self._apply_preset("Coordination")
        self.PresetMinimal.Click += lambda s, e: self._apply_preset("Minimal")
        self.PresetEquipment.Click += lambda s, e: self._apply_preset("Equipment")

        for c in self._appearance_bool_controls.values():
            try:
                c.Checked += self._appearance_changed
                c.Unchecked += self._appearance_changed
            except:
                pass
        for c in self._numeric_controls.values():
            try:
                c.ValueChanged += self._appearance_changed
            except:
                pass
        for mapping in (self._theme_choices, self._accent_choices):
            for c in mapping.values():
                try:
                    c.Checked += self._appearance_changed
                except:
                    pass

        self.BehaviorSnappy.Click += lambda s, e: self._apply_behavior_preset("snappy")
        self.BehaviorBalanced.Click += lambda s, e: self._apply_behavior_preset("balanced")
        self.BehaviorQuiet.Click += lambda s, e: self._apply_behavior_preset("quiet")

        self.ResetButton.Click += self._reset
        self.CancelButton.Click += lambda s, e: self.Close()
        self.SaveButton.Click += self._save

    def _page_controls(self):
        return self._page_map

    def _show_page(self, name):
        try:
            from System.Windows import Visibility
            self._current_page = name
            for key, item in self._page_map.items():
                page, nav, title, subtitle = item
                page.Visibility = Visibility.Visible if key == name else Visibility.Collapsed
                nav.Style = self.FindResource("NavButtonActive" if key == name else "NavButton")
            _, _, title, subtitle = self._page_map[name]
            self.PageTitle.Text = title
            self.PageSubtitle.Text = subtitle
            if name == "appearance":
                self._update_preview()
        except:
            pass

    def _show_field_group(self, name):
        try:
            from System.Windows import Visibility
            self._current_group = name
            if str(getattr(self.FieldSearchBox, "Text", "") or "").strip():
                self._apply_field_search()
                return
            self.FieldGroupBar.Visibility = Visibility.Visible
            self.FieldSearchStatus.Visibility = Visibility.Collapsed
            self.FieldSearchEmpty.Visibility = Visibility.Collapsed
            for key, (panel, btn) in self._field_group_map.items():
                panel.Visibility = Visibility.Visible if key == name else Visibility.Collapsed
                btn.Style = self.FindResource("GroupButtonActive" if key == name else "GroupButton")
                for cb, label, field_key in self._field_rows.get(key, []):
                    cb.Visibility = Visibility.Visible
        except:
            pass

    def _field_search_changed(self, sender, args):
        try:
            if self._search_timer is None:
                self._apply_field_search()
                return
            self._search_timer.Stop()
            self._search_timer.Start()
        except:
            self._apply_field_search()

    def _search_timer_tick(self, sender, args):
        try:
            if self._search_timer is not None:
                self._search_timer.Stop()
        except:
            pass
        self._apply_field_search()

    def _clear_field_search(self, sender, args):
        try:
            self.FieldSearchBox.Text = ""
            self.FieldSearchBox.Focus()
        except:
            pass
        self._show_field_group(self._current_group)

    def _apply_field_search(self):
        try:
            from System.Windows import Visibility
            query = str(self.FieldSearchBox.Text or "").strip().lower()
            if not query:
                self._show_field_group(self._current_group)
                return

            self.FieldGroupBar.Visibility = Visibility.Collapsed
            total = 0
            for group_name, (panel, btn) in self._field_group_map.items():
                matches = 0
                for cb, label, field_key in self._field_rows.get(group_name, []):
                    hay = (label + " " + field_key.replace("_", " ") + " " + group_name).lower()
                    is_match = query in hay
                    cb.Visibility = Visibility.Visible if is_match else Visibility.Collapsed
                    if is_match:
                        matches += 1
                panel.Visibility = Visibility.Visible if matches else Visibility.Collapsed
                if matches:
                    total += matches

            self.FieldSearchStatus.Text = "{0} matching field{1} across all groups".format(total, "" if total == 1 else "s")
            self.FieldSearchStatus.Visibility = Visibility.Visible
            self.FieldSearchEmpty.Visibility = Visibility.Collapsed if total else Visibility.Visible
        except:
            pass

    def _option_changed(self, sender, args):
        if getattr(self, "_suspend_events", False):
            return
        # Keep duplicate diagnostic controls synchronized.
        try:
            for key, primary in self._field_controls.items():
                aliases = getattr(self, "_field_aliases", {}).get(key, [])
                if sender is primary:
                    for alias in aliases:
                        if bool(alias.IsChecked) != bool(primary.IsChecked):
                            alias.IsChecked = bool(primary.IsChecked)
                elif sender in aliases:
                    if bool(primary.IsChecked) != bool(sender.IsChecked):
                        primary.IsChecked = bool(sender.IsChecked)
        except:
            pass
        self._update_count()
        self._set_dirty(True)

    def _set_choice(self, mapping, value, fallback):
        try:
            target = mapping.get(str(value)) or mapping.get(str(fallback))
            if target is not None:
                target.IsChecked = True
        except:
            pass

    def _choice_value(self, mapping, fallback):
        try:
            for value, control in mapping.items():
                if bool(control.IsChecked):
                    return value
        except:
            pass
        return fallback

    def _apply(self, values):
        previous_suspend = bool(getattr(self, "_suspend_events", False))
        self._suspend_events = True
        try:
            for key, control in self._field_controls.items():
                try: control.IsChecked = bool(values.get(key, DEFAULTS.get(key, False)))
                except: pass
            for key, aliases in getattr(self, "_field_aliases", {}).items():
                value = bool(values.get(key, DEFAULTS.get(key, False)))
                for alias in aliases:
                    try: alias.IsChecked = value
                    except: pass
            for key, control in self._category_controls.items():
                try: control.IsChecked = bool(values.get(key, DEFAULTS.get(key, False)))
                except: pass
            for key, control in self._appearance_bool_controls.items():
                try: control.IsChecked = bool(values.get(key, DEFAULTS.get(key, False)))
                except: pass
            for key, control in self._numeric_controls.items():
                try: control.Value = float(values.get(key, DEFAULTS.get(key, 0)))
                except: pass
            self._set_choice(self._theme_choices, values.get("popup_theme"), DEFAULTS.get("popup_theme", "Navy"))
            self._set_choice(self._accent_choices, values.get("popup_accent"), DEFAULTS.get("popup_accent", "#168CF3"))
        finally:
            self._suspend_events = previous_suspend
        self._update_count()
        self._update_value_labels()
        if getattr(self, "_current_page", "overview") == "appearance":
            self._update_preview()

    def _read(self):
        values = dict(DEFAULTS)
        for key, control in self._field_controls.items():
            try: values[key] = bool(control.IsChecked)
            except: pass
        for key, control in self._category_controls.items():
            try: values[key] = bool(control.IsChecked)
            except: pass
        for key, control in self._appearance_bool_controls.items():
            try: values[key] = bool(control.IsChecked)
            except: pass
        for key, control in self._numeric_controls.items():
            try:
                raw = float(control.Value)
                default = DEFAULTS.get(key)
                values[key] = raw if isinstance(default, float) else int(round(raw))
            except:
                pass
        values["popup_theme"] = self._choice_value(self._theme_choices, DEFAULTS.get("popup_theme", "Navy"))
        values["popup_accent"] = self._choice_value(self._accent_choices, DEFAULTS.get("popup_accent", "#168CF3"))
        return values

    def _appearance_changed(self, sender, args):
        if getattr(self, "_suspend_events", False):
            return
        self._update_value_labels()
        self._set_dirty(True)
        if getattr(self, "_current_page", "") == "appearance":
            self._schedule_preview()

    def _schedule_preview(self):
        try:
            if self._preview_timer is None:
                self._update_preview()
                return
            self._preview_timer.Stop()
            self._preview_timer.Start()
        except:
            self._update_preview()

    def _preview_timer_tick(self, sender, args):
        try:
            if self._preview_timer is not None:
                self._preview_timer.Stop()
        except:
            pass
        if getattr(self, "_current_page", "") == "appearance":
            self._update_preview()

    def _update_value_labels(self):
        try: self.PopupOpacityValue.Text = "{0}%".format(int(round(self.PopupOpacity.Value)))
        except: pass
        try: self.PopupCornerValue.Text = "{0:.0f}px".format(float(self.PopupCornerRadius.Value))
        except: pass
        try: self.PopupTextValue.Text = "{0:.1f}px".format(float(self.PopupTextSize.Value))
        except: pass
        try: self.PopupWidthValue.Text = "{0:.0f}px".format(float(self.PopupWidth.Value))
        except: pass
        try: self.PopupHideDelayValue.Text = "{0:.0f} ms".format(float(self.PopupHideDelay.Value))
        except: pass
        try: self.PopupOffsetXValue.Text = "{0:.0f}px".format(float(self.PopupOffsetX.Value))
        except: pass
        try: self.PopupOffsetYValue.Text = "{0:.0f}px".format(float(self.PopupOffsetY.Value))
        except: pass
        try: self.HoverMoveValue.Text = "{0:.0f} ms".format(float(self.HoverMoveInterval.Value))
        except: pass
        try: self.HoverReadValue.Text = "{0:.0f} ms".format(float(self.HoverReadInterval.Value))
        except: pass
        try: self.HoverIdleValue.Text = "{0:.0f} ms".format(float(self.HoverIdleRefresh.Value))
        except: pass
        try:
            theme = self._choice_value(self._theme_choices, "Navy")
            self.OverviewThemeText.Text = theme
        except:
            pass

    def _preview_colors(self):
        theme = self._choice_value(self._theme_choices, "Navy")
        accent = self._choice_value(self._accent_choices, "#168CF3")
        if theme == "Light":
            return accent, "#F6F8FA", "#102335", "#20384A", "#2875A7", "#D0DBE3"
        if theme == "Graphite":
            return accent, "#171C22", "#F4F7FA", "#E4EBF0", "#9DB1C0", "#354653"
        return accent, "#0A1725", "#F6FAFD", "#EAF3F9", accent, "#25425B"

    def _update_preview(self):
        try:
            from System.Windows import CornerRadius, Thickness, Visibility
            from System.Windows.Media import BrushConverter
            bc = BrushConverter()
            accent, bg, title, text, subtitle, divider = self._preview_colors()
            opacity = max(0.55, min(1.0, float(self.PopupOpacity.Value) / 100.0))
            radius = max(0.0, min(18.0, float(self.PopupCornerRadius.Value)))
            text_size = max(8.5, min(16.0, float(self.PopupTextSize.Value)))
            width = max(190.0, min(420.0, float(self.PopupWidth.Value)))

            self.PreviewPopup.Background = bc.ConvertFromString(bg)
            self.PreviewPopup.BorderBrush = bc.ConvertFromString(accent)
            self.PreviewPopup.Opacity = opacity
            self.PreviewPopup.CornerRadius = CornerRadius(radius)
            self.PreviewPopup.Width = min(320.0, width)
            self.PreviewAccent.Background = bc.ConvertFromString(accent)
            self.PreviewTitle.Foreground = bc.ConvertFromString(title)
            self.PreviewSubtitle.Foreground = bc.ConvertFromString(subtitle)
            self.PreviewDivider.Background = bc.ConvertFromString(divider)
            self.PreviewInfo.Foreground = bc.ConvertFromString(text)
            self.PreviewInfo.FontSize = text_size
            self.PreviewInfo.LineHeight = text_size * 1.30
            self.PreviewTitle.FontSize = text_size + 1.0
            self.PreviewSubtitle.FontSize = max(8.0, text_size - 1.5)
            self.PreviewHeader.Visibility = Visibility.Visible if bool(self.PopupShowHeader.IsChecked) else Visibility.Collapsed
            self.PreviewSubtitle.Visibility = Visibility.Visible if bool(self.PopupShowSubtitle.IsChecked) else Visibility.Collapsed
            self.PreviewIconTile.Visibility = Visibility.Visible if bool(self.PopupShowIcon.IsChecked) else Visibility.Collapsed
            self.PreviewAccent.Visibility = Visibility.Visible if bool(self.PopupShowAccentBar.IsChecked) else Visibility.Collapsed

        except:
            pass

    def _apply_behavior_preset(self, name):
        self._suspend_events = True
        try:
            if name == "snappy":
                self.HoverMoveInterval.Value = 16
                self.HoverReadInterval.Value = 30
                self.HoverIdleRefresh.Value = 650
                self.PopupHideDelay.Value = 70
            elif name == "quiet":
                self.HoverMoveInterval.Value = 28
                self.HoverReadInterval.Value = 60
                self.HoverIdleRefresh.Value = 1100
                self.PopupHideDelay.Value = 110
            else:
                self.HoverMoveInterval.Value = 20
                self.HoverReadInterval.Value = 35
                self.HoverIdleRefresh.Value = 650
                self.PopupHideDelay.Value = 85
        finally:
            self._suspend_events = False
        self._update_value_labels()
        self._set_dirty(True)

    def _apply_preset(self, name):
        preset = PRESETS.get(name)
        if preset is None:
            return
        current = self._read()
        for key in FIELD_KEYS:
            current[key] = bool(preset.get(key, False))
        self._apply(current)
        self._set_dirty(True)
        self._update_preset_state()

    def _update_count(self):
        try:
            count = sum(1 for k, c in self._field_controls.items() if bool(c.IsChecked))
            self.SelectedText.Text = "{0} fields enabled".format(count)
            self.OverviewFieldCount.Text = str(count)
        except:
            pass
        try:
            cat_count = sum(1 for k, c in self._category_controls.items() if bool(c.IsChecked))
            self.OverviewCategoryCount.Text = str(cat_count)
        except:
            pass
        self._update_preset_state()

    def _current_preset_name(self):
        try:
            current = dict((key, bool(control.IsChecked)) for key, control in self._field_controls.items())
            for name, preset in PRESETS.items():
                match = True
                for key in FIELD_KEYS:
                    if bool(current.get(key, False)) != bool(preset.get(key, False)):
                        match = False
                        break
                if match:
                    return name
        except:
            pass
        return "Custom"

    def _update_preset_state(self):
        try:
            name = self._current_preset_name()
            self._active_preset = name
            self.OverviewPresetText.Text = name
            for preset_name, button in self._preset_buttons.items():
                button.Style = self.FindResource("PresetButtonActive" if preset_name == name else "PresetButton")
        except:
            pass

    def _set_dirty(self, dirty):
        self._dirty = bool(dirty)
        try:
            self.FooterStatus.Text = "Unsaved changes" if self._dirty else "Settings saved"
            self.FooterStatus.Foreground = self.FindResource("RB.Warning" if self._dirty else "RB.TextFaint")
        except:
            pass

    def _reset(self, sender, args):
        self._apply(dict(DEFAULTS))
        self._set_dirty(True)

    def _notify_runtime(self):
        # If Fab Hover is already running (even if toggled OFF/hidden), update its
        # settings immediately instead of waiting for the next file timestamp poll.
        try:
            from System.Windows import Application
            app = Application.Current
            if app is None:
                return
            for window in list(app.Windows):
                try:
                    if window.Title == "Fab Hover - Revit 2025" and hasattr(window, "reload_settings"):
                        window.reload_settings()
                        return
                except:
                    pass
        except:
            pass

    def _save(self, sender, args):
        values = self._read()
        if save_settings(values):
            self._notify_runtime()
            self._set_dirty(False)
            self.Close()
        else:
            forms.alert("Could not save Fab Hover settings.", title="Fab Hover")


DisplayOptions().ShowDialog()
