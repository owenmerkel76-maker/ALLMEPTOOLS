# -*- coding: utf-8 -*-
"""Shared Fab Hover settings schema for runtime and config UI."""
import os

SETTINGS_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "FabHover")
SETTINGS_PATH = os.path.join(SETTINGS_DIR, "display_options.ini")

# Keep defaults deliberately lean. Presets can enable richer information without
# making every normal hover query expensive.
DEFAULTS = {
    # Common identity / location
    "show_type": True,
    "show_family": False,
    "show_size": True,
    "show_length": True,
    "show_level": False,
    "show_offset": False,
    "show_system": True,
    "show_system_type": False,
    "show_system_classification": False,
    "show_system_abbr": False,
    "show_service": True,
    "show_service_abbr": False,
    "show_mark": False,
    "show_type_mark": False,
    "show_comments": False,
    "show_workset": False,
    "show_element_id": False,
    "show_open_connectors": False,
    "show_phase": False,

    # Duct / HVAC
    "show_width": False,
    "show_height": False,
    "show_diameter": False,
    "show_cfm": True,
    "show_flow": False,
    "show_velocity": False,
    "show_friction": False,
    "show_pressure_drop": False,
    "show_static_pressure": False,
    "show_pressure_class": False,
    "show_bod": False,
    "show_cod": False,
    "show_tod": False,
    "show_slope": False,
    "show_insulation": False,
    "show_lining": False,

    # Pipe / plumbing / hydronic
    "show_pipe_diameter": True,
    "show_pipe_inside_diameter": False,
    "show_pipe_outside_diameter": False,
    "show_pipe_flow": True,
    "show_pipe_velocity": False,
    "show_pipe_friction": False,
    "show_pipe_pressure_drop": False,
    "show_pipe_material": False,
    "show_pipe_schedule": False,
    "show_pipe_segment": False,
    "show_connection_type": False,
    "show_fluid_type": False,
    "show_fluid_temperature": False,
    "show_fixture_units": False,
    "show_cwfu": False,
    "show_hwfu": False,
    "show_wfu": False,
    "show_invert_elevation": False,
    "show_pipe_bottom_elevation": False,
    "show_pipe_top_elevation": False,
    "show_pipe_insulation": False,

    # Equipment / terminals / fixtures
    "show_gpm": False,
    "show_power": False,
    "show_voltage": False,
    "show_capacity": False,
    "show_manufacturer": False,
    "show_model": False,
    "show_connector_size": False,
    "show_space": False,

    # Fabrication metadata
    "show_part": False,
    "show_item_number": False,
    "show_pattern": False,
    "show_specification": False,
    "show_material": False,
    "show_gauge": False,
    "show_notes": False,
    "show_alias": False,
    "show_spool_name": False,
    "show_product_name": False,
    "show_vendor": False,

    # Diagnostic / future-proofing
    "show_all_instance_parameters": False,
    "show_all_type_parameters": False,

    # Supported categories
    "category_fab_ductwork": True,
    "category_fab_pipework": True,
    "category_fab_containment": False,
    "category_ducts": True,
    "category_duct_fittings": True,
    "category_duct_accessories": True,
    "category_flex_ducts": True,
    "category_air_terminals": True,
    "category_pipes": True,
    "category_pipe_fittings": True,
    "category_pipe_accessories": True,
    "category_flex_pipes": True,
    "category_plumbing_fixtures": True,
    "category_sprinklers": True,
    "category_mechanical_equipment": True,
    "category_specialty_equipment": True,

    # Popup appearance (kept lightweight; no live Revit API dependency)
    "popup_theme": "Navy",
    "popup_accent": "#168CF3",
    "popup_opacity": 94,
    "popup_corner_radius": 8.0,
    "popup_text_size": 10.5,
    "popup_width": 270,
    "popup_show_header": True,
    "popup_show_subtitle": True,
    "popup_show_icon": True,
    "popup_show_accent_bar": True,

    # Hover behavior / performance
    "popup_hide_when_no_target": True,
    "popup_hide_delay_ms": 85,
    "popup_offset_x": 14,
    "popup_offset_y": 10,
    "hover_move_interval_ms": 20,
    "hover_read_interval_ms": 35,
    "hover_idle_refresh_ms": 650,
}

FIELD_GROUPS = {
    "common": [
        ("show_type", "Type"), ("show_family", "Family"), ("show_size", "Size"),
        ("show_length", "Length"), ("show_level", "Level"), ("show_offset", "Offset / elevation"),
        ("show_system", "System name"), ("show_system_type", "System type"),
        ("show_system_classification", "System classification"), ("show_system_abbr", "System abbreviation"),
        ("show_service", "Fabrication service"), ("show_service_abbr", "Service abbreviation"),
        ("show_mark", "Mark"), ("show_type_mark", "Type mark"), ("show_phase", "Phase"),
    ],
    "hvac": [
        ("show_width", "Width"), ("show_height", "Height"), ("show_diameter", "Diameter"),
        ("show_cfm", "CFM / airflow"), ("show_flow", "Flow"), ("show_velocity", "Velocity"),
        ("show_friction", "Friction"), ("show_pressure_drop", "Pressure drop"),
        ("show_static_pressure", "Static pressure"), ("show_pressure_class", "Pressure class"),
        ("show_bod", "BOD / bottom elevation"), ("show_cod", "COD / center elevation"),
        ("show_tod", "TOD / top elevation"), ("show_slope", "Slope"),
        ("show_insulation", "Insulation"), ("show_lining", "Lining"),
    ],
    "plumbing": [
        ("show_pipe_diameter", "Nominal diameter"), ("show_pipe_inside_diameter", "Inside diameter"),
        ("show_pipe_outside_diameter", "Outside diameter"), ("show_pipe_flow", "Flow / GPM"),
        ("show_pipe_velocity", "Velocity"), ("show_pipe_friction", "Friction"),
        ("show_pipe_pressure_drop", "Pressure drop"), ("show_slope", "Slope"),
        ("show_pipe_material", "Pipe material"), ("show_pipe_schedule", "Schedule / type"),
        ("show_pipe_segment", "Pipe segment"), ("show_connection_type", "Connection type"),
        ("show_fluid_type", "Fluid type"), ("show_fluid_temperature", "Fluid temperature"),
        ("show_fixture_units", "Fixture units"), ("show_cwfu", "CWFU"), ("show_hwfu", "HWFU"),
        ("show_wfu", "WFU"), ("show_invert_elevation", "Invert elevation"),
        ("show_pipe_bottom_elevation", "Bottom elevation"), ("show_pipe_top_elevation", "Top elevation"),
        ("show_pipe_insulation", "Pipe insulation"),
    ],
    "equipment": [
        ("show_cfm", "CFM / airflow"), ("show_gpm", "GPM / water flow"),
        ("show_power", "Power"), ("show_voltage", "Voltage"), ("show_capacity", "Capacity"),
        ("show_manufacturer", "Manufacturer"), ("show_model", "Model"),
        ("show_connector_size", "Connector size"), ("show_space", "Space / room"),
        ("show_mark", "Mark"), ("show_type_mark", "Type mark"),
    ],
    "fabrication": [
        ("show_part", "Part / description"), ("show_item_number", "Item number"),
        ("show_pattern", "Pattern / CID"), ("show_specification", "Specification"),
        ("show_material", "Material"), ("show_gauge", "Gauge"),
        ("show_insulation", "Insulation"), ("show_lining", "Lining"),
        ("show_notes", "Fabrication notes"), ("show_alias", "Alias"),
        ("show_spool_name", "Spool name"), ("show_product_name", "Product name"),
        ("show_vendor", "Vendor / OEM"),
    ],
    "qa": [
        ("show_open_connectors", "Open connector count"), ("show_workset", "Workset"),
        ("show_comments", "Comments"), ("show_element_id", "Element ID"),
        ("show_all_instance_parameters", "All non-empty instance parameters"),
        ("show_all_type_parameters", "All non-empty type parameters"),
    ],
}

CATEGORY_GROUPS = {
    "hvac": [
        ("category_fab_ductwork", "Fabrication ductwork"),
        ("category_ducts", "Ducts"), ("category_duct_fittings", "Duct fittings"),
        ("category_duct_accessories", "Duct accessories"), ("category_flex_ducts", "Flex ducts"),
        ("category_air_terminals", "Air terminals"),
    ],
    "plumbing": [
        ("category_fab_pipework", "Fabrication pipework"),
        ("category_pipes", "Pipes"), ("category_pipe_fittings", "Pipe fittings"),
        ("category_pipe_accessories", "Pipe accessories / valves"), ("category_flex_pipes", "Flex pipes"),
        ("category_plumbing_fixtures", "Plumbing fixtures"), ("category_sprinklers", "Sprinklers"),
    ],
    "equipment": [
        ("category_mechanical_equipment", "Mechanical equipment"),
        ("category_specialty_equipment", "Specialty equipment / water equipment"),
        ("category_fab_containment", "Fabrication containment"),
    ],
}

FIELD_KEYS = []
for _group in FIELD_GROUPS.values():
    for _key, _label in _group:
        if _key not in FIELD_KEYS:
            FIELD_KEYS.append(_key)
CATEGORY_KEYS = []
for _group in CATEGORY_GROUPS.values():
    for _key, _label in _group:
        if _key not in CATEGORY_KEYS:
            CATEGORY_KEYS.append(_key)


def blank_fields():
    return dict((k, False) for k in FIELD_KEYS)


def _preset(**kwargs):
    v = blank_fields()
    v.update(kwargs)
    return v

PRESETS = {
    "General": _preset(
        show_type=True, show_size=True, show_length=True, show_system=True,
        show_service=True, show_cfm=True, show_pipe_diameter=True, show_pipe_flow=True,
        show_level=True,
    ),
    "HVAC Fabrication": _preset(
        show_type=True, show_size=True, show_length=True, show_service=True,
        show_part=True, show_item_number=True, show_material=True, show_specification=True,
        show_bod=True, show_cod=True, show_tod=True, show_slope=True,
        show_cfm=True, show_system=True, show_level=True,
    ),
    "Plumbing": _preset(
        show_type=True, show_size=True, show_length=True, show_pipe_diameter=True,
        show_pipe_flow=True, show_system=True, show_system_type=True,
        show_pipe_material=True, show_pipe_schedule=True, show_slope=True,
        show_level=True, show_fixture_units=True,
    ),
    "Coordination": _preset(
        show_type=True, show_size=True, show_length=True, show_system=True,
        show_bod=True, show_cod=True, show_tod=True, show_slope=True,
        show_invert_elevation=True, show_pipe_bottom_elevation=True,
        show_pipe_top_elevation=True, show_level=True, show_offset=True,
        show_open_connectors=True,
    ),
    "Equipment": _preset(
        show_type=True, show_family=True, show_mark=True, show_level=True,
        show_system=True, show_cfm=True, show_gpm=True, show_power=True,
        show_voltage=True, show_capacity=True, show_manufacturer=True,
        show_model=True, show_connector_size=True,
    ),
    "Minimal": _preset(
        show_type=True, show_size=True, show_length=True, show_system=True,
        show_pipe_diameter=True,
    ),
}


def parse_value(raw, default):
    text = str(raw).strip()
    if isinstance(default, bool):
        return text.lower() in ("1", "true", "yes", "on")
    if isinstance(default, int) and not isinstance(default, bool):
        try:
            return int(round(float(text)))
        except:
            return default
    if isinstance(default, float):
        try:
            return float(text)
        except:
            return default
    return text


def load_settings():
    values = dict(DEFAULTS)
    try:
        if os.path.isfile(SETTINGS_PATH):
            with open(SETTINGS_PATH, "r") as fh:
                for raw in fh:
                    line = raw.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    key = key.strip()
                    if key in values:
                        values[key] = parse_value(value, values[key])
    except:
        pass
    return values


def save_settings(values):
    tmp_path = SETTINGS_PATH + ".tmp"
    try:
        if not os.path.isdir(SETTINGS_DIR):
            os.makedirs(SETTINGS_DIR)
        with open(tmp_path, "w") as fh:
            fh.write("# ROBMEPTOOLS Fab Hover settings\n")
            fh.write("# Generated by Fab Hover Display Options\n")
            for key in sorted(DEFAULTS.keys()):
                value = values.get(key, DEFAULTS[key])
                default = DEFAULTS[key]
                if isinstance(default, bool):
                    out = "1" if bool(value) else "0"
                else:
                    out = str(value)
                fh.write("{0}={1}\n".format(key, out))
        try:
            if os.path.isfile(SETTINGS_PATH):
                os.remove(SETTINGS_PATH)
        except:
            pass
        os.rename(tmp_path, SETTINGS_PATH)
        return True
    except:
        try:
            if os.path.isfile(tmp_path):
                os.remove(tmp_path)
        except:
            pass
        return False
