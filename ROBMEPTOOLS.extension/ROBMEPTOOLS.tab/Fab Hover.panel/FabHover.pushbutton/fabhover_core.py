# -*- coding: utf-8 -*-
"""Heavy runtime for ROBMEPTOOLS Fab Hover. Loaded only for a fresh start."""

TITLE = "Fab Hover - Revit 2025"
BUILD_ID = "2026.10-ui-system-v7.2"

import clr
import System
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
clr.AddReference("System.Windows.Forms")

from Autodesk.Revit import DB
from Autodesk.Revit.UI import IExternalEventHandler, ExternalEvent, ExternalEventRequest
from System.Windows.Forms import Control
from pyrevit import forms

# -----------------------------------------------------------------------------
# SHARED SETTINGS
# -----------------------------------------------------------------------------
import os
import sys
BUNDLE_DIR = os.path.dirname(__file__)
if BUNDLE_DIR not in sys.path:
    sys.path.insert(0, BUNDLE_DIR)
from fabhover_settings import DEFAULTS as DISPLAY_DEFAULTS, SETTINGS_PATH


class HoverHandler(IExternalEventHandler):
    def __init__(self, db_module, mouse_control, system_module):
        self.DB = db_module
        self.MouseControl = mouse_control
        self.System = system_module
        self.window = None

        self.last_eid = None
        self.same_element_reads = 0

        # Prevent a backlog of ExternalEvent requests.
        self.pending = False

        # Build the supported-category filter once. It can be refreshed when
        # settings change, but never during normal mouse movement.
        self.filter = self._make_category_filter()

        # Cached normalized view axes. Right/Up/ViewDirection do not change while
        # the same view is active, so avoid normalizing them on every hover read.
        self.basis_doc_hash = None
        self.basis_view_id = None
        self.basis_right = None
        self.basis_up = None
        self.basis_forward = None

        # -------------------------
        # 2D cache
        # -------------------------
        self.cache_doc_hash = None
        self.cache_view_id = None

        # Each entry is:
        # (ElementId, min_u, min_v, max_u, max_v, width, height,
        #  center_u, center_v, area)
        #
        # IMPORTANT:
        # No Revit bounding-box calls happen during normal mouse movement.
        self.cache_2d = []

        # Numeric spatial index for 2D hover. Built only when the cache is
        # rebuilt; normal mouse reads inspect nearby candidates instead of
        # linearly scanning every cached MEP element.
        self.cache_grid = {}
        self.cache_large = []
        self.cache_grid_cell = 8.0

        self.cache_idle_reads = 0
        self.cache_miss_reads = 0

        # -------------------------
        # 3D ReferenceIntersector cache
        # -------------------------
        self.ri = None
        self.ri_doc_hash = None
        self.ri_view_id = None

        # Active UIView cache. Revit's open-view enumeration is relatively
        # expensive compared with the numeric hover hit-test, so reuse the
        # matching UIView until the active view changes.
        self.uiview = None
        self.uiview_doc_hash = None
        self.uiview_view_id = None

        # Short-lived view mapping cache. GetWindowRectangle/GetZoomCorners are
        # Revit UI API calls; reusing them for a few frames reduces API chatter
        # while keeping pan/zoom response visually immediate.
        self.map_doc_hash = None
        self.map_view_id = None
        self.map_tick = 0
        self.map_rect = None
        self.map_corners = None

    def GetName(self):
        return "Fab Hover Reader"

    def _eid_value(self, eid):
        try:
            return eid.Value
        except:
            try:
                return eid.IntegerValue
            except:
                return None

    def _doc_hash(self, doc):
        try:
            return doc.GetHashCode()
        except:
            return None

    def _make_category_filter(self):
        db = self.DB
        cats = self.System.Collections.Generic.List[db.BuiltInCategory]()

        # If the modeless window is already initialized, use only categories the
        # user has enabled. This shrinks both 2D collectors and 3D raycast work.
        names = None
        try:
            if self.window is not None and hasattr(self.window, "enabled_bic_names"):
                names = self.window.enabled_bic_names()
        except:
            names = None

        if not names:
            names = (
                "OST_FabricationDuctwork", "OST_FabricationPipework", "OST_FabricationContainment",
                "OST_DuctCurves", "OST_DuctFitting", "OST_DuctAccessory", "OST_FlexDuctCurves",
                "OST_DuctTerminal", "OST_MechanicalEquipment",
                "OST_PipeCurves", "OST_PipeFitting", "OST_PipeAccessory", "OST_FlexPipeCurves",
                "OST_PlumbingFixtures", "OST_Sprinklers", "OST_SpecialityEquipment",
            )

        for name in names:
            try:
                cats.Add(getattr(db.BuiltInCategory, name))
            except:
                pass

        # The enabled list should never be empty in normal use. If a user disables
        # every category, retain a valid all-MEP filter and let is_category_enabled
        # suppress the result rather than constructing an invalid empty filter.
        try:
            if cats.Count <= 0:
                for name in (
                    "OST_FabricationDuctwork", "OST_FabricationPipework",
                    "OST_DuctCurves", "OST_DuctFitting", "OST_DuctAccessory",
                    "OST_DuctTerminal", "OST_MechanicalEquipment",
                    "OST_PipeCurves", "OST_PipeFitting", "OST_PipeAccessory",
                    "OST_PlumbingFixtures", "OST_Sprinklers", "OST_SpecialityEquipment",
                ):
                    try:
                        cats.Add(getattr(db.BuiltInCategory, name))
                    except:
                        pass
        except:
            pass

        return db.ElementMulticategoryFilter(cats)

    def refresh_filter(self):
        """Refresh the category filter only after settings changes."""
        try:
            self.filter = self._make_category_filter()
        except:
            pass
        self._clear_view_caches()

    def _view_basis(self, view):
        try:
            doc_hash = self._doc_hash(view.Document)
            view_id = self._eid_value(view.Id)
            if (
                self.basis_right is not None
                and self.basis_doc_hash == doc_hash
                and self.basis_view_id == view_id
            ):
                return self.basis_right, self.basis_up, self.basis_forward

            right = view.RightDirection.Normalize()
            up = view.UpDirection.Normalize()
            forward = view.ViewDirection.Normalize()
            self.basis_doc_hash = doc_hash
            self.basis_view_id = view_id
            self.basis_right = right
            self.basis_up = up
            self.basis_forward = forward
            return right, up, forward
        except:
            self.basis_doc_hash = None
            self.basis_view_id = None
            self.basis_right = None
            self.basis_up = None
            self.basis_forward = None
            return None

    def _find_uiview(self, uidoc, view):
        doc_hash = self._doc_hash(uidoc.Document)
        view_id = self._eid_value(view.Id)

        if (
            self.uiview is not None
            and self.uiview_doc_hash == doc_hash
            and self.uiview_view_id == view_id
        ):
            return self.uiview

        try:
            for uv in uidoc.GetOpenUIViews():
                if uv.ViewId == view.Id:
                    self.uiview = uv
                    self.uiview_doc_hash = doc_hash
                    self.uiview_view_id = view_id
                    return uv
        except:
            pass

        self.uiview = None
        self.uiview_doc_hash = None
        self.uiview_view_id = None
        return None

    def _cursor_view_data(self, uiview, view):
        """
        Convert the current Windows cursor location to the active Revit
        view plane. This is the only view-mapping work needed per read.
        """
        try:
            doc_hash = self._doc_hash(view.Document)
            view_id = self._eid_value(view.Id)
            now = int(self.System.Environment.TickCount)
            reuse_map = (
                self.map_rect is not None
                and self.map_corners is not None
                and self.map_doc_hash == doc_hash
                and self.map_view_id == view_id
                and abs(now - int(self.map_tick)) < 70
            )
            if reuse_map:
                rect = self.map_rect
                corners = self.map_corners
            else:
                rect = uiview.GetWindowRectangle()
                corners = uiview.GetZoomCorners()
                self.map_doc_hash = doc_hash
                self.map_view_id = view_id
                self.map_tick = now
                self.map_rect = rect
                self.map_corners = corners
            mouse = self.MouseControl.MousePosition

            if (
                mouse.X < rect.Left
                or mouse.X > rect.Right
                or mouse.Y < rect.Top
                or mouse.Y > rect.Bottom
            ):
                return None

            sw = float(rect.Right - rect.Left)
            sh = float(rect.Bottom - rect.Top)

            if sw <= 1.0 or sh <= 1.0:
                return None

            sx = (
                float(mouse.X)
                - float(rect.Left)
            ) / sw

            sy = (
                float(mouse.Y)
                - float(rect.Top)
            ) / sh

            c0 = corners[0]
            c1 = corners[1]

            basis = self._view_basis(view)
            if basis is None:
                return None
            right, up, forward = basis

            span = c1 - c0

            model_w = span.DotProduct(right)
            model_h = span.DotProduct(up)

            plane_point = (
                c0
                + right.Multiply(model_w * sx)
                + up.Multiply(model_h * (1.0 - sy))
            )

            cursor_u = plane_point.DotProduct(right)
            cursor_v = plane_point.DotProduct(up)

            upp_x = abs(model_w) / sw
            upp_y = abs(model_h) / sh

            units_per_pixel = max(
                upp_x,
                upp_y,
                1e-9
            )

            return (
                right,
                up,
                forward,
                plane_point,
                cursor_u,
                cursor_v,
                units_per_pixel
            )

        except:
            # A UIView can become stale if Revit closes/reopens a view. Drop the
            # cached handle so the next read reacquires the active UIView.
            self.uiview = None
            self.uiview_doc_hash = None
            self.uiview_view_id = None
            self.map_rect = None
            self.map_corners = None
            self.map_doc_hash = None
            self.map_view_id = None
            return None

    def _projected_bbox(self, element, view, right, up):
        """
        Project a Revit bounding box into view Right/Up coordinates.
        Called only while rebuilding the 2D cache.
        """
        try:
            bb = element.get_BoundingBox(view)
        except:
            bb = None

        if bb is None:
            return None

        try:
            minx = bb.Min.X
            miny = bb.Min.Y
            minz = bb.Min.Z
            maxx = bb.Max.X
            maxy = bb.Max.Y
            maxz = bb.Max.Z

            pts = (
                self.DB.XYZ(minx, miny, minz),
                self.DB.XYZ(maxx, miny, minz),
                self.DB.XYZ(minx, maxy, minz),
                self.DB.XYZ(maxx, maxy, minz),
                self.DB.XYZ(minx, miny, maxz),
                self.DB.XYZ(maxx, miny, maxz),
                self.DB.XYZ(minx, maxy, maxz),
                self.DB.XYZ(maxx, maxy, maxz)
            )

            min_u = None
            min_v = None
            max_u = None
            max_v = None

            for p in pts:
                u = p.DotProduct(right)
                v = p.DotProduct(up)

                if min_u is None:
                    min_u = max_u = u
                    min_v = max_v = v
                else:
                    if u < min_u:
                        min_u = u
                    if u > max_u:
                        max_u = u
                    if v < min_v:
                        min_v = v
                    if v > max_v:
                        max_v = v

            if min_u is None:
                return None

            return (
                min_u,
                min_v,
                max_u,
                max_v
            )

        except:
            return None

    def _clear_view_caches(self):
        self.cache_doc_hash = None
        self.cache_view_id = None
        self.cache_2d = []
        self.cache_grid = {}
        self.cache_large = []
        self.cache_grid_cell = 8.0
        self.cache_idle_reads = 0
        self.cache_miss_reads = 0

        # ReferenceIntersector implements IDisposable. Dispose old native state
        # whenever its view/filter cache is invalidated instead of waiting for GC.
        try:
            if self.ri is not None:
                self.ri.Dispose()
        except:
            pass
        self.ri = None
        self.ri_doc_hash = None
        self.ri_view_id = None

        self.uiview = None
        self.uiview_doc_hash = None
        self.uiview_view_id = None
        self.map_rect = None
        self.map_corners = None
        self.map_doc_hash = None
        self.map_view_id = None
        self.map_tick = 0

        self.basis_doc_hash = None
        self.basis_view_id = None
        self.basis_right = None
        self.basis_up = None
        self.basis_forward = None

    def _rebuild_2d_cache(self, doc, view, right, up):
        """
        Expensive work happens HERE, not while the mouse is moving.

        We store projected numeric rectangles so normal 2D hover reads
        are just Python number comparisons.
        """
        entries = []

        try:
            collector = (
                self.DB.FilteredElementCollector(
                    doc,
                    view.Id
                )
                .WhereElementIsNotElementType()
                .WherePasses(self.filter)
            )
        except:
            collector = None

        if collector is None:
            # Never fall back to a whole-document collector from a hover read.
            # If a view does not support a view-scoped collector, an empty hover
            # is safer than unexpectedly indexing a large project on the UI thread.
            collector = []

        for el in collector:
            try:
                # The filter normally already contains only enabled categories.
                # Keep this guard for the all-categories-disabled fallback and for
                # any stale filter during a settings handoff.
                try:
                    if self.window is not None and not self.window.is_category_enabled(el):
                        continue
                except:
                    pass

                box = self._projected_bbox(
                    el,
                    view,
                    right,
                    up
                )

                if box is None:
                    continue

                min_u, min_v, max_u, max_v = box

                width = max(
                    max_u - min_u,
                    1e-6
                )

                height = max(
                    max_v - min_v,
                    1e-6
                )

                area = width * height

                entries.append(
                    (
                        el.Id,
                        min_u,
                        min_v,
                        max_u,
                        max_v,
                        width,
                        height,
                        (min_u + max_u) * 0.5,
                        (min_v + max_v) * 0.5,
                        area
                    )
                )

            except:
                pass

        self.cache_2d = entries
        self._build_2d_spatial_index()
        self.cache_doc_hash = self._doc_hash(doc)
        self.cache_view_id = self._eid_value(view.Id)
        self.cache_idle_reads = 0
        self.cache_miss_reads = 0

    def _build_2d_spatial_index(self):
        self.cache_grid = {}
        self.cache_large = []

        if not self.cache_2d:
            self.cache_grid_cell = 8.0
            return

        # Adapt the cell size to the typical visible MEP object. A minimum cell
        # keeps tiny terminals from exploding the grid; a maximum keeps long
        # mains from making candidate buckets too broad.
        spans = []
        try:
            for entry in self.cache_2d:
                spans.append(max(entry[5], entry[6]))
            spans.sort()
            median = spans[len(spans) // 2] if spans else 2.0
            self.cache_grid_cell = max(2.0, min(20.0, median * 4.0))
        except:
            self.cache_grid_cell = 8.0

        cell = max(self.cache_grid_cell, 0.1)

        for idx, entry in enumerate(self.cache_2d):
            try:
                min_u, min_v, max_u, max_v = entry[1], entry[2], entry[3], entry[4]
                ix0 = int(min_u // cell)
                iy0 = int(min_v // cell)
                ix1 = int(max_u // cell)
                iy1 = int(max_v // cell)
                nx = ix1 - ix0 + 1
                ny = iy1 - iy0 + 1

                # Exceptionally large elements are cheaper to test separately
                # than to duplicate into hundreds of buckets.
                if nx <= 0 or ny <= 0 or (nx * ny) > 256:
                    self.cache_large.append(idx)
                    continue

                for ix in range(ix0, ix1 + 1):
                    for iy in range(iy0, iy1 + 1):
                        key = (ix, iy)
                        bucket = self.cache_grid.get(key)
                        if bucket is None:
                            self.cache_grid[key] = [idx]
                        else:
                            bucket.append(idx)
            except:
                self.cache_large.append(idx)

    def _candidate_2d_indices(self, cursor_u, cursor_v, tol):
        if not self.cache_grid:
            return range(len(self.cache_2d))

        cell = max(self.cache_grid_cell, 0.1)
        ix0 = int((cursor_u - tol) // cell)
        iy0 = int((cursor_v - tol) // cell)
        ix1 = int((cursor_u + tol) // cell)
        iy1 = int((cursor_v + tol) // cell)

        found = set()
        try:
            for ix in range(ix0, ix1 + 1):
                for iy in range(iy0, iy1 + 1):
                    for idx in self.cache_grid.get((ix, iy), []):
                        found.add(idx)
            for idx in self.cache_large:
                found.add(idx)
            return list(found)
        except:
            return range(len(self.cache_2d))

    def _ensure_2d_cache(
        self,
        doc,
        view,
        right,
        up,
        mouse_is_moving
    ):
        doc_hash = self._doc_hash(doc)
        view_id = self._eid_value(view.Id)

        changed_view = (
            self.cache_doc_hash != doc_hash
            or self.cache_view_id != view_id
        )

        if changed_view or not self.cache_2d:
            self._rebuild_2d_cache(
                doc,
                view,
                right,
                up
            )
            return

        # Do not rebuild a large model cache while the user is moving
        # the mouse. Refresh only during idle hover time.
        if mouse_is_moving:
            self.cache_idle_reads = 0
            return

        self.cache_idle_reads += 1

        # Periodic safety refresh only. Newly-created/moved items are handled by
        # the faster miss-based refresh below, so don't rebuild a large view cache
        # every few seconds when nothing changed.
        if self.cache_idle_reads >= 36:
            self._rebuild_2d_cache(
                doc,
                view,
                right,
                up
            )

    def _find_2d_element(
        self,
        doc,
        view,
        cursor_data,
        mouse_is_moving
    ):
        (
            right,
            up,
            forward,
            plane_point,
            cursor_u,
            cursor_v,
            units_per_pixel
        ) = cursor_data

        self._ensure_2d_cache(
            doc,
            view,
            right,
            up,
            mouse_is_moving
        )

        # Small enough to avoid sticky selection, large enough that
        # thin round duct is still easy to acquire.
        tol = units_per_pixel * 6.0

        best_id = None
        best_score = None

        # Pure numeric loop — no Revit API geometry calls here. The spatial
        # index normally reduces this to only a handful of nearby candidates.
        for entry_idx in self._candidate_2d_indices(cursor_u, cursor_v, tol):
            entry = self.cache_2d[entry_idx]
            (
                eid,
                min_u,
                min_v,
                max_u,
                max_v,
                cached_width,
                cached_height,
                center_u,
                center_v,
                area
            ) = entry

            if (
                cursor_u < min_u - tol
                or cursor_u > max_u + tol
                or cursor_v < min_v - tol
                or cursor_v > max_v + tol
            ):
                continue

            width = max(cached_width, tol)
            height = max(cached_height, tol)

            du = (
                cursor_u - center_u
            ) / width

            dv = (
                cursor_v - center_v
            ) / height

            # Prefer the box the cursor is actually inside.
            inside = (
                cursor_u >= min_u
                and cursor_u <= max_u
                and cursor_v >= min_v
                and cursor_v <= max_v
            )

            score = (
                du * du
                + dv * dv
                + area * 1e-7
            )

            if not inside:
                score += 0.35

            if (
                best_score is None
                or score < best_score
            ):
                best_score = score
                best_id = eid

        if best_id is not None:
            try:
                found_element = doc.GetElement(best_id)
            except:
                found_element = None

            if found_element is not None:
                self.cache_miss_reads = 0
                return found_element

            # Deleted elements can leave a stale cached id. Treat that as a miss
            # so the cache self-heals instead of repeatedly selecting nothing.
            if not mouse_is_moving:
                self.cache_miss_reads += 1
            return None

        # If the cursor is stationary over something newly created
        # or changed, allow a faster cache refresh after a few misses.
        if not mouse_is_moving:
            self.cache_miss_reads += 1

            if self.cache_miss_reads >= 3:
                self._rebuild_2d_cache(
                    doc,
                    view,
                    right,
                    up
                )

                # Retry once against the refreshed numeric cache.
                self.cache_miss_reads = 0

                for entry_idx in self._candidate_2d_indices(cursor_u, cursor_v, tol):
                    entry = self.cache_2d[entry_idx]
                    eid = entry[0]
                    min_u, min_v, max_u, max_v = entry[1], entry[2], entry[3], entry[4]

                    if (
                        cursor_u >= min_u - tol
                        and cursor_u <= max_u + tol
                        and cursor_v >= min_v - tol
                        and cursor_v <= max_v + tol
                    ):
                        try:
                            return doc.GetElement(eid)
                        except:
                            pass

        return None

    def _get_reference_intersector(self, doc, view):
        """
        Reuse the ReferenceIntersector instead of rebuilding it on
        every 3D mouse read.
        """
        doc_hash = self._doc_hash(doc)
        view_id = self._eid_value(view.Id)

        if (
            self.ri is not None
            and self.ri_doc_hash == doc_hash
            and self.ri_view_id == view_id
        ):
            return self.ri

        try:
            try:
                if self.ri is not None:
                    self.ri.Dispose()
            except:
                pass
            self.ri = None
            ri = self.DB.ReferenceIntersector(
                self.filter,
                self.DB.FindReferenceTarget.Element,
                view
            )

            ri.FindReferencesInRevitLinks = False

            self.ri = ri
            self.ri_doc_hash = doc_hash
            self.ri_view_id = view_id

            return ri

        except:
            self.ri = None
            return None

    def Execute(self, app):
        try:
            w = self.window

            if w is None:
                return
            try:
                if not w._runtime_active():
                    return
            except:
                if not bool(getattr(w, "is_active", True)):
                    return

            db = self.DB
            live_uidoc = app.ActiveUIDocument

            if live_uidoc is None:
                w.set_category("No active document")
                w.set_info("")
                return

            doc = live_uidoc.Document
            view = live_uidoc.ActiveView

            uiview = self._find_uiview(
                live_uidoc,
                view
            )

            if uiview is None:
                return

            cursor_data = self._cursor_view_data(
                uiview,
                view
            )

            if cursor_data is None:
                # Cursor is outside the active Revit view. Hide immediately so the
                # hover card never lingers over other Revit/UI controls.
                if self.last_eid is not None:
                    self.last_eid = None
                    self.same_element_reads = 0
                try:
                    w.no_target(immediate=True)
                except:
                    pass
                return

            element = None

            # ==================================================
            # 3D — precise raycast
            # ==================================================
            if isinstance(view, db.View3D):

                if view.IsPerspective:
                    try:
                        w.no_target(immediate=True)
                    except:
                        pass
                    return

                (
                    right,
                    up,
                    forward,
                    plane_point,
                    cursor_u,
                    cursor_v,
                    units_per_pixel
                ) = cursor_data

                ri = self._get_reference_intersector(
                    doc,
                    view
                )

                if ri is not None:
                    origin = (
                        plane_point
                        - forward.Multiply(100000.0)
                    )

                    hit = ri.FindNearest(
                        origin,
                        forward
                    )

                    if hit is not None:
                        try:
                            ref = hit.GetReference()

                            element = doc.GetElement(
                                ref.ElementId
                            )
                        except:
                            element = None

            # ==================================================
            # 2D — cached projected bounds
            # ==================================================
            else:
                element = self._find_2d_element(
                    doc,
                    view,
                    cursor_data,
                    bool(
                        getattr(
                            w,
                            "mouse_is_moving",
                            False
                        )
                    )
                )

            if element is not None:
                try:
                    if hasattr(w, "is_category_enabled") and not w.is_category_enabled(element):
                        element = None
                except:
                    pass

            if element is None:
                if self.last_eid is not None:
                    self.last_eid = None
                    self.same_element_reads = 0
                try:
                    w.no_target(immediate=False)
                except:
                    pass
                return

            eid = self._eid_value(
                element.Id
            )

            if eid != self.last_eid:
                self.last_eid = eid
                self.same_element_reads = 0
                w.show_element(element)

            else:
                # Refresh the same hovered element occasionally so parameter
                # changes show up without forcing heavy reads every tick.
                self.same_element_reads += 1

                if (
                    not getattr(
                        w,
                        "mouse_is_moving",
                        False
                    )
                    and
                    self.same_element_reads >= 3
                ):
                    self.same_element_reads = 0
                    w.show_element(element)

        except Exception as ex:
            try:
                if self.window is not None:
                    self.window.set_category(
                        "Hover error"
                    )
                    self.window.set_info(
                        str(ex)
                    )
            except:
                pass

        finally:
            # Let the UI timer request the next read.
            self.pending = False


class FabHover(forms.WPFWindow):
    def __init__(self, db_module, mouse_control, system_module):
        xaml=r"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
 xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
 Title="Fab Hover - Revit 2025"
 SizeToContent="WidthAndHeight"
 WindowStyle="None"
 ResizeMode="NoResize"
 ShowInTaskbar="False"
 ShowActivated="False"
 Focusable="False"
 IsHitTestVisible="False"
 AllowsTransparency="True"
 Background="Transparent"
 Topmost="True"
 UseLayoutRounding="True"
 WindowStartupLocation="Manual">

 <Border Name="PopupBorder"
         Background="#F20A1725"
         BorderBrush="#FF168CF3"
         BorderThickness="1"
         CornerRadius="8"
         MaxWidth="270"
         Padding="0"
         IsHitTestVisible="False">
  <Grid IsHitTestVisible="False">
   <Grid.ColumnDefinitions><ColumnDefinition Width="4"/><ColumnDefinition Width="*"/></Grid.ColumnDefinitions>
   <Border Name="AccentBar" Grid.Column="0" Background="#FF168CF3" CornerRadius="7,0,0,7"/>
   <StackPanel Grid.Column="1" Margin="8,7,9,8">
    <StackPanel Name="HeaderPanel">
     <Grid>
      <Grid.ColumnDefinitions><ColumnDefinition Width="Auto"/><ColumnDefinition Width="*"/></Grid.ColumnDefinitions>
      <Border Name="HeaderIconTile" Width="25" Height="25" Background="#FF143B5D" BorderBrush="#FF2C6F9E" BorderThickness="1" CornerRadius="4" Margin="0,0,7,0">
       <TextBlock Name="HeaderIcon" Text="M" Foreground="#FFD8EEFF" FontWeight="SemiBold" HorizontalAlignment="Center" VerticalAlignment="Center"/>
      </Border>
      <StackPanel Grid.Column="1" VerticalAlignment="Center">
       <TextBlock Name="HeaderTitle" Text="MEP Element" Foreground="#FFF6FAFD" FontFamily="Segoe UI" FontSize="11.5" FontWeight="SemiBold" TextTrimming="CharacterEllipsis"/>
       <TextBlock Name="HeaderSubtitle" Text="Fab Hover" Foreground="#FF55B8F4" FontFamily="Segoe UI" FontSize="8.7" TextTrimming="CharacterEllipsis"/>
      </StackPanel>
     </Grid>
     <Border Name="HeaderDivider" Height="1" Background="#FF25425B" Margin="0,6,0,5"/>
    </StackPanel>
    <TextBlock Name="InfoText"
               Text="Hover over MEP"
               Foreground="#FFEAF3F9"
               FontFamily="Segoe UI"
               FontSize="10.5"
               LineHeight="14"
               TextWrapping="Wrap"
               IsHitTestVisible="False"/>
   </StackPanel>
  </Grid>
 </Border>
</Window>"""
        forms.WPFWindow.__init__(self,xaml,literal_string=True)

        self.build_id = BUILD_ID
        self.is_active = True
        self._runtime_was_active = True
        self._is_closed = False
        try:
            self.Tag = True
            domain = system_module.AppDomain.CurrentDomain
            domain.SetData("ROBMEPTOOLS.FabHover.Window", self)
            domain.SetData("ROBMEPTOOLS.FabHover.Active", True)
        except:
            pass
        self.MouseControl = mouse_control
        self.System = system_module
        self.handler = HoverHandler(db_module, mouse_control, system_module)
        self.handler.window = self
        self.ext_event = ExternalEvent.Create(self.handler)

        # Copy settings state onto the modeless window. pyRevit can tear down a
        # script module after execution; keeping these values on self makes the
        # long-lived hover window independent of module globals.
        self._settings_defaults = dict(DISPLAY_DEFAULTS)
        self._settings_path = SETTINGS_PATH
        self._os = os
        self.display_settings = self._load_display_settings_runtime()
        self.display_settings_stamp = self._settings_stamp_runtime()
        self._last_settings_check_tick = 0

        # Cache BuiltInParameter enum resolution. Repeated getattr() calls are small
        # individually but add up when rapidly scanning many MEP elements.
        self._bip_enum_cache = {}

        # Per-element parameter text cache. Cleared each time the hovered element
        # changes/refreshed. This keeps the expansive optional display inexpensive.
        self._parameter_cache = {}

        # Cache category ids once. Keep the sets explicit so field extraction can
        # stay branch-light while hovering.
        def _bic_id(name):
            try:
                return int(getattr(db_module.BuiltInCategory, name))
            except:
                return None

        self._category_ids = {}
        for _name in (
            "OST_FabricationDuctwork", "OST_FabricationPipework", "OST_FabricationContainment",
            "OST_DuctCurves", "OST_DuctFitting", "OST_DuctAccessory", "OST_FlexDuctCurves",
            "OST_DuctTerminal", "OST_MechanicalEquipment",
            "OST_PipeCurves", "OST_PipeFitting", "OST_PipeAccessory", "OST_FlexPipeCurves",
            "OST_PlumbingFixtures", "OST_Sprinklers", "OST_SpecialityEquipment",
        ):
            _value = _bic_id(_name)
            if _value is not None:
                self._category_ids[_name] = _value

        self._fab_cat_ids = set(v for k, v in self._category_ids.items() if k in (
            "OST_FabricationDuctwork", "OST_FabricationPipework", "OST_FabricationContainment"))
        self._duct_cat_ids = set(v for k, v in self._category_ids.items() if k in (
            "OST_DuctCurves", "OST_DuctFitting", "OST_DuctAccessory", "OST_FlexDuctCurves"))
        self._pipe_cat_ids = set(v for k, v in self._category_ids.items() if k in (
            "OST_PipeCurves", "OST_PipeFitting", "OST_PipeAccessory", "OST_FlexPipeCurves"))
        self._air_terminal_cat_id = self._category_ids.get("OST_DuctTerminal")
        self._mechanical_equipment_cat_id = self._category_ids.get("OST_MechanicalEquipment")
        self._plumbing_fixture_cat_id = self._category_ids.get("OST_PlumbingFixtures")
        self._sprinkler_cat_id = self._category_ids.get("OST_Sprinklers")
        self._specialty_equipment_cat_id = self._category_ids.get("OST_SpecialityEquipment")
        self._equipment_cat_ids = set(v for v in (
            self._mechanical_equipment_cat_id, self._plumbing_fixture_cat_id,
            self._sprinkler_cat_id, self._specialty_equipment_cat_id
        ) if v is not None)

        # Precompute category -> setting lookups. The old build rebuilt this dict
        # on every hit-test result.
        self._category_setting_by_id = {}
        self._category_bic_by_setting = {}
        for _bic_name, _setting_key in (
            ("OST_FabricationDuctwork", "category_fab_ductwork"),
            ("OST_FabricationPipework", "category_fab_pipework"),
            ("OST_FabricationContainment", "category_fab_containment"),
            ("OST_DuctCurves", "category_ducts"),
            ("OST_DuctFitting", "category_duct_fittings"),
            ("OST_DuctAccessory", "category_duct_accessories"),
            ("OST_FlexDuctCurves", "category_flex_ducts"),
            ("OST_DuctTerminal", "category_air_terminals"),
            ("OST_PipeCurves", "category_pipes"),
            ("OST_PipeFitting", "category_pipe_fittings"),
            ("OST_PipeAccessory", "category_pipe_accessories"),
            ("OST_FlexPipeCurves", "category_flex_pipes"),
            ("OST_PlumbingFixtures", "category_plumbing_fixtures"),
            ("OST_Sprinklers", "category_sprinklers"),
            ("OST_MechanicalEquipment", "category_mechanical_equipment"),
            ("OST_SpecialityEquipment", "category_specialty_equipment"),
        ):
            _cat_value = self._category_ids.get(_bic_name)
            if _cat_value is not None:
                self._category_setting_by_id[_cat_value] = _setting_key
                self._category_bic_by_setting[_setting_key] = _bic_name

        from System.Windows.Threading import DispatcherTimer
        from System import TimeSpan
        from System.Windows import Point, PresentationSource

        self.Point = Point
        self.PresentationSource = PresentationSource
        self._screen_transform = None
        self._screen_transform_tick = 0

        # Smooth visual tracking is independent from Revit API reads. The default
        # is intentionally below 60fps to leave headroom for Revit's own UI thread.
        self.move_timer = DispatcherTimer()
        self.move_timer.Interval = TimeSpan.FromMilliseconds(max(14, int(self._value("hover_move_interval_ms") or 20)))
        self.move_timer.Tick += self.move_tick
        self.move_timer.Start()

        # Revit API reads are throttled independently. ExternalEvent.IsPending and
        # handler.pending guarantee that a slow Revit frame never creates a backlog.
        self.read_timer = DispatcherTimer()
        self.read_timer.Interval = TimeSpan.FromMilliseconds(max(28, int(self._value("hover_read_interval_ms") or 35)))
        self.read_timer.Tick += self.read_tick
        self.read_timer.Start()

        self.last_mouse_x = None
        self.last_mouse_y = None

        self.last_window_mouse_x = None
        self.last_window_mouse_y = None

        self.force_reads = 0
        self.mouse_is_moving = False
        self._popup_visible = False
        self._no_target_since_tick = None
        self._last_target_tick = 0
        self._idle_refresh_accum_ms = 0
        self._apply_popup_appearance()
        # The hover card should not sit on screen until a readable MEP element is hit.
        try:
            self.Opacity = 0.0
        except:
            pass

        # Now that settings/category maps exist, reduce collectors and 3D raycasts
        # to only the categories the user actually enabled.
        try:
            self.handler.refresh_filter()
        except:
            pass

        self.Closed += self.closed

    def set_info(self, text):
        try:
            if self.InfoText.Text != text:
                self.InfoText.Text = text
        except:
            pass

    def set_category(self, text):
        try:
            if self.HeaderSubtitle.Text != str(text):
                self.HeaderSubtitle.Text = str(text)
        except:
            pass

    def _brush(self, value):
        try:
            from System.Windows.Media import BrushConverter
            return BrushConverter().ConvertFromString(str(value))
        except:
            return None

    def _apply_popup_appearance(self):
        try:
            from System.Windows import CornerRadius, Thickness, Visibility
            theme = str(self._value("popup_theme") or "Navy")
            accent = str(self._value("popup_accent") or "#168CF3")
            opacity = max(0.55, min(1.0, float(self._value("popup_opacity") or 94) / 100.0))
            radius = max(0.0, min(18.0, float(self._value("popup_corner_radius") or 8.0)))
            text_size = max(8.5, min(16.0, float(self._value("popup_text_size") or 10.5)))
            width = max(190.0, min(420.0, float(self._value("popup_width") or 270)))

            if theme == "Light":
                bg, title, text, sub, divider = "#FFF6F8FA", "#FF102335", "#FF20384A", "#FF2875A7", "#FFD0DBE3"
            elif theme == "Graphite":
                bg, title, text, sub, divider = "#FF171C22", "#FFF4F7FA", "#FFE4EBF0", "#FF9DB1C0", "#FF354653"
            else:
                bg, title, text, sub, divider = "#FF0A1725", "#FFF6FAFD", "#FFEAF3F9", accent, "#FF25425B"

            self.PopupBorder.Background = self._brush(bg)
            self.PopupBorder.BorderBrush = self._brush(accent)
            self.PopupBorder.BorderThickness = Thickness(1.0)
            self.PopupBorder.CornerRadius = CornerRadius(radius)
            self.PopupBorder.MaxWidth = width
            self.PopupBorder.Opacity = opacity
            self.AccentBar.Background = self._brush(accent)
            self.HeaderTitle.Foreground = self._brush(title)
            self.HeaderSubtitle.Foreground = self._brush(sub)
            self.HeaderDivider.Background = self._brush(divider)
            self.InfoText.Foreground = self._brush(text)
            self.InfoText.FontSize = text_size
            self.InfoText.LineHeight = text_size * 1.30
            self.HeaderTitle.FontSize = text_size + 1.0
            self.HeaderSubtitle.FontSize = max(8.0, text_size - 1.5)
            self.HeaderPanel.Visibility = Visibility.Visible if self._setting("popup_show_header") else Visibility.Collapsed
            self.HeaderSubtitle.Visibility = Visibility.Visible if self._setting("popup_show_subtitle") else Visibility.Collapsed
            self.HeaderIconTile.Visibility = Visibility.Visible if self._setting("popup_show_icon") else Visibility.Collapsed
            self.AccentBar.Visibility = Visibility.Visible if self._setting("popup_show_accent_bar") else Visibility.Collapsed
        except:
            pass

    def _category_heading(self, el, cat_id):
        title = "MEP Element"
        subtitle = "Revit MEP"
        icon = "M"
        ids = self._category_ids
        if cat_id == ids.get("OST_FabricationDuctwork"):
            title, subtitle, icon = "Fabrication Duct", "Ducts (Fabrication)", "D"
        elif cat_id == ids.get("OST_FabricationPipework"):
            title, subtitle, icon = "Fabrication Pipe", "Pipes (Fabrication)", "P"
        elif cat_id == ids.get("OST_FabricationContainment"):
            title, subtitle, icon = "Fabrication Containment", "Containment (Fabrication)", "C"
        elif cat_id == ids.get("OST_DuctCurves"):
            title, subtitle, icon = "Duct", "HVAC Ductwork", "D"
        elif cat_id == ids.get("OST_DuctFitting"):
            title, subtitle, icon = "Duct Fitting", "HVAC Ductwork", "D"
        elif cat_id == ids.get("OST_DuctAccessory"):
            title, subtitle, icon = "Duct Accessory", "HVAC Ductwork", "D"
        elif cat_id == ids.get("OST_FlexDuctCurves"):
            title, subtitle, icon = "Flex Duct", "HVAC Ductwork", "D"
        elif cat_id == ids.get("OST_PipeCurves"):
            title, subtitle, icon = "Pipe", "Plumbing / Piping", "P"
        elif cat_id == ids.get("OST_PipeFitting"):
            title, subtitle, icon = "Pipe Fitting", "Plumbing / Piping", "P"
        elif cat_id == ids.get("OST_PipeAccessory"):
            title, subtitle, icon = "Pipe Accessory", "Plumbing / Piping", "P"
        elif cat_id == ids.get("OST_FlexPipeCurves"):
            title, subtitle, icon = "Flex Pipe", "Plumbing / Piping", "P"
        elif cat_id == self._air_terminal_cat_id:
            title, subtitle, icon = "Air Terminal", "Air Terminals", "A"
        elif cat_id == self._plumbing_fixture_cat_id:
            title, subtitle, icon = "Plumbing Fixture", "Plumbing Fixtures", "W"
        elif cat_id == self._sprinkler_cat_id:
            title, subtitle, icon = "Sprinkler", "Fire Protection", "S"
        elif cat_id == self._mechanical_equipment_cat_id:
            title, subtitle, icon = "Mechanical Equipment", "Mechanical Equipment", "M"
        elif cat_id == self._specialty_equipment_cat_id:
            title, subtitle, icon = "Water / Specialty Equipment", "Specialty Equipment", "W"
        try:
            if self._setting("popup_show_header"):
                specific = self.type_name(el)
                if specific and len(specific) <= 48:
                    title = specific
        except:
            pass
        return title, subtitle, icon

    def _set_heading_for_element(self, el, cat_id):
        try:
            title, subtitle, icon = self._category_heading(el, cat_id)
            self.HeaderTitle.Text = title
            self.HeaderSubtitle.Text = subtitle
            self.HeaderIcon.Text = icon
        except:
            pass

    def _reveal_target(self):
        self._no_target_since_tick = None
        try:
            self._last_target_tick = int(self.System.Environment.TickCount)
        except:
            pass
        if not getattr(self, "_popup_visible", False):
            try:
                self.Opacity = 1.0
            except:
                pass
            self._popup_visible = True

    def no_target(self, immediate=False):
        if not self._setting("popup_hide_when_no_target"):
            return
        try:
            now = int(self.System.Environment.TickCount)
        except:
            now = 0
        if immediate:
            elapsed = 999999
        else:
            if self._no_target_since_tick is None:
                self._no_target_since_tick = now
                return
            elapsed = abs(now - int(self._no_target_since_tick))
        try:
            delay = max(0, int(self._value("popup_hide_delay_ms") or 85))
        except:
            delay = 85
        if elapsed >= delay and getattr(self, "_popup_visible", False):
            try:
                self.Opacity = 0.0
            except:
                pass
            self._popup_visible = False

    def ptext(self, el, names):
        try:
            eid_key = self.handler._eid_value(el.Id)
        except:
            eid_key = id(el)
        for n in names:
            key = (eid_key, str(n))
            try:
                if key in self._parameter_cache:
                    value = self._parameter_cache[key]
                    if value:
                        return value
                    continue
            except:
                pass

            value = ""
            try:
                p = el.LookupParameter(n)
                if p:
                    try:
                        value = p.AsValueString() or ""
                    except:
                        value = ""
                    if not value:
                        try:
                            value = p.AsString() or ""
                        except:
                            value = ""
            except:
                value = ""

            try:
                self._parameter_cache[key] = value
            except:
                pass

            if value:
                return value
        return ""

    def aval(self, el, name):
        try:
            v=getattr(el,name)
            if v is not None: return str(v)
        except: pass
        return ""

    def feet_inches(self, feet_value):
        """Format Revit internal feet as feet + fractional inches (nearest 1/16")."""
        try:
            total_inches = float(feet_value) * 12.0
            sign = "-" if total_inches < 0 else ""
            total_inches = abs(total_inches)

            feet = int(total_inches // 12.0)
            inches = total_inches - (feet * 12.0)
            sixteenths = int(round(inches * 16.0))

            if sixteenths >= 192:
                feet += 1
                sixteenths -= 192

            whole_inches = sixteenths // 16
            num = sixteenths % 16

            if num:
                den = 16
                while num % 2 == 0 and den > 1:
                    num //= 2
                    den //= 2
                inch_text = str(whole_inches) + " " + str(num) + "/" + str(den)
            else:
                inch_text = str(whole_inches)

            return sign + str(feet) + "'-" + inch_text + '"'
        except:
            return ""

    def type_name(self, el):
        # Prefer familiar family/type labels.
        for names in [
            ["Type Name", "Type"],
            ["Family and Type"],
            ["Family Name"]
        ]:
            txt = self.ptext(el, names)
            if txt:
                return txt

        try:
            typ = self._type_element(el)
            if typ:
                try:
                    if typ.Name:
                        return str(typ.Name)
                except:
                    pass
        except:
            pass
        return ""

    def first_param(self, el, names):
        return self.ptext(el, names)

    def _type_element(self, el):
        try:
            tid = el.GetTypeId()
            tid_value = self.handler._eid_value(tid)
            if tid_value is None or tid_value < 0:
                return None
            if getattr(self, "_cached_type_id", None) == tid_value:
                return getattr(self, "_cached_type_element", None)
            typ = el.Document.GetElement(tid)
            self._cached_type_id = tid_value
            self._cached_type_element = typ
            return typ
        except:
            return None

    def first_param_any(self, el, names):
        """Read instance first, then type; useful for family/type MEP metadata."""
        value = self.ptext(el, names)
        if value:
            return value
        typ = self._type_element(el)
        if typ is not None:
            return self.ptext(typ, names)
        return ""

    def _load_display_settings_runtime(self):
        values = dict(self._settings_defaults)
        try:
            if self._os.path.isfile(self._settings_path):
                with open(self._settings_path, "r") as fh:
                    for raw in fh:
                        line = raw.strip()
                        if not line or line.startswith("#") or "=" not in line:
                            continue
                        key, value = line.split("=", 1)
                        key = key.strip()
                        if key not in values:
                            continue
                        default = self._settings_defaults.get(key)
                        text = value.strip()
                        try:
                            if isinstance(default, bool):
                                values[key] = text.lower() in ("1", "true", "yes", "on")
                            elif isinstance(default, int) and not isinstance(default, bool):
                                values[key] = int(round(float(text)))
                            elif isinstance(default, float):
                                values[key] = float(text)
                            else:
                                values[key] = text
                        except:
                            values[key] = default
        except:
            pass
        return values

    def _settings_stamp_runtime(self):
        try:
            return self._os.path.getmtime(self._settings_path)
        except:
            return None

    def _refresh_display_settings(self, force=False):
        try:
            # Avoid a filesystem stat every time the cursor crosses into a new
            # element. One check per second is more than enough for settings UI.
            now = int(self.System.Environment.TickCount)
            last = int(getattr(self, "_last_settings_check_tick", 0))
            if not force and last and abs(now - last) < 1000:
                return False
            self._last_settings_check_tick = now

            stamp = self._settings_stamp_runtime()
            if force or stamp != self.display_settings_stamp:
                previous = dict(self.display_settings)
                self.display_settings = self._load_display_settings_runtime()
                self.display_settings_stamp = stamp

                category_changed = False
                try:
                    for key in self._category_bic_by_setting.keys():
                        if bool(previous.get(key)) != bool(self.display_settings.get(key)):
                            category_changed = True
                            break
                except:
                    category_changed = True

                if category_changed:
                    try:
                        self.handler.refresh_filter()
                    except:
                        pass
                try:
                    self._apply_popup_appearance()
                    if hasattr(self, "move_timer") and hasattr(self, "read_timer"):
                        from System import TimeSpan
                        self.move_timer.Interval = TimeSpan.FromMilliseconds(max(14, int(self._value("hover_move_interval_ms") or 20)))
                        self.read_timer.Interval = TimeSpan.FromMilliseconds(max(28, int(self._value("hover_read_interval_ms") or 35)))
                except:
                    pass
                return True
        except:
            pass
        return False

    def reload_settings(self):
        """Called directly by config.py after Apply when the hover window exists."""
        try:
            self._last_settings_check_tick = 0
            changed = self._refresh_display_settings(force=True)
            self._parameter_cache = {}
            self.handler.last_eid = None
            self.handler.same_element_reads = 0
            self._apply_popup_appearance()
            try:
                from System import TimeSpan
                self.move_timer.Interval = TimeSpan.FromMilliseconds(max(14, int(self._value("hover_move_interval_ms") or 20)))
                self.read_timer.Interval = TimeSpan.FromMilliseconds(max(28, int(self._value("hover_read_interval_ms") or 35)))
            except:
                pass
            return changed
        except:
            return False

    def _setting(self, name):
        try:
            return bool(self.display_settings.get(name, self._settings_defaults.get(name, False)))
        except:
            try:
                return bool(self._settings_defaults.get(name, False))
            except:
                return False

    def _value(self, name):
        try:
            return self.display_settings.get(name, self._settings_defaults.get(name))
        except:
            return self._settings_defaults.get(name)

    def _parameter_text(self, el, bip, fallback_names=None):
        """Read a parameter using project formatting whenever possible."""
        try:
            p = el.get_Parameter(bip)
            if p is not None and p.HasValue:
                try:
                    txt = p.AsValueString()
                    if txt:
                        return txt
                except:
                    pass
                try:
                    txt = p.AsString()
                    if txt:
                        return txt
                except:
                    pass
                try:
                    if p.StorageType == self.handler.DB.StorageType.Double:
                        return self.feet_inches(p.AsDouble())
                except:
                    pass
        except:
            pass

        if fallback_names:
            return self.ptext(el, fallback_names)
        return ""

    def _fabrication_elevation(self, el, mode):
        if mode == "BOD":
            txt = self._bip_text(
                el, "FABRICATION_BOTTOM_ELEVATION_OF_PART",
                ["Bottom Elevation", "Spot Bottom Elevation"]
            )
            if txt:
                return txt
            try:
                return self.feet_inches(el.BottomOfPartElevation)
            except:
                return ""

        if mode == "COD":
            txt = self._bip_text(
                el, "FABRICATION_CENTERLINE_ELEVATION_OF_PART",
                ["Spot Centerline Elevation", "Centerline Elevation", "Middle Elevation"]
            )
            if txt:
                return txt
            return self._bip_text(el, "FABRICATION_OFFSET_PARAM", ["Middle Elevation"])

        if mode == "TOD":
            txt = self._bip_text(
                el, "FABRICATION_TOP_ELEVATION_OF_PART",
                ["Top Elevation", "Spot Top Elevation"]
            )
            if txt:
                return txt
            try:
                return self.feet_inches(el.TopOfPartElevation)
            except:
                return ""

        return ""

    def _bip_text(self, el, bip_name, fallback_names=None):
        # Several BuiltInParameter names vary by Revit version/category. Cache
        # missing enum names as False so a missing 2025 parameter does not trigger
        # an exception + reflection lookup for every element the cursor crosses.
        try:
            if bip_name in self._bip_enum_cache:
                bip = self._bip_enum_cache[bip_name]
            else:
                try:
                    bip = getattr(self.handler.DB.BuiltInParameter, bip_name)
                except:
                    bip = False
                self._bip_enum_cache[bip_name] = bip

            if bip is not False:
                value = self._parameter_text(el, bip, None)
                if value:
                    return value
        except:
            pass

        if fallback_names:
            return self.ptext(el, fallback_names)
        return ""

    def _inch_text(self, feet_value):
        try:
            total = abs(float(feet_value)) * 12.0
            sixteenths = int(round(total * 16.0))
            whole = sixteenths // 16
            num = sixteenths % 16
            if num:
                den = 16
                while num % 2 == 0 and den > 1:
                    num //= 2
                    den //= 2
                return '{0} {1}/{2}"'.format(whole, num, den) if whole else '{0}/{1}"'.format(num, den)
            return '{0}"'.format(whole)
        except:
            return ""

    def _level_text(self, el):
        try:
            level = el.Document.GetElement(el.LevelId)
            if level is not None:
                return str(level.Name)
        except:
            pass
        return self.ptext(el, ["Reference Level", "Level", "Schedule Level"])

    def _fabrication_insulation(self, el):
        parts = []
        try:
            typ = el.InsulationType
            if typ:
                parts.append(str(typ))
        except:
            pass
        try:
            thick = float(el.InsulationThickness)
            if thick > 1e-8:
                txt = self._inch_text(thick)
                if txt:
                    parts.append(txt)
        except:
            pass
        if not parts:
            txt = self.ptext(el, ["Insulation Type", "Insulation", "Insulation Thickness"])
            if txt:
                return txt
        return " / ".join(parts)

    def _fabrication_lining(self, el):
        parts = []
        try:
            typ = el.LiningType
            if typ:
                parts.append(str(typ))
        except:
            pass
        try:
            thick = float(el.LiningThickness)
            if thick > 1e-8:
                txt = self._inch_text(thick)
                if txt:
                    parts.append(txt)
        except:
            pass
        if not parts:
            txt = self.ptext(el, ["Lining Type", "Lining", "Lining Thickness"])
            if txt:
                return txt
        return " / ".join(parts)

    def _workset_text(self, el):
        try:
            ws = el.Document.GetWorksetTable().GetWorkset(el.WorksetId)
            if ws is not None:
                return str(ws.Name)
        except:
            pass
        return self.ptext(el, ["Workset"])

    def _open_connector_count(self, el):
        connectors = None
        try:
            connectors = el.ConnectorManager.Connectors
        except:
            try:
                mep = el.MEPModel
                if mep is not None and mep.ConnectorManager is not None:
                    connectors = mep.ConnectorManager.Connectors
            except:
                connectors = None
        if connectors is None:
            return ""
        total = 0
        open_count = 0
        try:
            for c in connectors:
                total += 1
                try:
                    if not c.IsConnected:
                        open_count += 1
                except:
                    pass
        except:
            return ""
        if total <= 0:
            return ""
        return str(open_count)

    def _category_id(self, el):
        try:
            return el.Category.Id.IntegerValue
        except:
            try:
                return int(el.Category.Id.Value)
            except:
                return None

    def _family_name(self, el):
        try:
            sym = getattr(el, "Symbol", None)
            if sym is not None:
                fam = getattr(sym, "Family", None)
                if fam is not None and fam.Name:
                    return str(fam.Name)
        except:
            pass
        return self.first_param(el, ["Family", "Family Name"])

    def _category_setting_key(self, cat_id):
        return self._category_setting_by_id.get(cat_id)

    def enabled_bic_names(self):
        names = []
        for setting_key, bic_name in self._category_bic_by_setting.items():
            try:
                if self._setting(setting_key):
                    names.append(bic_name)
            except:
                pass
        return tuple(names)

    def is_category_enabled(self, el):
        key = self._category_setting_key(self._category_id(el))
        if not key:
            return False
        return self._setting(key)

    def _system_values(self, el, need_name, need_type, need_class, need_abbr):
        name = ""
        systype = ""
        classification = ""
        abbr = ""

        if need_name:
            name = self._bip_text(el, "RBS_SYSTEM_NAME_PARAM", ["System Name"])

        if need_type:
            systype = self._bip_text(el, "RBS_DUCT_SYSTEM_TYPE_PARAM", ["System Type"])
            if not systype:
                systype = self._bip_text(el, "RBS_PIPING_SYSTEM_TYPE_PARAM", ["System Type"])

        if need_class:
            classification = self._bip_text(
                el, "RBS_SYSTEM_CLASSIFICATION_PARAM", ["System Classification"])
            if not classification:
                classification = self._bip_text(
                    el, "RBS_PIPE_CONNECTOR_SYSTEM_CLASSIFICATION_PARAM", ["System Classification"])
            if not classification:
                classification = self._bip_text(
                    el, "RBS_DUCT_CONNECTOR_SYSTEM_CLASSIFICATION_PARAM", ["System Classification"])

        if need_abbr:
            abbr = self._bip_text(
                el, "RBS_DUCT_PIPE_SYSTEM_ABBREVIATION_PARAM", ["System Abbreviation", "Abbreviation"])
            if not abbr:
                abbr = self._bip_text(
                    el, "RBS_SYSTEM_ABBREVIATION_PARAM", ["System Abbreviation", "Abbreviation"])

        return name, systype, classification, abbr

    def _all_parameter_rows(self, el, existing_labels, type_params=False, limit=35):
        target = el
        if type_params:
            try:
                tid = el.GetTypeId()
                if tid is not None:
                    target = el.Document.GetElement(tid)
            except:
                target = None
        if target is None:
            return []
        rows = []
        seen = set(existing_labels)
        try:
            params = target.Parameters
        except:
            params = []
        for p in params:
            if len(rows) >= limit:
                break
            try:
                name = str(p.Definition.Name)
            except:
                continue
            key = name.strip().lower()
            if not key or key in seen:
                continue
            value = ""
            try:
                value = p.AsValueString() or ""
            except:
                value = ""
            if not value:
                try:
                    value = p.AsString() or ""
                except:
                    value = ""
            if not value:
                continue
            seen.add(key)
            rows.append("{0}: {1}".format(name, value))
        return rows

    def show_element(self, el):
        self._refresh_display_settings()
        self._parameter_cache = {}
        self._cached_type_id = None
        self._cached_type_element = None

        cat_id = self._category_id(el)
        if not self.is_category_enabled(el):
            self.no_target(immediate=False)
            return

        self._set_heading_for_element(el, cat_id)
        self._reveal_target()
        rows = []
        labels = set()

        def add(label, value):
            try:
                value = str(value).strip() if value is not None else ""
            except:
                value = ""
            if not value:
                return
            lk = label.strip().lower()
            if lk in labels:
                return
            labels.add(lk)
            rows.append("{0}: {1}".format(label, value))

        # -------------------------
        # Common MEP identity
        # -------------------------
        if self._setting("show_type"):
            add("Type", self.type_name(el))
        if self._setting("show_family"):
            add("Family", self._family_name(el))
        if self._setting("show_mark"):
            add("Mark", self.first_param(el, ["Mark"]))
        if self._setting("show_type_mark"):
            add("Type Mark", self.first_param_any(el, ["Type Mark"]))
        if self._setting("show_level"):
            add("Level", self._level_text(el))
        if self._setting("show_offset"):
            add("Offset", self.first_param(el, ["Offset", "Middle Elevation", "Start Offset", "Elevation from Level"]))
        if self._setting("show_phase"):
            add("Phase", self.first_param(el, ["Phase Created", "Phase"]))

        need_sysname = self._setting("show_system")
        need_systype = self._setting("show_system_type")
        need_sysclass = self._setting("show_system_classification")
        need_sysabbr = self._setting("show_system_abbr")
        if need_sysname or need_systype or need_sysclass or need_sysabbr:
            sysname, systype, classification, sysabbr = self._system_values(
                el, need_sysname, need_systype, need_sysclass, need_sysabbr)
            if need_sysname:
                add("System", sysname)
            if need_systype:
                add("System Type", systype)
            if need_sysclass:
                add("System Class", classification)
            if need_sysabbr:
                add("System Abbr", sysabbr)

        fab_cats = self._fab_cat_ids
        fab_duct_id = self._category_ids.get("OST_FabricationDuctwork")
        fab_pipe_id = self._category_ids.get("OST_FabricationPipework")
        is_fab = cat_id in fab_cats
        is_native_duct = cat_id in self._duct_cat_ids
        is_native_pipe = cat_id in self._pipe_cat_ids

        # -------------------------
        # Fabrication duct / pipe
        # -------------------------
        if is_fab:
            if self._setting("show_part"):
                part = self._bip_text(
                    el, "FABRICATION_FITTING_DESCRIPTION",
                    ["Fabrication Fitting Description", "Description", "Part Name"])
                if not part:
                    try: part = str(el.Name)
                    except: part = ""
                add("Part", part)
            if self._setting("show_size"):
                add("Size", self.aval(el, "Size") or self.ptext(el, ["Size"]))
            if self._setting("show_length"):
                raw_length = None
                try: raw_length = el.CenterlineLength
                except: pass
                if raw_length is None:
                    try: raw_length = el.Length
                    except: pass
                txt = self.feet_inches(raw_length) if raw_length is not None else ""
                if not txt:
                    txt = self._bip_text(el, "FABRICATION_PART_LENGTH", ["Length", "Centerline Length"])
                add("Length", txt)
            if self._setting("show_service"):
                add("Service", self.aval(el, "ServiceName") or self._bip_text(
                    el, "FABRICATION_SERVICE_NAME", ["Fabrication Service Name", "Service Name", "Service"]))
            if self._setting("show_service_abbr"):
                add("Service Abbr", self.aval(el, "ServiceAbbreviation") or self._bip_text(
                    el, "FABRICATION_SERVICE_ABBREVIATION", ["Fabrication Service Abbreviation", "Service Abbreviation"]))
            if self._setting("show_bod"):
                add("BOD", self._fabrication_elevation(el, "BOD"))
            if self._setting("show_cod"):
                add("COD", self._fabrication_elevation(el, "COD"))
            if self._setting("show_tod"):
                add("TOD", self._fabrication_elevation(el, "TOD"))
            if self._setting("show_slope"):
                add("Slope", self._bip_text(el, "FABRICATION_SLOPE_PARAM", ["Slope"]) or self.aval(el, "Slope"))
            if self._setting("show_item_number"):
                add("Item No", self.aval(el, "ItemNumber") or self._bip_text(el, "FABRICATION_PART_ITEM_NUMBER", ["Item Number"]))
            if self._setting("show_pattern"):
                add("Pattern/CID", self._bip_text(el, "FABRICATION_PART_PAT_NO", ["Part Pattern Number", "Pattern Number", "CID"]))
            if self._setting("show_specification"):
                add("Spec", self._bip_text(el, "FABRICATION_SPECIFICATION", ["Specification"]) or self.aval(el, "ProductSpecificationDescription"))
            if self._setting("show_material"):
                add("Material", self._bip_text(el, "FABRICATION_PART_MATERIAL", ["Part Material", "Material"]))
            if self._setting("show_gauge"):
                add("Gauge", self._bip_text(el, "FABRICATION_MATERIAL_GAUGE", ["Material Gauge", "Gauge"]))
            if self._setting("show_insulation"):
                add("Insulation", self._fabrication_insulation(el))
            if self._setting("show_lining"):
                add("Lining", self._fabrication_lining(el))
            if self._setting("show_notes"):
                add("Notes", self.aval(el, "Notes") or self._bip_text(el, "FABRICATION_PART_NOTES", ["Fabrication Notes", "Notes"]))
            if self._setting("show_alias"):
                add("Alias", self.aval(el, "Alias") or self._bip_text(el, "FABRICATION_PART_ALIAS", ["Alias"]))
            if self._setting("show_spool_name"):
                add("Spool", self.aval(el, "SpoolName") or self.first_param(el, ["Spool Name", "Spool"]))
            if self._setting("show_product_name"):
                add("Product", self.aval(el, "ProductName") or self.aval(el, "ProductShortDescription") or self.first_param(el, ["Product Name"]))
            if self._setting("show_vendor"):
                add("Vendor", self.aval(el, "Vendor") or self.aval(el, "ProductOriginalEquipmentManufacture") or self.first_param(el, ["Vendor", "Manufacturer"]))
            if self._setting("show_pressure_class"):
                add("Pressure Class", self.first_param_any(el, ["Pressure Class", "Pressure Class Name"]))

            # Flow-related fields are often available on fabrication connectors or
            # as parameters. Query only when explicitly enabled.
            if cat_id == fab_duct_id:
                if self._setting("show_cfm") or self._setting("show_flow"):
                    add("Flow", self.first_param(el, ["Flow", "Air Flow", "Airflow", "CFM"]))
                if self._setting("show_velocity"):
                    add("Velocity", self.first_param(el, ["Velocity"]))
            if cat_id == fab_pipe_id:
                if self._setting("show_pipe_flow") or self._setting("show_gpm"):
                    add("Flow", self.first_param(el, ["Flow", "GPM", "Calculated Flow"]))
                if self._setting("show_pipe_velocity"):
                    add("Velocity", self.first_param(el, ["Velocity"]))
                if self._setting("show_pipe_material"):
                    add("Pipe Material", self.first_param(el, ["Material", "Part Material"]))
                if self._setting("show_fixture_units"):
                    add("Fixture Units", self.first_param(el, ["Fixture Units"]))

        # -------------------------
        # Native Revit ductwork
        # -------------------------
        elif is_native_duct:
            if self._setting("show_size"):
                add("Size", self._bip_text(el, "RBS_DUCT_SIZE_FORMATTED_PARAM", ["Size", "Duct Size"]))
            if self._setting("show_length"):
                add("Length", self._bip_text(el, "CURVE_ELEM_LENGTH", ["Length"]))
            if self._setting("show_width"):
                add("Width", self._bip_text(el, "RBS_CURVE_WIDTH_PARAM", ["Width"]))
            if self._setting("show_height"):
                add("Height", self._bip_text(el, "RBS_CURVE_HEIGHT_PARAM", ["Height"]))
            if self._setting("show_diameter"):
                add("Diameter", self._bip_text(el, "RBS_CURVE_DIAMETER_PARAM", ["Diameter"]))
            if self._setting("show_cfm") or self._setting("show_flow"):
                add("Flow", self._bip_text(el, "RBS_DUCT_FLOW_PARAM", ["Flow", "Air Flow", "Airflow", "CFM"]))
            if self._setting("show_velocity"):
                add("Velocity", self._bip_text(el, "RBS_VELOCITY", ["Velocity"]))
            if self._setting("show_friction"):
                add("Friction", self._bip_text(el, "RBS_FRICTION", ["Friction"]))
            if self._setting("show_pressure_drop"):
                add("Pressure Drop", self._bip_text(el, "RBS_DUCT_PRESSURE_DROP", ["Pressure Drop"]))
            if self._setting("show_static_pressure"):
                add("Static Pressure", self._bip_text(el, "RBS_DUCT_STATIC_PRESSURE", ["Static Pressure"]))
            if self._setting("show_slope"):
                add("Slope", self._bip_text(el, "RBS_DUCT_SLOPE", ["Slope"]) or self._bip_text(el, "RBS_CURVE_SLOPE", ["Slope"]))
            if self._setting("show_bod"):
                add("BOD", self._bip_text(el, "RBS_DUCT_BOTTOM_ELEVATION", ["Bottom Elevation", "Lower End Bottom Elevation"]))
            if self._setting("show_tod"):
                add("TOD", self._bip_text(el, "RBS_DUCT_TOP_ELEVATION", ["Top Elevation", "Upper End Top Elevation"]))
            if self._setting("show_cod"):
                add("COD", self.first_param(el, ["Middle Elevation", "Center Elevation", "Offset"]))
            if self._setting("show_insulation"):
                add("Insulation", self.first_param(el, ["Insulation Thickness", "Insulation Type", "Insulation"]))
            if self._setting("show_lining"):
                add("Lining", self.first_param(el, ["Lining Thickness", "Lining Type", "Lining"]))

        # -------------------------
        # Native Revit piping
        # -------------------------
        elif is_native_pipe:
            if self._setting("show_size"):
                add("Size", self._bip_text(el, "RBS_PIPE_CALCULATED_SIZE", ["Size", "Pipe Size"]) or self._bip_text(el, "RBS_PIPE_SIZE_FORMATTED_PARAM", ["Size"]))
            if self._setting("show_length"):
                add("Length", self._bip_text(el, "CURVE_ELEM_LENGTH", ["Length"]))
            if self._setting("show_pipe_diameter") or self._setting("show_diameter"):
                add("Diameter", self._bip_text(el, "RBS_PIPE_DIAMETER_PARAM", ["Diameter"]))
            if self._setting("show_pipe_inside_diameter"):
                add("Inside Dia", self._bip_text(el, "RBS_PIPE_INNER_DIAM_PARAM", ["Inside Diameter"]))
            if self._setting("show_pipe_outside_diameter"):
                add("Outside Dia", self._bip_text(el, "RBS_PIPE_OUTER_DIAMETER", ["Outside Diameter"]))
            if self._setting("show_pipe_flow") or self._setting("show_gpm"):
                add("Flow", self._bip_text(el, "RBS_PIPE_FLOW_PARAM", ["Flow", "GPM", "Calculated Flow"]))
            if self._setting("show_pipe_velocity"):
                add("Velocity", self._bip_text(el, "RBS_PIPE_VELOCITY_PARAM", ["Velocity"]))
            if self._setting("show_pipe_friction"):
                add("Friction", self._bip_text(el, "RBS_PIPE_FRICTION_PARAM", ["Friction"]))
            if self._setting("show_pipe_pressure_drop"):
                add("Pressure Drop", self._bip_text(el, "RBS_PIPE_PRESSUREDROP_PARAM", ["Pressure Drop"]))
            if self._setting("show_slope"):
                add("Slope", self._bip_text(el, "RBS_PIPE_SLOPE", ["Slope"]) or self._bip_text(el, "RBS_CURVE_SLOPE", ["Slope"]))
            if self._setting("show_pipe_material"):
                add("Material", self._bip_text(el, "RBS_PIPE_MATERIAL_PARAM", ["Material"]))
            if self._setting("show_pipe_schedule"):
                add("Schedule/Type", self._bip_text(el, "RBS_PIPE_CLASS_PARAM", ["Schedule/Type", "Schedule"]))
            if self._setting("show_pipe_segment"):
                add("Pipe Segment", self.first_param(el, ["Pipe Segment", "Segment Description"]) or self._bip_text(el, "RBS_SEGMENT_DESCRIPTION_PARAM", ["Segment Description"]))
            if self._setting("show_connection_type"):
                add("Connection", self._bip_text(el, "RBS_PIPE_CONNECTIONTYPE_PARAM", ["Connection Type"]))
            if self._setting("show_fluid_type"):
                add("Fluid", self._bip_text(el, "RBS_PIPE_FLUID_TYPE_PARAM", ["Fluid Type"]))
            if self._setting("show_fluid_temperature"):
                add("Fluid Temp", self._bip_text(el, "RBS_PIPE_FLUID_TEMPERATURE_PARAM", ["Fluid Temperature"]))
            if self._setting("show_fixture_units"):
                add("Fixture Units", self._bip_text(el, "RBS_PIPE_FIXTURE_UNITS_PARAM", ["Fixture Units"]))
            if self._setting("show_cwfu"):
                add("CWFU", self._bip_text(el, "RBS_PIPE_CWFU_PARAM", ["CWFU"]))
            if self._setting("show_hwfu"):
                add("HWFU", self._bip_text(el, "RBS_PIPE_HWFU_PARAM", ["HWFU"]))
            if self._setting("show_wfu"):
                add("WFU", self._bip_text(el, "RBS_PIPE_WFU_PARAM", ["WFU"]))
            if self._setting("show_invert_elevation"):
                add("Invert Elev", self._bip_text(el, "RBS_PIPE_INVERT_ELEVATION", ["Invert Elevation"]))
            if self._setting("show_pipe_bottom_elevation"):
                add("Bottom Elev", self._bip_text(el, "RBS_PIPE_BOTTOM_ELEVATION", ["Lower End Bottom Elevation", "Bottom Elevation"]))
            if self._setting("show_pipe_top_elevation"):
                add("Top Elev", self._bip_text(el, "RBS_PIPE_TOP_ELEVATION", ["Upper End Top Elevation", "Top Elevation"]))
            if self._setting("show_pipe_insulation"):
                add("Insulation", self._bip_text(el, "RBS_PIPE_INSULATION_THICKNESS", ["Insulation Thickness", "Insulation"]))

        # -------------------------
        # Air terminals
        # -------------------------
        elif cat_id == self._air_terminal_cat_id:
            if self._setting("show_size"):
                add("Size", self.first_param_any(el, ["Size", "Neck Size", "Connection Size", "Inlet Size", "Duct Size"]))
            if self._setting("show_connector_size"):
                add("Connector", self.first_param_any(el, ["Neck Size", "Connection Size", "Connector Size", "Inlet Size"]))
            if self._setting("show_cfm") or self._setting("show_flow"):
                add("CFM", self.first_param_any(el, ["Flow", "Air Flow", "Airflow", "CFM", "Supply Air Flow", "Return Air Flow"]))

        # -------------------------
        # Mechanical / water equipment, plumbing fixtures, sprinklers
        # -------------------------
        elif cat_id in self._equipment_cat_ids:
            if self._setting("show_size"):
                add("Size", self.first_param_any(el, ["Size", "Connection Size", "Duct Size", "Pipe Size", "Supply Duct Size", "Return Duct Size"]))
            if self._setting("show_connector_size"):
                add("Connector", self.first_param_any(el, ["Connector Size", "Connection Size", "Inlet Size", "Outlet Size", "Pipe Connection Size", "Neck Size"]))
            if self._setting("show_cfm"):
                add("CFM", self.first_param_any(el, ["Air Flow", "Airflow", "CFM", "Supply Air Flow", "Return Air Flow", "Design Air Flow"]))
            if self._setting("show_gpm") or self._setting("show_pipe_flow"):
                add("GPM", self.first_param_any(el, ["Flow", "GPM", "Water Flow", "Design Flow", "Calculated Flow"]))
            if self._setting("show_pipe_pressure_drop") or self._setting("show_pressure_drop"):
                add("Pressure Drop", self.first_param_any(el, ["Calculated Pressure Drop", "Pressure Drop"]))
            if self._setting("show_fixture_units"):
                add("Fixture Units", self.first_param_any(el, ["Fixture Units"]))
            if self._setting("show_cwfu"):
                add("CWFU", self.first_param_any(el, ["CWFU", "Cold Water Fixture Units"]))
            if self._setting("show_hwfu"):
                add("HWFU", self.first_param_any(el, ["HWFU", "Hot Water Fixture Units"]))
            if self._setting("show_wfu"):
                add("WFU", self.first_param_any(el, ["WFU", "Waste Fixture Units"]))
            if self._setting("show_power"):
                add("Power", self.first_param_any(el, ["Power", "Electrical Power", "Power Input", "Input Power", "Heat Input"]))
            if self._setting("show_voltage"):
                add("Voltage", self.first_param_any(el, ["Voltage", "Volts"]))
            if self._setting("show_capacity"):
                add("Capacity", self.first_param_any(el, ["Capacity", "Heating Capacity", "Cooling Capacity", "Total Cooling Capacity", "Water Heater Capacity", "Storage Capacity"]))
            if self._setting("show_manufacturer"):
                add("Manufacturer", self.first_param_any(el, ["Manufacturer"]))
            if self._setting("show_model"):
                add("Model", self.first_param_any(el, ["Model", "Model Number"]))
            if self._setting("show_space"):
                add("Space/Room", self.first_param(el, ["Space", "Space Name", "Room Name", "Room Number", "Location"]))

        # Common QA / identity fields after discipline-specific rows.
        if self._setting("show_open_connectors"):
            add("Open Ends", self._open_connector_count(el))
        if self._setting("show_workset"):
            add("Workset", self._workset_text(el))
        if self._setting("show_comments"):
            add("Comments", self.first_param(el, ["Comments"]))
        if self._setting("show_element_id"):
            try: add("Element ID", str(self.handler._eid_value(el.Id)))
            except: pass

        # Diagnostic mode follows the same on-demand pattern as Revit inspection
        # tools: enumerate parameters only for the currently hovered element, and
        # only when the user explicitly enables it.
        existing = set(labels)
        if self._setting("show_all_instance_parameters"):
            rows.extend(self._all_parameter_rows(el, existing, False, 35))
        if self._setting("show_all_type_parameters"):
            existing = set(r.split(":", 1)[0].strip().lower() for r in rows if ":" in r)
            rows.extend(self._all_parameter_rows(el, existing, True, 25))

        if not rows:
            rows.append("No selected fields have values")

        self.set_info("\n".join(rows))

    def _screen_to_wpf(self, x, y):
        """Convert physical screen pixels to WPF DIPs with a cached DPI transform."""
        try:
            now = int(self.System.Environment.TickCount)
            last = int(getattr(self, "_screen_transform_tick", 0))
            if self._screen_transform is None or not last or abs(now - last) >= 2000:
                source = self.PresentationSource.FromVisual(self)
                if source is not None and source.CompositionTarget is not None:
                    self._screen_transform = source.CompositionTarget.TransformFromDevice
                    self._screen_transform_tick = now

            if self._screen_transform is not None:
                return self._screen_transform.Transform(self.Point(float(x), float(y)))
        except:
            self._screen_transform = None

        return self.Point(float(x), float(y))

    def _runtime_active(self):
        """Return the cross-engine active flag.

        V7.2 stores the hot toggle state directly in AppDomain data so the native
        IExternalCommand can flip a boxed bool without invoking IronPython, WPF,
        settings, filters, or the hover engine. Window.Tag remains a compatibility
        fallback for older state and for diagnostics.
        """
        try:
            value = self.System.AppDomain.CurrentDomain.GetData("ROBMEPTOOLS.FabHover.Active")
            if isinstance(value, bool):
                return value
            if value is not None:
                text = str(value).strip().lower()
                if text in ("true", "1", "on"):
                    return True
                if text in ("false", "0", "off"):
                    return False
        except:
            pass
        try:
            tag = self.Tag
            if isinstance(tag, bool):
                return tag
            if tag is not None:
                text = str(tag).strip().lower()
                if text in ("true", "1", "on"):
                    return True
                if text in ("false", "0", "off"):
                    return False
        except:
            pass
        return bool(getattr(self, "is_active", False))

    def move_tick(self, sender, args):
        if not self._runtime_active():
            return
        try:
            p = self.MouseControl.MousePosition

            # Do not ask WPF to reposition if Windows says the mouse
            # has not moved.
            if (
                p.X == self.last_window_mouse_x
                and
                p.Y == self.last_window_mouse_y
            ):
                return

            self.last_window_mouse_x = p.X
            self.last_window_mouse_y = p.Y

            wp = self._screen_to_wpf(
                p.X,
                p.Y
            )

            try:
                ox = float(self._value("popup_offset_x") or 14)
                oy = float(self._value("popup_offset_y") or 10)
            except:
                ox, oy = 14.0, 10.0
            self.Left = wp.X + ox
            self.Top = wp.Y + oy

        except:
            pass

    def _request_read(self):
        if not self._runtime_active():
            return

        # Revit 2025 exposes ExternalEvent.IsPending. Use the native queue state
        # first, with the handler flag as a fallback/secondary guard. This avoids
        # flooding the queue and also prevents a denied/timed-out Raise() from
        # leaving the hover reader permanently stuck in a synthetic pending state.
        try:
            if self.ext_event.IsPending:
                return
        except:
            if self.handler.pending:
                return

        if self.handler.pending:
            return
        self.handler.pending = True

        try:
            request = self.ext_event.Raise()
            if request != ExternalEventRequest.Accepted:
                self.handler.pending = False
        except:
            self.handler.pending = False

    def read_tick(self, sender, args):
        active = self._runtime_active()
        if not active:
            self._runtime_was_active = False
            return
        try:
            if not bool(getattr(self, "_runtime_was_active", False)):
                # A compiled Fast Toggle can flip Window.Tag without calling back
                # into IronPython. Detect that transition here and force the very
                # next timer tick to acquire the element under the stationary cursor.
                self._runtime_was_active = True
                self.last_mouse_x = None
                self.last_mouse_y = None
                self.force_reads = 0
            p = self.MouseControl.MousePosition

            if (
                self.last_mouse_x is None
                or
                self.last_mouse_y is None
            ):
                dx = 999
                dy = 999
            else:
                dx = abs(
                    p.X - self.last_mouse_x
                )
                dy = abs(
                    p.Y - self.last_mouse_y
                )

            # One-pixel movement counts. ExternalEvent.IsPending prevents this
            # from building a queue, while the lower threshold feels more direct
            # when sliding across narrow pipe/duct edges in plan and 3D.
            moved = (
                dx >= 1
                or
                dy >= 1
            )

            self.mouse_is_moving = moved

            if moved:
                self.last_mouse_x = p.X
                self.last_mouse_y = p.Y
                self.force_reads = 0
                self._request_read()
                return

            # Stationary refresh keeps values/caches fresh without hammering
            # Revit. Convert the requested idle period to timer ticks so tuning the
            # read interval does not accidentally make idle polling aggressive.
            self.force_reads += 1
            try:
                read_ms = max(28, int(self._value("hover_read_interval_ms") or 35))
                idle_ms = max(350, int(self._value("hover_idle_refresh_ms") or 650))
                idle_ticks = max(4, int(round(float(idle_ms) / float(read_ms))))
            except:
                idle_ticks = 18

            if self.force_reads >= idle_ticks:
                self.force_reads = 0
                self.mouse_is_moving = False
                self._request_read()

        except:
            pass


    def deactivate(self):
        """Ultra-light OFF path shared by the Python and CLR toggle commands."""
        if not self._runtime_active():
            return False
        self.is_active = False
        self._runtime_was_active = False
        try:
            self.Tag = False
            self.System.AppDomain.CurrentDomain.SetData("ROBMEPTOOLS.FabHover.Active", False)
        except:
            pass
        try:
            self.handler.last_eid = None
            self.handler.same_element_reads = 0
        except:
            pass
        try:
            self._popup_visible = False
            self._no_target_since_tick = None
            self.Opacity = 0.0
        except:
            pass
        return False

    def activate(self):
        """Ultra-light ON path: every heavy object remains alive."""
        if self._is_closed:
            return False
        if self._runtime_active():
            return True
        self.is_active = True
        self._runtime_was_active = True
        try:
            self.Tag = True
            self.System.AppDomain.CurrentDomain.SetData("ROBMEPTOOLS.FabHover.Active", True)
        except:
            pass
        self.last_mouse_x = None
        self.last_mouse_y = None
        self.last_window_mouse_x = None
        self.last_window_mouse_y = None
        self.force_reads = 0
        self.mouse_is_moving = False
        try:
            self.handler.last_eid = None
            self.handler.same_element_reads = 0
        except:
            pass
        try:
            self._popup_visible = False
            self._no_target_since_tick = None
            self.Opacity = 0.0
        except:
            pass
        try:
            self._request_read()
        except:
            pass
        return True

    def toggle_active(self):
        if self._runtime_active():
            return self.deactivate()
        return self.activate()


    def closed(self, sender, args):
        self.is_active = False
        self._is_closed = True
        try:
            self.Tag = False
            domain = self.System.AppDomain.CurrentDomain
            domain.SetData("ROBMEPTOOLS.FabHover.Active", False)
            current = domain.GetData("ROBMEPTOOLS.FabHover.Window")
            if current is self:
                domain.SetData("ROBMEPTOOLS.FabHover.Window", None)
        except:
            pass
        try:
            self.move_timer.Stop()
        except:
            pass

        try:
            self.read_timer.Stop()
        except:
            pass

        try:
            self.handler._clear_view_caches()
        except:
            pass

        try:
            self.handler.window = None
        except:
            pass

        try:
            self.ext_event.Dispose()
        except:
            pass


def start(uiapp):
    """Create and show one Fab Hover modeless window."""
    try:
        if uiapp is None or uiapp.ActiveUIDocument is None:
            forms.alert("Open a Revit project first.", title="Fab Hover")
            return None
    except:
        forms.alert("Open a Revit project first.", title="Fab Hover")
        return None

    w = FabHover(DB, Control, System)
    w.show(modal=False)
    return w
