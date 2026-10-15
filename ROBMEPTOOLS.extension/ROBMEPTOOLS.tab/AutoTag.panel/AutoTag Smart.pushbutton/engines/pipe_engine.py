# -*- coding: utf-8 -*-
"""
AutoTag Plumbing Smart V1.5 - pipe sheet review / verified tag accounting

Workflow
--------
1. Open AutoTag Smart.
2. Choose a loaded BOP event tag type on Tag Types.
3. Run AutoTag Plumbing; no sample tag placement or pick is required.

The tool supports BOTH native Revit Pipe and MEP Fabrication pipework.
It tags straight, horizontal/sloped pipe pieces when the connected network indicates one of these events:
    - horizontal left/right direction change
    - elevation change (vertical/steep transition pipe is NOT tagged)
    - size change
    - shape change (rectangular/oval/round)
    - last horizontal/sloped straight pipe piece before an end-cap fitting

For every information-changing event, the adjacent horizontal/sloped straight
pipe pieces are normally targeted. Vertical/steep transition pipe is traversed
for connectivity but is never itself tagged. Only unchanged routing-only fixture
tails are suppressed; size/elevation/profile/endcap events remain required.
Repeated turn/branch-only callouts along the
same local two-port pipe path are also consolidated to one human-style BOP tag.

It avoids duplicate tags, uses no-leader placement only when the tag genuinely fits on the pipe, scans
visible CAD/imports for collision scoring, and otherwise uses Revit-attached
leaders that stay straight when the direct route is clean, otherwise using a compact manual-style shoulder.

Designed for Revit 2025+ / pyRevit and written to remain IronPython-friendly.
The BOP event-tag selection determines whether the run targets native pipe or fabrication pipework.

Experimental Smart V9 layer:
- Current Local reproduces the production/local placement baseline.
- Smart V9 Balanced keeps the proven V6/V7 layout style but moves the hot candidate
  search into pure view-plane math, minimizes Revit API object creation, and uses
  one placement transaction instead of a SubTransaction for every tag.
- Smart Pipe V1 Fast narrows candidate/cluster breadth further for large views.
- Smart Pipe V1 Clean keeps a wider local search while retaining the V7 runtime shortcuts and V9 collision-safe escape search.
- Straight leaders remain the default. Doglegs stay exceptional.
The mature layout engine is retained, while host/event detection is adapted for native and fabrication pipework.
Pipe V1 tags direction changes, elevation offsets, size/profile changes, and capped ends.
"""

import math
import time
import os
import sys
import System
import json
import uuid
from collections import deque

from pyrevit import revit, DB, UI, forms, script

BUNDLE_DIR = os.path.dirname(__file__)
if BUNDLE_DIR not in sys.path:
    sys.path.insert(0, BUNDLE_DIR)
from autotag_menu import show_autotag_menu
from autotag_components import run_direct_component_tags, component_summary

AUTOTAG_RUN_OPTIONS = {}
AUTOTAG_ENABLED_REASONS = set(['turn', 'elevation', 'size', 'shape', 'endcap'])
AUTOTAG_EXTERNAL_OPTIONS = None
AUTOTAG_SUPPRESS_RESULT_DIALOG = False

# Human-reference pass: a turn that changes only direction does not need two
# identical BOP/size tags. Size, elevation, profile/shape and end-condition
# events remain strict two-sided coverage. This mirrors the supplied human
# drawing while preserving information-changing events.
SMART_HUMAN_TURN_DENSITY = True

# 2026-10-07 DWP human-density rule:
# Short local fixture tails/drops in bathroom groups do not need their own BOP
# callout. Keep the distribution/branch information, but suppress the final
# routing-only terminal piece when it reaches a Plumbing Fixture through at most
# a couple of local fittings. Changed-value events remain required.
SMART_SUPPRESS_FIXTURE_TAIL_BOP = True
FIXTURE_TAIL_MAX_LENGTH_FT = 6.0
FIXTURE_TAIL_MAX_FITTING_HOPS = 2

# v1.4 human-reference density: repeated turn/branch-only BOP targets on the
# same local two-port path carry the same information. Collapse those local
# duplicates while keeping every elevation/size/shape/endcap event strict.
SMART_HUMAN_LOCAL_TURN_CONSOLIDATION = True
HUMAN_LOCAL_TURN_MAX_SPAN_FT = 14.0


# -----------------------------------------------------------------------------
# USER-TUNABLE SETTINGS
# All layout distances are PAPER inches, so the appearance stays similar when
# view scale changes.
# -----------------------------------------------------------------------------
LEADER_SHOULDER_PAPER_IN = 0.040
TAG_CLEARANCE_PAPER_IN = 0.045
ANCHOR_FROM_CHANGE_PAPER_IN = 0.34

NO_LEADER_EXTRA_OFFSETS_PAPER_IN = [0.01, 0.03, 0.06]
NO_LEADER_ALONG_SHIFTS_PAPER_IN = [0.0, 0.08, -0.08, 0.16, -0.16]

# No-leader tags must stay visibly associated with their host duct. The solver
# still checks BOTH sides, but it is no longer allowed to drift far down a run
# just because a remote spot happens to be collision-free.
NO_LEADER_MAX_EXTRA_PAPER_IN = 0.05
NO_LEADER_MAX_ALONG_SHIFT_PAPER_IN = 0.10
NO_LEADER_CLEARANCE_HALO_PAPER_IN = 0.12
NO_LEADER_CLEARANCE_WEIGHT = 0.012

LEADER_EXTRA_OFFSETS_PAPER_IN = [0.10, 0.14, 0.18, 0.24, 0.32, 0.42, 0.54]
LEADER_ALONG_SHIFTS_PAPER_IN = [0.0, 0.08, -0.08, 0.16, -0.16, 0.26, -0.26, 0.38, -0.38]

# A no-leader candidate that touches even one DWG line will normally be rejected
# in favor of a cleaner candidate/leader location.
NO_LEADER_SCORE_LIMIT = 80.0

TURN_ANGLE_TOL_DEG = 8.0
HORIZONTAL_SLOPE_TOL = 0.060       # abs(direction.Z), ~3.4 degrees; accepts common drainage slopes
ELEVATION_TOL_FT = 1.0 / 192.0     # 1/16 inch model tolerance
SIZE_TOL_FT = 1.0 / 192.0          # 1/16 inch model tolerance
MAX_NETWORK_HOPS = 10
MAX_CAD_SEGMENTS = 90000
MAX_GRID_CELLS_PER_RECORD = 4096
CAD_SCAN_MARGIN_PAPER_IN = 1.50
TAG_SIZE_SAFETY_PAPER_IN = 0.035

# Collision weights. Higher = more strongly avoided.
W_TAG = 6000.0
W_ANNOTATION = 4500.0
W_DUCT = 1800.0
W_FITTING = 1900.0
W_CAD = 90.0
W_CAD_MAJOR = 900.0
W_CAD_MEDIUM = 240.0
W_CAD_HATCH = 0.08
W_LEADER = 900.0
W_OUTSIDE_CROP = 100000.0

# Leader-cleanup tuning. These affect placement aesthetics only; detection is
# intentionally untouched. Shoulder is intentionally very short to match the
# manual drafting style: tiny horizontal stub, then one diagonal to the host.
LEADER_LENGTH_PENALTY_PER_PAPER_IN = 420.0
LEADER_REVERSED_SHOULDER_PENALTY = 1400.0
LEADER_WRONG_SIDE_PENALTY = 50000.0

# Hard visual limits for leader routing. Normal candidates outside these limits
# are rejected rather than allowed to create the long diagonal leaders that are
# visually disconnected from their host. The solver has many close candidates
# before these limits are reached, so this is a safety rail, not the primary
# placement mechanism.
MAX_LEADER_TOTAL_PAPER_IN = 0.92
MAX_LEADER_DIAGONAL_PAPER_IN = 0.84
TAG_EDGE_SAFETY_PAPER_IN = 0.018

# V9 keeps only a light planning buffer. V8 proved that an oversized safety
# footprint collapses the normal candidate pool and pushes too many tags into
# overlap-tolerant emergency placement. V9 instead adds a collision-safe escape
# stage before emergency, so normal candidates can stay compact.
SMART_V8_RESERVE_PAD_PAPER_IN = 0.035
SMART_V8_MICRO_HARD_GAP_PAPER_IN = 0.060

# Dense-trunk coordination. These are intentionally layout-only settings. On
# near-vertical mains, leader tags softly favor the same open side/column as
# nearby tags and gain extra up/down candidates before moving farther away.
TRUNK_VERTICAL_RATIO = 1.35
TRUNK_NEIGHBOR_ACROSS_PAPER_IN = 1.35
TRUNK_NEIGHBOR_ALONG_PAPER_IN = 4.00
TRUNK_SIDE_CONSISTENCY_PENALTY = 80.0
TRUNK_COLUMN_TOL_PAPER_IN = 0.08
TRUNK_COLUMN_PENALTY_PER_PAPER_IN = 24.0
TRUNK_TAG_GAP_PAPER_IN = 0.10
TRUNK_TAG_GAP_PENALTY = 1200.0
TRUNK_EXTRA_ALONG_SHIFTS_PAPER_IN = [0.55, -0.55, 0.75, -0.75]

# Human-drafting layout engine.  Background CAD is layer-aware: hatch remains soft, while major architectural
# linework (walls, doors, partitions, etc.) is strongly discouraged for tag heads.
# MEP, tags, annotations and existing leaders remain hard obstacles.
CAD_HEAD_SCORE_CAP = 1200.0
CAD_LEADER_SCORE_CAP = 180.0
HUMAN_LEADER_GAPS_PAPER_IN = [0.05, 0.10, 0.16, 0.24]
HUMAN_LEADER_ALONG_PAPER_IN = [0.0, 0.10, -0.10, 0.20, -0.20]
HUMAN_DIAGONAL_RUN_PAPER_IN = [0.08, 0.14, 0.22, 0.30]
HUMAN_ANGLE_TARGET_DEG = 55.0
HUMAN_ANGLE_PENALTY_PER_DEG = 1.8
HUMAN_EDGE_AWAY_PENALTY = 120.0
HUMAN_MAX_CANDIDATES = 64
MAX_LAYOUT_ATTEMPTS = 12
EMERGENCY_LEADER_GAPS_PAPER_IN = [0.28, 0.36, 0.44]
EMERGENCY_ALONG_PAPER_IN = [0.0, 0.14, -0.14, 0.28, -0.28]

# Human-style placement tiers. Major/long architectural CAD lines block tag heads,
# while hatch remains a negligible soft cost. The final emergency search is local
# and deterministic: it chooses the least-bad nearby option instead of failing.
CAD_HEAD_BLOCK_THRESHOLD = 1800.0
INLINE_HOST_FIT_RATIO = 0.82
INLINE_HOST_GAP_PAPER_IN = 0.02
HUMAN_MIN_LEADER_ANGLE_DEG = 24.0
HUMAN_MAX_LEADER_ANGLE_DEG = 82.0
EMERGENCY_MAX_TOTAL_PAPER_IN = 0.68
EMERGENCY_HARD_WEIGHT = 18.0

# -----------------------------------------------------------------------------
# Two-pass relaxed human lane/group planner
#
# Mature annotation workflows do not solve dense tags one-by-one.  They first
# find sensible local choices, then coordinate nearby annotations into a common
# side/lane before anything is committed to Revit.  These settings affect only
# placement; pipe-event detection remains untouched.
# -----------------------------------------------------------------------------
LANE_ORIENTATION_RATIO = 1.35
LANE_GROUP_ACROSS_PAPER_IN = 0.48
LANE_GROUP_ALONG_PAPER_IN = 3.40
LANE_MAX_GROUP_SIZE = 6
LANE_BEAM_WIDTH = 10
LANE_CANDIDATES_PER_TARGET = 16
LANE_EMERGENCY_CANDIDATES = 0
LANE_MIN_NORMAL_CANDIDATES = 1
LANE_SIDE_MISMATCH_PENALTY = 2400.0
LANE_ALIGNMENT_PENALTY_PER_PAPER_IN = 18.0
LANE_TAG_GAP_PAPER_IN = 0.11
LANE_TAG_GAP_PENALTY = 850.0
LANE_LEADER_CROSS_PENALTY = 12000.0
LANE_ORDER_REVERSE_PENALTY = 4200.0
LANE_ORDER_TOL_PAPER_IN = 0.08
LANE_GLOBAL_LEADER_CROSS_PENALTY = 9000.0

# v7 relaxed-human routing.  The main lesson from the v6 field test was that
# strict lane alignment can never outrank local leader quality.  Long leaders
# receive a convex (quadratic) distance cost, CAD remains a strong preference
# rather than a reason to throw a tag across the plan, and leader anchors may
# slide along the tagged straight piece before the tag head is moved farther.
PREFERRED_LEADER_TOTAL_PAPER_IN = 0.30
NORMAL_LEADER_HARD_MAX_PAPER_IN = 0.55
NORMAL_LEADER_DIAG_MAX_PAPER_IN = 0.50
LEADER_DISTANCE_LINEAR = 220.0
LEADER_DISTANCE_QUADRATIC = 2600.0
CAD_LOCAL_OVERLAP_PENALTY = 1.15
CAD_EXTREME_BLOCK_THRESHOLD = 3600.0
ANCHOR_SWEEP_PAPER_IN = [0.0, 0.12, -0.12, 0.24, -0.24]
LANE_SIDE_BUCKET_COUNT = 6

# v8 post-placement repair pass. The initial v7 solver remains unchanged.
# Only leaders that are objectively questionable are reconsidered after all
# tags exist, using the final annotation layout as context.
REPAIR_TRIGGER_LONG_PAPER_IN = 0.68
REPAIR_TARGET_TOTAL_PAPER_IN = 0.46
REPAIR_MAX_TOTAL_PAPER_IN = 0.58
REPAIR_MIN_LENGTH_GAIN_PAPER_IN = 0.08
REPAIR_MIN_SCORE_GAIN = 220.0
REPAIR_MAX_CANDIDATES = 10
REPAIR_BAD_ANGLE_MIN_DEG = 24.0
REPAIR_BAD_ANGLE_MAX_DEG = 82.0
REPAIR_EMERGENCY_SOURCE_PENALTY = 900.0
REPAIR_LAST_SOURCE_PENALTY = 2200.0
REPAIR_HARD_COLLISION_MULT = 24.0
REPAIR_MAX_RECORDS = 20
REPAIR_CAD_HEAD_MULT = 0.55
REPAIR_CAD_LEADER_MULT = 0.18

# V3 repair/search tuning. These remain placement-only.
V3_REPAIR_WIDE_GAPS_PAPER_IN = [0.04, 0.08, 0.14, 0.20, 0.28, 0.36]
V3_REPAIR_WIDE_ALONG_PAPER_IN = [0.0, 0.08, -0.08, 0.16, -0.16, 0.28, -0.28, 0.40, -0.40]
V3_REPAIR_MAX_POOL = 48

# V4 cleanup searches a little wider and accepts a visible shortening even when
# it cannot get all the way under the old 0.54-in hard repair ceiling.
V4_REPAIR_MAX_POOL = 64
V4_REPAIR_ANCHOR_SWEEP_PAPER_IN = [0.0, 0.06, -0.06, 0.12, -0.12, 0.20, -0.20, 0.30, -0.30]

# -----------------------------------------------------------------------------
# AutoTag Plumbing Smart V1 runtime controls
# -----------------------------------------------------------------------------
# Detection is deliberately NOT controlled here. V9 changes placement/runtime/collision routing only.
SMART_VERSION = '9.1'
SMART_ENGINE_LABEL = 'Smart Pipe V1 Balanced (recommended)'
SMART_V3_ACTIVE = True          # compatibility flag for proven V3 helpers
SMART_V4_ACTIVE = True          # compatibility flag for V4 helpers/telemetry
SMART_V5_ACTIVE = True          # compatibility flag for V5 plumbing
SMART_V6_ACTIVE = True
SMART_GROUP_COORDINATION = True
SMART_ENABLE_REPAIR = False     # zero-yield legacy cleanup stays off by default
SMART_STRAIGHT_BIAS = True
SMART_STRAIGHT_FIRST = True
SMART_ALLOW_DOGLEGS_WHEN_STRAIGHT = False
SMART_FORCE_LEADERS = False
SMART_SOFT_MEP_CROSSINGS = True
SMART_DEBUG_REPORT = False
SMART_SELECTION_ONLY = False
SMART_MICRO_CLUSTERING = True
SMART_BASE_POINT_COUNT = 2
SMART_ANCHOR_LIMIT = 3
SMART_MEP_CROSS_MAX_SCORE = 3200.0
SMART_MEP_CROSS_PENALTY_MULT = 0.24
SMART_CLUSTER_DOGLEG_PENALTY = 1100.0
SMART_DOGLEG_BASE = 190.0
SMART_INLINE_SPILL_PENALTY = 65.0
SMART_INLINE_MIN_HOST_PAPER_IN = 0.020
SMART_NORMAL_STRAIGHT_MAX_PAPER_IN = 0.54

# Legacy settings retained only for Current Local compatibility.
SMART_RESCUE_ENABLED = False
SMART_RESCUE_TRIGGER_PAPER_IN = 0.49
SMART_RESCUE_BASE_SCORE = 2400.0
SMART_RESCUE_MAX_CANDIDATES = 18
SMART_RESCUE_GAPS_PAPER_IN = [0.08, 0.14, 0.22, 0.30, 0.38]
SMART_RESCUE_ALONG_PAPER_IN = [0.0, 0.12, -0.12, 0.24, -0.24, 0.36, -0.36]
SMART_RESCUE_ANCHOR_LIMIT = 5
SMART_BRIDGE_ENABLED = False
SMART_BRIDGE_BASE_SCORE = 3800.0
SMART_BRIDGE_MAX_CANDIDATES = 0
SMART_BRIDGE_GAPS_PAPER_IN = []
SMART_BRIDGE_ALONG_PAPER_IN = []
SMART_BRIDGE_ANCHOR_LIMIT = 0
SMART_BRIDGE_MEP_MAX_SCORE = 6800.0
SMART_BRIDGE_MAX_LENGTH_PAPER_IN = 0.68
SMART_EMERGENCY_SCORE_FLOOR = 8000.0
SMART_UNIFIED_POOL_MAX = 40

# V6 adaptive staged cloud. The biggest V5 cost was 47k head checks and Stage B
# on 146/216 targets. V6 stops the compact search once it has enough good routes
# and runs Stage B only when Stage A returns NO valid route.
SMART_V6_EXPANDED_BASE_SCORE = 2350.0
SMART_V6_EXPANDED_MAX_LENGTH = 0.62
SMART_V6_EXPANDED_MEP_MAX_SCORE = 7600.0
SMART_V6_REUSE_BASE_SCORE = 5200.0
SMART_V6_REUSE_MAX_LENGTH = 0.64
SMART_V6_REUSE_MEP_MAX_SCORE = 11000.0
SMART_V6_POOL_MAX = 30
SMART_V6_STAGE_RESULT_TARGET = 6
SMART_V6_EARLY_SHORT_LENGTH = 0.42
SMART_V6_STAGE_A_GAPS = [0.00, 0.04, 0.08, 0.14]
SMART_V6_STAGE_A_SHIFTS = [0.0, 0.06, -0.06, 0.12, -0.12]
SMART_V6_STAGE_B_GAPS = [0.18, 0.26, 0.36]
SMART_V6_STAGE_B_SHIFTS = [0.0, 0.18, -0.18, 0.30, -0.30, 0.42, -0.42]
SMART_V6_INLINE_SHIFTS = [0.0, 0.06, -0.06, 0.12, -0.12, 0.20, -0.20]
SMART_V6_DOGLEG_HEAD_LIMIT = 8
SMART_V6_DOGLEG_ANCHOR_LIMIT = 2
SMART_V6_REUSE_HEAD_LIMIT = 12
SMART_V6_REUSE_ANCHOR_LIMIT = 3

# V9 collision-safe escape stage. This is intentionally wider than Stage B but
# still rejects tag-head collisions and blocking leader crossings. It is cheaper
# and visually safer than dropping directly into the overlap-tolerant emergency
# routine. Only targets with no normal/reuse route ever pay for this search.
SMART_V9_ESCAPE_BASE_SCORE = 6500.0
SMART_V9_ESCAPE_MAX_LENGTH = 0.74
SMART_V9_ESCAPE_MEP_MAX_SCORE = 18000.0
SMART_V9_ESCAPE_GAPS = [0.18, 0.26, 0.36, 0.48, 0.62]
SMART_V9_ESCAPE_SHIFTS = [0.0, 0.16, -0.16, 0.30, -0.30, 0.48, -0.48, 0.68, -0.68]
SMART_V9_ESCAPE_BASE_COUNT = 3
SMART_V9_ESCAPE_ANCHOR_LIMIT = 3
SMART_V9_ESCAPE_MAX_RESULTS = 8

SMART_MICRO_RADIUS_PAPER_IN = 1.48
SMART_MICRO_GROUP_SIZE = 7
SMART_MICRO_BEAM_WIDTH = 10
SMART_MICRO_CANDIDATES_PER_TARGET = 8
SMART_LENGTH_BREAK_1 = 0.35
SMART_LENGTH_BREAK_2 = 0.50
SMART_LENGTH_BREAK_3 = 0.60
SMART_TELEMETRY_ENABLED = True


uidoc = revit.uidoc
doc = revit.doc
view = doc.ActiveView
output = script.get_output()

try:
    RIGHT = view.RightDirection
    UP = view.UpDirection
except Exception:
    # Keep module import safe in unsupported views. main() will show the user a
    # friendly plan-view message before any geometry logic runs.
    RIGHT = DB.XYZ.BasisX
    UP = DB.XYZ.BasisY

# Per-run caches. The command never edits duct geometry, so caching these
# Revit API lookups is safe and substantially reduces repeated connector/curve
# access on larger networks. pyRevit reloads this module for each execution.
_DUCT_SIZE_CACHE = {}
_FAB_STRAIGHT_FALLBACK_CACHE = {}
_FAB_STRAIGHT_FALLBACK_IDS = set()
_FAB_RECOVERY_LINE_CACHE = {}
_FAB_RECOVERY_MAIN_CONNECTORS = {}
_DUCT_LINE_CACHE = {}
_DUCT_DIRECTION_CACHE = {}
_HORIZONTAL_DUCT_CACHE = {}
_CONNECTOR_CACHE = {}
_PHYSICAL_CONNECTOR_CACHE = {}
_ENDCAP_FITTING_CACHE = {}
_PASS_THROUGH_FITTING_CACHE = {}
_CENTER_ELEV_CACHE = {}
_AXIS_UV_CACHE = {}
_PLAN_HALF_WIDTH_CACHE = {}
_TAG_MEASURE_KEY_CACHE = {}
_LAYOUT_SERVICE_KEY_CACHE = {}
_V7_HOST_CONTEXT_CACHE = {}
_V6_CLEAR_HEAD_CACHE = {}

try:
    _PAPER_TO_MODEL_FACTOR = float(max(1, view.Scale)) / 12.0
except Exception:
    _PAPER_TO_MODEL_FACTOR = 1.0 / 12.0


# -----------------------------------------------------------------------------
# Smart V9 placement telemetry
# -----------------------------------------------------------------------------
_LAYOUT_TELEMETRY = {
    'target_reasons': {},
    'raw_rejects': {},
    'pool_counts': {},
    'normal_empty': set(),
    'rescue_used': set(),
    'bridge_used': set(),
    'emergency_used': set(),
    'v5_heads_tested': 0,
    'v5_clear_heads': 0,
    'v5_anchor_tests': 0,
    'v5_expanded_targets': set(),
    'v6_reuse_used': set(),
    'v6_stage_a_early_stops': 0,
    'v6_emergency_head_tests': 0,
    'v7_xyz_materialized': 0,
    'v7_fast_straight_accepts': 0,
    'v7_fast_inline_accepts': 0,
    'v7_single_tx_tags': 0,
    'v8_preplanned_replans': 0,
    'v9_escape_used': set(),
    'v9_escape_head_tests': 0,
    'v9_emergency_text_blocked_heads': 0,
}




def _telemetry_reset():
    _LAYOUT_TELEMETRY['target_reasons'] = {}
    _LAYOUT_TELEMETRY['raw_rejects'] = {}
    _LAYOUT_TELEMETRY['pool_counts'] = {}
    _LAYOUT_TELEMETRY['normal_empty'] = set()
    _LAYOUT_TELEMETRY['rescue_used'] = set()
    _LAYOUT_TELEMETRY['bridge_used'] = set()
    _LAYOUT_TELEMETRY['emergency_used'] = set()
    _LAYOUT_TELEMETRY['v5_heads_tested'] = 0
    _LAYOUT_TELEMETRY['v5_clear_heads'] = 0
    _LAYOUT_TELEMETRY['v5_anchor_tests'] = 0
    _LAYOUT_TELEMETRY['v5_expanded_targets'] = set()
    _LAYOUT_TELEMETRY['v6_reuse_used'] = set()
    _LAYOUT_TELEMETRY['v6_stage_a_early_stops'] = 0
    _LAYOUT_TELEMETRY['v6_emergency_head_tests'] = 0
    _LAYOUT_TELEMETRY['v7_xyz_materialized'] = 0
    _LAYOUT_TELEMETRY['v7_fast_straight_accepts'] = 0
    _LAYOUT_TELEMETRY['v7_fast_inline_accepts'] = 0
    _LAYOUT_TELEMETRY['v7_single_tx_tags'] = 0
    _LAYOUT_TELEMETRY['v8_preplanned_replans'] = 0
    _LAYOUT_TELEMETRY['v9_escape_used'] = set()
    _LAYOUT_TELEMETRY['v9_escape_head_tests'] = 0
    _LAYOUT_TELEMETRY['v9_emergency_text_blocked_heads'] = 0
    _V6_CLEAR_HEAD_CACHE.clear()
    _V7_HOST_CONTEXT_CACHE.clear()
    _TAG_MEASURE_KEY_CACHE.clear()
    _LAYOUT_SERVICE_KEY_CACHE.clear()


def _telemetry_reject(duct, reason):
    if not SMART_TELEMETRY_ENABLED or duct is None:
        return
    try:
        did = eid_int(duct.Id)
    except Exception:
        return
    raw = _LAYOUT_TELEMETRY['raw_rejects']
    raw[reason] = raw.get(reason, 0) + 1
    by_target = _LAYOUT_TELEMETRY['target_reasons']
    if did not in by_target:
        by_target[did] = set()
    by_target[did].add(reason)


def _telemetry_pool(duct, tier, count):
    if not SMART_TELEMETRY_ENABLED or duct is None:
        return
    try:
        did = eid_int(duct.Id)
    except Exception:
        return
    pools = _LAYOUT_TELEMETRY['pool_counts']
    key = (did, tier)
    old = pools.get(key)
    if old is None or count > old:
        pools[key] = count
    if tier == 'normal' and count <= 0:
        _LAYOUT_TELEMETRY['normal_empty'].add(did)
    elif tier == 'rescue' and count > 0:
        _LAYOUT_TELEMETRY['rescue_used'].add(did)
    elif tier == 'bridge' and count > 0:
        _LAYOUT_TELEMETRY['bridge_used'].add(did)
    elif tier == 'emergency' and count > 0:
        _LAYOUT_TELEMETRY['emergency_used'].add(did)


def _telemetry_reason_target_counts():
    counts = {}
    for did, reasons in _LAYOUT_TELEMETRY.get('target_reasons', {}).items():
        for reason in reasons:
            counts[reason] = counts.get(reason, 0) + 1
    return counts


def _telemetry_top_reasons(limit=5):
    counts = _telemetry_reason_target_counts()
    # Inline eligibility is useful as a separate diagnostic but should not bury
    # the actual leader/fallback rejection reasons in the top list.
    hidden = set(['inline_ineligible'])
    items = [(k, v) for k, v in counts.items() if k not in hidden]
    items.sort(key=lambda x: (-x[1], x[0]))
    return items[:max(0, int(limit))]


def _layout_source_from_score(score):
    try:
        value = float(score)
    except Exception:
        return 'normal'
    if value >= 900000.0:
        return 'last'
    if value >= SMART_EMERGENCY_SCORE_FLOOR:
        return 'emergency'
    if SMART_V6_ACTIVE and value >= SMART_V9_ESCAPE_BASE_SCORE:
        return 'escape'
    if SMART_V6_ACTIVE and value >= SMART_V6_REUSE_BASE_SCORE:
        return 'bridge'
    if SMART_V6_ACTIVE and value >= SMART_V6_EXPANDED_BASE_SCORE:
        return 'rescue'
    if SMART_V5_ACTIVE and value >= 2400.0:
        return 'rescue'
    if SMART_V4_ACTIVE and value >= SMART_BRIDGE_BASE_SCORE:
        return 'bridge'
    if SMART_V3_ACTIVE and value >= SMART_RESCUE_BASE_SCORE:
        return 'rescue'
    return 'normal'

def eid_int(eid):
    try:
        return int(eid.Value)
    except Exception:
        return int(eid.IntegerValue)


def bic_int(bic):
    """Return a BuiltInCategory id safely on Revit 2024+ (64-bit ElementId)."""
    try:
        return eid_int(DB.ElementId(bic))
    except Exception:
        return int(bic)


def paper_to_model(paper_inches):
    # View scale is constant for the whole command. Avoid hitting the Revit API
    # for view.Scale during every layout candidate calculation.
    return float(paper_inches) * _PAPER_TO_MODEL_FACTOR


def uv_of_point(p):
    return (p.DotProduct(RIGHT), p.DotProduct(UP))


def vec_from_uv(du, dv):
    return RIGHT.Multiply(du) + UP.Multiply(dv)


def dist2d_uv(a, b):
    du = a[0] - b[0]
    dv = a[1] - b[1]
    return math.sqrt(du * du + dv * dv)


def normalize2d(du, dv):
    ln = math.sqrt(du * du + dv * dv)
    if ln < 1e-9:
        return None
    return (du / ln, dv / ln)


def rect_expand(r, pad):
    return (r[0] - pad, r[1] - pad, r[2] + pad, r[3] + pad)


def rect_union(rects):
    valid = [r for r in rects if r is not None]
    if not valid:
        return None
    return (min(r[0] for r in valid),
            min(r[1] for r in valid),
            max(r[2] for r in valid),
            max(r[3] for r in valid))


def rect_intersects(a, b):
    return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])


def rect_intersection(a, b):
    if a is None:
        return b
    if b is None:
        return a
    r = (max(a[0], b[0]), max(a[1], b[1]),
         min(a[2], b[2]), min(a[3], b[3]))
    if r[0] > r[2] or r[1] > r[3]:
        return None
    return r


def rect_contains_rect(outer, inner):
    return (inner[0] >= outer[0] and inner[1] >= outer[1] and
            inner[2] <= outer[2] and inner[3] <= outer[3])


def point_in_rect(p, r):
    return p[0] >= r[0] and p[0] <= r[2] and p[1] >= r[1] and p[1] <= r[3]


def orient2d(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def segments_intersect(a, b, c, d):
    # Fast bbox reject first.
    if max(a[0], b[0]) < min(c[0], d[0]) or max(c[0], d[0]) < min(a[0], b[0]):
        return False
    if max(a[1], b[1]) < min(c[1], d[1]) or max(c[1], d[1]) < min(a[1], b[1]):
        return False
    o1 = orient2d(a, b, c)
    o2 = orient2d(a, b, d)
    o3 = orient2d(c, d, a)
    o4 = orient2d(c, d, b)
    eps = 1e-9
    if ((o1 > eps and o2 < -eps) or (o1 < -eps and o2 > eps)) and \
       ((o3 > eps and o4 < -eps) or (o3 < -eps and o4 > eps)):
        return True
    # Collinear/touching cases: bbox overlap is enough after near-zero orientation.
    if abs(o1) <= eps and point_in_rect(c, (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))):
        return True
    if abs(o2) <= eps and point_in_rect(d, (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))):
        return True
    if abs(o3) <= eps and point_in_rect(a, (min(c[0], d[0]), min(c[1], d[1]), max(c[0], d[0]), max(c[1], d[1]))):
        return True
    if abs(o4) <= eps and point_in_rect(b, (min(c[0], d[0]), min(c[1], d[1]), max(c[0], d[0]), max(c[1], d[1]))):
        return True
    return False


def segment_intersects_rect(a, b, r):
    if point_in_rect(a, r) or point_in_rect(b, r):
        return True
    p1 = (r[0], r[1])
    p2 = (r[2], r[1])
    p3 = (r[2], r[3])
    p4 = (r[0], r[3])
    return (segments_intersect(a, b, p1, p2) or
            segments_intersect(a, b, p2, p3) or
            segments_intersect(a, b, p3, p4) or
            segments_intersect(a, b, p4, p1))


def bbox_to_rect(bb):
    if bb is None:
        return None
    try:
        tr = bb.Transform
    except Exception:
        tr = DB.Transform.Identity
    mn = bb.Min
    mx = bb.Max
    pts = []
    for x in [mn.X, mx.X]:
        for y in [mn.Y, mx.Y]:
            for z in [mn.Z, mx.Z]:
                p = DB.XYZ(x, y, z)
                try:
                    p = tr.OfPoint(p)
                except Exception:
                    pass
                pts.append(uv_of_point(p))
    if not pts:
        return None
    us = [p[0] for p in pts]
    vs = [p[1] for p in pts]
    return (min(us), min(vs), max(us), max(vs))


def element_rect(elem):
    try:
        return bbox_to_rect(elem.get_BoundingBox(view))
    except Exception:
        return None


def crop_rect_for_view(v):
    try:
        if not v.CropBoxActive:
            return None
        return bbox_to_rect(v.CropBox)
    except Exception:
        return None


# -----------------------------------------------------------------------------
# Spatial obstacle index
# -----------------------------------------------------------------------------
class SpatialGrid(object):
    def __init__(self, cell_size):
        self.cell = max(cell_size, 0.10)
        self.cells = {}
        self.records = []
        self.oversized = []
        self.inactive = set()
        self.source_records = {}
        self._marks = []
        self._query_stamp = 0
        self.query_count = 0

    def _bounds(self, r):
        x0 = int(math.floor(r[0] / self.cell))
        y0 = int(math.floor(r[1] / self.cell))
        x1 = int(math.floor(r[2] / self.cell))
        y1 = int(math.floor(r[3] / self.cell))
        return x0, y0, x1, y1

    def _cell_range(self, r):
        x0, y0, x1, y1 = self._bounds(r)
        nx = x1 - x0 + 1
        ny = y1 - y0 + 1
        if nx <= 0 or ny <= 0 or (nx * ny) > MAX_GRID_CELLS_PER_RECORD:
            return None
        return x0, y0, x1, y1

    def _add_record(self, rec, bbox):
        idx = len(self.records)
        self.records.append(rec)
        self._marks.append(0)
        try:
            source_id = rec[4]
            if source_id is not None:
                if source_id not in self.source_records:
                    self.source_records[source_id] = []
                self.source_records[source_id].append(idx)
        except Exception:
            pass
        bounds = self._cell_range(bbox)
        if bounds is None:
            self.oversized.append(idx)
            return
        x0, y0, x1, y1 = bounds
        for ix in range(x0, x1 + 1):
            for iy in range(y0, y1 + 1):
                key = (ix, iy)
                bucket = self.cells.get(key)
                if bucket is None:
                    bucket = []
                    self.cells[key] = bucket
                bucket.append(idx)

    def add_rect(self, kind, r, weight, source_id=None):
        if r is None:
            return
        rec = ('rect', kind, r, weight, source_id)
        self._add_record(rec, r)

    def add_segment(self, kind, a, b, weight, source_id=None):
        r = (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))
        rec = ('seg', kind, (a, b), weight, source_id)
        self._add_record(rec, r)

    def _iter_candidate_indices(self, r):
        """Yield unique nearby records without constructing a temporary set."""
        self.query_count += 1
        self._query_stamp += 1
        if self._query_stamp >= 2000000000:
            self._query_stamp = 1
            for i in range(len(self._marks)):
                self._marks[i] = 0
        stamp = self._query_stamp
        bounds = self._cell_range(r)
        if bounds is None:
            for idx in range(len(self.records)):
                yield idx
            return
        for idx in self.oversized:
            if self._marks[idx] != stamp:
                self._marks[idx] = stamp
                yield idx
        x0, y0, x1, y1 = bounds
        for ix in range(x0, x1 + 1):
            for iy in range(y0, y1 + 1):
                for idx in self.cells.get((ix, iy), ()):
                    if self._marks[idx] == stamp:
                        continue
                    self._marks[idx] = stamp
                    yield idx

    def remove_source(self, source_id):
        if source_id is None:
            return
        for idx in self.source_records.get(source_id, []):
            self.inactive.add(idx)

    def score_rect(self, r, ignore_source_id=None):
        score = 0.0
        for idx in self._iter_candidate_indices(r):
            if idx in self.inactive:
                continue
            rec = self.records[idx]
            if ignore_source_id is not None and rec[4] == ignore_source_id:
                continue
            if rec[0] == 'rect':
                if rect_intersects(r, rec[2]):
                    score += rec[3]
            else:
                a, b = rec[2]
                if segment_intersects_rect(a, b, r):
                    score += rec[3]
        return score

    def score_segment(self, a, b, ignore_source_id=None):
        br = (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))
        score = 0.0
        for idx in self._iter_candidate_indices(br):
            if idx in self.inactive:
                continue
            rec = self.records[idx]
            if ignore_source_id is not None and rec[4] == ignore_source_id:
                continue
            if rec[0] == 'rect':
                hit = segment_intersects_rect(a, b, rec[2])
            else:
                c, d = rec[2]
                hit = segments_intersect(a, b, c, d)
            if not hit:
                continue
            kind = rec[1]
            if kind == 'cad':
                mult = 0.16
            elif kind in ('duct', 'fitting', 'accessory', 'flexduct', 'terminal', 'equipment'):
                mult = 1.15
            elif kind in ('tag', 'annotation'):
                mult = 1.00
            elif kind == 'leader':
                mult = 1.50
            else:
                mult = 0.35
            score += rec[3] * mult
        return score

    def rect_hits_kinds(self, r, kinds, ignore_source_id=None):
        """Fast boolean query used by emergency ranking to protect text."""
        wanted = kinds if isinstance(kinds, set) else set(kinds)
        for idx in self._iter_candidate_indices(r):
            if idx in self.inactive:
                continue
            rec = self.records[idx]
            if ignore_source_id is not None and rec[4] == ignore_source_id:
                continue
            if rec[1] not in wanted:
                continue
            if rec[0] == 'rect':
                hit = rect_intersects(r, rec[2])
            else:
                a, b = rec[2]
                hit = segment_intersects_rect(a, b, r)
            if hit:
                return True
        return False

    def score_rect_components(self, r, ignore_source_id=None):
        hard = 0.0
        cad = 0.0
        for idx in self._iter_candidate_indices(r):
            if idx in self.inactive:
                continue
            rec = self.records[idx]
            if ignore_source_id is not None and rec[4] == ignore_source_id:
                continue
            if rec[0] == 'rect':
                hit = rect_intersects(r, rec[2])
            else:
                a, b = rec[2]
                hit = segment_intersects_rect(a, b, r)
            if not hit:
                continue
            if rec[1] == 'cad':
                cad += rec[3]
            else:
                hard += rec[3]
        return hard, cad

    def score_rect_components_fast(self, r, ignore_source_id=None):
        """Normal-search head test: return immediately on the first hard hit."""
        cad = 0.0
        for idx in self._iter_candidate_indices(r):
            if idx in self.inactive:
                continue
            rec = self.records[idx]
            if ignore_source_id is not None and rec[4] == ignore_source_id:
                continue
            if rec[0] == 'rect':
                hit = rect_intersects(r, rec[2])
            else:
                a, b = rec[2]
                hit = segment_intersects_rect(a, b, r)
            if not hit:
                continue
            if rec[1] == 'cad':
                cad += rec[3]
            else:
                return rec[3], cad
        return 0.0, cad

    def score_segment_components(self, a, b, ignore_source_id=None):
        br = (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))
        hard = 0.0
        cad = 0.0
        for idx in self._iter_candidate_indices(br):
            if idx in self.inactive:
                continue
            rec = self.records[idx]
            if ignore_source_id is not None and rec[4] == ignore_source_id:
                continue
            if rec[0] == 'rect':
                hit = segment_intersects_rect(a, b, rec[2])
            else:
                c, d = rec[2]
                hit = segments_intersect(a, b, c, d)
            if not hit:
                continue
            kind = rec[1]
            if kind == 'cad':
                cad += rec[3]
            elif kind == 'leader':
                hard += rec[3] * 1.50
            elif kind in ('duct', 'fitting', 'accessory', 'flexduct', 'terminal', 'equipment'):
                hard += rec[3] * 1.15
            else:
                hard += rec[3]
        return hard, cad

    def score_segment_detail(self, a, b, ignore_source_id=None):
        br = (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))
        result = {'cad': 0.0, 'mep': 0.0, 'blocking': 0.0, 'leader': 0.0}
        for idx in self._iter_candidate_indices(br):
            if idx in self.inactive:
                continue
            rec = self.records[idx]
            if ignore_source_id is not None and rec[4] == ignore_source_id:
                continue
            if rec[0] == 'rect':
                hit = segment_intersects_rect(a, b, rec[2])
            else:
                c, d = rec[2]
                hit = segments_intersect(a, b, c, d)
            if not hit:
                continue
            kind = rec[1]
            if kind == 'cad':
                result['cad'] += rec[3]
            elif kind in ('duct', 'fitting', 'accessory', 'flexduct', 'terminal', 'equipment'):
                result['mep'] += rec[3] * 1.15
            elif kind == 'leader':
                value = rec[3] * 1.50
                result['leader'] += value
                result['blocking'] += value
            else:
                result['blocking'] += rec[3]
        return result

    def score_segment_detail_fast(self, a, b, ignore_source_id=None):
        """Normal-search leader test with an early exit on hard annotation/leader hits."""
        br = (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))
        result = {'cad': 0.0, 'mep': 0.0, 'blocking': 0.0, 'leader': 0.0}
        for idx in self._iter_candidate_indices(br):
            if idx in self.inactive:
                continue
            rec = self.records[idx]
            if ignore_source_id is not None and rec[4] == ignore_source_id:
                continue
            if rec[0] == 'rect':
                hit = segment_intersects_rect(a, b, rec[2])
            else:
                c, d = rec[2]
                hit = segments_intersect(a, b, c, d)
            if not hit:
                continue
            kind = rec[1]
            if kind == 'cad':
                result['cad'] += rec[3]
            elif kind in ('duct', 'fitting', 'accessory', 'flexduct', 'terminal', 'equipment'):
                result['mep'] += rec[3] * 1.15
            elif kind == 'leader':
                value = rec[3] * 1.50
                result['leader'] += value
                result['blocking'] += value
                return result
            else:
                result['blocking'] += rec[3]
                return result
        return result

# -----------------------------------------------------------------------------
# Pipe/connectivity helpers (mature layout function names retained internally)
# NOTE: internal dictionary keys/variable names such as 'duct' are intentionally retained.
# They represent the tagged linear MEP host and keep the proven Smart V9 layout engine unchanged.
# -----------------------------------------------------------------------------
def is_native_duct(elem):
    """Native Revit Pipe host. Internal function name is retained from the duct engine to minimize layout regressions."""
    try:
        return (elem is not None and elem.Category is not None and
                eid_int(elem.Category.Id) == bic_int(DB.BuiltInCategory.OST_PipeCurves))
    except Exception:
        return False


def is_fabrication_duct_part(elem):
    try:
        return (isinstance(elem, DB.FabricationPart) and
                elem.Category is not None and
                eid_int(elem.Category.Id) == bic_int(DB.BuiltInCategory.OST_FabricationPipework))
    except Exception:
        return False


def _fabrication_connector_profile(conn):
    """Return a conservative (shape, dimensions) connector profile signature."""
    try:
        shape = str(conn.Shape).lower()
    except Exception:
        shape = 'unknown'
    dims = ()
    if 'round' in shape:
        try:
            dims = (float(conn.Radius) * 2.0,)
        except Exception:
            pass
    elif 'rect' in shape or 'oval' in shape:
        try:
            dims = tuple(sorted((float(conn.Width), float(conn.Height))))
        except Exception:
            pass
    return shape, dims


def _fabrication_connector_direction(conn):
    try:
        cs = conn.CoordinateSystem
        if cs is not None:
            return cs.BasisZ.Normalize()
    except Exception:
        pass
    return None


def _looks_like_fabrication_straight(elem):
    """Strict recovery for fabrication straight hosts Revit does not flag cleanly.

    Field testing showed the older recovery was too permissive: any two-port part
    with matching profiles could be promoted to a straight, which could tag a
    fitting/run incorrectly.  This version requires a genuine straight-through
    connector pair:
      * matching connector profile
      * connector axes nearly opposite
      * connector-to-connector line aligned with BOTH axes
      * optional CenterlineLength agrees with that line

    Extra physical connectors are allowed.  This is important for a real straight
    that carries a cut-in/tap connector; only the best straight-through pair is
    treated as the two run ends.
    """
    if not is_fabrication_duct_part(elem):
        return False
    try:
        key = eid_int(elem.Id)
    except Exception:
        key = None
    if key is not None and key in _FAB_STRAIGHT_FALLBACK_CACHE:
        return _FAB_STRAIGHT_FALLBACK_CACHE[key]

    result = False
    best = None
    best_dist = -1.0
    try:
        try:
            if bool(elem.IsAHanger()) or bool(elem.IsATap()):
                raise ValueError('not straight')
        except AttributeError:
            pass

        words = []
        for attr in ('ProductName', 'ProductShortDescription', 'ProductLongDescription', 'Alias', 'Name'):
            try:
                val = getattr(elem, attr)
                if val:
                    words.append(str(val).lower())
            except Exception:
                pass
        desc = ' '.join(words)
        bad = ('elbow', 'transition', 'reducer', 'increaser', 'tee', 'wye',
               'tap', 'shoe', 'coupling', 'union', 'flange', 'damper', 'cap',
               'offset', 'boot', 'bend')
        if any(x in desc for x in bad):
            raise ValueError('fitting description')

        conns = physical_connectors(elem)
        if len(conns) < 2:
            raise ValueError('not enough connectors')

        for i in range(len(conns)):
            for j in range(i + 1, len(conns)):
                c0 = conns[i]
                c1 = conns[j]
                try:
                    p0 = c0.Origin
                    p1 = c1.Origin
                    delta = p1 - p0
                    dist = delta.GetLength()
                    if dist <= 1e-4:
                        continue
                    line_dir = delta.Normalize()
                except Exception:
                    continue

                sig0 = _fabrication_connector_profile(c0)
                sig1 = _fabrication_connector_profile(c1)
                if sig0[0] != sig1[0] or len(sig0[1]) != len(sig1[1]):
                    continue
                profile_ok = True
                for a, b in zip(sig0[1], sig1[1]):
                    if abs(a - b) > SIZE_TOL_FT:
                        profile_ok = False
                        break
                if not profile_ok:
                    continue

                d0 = _fabrication_connector_direction(c0)
                d1 = _fabrication_connector_direction(c1)
                # Recovery is intentionally strict. If the connector coordinate
                # systems are unavailable, leave the part classified by Revit.
                if d0 is None or d1 is None:
                    continue
                if d0.DotProduct(d1) > -0.96:
                    continue
                # A true straight runs on the connector axes. This rejects an
                # offset with parallel/opposite ends whose origins are displaced.
                if abs(d0.DotProduct(line_dir)) < 0.965:
                    continue
                if abs(d1.DotProduct(line_dir)) < 0.965:
                    continue

                if dist > best_dist:
                    best_dist = dist
                    best = (c0, c1, p0, p1)

        if best is None:
            raise ValueError('no straight-through connector pair')

        # When available, CenterlineLength is a useful extra guard against a
        # visually linear fitting whose path bends between its end connectors.
        try:
            cl = float(elem.CenterlineLength)
            if cl > 1e-6 and abs(cl - best_dist) / max(cl, best_dist) > 0.12:
                raise ValueError('centerline disagrees with chord')
        except AttributeError:
            pass
        except TypeError:
            pass

        c0, c1, p0, p1 = best
        result = True
        if key is not None:
            try:
                _FAB_RECOVERY_LINE_CACHE[key] = DB.Line.CreateBound(p0, p1)
                _FAB_RECOVERY_MAIN_CONNECTORS[key] = [c0, c1]
            except Exception:
                pass
    except Exception:
        result = False

    if key is not None:
        _FAB_STRAIGHT_FALLBACK_CACHE[key] = result
        if result:
            _FAB_STRAIGHT_FALLBACK_IDS.add(key)
    return result


def _is_coupling_like_fabrication_part(elem):
    if not is_fabrication_duct_part(elem):
        return False
    words = []
    for attr in ('ProductName', 'ProductShortDescription', 'ProductLongDescription', 'Alias', 'Name'):
        try:
            val = getattr(elem, attr)
            if val:
                words.append(str(val).lower())
        except Exception:
            pass
    desc = ' '.join(words)
    return ('coupling' in desc) or ('coupler' in desc) or ('union' in desc)


def is_fabrication_straight(elem):
    if not is_fabrication_duct_part(elem):
        return False
    # BOP is a straight-pipe annotation. Some fabrication databases report
    # coupling/union items as straight-like; never promote those fitting hosts.
    if _is_coupling_like_fabrication_part(elem):
        return False
    try:
        if bool(elem.IsAStraight()):
            return True
    except Exception:
        pass
    try:
        legacy = getattr(elem, 'IsStraightSegment', None)
        if legacy is not None and bool(legacy()):
            return True
    except Exception:
        pass
    return _looks_like_fabrication_straight(elem)


def is_duct(elem):
    """A straight duct element that may legitimately become a tag target."""
    return is_native_duct(elem) or is_fabrication_straight(elem)


def _line_from_connector_origins(elem):
    """Create a centerline from the farthest pair of physical connector origins."""
    pts = []
    for c in physical_connectors(elem):
        try:
            pts.append(c.Origin)
        except Exception:
            pass
    if len(pts) < 2:
        return None
    best = None
    best_d = -1.0
    for i in range(len(pts)):
        for j in range(i + 1, len(pts)):
            try:
                d = pts[i].DistanceTo(pts[j])
                if d > best_d:
                    best_d = d
                    best = (pts[i], pts[j])
            except Exception:
                pass
    if best is None or best_d <= 1e-9:
        return None
    try:
        return DB.Line.CreateBound(best[0], best[1])
    except Exception:
        return None


def duct_line(duct):
    did = eid_int(duct.Id)
    if did in _DUCT_LINE_CACHE:
        return _DUCT_LINE_CACHE[did]
    line = None
    if is_native_duct(duct):
        try:
            curve = duct.Location.Curve
            if isinstance(curve, DB.Line):
                line = curve
        except Exception:
            pass
    elif is_fabrication_straight(duct):
        line = _FAB_RECOVERY_LINE_CACHE.get(did)
        if line is None:
            line = _line_from_connector_origins(duct)
    _DUCT_LINE_CACHE[did] = line
    return line


def duct_direction(duct):
    did = eid_int(duct.Id)
    if did in _DUCT_DIRECTION_CACHE:
        return _DUCT_DIRECTION_CACHE[did]
    line = duct_line(duct)
    direction = None
    if line is not None:
        try:
            direction = (line.GetEndPoint(1) - line.GetEndPoint(0)).Normalize()
        except Exception:
            pass
    _DUCT_DIRECTION_CACHE[did] = direction
    return direction


def is_horizontal_straight_duct(duct):
    did = eid_int(duct.Id)
    if did in _HORIZONTAL_DUCT_CACHE:
        return _HORIZONTAL_DUCT_CACHE[did]
    if not is_duct(duct):
        _HORIZONTAL_DUCT_CACHE[did] = False
        return False
    direction = duct_direction(duct)
    result = direction is not None and abs(direction.Z) <= HORIZONTAL_SLOPE_TOL
    _HORIZONTAL_DUCT_CACHE[did] = result
    return result


def get_connectors(elem):
    try:
        key = eid_int(elem.Id)
    except Exception:
        key = None
    if key is not None and key in _CONNECTOR_CACHE:
        return _CONNECTOR_CACHE[key]

    result = []
    try:
        cm = elem.ConnectorManager
        for c in cm.Connectors:
            result.append(c)
    except Exception:
        try:
            mep = elem.MEPModel
            if mep is not None and mep.ConnectorManager is not None:
                for c in mep.ConnectorManager.Connectors:
                    result.append(c)
        except Exception:
            pass
    if key is not None:
        _CONNECTOR_CACHE[key] = result
    return result


def is_physical_connector_type(connector_type):
    try:
        return connector_type in (
            DB.ConnectorType.End,
            DB.ConnectorType.Curve,
            DB.ConnectorType.Physical,
        )
    except Exception:
        return False


def physical_connectors(elem):
    try:
        key = eid_int(elem.Id)
    except Exception:
        key = None
    if key is not None and key in _PHYSICAL_CONNECTOR_CACHE:
        return _PHYSICAL_CONNECTOR_CACHE[key]
    result = []
    for c in get_connectors(elem):
        try:
            if is_physical_connector_type(c.ConnectorType):
                result.append(c)
        except Exception:
            pass
    if key is not None:
        _PHYSICAL_CONNECTOR_CACHE[key] = result
    return result


def physical_connected_connectors(elem):
    result = []
    for c in physical_connectors(elem):
        try:
            if c.IsConnected:
                result.append(c)
        except Exception:
            pass
    return result


def is_duct_fitting(elem):
    """Native pipe fitting OR non-straight fabrication pipework part."""
    try:
        if elem is None or elem.Category is None:
            return False
        if eid_int(elem.Category.Id) == bic_int(DB.BuiltInCategory.OST_PipeFitting):
            return True
    except Exception:
        pass
    if is_fabrication_duct_part(elem):
        return not is_fabrication_straight(elem)
    return False


def fitting_part_type(elem):
    """Return Revit PartType for a native mechanical fitting when available."""
    if is_fabrication_duct_part(elem):
        return None
    try:
        mep = elem.MEPModel
        if mep is not None:
            return mep.PartType
    except Exception:
        pass
    return None


def is_endcap_duct_fitting(elem):
    """True for a pipe cap/end-cap fitting."""
    try:
        key = eid_int(elem.Id)
    except Exception:
        key = None
    if key is not None and key in _ENDCAP_FITTING_CACHE:
        return _ENDCAP_FITTING_CACHE[key]

    result = False
    if is_duct_fitting(elem):
        part_type = fitting_part_type(elem)
        if part_type is not None:
            try:
                result = part_type == DB.PartType.Cap
            except Exception:
                pass
            if not result:
                try:
                    result = part_type == DB.PartType.EndCap
                except Exception:
                    pass
        if not result:
            # Fabrication end caps and many custom native caps are reliably
            # distinguishable as one-port duct fittings/parts.
            try:
                result = len(physical_connectors(elem)) == 1
            except Exception:
                result = False
    if key is not None:
        _ENDCAP_FITTING_CACHE[key] = result
    return result


def duct_end_has_endcap(conn):
    """Check whether this pipe connector is physically connected to an end cap."""
    for ref_conn in connector_refs(conn):
        try:
            if is_endcap_duct_fitting(ref_conn.Owner):
                return True
        except Exception:
            pass
    return False


def is_pass_through_duct_fitting(elem):
    try:
        key = eid_int(elem.Id)
    except Exception:
        key = None
    if key is not None and key in _PASS_THROUGH_FITTING_CACHE:
        return _PASS_THROUGH_FITTING_CACHE[key]
    result = False
    if is_duct_fitting(elem) and not is_endcap_duct_fitting(elem):
        # Count ALL physical ports, not only the connected ones. A tee with an
        # unconnected/capped branch must still remain a branch and must not be
        # mistaken for a two-port elbow/transition.
        result = len(physical_connectors(elem)) == 2
    if key is not None:
        _PASS_THROUGH_FITTING_CACHE[key] = result
    return result


def connector_refs(conn):
    refs = []
    try:
        for r in conn.AllRefs:
            try:
                if r.Owner is None:
                    continue
                # AllRefs can include logical/reference connections. Restrict the
                # network walk to physical MEP connections only.
                if not is_physical_connector_type(r.ConnectorType):
                    continue
                refs.append(r)
            except Exception:
                pass
    except Exception:
        pass
    return refs


def walk_from_duct_end(start_duct, start_conn):
    """Return nearest horizontal/sloped pipe reached through 2-port fittings/non-horizontal pipe.

    Returns list of tuples: (terminal_pipe, terminal_connector_origin, path_had_nonhorizontal)
    Usually there is exactly one result because tees/crosses are excluded.
    """
    start_id = eid_int(start_duct.Id)
    queue = deque()
    results = []

    for r in connector_refs(start_conn):
        try:
            owner = r.Owner
            oid = eid_int(owner.Id)
            if oid == start_id:
                continue
            queue.append((owner, r, 1, set([start_id]), False))
        except Exception:
            pass

    while queue:
        owner, entered_ref, hops, visited, had_nonhorizontal = queue.popleft()
        if hops > MAX_NETWORK_HOPS:
            continue
        oid = eid_int(owner.Id)
        if oid in visited:
            continue
        visited2 = set(visited)
        visited2.add(oid)

        if is_duct(owner):
            if is_horizontal_straight_duct(owner):
                try:
                    terminal_origin = entered_ref.Origin
                except Exception:
                    line = duct_line(owner)
                    terminal_origin = line.Evaluate(0.5, True) if line else None
                if terminal_origin is not None:
                    results.append((owner, terminal_origin, had_nonhorizontal))
                continue
            # This is the vertical/steep transition portion. Traverse through it,
            # but never make it a tag target.
            next_had_nonhorizontal = True
        elif is_pass_through_duct_fitting(owner):
            next_had_nonhorizontal = had_nonhorizontal
        else:
            # Stop at accessories, equipment, terminals, tees, crosses, end caps, etc.
            continue

        for c in physical_connected_connectors(owner):
            for r2 in connector_refs(c):
                try:
                    o2 = r2.Owner
                    o2id = eid_int(o2.Id)
                    if o2id in visited2:
                        continue
                    queue.append((o2, r2, hops + 1, visited2, next_had_nonhorizontal))
                except Exception:
                    pass

    return results


def first_end_connectors(duct):
    try:
        did = eid_int(duct.Id)
        recovered = _FAB_RECOVERY_MAIN_CONNECTORS.get(did)
        if recovered:
            return list(recovered)
    except Exception:
        pass
    conns = []
    fallback = []
    for c in get_connectors(duct):
        try:
            if c.ConnectorType == DB.ConnectorType.End:
                conns.append(c)
            elif is_physical_connector_type(c.ConnectorType):
                fallback.append(c)
        except Exception:
            fallback.append(c)
    return conns if conns else fallback


def duct_shape_and_size(duct):
    """Return (shape, dimensions_tuple) using connector geometry when possible."""
    did = eid_int(duct.Id)
    cached = _DUCT_SIZE_CACHE.get(did)
    if cached is not None:
        return cached
    shape = 'Unknown'
    dims = ()
    conns = first_end_connectors(duct)
    if conns:
        c = conns[0]
        try:
            shape = str(c.Shape)
        except Exception:
            pass
        low = shape.lower()
        if 'round' in low:
            try:
                dims = (float(c.Radius) * 2.0,)
            except Exception:
                pass
        elif 'rect' in low or 'oval' in low:
            try:
                dims = (float(c.Width), float(c.Height))
            except Exception:
                pass

    if dims:
        result = (shape, dims)
        _DUCT_SIZE_CACHE[did] = result
        return result

    # Parameter fallbacks for native Revit Pipe.
    def pval(bip):
        try:
            p = duct.get_Parameter(bip)
            if p is not None and p.HasValue:
                return p.AsDouble()
        except Exception:
            pass
        return None

    dia = pval(DB.BuiltInParameter.RBS_CURVE_DIAMETER_PARAM)
    if dia is not None and dia > 1e-8:
        result = ('Round', (dia,))
        _DUCT_SIZE_CACHE[did] = result
        return result
    w = pval(DB.BuiltInParameter.RBS_CURVE_WIDTH_PARAM)
    h = pval(DB.BuiltInParameter.RBS_CURVE_HEIGHT_PARAM)
    if w is not None and h is not None:
        result = ('Rectangular', (w, h))
        _DUCT_SIZE_CACHE[did] = result
        return result
    result = (shape, dims)
    _DUCT_SIZE_CACHE[did] = result
    return result


def size_or_shape_changed(a, b):
    sa, da = duct_shape_and_size(a)
    sb, db = duct_shape_and_size(b)
    sa_low = sa.lower()
    sb_low = sb.lower()
    if sa_low != sb_low:
        return (True, True)   # changed, shape_changed
    if len(da) != len(db):
        return (True, False)
    if not da and not db:
        return (False, False)

    # Rectangular/oval connectors can report Width/Height swapped when the
    # profile is rolled. 12x8 and 8x12 are the same physical size, so compare
    # the unordered pair and avoid a false size-change tag on a simple roll.
    da_cmp = da
    db_cmp = db
    if len(da) == 2 and ('rect' in sa_low or 'oval' in sa_low):
        da_cmp = tuple(sorted(da))
        db_cmp = tuple(sorted(db))

    for x, y in zip(da_cmp, db_cmp):
        if abs(x - y) > SIZE_TOL_FT:
            return (True, False)
    return (False, False)


def centerline_elevation(duct):
    did = eid_int(duct.Id)
    if did in _CENTER_ELEV_CACHE:
        return _CENTER_ELEV_CACHE[did]
    line = duct_line(duct)
    result = 0.0
    if line is not None:
        p0 = line.GetEndPoint(0)
        p1 = line.GetEndPoint(1)
        result = 0.5 * (p0.Z + p1.Z)
    _CENTER_ELEV_CACHE[did] = result
    return result


def pipe_event_elevation_changed(a, b, a_origin=None, b_origin=None, path_had_nonhorizontal=False):
    """Detect a real offset/drop without flagging ordinary continuous pipe slope.

    For plumbing, centerline mid-elevations are a poor comparison because two
    adjacent sloped pipe segments naturally have different midpoints. Prefer the
    connector/event elevations on the two sides of the fitting/offset path.
    """
    try:
        if a_origin is not None and b_origin is not None:
            return abs(float(a_origin.Z) - float(b_origin.Z)) > ELEVATION_TOL_FT
    except Exception:
        pass
    # Only use midpoint fallback when topology already tells us a non-horizontal
    # transition was traversed. This keeps a normal sloped sanitary run quiet.
    if path_had_nonhorizontal:
        try:
            return abs(centerline_elevation(a) - centerline_elevation(b)) > ELEVATION_TOL_FT
        except Exception:
            pass
    return False


def horizontal_axis_uv(duct):
    did = eid_int(duct.Id)
    if did in _AXIS_UV_CACHE:
        return _AXIS_UV_CACHE[did]
    line = duct_line(duct)
    result = None
    if line is not None:
        p0 = uv_of_point(line.GetEndPoint(0))
        p1 = uv_of_point(line.GetEndPoint(1))
        result = normalize2d(p1[0] - p0[0], p1[1] - p0[1])
    _AXIS_UV_CACHE[did] = result
    return result


def direction_away_from_event_uv(duct, event_point):
    line = duct_line(duct)
    if line is None or event_point is None:
        return None
    p0 = line.GetEndPoint(0)
    p1 = line.GetEndPoint(1)
    far = p1 if event_point.DistanceTo(p0) <= event_point.DistanceTo(p1) else p0
    a = uv_of_point(event_point)
    b = uv_of_point(far)
    return normalize2d(b[0] - a[0], b[1] - a[1])


def is_horizontal_turn(a, b, a_event=None, b_event=None):
    # Use vectors pointing away from the connection. This distinguishes a true
    # 180-degree U-turn from a straight colinear continuation, which simple
    # undirected pipe axes cannot do.
    va = direction_away_from_event_uv(a, a_event)
    vb = direction_away_from_event_uv(b, b_event)
    if va is not None and vb is not None:
        # Straight continuation has va == -vb, so compare va with -vb.
        dot = va[0] * (-vb[0]) + va[1] * (-vb[1])
        dot = max(-1.0, min(1.0, dot))
        angle = math.degrees(math.acos(dot))
        return angle > TURN_ANGLE_TOL_DEG

    # Fallback when connector origins are unavailable. U-turn distinction is not
    # possible here, but ordinary elbows are still detected correctly.
    va = horizontal_axis_uv(a)
    vb = horizontal_axis_uv(b)
    if va is None or vb is None:
        return False
    dot = abs(va[0] * vb[0] + va[1] * vb[1])
    dot = max(-1.0, min(1.0, dot))
    angle = math.degrees(math.acos(dot))
    return angle > TURN_ANGLE_TOL_DEG


def plan_half_width(duct):
    did = eid_int(duct.Id)
    if did in _PLAN_HALF_WIDTH_CACHE:
        return _PLAN_HALF_WIDTH_CACHE[did]
    shape, dims = duct_shape_and_size(duct)
    if dims:
        if len(dims) == 1:
            result = max(0.05, dims[0] * 0.5)
        else:
            # For pipe the single connector dimension is diameter; rectangular fallback is retained generically.
            result = max(0.05, dims[0] * 0.5)
    else:
        result = paper_to_model(0.05)
    _PLAN_HALF_WIDTH_CACHE[did] = result
    return result


def visible_fabrication_duct_count():
    count = 0
    try:
        parts = (DB.FilteredElementCollector(doc, view.Id)
                 .OfClass(DB.FabricationPart)
                 .WhereElementIsNotElementType())
        for part in parts:
            if is_fabrication_duct_part(part):
                count += 1
    except Exception:
        pass
    return count


def sample_tag_mode(tag):
    """Return 'native' or 'fabrication' from the selected placed tag."""
    try:
        for eid in tagged_local_ids(tag):
            host = doc.GetElement(eid)
            if is_native_duct(host):
                return 'native'
            if is_fabrication_duct_part(host):
                return 'fabrication'
    except Exception:
        pass
    try:
        if tag.Category is not None:
            cid = eid_int(tag.Category.Id)
            if cid == bic_int(DB.BuiltInCategory.OST_PipeTags):
                return 'native'
            if cid == bic_int(DB.BuiltInCategory.OST_FabricationPipeworkTags):
                return 'fabrication'
    except Exception:
        pass
    return None


def collect_mode_ductwork(mode):
    """Return visible pipework elements for the tag category chosen by the user."""
    if mode == 'fabrication':
        result = []
        try:
            parts = (DB.FilteredElementCollector(doc, view.Id)
                     .OfClass(DB.FabricationPart)
                     .WhereElementIsNotElementType())
            for part in parts:
                if is_fabrication_duct_part(part):
                    result.append(part)
        except Exception:
            pass
        return result
    return list(DB.FilteredElementCollector(doc, view.Id)
                .OfCategory(DB.BuiltInCategory.OST_PipeCurves)
                .WhereElementIsNotElementType())


# -----------------------------------------------------------------------------
# Target detection
# -----------------------------------------------------------------------------
def add_target(targets, duct, event_point, reasons):
    """Add one horizontal duct target for one or more event reasons."""
    did = eid_int(duct.Id)
    if did not in targets:
        targets[did] = {'duct': duct, 'event_points': [], 'reasons': set()}

    if event_point is not None:
        duplicate_point = False
        for existing in targets[did]['event_points']:
            try:
                if existing.DistanceTo(event_point) <= 1e-6:
                    duplicate_point = True
                    break
            except Exception:
                pass
        if not duplicate_point:
            targets[did]['event_points'].append(event_point)

    if isinstance(reasons, (list, tuple, set)):
        for reason in reasons:
            targets[did]['reasons'].add(reason)
    else:
        targets[did]['reasons'].add(reasons)


def _turn_density_can_collapse(a, b):
    """Return True when a turn-only event carries the same annotation state.

    Normal drainage slope is intentionally kept strict: on sloped runs the BOP
    value changes along the pipe even when the event is not an elevation offset.
    """
    if not SMART_HUMAN_TURN_DENSITY:
        return False
    try:
        da = duct_direction(a)
        db = duct_direction(b)
        if da is None or db is None:
            return False
        if abs(float(da.Z)) > 0.006 or abs(float(db.Z)) > 0.006:
            return False
    except Exception:
        return False
    # Equal world heights can have different level-relative BOP labels.
    # Unknown datums are not proof that two annotations communicate the same value.
    level_a = _pipe_reference_level_key(a)
    level_b = _pipe_reference_level_key(b)
    if level_a is None or level_a != level_b:
        return False
    # reasons == turn-only already proves size/shape and event elevation did not
    # change. Keep service identity equal as an additional drafting safeguard.
    try:
        sa = _layout_service_key(a)
        sb = _layout_service_key(b)
        if sa is not None and sb is not None and sa != sb:
            return False
    except Exception:
        pass
    return True


def _preferred_turn_tag_side(a, b, targets):
    """Pick the more useful straight for a redundant turn-only pair."""
    aid = eid_int(a.Id); bid = eid_int(b.Id)
    if aid in targets and bid not in targets:
        return a
    if bid in targets and aid not in targets:
        return b
    # At the first elbow after a tee/takeoff, keep the actual branch-start
    # straight as the one BOP callout.  The branch audit then does not add a
    # second identical tag on the short leg.
    try:
        abr = _straight_is_direct_branch_leg(a)
        bbr = _straight_is_direct_branch_leg(b)
        if abr != bbr:
            return a if abr else b
    except Exception:
        pass
    try:
        la = float(duct_line(a).Length)
    except Exception:
        la = 0.0
    try:
        lb = float(duct_line(b).Length)
    except Exception:
        lb = 0.0
    if abs(la - lb) > 1e-6:
        return a if la > lb else b
    return a if aid <= bid else b


def _branch_fitting_text(elem):
    words = []
    for attr in ('ProductName', 'ProductShortDescription', 'ProductLongDescription', 'Alias', 'Name'):
        try:
            val = getattr(elem, attr)
            if val:
                words.append(str(val).lower())
        except Exception:
            pass
    return ' '.join(words)


def _is_branch_fitting(elem):
    """Local branch identity only; never a network walk."""
    if elem is None or not is_duct_fitting(elem) or is_endcap_duct_fitting(elem):
        return False
    try:
        if bool(elem.IsATap()):
            return True
    except Exception:
        pass
    try:
        if len(physical_connectors(elem)) >= 3:
            return True
    except Exception:
        pass
    text = _branch_fitting_text(elem)
    return any(x in text for x in ('tee', 'wye', 'takeoff', 'take-off', 'tap', 'branch', 'saddle', 'shoe'))


def _connector_plan_axis(conn):
    try:
        cs = conn.CoordinateSystem
        if cs is None:
            return None
        d = cs.BasisZ.Normalize()
        n = (float(d.X) * float(d.X) + float(d.Y) * float(d.Y)) ** 0.5
        if n <= 1e-7:
            return None
        return (float(d.X) / n, float(d.Y) / n)
    except Exception:
        return None


def _fitting_connector_is_branch(fitting, ref_conn):
    """Return True only for the non-main port of a tee/wye/tap fitting."""
    try:
        if bool(fitting.IsATap()):
            return True
    except Exception:
        pass
    conns = list(physical_connectors(fitting))
    if len(conns) < 3:
        text = _branch_fitting_text(fitting)
        return any(x in text for x in ('takeoff', 'take-off', 'tap', 'branch', 'saddle', 'shoe'))
    idx = None
    try:
        rp = ref_conn.Origin
        best = None
        for i, c in enumerate(conns):
            d = c.Origin.DistanceTo(rp)
            if best is None or d < best:
                best = d; idx = i
    except Exception:
        idx = None
    if idx is None:
        return False
    axes = [_connector_plan_axis(c) for c in conns]
    best_pair = None; best_dot = -1.0
    for i in range(len(conns)):
        if axes[i] is None:
            continue
        for j in range(i + 1, len(conns)):
            if axes[j] is None:
                continue
            dot = abs(axes[i][0] * axes[j][0] + axes[i][1] * axes[j][1])
            if dot > best_dot:
                best_dot = dot; best_pair = (i, j)
    if best_pair is None or best_dot < 0.88:
        return False
    return idx not in best_pair


def _straight_is_direct_branch_leg(straight):
    for sc in first_end_connectors(straight):
        for ref in connector_refs(sc):
            try:
                fitting = ref.Owner
            except Exception:
                continue
            if _is_branch_fitting(fitting) and _fitting_connector_is_branch(fitting, ref):
                return True
    return False


def _is_plumbing_fixture(elem):
    try:
        return (elem is not None and elem.Category is not None and
                eid_int(elem.Category.Id) == bic_int(DB.BuiltInCategory.OST_PlumbingFixtures))
    except Exception:
        return False


def _fixture_reachable_from_end_connector(start_conn, straight_id, max_fitting_hops):
    """Local-only fixture test used for bathroom-tail suppression.

    Walk through compact pass-through fittings only. Never walk into another
    straight pipe and never cross a tee/wye/takeoff, so a distribution main is
    not accidentally classified as a fixture tail.
    """
    queue = deque()
    seen = set([int(straight_id)])
    for ref in connector_refs(start_conn):
        try:
            owner = ref.Owner
            oid = eid_int(owner.Id)
            if oid != straight_id:
                queue.append((owner, 0))
        except Exception:
            pass

    while queue:
        owner, hops = queue.popleft()
        try:
            oid = eid_int(owner.Id)
        except Exception:
            continue
        if oid in seen:
            continue
        seen.add(oid)

        if _is_plumbing_fixture(owner):
            return True

        if is_duct(owner):
            continue
        if hops >= max_fitting_hops:
            continue
        if _is_branch_fitting(owner):
            continue
        if not is_duct_fitting(owner):
            continue

        for oc in physical_connected_connectors(owner):
            for ref2 in connector_refs(oc):
                try:
                    nxt = ref2.Owner
                    nid = eid_int(nxt.Id)
                    if nid in seen:
                        continue
                    queue.append((nxt, hops + 1))
                except Exception:
                    pass
    return False


def _straight_is_local_fixture_tail(straight):
    if not SMART_SUPPRESS_FIXTURE_TAIL_BOP:
        return False
    try:
        line = duct_line(straight)
        if line is None or float(line.Length) > FIXTURE_TAIL_MAX_LENGTH_FT:
            return False
        sid = eid_int(straight.Id)
    except Exception:
        return False
    for sc in first_end_connectors(straight):
        if _fixture_reachable_from_end_connector(
                sc, sid, int(FIXTURE_TAIL_MAX_FITTING_HOPS)):
            return True
    return False


def suppress_fixture_tail_bop_targets(targets):
    """Remove redundant terminal BOP targets at local plumbing fixtures.

    This runs after all normal detection/audits, so coverage logic stays intact
    and only the final human-density target set is reduced.
    """
    removed = 0
    for did in list(targets.keys()):
        try:
            target = targets.get(did)
            straight = target.get('duct') if target else None
            # A short fixture tail can carry a changed size/elevation/endcap.
            # Those values are visible in the human reference and must survive;
            # only unchanged routing-only callouts are redundant.
            if (straight is not None and _human_soft_turn_target(target) and
                    _straight_is_local_fixture_tail(straight)):
                del targets[did]
                removed += 1
        except Exception:
            pass
    return removed


def _human_soft_turn_target(target):
    try:
        reasons = set(target.get('reasons', set()))
    except Exception:
        return False
    if not reasons:
        return False
    # These reasons communicate routing/topology, not a changed annotation value.
    # Information-changing events stay strict and are never consolidated here.
    return reasons.issubset(set(['turn', 'branch']))


def _pipe_reference_level_key(straight):
    """Conservative level-datum identity for equivalent BOP routing events."""
    levels = set()
    for attr in ('LevelId', 'ReferenceLevel'):
        try:
            value = getattr(straight, attr)
            level_id = eid_int(value.Id if attr == 'ReferenceLevel' else value)
            if level_id >= 0:
                levels.add(level_id)
        except Exception as ex:
            if _is_fatal_revit_error(ex):
                raise
    for name in ('RBS_START_LEVEL_PARAM', 'INSTANCE_REFERENCE_LEVEL_PARAM',
                 'FABRICATION_LEVEL_PARAM'):
        try:
            parameter = straight.get_Parameter(getattr(DB.BuiltInParameter, name))
            if parameter is not None:
                level_id = eid_int(parameter.AsElementId())
                if level_id >= 0:
                    levels.add(level_id)
        except Exception as ex:
            if _is_fatal_revit_error(ex):
                raise
    return tuple(sorted(levels)) if levels else None


def _human_turn_state_key(straight):
    """Stable annotation state for conservative local BOP consolidation."""
    try:
        d = duct_direction(straight)
        if d is None or abs(float(d.Z)) > 0.006:
            # Sloped runs carry changing BOP values; never collapse them.
            return None
    except Exception:
        return None
    try:
        shape, dims = duct_shape_and_size(straight)
        dims_key = tuple(round(float(x), 5) for x in (dims or ()))
    except Exception:
        return None
    if not dims_key or str(shape).lower() == 'unknown':
        return None
    try:
        elev = round(float(centerline_elevation(straight)) * 192.0) / 192.0
    except Exception:
        return None
    try:
        service = _layout_service_key(straight)
    except Exception:
        return None
    if service is None:
        return None
    level_key = _pipe_reference_level_key(straight)
    if level_key is None:
        return None
    return (str(service), str(shape).lower(), dims_key, elev, level_key)


def _human_target_midpoint(straight):
    try:
        line = duct_line(straight)
        if line is not None:
            return line.Evaluate(0.5, True)
    except Exception:
        pass
    return None


def _human_turn_keep_rank(target):
    """Lower is better: keep branch-start/longer straights as the one callout."""
    straight = target.get('duct')
    branch_penalty = 1
    try:
        branch_penalty = 0 if _straight_is_direct_branch_leg(straight) else 1
    except Exception:
        pass
    length = 0.0
    try:
        line = duct_line(straight)
        length = float(line.Length) if line is not None else 0.0
    except Exception:
        pass
    try:
        did = eid_int(straight.Id)
    except Exception:
        did = 2147483647
    return (branch_penalty, -length, did)


def suppress_redundant_human_turn_targets(targets):
    """Collapse repeated local turn/branch-only BOP callouts.

    The graph walks only through the existing two-port pass-through traversal
    used by event detection. Tee/wye/takeoff fittings terminate the walk, so
    separate branches remain separate drafting obligations. Elevation/size/
    shape/endcap targets are never touched.
    """
    if not SMART_HUMAN_LOCAL_TURN_CONSOLIDATION:
        return 0

    soft = {}
    state = {}
    midpoint = {}
    for did, target in list(targets.items()):
        if not _human_soft_turn_target(target):
            continue
        straight = target.get('duct')
        key = _human_turn_state_key(straight)
        if key is None:
            continue
        soft[int(did)] = target
        state[int(did)] = key
        midpoint[int(did)] = _human_target_midpoint(straight)

    if len(soft) < 2:
        return 0

    graph = dict((did, set()) for did in soft.keys())
    for did, target in list(soft.items()):
        straight = target.get('duct')
        for sc in first_end_connectors(straight):
            try:
                neighbors = walk_from_duct_end(straight, sc)
            except Exception:
                neighbors = []
            for other, _origin, had_nonhorizontal in neighbors:
                if had_nonhorizontal:
                    continue
                oid = eid_int(other.Id)
                if oid == did or oid not in soft:
                    continue
                if state.get(oid) != state.get(did):
                    continue
                pa = midpoint.get(did); pb = midpoint.get(oid)
                if pa is None or pb is None:
                    continue
                try:
                    if pa.DistanceTo(pb) > HUMAN_LOCAL_TURN_MAX_SPAN_FT:
                        continue
                except Exception:
                    continue
                graph[did].add(oid)
                graph[oid].add(did)

    removed = 0
    unseen = set(graph.keys())
    while unseen:
        keeper = min(unseen, key=lambda x: _human_turn_keep_rank(soft[x]))
        # Pairwise-local links must not collapse a whole floor by transitivity.
        # Bound the connected path from this actual keeper, then leave remote
        # targets for the next group and its own readable callout.
        distances = {keeper: 0.0}
        pending = [(0.0, keeper)]
        comp = []
        while pending:
            pending.sort(reverse=True)
            distance, cur = pending.pop()
            if cur not in unseen or distance > distances.get(cur, float('inf')):
                continue
            unseen.remove(cur)
            comp.append(cur)
            for nxt in graph.get(cur, set()):
                if nxt not in unseen:
                    continue
                try:
                    step = midpoint[cur].DistanceTo(midpoint[nxt])
                except Exception:
                    continue
                new_distance = distance + step
                if (new_distance <= HUMAN_LOCAL_TURN_MAX_SPAN_FT and
                        new_distance < distances.get(nxt, float('inf'))):
                    distances[nxt] = new_distance
                    pending.append((new_distance, nxt))
        if len(comp) < 2:
            continue
        for did in comp:
            if did == keeper:
                continue
            # Preserve event-point history on the keeper for placement anchoring.
            try:
                keep_t = targets.get(keeper)
                rem_t = targets.get(did)
                for pt in rem_t.get('event_points', []):
                    duplicate = False
                    for existing in keep_t.get('event_points', []):
                        try:
                            if existing.DistanceTo(pt) <= 1e-6:
                                duplicate = True
                                break
                        except Exception:
                            pass
                    if not duplicate:
                        keep_t['event_points'].append(pt)
                keep_t['reasons'].update(rem_t.get('reasons', set()))
            except Exception:
                pass
            if did in targets:
                del targets[did]
                removed += 1
    return removed


def audit_branch_start_bop(horizontal_ducts, targets):
    """Guarantee one BOP tag on the actual straight branch leaving a tee/takeoff.

    The fitting only identifies the drafting event; the straight pipe owns the
    tag. Main-run tee ports are ignored, couplings/two-port fittings are ignored,
    and an already-targeted branch straight is never duplicated.
    """
    if 'turn' not in AUTOTAG_ENABLED_REASONS:
        return 0
    added = 0
    for straight in horizontal_ducts:
        sid = eid_int(straight.Id)
        if sid in targets:
            continue
        found = False
        for sc in first_end_connectors(straight):
            try:
                origin = sc.Origin
            except Exception:
                origin = None
            for ref in connector_refs(sc):
                try:
                    fitting = ref.Owner
                except Exception:
                    continue
                if not _is_branch_fitting(fitting):
                    continue
                if not _fitting_connector_is_branch(fitting, ref):
                    continue
                add_target(targets, straight, origin, 'branch')
                added += 1
                found = True
                break
            if found:
                break
    return added


def detect_targets(horizontal_ducts):
    """Find every horizontal/sloped straight pipe piece that must receive a tag.

    For each qualifying transition between two horizontal ducts, BOTH sides are
    added as targets. The network walker may traverse elbows, transitions, and
    vertical/steep pipe, but vertical/steep pipe is never itself a target.

    The last horizontal/sloped straight pipe piece attached to a physical end-cap
    fitting is also a target. The end-cap fitting itself is never tagged.
    """
    targets = {}
    seen_pairs = set()
    seen_capped_ends = set()
    visible_ids = set(eid_int(d.Id) for d in horizontal_ducts)
    event_counts = {
        'turn': 0,
        'elevation': 0,
        'size': 0,
        'shape': 0,
        'endcap': 0,
        'turn_condensed': 0,
    }

    for a in horizontal_ducts:
        aid = eid_int(a.Id)
        for a_conn in first_end_connectors(a):
            try:
                a_origin = a_conn.Origin
                is_connected = bool(a_conn.IsConnected)
            except Exception:
                continue

            # Capped-end event: tag ONLY the straight horizontal duct attached
            # to the end cap. The end-cap fitting itself is never a tag target.
            if 'endcap' in AUTOTAG_ENABLED_REASONS and is_connected and duct_end_has_endcap(a_conn):
                end_key = (
                    aid,
                    round(float(a_origin.X), 6),
                    round(float(a_origin.Y), 6),
                    round(float(a_origin.Z), 6),
                )
                if end_key not in seen_capped_ends:
                    seen_capped_ends.add(end_key)
                    event_counts['endcap'] += 1
                    add_target(targets, a, a_origin, 'endcap')

            if not is_connected:
                continue

            # Find the nearest horizontal/sloped straight pipe on the other side of the
            # fitting/offset path. This is what guarantees the before/after pair.
            for b, b_origin, path_had_nonhorizontal in walk_from_duct_end(a, a_conn):
                bid = eid_int(b.Id)
                if aid == bid:
                    continue
                key = (min(aid, bid), max(aid, bid))
                if key in seen_pairs:
                    continue
                seen_pairs.add(key)

                reasons = []

                # Left/right (plan) direction change.
                if is_horizontal_turn(a, b, a_origin, b_origin):
                    reasons.append('turn')

                # Elevation offset/drop. Plumbing uses the actual event-connector
                # elevations so ordinary sanitary slope does not create false
                # elevation-change tags. A vertical/steep transition may be traversed.
                if pipe_event_elevation_changed(a, b, a_origin, b_origin, path_had_nonhorizontal):
                    reasons.append('elevation')
                elif path_had_nonhorizontal:
                    # A sloped detour that returns to the same elevation is not a
                    # net elevation change, so no elevation reason is added.
                    pass

                # Size and shape are independent event types. Shape changes take
                # precedence over size in the summary so rect->round is not double
                # counted, while both adjacent straight pipes are still tagged.
                size_changed, shape_changed = size_or_shape_changed(a, b)
                if shape_changed:
                    reasons.append('shape')
                elif size_changed:
                    reasons.append('size')

                reasons = [r for r in reasons if r in AUTOTAG_ENABLED_REASONS]
                if not reasons:
                    continue

                for reason in reasons:
                    event_counts[reason] += 1

                # Human drafting density: if this event ONLY changes direction and
                # both runs are level/same-service, one tag communicates the same
                # BOP/size information. Keep the longer/already-required side.
                # Information-changing events (elevation/size/shape) remain strict
                # two-sided coverage.
                if reasons == ['turn'] and _turn_density_can_collapse(a, b):
                    if aid in visible_ids and bid not in visible_ids:
                        preferred = a
                    elif bid in visible_ids and aid not in visible_ids:
                        preferred = b
                    else:
                        preferred = _preferred_turn_tag_side(a, b, targets)
                    pid = eid_int(preferred.Id)
                    if pid in visible_ids:
                        p_origin = a_origin if pid == aid else b_origin
                        add_target(targets, preferred, p_origin, reasons)
                    event_counts['turn_condensed'] += 1
                    continue

                # Strict two-sided rule for every information-changing event. If one
                # side lies outside the active view it is still used for detection
                # but is not tagged in this view.
                if aid in visible_ids:
                    add_target(targets, a, a_origin, reasons)
                if bid in visible_ids:
                    add_target(targets, b, b_origin, reasons)

    return targets, event_counts


def audit_direct_two_port_events(horizontal_ducts, targets):
    """Conservative topology safety audit for fabrication/native straight pipe.

    This does NOT traverse tees/crosses and therefore does not invent branch
    tags. It only rechecks a straight pipe directly through a two-port fitting. In
    normal topology detect_targets already finds these; this audit catches odd
    fabrication connector/ref cases that can otherwise leave one obvious straight
    untagged. Returns the number of newly added target ducts.
    """
    visible = dict((eid_int(d.Id), d) for d in horizontal_ducts)
    before = set(targets.keys())
    for a in horizontal_ducts:
        aid = eid_int(a.Id)
        if aid in targets:
            continue
        for a_conn in first_end_connectors(a):
            try:
                a_origin = a_conn.Origin
            except Exception:
                continue
            for ref_conn in connector_refs(a_conn):
                try:
                    fitting = ref_conn.Owner
                except Exception:
                    continue
                if not is_pass_through_duct_fitting(fitting):
                    continue
                for fc in physical_connected_connectors(fitting):
                    for out_ref in connector_refs(fc):
                        try:
                            b = out_ref.Owner
                            bid = eid_int(b.Id)
                        except Exception:
                            continue
                        if bid == aid or bid not in visible:
                            continue
                        if not is_horizontal_straight_duct(b):
                            continue
                        try:
                            b_origin = out_ref.Origin
                        except Exception:
                            b_origin = None
                        reasons = []
                        if is_horizontal_turn(a, b, a_origin, b_origin):
                            reasons.append('turn')
                        if pipe_event_elevation_changed(a, b, a_origin, b_origin, False):
                            reasons.append('elevation')
                        size_changed, shape_changed = size_or_shape_changed(a, b)
                        if shape_changed:
                            reasons.append('shape')
                        elif size_changed:
                            reasons.append('size')
                        reasons = [r for r in reasons if r in AUTOTAG_ENABLED_REASONS]
                        if reasons:
                            # Keep the human-density rule in the conservative direct
                            # two-port safety audit too.  Older builds condensed a
                            # turn-only pair in detect_targets(), then this audit
                            # silently added BOTH sides back and effectively doubled
                            # many unchanged BOP callouts.  Information-changing
                            # events remain strict two-sided coverage.
                            if reasons == ['turn'] and _turn_density_can_collapse(a, b):
                                preferred = _preferred_turn_tag_side(a, b, targets)
                                pid = eid_int(preferred.Id)
                                p_origin = a_origin if pid == aid else b_origin
                                add_target(targets, preferred, p_origin, reasons)
                            else:
                                add_target(targets, a, a_origin, reasons)
                                add_target(targets, b, b_origin, reasons)
                            break
                    if aid in targets:
                        break
                if aid in targets:
                    break
            if aid in targets:
                break
    return len(set(targets.keys()) - before)


def target_anchor(target):
    # choose_layout() and final tag creation both need the same point. Store it
    # on the per-run target record so it is calculated only once.
    if '_anchor' in target:
        return target['_anchor']
    duct = target['duct']
    line = duct_line(duct)
    if line is None:
        target['_anchor'] = None
        return None
    p0 = line.GetEndPoint(0)
    p1 = line.GetEndPoint(1)
    length = line.Length
    pts = target['event_points']
    if not pts:
        result = line.Evaluate(0.5, True)
        target['_anchor'] = result
        return result

    # If this duct is immediately adjacent to changes at BOTH ends, one centered
    # tag is cleaner than duplicate tags on the same straight piece.
    near0 = False
    near1 = False
    for ep in pts:
        if ep.DistanceTo(p0) <= ep.DistanceTo(p1):
            near0 = True
        else:
            near1 = True
    if near0 and near1:
        result = line.Evaluate(0.5, True)
        target['_anchor'] = result
        return result

    ep = pts[0]
    from_p0 = ep.DistanceTo(p0) <= ep.DistanceTo(p1)
    desired = min(length * 0.42, paper_to_model(ANCHOR_FROM_CHANGE_PAPER_IN))
    desired = max(min(length * 0.42, desired), min(length * 0.18, paper_to_model(0.08)))
    if length < 1e-6:
        result = line.Evaluate(0.5, True)
    else:
        t = desired / length
        result = line.Evaluate(t if from_p0 else 1.0 - t, True)
    target['_anchor'] = result
    return result


# -----------------------------------------------------------------------------
# Existing tag discovery / sample tag selection
# -----------------------------------------------------------------------------
def tagged_local_ids(tag):
    ids = []
    try:
        for eid in tag.GetTaggedLocalElementIds():
            ids.append(eid)
        return ids
    except Exception:
        pass
    try:
        for r in tag.GetTaggedReferences():
            ids.append(r.ElementId)
        return ids
    except Exception:
        pass
    try:
        eid = tag.TaggedLocalElementId
        if eid is not None and eid != DB.ElementId.InvalidElementId:
            ids.append(eid)
    except Exception:
        pass
    return ids


def _is_fatal_revit_error(error):
    """A failed regeneration forbids further reads/writes until rollback."""
    names = [type(error).__name__]
    try:
        names.append(str(error.GetType().Name))
    except Exception:
        pass
    return any(name in ('RegenerationFailedException',
                        'ModificationForbiddenException') for name in names)


def _tag_identity_check(tag, tag_type_id, source_id=None, require_text=True):
    """Prove a real local tag of the selected type references the intended pipe.

    This verifies source/type association and readable content, not the numeric
    correctness of the family label or the plotted placement.
    """
    if tag is None:
        return False, 'missing-tag', []
    try:
        if not tag.IsValidObject:
            return False, 'invalid-tag', []
        if not isinstance(tag, DB.IndependentTag):
            return False, 'wrong-element-class', []
        if eid_int(tag.OwnerViewId) != eid_int(view.Id):
            return False, 'wrong-view', []
        if eid_int(tag.GetTypeId()) != eid_int(tag_type_id):
            return False, 'wrong-tag-type', []
        if tag.IsOrphaned:
            return False, 'orphaned-tag', []
        ids = sorted(set(eid_int(eid) for eid in tagged_local_ids(tag)
                         if eid_int(eid) >= 0))
        if not ids:
            return False, 'no-local-source', []
        if source_id is not None and int(source_id) not in ids:
            return False, 'wrong-source', ids
        if require_text:
            text = str(tag.TagText or '').strip()
            if not text or text == '?':
                return False, 'empty-or-unresolved-tag-text', ids
        return True, None, ids
    except Exception as ex:
        if _is_fatal_revit_error(ex):
            raise
        return False, 'unreadable-tag-identity', []


def _surviving_tag_records(records, tag_type_id):
    surviving = []
    rejected = []
    for record in records:
        source_id = eid_int(record['target']['duct'].Id)
        tag = doc.GetElement(DB.ElementId(System.Int64(record['tag_id'])))
        valid, reason, _ids = _tag_identity_check(tag, tag_type_id, source_id)
        if valid:
            # Cleanup and Revit commit may alter leader visibility; report the
            # actual state rather than the planned flag.
            record['leader_applied'] = bool(tag.HasLeader)
            if not record['leader_applied']:
                record['leader_mode'] = None
            record['actual_text'] = str(tag.TagText)
            try:
                record['head'] = tag.TagHeadPosition
            except Exception:
                pass
            surviving.append(record)
        else:
            rejected.append((source_id, reason, int(record['tag_id'])))
    return surviving, rejected


def _verify_created_tag_head_clearance(records, grid, crop_rect):
    """Measure real family text with temporary heads on-host and leaders hidden.

    One regeneration in a rolled-back subtransaction yields conservative family
    bounding boxes with compact heads and hidden leaders. Shift them to placed
    heads, including rotated families, before accepting the final batch. Revit
    bounding boxes may include nonvisible family geometry; these are not glyph
    bounds or proof of association-line behavior in every tag family.
    """
    if not records:
        return [], []
    measured = {}
    errors = {}
    temporary = {}
    st = DB.SubTransaction(doc)
    st.Start()
    try:
        for record in records:
            tag_id = record['tag_id']
            try:
                tag = doc.GetElement(DB.ElementId(System.Int64(tag_id)))
                if tag is None:
                    raise RuntimeError('Tag missing before final head measurement.')
                actual_head = tag.TagHeadPosition
                anchor = record.get('anchor')
                if anchor is None:
                    anchor = target_anchor(record['target'])
                tag.HasLeader = False
                if tag.HasLeader:
                    raise RuntimeError('Tag family cannot expose leader-free text extents.')
                tag.TagHeadPosition = anchor
                temporary[tag_id] = (tag, actual_head)
            except Exception as ex:
                if _is_fatal_revit_error(ex):
                    raise
                errors[tag_id] = str(ex)
        if temporary:
            doc.Regenerate()
        for tag_id, (tag, actual_head) in temporary.items():
            r = element_rect(tag)
            if r is None:
                errors[tag_id] = 'Actual tag family bounding box is unavailable.'
                continue
            origin = uv_of_point(tag.TagHeadPosition)
            destination = uv_of_point(actual_head)
            du, dv = destination[0] - origin[0], destination[1] - origin[1]
            measured[tag_id] = rect_expand((r[0] + du, r[1] + dv,
                                           r[2] + du, r[3] + dv),
                                          paper_to_model(TAG_CLEARANCE_PAPER_IN))
    finally:
        st.RollBack()

    for record in records:
        grid.remove_source(record['tag_id'])
    for record in records:
        if record['tag_id'] in measured:
            record['rect'] = measured[record['tag_id']]
        _reserve_record_geometry(grid, record)
    surviving = []
    rejected = []
    for record in reversed(records):
        tag_id = record['tag_id']
        grid.remove_source(tag_id)
        source_id = eid_int(record['target']['duct'].Id)
        reason = errors.get(tag_id)
        if reason is None:
            ignore = source_id if not record.get('leader_applied') else None
            hard, cad = grid.score_rect_components(record['rect'], ignore_source_id=ignore)
            if crop_rect is not None and not rect_contains_rect(crop_rect, record['rect']):
                reason = 'Actual tag head extends outside the crop.'
            elif hard > 0.0 or cad >= CAD_EXTREME_BLOCK_THRESHOLD * 1.8:
                reason = 'Actual tag family head overlaps protected geometry.'
        if reason is not None:
            doc.Delete(DB.ElementId(System.Int64(tag_id)))
            rejected.append((source_id, reason))
        else:
            record['head_clearance_verified'] = True
            surviving.append(record)
            _reserve_record_geometry(grid, record)
    surviving.reverse()
    return surviving, rejected


def _sample_tag_looks_valid(tag):
    """Accept native pipe tags and MEP Fabrication pipework tags."""
    return sample_tag_mode(tag) in ('native', 'fabrication')


def get_sample_tag():
    selected = []
    for eid in uidoc.Selection.GetElementIds():
        elem = doc.GetElement(eid)
        if isinstance(elem, DB.IndependentTag):
            selected.append(elem)
    if len(selected) == 1:
        if _sample_tag_looks_valid(selected[0]):
            return selected[0]
        forms.alert('The selected tag is not a native pipe tag or MEP Fabrication pipework tag.\n\nSelect one already-placed pipe/fabrication pipework tag and run again.', title='AutoTag Plumbing')
        return None
    try:
        # Deliberately avoid a custom ISelectionFilter here. Plain PickObject is
        # reliable under both pyRevit IronPython and CPython/pythonnet engines;
        # we validate the picked element immediately afterward.
        ref = uidoc.Selection.PickObject(
            UI.Selection.ObjectType.Element,
            'Pick ONE already-placed duct tag to use as the tag family/type.'
        )
        tag = doc.GetElement(ref.ElementId)
        if tag is not None and _sample_tag_looks_valid(tag):
            return tag
        forms.alert('That tag is not a native pipe tag or MEP Fabrication pipework tag.\n\nPick an already-placed pipe/fabrication pipework tag and run again.', title='AutoTag Plumbing')
        return None
    except Exception:
        return None


# -----------------------------------------------------------------------------
# CAD scan + obstacle building
# -----------------------------------------------------------------------------
def _graphics_style_info(obj, cache):
    """Return (visible, layer_name) for CAD geometry with one cached lookup."""
    try:
        sid = obj.GraphicsStyleId
        key = eid_int(sid)
        if key < 0:
            return (True, '')
        if key in cache:
            return cache[key]
        gs = doc.GetElement(sid)
        if gs is None or gs.GraphicsStyleCategory is None:
            info = (True, '')
            cache[key] = info
            return info
        try:
            visible = not view.GetCategoryHidden(gs.GraphicsStyleCategory.Id)
        except Exception:
            visible = True
        try:
            name = str(gs.GraphicsStyleCategory.Name or '')
        except Exception:
            name = ''
        info = (visible, name)
        cache[key] = info
        return info
    except Exception:
        return (True, '')


def _cad_segment_weight(layer_name, paper_len):
    """Weight meaningful architectural linework strongly, hatch noise lightly."""
    name = (layer_name or '').lower()
    hatch_words = ('hatch', 'patt', 'pattern', 'fill', 'poche', 'poch', 'solid', 'tile', 'insul')
    major_words = ('wall', 'door', 'window', 'wind', 'glaz', 'partition', 'shaft',
                   'column', 'colu', 'case', 'mill', 'stair', 'beam', 'struct',
                   'curb', 'plumb', 'arch')
    if any(w in name for w in hatch_words):
        return W_CAD_HATCH
    if any(w in name for w in major_words):
        return W_CAD_MAJOR
    if paper_len >= 1.00:
        return W_CAD_MEDIUM
    if paper_len >= 0.45:
        return W_CAD
    if paper_len >= 0.18:
        return 24.0
    if paper_len >= 0.06:
        return 3.0
    return 0.25


def add_curve_segments_from_points(points, grid, source_id, counter, scan_rect, min_seg_len, layer_name):
    if len(points) < 2:
        return
    for i in range(len(points) - 1):
        if counter[0] >= MAX_CAD_SEGMENTS:
            return
        a = uv_of_point(points[i])
        b = uv_of_point(points[i + 1])
        if dist2d_uv(a, b) < min_seg_len:
            continue
        seg_rect = (min(a[0], b[0]), min(a[1], b[1]),
                    max(a[0], b[0]), max(a[1], b[1]))
        if scan_rect is not None and not rect_intersects(seg_rect, scan_rect):
            continue
        # Layer-aware CAD weighting: hatch/tessellation remains cheap, while
        # wall/door/partition linework strongly discourages placing tag text on
        # top of architectural background geometry.
        paper_len = dist2d_uv(a, b) / max(_PAPER_TO_MODEL_FACTOR, 1e-9)
        cad_weight = _cad_segment_weight(layer_name, paper_len)
        grid.add_segment('cad', a, b, cad_weight, source_id)
        counter[0] += 1


def scan_geometry_element(geo, grid, source_id, counter, scan_rect, min_seg_len, style_cache):
    if geo is None or counter[0] >= MAX_CAD_SEGMENTS:
        return
    for obj in geo:
        if counter[0] >= MAX_CAD_SEGMENTS:
            return
        try:
            if isinstance(obj, DB.GeometryInstance):
                # GetInstanceGeometry returns geometry in the owning model's
                # coordinates, which is what our view-space projection expects.
                scan_geometry_element(
                    obj.GetInstanceGeometry(), grid, source_id, counter,
                    scan_rect, min_seg_len, style_cache
                )
            elif isinstance(obj, DB.PolyLine):
                visible, layer_name = _graphics_style_info(obj, style_cache)
                if not visible:
                    continue
                pts = list(obj.GetCoordinates())
                add_curve_segments_from_points(
                    pts, grid, source_id, counter, scan_rect, min_seg_len, layer_name
                )
            elif isinstance(obj, DB.Curve):
                visible, layer_name = _graphics_style_info(obj, style_cache)
                if not visible:
                    continue
                pts = list(obj.Tessellate())
                add_curve_segments_from_points(
                    pts, grid, source_id, counter, scan_rect, min_seg_len, layer_name
                )
        except Exception:
            # A malformed CAD entity should not stop the complete scan.
            pass


def scan_visible_dwgs(grid, scan_rect):
    counter = [0]
    import_count = 0
    failed_count = 0
    style_cache = {}
    min_seg_len = paper_to_model(0.005)
    opts = DB.Options()
    try:
        opts.View = view
    except Exception:
        pass
    opts.IncludeNonVisibleObjects = False
    opts.ComputeReferences = False

    imports = (DB.FilteredElementCollector(doc, view.Id)
               .OfClass(DB.ImportInstance)
               .WhereElementIsNotElementType())
    for imp in imports:
        if counter[0] >= MAX_CAD_SEGMENTS:
            break
        try:
            if imp.IsHidden(view):
                continue
        except Exception:
            pass
        imp_rect = element_rect(imp)
        if scan_rect is not None and imp_rect is not None and not rect_intersects(imp_rect, scan_rect):
            continue
        import_count += 1
        try:
            geo = imp.get_Geometry(opts)
            if geo is None:
                failed_count += 1
                continue
            scan_geometry_element(
                geo, grid, eid_int(imp.Id), counter,
                scan_rect, min_seg_len, style_cache
            )
        except Exception:
            # Do not turn the whole DWG bounding box into an obstacle. A failed
            # parse should degrade collision avoidance, not make every tag collide.
            failed_count += 1
    return import_count, counter[0], counter[0] >= MAX_CAD_SEGMENTS, failed_count


def build_obstacle_grid(ducts, target_ducts=None):
    cell = max(paper_to_model(0.70), 0.5)
    grid = SpatialGrid(cell)
    duct_rects = []
    duct_rect_by_id = {}

    # Visible pipe bodies. Keep the bbox locally so target-region construction
    # does not ask Revit for the same duct bounding box a second time.
    for d in ducts:
        r = element_rect(d)
        if r is not None:
            did = eid_int(d.Id)
            duct_rects.append(r)
            duct_rect_by_id[did] = r
            grid.add_rect('duct', rect_expand(r, paper_to_model(0.012)), W_DUCT, did)

    # Nearby MEP model geometry that tag heads should not sit on top of.
    # Keep this list intentionally small/cheap; the background DWG scan handles
    # most architectural linework and the native pipe bodies are indexed above.
    obstacle_categories = [
        ('fitting', 'OST_PipeFitting'),
        ('accessory', 'OST_PipeAccessory'),
        ('flexpipe', 'OST_FlexPipeCurves'),
        ('fixture', 'OST_PlumbingFixtures'),
        ('plumbing_equipment', 'OST_PlumbingEquipment'),
        ('equipment', 'OST_MechanicalEquipment'),
    ]
    for kind, bic_name in obstacle_categories:
        try:
            bic = getattr(DB.BuiltInCategory, bic_name)
            elems = (DB.FilteredElementCollector(doc, view.Id)
                     .OfCategory(bic)
                     .WhereElementIsNotElementType())
            for elem in elems:
                r = element_rect(elem)
                if r is not None:
                    grid.add_rect(kind, rect_expand(r, paper_to_model(0.015)), W_FITTING, eid_int(elem.Id))
        except Exception:
            # Category availability can vary by Revit release/template.
            pass

    # Existing view-owned annotation.  Only REAL annotation content is a hard
    # blocker.  Treating every view-specific element as hard (detail lines, filled
    # regions, drafting hatch, etc.) makes a dense plan look falsely "full" and
    # drives leaders across the sheet.  Humans routinely place tags over hatch,
    # but avoid text, dimensions and other tags.
    try:
        annotation_collector = (DB.FilteredElementCollector(doc)
                                .OwnedByView(view.Id)
                                .WhereElementIsNotElementType())
        for e in annotation_collector:
            try:
                if isinstance(e, DB.ImportInstance):
                    continue
                kind = None
                weight = None
                if isinstance(e, DB.IndependentTag):
                    kind = 'tag'
                    weight = W_TAG
                elif isinstance(e, DB.TextNote) or isinstance(e, DB.Dimension):
                    kind = 'annotation'
                    weight = W_ANNOTATION
                else:
                    # Room/space/area tags and generic annotation families are
                    # also meaningful text/graphics that should remain readable.
                    try:
                        if isinstance(e, DB.SpatialElementTag):
                            kind = 'annotation'
                            weight = W_ANNOTATION
                    except Exception:
                        pass
                    if kind is None:
                        try:
                            cid = eid_int(e.Category.Id) if e.Category is not None else None
                            generic_id = bic_int(DB.BuiltInCategory.OST_GenericAnnotation)
                            if cid == generic_id:
                                kind = 'annotation'
                                weight = W_ANNOTATION
                        except Exception:
                            pass
                if kind is None:
                    continue
                r = element_rect(e)
                if r is None:
                    continue
                pad = 0.025 if kind == 'tag' else 0.015
                grid.add_rect(kind, rect_expand(r, paper_to_model(pad)), weight, eid_int(e.Id))
            except Exception:
                pass
    except Exception:
        pass

    # Limit CAD parsing to the region where tags can actually be placed. Using
    # target pipe extents is much faster than indexing an entire floor DWG.
    scan_source = []
    if target_ducts:
        for d in target_ducts:
            did = eid_int(d.Id)
            r = duct_rect_by_id.get(did)
            if r is None:
                r = element_rect(d)
            if r is not None:
                scan_source.append(r)
    if not scan_source:
        scan_source = duct_rects
    scan_rect = rect_union(scan_source)
    if scan_rect is not None:
        scan_rect = rect_expand(scan_rect, paper_to_model(CAD_SCAN_MARGIN_PAPER_IN))
    crop = crop_rect_for_view(view)
    if crop is not None:
        crop = rect_expand(crop, paper_to_model(0.10))
        if scan_rect is not None:
            clipped = rect_intersection(scan_rect, crop)
            if clipped is None:
                return grid, (0, 0, False, 0)
            scan_rect = clipped
        else:
            scan_rect = crop

    dwg_info = scan_visible_dwgs(grid, scan_rect)
    return grid, dwg_info


# -----------------------------------------------------------------------------
# Tag creation / layout
# -----------------------------------------------------------------------------
def create_raw_tag(duct, point, tag_type_id, orientation, add_leader=False):
    ref = DB.Reference(duct)
    last_error = None
    tag = None
    try:
        tag = DB.IndependentTag.Create(
            doc, tag_type_id, view.Id, ref, add_leader, orientation, point
        )
        valid, reason, _ids = _tag_identity_check(
            tag, tag_type_id, eid_int(duct.Id), require_text=False)
        if not valid:
            raise RuntimeError('Created tag identity rejected: ' + str(reason))
        return tag, ref
    except Exception as ex:
        if _is_fatal_revit_error(ex):
            raise
        if tag is not None:
            doc.Delete(tag.Id)
        last_error = ex

    modes = [DB.TagMode.TM_ADDBY_CATEGORY]
    try:
        modes.append(DB.TagMode.TM_ADDBY_MULTICATEGORY)
    except Exception:
        pass
    for mode in modes:
        tag = None
        try:
            tag = DB.IndependentTag.Create(
                doc, view.Id, ref, add_leader, mode, orientation, point
            )
            if tag.GetTypeId() != tag_type_id:
                replacement_id = tag.ChangeTypeId(tag_type_id)
                if (replacement_id is not None and
                        replacement_id != DB.ElementId.InvalidElementId):
                    tag = doc.GetElement(replacement_id)
            valid, reason, _ids = _tag_identity_check(
                tag, tag_type_id, eid_int(duct.Id), require_text=False)
            if not valid:
                raise RuntimeError('Created tag identity rejected: ' + str(reason))
            return tag, ref
        except Exception as ex:
            if _is_fatal_revit_error(ex):
                raise
            # Failed type assignment used to leave a stray wrong-family tag.
            # Remove it before trying the next supported creation overload.
            if tag is not None:
                doc.Delete(tag.Id)
            last_error = ex
    if last_error is not None:
        raise last_error
    raise RuntimeError('Revit did not return a usable tag creation error.')

def _tag_measure_key(duct):
    did = eid_int(duct.Id)
    cached = _TAG_MEASURE_KEY_CACHE.get(did)
    if cached is not None:
        return cached
    shape, dims = duct_shape_and_size(duct)
    rounded_dims = tuple(round(float(x), 5) for x in dims)
    system_id = -1
    system_type = -1
    try:
        if duct.MEPSystem is not None:
            system_id = eid_int(duct.MEPSystem.Id)
            system_type = eid_int(duct.MEPSystem.GetTypeId())
    except Exception:
        pass
    if is_fabrication_duct_part(duct):
        try:
            system_id = int(duct.ServiceId)
        except Exception:
            pass
        try:
            system_type = int(duct.ServiceType)
        except Exception:
            pass
    elev = round(float(centerline_elevation(duct)), 4)
    # Rotate-with-component families change their visible extents by host axis.
    # Sloped labels can also display different values even at equal midpoint
    # elevation. Never reuse horizontal metrics for a vertical/angled plan run.
    axis = horizontal_axis_uv(duct)
    axis_key = tuple(round(float(x), 4) for x in axis) if axis else None
    direction = duct_direction(duct)
    slope_key = round(float(direction.Z), 5) if direction is not None else None
    line = duct_line(duct)
    endpoint_z_key = (tuple(round(float(line.GetEndPoint(index).Z), 4) for index in (0, 1))
                      if line is not None else None)
    result = (shape.lower(), rounded_dims, system_id, system_type, elev,
              axis_key, slope_key, endpoint_z_key)
    _TAG_MEASURE_KEY_CACHE[did] = result
    return result

def _fallback_tag_metrics(sample_tag=None):
    """Return visible tag extents from TagHeadPosition: (L, R, B, T).

    TagHeadPosition is the family insertion point, not guaranteed to be the
    visual center.  Treating width/height as symmetric is what allowed elbows
    to land inside some tag families and made leaders appear to leave the middle
    of the text.  Measure the real asymmetric extents instead.
    """
    left = paper_to_model(0.30)
    right = paper_to_model(0.30)
    bottom = paper_to_model(0.09)
    top = paper_to_model(0.09)
    if sample_tag is not None:
        use_sample_bbox = True
        try:
            use_sample_bbox = not bool(sample_tag.HasLeader)
        except Exception:
            pass
        if use_sample_bbox:
            r = element_rect(sample_tag)
            try:
                huv = uv_of_point(sample_tag.TagHeadPosition)
            except Exception:
                huv = None
            if r is not None and huv is not None:
                safety = paper_to_model(TAG_SIZE_SAFETY_PAPER_IN)
                left = max(huv[0] - r[0] + safety, paper_to_model(0.04))
                right = max(r[2] - huv[0] + safety, paper_to_model(0.04))
                bottom = max(huv[1] - r[1] + safety, paper_to_model(0.035))
                top = max(r[3] - huv[1] + safety, paper_to_model(0.035))
    return (left, right, bottom, top)


def build_tag_size_cache(targets, tag_type_id, orientation, sample_rotation, sample_tag=None):
    """Measure representative visible tag extents with one regeneration."""
    cache = {}
    reps = {}
    for target in targets:
        duct = target['duct']
        key = _tag_measure_key(duct)
        if key not in reps:
            reps[key] = duct

    fallback = _fallback_tag_metrics(sample_tag)
    if not reps:
        return cache, fallback

    st = DB.SubTransaction(doc)
    st.Start()
    made = {}
    try:
        for key, duct in reps.items():
            try:
                line = duct_line(duct)
                if line is None:
                    continue
                p = line.Evaluate(0.5, True)
                # Put the temporary head on the host so Revit's invisible
                # host-association line has essentially zero length.
                tag, _ = create_raw_tag(duct, p, tag_type_id, orientation, False)
                try:
                    tag.HasLeader = False
                except Exception:
                    pass
                try:
                    tag.TagHeadPosition = p
                except Exception:
                    pass
                if sample_rotation is not None:
                    try:
                        tag.RotationAngle = sample_rotation
                    except Exception:
                        pass
                made[key] = tag
            except Exception as ex:
                if _is_fatal_revit_error(ex):
                    raise

        if made:
            doc.Regenerate()
        safety = paper_to_model(TAG_SIZE_SAFETY_PAPER_IN)
        for key in reps:
            tag = made.get(key)
            if tag is None:
                cache[key] = fallback
                continue
            r = element_rect(tag)
            try:
                huv = uv_of_point(tag.TagHeadPosition)
            except Exception:
                huv = None
            if r is None or huv is None:
                cache[key] = fallback
                continue
            left = max(huv[0] - r[0] + safety, paper_to_model(0.04))
            right = max(r[2] - huv[0] + safety, paper_to_model(0.04))
            bottom = max(huv[1] - r[1] + safety, paper_to_model(0.035))
            top = max(r[3] - huv[1] + safety, paper_to_model(0.035))
            # Measured family text can be wider/taller than a default family.
            # Clamping real extents would create a knowingly undersized blocker.
            cache[key] = (left, right, bottom, top)
    finally:
        try:
            st.RollBack()
        except Exception:
            pass
    return cache, fallback


def get_tag_metrics_cached(cache, fallback, duct):
    return cache.get(_tag_measure_key(duct), fallback)


def tag_metrics_size(metrics):
    return (metrics[0] + metrics[1], metrics[2] + metrics[3])


def tag_support_extent(metrics, direction_uv):
    """Distance from insertion point to visible tag edge in a view direction."""
    du, dv = direction_uv
    left, right, bottom, top = metrics
    return ((right if du >= 0.0 else left) * abs(du) +
            (top if dv >= 0.0 else bottom) * abs(dv))


def candidate_rect(head, metrics):
    u, v = uv_of_point(head)
    left, right, bottom, top = metrics
    pad = paper_to_model(TAG_CLEARANCE_PAPER_IN)
    return (u - left - pad,
            v - bottom - pad,
            u + right + pad,
            v + top + pad)


def duct_axis_and_perp(duct):
    axis = horizontal_axis_uv(duct)
    if axis is None:
        return None, None
    perp = (-axis[1], axis[0])
    return axis, perp


def score_head_rect(grid, r, crop_rect):
    hard, cad = grid.score_rect_components(r)
    if crop_rect is not None and not rect_contains_rect(crop_rect, r):
        hard += W_OUTSIDE_CROP
    return hard, cad


def _line_projection_param(duct, point_uv):
    line = duct_line(duct)
    if line is None or line.Length < 1e-9:
        return None
    p0 = uv_of_point(line.GetEndPoint(0))
    p1 = uv_of_point(line.GetEndPoint(1))
    du = p1[0] - p0[0]
    dv = p1[1] - p0[1]
    den = du * du + dv * dv
    if den < 1e-12:
        return None
    return ((point_uv[0] - p0[0]) * du + (point_uv[1] - p0[1]) * dv) / den


def _clamped_host_param(duct, t):
    line = duct_line(duct)
    if line is None or line.Length < 1e-9:
        return 0.5
    margin = paper_to_model(0.10) / max(line.Length, 1e-9)
    margin = min(0.22, max(0.08, margin))
    lo = margin
    hi = 1.0 - margin
    return max(lo, min(hi, t))


def _host_anchor_from_elbow(duct, elbow, along_run_paper, sign):
    """Project elbow to host, then offset along host for a clean diagonal leg."""
    line = duct_line(duct)
    if line is None or line.Length < 1e-9:
        return None
    euv = uv_of_point(elbow)
    t = _line_projection_param(duct, euv)
    if t is None:
        return None
    t += sign * paper_to_model(along_run_paper) / max(line.Length, 1e-9)
    t = _clamped_host_param(duct, t)
    try:
        return line.Evaluate(t, True)
    except Exception:
        return None


def _leader_angle_penalty(elbow_uv, anchor_uv):
    du = abs(anchor_uv[0] - elbow_uv[0])
    dv = abs(anchor_uv[1] - elbow_uv[1])
    if du < 1e-9 and dv < 1e-9:
        return 9999.0
    angle = math.degrees(math.atan2(dv, du))
    return abs(angle - HUMAN_ANGLE_TARGET_DEG) * HUMAN_ANGLE_PENALTY_PER_DEG


def leader_length_paper(a, b):
    factor = max(_PAPER_TO_MODEL_FACTOR, 1e-9)
    return dist2d_uv(a, b) / factor


def host_layout_points(target):
    """Return human-style points along the tagged straight duct.

    Event detection decides *which* straight piece gets tagged. Placement is then
    based on the host piece itself: center first, then quarter-ish points. This is
    the same separation used by mature annotation tools and avoids pulling every
    tag toward the fitting that triggered it.
    """
    cached = target.get('_layout_points')
    if cached is not None:
        return cached
    line = duct_line(target['duct'])
    if line is None or line.Length < 1e-8:
        target['_layout_points'] = []
        return []
    params = [0.50, 0.36, 0.64, 0.24, 0.76, 0.16, 0.84]
    pts = []
    for t in params:
        try:
            pts.append(line.Evaluate(t, True))
        except Exception:
            pass
    target['_layout_points'] = pts
    return pts


class LayoutCoordinator(object):
    """Very soft organization memory for dense vertical mains.

    Earlier builds over-constrained columns and created long leaders. This keeps
    only a light preference for nearby tags using the same side while local
    distance/collision quality remains dominant ("relaxed alignment").
    """
    def __init__(self):
        self.entries = []

    def _is_vertical_axis(self, axis):
        if axis is None:
            return False
        return abs(axis[1]) >= (abs(axis[0]) * TRUNK_VERTICAL_RATIO)

    def _nearby(self, anchor_uv):
        across = paper_to_model(TRUNK_NEIGHBOR_ACROSS_PAPER_IN)
        along = paper_to_model(TRUNK_NEIGHBOR_ALONG_PAPER_IN)
        result = []
        for entry in self.entries:
            ea = entry['anchor_uv']
            if abs(ea[0] - anchor_uv[0]) <= across and abs(ea[1] - anchor_uv[1]) <= along:
                result.append(entry)
        return result

    def score_vertical_leader(self, axis, anchor_uv, head_uv, rect):
        if not self._is_vertical_axis(axis):
            return 0.0
        nearby = self._nearby(anchor_uv)
        if not nearby:
            return 0.0
        score = 0.0
        side = 1 if head_uv[0] >= anchor_uv[0] else -1
        vote = sum(entry['side'] for entry in nearby)
        if vote:
            preferred = 1 if vote > 0 else -1
            if side != preferred:
                score += TRUNK_SIDE_CONSISTENCY_PENALTY
        same = [entry for entry in nearby if entry['side'] == side]
        if same:
            expanded = rect_expand(rect, paper_to_model(TRUNK_TAG_GAP_PAPER_IN))
            for entry in same:
                if rect_intersects(expanded, entry['rect']):
                    score += TRUNK_TAG_GAP_PENALTY
        return score

    def register(self, target, head, rect, anchor=None):
        axis = horizontal_axis_uv(target['duct'])
        if not self._is_vertical_axis(axis):
            return
        if anchor is None:
            pts = host_layout_points(target)
            anchor = pts[0] if pts else target_anchor(target)
        if anchor is None:
            return
        auv = uv_of_point(anchor)
        huv = uv_of_point(head)
        self.entries.append({
            'anchor_uv': auv,
            'head_uv': huv,
            'rect': rect,
            'side': 1 if huv[0] >= auv[0] else -1,
        })


def _head_scores(grid, rect, crop_rect, host_id=None):
    hard, cad = grid.score_rect_components(rect, ignore_source_id=host_id)
    if crop_rect is not None and not rect_contains_rect(crop_rect, rect):
        hard += W_OUTSIDE_CROP
    return hard, cad


def _cad_head_is_blocked(cad_score):
    return cad_score >= CAD_HEAD_BLOCK_THRESHOLD


def _host_tag_spans(metrics, axis, perp):
    along = tag_support_extent(metrics, axis) + tag_support_extent(metrics, (-axis[0], -axis[1]))
    across = tag_support_extent(metrics, perp) + tag_support_extent(metrics, (-perp[0], -perp[1]))
    return along, across


def _inline_host_candidate_allowed(duct, metrics, axis, perp):
    """Return True when an on-host tag can remain visually tied to its duct.

    V5 deliberately does NOT require the whole printed label to fit between the
    pipe endpoints. elevation/size tags are often wider than a short piece next to an
    elbow. Association comes from the tag center being on the host centerline;
    actual visible collisions are checked per candidate later.
    """
    line = duct_line(duct)
    if line is None or line.Length < 1e-9:
        _telemetry_reject(duct, 'inline_no_host_line')
        return False
    along, across = _host_tag_spans(metrics, axis, perp)
    host_across = plan_half_width(duct) * 2.0
    host_paper = host_across / max(_PAPER_TO_MODEL_FACTOR, 1e-9)
    ratio_ok = host_across >= (across * INLINE_HOST_FIT_RATIO)
    paper_ok = SMART_V5_ACTIVE and host_paper >= SMART_INLINE_MIN_HOST_PAPER_IN
    if not ratio_ok and not paper_ok:
        _telemetry_reject(duct, 'inline_ineligible')
        return False
    return True

def _edge_geometry(head, metrics, edge_sign, shoulder_model):
    """Estimated visible tag edge + tiny horizontal shoulder.

    Revit clips the leader at the tag graphics. With a FREE leader and an elbow
    just outside the measured tag edge, the visible result is the manual style:
    tiny horizontal shoulder, then one diagonal leg.
    """
    left, right, bottom, top = metrics
    edge_extent = left if edge_sign < 0.0 else right
    attachment = head + RIGHT.Multiply(edge_sign * edge_extent)
    elbow = attachment + RIGHT.Multiply(edge_sign * shoulder_model)
    return attachment, elbow


def _anchor_candidates_from_elbow(duct, elbow):
    """Return local leader anchors by sliding along the tagged straight.

    Human drafters usually keep a good tag head where it is and move the leader
    end along the host to get a cleaner diagonal.  Earlier builds moved the head
    too aggressively and created wild leaders.  Projection is tried first, then
    a compact sweep along the same straight piece, plus the pipe midpoint.
    """
    line = duct_line(duct)
    if line is None or line.Length < 1e-9:
        return []
    euv = uv_of_point(elbow)
    t0 = _line_projection_param(duct, euv)
    if t0 is None:
        return []
    raw = []
    for delta_paper in ANCHOR_SWEEP_PAPER_IN:
        t = t0 + paper_to_model(delta_paper) / max(line.Length, 1e-9)
        raw.append(_clamped_host_param(duct, t))
    # Stable human fallbacks: middle first, then quarter-ish points.
    raw.extend([0.50])
    result = []
    seen = set()
    # Keep the projection-near candidates first; the appended stable points are
    # naturally considered later if local anchors are obstructed.
    for t in raw:
        key = round(float(t), 6)
        if key in seen:
            continue
        seen.add(key)
        try:
            result.append(line.Evaluate(t, True))
        except Exception:
            pass
    return result


def _preferred_edge_sign(head, metrics, anchor):
    """Choose the visible left/right tag edge nearest the leader anchor.

    Revit 2025 does not expose a freely positionable leader start on the tag
    outline.  The most reliable way to make the leader read as coming from an
    end of the tag is to put the elbow just beyond the nearest left/right edge.
    """
    huv = uv_of_point(head)
    auv = uv_of_point(anchor)
    left_u = huv[0] - metrics[0]
    right_u = huv[0] + metrics[1]
    if abs(auv[0] - left_u) <= abs(auv[0] - right_u):
        return -1.0
    return 1.0


def _leader_distance_cost(total_paper):
    value = max(0.0, float(total_paper))
    return (value * LEADER_DISTANCE_LINEAR +
            value * value * LEADER_DISTANCE_QUADRATIC)

def _leader_angle_deg(elbow_uv, anchor_uv):
    du = abs(anchor_uv[0] - elbow_uv[0])
    dv = abs(anchor_uv[1] - elbow_uv[1])
    if du < 1e-9 and dv < 1e-9:
        return 90.0
    return math.degrees(math.atan2(dv, du))


def _smart_length_breakpoint_penalty(total_paper):
    """Convex drafting penalty with V6 emphasis on staying below 0.55 in."""
    if not SMART_V3_ACTIVE:
        return 0.0
    x = max(0.0, float(total_paper))
    p = 0.0
    if x > SMART_LENGTH_BREAK_1:
        p += (x - SMART_LENGTH_BREAK_1) * 420.0
    if x > SMART_LENGTH_BREAK_2:
        p += (x - SMART_LENGTH_BREAK_2) * 6200.0
    if x > 0.55:
        p += (x - 0.55) * 9000.0
    if x > SMART_LENGTH_BREAK_3:
        p += (x - SMART_LENGTH_BREAK_3) * 16000.0
    return p

def _layout_total_paper(layout):
    try:
        if not bool(layout[4]):
            return 0.0
        attachment = layout[6]
        anchor = layout[5]
        elbow = layout[2]
        if attachment is None or anchor is None:
            return 999.0
        a = uv_of_point(attachment)
        z = uv_of_point(anchor)
        if elbow is None:
            return leader_length_paper(a, z)
        e = uv_of_point(elbow)
        return leader_length_paper(a, e) + leader_length_paper(e, z)
    except Exception:
        return 999.0


def _straight_leader_candidate_score(grid, duct, head, rect, metrics, anchor,
                                     base_rank, gap_paper, shift_paper,
                                     crop_rect, coordinator, mep_limit=None,
                                     max_length=None, base_boost=0.0,
                                     telemetry_prefix='normal', head_prefilter=None):
    """Score a true straight leader (no elbow/shoulder).

    head_prefilter=(hard_head, cad_head) lets V5 reuse the rectangle collision
    result for every anchor of the same candidate head.
    """
    host_id = eid_int(duct.Id)
    if head_prefilter is None:
        outside = crop_rect is not None and not rect_contains_rect(crop_rect, rect)
        hard_head, cad_head = grid.score_rect_components(rect, ignore_source_id=None)
        if outside:
            _telemetry_reject(duct, telemetry_prefix + '_head_outside_crop')
            return None
        if hard_head > 0.0:
            _telemetry_reject(duct, telemetry_prefix + '_head_blocked')
            return None
        if cad_head >= CAD_EXTREME_BLOCK_THRESHOLD:
            _telemetry_reject(duct, telemetry_prefix + '_head_cad')
            return None
    else:
        hard_head, cad_head = head_prefilter

    edge_sign = _preferred_edge_sign(head, metrics, anchor)
    edge_extent = metrics[0] if edge_sign < 0.0 else metrics[1]
    attachment = head + RIGHT.Multiply(edge_sign * edge_extent)
    atuv = uv_of_point(attachment)
    auv = uv_of_point(anchor)

    mep_pen = 0.0
    if SMART_V3_ACTIVE and SMART_SOFT_MEP_CROSSINGS:
        detail = grid.score_segment_detail(atuv, auv, ignore_source_id=host_id)
        if detail['blocking'] > 0.0:
            _telemetry_reject(duct, telemetry_prefix + '_leader_blocked')
            return None
        limit = SMART_MEP_CROSS_MAX_SCORE if mep_limit is None else float(mep_limit)
        if detail['mep'] > limit:
            _telemetry_reject(duct, telemetry_prefix + '_mep_cross_limit')
            return None
        cad_line = detail['cad']
        mep_pen = detail['mep'] * SMART_MEP_CROSS_PENALTY_MULT
    else:
        hard_line, cad_line = grid.score_segment_components(
            atuv, auv, ignore_source_id=host_id
        )
        if hard_line > 0.0:
            _telemetry_reject(duct, telemetry_prefix + '_leader_blocked')
            return None

    total_len = leader_length_paper(atuv, auv)
    straight_limit = min(NORMAL_LEADER_HARD_MAX_PAPER_IN, 0.46)
    if SMART_V3_ACTIVE:
        straight_limit = max(straight_limit, SMART_NORMAL_STRAIGHT_MAX_PAPER_IN)
    if max_length is not None:
        straight_limit = max(straight_limit, float(max_length))
    if total_len > straight_limit:
        _telemetry_reject(duct, telemetry_prefix + '_leader_too_long')
        return None

    huv = uv_of_point(head)
    coord_pen = 0.0
    if coordinator is not None:
        axis = horizontal_axis_uv(duct)
        coord_pen = coordinator.score_vertical_leader(axis, auv, huv, rect)

    cad_pen = min(cad_head, CAD_HEAD_SCORE_CAP * 2.0) * CAD_LOCAL_OVERLAP_PENALTY
    cad_pen += min(cad_line, CAD_LEADER_SCORE_CAP * 2.0) * 0.08
    straight_base = 6.0 if SMART_STRAIGHT_BIAS else 28.0
    score = (straight_base + float(base_boost) + coord_pen + cad_pen + mep_pen +
             _leader_distance_cost(total_len) * 0.72 +
             _smart_length_breakpoint_penalty(total_len) +
             base_rank * 5.0 + gap_paper * 10.0 + abs(shift_paper) * 5.0)
    return (score, head, None, rect, True, anchor, attachment)

def _leader_candidate_score(grid, duct, head, rect, metrics, anchor, edge_sign,
                            base_rank, gap_paper, shift_paper, crop_rect, coordinator, head_prefilter=None):
    host_id = eid_int(duct.Id)
    if head_prefilter is None:
        outside = crop_rect is not None and not rect_contains_rect(crop_rect, rect)
        hard_head, cad_head = grid.score_rect_components(rect, ignore_source_id=None)
        if outside:
            _telemetry_reject(duct, 'dogleg_head_outside_crop')
            return None
        if hard_head > 0.0:
            _telemetry_reject(duct, 'dogleg_head_blocked')
            return None
        if cad_head >= CAD_EXTREME_BLOCK_THRESHOLD:
            _telemetry_reject(duct, 'dogleg_head_cad')
            return None
    else:
        hard_head, cad_head = head_prefilter

    shoulder = paper_to_model(LEADER_SHOULDER_PAPER_IN)
    attachment, elbow = _edge_geometry(head, metrics, edge_sign, shoulder)
    atuv = uv_of_point(attachment)
    euv = uv_of_point(elbow)
    auv = uv_of_point(anchor)

    mep_pen = 0.0
    if SMART_V3_ACTIVE and SMART_SOFT_MEP_CROSSINGS:
        d1 = grid.score_segment_detail(atuv, euv, ignore_source_id=host_id)
        d2 = grid.score_segment_detail(euv, auv, ignore_source_id=host_id)
        if d1['blocking'] > 0.0 or d2['blocking'] > 0.0:
            _telemetry_reject(duct, 'dogleg_leader_blocked')
            return None
        mep_total = d1['mep'] + d2['mep']
        if mep_total > SMART_MEP_CROSS_MAX_SCORE:
            _telemetry_reject(duct, 'dogleg_mep_cross_limit')
            return None
        cad_sh = d1['cad']
        cad_diag = d2['cad']
        mep_pen = mep_total * SMART_MEP_CROSS_PENALTY_MULT
    else:
        hard_sh, cad_sh = grid.score_segment_components(atuv, euv, ignore_source_id=host_id)
        hard_diag, cad_diag = grid.score_segment_components(euv, auv, ignore_source_id=host_id)
        if hard_sh > 0.0 or hard_diag > 0.0:
            _telemetry_reject(duct, 'dogleg_leader_blocked')
            return None

    shoulder_len = leader_length_paper(atuv, euv)
    diag_len = leader_length_paper(euv, auv)
    total_len = shoulder_len + diag_len
    hard_total_limit = NORMAL_LEADER_HARD_MAX_PAPER_IN
    hard_diag_limit = NORMAL_LEADER_DIAG_MAX_PAPER_IN
    if SMART_V3_ACTIVE:
        hard_total_limit = max(hard_total_limit, 0.62)
        hard_diag_limit = max(hard_diag_limit, 0.56)
    if diag_len > hard_diag_limit or total_len > hard_total_limit:
        _telemetry_reject(duct, 'dogleg_too_long')
        return None

    angle = _leader_angle_deg(euv, auv)
    if angle < HUMAN_MIN_LEADER_ANGLE_DEG or angle > HUMAN_MAX_LEADER_ANGLE_DEG:
        angle_pen = 180.0 + abs(angle - HUMAN_ANGLE_TARGET_DEG) * HUMAN_ANGLE_PENALTY_PER_DEG
    else:
        angle_pen = abs(angle - HUMAN_ANGLE_TARGET_DEG) * HUMAN_ANGLE_PENALTY_PER_DEG

    huv = uv_of_point(head)
    buv = uv_of_point(anchor)
    coord_pen = 0.0
    if coordinator is not None:
        axis = horizontal_axis_uv(duct)
        coord_pen = coordinator.score_vertical_leader(axis, buv, huv, rect)

    cad_pen = min(cad_head, CAD_HEAD_SCORE_CAP * 2.0) * CAD_LOCAL_OVERLAP_PENALTY
    cad_pen += min(cad_sh + cad_diag, CAD_LEADER_SCORE_CAP * 2.0) * 0.10

    distance_pen = _leader_distance_cost(total_len) + _smart_length_breakpoint_penalty(total_len)
    if total_len > PREFERRED_LEADER_TOTAL_PAPER_IN:
        excess = total_len - PREFERRED_LEADER_TOTAL_PAPER_IN
        distance_pen += excess * excess * 5200.0

    dogleg_base = SMART_DOGLEG_BASE if SMART_V3_ACTIVE else (118.0 if SMART_STRAIGHT_BIAS else 70.0)
    score = (dogleg_base + coord_pen + cad_pen + mep_pen + angle_pen + distance_pen +
             base_rank * 6.0 + gap_paper * 14.0 + abs(shift_paper) * 6.0)
    return (score, head, elbow, rect, True, anchor, attachment)

def _v7_host_context(duct):
    did = eid_int(duct.Id)
    cached = _V7_HOST_CONTEXT_CACHE.get(did)
    if cached is not None:
        return cached
    line = duct_line(duct)
    if line is None or line.Length < 1e-9:
        _V7_HOST_CONTEXT_CACHE[did] = None
        return None
    p0 = line.GetEndPoint(0)
    p1 = line.GetEndPoint(1)
    u0 = uv_of_point(p0)
    u1 = uv_of_point(p1)
    du = u1[0] - u0[0]
    dv = u1[1] - u0[1]
    length_uv = math.sqrt(du * du + dv * dv)
    if length_uv < 1e-9:
        _V7_HOST_CONTEXT_CACHE[did] = None
        return None
    axis = (du / length_uv, dv / length_uv)
    ctx = {
        'did': did,
        'line': line,
        'p0': p0,
        'p1': p1,
        'uv0': u0,
        'uv1': u1,
        'du': du,
        'dv': dv,
        'length': float(line.Length),
        'length_uv': length_uv,
        'axis': axis,
        'perp': (-axis[1], axis[0]),
    }
    _V7_HOST_CONTEXT_CACHE[did] = ctx
    return ctx


def _v7_uv_to_xyz(ctx, uv):
    _LAYOUT_TELEMETRY['v7_xyz_materialized'] += 1
    base = ctx['p0']
    u0 = ctx['uv0']
    return base + RIGHT.Multiply(uv[0] - u0[0]) + UP.Multiply(uv[1] - u0[1])


def _v7_param_uv(ctx, t):
    return (ctx['uv0'][0] + ctx['du'] * t,
            ctx['uv0'][1] + ctx['dv'] * t)


def _v7_param_xyz(ctx, t):
    try:
        return ctx['line'].Evaluate(t, True)
    except Exception:
        return _v7_uv_to_xyz(ctx, _v7_param_uv(ctx, t))


def _v7_base_uvs(ctx):
    params = (0.50, 0.36, 0.64, 0.24, 0.76, 0.16, 0.84)
    return [(t, _v7_param_uv(ctx, t)) for t in params]


def _v7_candidate_rect_uv(head_uv, metrics):
    left, right, bottom, top = metrics
    pad = paper_to_model(TAG_CLEARANCE_PAPER_IN)
    return (head_uv[0] - left - pad,
            head_uv[1] - bottom - pad,
            head_uv[0] + right + pad,
            head_uv[1] + top + pad)


def _v7_clamped_param(ctx, t):
    margin = paper_to_model(0.10) / max(ctx['length'], 1e-9)
    margin = min(0.22, max(0.08, margin))
    return max(margin, min(1.0 - margin, t))


def _v7_anchor_uvs(ctx, head_uv, limit):
    # Orthogonal projection is mathematically the shortest straight route.
    du = head_uv[0] - ctx['uv0'][0]
    dv = head_uv[1] - ctx['uv0'][1]
    den = ctx['du'] * ctx['du'] + ctx['dv'] * ctx['dv']
    if den < 1e-12:
        return []
    t0 = (du * ctx['du'] + dv * ctx['dv']) / den
    values = []
    seen = set()
    for delta_paper in ANCHOR_SWEEP_PAPER_IN:
        t = t0 + paper_to_model(delta_paper) / max(ctx['length'], 1e-9)
        t = _v7_clamped_param(ctx, t)
        key = round(float(t), 6)
        if key in seen:
            continue
        seen.add(key)
        values.append((t, _v7_param_uv(ctx, t)))
        if len(values) >= limit:
            break
    if len(values) < limit:
        t = 0.50
        key = round(t, 6)
        if key not in seen:
            values.append((t, _v7_param_uv(ctx, t)))
    return values[:limit]


def _v7_edge_sign(head_uv, metrics, anchor_uv):
    left_u = head_uv[0] - metrics[0]
    right_u = head_uv[0] + metrics[1]
    return -1.0 if abs(anchor_uv[0] - left_u) <= abs(anchor_uv[0] - right_u) else 1.0


def _v7_straight_candidate(grid, duct, ctx, head_uv, rect, metrics, anchor_t, anchor_uv,
                           base_rank, gap_paper, shift_paper, coordinator,
                           mep_limit, max_length, base_boost, telemetry_prefix):
    edge_sign = _v7_edge_sign(head_uv, metrics, anchor_uv)
    edge_extent = metrics[0] if edge_sign < 0.0 else metrics[1]
    attachment_uv = (head_uv[0] + edge_sign * edge_extent, head_uv[1])

    detail = grid.score_segment_detail_fast(attachment_uv, anchor_uv, ignore_source_id=ctx['did'])
    if detail['blocking'] > 0.0:
        _telemetry_reject(duct, telemetry_prefix + '_leader_blocked')
        return None
    if detail['mep'] > float(mep_limit):
        _telemetry_reject(duct, telemetry_prefix + '_mep_cross_limit')
        return None

    total_len = leader_length_paper(attachment_uv, anchor_uv)
    if total_len > float(max_length):
        _telemetry_reject(duct, telemetry_prefix + '_leader_too_long')
        return None

    coord_pen = 0.0
    if coordinator is not None:
        coord_pen = coordinator.score_vertical_leader(ctx['axis'], anchor_uv, head_uv, rect)
    cad_pen = min(detail['cad'], CAD_LEADER_SCORE_CAP * 2.0) * 0.08
    mep_pen = detail['mep'] * SMART_MEP_CROSS_PENALTY_MULT
    straight_base = 6.0 if SMART_STRAIGHT_BIAS else 28.0
    score = (straight_base + float(base_boost) + coord_pen + cad_pen + mep_pen +
             _leader_distance_cost(total_len) * 0.72 +
             _smart_length_breakpoint_penalty(total_len) +
             base_rank * 5.0 + gap_paper * 10.0 + abs(shift_paper) * 5.0)

    head = _v7_uv_to_xyz(ctx, head_uv)
    anchor = _v7_param_xyz(ctx, anchor_t)
    attachment = _v7_uv_to_xyz(ctx, attachment_uv)
    _LAYOUT_TELEMETRY['v7_fast_straight_accepts'] += 1
    return (score, head, None, rect, True, anchor, attachment)


def generate_v6_fast_layout_pool(target, grid, metrics, crop_rect,
                                 allow_leader=True, coordinator=None,
                                 cap_results=True):
    """V7 hot path: pure view-plane search, materializing XYZ only for viable layouts."""
    duct = target['duct']
    did = eid_int(duct.Id)
    ctx = _v7_host_context(duct)
    if ctx is None:
        _telemetry_reject(duct, 'no_layout_base')
        _telemetry_pool(duct, 'normal', 0)
        return []

    axis = ctx['axis']
    perp = ctx['perp']
    half_duct = plan_half_width(duct)
    bases = _v7_base_uvs(ctx)
    candidates = []
    straight_candidates = []
    clear_heads = []
    clear_head_keys = set()

    def remember_head(data):
        head_uv = data[3]
        key = (round(head_uv[0], 5), round(head_uv[1], 5))
        if key not in clear_head_keys:
            clear_head_keys.add(key)
            clear_heads.append(data)

    # On-host search is cheap. For isolated placement, an excellent clean inline
    # candidate can return immediately instead of also generating leader clouds.
    if (not SMART_FORCE_LEADERS) and _inline_host_candidate_allowed(duct, metrics, axis, perp):
        along_span, across_span = _host_tag_spans(metrics, axis, perp)
        host_across = max(half_duct * 2.0, 1e-9)
        across_spill = max(0.0, (across_span - host_across) / max(across_span, 1e-9))
        along_spill = max(0.0, (along_span - ctx['length']) / max(along_span, 1e-9))
        spill_pen = ((across_spill * SMART_INLINE_SPILL_PENALTY) +
                     (along_spill * SMART_INLINE_SPILL_PENALTY * 0.75))
        for base_rank, base_item in enumerate(bases[:SMART_BASE_POINT_COUNT]):
            base_t, base_uv = base_item
            for shift_paper in SMART_V6_INLINE_SHIFTS:
                shift = paper_to_model(shift_paper)
                head_uv = (base_uv[0] + axis[0] * shift,
                           base_uv[1] + axis[1] * shift)
                rect = _v7_candidate_rect_uv(head_uv, metrics)
                _LAYOUT_TELEMETRY['v5_heads_tested'] += 1
                if crop_rect is not None and not rect_contains_rect(crop_rect, rect):
                    continue
                hard, cad = grid.score_rect_components_fast(rect, ignore_source_id=did)
                if hard > 0.0 or cad >= CAD_EXTREME_BLOCK_THRESHOLD:
                    continue
                _LAYOUT_TELEMETRY['v5_clear_heads'] += 1
                score = spill_pen + cad * 0.90 + base_rank * 4.0 + abs(shift_paper) * 7.0
                head = _v7_uv_to_xyz(ctx, head_uv)
                base_xyz = _v7_param_xyz(ctx, base_t)
                candidates.append((score, head, None, rect, False, base_xyz, None))
                _LAYOUT_TELEMETRY['v7_fast_inline_accepts'] += 1
                if cap_results and score <= 45.0:
                    _telemetry_pool(duct, 'normal', len(candidates))
                    return candidates[:1]

    if not allow_leader:
        candidates.sort(key=lambda x: (x[0], _layout_total_paper(x)))
        _telemetry_pool(duct, 'normal', len(candidates))
        return candidates[:SMART_V6_POOL_MAX if cap_results else len(candidates)]

    def run_straight_stage(gaps, shifts, mep_limit, max_length, base_boost, prefix,
                           allow_early_stop):
        stage = []
        # Isolated targets need only a tiny quality pool; micro-clusters request
        # cap_results=False and retain the wider diversity needed by beam search.
        target_count = 3 if cap_results else SMART_V6_STAGE_RESULT_TARGET
        early_length = min(SMART_V6_EARLY_SHORT_LENGTH, 0.42) if cap_results else SMART_V6_EARLY_SHORT_LENGTH
        anchor_limit = min(SMART_ANCHOR_LIMIT, 2) if cap_results else SMART_ANCHOR_LIMIT
        for base_rank, base_item in enumerate(bases[:SMART_BASE_POINT_COUNT]):
            base_t, base_uv = base_item
            for side in (1.0, -1.0):
                toward_host = (-side * perp[0], -side * perp[1])
                body = tag_support_extent(metrics, toward_host)
                for gap_paper in gaps:
                    normal_dist = half_duct + body + paper_to_model(gap_paper)
                    nu = perp[0] * side * normal_dist
                    nv = perp[1] * side * normal_dist
                    for shift_paper in shifts:
                        sh = paper_to_model(shift_paper)
                        head_uv = (base_uv[0] + nu + axis[0] * sh,
                                   base_uv[1] + nv + axis[1] * sh)
                        rect = _v7_candidate_rect_uv(head_uv, metrics)
                        _LAYOUT_TELEMETRY['v5_heads_tested'] += 1
                        if crop_rect is not None and not rect_contains_rect(crop_rect, rect):
                            continue
                        hard_head, cad_head = grid.score_rect_components_fast(rect)
                        if hard_head > 0.0 or cad_head >= CAD_EXTREME_BLOCK_THRESHOLD:
                            continue
                        _LAYOUT_TELEMETRY['v5_clear_heads'] += 1
                        head_data = (base_rank, gap_paper, shift_paper, head_uv, rect,
                                     hard_head, cad_head)
                        remember_head(head_data)
                        anchors = _v7_anchor_uvs(ctx, head_uv, anchor_limit)
                        best_for_head = None
                        best_len = 999.0
                        for anchor_t, anchor_uv in anchors:
                            _LAYOUT_TELEMETRY['v5_anchor_tests'] += 1
                            cand = _v7_straight_candidate(
                                grid, duct, ctx, head_uv, rect, metrics,
                                anchor_t, anchor_uv, base_rank, gap_paper, shift_paper,
                                coordinator, mep_limit, max_length, base_boost, prefix
                            )
                            if cand is None:
                                continue
                            clen = _layout_total_paper(cand)
                            if best_for_head is None or cand[0] < best_for_head[0]:
                                best_for_head = cand
                                best_len = clen
                            if clen <= 0.36:
                                break
                        if best_for_head is not None:
                            stage.append(best_for_head)
                            if allow_early_stop and len(stage) >= target_count and best_len <= early_length:
                                _LAYOUT_TELEMETRY['v6_stage_a_early_stops'] += 1
                                return stage
        return stage

    stage_a = run_straight_stage(
        SMART_V6_STAGE_A_GAPS, SMART_V6_STAGE_A_SHIFTS,
        SMART_MEP_CROSS_MAX_SCORE, SMART_NORMAL_STRAIGHT_MAX_PAPER_IN,
        0.0, 'normal', True
    )
    straight_candidates.extend(stage_a)

    if not stage_a and not candidates:
        _LAYOUT_TELEMETRY['v5_expanded_targets'].add(did)
        stage_b = run_straight_stage(
            SMART_V6_STAGE_B_GAPS, SMART_V6_STAGE_B_SHIFTS,
            SMART_V6_EXPANDED_MEP_MAX_SCORE, SMART_V6_EXPANDED_MAX_LENGTH,
            SMART_V6_EXPANDED_BASE_SCORE, 'expanded', False
        )
        straight_candidates.extend(stage_b)

    candidates.extend(straight_candidates)

    # Doglegs remain a rare fallback. Convert only the few best cached UV heads
    # back to XYZ before calling the proven legacy elbow scorer.
    if (not straight_candidates) or SMART_ALLOW_DOGLEGS_WHEN_STRAIGHT:
        ranked_heads = sorted(clear_heads, key=lambda x: (abs(x[2]) + x[1] * 0.8, x[0]))[:SMART_V6_DOGLEG_HEAD_LIMIT]
        for base_rank, gap_paper, shift_paper, head_uv, rect, hard_head, cad_head in ranked_heads:
            head = _v7_uv_to_xyz(ctx, head_uv)
            anchors = _anchor_candidates_from_elbow(duct, head)
            for anchor in anchors[:SMART_V6_DOGLEG_ANCHOR_LIMIT]:
                _LAYOUT_TELEMETRY['v5_anchor_tests'] += 1
                edge_sign = _preferred_edge_sign(head, metrics, anchor)
                cand = _leader_candidate_score(
                    grid, duct, head, rect, metrics, anchor, edge_sign,
                    base_rank, gap_paper, shift_paper, crop_rect, coordinator,
                    head_prefilter=(hard_head, cad_head)
                )
                if cand is not None:
                    candidates.append(cand)
                    break

    _V6_CLEAR_HEAD_CACHE[did] = list(sorted(
        clear_heads, key=lambda x: (abs(x[2]) + x[1] * 0.8, x[0])
    )[:SMART_V6_REUSE_HEAD_LIMIT])

    unique = []
    seen = set()
    for layout in sorted(candidates, key=lambda x: (x[0], _layout_total_paper(x))):
        try:
            h = uv_of_point(layout[1])
            a = uv_of_point(layout[5]) if layout[5] is not None else (0.0, 0.0)
            key = (round(h[0], 4), round(h[1], 4), round(a[0], 4), round(a[1], 4),
                   bool(layout[4]), bool(layout[2] is not None))
        except Exception:
            key = (id(layout),)
        if key in seen:
            continue
        seen.add(key)
        unique.append(layout)
        if len(unique) >= SMART_V6_POOL_MAX:
            break

    _telemetry_pool(duct, 'normal', len(unique))
    if cap_results and len(unique) > HUMAN_MAX_CANDIDATES:
        unique = unique[:HUMAN_MAX_CANDIDATES]
    return unique

def generate_v6_reuse_layout_candidates(target, grid, metrics, crop_rect, coordinator=None):
    """Reuse V7 clear UV heads with relaxed route limits before emergency search."""
    if not SMART_V6_ACTIVE:
        return []
    duct = target['duct']
    did = eid_int(duct.Id)
    ctx = _v7_host_context(duct)
    cached = _V6_CLEAR_HEAD_CACHE.get(did, [])
    if ctx is None or not cached:
        return []
    results = []
    for base_rank, gap_paper, shift_paper, head_uv, rect, hard_head, cad_head in cached[:SMART_V6_REUSE_HEAD_LIMIT]:
        anchors = _v7_anchor_uvs(ctx, head_uv, SMART_V6_REUSE_ANCHOR_LIMIT)
        for anchor_t, anchor_uv in anchors:
            _LAYOUT_TELEMETRY['v5_anchor_tests'] += 1
            cand = _v7_straight_candidate(
                grid, duct, ctx, head_uv, rect, metrics,
                anchor_t, anchor_uv, base_rank, gap_paper, shift_paper,
                coordinator, SMART_V6_REUSE_MEP_MAX_SCORE,
                SMART_V6_REUSE_MAX_LENGTH, SMART_V6_REUSE_BASE_SCORE, 'reuse'
            )
            if cand is not None:
                results.append(cand)
                if _layout_total_paper(cand) <= 0.55:
                    break
    results.sort(key=lambda x: (x[0], _layout_total_paper(x)))
    return results[:10]

def generate_v9_escape_layout_candidates(target, grid, metrics, crop_rect, coordinator=None):
    """Collision-safe wide search before the overlap-tolerant emergency tier.

    V8 showed that making the normal tag footprint too conservative simply moved
    difficult tags into emergency placement, where hard overlaps are permitted.
    V9 reverses that trade: keep the normal footprint compact, then search a few
    wider straight-leader lanes while still requiring a completely clear tag head
    and no blocking annotation/tag/leader crossing. MEP crossings may be tolerated
    at a high score because they are visually preferable to stacked text.
    """
    if not SMART_V6_ACTIVE:
        return []
    duct = target['duct']
    did = eid_int(duct.Id)
    ctx = _v7_host_context(duct)
    if ctx is None:
        return []
    axis = ctx['axis']
    perp = ctx['perp']
    half_duct = plan_half_width(duct)
    bases = _v7_base_uvs(ctx)[:SMART_V9_ESCAPE_BASE_COUNT]
    results = []

    for base_rank, base_item in enumerate(bases):
        base_t, base_uv = base_item
        for side in (1.0, -1.0):
            toward_host = (-side * perp[0], -side * perp[1])
            body = tag_support_extent(metrics, toward_host)
            for gap_paper in SMART_V9_ESCAPE_GAPS:
                normal_dist = half_duct + body + paper_to_model(gap_paper)
                nu = perp[0] * side * normal_dist
                nv = perp[1] * side * normal_dist
                for shift_paper in SMART_V9_ESCAPE_SHIFTS:
                    sh = paper_to_model(shift_paper)
                    head_uv = (base_uv[0] + nu + axis[0] * sh,
                               base_uv[1] + nv + axis[1] * sh)
                    rect = _v7_candidate_rect_uv(head_uv, metrics)
                    _LAYOUT_TELEMETRY['v9_escape_head_tests'] += 1
                    _LAYOUT_TELEMETRY['v5_heads_tested'] += 1
                    if crop_rect is not None and not rect_contains_rect(crop_rect, rect):
                        continue
                    hard_head, cad_head = grid.score_rect_components_fast(rect)
                    if hard_head > 0.0 or cad_head >= CAD_EXTREME_BLOCK_THRESHOLD * 1.5:
                        continue
                    _LAYOUT_TELEMETRY['v5_clear_heads'] += 1
                    anchors = _v7_anchor_uvs(ctx, head_uv, SMART_V9_ESCAPE_ANCHOR_LIMIT)
                    best_for_head = None
                    for anchor_t, anchor_uv in anchors:
                        _LAYOUT_TELEMETRY['v5_anchor_tests'] += 1
                        cand = _v7_straight_candidate(
                            grid, duct, ctx, head_uv, rect, metrics,
                            anchor_t, anchor_uv, base_rank, gap_paper, shift_paper,
                            coordinator, SMART_V9_ESCAPE_MEP_MAX_SCORE,
                            SMART_V9_ESCAPE_MAX_LENGTH, SMART_V9_ESCAPE_BASE_SCORE,
                            'escape'
                        )
                        if cand is None:
                            continue
                        if best_for_head is None or (cand[0], _layout_total_paper(cand)) < (best_for_head[0], _layout_total_paper(best_for_head)):
                            best_for_head = cand
                        if _layout_total_paper(cand) <= 0.56:
                            break
                    if best_for_head is not None:
                        results.append(best_for_head)
                        # This tier exists to avoid emergency, not to build a huge
                        # candidate cloud. Stop as soon as a few safe choices exist.
                        if len(results) >= 3:
                            results.sort(key=lambda x: (x[0], _layout_total_paper(x)))
                            if _layout_total_paper(results[0]) <= 0.64:
                                return results[:SMART_V9_ESCAPE_MAX_RESULTS]
                if len(results) >= SMART_V9_ESCAPE_MAX_RESULTS:
                    break
            if len(results) >= SMART_V9_ESCAPE_MAX_RESULTS:
                break
        if len(results) >= SMART_V9_ESCAPE_MAX_RESULTS:
            break
    results.sort(key=lambda x: (x[0], _layout_total_paper(x)))
    return results[:SMART_V9_ESCAPE_MAX_RESULTS]


def generate_layout_candidates(target, grid, metrics, crop_rect, allow_leader=True, coordinator=None, cap_results=True):
    """Generate compact human-style candidates with V4 failure telemetry."""
    duct = target['duct']
    bases = host_layout_points(target)
    if not bases:
        fb = target_anchor(target)
        bases = [fb] if fb is not None else []
    if not bases:
        _telemetry_reject(duct, 'no_layout_base')
        _telemetry_pool(duct, 'normal', 0)
        return []

    axis, perp = duct_axis_and_perp(duct)
    if axis is None:
        _telemetry_reject(duct, 'no_plan_axis')
        _telemetry_pool(duct, 'normal', 0)
        return []
    axis_vec = vec_from_uv(axis[0], axis[1])
    perp_vec = vec_from_uv(perp[0], perp[1])
    half_duct = plan_half_width(duct)
    host_id = eid_int(duct.Id)
    candidates = []

    inline_allowed = (not SMART_FORCE_LEADERS) and _inline_host_candidate_allowed(duct, metrics, axis, perp)
    if inline_allowed:
        along_span, across_span = _host_tag_spans(metrics, axis, perp)
        host_across = max(plan_half_width(duct) * 2.0, 1e-9)
        spill_ratio = max(0.0, (across_span - host_across) / max(across_span, 1e-9))
        spill_pen = spill_ratio * SMART_INLINE_SPILL_PENALTY if SMART_V3_ACTIVE else 0.0
        for base_rank, base in enumerate(bases[:3]):
            for shift_paper in (0.0, 0.06, -0.06, 0.12, -0.12, 0.20, -0.20):
                head = base + axis_vec.Multiply(paper_to_model(shift_paper))
                r = candidate_rect(head, metrics)
                if crop_rect is not None and not rect_contains_rect(crop_rect, r):
                    _telemetry_reject(duct, 'inline_outside_crop')
                    continue
                hard, cad = grid.score_rect_components(r, ignore_source_id=host_id)
                if hard > 0.0:
                    _telemetry_reject(duct, 'inline_head_blocked')
                    continue
                if cad >= CAD_EXTREME_BLOCK_THRESHOLD:
                    _telemetry_reject(duct, 'inline_head_cad')
                    continue
                score = (spill_pen + cad * 0.90 + base_rank * 4.0 + abs(shift_paper) * 7.0)
                candidates.append((score, head, None, r, False, base, None))

    if allow_leader:
        base_count = SMART_BASE_POINT_COUNT if SMART_V3_ACTIVE else 3
        anchor_limit = SMART_ANCHOR_LIMIT if SMART_V3_ACTIVE else 99
        for base_rank, base in enumerate(bases[:base_count]):
            for side in (1.0, -1.0):
                toward_host = (-side * perp[0], -side * perp[1])
                body = tag_support_extent(metrics, toward_host)
                for gap_paper in HUMAN_LEADER_GAPS_PAPER_IN:
                    normal_dist = half_duct + body + paper_to_model(gap_paper)
                    for shift_paper in HUMAN_LEADER_ALONG_PAPER_IN:
                        head = (base + perp_vec.Multiply(side * normal_dist) +
                                axis_vec.Multiply(paper_to_model(shift_paper)))
                        r = candidate_rect(head, metrics)
                        if crop_rect is not None and not rect_contains_rect(crop_rect, r):
                            _telemetry_reject(duct, 'normal_head_outside_crop')
                            continue
                        hard_head, cad_head = grid.score_rect_components(r)
                        if hard_head > 0.0:
                            _telemetry_reject(duct, 'normal_head_blocked')
                            continue
                        if cad_head >= CAD_EXTREME_BLOCK_THRESHOLD:
                            _telemetry_reject(duct, 'normal_head_cad')
                            continue
                        anchors = _anchor_candidates_from_elbow(duct, head)
                        if not anchors:
                            _telemetry_reject(duct, 'no_usable_anchor')
                            continue
                        for anchor in anchors[:anchor_limit]:
                            straight_cand = _straight_leader_candidate_score(
                                grid, duct, head, r, metrics, anchor,
                                base_rank, gap_paper, shift_paper, crop_rect, coordinator,
                                telemetry_prefix='normal'
                            )
                            if straight_cand is not None:
                                candidates.append(straight_cand)
                                if SMART_V3_ACTIVE and SMART_STRAIGHT_FIRST and not SMART_ALLOW_DOGLEGS_WHEN_STRAIGHT:
                                    continue
                            edge_sign = _preferred_edge_sign(head, metrics, anchor)
                            cand = _leader_candidate_score(
                                grid, duct, head, r, metrics, anchor, edge_sign,
                                base_rank, gap_paper, shift_paper, crop_rect, coordinator
                            )
                            if cand is not None:
                                candidates.append(cand)

    candidates.sort(key=lambda x: x[0])
    _telemetry_pool(duct, 'normal', len(candidates))
    if cap_results and len(candidates) > HUMAN_MAX_CANDIDATES:
        candidates = candidates[:HUMAN_MAX_CANDIDATES]
    return candidates

def generate_rescue_layout_candidates(target, grid, metrics, crop_rect, coordinator=None, cap_results=True):
    """Wider but still local search kept below V4 bridge/emergency tiers."""
    if not SMART_V3_ACTIVE or not SMART_RESCUE_ENABLED:
        return []
    duct = target['duct']
    bases = host_layout_points(target)
    if not bases:
        fb = target_anchor(target)
        bases = [fb] if fb is not None else []
    if not bases:
        _telemetry_pool(duct, 'rescue', 0)
        return []
    axis, perp = duct_axis_and_perp(duct)
    if axis is None:
        _telemetry_pool(duct, 'rescue', 0)
        return []
    axis_vec = vec_from_uv(axis[0], axis[1])
    perp_vec = vec_from_uv(perp[0], perp[1])
    half_duct = plan_half_width(duct)
    results = []

    if not SMART_FORCE_LEADERS and _inline_host_candidate_allowed(duct, metrics, axis, perp):
        host_id = eid_int(duct.Id)
        for base_rank, base in enumerate(bases[:3]):
            for shift_paper in (0.24, -0.24, 0.34, -0.34, 0.46, -0.46):
                head = base + axis_vec.Multiply(paper_to_model(shift_paper))
                rect = candidate_rect(head, metrics)
                if crop_rect is not None and not rect_contains_rect(crop_rect, rect):
                    continue
                hard, cad = grid.score_rect_components(rect, ignore_source_id=host_id)
                if hard > 0.0 or cad >= CAD_EXTREME_BLOCK_THRESHOLD:
                    continue
                score = SMART_RESCUE_BASE_SCORE * 0.55 + cad * 0.90 + abs(shift_paper) * 10.0
                results.append((score, head, None, rect, False, base, None))

    for base_rank, base in enumerate(bases[:3]):
        for side in (1.0, -1.0):
            toward_host = (-side * perp[0], -side * perp[1])
            body = tag_support_extent(metrics, toward_host)
            for gap_paper in SMART_RESCUE_GAPS_PAPER_IN:
                normal_dist = half_duct + body + paper_to_model(gap_paper)
                for shift_paper in SMART_RESCUE_ALONG_PAPER_IN:
                    head = (base + perp_vec.Multiply(side * normal_dist) +
                            axis_vec.Multiply(paper_to_model(shift_paper)))
                    rect = candidate_rect(head, metrics)
                    if crop_rect is not None and not rect_contains_rect(crop_rect, rect):
                        continue
                    hard_head, cad_head = grid.score_rect_components(rect)
                    if hard_head > 0.0 or cad_head >= CAD_EXTREME_BLOCK_THRESHOLD:
                        continue
                    anchors = _anchor_candidates_from_elbow(duct, head)
                    for anchor in anchors[:SMART_RESCUE_ANCHOR_LIMIT]:
                        cand = _straight_leader_candidate_score(
                            grid, duct, head, rect, metrics, anchor,
                            base_rank + 2, gap_paper, shift_paper, crop_rect, coordinator,
                            telemetry_prefix='rescue'
                        )
                        if cand is not None:
                            c = list(cand)
                            c[0] += SMART_RESCUE_BASE_SCORE + _smart_length_breakpoint_penalty(_layout_total_paper(cand))
                            results.append(tuple(c))
                            if SMART_STRAIGHT_FIRST and not SMART_ALLOW_DOGLEGS_WHEN_STRAIGHT:
                                continue
                        edge_sign = _preferred_edge_sign(head, metrics, anchor)
                        dog = _leader_candidate_score(
                            grid, duct, head, rect, metrics, anchor, edge_sign,
                            base_rank + 2, gap_paper, shift_paper, crop_rect, coordinator
                        )
                        if dog is not None:
                            c = list(dog)
                            c[0] += SMART_RESCUE_BASE_SCORE + 650.0
                            results.append(tuple(c))
    results.sort(key=lambda x: x[0])
    _telemetry_pool(duct, 'rescue', len(results))
    if cap_results:
        return results[:SMART_RESCUE_MAX_CANDIDATES]
    return results


def generate_bridge_layout_candidates(target, grid, metrics, crop_rect, coordinator=None, cap_results=True):
    """V4 controlled bridge between rescue and emergency.

    The tag head must remain completely clear. Only the leader is relaxed, and
    only for MEP crossings; tags/annotations/leaders stay hard blockers. Bridge
    intentionally favors straight leaders and does not generate doglegs.
    """
    if not SMART_V4_ACTIVE or not SMART_BRIDGE_ENABLED:
        return []
    duct = target['duct']
    bases = host_layout_points(target)
    if not bases:
        fb = target_anchor(target)
        bases = [fb] if fb is not None else []
    if not bases:
        _telemetry_pool(duct, 'bridge', 0)
        return []
    axis, perp = duct_axis_and_perp(duct)
    if axis is None:
        _telemetry_pool(duct, 'bridge', 0)
        return []
    axis_vec = vec_from_uv(axis[0], axis[1])
    perp_vec = vec_from_uv(perp[0], perp[1])
    half_duct = plan_half_width(duct)
    results = []

    # A wider along-host inline sweep is cheap and occasionally removes a leader
    # entirely without accepting any overlap with another visible object.
    if not SMART_FORCE_LEADERS and _inline_host_candidate_allowed(duct, metrics, axis, perp):
        host_id = eid_int(duct.Id)
        for base in bases[:3]:
            for shift_paper in (0.28, -0.28, 0.40, -0.40, 0.54, -0.54):
                head = base + axis_vec.Multiply(paper_to_model(shift_paper))
                rect = candidate_rect(head, metrics)
                if crop_rect is not None and not rect_contains_rect(crop_rect, rect):
                    continue
                hard, cad = grid.score_rect_components(rect, ignore_source_id=host_id)
                if hard > 0.0 or cad >= CAD_EXTREME_BLOCK_THRESHOLD:
                    continue
                score = SMART_BRIDGE_BASE_SCORE - 450.0 + cad * 0.8 + abs(shift_paper) * 12.0
                results.append((score, head, None, rect, False, base, None))

    for base_rank, base in enumerate(bases[:3]):
        for side in (1.0, -1.0):
            toward_host = (-side * perp[0], -side * perp[1])
            body = tag_support_extent(metrics, toward_host)
            for gap_paper in SMART_BRIDGE_GAPS_PAPER_IN:
                normal_dist = half_duct + body + paper_to_model(gap_paper)
                for shift_paper in SMART_BRIDGE_ALONG_PAPER_IN:
                    head = (base + perp_vec.Multiply(side * normal_dist) +
                            axis_vec.Multiply(paper_to_model(shift_paper)))
                    rect = candidate_rect(head, metrics)
                    if crop_rect is not None and not rect_contains_rect(crop_rect, rect):
                        _telemetry_reject(duct, 'bridge_head_outside_crop')
                        continue
                    hard_head, cad_head = grid.score_rect_components(rect)
                    if hard_head > 0.0:
                        _telemetry_reject(duct, 'bridge_head_blocked')
                        continue
                    if cad_head >= CAD_EXTREME_BLOCK_THRESHOLD:
                        _telemetry_reject(duct, 'bridge_head_cad')
                        continue
                    anchors = _anchor_candidates_from_elbow(duct, head)
                    if not anchors:
                        continue
                    for anchor in anchors[:SMART_BRIDGE_ANCHOR_LIMIT]:
                        cand = _straight_leader_candidate_score(
                            grid, duct, head, rect, metrics, anchor,
                            base_rank + 3, gap_paper, shift_paper,
                            crop_rect, coordinator,
                            mep_limit=SMART_BRIDGE_MEP_MAX_SCORE,
                            max_length=SMART_BRIDGE_MAX_LENGTH_PAPER_IN,
                            base_boost=SMART_BRIDGE_BASE_SCORE,
                            telemetry_prefix='bridge'
                        )
                        if cand is not None:
                            results.append(cand)
                            # One valid anchor is enough for this head; keep the
                            # bridge pool diverse instead of filling it with near
                            # duplicates of the same visible straight leader.
                            break
                    if len(results) >= SMART_BRIDGE_MAX_CANDIDATES * 2:
                        break
                if len(results) >= SMART_BRIDGE_MAX_CANDIDATES * 2:
                    break
            if len(results) >= SMART_BRIDGE_MAX_CANDIDATES * 2:
                break
        if len(results) >= SMART_BRIDGE_MAX_CANDIDATES * 2:
            break

    results.sort(key=lambda x: (x[0], _layout_total_paper(x)))
    _telemetry_pool(duct, 'bridge', len(results))
    if cap_results:
        return results[:SMART_BRIDGE_MAX_CANDIDATES]
    return results


def generate_ranked_layout_pool(target, grid, metrics, crop_rect, allow_leader=True,
                                coordinator=None, cap_results=True):
    if SMART_V6_ACTIVE:
        return generate_v6_fast_layout_pool(
            target, grid, metrics, crop_rect,
            allow_leader=allow_leader, coordinator=coordinator,
            cap_results=cap_results
        )
    if SMART_V5_ACTIVE:
        return generate_v6_fast_layout_pool(
            target, grid, metrics, crop_rect,
            allow_leader=allow_leader, coordinator=coordinator,
            cap_results=cap_results
        )

    # Legacy V4/local path retained for baseline comparison.
    duct = target['duct']
    normal = generate_layout_candidates(
        target, grid, metrics, crop_rect,
        allow_leader=allow_leader, coordinator=coordinator,
        cap_results=False
    )
    combined = list(normal)
    best = normal[0] if normal else None
    need_rescue = bool(allow_leader and SMART_RESCUE_ENABLED and
                       (best is None or _layout_total_paper(best) > SMART_RESCUE_TRIGGER_PAPER_IN or best[0] > 1800.0))
    if need_rescue:
        combined.extend(generate_rescue_layout_candidates(
            target, grid, metrics, crop_rect,
            coordinator=coordinator, cap_results=False
        ))
    combined.sort(key=lambda x: (x[0], _layout_total_paper(x)))
    return combined[:HUMAN_MAX_CANDIDATES if cap_results else len(combined)]

def generate_emergency_layout_candidates(target, grid, metrics, crop_rect, coordinator=None):
    """Last-resort local search, optimized to avoid duplicate dogleg work."""
    duct = target['duct']
    bases = host_layout_points(target)
    if not bases:
        return []
    axis, perp = duct_axis_and_perp(duct)
    if axis is None:
        return []
    axis_vec = vec_from_uv(axis[0], axis[1])
    perp_vec = vec_from_uv(perp[0], perp[1])
    half_duct = plan_half_width(duct)
    host_id = eid_int(duct.Id)
    results = []

    # V6 pulls emergency heads closer to the host than V5. That usually shortens
    # the leader and the emergency routine already prices any resulting overlap.
    gaps = [0.18, 0.26, 0.34] if SMART_V6_ACTIVE else EMERGENCY_LEADER_GAPS_PAPER_IN
    shifts = [0.0, 0.12, -0.12, 0.24, -0.24] if SMART_V6_ACTIVE else EMERGENCY_ALONG_PAPER_IN
    base_limit = 2 if SMART_V6_ACTIVE else (3 if SMART_V3_ACTIVE else 5)

    for base_rank, base in enumerate(bases[:base_limit]):
        for side in (1.0, -1.0):
            toward_host = (-side * perp[0], -side * perp[1])
            body = tag_support_extent(metrics, toward_host)
            for gap_paper in gaps:
                normal_dist = half_duct + body + paper_to_model(gap_paper)
                for shift_paper in shifts:
                    head = (base + perp_vec.Multiply(side * normal_dist) +
                            axis_vec.Multiply(paper_to_model(shift_paper)))
                    r = candidate_rect(head, metrics)
                    _LAYOUT_TELEMETRY['v6_emergency_head_tests'] += 1
                    hard_head, cad_head = _head_scores(grid, r, crop_rect)
                    if hard_head > 0.0 or cad_head >= CAD_EXTREME_BLOCK_THRESHOLD * 1.8:
                        if grid.rect_hits_kinds(r, set(['tag', 'annotation'])):
                            _LAYOUT_TELEMETRY['v9_emergency_text_blocked_heads'] += 1
                        continue
                    text_block_pen = 0.0

                    anchors = _anchor_candidates_from_elbow(duct, head)
                    for anchor in anchors[:SMART_ANCHOR_LIMIT if SMART_V3_ACTIVE else 99]:
                        edge_sign = _preferred_edge_sign(head, metrics, anchor)
                        auv = uv_of_point(anchor)
                        straight_added = False
                        if SMART_V3_ACTIVE:
                            edge_extent = metrics[0] if edge_sign < 0.0 else metrics[1]
                            straight_attachment = head + RIGHT.Multiply(edge_sign * edge_extent)
                            sauv = uv_of_point(straight_attachment)
                            hard_line, cad_line = grid.score_segment_components(
                                sauv, auv, ignore_source_id=host_id
                            )
                            straight_len = leader_length_paper(sauv, auv)
                            if straight_len <= EMERGENCY_MAX_TOTAL_PAPER_IN:
                                coord_pen = 0.0
                                if coordinator is not None:
                                    coord_pen = coordinator.score_vertical_leader(
                                        axis, auv, uv_of_point(head), r
                                    )
                                sscore = (5600.0 + text_block_pen + hard_head * EMERGENCY_HARD_WEIGHT +
                                          hard_line * (EMERGENCY_HARD_WEIGHT * 0.75) +
                                          cad_head * 0.95 + cad_line * 0.10 + coord_pen +
                                          _leader_distance_cost(straight_len) * 1.18 +
                                          _smart_length_breakpoint_penalty(straight_len) +
                                          base_rank * 12.0 + gap_paper * 14.0 +
                                          abs(shift_paper) * 9.0)
                                candidate = (sscore, head, None, r, True, anchor, straight_attachment)
                                if not _layout_is_safe(target, candidate, grid, crop_rect):
                                    continue
                                results.append(candidate)
                                straight_added = True
                                # Do not compute a dogleg for a head/anchor that
                                # already produced the preferred straight route.
                                if SMART_STRAIGHT_FIRST and not SMART_ALLOW_DOGLEGS_WHEN_STRAIGHT:
                                    if straight_len <= 0.55:
                                        break
                                    continue

                        attachment, elbow = _edge_geometry(
                            head, metrics, edge_sign,
                            paper_to_model(LEADER_SHOULDER_PAPER_IN)
                        )
                        atuv = uv_of_point(attachment)
                        euv = uv_of_point(elbow)
                        hard_sh, cad_sh = grid.score_segment_components(
                            atuv, euv, ignore_source_id=host_id
                        )
                        hard_diag, cad_diag = grid.score_segment_components(
                            euv, auv, ignore_source_id=host_id
                        )
                        total_len = (leader_length_paper(atuv, euv) +
                                     leader_length_paper(euv, auv))
                        if total_len > EMERGENCY_MAX_TOTAL_PAPER_IN:
                            continue
                        hard_total = hard_head + hard_sh + hard_diag
                        cad_total = cad_head + (cad_sh + cad_diag) * 0.15
                        angle = _leader_angle_deg(euv, auv)
                        angle_pen = abs(angle - HUMAN_ANGLE_TARGET_DEG) * 1.4
                        coord_pen = 0.0
                        if coordinator is not None:
                            coord_pen = coordinator.score_vertical_leader(
                                axis, auv, uv_of_point(head), r
                            )
                        emergency_base = 6200.0 if SMART_V3_ACTIVE else 4200.0
                        score = (emergency_base + text_block_pen + hard_total * EMERGENCY_HARD_WEIGHT +
                                 cad_total * 0.95 + coord_pen +
                                 _leader_distance_cost(total_len) * 1.45 +
                                 _smart_length_breakpoint_penalty(total_len) +
                                 angle_pen + base_rank * 15.0 + gap_paper * 16.0 +
                                 abs(shift_paper) * 10.0)
                        candidate = (score, head, elbow, r, True, anchor, attachment)
                        if _layout_is_safe(target, candidate, grid, crop_rect):
                            results.append(candidate)

                    # Once this target has several compact emergency choices, more
                    # heads rarely improve the final drawing enough to justify the cost.
                    if SMART_V6_ACTIVE and len(results) >= 8:
                        best_now = min(results, key=lambda x: (x[0], _layout_total_paper(x)))
                        if _layout_total_paper(best_now) <= 0.55:
                            break
                if SMART_V6_ACTIVE and len(results) >= 8:
                    best_now = min(results, key=lambda x: (x[0], _layout_total_paper(x)))
                    if _layout_total_paper(best_now) <= 0.55:
                        break
            if SMART_V6_ACTIVE and len(results) >= 8:
                best_now = min(results, key=lambda x: (x[0], _layout_total_paper(x)))
                if _layout_total_paper(best_now) <= 0.55:
                    break
        if SMART_V6_ACTIVE and len(results) >= 8:
            best_now = min(results, key=lambda x: (x[0], _layout_total_paper(x)))
            if _layout_total_paper(best_now) <= 0.55:
                break

    results = [layout for layout in results
               if _layout_is_safe(target, layout, grid, crop_rect)]
    results.sort(key=lambda x: (x[0], _layout_total_paper(x)))
    _telemetry_pool(duct, 'emergency', len(results))
    return results[:MAX_LAYOUT_ATTEMPTS]

def _layout_is_safe(target, layout, grid, crop_rect):
    """All placement tiers preserve text, MEP bodies, crop and leader blockers."""
    if layout is None:
        return False
    _score, _head, _elbow, rect, use_leader, _anchor, _attachment = layout
    if crop_rect is not None and not rect_contains_rect(crop_rect, rect):
        return False
    host_id = eid_int(target['duct'].Id)
    hard, cad = grid.score_rect_components(
        rect, ignore_source_id=host_id if not use_leader else None)
    if hard > 0.0 or cad >= CAD_EXTREME_BLOCK_THRESHOLD * 1.8:
        return False
    segments = _lane_candidate_segments(layout)
    if use_leader and not segments:
        return False
    for a, b in segments:
        detail = grid.score_segment_detail(a, b, ignore_source_id=host_id)
        if detail['blocking'] > 0.0 or detail['mep'] > SMART_BRIDGE_MEP_MAX_SCORE:
            return False
    return not use_leader or _layout_total_paper(layout) <= MAX_LEADER_TOTAL_PAPER_IN


def _deterministic_last_resort(target, metrics, crop_rect, grid=None):
    """Compact fallback only when live geometry proves the layout is usable."""
    if grid is None:
        return None
    duct = target['duct']
    bases = host_layout_points(target)
    if not bases:
        return None
    axis, perp = duct_axis_and_perp(duct)
    if axis is None:
        return None
    axis_vec = vec_from_uv(axis[0], axis[1])
    perp_vec = vec_from_uv(perp[0], perp[1])
    half_duct = plan_half_width(duct)
    best = None
    for base_rank, base in enumerate(bases[:3]):
        for side in (1.0, -1.0):
            toward_host = (-side * perp[0], -side * perp[1])
            body = tag_support_extent(metrics, toward_host)
            normal_dist = half_duct + body + paper_to_model(0.48)
            for shift_paper in (0.0, 0.18, -0.18, 0.34, -0.34, 0.52, -0.52):
                head = (base + perp_vec.Multiply(side * normal_dist) +
                        axis_vec.Multiply(paper_to_model(shift_paper)))
                r = candidate_rect(head, metrics)
                anchors = _anchor_candidates_from_elbow(duct, head)
                for anchor in anchors[:7]:
                    edge_sign = _preferred_edge_sign(head, metrics, anchor)
                    attachment, elbow = _edge_geometry(
                        head, metrics, edge_sign,
                        paper_to_model(LEADER_SHOULDER_PAPER_IN)
                    )
                    total = (leader_length_paper(uv_of_point(attachment), uv_of_point(elbow)) +
                             leader_length_paper(uv_of_point(elbow), uv_of_point(anchor)))
                    if total > EMERGENCY_MAX_TOTAL_PAPER_IN:
                        continue
                    candidate = (900000.0 + _leader_distance_cost(total) * 2.0 +
                                 base_rank * 20.0 + abs(shift_paper) * 15.0,
                                 head, elbow, r, True, anchor, attachment)
                    if (not _layout_is_safe(target, candidate, grid, crop_rect)):
                        continue
                    if best is None or candidate[0] < best[0]:
                        best = candidate
    return best

def choose_layout(target, grid, metrics, crop_rect, allow_leader=True, coordinator=None):
    candidates = generate_ranked_layout_pool(
        target, grid, metrics, crop_rect,
        allow_leader=allow_leader, coordinator=coordinator
    )
    for candidate in candidates:
        if _layout_is_safe(target, candidate, grid, crop_rect):
            return candidate
    if allow_leader:
        if SMART_V6_ACTIVE:
            reused = generate_v6_reuse_layout_candidates(
                target, grid, metrics, crop_rect, coordinator=coordinator
            )
            reused = [candidate for candidate in reused
                      if _layout_is_safe(target, candidate, grid, crop_rect)]
            if reused:
                did = eid_int(target['duct'].Id)
                _LAYOUT_TELEMETRY['v6_reuse_used'].add(did)
                return reused[0]
        escape = generate_v9_escape_layout_candidates(
            target, grid, metrics, crop_rect, coordinator=coordinator
        )
        escape = [candidate for candidate in escape
                  if _layout_is_safe(target, candidate, grid, crop_rect)]
        if escape:
            did = eid_int(target['duct'].Id)
            _LAYOUT_TELEMETRY['v9_escape_used'].add(did)
            return escape[0]
        emergency = generate_emergency_layout_candidates(
            target, grid, metrics, crop_rect, coordinator=coordinator
        )
        if emergency:
            _LAYOUT_TELEMETRY['emergency_used'].add(eid_int(target['duct'].Id))
            chosen = list(emergency[0])
            chosen[0] = max(float(chosen[0]), SMART_EMERGENCY_SCORE_FLOOR + 1.0)
            return tuple(chosen)
        return _deterministic_last_resort(target, metrics, crop_rect, grid=grid)
    return None

def _median_numeric(values):
    if not values:
        return None
    vals = sorted(values)
    n = len(vals)
    mid = n // 2
    if n % 2:
        return vals[mid]
    return 0.5 * (vals[mid - 1] + vals[mid])


def _layout_service_key(duct):
    did = eid_int(duct.Id)
    if did in _LAYOUT_SERVICE_KEY_CACHE:
        return _LAYOUT_SERVICE_KEY_CACHE[did]
    result = None
    try:
        value = duct.ServiceId
        if value is not None:
            result = 'fab:{0}'.format(value)
    except Exception:
        pass
    if result is None:
        try:
            value = duct.ServiceName
            if value:
                result = 'fabname:{0}'.format(str(value))
        except Exception:
            pass
    if result is None:
        try:
            sysobj = duct.MEPSystem
            if sysobj is not None:
                result = 'sys:{0}'.format(eid_int(sysobj.Id))
        except Exception:
            pass
    _LAYOUT_SERVICE_KEY_CACHE[did] = result
    return result

def _lane_target_info(target):
    duct = target['duct']
    axis = horizontal_axis_uv(duct)
    pts = host_layout_points(target)
    if axis is None or not pts:
        return None
    au = abs(axis[0])
    av = abs(axis[1])
    if av >= au * LANE_ORIENTATION_RATIO:
        orient = 'vertical'
    elif au >= av * LANE_ORIENTATION_RATIO:
        orient = 'horizontal'
    else:
        orient = 'angled'
    base_uv = uv_of_point(pts[0])
    return {
        'target': target,
        'id': eid_int(duct.Id),
        'orientation': orient,
        'axis': axis,
        'base_uv': base_uv,
        'across': base_uv[0],
        'along': base_uv[1],
        'service': _layout_service_key(duct),
    }

def _lane_infos_can_group(a, b):
    sa = a.get('service')
    sb = b.get('service')
    if sa is not None and sb is not None and sa != sb:
        return False
    if SMART_V3_ACTIVE and SMART_MICRO_CLUSTERING:
        d = dist2d_uv(a['base_uv'], b['base_uv']) / max(_PAPER_TO_MODEL_FACTOR, 1e-9)
        return d <= SMART_MICRO_RADIUS_PAPER_IN
    if a['orientation'] != b['orientation']:
        return False
    if abs(a['across'] - b['across']) > paper_to_model(LANE_GROUP_ACROSS_PAPER_IN):
        return False
    if abs(a['along'] - b['along']) > paper_to_model(LANE_GROUP_ALONG_PAPER_IN):
        return False
    return True

def _build_lane_groups(targets):
    infos = []
    for target in targets:
        info = _lane_target_info(target)
        if info is not None:
            infos.append(info)

    infos.sort(key=lambda x: (str(x.get('service')), x['base_uv'][0], x['base_uv'][1], x['id']))
    if not infos:
        return []

    max_size = SMART_MICRO_GROUP_SIZE if SMART_V3_ACTIVE else LANE_MAX_GROUP_SIZE
    if not (SMART_V3_ACTIVE and SMART_MICRO_CLUSTERING):
        # Legacy grouping is already small; preserve exact behavior.
        unused = set(range(len(infos)))
        groups = []
        while unused:
            seed_i = min(unused)
            unused.remove(seed_i)
            seed = infos[seed_i]
            nearby = []
            for j in list(unused):
                other = infos[j]
                if not _lane_infos_can_group(seed, other):
                    continue
                d = dist2d_uv(seed['base_uv'], other['base_uv']) / max(_PAPER_TO_MODEL_FACTOR, 1e-9)
                nearby.append((d, j))
            nearby.sort(key=lambda x: (x[0], infos[x[1]]['id']))
            chosen = [seed_i] + [x[1] for x in nearby[:max(0, max_size - 1)]]
            for j in chosen[1:]:
                unused.discard(j)
            members = [infos[i] for i in chosen]
            if len(members) >= 2:
                groups.append(members)
        groups.sort(key=lambda g: (-len(g), min(x['id'] for x in g)))
        return groups

    radius_model = max(paper_to_model(SMART_MICRO_RADIUS_PAPER_IN), 1e-6)
    bins = {}
    for i, info in enumerate(infos):
        u, v = info['base_uv']
        key = (int(math.floor(u / radius_model)), int(math.floor(v / radius_model)))
        bins.setdefault(key, []).append(i)

    unused = set(range(len(infos)))
    groups = []
    while unused:
        seed_i = min(unused)
        unused.remove(seed_i)
        seed = infos[seed_i]
        u, v = seed['base_uv']
        bx = int(math.floor(u / radius_model))
        by = int(math.floor(v / radius_model))
        nearby = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for j in bins.get((bx + dx, by + dy), ()):
                    if j not in unused:
                        continue
                    other = infos[j]
                    if not _lane_infos_can_group(seed, other):
                        continue
                    d = dist2d_uv(seed['base_uv'], other['base_uv']) / max(_PAPER_TO_MODEL_FACTOR, 1e-9)
                    nearby.append((d, j))
        nearby.sort(key=lambda x: (x[0], infos[x[1]]['id']))
        chosen = [seed_i] + [x[1] for x in nearby[:max(0, max_size - 1)]]
        for j in chosen[1:]:
            unused.discard(j)
        members = [infos[i] for i in chosen]
        if len(members) >= 2:
            groups.append(members)
    groups.sort(key=lambda g: (-len(g), min(x['id'] for x in g)))
    return groups

def _lane_candidate_segments(layout):
    try:
        use_leader = bool(layout[4])
    except Exception:
        return []
    if not use_leader:
        return []
    elbow = layout[2]
    anchor = layout[5]
    attachment = layout[6]
    if anchor is None or attachment is None:
        return []
    a = uv_of_point(attachment)
    z = uv_of_point(anchor)
    if elbow is None:
        return [(a, z)]
    e = uv_of_point(elbow)
    return [(a, e), (e, z)]


def _lane_candidate_meta(info, metrics, layout, source):
    head_uv = uv_of_point(layout[1])
    base = info['base_uv']
    if info['orientation'] == 'vertical':
        delta = head_uv[0] - base[0]
        head_along = head_uv[1]
        if delta > paper_to_model(0.015):
            side = 1
            near_edge = head_uv[0] - metrics[0]
        elif delta < -paper_to_model(0.015):
            side = -1
            near_edge = head_uv[0] + metrics[1]
        else:
            side = 0
            near_edge = head_uv[0]
    else:
        delta = head_uv[1] - base[1]
        head_along = head_uv[0]
        if delta > paper_to_model(0.015):
            side = 1
            near_edge = head_uv[1] - metrics[2]
        elif delta < -paper_to_model(0.015):
            side = -1
            near_edge = head_uv[1] + metrics[3]
        else:
            side = 0
            near_edge = head_uv[1]
    return {
        'layout': layout,
        'source': source,
        'side': side,
        'near_edge': near_edge,
        'head_along': head_along,
        'rect': layout[3],
        'segments': _lane_candidate_segments(layout),
        'dogleg': bool(layout[4] and layout[2] is not None),
    }


def _lane_candidate_pool(info, grid, metrics, crop_rect):
    """V3 micro-cluster candidate pool.

    Keep the best diverse local choices, including rescue-tier candidates when
    the normal pool is weak. Alignment is no longer forced across mixed axes.
    """
    target = info['target']
    layouts = generate_ranked_layout_pool(
        target, grid, metrics, crop_rect,
        allow_leader=True, coordinator=None, cap_results=False
    )
    pool = []
    inline = 0
    straight = 0
    dogleg = 0
    limit = SMART_MICRO_CANDIDATES_PER_TARGET if SMART_V3_ACTIVE else LANE_CANDIDATES_PER_TARGET
    for layout in layouts:
        use_leader = bool(layout[4])
        is_dog = bool(use_leader and layout[2] is not None)
        if not use_leader:
            if inline >= 3:
                continue
            inline += 1
        elif is_dog:
            if dogleg >= 2:
                continue
            dogleg += 1
        else:
            if straight >= max(5, limit - 4):
                continue
            straight += 1
        score = layout[0]
        source = _layout_source_from_score(score)
        pool.append({
            'layout': layout,
            'source': source,
            'side': 0,
            'near_edge': 0.0,
            'head_along': 0.0,
            'rect': layout[3],
            'segments': _lane_candidate_segments(layout),
            'dogleg': is_dog,
        })
        if len(pool) >= limit:
            break
    return pool

def _lane_segment_hits_rect(segments, rect):
    for a, b in segments:
        if segment_intersects_rect(a, b, rect):
            return True
    return False


def _lane_segments_cross(a_segments, b_segments):
    for a1, a2 in a_segments:
        for b1, b2 in b_segments:
            if segments_intersect(a1, a2, b1, b2):
                return True
    return False


def _lane_pair_penalty(candidate, selected):
    penalty = 0.0
    r = candidate['rect']
    expanded = rect_expand(r, paper_to_model(LANE_TAG_GAP_PAPER_IN))
    hard_gap = paper_to_model(SMART_V8_MICRO_HARD_GAP_PAPER_IN) * 0.5
    safe_r = rect_expand(r, hard_gap)
    existing_doglegs = 0
    for prev in selected:
        pr = prev['rect']
        safe_pr = rect_expand(pr, hard_gap)
        # V8: a tiny visible air gap is mandatory inside micro-clusters. Earlier
        # builds only rejected literal rectangle intersection, which was too
        # optimistic once Revit rendered the real annotation graphics.
        if rect_intersects(safe_r, safe_pr):
            return None
        if _lane_segment_hits_rect(candidate['segments'], pr):
            return None
        if _lane_segment_hits_rect(prev['segments'], r):
            return None
        if rect_intersects(expanded, pr):
            penalty += LANE_TAG_GAP_PENALTY
        if candidate['segments'] and prev['segments'] and _lane_segments_cross(candidate['segments'], prev['segments']):
            penalty += LANE_LEADER_CROSS_PENALTY
        if prev.get('dogleg'):
            existing_doglegs += 1
    if SMART_V3_ACTIVE and candidate.get('dogleg'):
        penalty += (1 + existing_doglegs) * SMART_CLUSTER_DOGLEG_PENALTY
    return penalty

def _lane_global_penalty(candidate, planned_grid):
    # Previous groups are stored in a tiny supplemental spatial index.  Tag-head
    # intersections are rejected; leader crossings are allowed only at a very
    # high cost so one group cannot casually draw through another group's work.
    if planned_grid is None:
        return 0.0
    safe_rect = rect_expand(candidate['rect'], paper_to_model(SMART_V8_MICRO_HARD_GAP_PAPER_IN) * 0.5)
    if planned_grid.score_rect(safe_rect) > 0.0:
        return None
    penalty = 0.0
    for a, b in candidate['segments']:
        score = planned_grid.score_segment(a, b)
        if score > 0.0:
            penalty += LANE_GLOBAL_LEADER_CROSS_PENALTY + score * 0.65
    return penalty


def _solve_micro_group(group, pools, planned_grid):
    beam = SMART_MICRO_BEAM_WIDTH if SMART_V3_ACTIVE else LANE_BEAM_WIDTH
    states = [(0.0, [])]
    for index in range(len(group)):
        pool = pools[index]
        new_states = []
        for base_cost, selected in states:
            for cand in pool:
                pair_pen = _lane_pair_penalty(cand, selected)
                if pair_pen is None:
                    continue
                global_pen = _lane_global_penalty(cand, planned_grid)
                if global_pen is None:
                    continue
                source_pen = 0.0
                if cand.get('source') == 'rescue':
                    source_pen = 120.0
                elif cand.get('source') == 'bridge':
                    source_pen = 320.0
                total = base_cost + cand['layout'][0] + pair_pen + global_pen + source_pen
                new_states.append((total, selected + [cand]))
        if not new_states:
            return None
        new_states.sort(key=lambda s: s[0])
        states = new_states[:beam]
    return states[0] if states else None


def build_grouped_layout_plan(targets, grid, tag_size_cache, tag_size_fallback, crop_rect):
    """Plan small mixed-orientation drafting neighborhoods before placement."""
    groups = _build_lane_groups(targets)
    plan = {}
    order = []
    stats = {
        'groups': 0,
        'placements': 0,
        'opposite': 0,
        'emergency': 0,
        'last': 0,
        'rescue': 0,
        'bridge': 0,
    }
    planned_grid = SpatialGrid(max(paper_to_model(0.70), 0.5))

    for group in groups:
        active = [info for info in group if info['id'] not in plan]
        if len(active) < 2:
            continue
        pools = []
        usable = True
        for info in active:
            metrics = get_tag_metrics_cached(tag_size_cache, tag_size_fallback, info['target']['duct'])
            pool = _lane_candidate_pool(info, grid, metrics, crop_rect)
            if not pool:
                usable = False
                break
            pools.append(pool)
        if not usable:
            continue

        solved = _solve_micro_group(active, pools, planned_grid)
        if solved is None:
            continue
        selected = solved[1]
        stats['groups'] += 1
        for info, cand in zip(active, selected):
            did = info['id']
            plan[did] = {'layout': cand['layout'], 'source': cand.get('source') or 'normal'}
            order.append(did)
            stats['placements'] += 1
            if cand.get('source') == 'rescue':
                stats['rescue'] += 1
            elif cand.get('source') == 'bridge':
                stats['bridge'] += 1
            planned_grid.add_rect(
                'tag', rect_expand(cand['rect'], paper_to_model(SMART_V8_RESERVE_PAD_PAPER_IN)),
                W_TAG, did
            )
            for a, b in cand['segments']:
                planned_grid.add_segment('leader', a, b, W_LEADER, did)
    return plan, order, stats

def apply_leader(tag, reference, anchor, elbow):
    """Apply leader geometry with a zero-extra-call straight-attached fast path."""
    if elbow is None:
        try:
            if not tag.HasLeader:
                tag.HasLeader = True
            if not tag.HasLeader:
                return False
            return 'attached_straight'
        except Exception as ex:
            if _is_fatal_revit_error(ex):
                raise
            return False

    # A tag created with addLeader=True already owns a straight attached leader.
    # Setting an elbow directly is enough to turn that leader into a compact dogleg.
    try:
        tag.SetLeaderElbow(reference, elbow)
        return 'attached_elbow'
    except Exception as ex:
        if _is_fatal_revit_error(ex):
            raise

    # Rare fallback for tag types that only permit free leader ends.
    try:
        tag.LeaderEndCondition = DB.LeaderEndCondition.Free
        tag.SetLeaderEnd(reference, anchor)
        try:
            tag.SetLeaderElbow(reference, elbow)
            return 'free_elbow'
        except Exception as ex:
            if _is_fatal_revit_error(ex):
                raise
            return 'free_straight'
    except Exception as ex:
        if _is_fatal_revit_error(ex):
            raise
        return False

# -----------------------------------------------------------------------------
# v8 post-placement repair pass
# -----------------------------------------------------------------------------
def _record_leader_segments(record):
    if not record.get('leader_applied'):
        return []
    attachment = record.get('attachment')
    anchor = record.get('anchor')
    if attachment is None or anchor is None:
        return []
    a = uv_of_point(attachment)
    z = uv_of_point(anchor)
    elbow = record.get('elbow')
    mode = record.get('leader_mode')
    if elbow is not None and mode in ('elbow', 'elbow_attached', 'attached_elbow', 'free_elbow'):
        e = uv_of_point(elbow)
        return [(a, e), (e, z)]
    return [(a, z)]


def _reserve_record_geometry(grid, record):
    tag_id = record.get('tag_id')
    rect = record.get('rect')
    if rect is not None:
        # Reserve a slightly larger footprint than the scored candidate. This is
        # cheap (no extra Revit API call) and protects following tags from small
        # family/bounding-box discrepancies and visually touching text.
        grid.add_rect(
            'tag', rect_expand(rect, paper_to_model(SMART_V8_RESERVE_PAD_PAPER_IN)),
            W_TAG, tag_id
        )
    for a, b in _record_leader_segments(record):
        grid.add_segment('leader', a, b, W_LEADER, tag_id)


def _record_leader_total_paper(record):
    total = 0.0
    for a, b in _record_leader_segments(record):
        total += leader_length_paper(a, b)
    return total


def _record_leader_angle(record):
    elbow = record.get('elbow')
    anchor = record.get('anchor')
    if elbow is None or anchor is None:
        return 90.0
    return _leader_angle_deg(uv_of_point(elbow), uv_of_point(anchor))


def _repair_source_penalty(source):
    if source == 'last':
        return REPAIR_LAST_SOURCE_PENALTY
    if source == 'emergency':
        return REPAIR_EMERGENCY_SOURCE_PENALTY
    return 0.0


def _repair_geometry_quality(grid, target, rect, attachment, elbow, anchor,
                             source, crop_rect):
    duct = target['duct']
    host_id = eid_int(duct.Id)
    hard_head, cad_head = grid.score_rect_components(rect)
    if crop_rect is not None and not rect_contains_rect(crop_rect, rect):
        hard_head += W_OUTSIDE_CROP

    hard_leader = 0.0
    cad_leader = 0.0
    total_len = 0.0
    angle = 90.0
    if attachment is not None and anchor is not None:
        a = uv_of_point(attachment)
        z = uv_of_point(anchor)
        if elbow is not None:
            e = uv_of_point(elbow)
            h1, c1 = grid.score_segment_components(a, e, ignore_source_id=host_id)
            h2, c2 = grid.score_segment_components(e, z, ignore_source_id=host_id)
            hard_leader += h1 + h2
            cad_leader += c1 + c2
            total_len = leader_length_paper(a, e) + leader_length_paper(e, z)
            angle = _leader_angle_deg(e, z)
        else:
            h1, c1 = grid.score_segment_components(a, z, ignore_source_id=host_id)
            hard_leader += h1
            cad_leader += c1
            total_len = leader_length_paper(a, z)

    angle_pen = 0.0
    if angle < REPAIR_BAD_ANGLE_MIN_DEG:
        angle_pen = (REPAIR_BAD_ANGLE_MIN_DEG - angle) * 14.0
    elif angle > REPAIR_BAD_ANGLE_MAX_DEG:
        angle_pen = (angle - REPAIR_BAD_ANGLE_MAX_DEG) * 14.0

    score = ((hard_head + hard_leader) * REPAIR_HARD_COLLISION_MULT +
             cad_head * REPAIR_CAD_HEAD_MULT +
             cad_leader * REPAIR_CAD_LEADER_MULT +
             _leader_distance_cost(total_len) * 1.20 +
             angle_pen + _repair_source_penalty(source))
    return {
        'score': score,
        'hard': hard_head + hard_leader,
        'cad': cad_head + cad_leader,
        'length': total_len,
        'angle': angle,
    }


def _generate_v3_repair_pool(record, grid, crop_rect):
    """V4 fresh repair search against the final placed-neighbor geometry."""
    target = record.get('target')
    metrics = record.get('metrics')
    if target is None or metrics is None:
        return []
    layouts = generate_ranked_layout_pool(
        target, grid, metrics, crop_rect,
        allow_leader=True, coordinator=None, cap_results=False
    )

    # Same-head reroute: often the best cleanup is simply moving the attached
    # leader end along the host while leaving an already-good tag head alone.
    if record.get('head') is not None and record.get('rect') is not None:
        duct = target['duct']
        head = record.get('head')
        rect = record.get('rect')
        current_len = _record_leader_total_paper(record)
        anchors = _anchor_candidates_from_elbow(duct, head)
        for idx, anchor in enumerate(anchors[:9]):
            cand = _straight_leader_candidate_score(
                grid, duct, head, rect, metrics, anchor,
                idx, 0.0, 0.0, crop_rect, None,
                mep_limit=SMART_BRIDGE_MEP_MAX_SCORE,
                max_length=max(0.62, current_len),
                base_boost=0.0,
                telemetry_prefix='repair'
            )
            if cand is not None:
                layouts.append(cand)

    unique = []
    seen = set()
    for layout in sorted(layouts, key=lambda x: (x[0], _layout_total_paper(x))):
        try:
            h = uv_of_point(layout[1])
            a = uv_of_point(layout[5]) if layout[5] is not None else (0.0, 0.0)
            key = (round(h[0], 4), round(h[1], 4), round(a[0], 4), round(a[1], 4),
                   bool(layout[4]), bool(layout[2] is not None))
        except Exception:
            key = (id(layout),)
        if key in seen:
            continue
        seen.add(key)
        unique.append(layout)
        if len(unique) >= V4_REPAIR_MAX_POOL:
            break
    return unique

def _repair_candidate_quality(grid, target, layout, crop_rect):
    score, head, elbow, rect, use_leader, anchor, attachment = layout
    if not use_leader:
        result = _repair_geometry_quality(
            grid, target, rect, None, None, None, 'normal', crop_rect
        )
    else:
        if attachment is None or anchor is None:
            return None
        result = _repair_geometry_quality(
            grid, target, rect, attachment, elbow, anchor, 'normal', crop_rect
        )
    result['layout'] = layout
    return result

def _should_attempt_repair(record, current_quality):
    if not record.get('leader_applied'):
        return False
    if record.get('source') in ('emergency', 'last'):
        return True
    if current_quality['hard'] > 0.0:
        return True
    if current_quality['length'] > REPAIR_TRIGGER_LONG_PAPER_IN:
        return True
    # V2 actively asks whether an ordinary dogleg can become a clean straight
    # leader (or a safe on-host tag), even when the dogleg is not extremely long.
    if SMART_V3_ACTIVE and record.get('elbow') is not None and current_quality['length'] > 0.24:
        return True
    angle = current_quality['angle']
    if (current_quality['length'] > 0.42 and
            (angle < REPAIR_BAD_ANGLE_MIN_DEG or angle > REPAIR_BAD_ANGLE_MAX_DEG)):
        return True
    return False

def _candidate_is_meaningfully_better(current_q, candidate_q):
    if candidate_q is None:
        return False
    max_total = REPAIR_MAX_TOTAL_PAPER_IN
    if SMART_V4_ACTIVE and current_q['length'] > 0.55:
        max_total = max(max_total, min(current_q['length'] - 0.01, 0.62))
    if candidate_q['length'] > max_total:
        return False
    if current_q['hard'] > 0.0 and candidate_q['hard'] <= 0.0:
        return True
    # V3 treats a visible shortening as useful even if the score delta is modest.
    if current_q['length'] > REPAIR_TRIGGER_LONG_PAPER_IN:
        min_gain = REPAIR_MIN_LENGTH_GAIN_PAPER_IN
        if SMART_V3_ACTIVE:
            min_gain = min(min_gain, 0.015 if SMART_V4_ACTIVE else 0.025)
        if candidate_q['length'] <= current_q['length'] - min_gain:
            return True
    gain = current_q['score'] - candidate_q['score']
    return gain >= REPAIR_MIN_SCORE_GAIN

def repair_questionable_leaders(records, grid, crop_rect):
    stats = {
        'considered': 0,
        'repaired': 0,
        'long_before': 0,
        'cross_before': 0,
        'angle_before': 0,
        'dogleg_before': 0,
        'to_straight': 0,
        'to_no_leader': 0,
        'unrepaired': 0,
    }

    ranked = []
    for record in records:
        if not record.get('leader_applied'):
            continue
        length = _record_leader_total_paper(record)
        source_rank = 2 if record.get('source') == 'last' else (1 if record.get('source') == 'emergency' else 0)
        dogleg_rank = 1 if record.get('elbow') is not None else 0
        ranked.append((source_rank, dogleg_rank, length, record))
    ranked.sort(key=lambda x: (-x[0], -x[1], -x[2], x[3].get('tag_id', 0)))
    ranked = ranked[:REPAIR_MAX_RECORDS]

    for _, _, _, record in ranked:
        tag_id = record.get('tag_id')
        target = record.get('target')
        metrics = record.get('metrics')
        if tag_id is None or target is None or metrics is None:
            continue

        grid.remove_source(tag_id)
        current_q = _repair_geometry_quality(
            grid, target, record.get('rect'), record.get('attachment'),
            record.get('elbow'), record.get('anchor'), record.get('source'), crop_rect
        )

        if not _should_attempt_repair(record, current_q):
            _reserve_record_geometry(grid, record)
            continue

        stats['considered'] += 1
        if current_q['length'] > REPAIR_TRIGGER_LONG_PAPER_IN:
            stats['long_before'] += 1
        if current_q['hard'] > 0.0:
            stats['cross_before'] += 1
        if record.get('elbow') is not None:
            stats['dogleg_before'] += 1
        if (current_q['angle'] < REPAIR_BAD_ANGLE_MIN_DEG or
                current_q['angle'] > REPAIR_BAD_ANGLE_MAX_DEG):
            stats['angle_before'] += 1

        candidates = _generate_v3_repair_pool(
            record, grid, crop_rect
        )
        candidate_qualities = []
        for layout in candidates[:max(REPAIR_MAX_CANDIDATES, 24 if SMART_V3_ACTIVE else REPAIR_MAX_CANDIDATES)]:
            q = _repair_candidate_quality(grid, target, layout, crop_rect)
            if q is not None:
                candidate_qualities.append(q)
        candidate_qualities.sort(key=lambda x: (x['hard'], x['score'], x['length']))

        chosen = None
        for cq in candidate_qualities:
            if _candidate_is_meaningfully_better(current_q, cq):
                chosen = cq
                break

        if chosen is None:
            stats['unrepaired'] += 1
            _reserve_record_geometry(grid, record)
            continue

        layout = chosen['layout']
        _, new_head, new_elbow, new_rect, use_leader, new_anchor, new_attachment = layout
        st = DB.SubTransaction(doc)
        st.Start()
        success = False
        new_mode = None
        try:
            tag = doc.GetElement(DB.ElementId(tag_id))
            if tag is None:
                raise RuntimeError('Tag no longer exists during repair pass.')
            tag.TagHeadPosition = new_head
            if use_leader:
                ref = DB.Reference(target['duct'])
                new_mode = apply_leader(tag, ref, new_anchor, new_elbow)
                if not new_mode:
                    raise RuntimeError('Repair candidate leader geometry was rejected.')
            else:
                try:
                    tag.HasLeader = False
                except Exception:
                    raise RuntimeError('Tag family did not permit leader removal.')
                new_mode = None
            st.Commit()
            record['head'] = new_head
            record['rect'] = new_rect
            record['anchor'] = new_anchor
            record['attachment'] = new_attachment
            record['elbow'] = new_elbow
            record['leader_mode'] = new_mode
            record['leader_applied'] = bool(use_leader)
            record['source'] = 'repair'
            success = True
        except Exception as ex:
            try:
                st.RollBack()
            except Exception:
                pass
            if _is_fatal_revit_error(ex):
                raise

        if success:
            stats['repaired'] += 1
            if not use_leader:
                stats['to_no_leader'] += 1
            elif new_elbow is None:
                stats['to_straight'] += 1
        else:
            stats['unrepaired'] += 1
        _reserve_record_geometry(grid, record)

    return stats

# -----------------------------------------------------------------------------
# Smart V7 comparison menu
# -----------------------------------------------------------------------------
def _configure_smart_runtime(engine_name, switches):
    global SMART_ENGINE_LABEL, SMART_V3_ACTIVE, SMART_V4_ACTIVE, SMART_V5_ACTIVE, SMART_V6_ACTIVE
    global SMART_GROUP_COORDINATION, SMART_ENABLE_REPAIR, SMART_STRAIGHT_BIAS
    global SMART_STRAIGHT_FIRST, SMART_SOFT_MEP_CROSSINGS, SMART_MICRO_CLUSTERING
    global SMART_RESCUE_ENABLED, SMART_BRIDGE_ENABLED
    global SMART_ALLOW_DOGLEGS_WHEN_STRAIGHT, SMART_FORCE_LEADERS
    global SMART_SELECTION_ONLY, SMART_DEBUG_REPORT
    global SMART_BASE_POINT_COUNT, SMART_ANCHOR_LIMIT, SMART_MEP_CROSS_MAX_SCORE
    global SMART_MEP_CROSS_PENALTY_MULT, SMART_CLUSTER_DOGLEG_PENALTY
    global SMART_DOGLEG_BASE, SMART_INLINE_SPILL_PENALTY, SMART_INLINE_MIN_HOST_PAPER_IN
    global SMART_NORMAL_STRAIGHT_MAX_PAPER_IN, SMART_MICRO_RADIUS_PAPER_IN
    global SMART_MICRO_GROUP_SIZE, SMART_MICRO_BEAM_WIDTH, SMART_MICRO_CANDIDATES_PER_TARGET
    global SMART_V6_EXPANDED_MAX_LENGTH, SMART_V6_EXPANDED_MEP_MAX_SCORE
    global SMART_V6_POOL_MAX, SMART_V6_STAGE_RESULT_TARGET
    global SMART_V6_STAGE_A_GAPS, SMART_V6_STAGE_A_SHIFTS
    global SMART_V6_STAGE_B_GAPS, SMART_V6_STAGE_B_SHIFTS
    global SMART_V6_REUSE_MEP_MAX_SCORE, SMART_V6_REUSE_MAX_LENGTH
    global INLINE_HOST_FIT_RATIO, HUMAN_MAX_CANDIDATES, SMART_HUMAN_TURN_DENSITY
    global REPAIR_MAX_RECORDS, REPAIR_MAX_CANDIDATES

    SMART_ENGINE_LABEL = engine_name or 'Smart Pipe V1 Balanced (recommended)'
    SMART_HUMAN_TURN_DENSITY = SMART_ENGINE_LABEL != 'Current Local (baseline)'
    SMART_V6_ACTIVE = SMART_ENGINE_LABEL != 'Current Local (baseline)'
    SMART_V5_ACTIVE = SMART_V6_ACTIVE
    SMART_V3_ACTIVE = SMART_V6_ACTIVE
    SMART_V4_ACTIVE = SMART_V6_ACTIVE

    SMART_GROUP_COORDINATION = SMART_V6_ACTIVE
    SMART_ENABLE_REPAIR = False
    SMART_STRAIGHT_BIAS = SMART_V6_ACTIVE
    SMART_STRAIGHT_FIRST = SMART_V6_ACTIVE
    SMART_SOFT_MEP_CROSSINGS = SMART_V6_ACTIVE
    SMART_MICRO_CLUSTERING = SMART_V6_ACTIVE
    SMART_RESCUE_ENABLED = False
    SMART_BRIDGE_ENABLED = False
    SMART_BASE_POINT_COUNT = 2
    SMART_ANCHOR_LIMIT = 3
    SMART_MEP_CROSS_MAX_SCORE = 3200.0
    SMART_MEP_CROSS_PENALTY_MULT = 0.24
    SMART_CLUSTER_DOGLEG_PENALTY = 1100.0
    SMART_DOGLEG_BASE = 190.0
    SMART_INLINE_SPILL_PENALTY = 65.0
    SMART_INLINE_MIN_HOST_PAPER_IN = 0.014
    SMART_NORMAL_STRAIGHT_MAX_PAPER_IN = 0.54
    SMART_MICRO_RADIUS_PAPER_IN = 1.58
    SMART_MICRO_GROUP_SIZE = 8
    SMART_MICRO_BEAM_WIDTH = 12
    SMART_MICRO_CANDIDATES_PER_TARGET = 10
    SMART_V6_EXPANDED_MAX_LENGTH = 0.62
    SMART_V6_EXPANDED_MEP_MAX_SCORE = 7600.0
    SMART_V6_REUSE_MEP_MAX_SCORE = 11000.0
    SMART_V6_REUSE_MAX_LENGTH = 0.64
    SMART_V6_POOL_MAX = 30
    SMART_V6_STAGE_RESULT_TARGET = 6
    SMART_V6_STAGE_A_GAPS = [0.00, 0.05, 0.10, 0.16]
    SMART_V6_STAGE_A_SHIFTS = [0.0, 0.07, -0.07, 0.14, -0.14, 0.22, -0.22]
    SMART_V6_STAGE_B_GAPS = [0.20, 0.30, 0.42]
    SMART_V6_STAGE_B_SHIFTS = [0.0, 0.20, -0.20, 0.34, -0.34, 0.50, -0.50]
    INLINE_HOST_FIT_RATIO = 0.30
    HUMAN_MAX_CANDIDATES = 30
    REPAIR_MAX_RECORDS = 28
    REPAIR_MAX_CANDIDATES = 20

    if SMART_ENGINE_LABEL == 'Smart Pipe V1 Fast':
        SMART_MEP_CROSS_MAX_SCORE = 3600.0
        SMART_MEP_CROSS_PENALTY_MULT = 0.20
        SMART_MICRO_RADIUS_PAPER_IN = 1.12
        SMART_MICRO_GROUP_SIZE = 4
        SMART_MICRO_BEAM_WIDTH = 6
        SMART_MICRO_CANDIDATES_PER_TARGET = 5
        SMART_V6_POOL_MAX = 22
        SMART_V6_STAGE_RESULT_TARGET = 4
        SMART_BASE_POINT_COUNT = 2
        SMART_ANCHOR_LIMIT = 2
        SMART_V6_STAGE_A_GAPS = [0.00, 0.06, 0.12]
        SMART_V6_STAGE_A_SHIFTS = [0.0, 0.08, -0.08, 0.16, -0.16]
        SMART_V6_STAGE_B_GAPS = [0.20, 0.32]
        SMART_V6_STAGE_B_SHIFTS = [0.0, 0.22, -0.22, 0.36, -0.36]
        HUMAN_MAX_CANDIDATES = 22
    elif SMART_ENGINE_LABEL == 'Smart Pipe V1 Clean':
        SMART_MEP_CROSS_MAX_SCORE = 2600.0
        SMART_MEP_CROSS_PENALTY_MULT = 0.31
        SMART_CLUSTER_DOGLEG_PENALTY = 1500.0
        SMART_DOGLEG_BASE = 235.0
        SMART_INLINE_SPILL_PENALTY = 80.0
        SMART_INLINE_MIN_HOST_PAPER_IN = 0.016
        SMART_NORMAL_STRAIGHT_MAX_PAPER_IN = 0.56
        SMART_MICRO_RADIUS_PAPER_IN = 1.70
        SMART_MICRO_GROUP_SIZE = 9
        SMART_MICRO_BEAM_WIDTH = 12
        SMART_MICRO_CANDIDATES_PER_TARGET = 10
        SMART_ANCHOR_LIMIT = 4
        SMART_V6_POOL_MAX = 38
        SMART_V6_STAGE_RESULT_TARGET = 8
        SMART_V6_EXPANDED_MEP_MAX_SCORE = 6200.0
        SMART_V6_REUSE_MEP_MAX_SCORE = 9000.0
        INLINE_HOST_FIT_RATIO = 0.38
        SMART_INLINE_MIN_HOST_PAPER_IN = 0.026
        HUMAN_MAX_CANDIDATES = 38
        SMART_ENABLE_REPAIR = True
    elif SMART_ENGINE_LABEL == 'Current Local (baseline)':
        SMART_V3_ACTIVE = False
        SMART_V4_ACTIVE = False
        SMART_V5_ACTIVE = False
        SMART_V6_ACTIVE = False
        SMART_GROUP_COORDINATION = False
        SMART_HUMAN_TURN_DENSITY = False
        SMART_ENABLE_REPAIR = False
        SMART_STRAIGHT_BIAS = False
        SMART_STRAIGHT_FIRST = False
        SMART_SOFT_MEP_CROSSINGS = False
        SMART_MICRO_CLUSTERING = False
        SMART_RESCUE_ENABLED = False
        SMART_BRIDGE_ENABLED = False
        SMART_BASE_POINT_COUNT = 3
        SMART_ANCHOR_LIMIT = 99

    SMART_ALLOW_DOGLEGS_WHEN_STRAIGHT = bool(switches.get('Allow doglegs even when straight is clear', False))
    SMART_FORCE_LEADERS = bool(switches.get('Force leaders (no on-host text)', False))
    if bool(switches.get('Disable micro-cluster coordination', False)):
        SMART_GROUP_COORDINATION = False
    if bool(switches.get('Run extra cleanup pass (slower)', False)) and SMART_V6_ACTIVE:
        SMART_ENABLE_REPAIR = True
        REPAIR_MAX_RECORDS = max(REPAIR_MAX_RECORDS, 36)
        REPAIR_MAX_CANDIDATES = max(REPAIR_MAX_CANDIDATES, 24)
    SMART_SELECTION_ONLY = bool(switches.get('Only selected qualifying pipes', False))
    SMART_DEBUG_REPORT = bool(switches.get('Detailed console report', False))

def _ask_smart_menu():
    global AUTOTAG_RUN_OPTIONS, AUTOTAG_ENABLED_REASONS
    options = globals().get('AUTOTAG_EXTERNAL_OPTIONS')
    if options is None:
        try:
            options = show_autotag_menu(doc, 'pipe')
        except Exception as ex:
            forms.alert('ROBMEPTOOLS AutoTag could not open its profile menu.\n\n{0}'.format(ex), title='AutoTag Plumbing')
            return False
    if not options:
        return False
    AUTOTAG_RUN_OPTIONS = options
    event_choice = options.get('event_tag_type') or {}
    if event_choice.get('id') is None:
        AUTOTAG_ENABLED_REASONS = set()
    else:
        AUTOTAG_ENABLED_REASONS = set(options.get('event_reasons', []))
    _configure_smart_runtime(options.get('engine'), options.get('switches', {}))
    return True


def _components_enabled():
    try:
        return any(AUTOTAG_RUN_OPTIONS.get('components', {}).values())
    except Exception:
        return False


def _run_component_tags():
    if not _components_enabled():
        return {'created':0,'skipped':0,'failed':0,'runtime':0.0,'by_category':{}}
    return run_direct_component_tags(doc, view, uidoc, 'pipe', AUTOTAG_RUN_OPTIONS)

def _component_early_result(base_message, title):
    if not _components_enabled():
        return False
    try:
        stats = _run_component_tags()
        ctext = component_summary(stats)
    except Exception as ex:
        if _is_fatal_revit_error(ex):
            raise
        ctext = 'Direct component tagging stopped: {0}'.format(ex)
    msg = base_message
    if ctext:
        msg += '\n\n' + ctext
    forms.alert(msg, title=title)
    return True

def _audit_point(point):
    try:
        values = [float(point.X), float(point.Y), float(point.Z)]
        if any(math.isnan(value) or math.isinf(value) for value in values):
            return None
        return values
    except Exception:
        return None


def _pipe_source_audit(source):
    data = {'source_id': eid_int(source.Id)}
    try:
        shape, dims = duct_shape_and_size(source)
        data['shape'] = str(shape)
        data['dimensions_ft'] = [float(value) for value in dims]
        data['centerline_midpoint_elevation_ft'] = float(centerline_elevation(source))
        data['service_key'] = _layout_service_key(source)
        line = duct_line(source)
        if line is not None:
            data['endpoints_ft'] = [_audit_point(line.GetEndPoint(0)),
                                    _audit_point(line.GetEndPoint(1))]
        levels = []
        for name in ('RBS_START_LEVEL_PARAM', 'INSTANCE_REFERENCE_LEVEL_PARAM',
                     'FABRICATION_LEVEL_PARAM'):
            try:
                parameter = source.get_Parameter(getattr(DB.BuiltInParameter, name))
                if parameter is None:
                    continue
                level_id = parameter.AsElementId()
                level = doc.GetElement(level_id)
                if level is not None:
                    levels.append({'parameter': name, 'level_id': eid_int(level_id),
                                   'name': str(level.Name), 'elevation_ft': float(level.Elevation)})
            except Exception as ex:
                if _is_fatal_revit_error(ex):
                    raise
                pass
        data['reference_levels'] = levels
    except Exception as ex:
        if _is_fatal_revit_error(ex):
            raise
        data['source_read_warning'] = str(ex)
    return data


def _build_tag_run_audit(raw_targets, density_targets, scoped_targets,
                         records, tag_type_id, existing, components, failed, result):
    by_source = {}
    tags = []
    for record in records:
        source_id = eid_int(record['target']['duct'].Id)
        by_source.setdefault(source_id, []).append(int(record['tag_id']))
        tags.append({'tag_id': int(record['tag_id']), 'source_id': source_id,
                     'type_id': eid_int(tag_type_id), 'text': record.get('actual_text'),
                     'head_ft': _audit_point(record.get('head')),
                     'has_leader': bool(record.get('leader_applied')),
                     'measured_family_head_clearance_verified': bool(record.get('head_clearance_verified')),
                     'layout_source': record.get('source'),
                     'identity_verified_after_commit': True})
    scoped_ids = set(eid_int(target['duct'].Id) for target in scoped_targets)
    targets = []
    for source_id, target in sorted(raw_targets.items()):
        entry = _pipe_source_audit(target['duct'])
        entry['reasons'] = sorted(str(reason) for reason in target.get('reasons', []))
        entry['event_points_ft'] = [_audit_point(point)
                                    for point in target.get('event_points', [])]
        entry['created_tag_ids'] = by_source.get(int(source_id), [])
        entry['existing_tag_ids'] = list(existing.get(int(source_id), []))
        if source_id not in density_targets:
            entry['status'] = 'redundant-routing-target-suppressed'
        elif source_id not in scoped_ids:
            entry['status'] = 'outside-selection'
        elif entry['created_tag_ids']:
            entry['status'] = 'created-source-type-verified'
        elif entry['existing_tag_ids']:
            entry['status'] = 'existing-source-type-verified'
        else:
            entry['status'] = 'missing-required-tag'
        targets.append(entry)
    return {
        'schema_version': 1, 'engine': 'pipe-autotag-1.5-review',
        'document': str(doc.Title), 'view': str(view.Name), 'view_id': eid_int(view.Id),
        'revit_version': str(doc.Application.VersionNumber), 'view_scale': int(view.Scale),
        'selected_tag_type': AUTOTAG_RUN_OPTIONS.get('event_tag_type') or {},
        'scope': 'selection' if SMART_SELECTION_ONLY else 'view',
        'summary': dict((key, value) for key, value in result.items() if key != 'message'),
        'targets': targets, 'tags': tags,
        'components': dict((key, value) for key, value in components.items()
                           if key in ('created', 'failed', 'skipped', 'unmapped',
                                      'skipped_existing', 'skipped_no_type', 'failures', 'by_category',
                                      'created_ids', 'created_records',
                                      'post_commit_rejected', 'runtime')),
        'failures': [{'source_id': int(source_id), 'reason': str(reason)}
                     for source_id, reason in failed],
        'limitations': [
            'Tag identity verifies source, family type, view and nonempty text; it does not certify label values.',
            'BOP and centerline meanings come from the selected tag family and model parameters.',
            'Leader lengths and collision footprints are planned geometry; final plotted readability needs Revit review.',
            'Direct component tags use their own placement path; they are not certified by the pipe event collision solver.',
        ],
    }


def _save_tag_run_audit(payload):
    path = script.get_data_file('robmep_autotag_pipe_' + uuid.uuid4().hex, 'json')
    with open(path, 'w') as stream:
        json.dump(payload, stream, indent=2, sort_keys=True, allow_nan=False)
    return path


def _finish_no_new_pipe_tags(message, raw_targets, targets, tag_type_id,
                            existing, run_started):
    components = _run_component_tags()
    ctext = component_summary(components)
    if ctext:
        message += '\n\n' + ctext
    result = {'discipline': 'pipe', 'created': 0, 'failed': 0,
              'required_targets': len(targets),
              'skipped_existing': len([source for source in targets if source in existing]),
              'component_created': components.get('created', 0),
              'component_failed': components.get('failed', 0),
              'message': message, 'runtime': time.time() - run_started}
    try:
        payload = _build_tag_run_audit(raw_targets, targets, list(targets.values()),
                                      [], tag_type_id, existing, components, [], result)
        path = _save_tag_run_audit(payload)
        result['audit_path'] = path
        result['message'] += '\n\nRun diagnostics: ' + path
    except Exception as ex:
        if _is_fatal_revit_error(ex):
            raise
        result['message'] += '\n\nDiagnostics could not be saved: ' + str(ex)
    if not globals().get('AUTOTAG_SUPPRESS_RESULT_DIALOG', False):
        forms.alert(result['message'], title='AutoTag Plumbing Smart V1')
    return result


def main():
    run_started = time.time()
    _telemetry_reset()
    phase_times = {}
    phase_mark = [run_started]

    def mark_phase(name):
        now = time.time()
        phase_times[name] = now - phase_mark[0]
        phase_mark[0] = now

    if not isinstance(view, DB.ViewPlan):
        forms.alert('AutoTag Plumbing currently runs in plan views only.', title='AutoTag Plumbing')
        return
    try:
        if view.IsTemplate:
            forms.alert('Open a normal project plan view first.', title='AutoTag Plumbing')
            return
    except Exception:
        pass

    if not _ask_smart_menu():
        return

    # Component-only profiles do not require a sample linear tag.
    if not AUTOTAG_ENABLED_REASONS:
        try:
            return _finish_no_new_pipe_tags(
                'No linear pipe event triggers are enabled.', {}, {}, None, {}, run_started)
        except Exception as ex:
            forms.alert('Direct component tagging stopped:\n\n{0}'.format(ex), title='ROBMEPTOOLS AutoTag')
            return

    # Fail early with a useful message instead of allowing Transaction.Start()
    # to throw later (e.g. read-only model, viewer state, or protected document).
    try:
        if doc.IsReadOnly:
            forms.alert(
                'This Revit document is read-only, so AutoTag Plumbing cannot create tags.',
                title='AutoTag Plumbing'
            )
            return
    except Exception:
        pass

    event_choice = AUTOTAG_RUN_OPTIONS.get('event_tag_type') or {}
    try:
        tag_type_id = DB.ElementId(System.Int64(int(event_choice.get('id'))))
    except Exception:
        forms.alert('Choose a valid BOP event tag type on the AutoTag Tag Types page.', title='AutoTag Plumbing')
        return
    orientation = DB.TagOrientation.Horizontal
    sample_rotation = None
    sample_tag = None

    mode = str(event_choice.get('mode', '')).lower()
    if mode not in ('native', 'fabrication'):
        forms.alert(
            'The selected BOP event tag type is not mapped to native pipe or MEP Fabrication pipework.',
            title='AutoTag Plumbing'
        )
        return

    mark_phase('setup')
    all_ducts = collect_mode_ductwork(mode)
    horizontal_ducts = [d for d in all_ducts if is_horizontal_straight_duct(d)]
    mark_phase('collect')
    if not horizontal_ducts:
        label = 'MEP Fabrication pipework' if mode == 'fabrication' else 'native Revit pipe'
        base = 'No straight horizontal {0} was found in this view.'.format(label)
        return _finish_no_new_pipe_tags(base, {}, {}, tag_type_id, {}, run_started)

    targets, event_counts = detect_targets(horizontal_ducts)
    branch_start_added = audit_branch_start_bop(horizontal_ducts, targets)
    direct_audit_added = audit_direct_two_port_events(horizontal_ducts, targets)
    if SMART_SELECTION_ONLY:
        selected_ids = set(eid_int(x) for x in uidoc.Selection.GetElementIds())
        targets = dict((did, target) for did, target in targets.items() if did in selected_ids)
    raw_targets = dict((did, {'duct': target['duct'],
                             'reasons': set(target.get('reasons', [])),
                             'event_points': list(target.get('event_points', []))})
                       for did, target in targets.items())
    fixture_tail_suppressed = suppress_fixture_tail_bop_targets(targets)
    event_counts['fixture_tail_suppressed'] = fixture_tail_suppressed
    human_turn_suppressed = suppress_redundant_human_turn_targets(targets)
    event_counts['human_turn_suppressed'] = human_turn_suppressed
    if mode == 'fabrication' and _FAB_STRAIGHT_FALLBACK_IDS:
        try:
            ids = sorted(list(_FAB_STRAIGHT_FALLBACK_IDS))
            output.print_md('**AutoTag v11 strict-straight recovery:** `{0}`'.format(', '.join(str(x) for x in ids[:20])))
        except Exception:
            pass
    mark_phase('detect')
    if not targets:
        base = 'No qualifying pipe changes were found for the enabled event triggers.'
        return _finish_no_new_pipe_tags(base, raw_targets, targets, tag_type_id, {}, run_started)

    # Skip only ducts already carrying THIS selected tag type. Other duct tags
    # may serve a different annotation purpose and should not suppress this tool.
    already_tagged = set()
    existing_tag_ids = {}
    for tag in DB.FilteredElementCollector(doc, view.Id).OfClass(DB.IndependentTag).WhereElementIsNotElementType():
        valid, _reason, source_ids = _tag_identity_check(tag, tag_type_id)
        if not valid:
            continue
        for source_id in source_ids:
            already_tagged.add(source_id)
            existing_tag_ids.setdefault(source_id, []).append(eid_int(tag.Id))

    skipped_existing = 0
    filtered_targets = []
    for did, target in targets.items():
        if did in already_tagged:
            skipped_existing += 1
        else:
            filtered_targets.append(target)

    if not filtered_targets:
        base = 'Every qualifying straight pipe is already tagged in this view.'
        return _finish_no_new_pipe_tags(
            base, raw_targets, targets, tag_type_id, existing_tag_ids, run_started)
    scoped_targets = list(targets.values())

    # Collision database is built before creating new tags.
    grid, dwg_info = build_obstacle_grid(all_ducts, [t['duct'] for t in filtered_targets])
    crop_rect = crop_rect_for_view(view)
    mark_phase('obstacles')

    created = 0
    no_leader_count = 0
    leader_count = 0
    emergency_layout_count = 0
    rescue_layout_count = 0
    bridge_layout_count = 0
    escape_layout_count = 0
    last_resort_layout_count = 0
    lane_placement_count = 0
    lane_stats = {'groups': 0, 'placements': 0, 'opposite': 0, 'emergency': 0, 'last': 0, 'rescue': 0, 'bridge': 0, 'escape': 0}
    repair_stats = {'considered': 0, 'repaired': 0, 'long_before': 0, 'cross_before': 0, 'angle_before': 0, 'dogleg_before': 0, 'to_straight': 0, 'to_no_leader': 0, 'unrepaired': 0}
    created_records = []
    failed = []
    layout_coordinator = LayoutCoordinator()

    tx = DB.Transaction(doc, 'AutoTag Plumbing Smart V1')
    try:
        tx.Start()
    except Exception as ex:
        forms.alert(
            'AutoTag Plumbing could not start a Revit transaction.\n\n{0}'.format(ex),
            title='AutoTag Plumbing'
        )
        return
    try:
        tag_size_cache, tag_size_fallback = build_tag_size_cache(
            filtered_targets, tag_type_id, orientation, sample_rotation, sample_tag
        )
        mark_phase('tag_metrics')

        # V6 optimized micro-cluster planner. Nearby mixed-orientation tags are coordinated
        # before final Revit tags are created; isolated tags keep the proven local
        # v5 solver. This is layout-only and never changes target detection.
        # Whole-floor/transitive grouping remains disabled; only direct local
        # drafting neighborhoods are solved together.
        lane_plan = {}
        lane_order = []
        lane_stats = {'groups': 0, 'placements': 0, 'opposite': 0, 'emergency': 0, 'last': 0, 'rescue': 0, 'bridge': 0, 'escape': 0}
        if SMART_GROUP_COORDINATION:
            lane_plan, lane_order, lane_stats = build_grouped_layout_plan(
                filtered_targets, grid, tag_size_cache, tag_size_fallback, crop_rect
            )
        mark_phase('lane_plan')

        # Keep the placement pass light. Earlier builds pre-generated thousands
        # of candidates per target just to estimate "constraint count", then did
        # the same work again for placement. Short pieces and multi-reason events
        # are a good cheap proxy for constrained geometry and avoid that duplicate
        # solver cost on large floors.
        def target_sort_key(t):
            line = duct_line(t['duct'])
            length = line.Length if line is not None else 999999.0
            reason_count = len(t.get('reasons', []))
            return (-reason_count, length, eid_int(t['duct'].Id))

        # Place coordinated groups in the same order used by the planner so the
        # live collision grid matches the planned solution. Remaining isolated
        # targets then use the normal constrained-first ordering.
        target_by_id = dict((eid_int(x['duct'].Id), x) for x in filtered_targets)
        planned_targets = [target_by_id[x] for x in lane_order if x in target_by_id]
        planned_ids = set(lane_order)
        remaining_targets = [x for x in filtered_targets if eid_int(x['duct'].Id) not in planned_ids]
        remaining_targets.sort(key=target_sort_key)
        filtered_targets = planned_targets + remaining_targets

        lane_placement_count = 0

        for target in filtered_targets:
            duct = target['duct']
            did = eid_int(duct.Id)
            tag = None
            try:
                tag_metrics = get_tag_metrics_cached(
                    tag_size_cache, tag_size_fallback, duct
                )
                planned_entry = lane_plan.get(did)
                if planned_entry is not None:
                    layout = planned_entry['layout']
                    # V8 live revalidation: micro-clusters are planned before any
                    # new tags exist. Recheck the chosen head against the live
                    # collision grid after earlier tags have reserved their
                    # safety-expanded footprints. If the preplan became crowded,
                    # cheaply re-solve only this duct instead of accepting overlap.
                    try:
                        _ignore = did if not bool(layout[4]) else None
                        _live_hard, _live_cad = grid.score_rect_components(
                            layout[3], ignore_source_id=_ignore
                        )
                    except Exception:
                        _live_hard = 0.0
                    if _live_hard > 0.0 or not _layout_is_safe(target, layout, grid, crop_rect):
                        _LAYOUT_TELEMETRY['v8_preplanned_replans'] += 1
                        planned_entry = None
                        layout = choose_layout(
                            target, grid, tag_metrics, crop_rect,
                            coordinator=layout_coordinator
                        )
                    else:
                        lane_placement_count += 1
                        if planned_entry.get('source') == 'emergency':
                            emergency_layout_count += 1
                        elif planned_entry.get('source') == 'last':
                            last_resort_layout_count += 1
                        elif planned_entry.get('source') == 'rescue':
                            rescue_layout_count += 1
                        elif planned_entry.get('source') == 'bridge':
                            bridge_layout_count += 1
                        elif planned_entry.get('source') == 'escape':
                            escape_layout_count += 1
                else:
                    layout = choose_layout(
                        target, grid, tag_metrics, crop_rect,
                        coordinator=layout_coordinator
                    )
                if layout is None:
                    failed.append((did, 'No usable tag layout candidate was found.'))
                    continue
                if not _layout_is_safe(target, layout, grid, crop_rect):
                    failed.append((did, 'No collision-safe local tag head/leader layout was found.'))
                    continue

                score, head, elbow, planned_rect, use_leader, anchor, attachment = layout
                if planned_entry is not None:
                    layout_source = planned_entry.get('source') or 'normal'
                else:
                    layout_source = _layout_source_from_score(score)
                if planned_entry is None:
                    if layout_source == 'last':
                        last_resort_layout_count += 1
                    elif layout_source == 'emergency':
                        emergency_layout_count += 1
                    elif layout_source == 'bridge':
                        bridge_layout_count += 1
                    elif layout_source == 'escape':
                        escape_layout_count += 1
                    elif layout_source == 'rescue':
                        rescue_layout_count += 1

                if use_leader:
                    try:
                        tag, ref = create_raw_tag(
                            duct, anchor, tag_type_id, orientation, True
                        )
                    except Exception as ex:
                        if _is_fatal_revit_error(ex):
                            raise
                        fallback = choose_layout(
                            target, grid, tag_metrics, crop_rect, allow_leader=False
                        )
                        if fallback is None or not _layout_is_safe(target, fallback, grid, crop_rect):
                            raise
                        _, head, _, planned_rect, _, anchor, _ = fallback
                        elbow = None
                        use_leader = False
                        tag, ref = create_raw_tag(
                            duct, anchor, tag_type_id, orientation, True
                        )
                else:
                    try:
                        tag, ref = create_raw_tag(
                            duct, anchor, tag_type_id, orientation, True
                        )
                        tag.TagHeadPosition = head
                        tag.HasLeader = False
                    except Exception as ex:
                        if _is_fatal_revit_error(ex):
                            raise
                        if tag is not None:
                            doc.Delete(tag.Id)
                            tag = None
                        tag, ref = create_raw_tag(
                            duct, head, tag_type_id, orientation, False
                        )

                # One head assignment is enough for leader tags. For no-leader
                # tags the first assignment above is retained if it already worked.
                if use_leader:
                    tag.TagHeadPosition = head
                else:
                    try:
                        tag.TagHeadPosition = head
                    except Exception:
                        pass

                if sample_rotation is not None and abs(float(sample_rotation)) > 1e-9:
                    try:
                        tag.RotationAngle = sample_rotation
                    except Exception:
                        pass

                leader_applied = False
                leader_mode = None
                final_head = head
                final_elbow = elbow
                final_attachment = attachment
                if use_leader:
                    leader_result = apply_leader(tag, ref, anchor, elbow)
                    if leader_result:
                        leader_applied = True
                        leader_mode = leader_result
                    else:
                        fallback = choose_layout(
                            target, grid, tag_metrics, crop_rect, allow_leader=False
                        )
                        if fallback is None or not _layout_is_safe(target, fallback, grid, crop_rect):
                            raise RuntimeError('Selected tag family would not accept the requested leader geometry.')
                        _, fallback_head, _, fallback_rect, _, fallback_anchor, _ = fallback
                        old_id = tag.Id
                        doc.Delete(old_id)
                        tag = None
                        try:
                            tag, ref = create_raw_tag(
                                duct, fallback_anchor, tag_type_id, orientation, True
                            )
                            tag.TagHeadPosition = fallback_head
                            tag.HasLeader = False
                        except Exception as ex:
                            if _is_fatal_revit_error(ex):
                                raise
                            if tag is not None:
                                doc.Delete(tag.Id)
                                tag = None
                            tag, ref = create_raw_tag(
                                duct, fallback_head, tag_type_id, orientation, False
                            )
                        if sample_rotation is not None and abs(float(sample_rotation)) > 1e-9:
                            try:
                                tag.RotationAngle = sample_rotation
                            except Exception:
                                pass
                        planned_rect = fallback_rect
                        final_head = fallback_head
                        final_elbow = None
                        final_attachment = None
                        use_leader = False

                if not use_leader:
                    tag.HasLeader = False
                    if tag.HasLeader:
                        raise RuntimeError('Tag family did not permit the planned leader removal.')
                tag_id = eid_int(tag.Id)
                _LAYOUT_TELEMETRY['v7_single_tx_tags'] += 1
                if leader_applied:
                    leader_count += 1
                else:
                    no_leader_count += 1
                record = {
                    'tag_id': tag_id,
                    'target': target,
                    'metrics': tag_metrics,
                    'head': final_head,
                    'rect': planned_rect,
                    'anchor': anchor,
                    'attachment': final_attachment,
                    'elbow': final_elbow,
                    'leader_mode': leader_mode,
                    'leader_applied': bool(leader_applied),
                    'source': layout_source,
                }
                _reserve_record_geometry(grid, record)
                created_records.append(record)
                layout_coordinator.register(target, final_head, planned_rect, anchor)
                created += 1
            except Exception as ex:
                # In the common path no per-tag SubTransaction is used. If Revit
                # itself enters failure handling, abort this batch so the outer
                # transaction can roll back cleanly. Ordinary per-tag exceptions
                # are isolated by deleting the partial tag and continuing.
                if _is_fatal_revit_error(ex):
                    raise
                if tag is not None:
                    try:
                        doc.Delete(tag.Id)
                    except Exception:
                        pass
                failed.append((did, str(ex)))
                output.print_md('**AutoTag Plumbing:** failed on pipe `{0}`: `{1}`'.format(did, ex))

        mark_phase('placement')

        # V3 cleanup only reconsiders objectively questionable leaders and can
        # simplify a dogleg into a straight leader or safe on-host tag.
        if SMART_ENABLE_REPAIR:
            repair_stats = repair_questionable_leaders(created_records, grid, crop_rect)
        mark_phase('repair')

        created_records, head_clearance_rejected = _verify_created_tag_head_clearance(
            created_records, grid, crop_rect)
        failed.extend(head_clearance_rejected)
        created = len(created_records)
        mark_phase('final_head_measurement')
        if created == 0:
            tx.RollBack()
        else:
            commit_status = tx.Commit()
            if commit_status != DB.TransactionStatus.Committed:
                raise RuntimeError('Pipe tag transaction did not commit: ' + str(commit_status))
    except Exception as ex:
        try:
            tx.RollBack()
        except Exception:
            pass
        forms.alert('AutoTag Plumbing stopped:\n\n{0}'.format(ex), title='AutoTag Plumbing')
        return

    attempted_created = created
    created_records, post_commit_rejected = _surviving_tag_records(created_records, tag_type_id)
    for source_id, reason, tag_id in post_commit_rejected:
        failed.append((source_id, 'Post-commit tag {0}: {1}'.format(tag_id, reason)))
    created = len(created_records)
    created_source_ids = set(eid_int(record['target']['duct'].Id) for record in created_records)
    missing_ids = sorted(eid_int(target['duct'].Id) for target in scoped_targets
                         if eid_int(target['duct'].Id) not in created_source_ids and
                         eid_int(target['duct'].Id) not in already_tagged)

    component_stats = {'created':0,'skipped':0,'failed':0,'runtime':0.0,'by_category':{}}
    component_error = None
    if _components_enabled():
        try:
            component_stats = _run_component_tags()
        except Exception as ex:
            if _is_fatal_revit_error(ex):
                raise
            component_error = str(ex)
            try: output.print_md('**AutoTag component tagging warning:** `{0}`'.format(ex))
            except Exception: pass

    import_count, cad_segments, cad_capped, cad_failed = dwg_info
    cap_note = ' (scan cap reached)' if cad_capped else ''
    total_runtime = time.time() - run_started
    # Cleanup may have changed leader state, so derive final counts from records.
    leader_count = len([x for x in created_records if x.get('leader_applied')])
    no_leader_count = len(created_records) - leader_count
    leader_lengths = [_record_leader_total_paper(x) for x in created_records if x.get('leader_applied')]
    max_leader_length = max(leader_lengths) if leader_lengths else 0.0
    leaders_over_055 = len([x for x in leader_lengths if x > 0.55])
    attached_leaders = len([x for x in created_records if str(x.get('leader_mode') or '').startswith('attached')])
    free_leaders = len([x for x in created_records if str(x.get('leader_mode') or '').startswith('free')])
    straight_leaders = len([x for x in created_records if str(x.get('leader_mode') or '').endswith('straight')])
    elbow_leaders = len([x for x in created_records if str(x.get('leader_mode') or '').endswith('elbow')])
    fab_fallback_count = len(_FAB_STRAIGHT_FALLBACK_IDS) if mode == 'fabrication' else 0
    failure_note = ''
    if failed:
        try:
            failure_note = '\nFirst failure: pipe {0} - {1}\n'.format(failed[0][0], failed[0][1])
        except Exception:
            pass
    mode_label = 'MEP Fabrication pipework' if mode == 'fabrication' else 'native Revit pipe'
    reason_counts = _telemetry_reason_target_counts()
    top_reasons = _telemetry_top_reasons(5)
    inline_ineligible_targets = reason_counts.get('inline_ineligible', 0)
    diag_lines = []
    labels = {
        'normal_head_blocked': 'normal tag-head blocked',
        'normal_leader_blocked': 'straight leader blocked',
        'normal_mep_cross_limit': 'MEP crossing above normal limit',
        'normal_leader_too_long': 'straight leader too long',
        'dogleg_head_blocked': 'dogleg tag-head blocked',
        'dogleg_leader_blocked': 'dogleg route blocked',
        'dogleg_mep_cross_limit': 'dogleg MEP crossing limit',
        'dogleg_too_long': 'dogleg too long',
        'normal_head_cad': 'tag head blocked by CAD',
        'normal_head_outside_crop': 'tag head outside crop',
        'no_usable_anchor': 'no usable leader anchor',
        'no_layout_base': 'no host layout base',
    }
    for reason, count in top_reasons:
        diag_lines.append('  {0}: {1}'.format(labels.get(reason, reason.replace('_', ' ')), count))
    if not diag_lines:
        diag_lines.append('  No dominant rejection recorded.')
    diag_text = '\n'.join(diag_lines)
    v5_perf_text = ('  Heads tested / clear: {0}/{1}\n'
                    '  Anchor routes tested: {2}\n'
                    '  Targets needing Stage B: {3}\n'
                    '  Stage A early-stops: {4}\n'
                    '  Reused-head fallbacks: {5}\n'
                    '  Safe-escape heads tested: {6}\n'
                    '  Emergency heads tested: {7}\n'
                    '  Emergency heads touching text: {8}\n'
                    '  Spatial-grid queries: {9}\n'
                    '  XYZ points materialized: {10}\n'
                    '  Single-transaction tags: {11}\n'
                    '  Collision-safe preplan re-solves: {12}').format(
                        _LAYOUT_TELEMETRY.get('v5_heads_tested', 0),
                        _LAYOUT_TELEMETRY.get('v5_clear_heads', 0),
                        _LAYOUT_TELEMETRY.get('v5_anchor_tests', 0),
                        len(_LAYOUT_TELEMETRY.get('v5_expanded_targets', set())),
                        _LAYOUT_TELEMETRY.get('v6_stage_a_early_stops', 0),
                        len(_LAYOUT_TELEMETRY.get('v6_reuse_used', set())),
                        _LAYOUT_TELEMETRY.get('v9_escape_head_tests', 0),
                        _LAYOUT_TELEMETRY.get('v6_emergency_head_tests', 0),
                        _LAYOUT_TELEMETRY.get('v9_emergency_text_blocked_heads', 0),
                        getattr(grid, 'query_count', 0),
                        _LAYOUT_TELEMETRY.get('v7_xyz_materialized', 0),
                        _LAYOUT_TELEMETRY.get('v7_single_tx_tags', 0),
                        _LAYOUT_TELEMETRY.get('v8_preplanned_replans', 0))

    msg = (
        'Engine: {0}\n'
        'Created {1} surviving source/type-verified pipe tag(s) on {2}.\n\n'
        'Final layout:\n'
        '  No leader / on-host: {3}\n'
        '  With leader: {4}\n'
        '    Straight: {5}\n'
        '    Dogleg/elbow: {6}\n'
        '  Leaders over 0.55" paper: {7}\n'
        '  Longest planned leader: {8:.2f}" paper\n\n'
        'Smart Pipe V1 work:\n'
        '  Micro-clusters: {9}\n'
        '  Cluster-planned tags: {10}\n'
        '  Stage-B placements: {11}\n'
        '  Reused-head fallback placements: {12}\n'
        '  Collision-safe escape placements: {13}\n'
        '  Collision-checked emergency placements: {14}\n'
        '  Optional cleanup considered/repaired: {15}/{16}\n'
        '  Doglegs simplified to straight: {17}\n'
        '  Leaders removed by cleanup: {18}\n\n'
        'Pipe V1 search diagnostics:\n'
        '  Unified pool empty: {19}\n'
        '  On-host geometry ineligible: {20}\n'
        '{21}\n'
        '{40}\n\n'
        'Human-density detection:\n'
        '  Already tagged / skipped: {22}\n'
        '  Failed: {23}\n'
        '  Turns: {24} | Elevation: {25} | Size: {26} | Shape: {27} | Endcaps: {28}\n'
        '  Redundant turn-only pairs condensed: {41}\n'
        '  Local plumbing-fixture tail BOP targets suppressed: {42}\n'
        '  Repeated local turn/branch BOP targets consolidated: {43}\n'
        '  Visible horizontal straights: {29}\n'
        '  Qualifying targets in view: {30}\n\n'
        'Runtime (seconds):\n'
        '  Setup/menu/tag mapping: {31:.1f}\n'
        '  Model collection: {32:.1f}\n'
        '  Detect + audit: {33:.1f}\n'
        '  Obstacles: {34:.1f}\n'
        '  Tag metrics: {35:.1f}\n'
        '  Micro planning: {36:.1f}\n'
        '  Placement: {37:.1f}\n'
        '  Cleanup: {38:.1f}\n'
        '  Total click-to-finish: {39:.1f}'
    ).format(
        SMART_ENGINE_LABEL, created, mode_label,
        no_leader_count, leader_count, straight_leaders, elbow_leaders,
        leaders_over_055, max_leader_length,
        lane_stats.get('groups', 0), lane_placement_count,
        rescue_layout_count, bridge_layout_count, escape_layout_count, emergency_layout_count,
        repair_stats.get('considered', 0), repair_stats.get('repaired', 0),
        repair_stats.get('to_straight', 0), repair_stats.get('to_no_leader', 0),
        len(_LAYOUT_TELEMETRY.get('normal_empty', set())), inline_ineligible_targets,
        diag_text,
        skipped_existing, len(failed),
        event_counts['turn'], event_counts['elevation'], event_counts['size'],
        event_counts['shape'], event_counts['endcap'],
        len(horizontal_ducts), len(targets),
        phase_times.get('setup', 0.0), phase_times.get('collect', 0.0),
        phase_times.get('detect', 0.0), phase_times.get('obstacles', 0.0),
        phase_times.get('tag_metrics', 0.0), phase_times.get('lane_plan', 0.0),
        phase_times.get('placement', 0.0), phase_times.get('repair', 0.0), total_runtime,
        v5_perf_text, event_counts.get('turn_condensed', 0),
        event_counts.get('fixture_tail_suppressed', 0),
        event_counts.get('human_turn_suppressed', 0)
    )
    if failed:
        try:
            msg += '\n\nFirst failure: pipe {0} - {1}'.format(failed[0][0], failed[0][1])
        except Exception:
            pass
    msg += ('\n\nPost-commit identity audit:\n'
            '  Tags created before commit: {0}\n'
            '  Missing or invalid after commit: {1}\n'
            '  Required pipe event tags still missing: {2}\n'
            '  Values remain controlled by the selected Revit tag family.').format(
                attempted_created, len(post_commit_rejected), len(missing_ids))
    msg += '\n  Actual family-head overlaps/unmeasurable heads rejected: {0}'.format(len(head_clearance_rejected))
    if component_error:
        msg += '\n\nComponent tagging stopped: ' + component_error
    if SMART_DEBUG_REPORT:
        try:
            output.print_md('**AutoTag Plumbing Smart V1 engine:** `{0}`'.format(SMART_ENGINE_LABEL))
            output.print_md('Branch-start BOP straights restored: `{0}`'.format(branch_start_added))
            output.print_md('Micro-clusters: `{0}` / planned: `{1}` / rescue: `{2}` / bridge: `{3}` / escape: `{4}` / emergency: `{5}`'.format(
                lane_stats.get('groups', 0), lane_placement_count, rescue_layout_count, bridge_layout_count, escape_layout_count, emergency_layout_count))
            output.print_md('Cleanup: considered `{0}`, repaired `{1}`, to straight `{2}`, no leader `{3}`'.format(
                repair_stats.get('considered', 0), repair_stats.get('repaired', 0),
                repair_stats.get('to_straight', 0), repair_stats.get('to_no_leader', 0)))
            output.print_md('Attached leaders: `{0}` / free fallback: `{1}`'.format(attached_leaders, free_leaders))
            output.print_md('DWGs: `{0}` / segments: `{1}` / failures: `{2}`'.format(import_count, cad_segments, cad_failed))
        except Exception:
            pass
    ctext = component_summary(component_stats)
    if ctext:
        msg += '\n\n' + ctext
    result = {
        'discipline': 'pipe',
        'created': created,
        'component_created': component_stats.get('created', 0),
        'component_failed': component_stats.get('failed', 0),
        'failed': len(failed),
        'skipped_existing': skipped_existing,
        'required_targets': len(scoped_targets),
        'raw_targets': len(raw_targets),
        'post_commit_rejected': len(post_commit_rejected),
        'head_clearance_rejected': len(head_clearance_rejected),
        'component_error': component_error,
        'missing_target_ids': missing_ids,
        'created_ids': [int(record['tag_id']) for record in created_records],
        'message': msg,
        'runtime': total_runtime,
    }
    try:
        audit = _build_tag_run_audit(raw_targets, targets, scoped_targets,
                                    created_records, tag_type_id, existing_tag_ids,
                                    component_stats, failed, result)
        audit_path = _save_tag_run_audit(audit)
        result['audit_path'] = audit_path
        msg += '\n\nRun diagnostics: ' + audit_path
        result['message'] = msg
        output.print_md('**AutoTag Pipe run diagnostics:** `{0}`'.format(audit_path))
    except Exception as ex:
        if _is_fatal_revit_error(ex):
            raise
        msg += '\n\nDiagnostics could not be saved: ' + str(ex)
        result['message'] = msg
    if not globals().get('AUTOTAG_SUPPRESS_RESULT_DIALOG', False):
        forms.alert(msg, title='AutoTag Plumbing Smart V1')
    return result


if __name__ == '__main__':
    main()
