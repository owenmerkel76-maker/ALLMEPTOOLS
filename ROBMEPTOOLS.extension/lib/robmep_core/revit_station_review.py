# -*- coding: utf-8 -*-
"""Scoped TemporaryGraphicsManager markers; no model edits or global Clear()."""
import os
import shutil
import tempfile

from robmep_core.station_review import point


def write_marker(path, number):
    """Revit 2025 requires BMP; teal RGB(0,128,128) is its transparency key."""
    import clr
    clr.AddReference('System.Drawing')
    from System.Drawing import (Bitmap, Graphics, Font, FontStyle, Color, Pen,
                                SolidBrush, RectangleF, StringFormat, StringAlignment)
    from System.Drawing.Imaging import ImageFormat, PixelFormat
    resources = []
    try:
        bitmap = Bitmap(64,64,PixelFormat.Format24bppRgb); resources.append(bitmap)
        graphics = Graphics.FromImage(bitmap); resources.append(graphics)
        font = Font('Segoe UI',18.,FontStyle.Bold); resources.append(font)
        brush = SolidBrush(Color.White); resources.append(brush)
        fill = SolidBrush(Color.FromArgb(30,90,170)); resources.append(fill)
        pen = Pen(Color.White,2.); resources.append(pen)
        formatting = StringFormat(); resources.append(formatting)
        formatting.Alignment = StringAlignment.Center
        formatting.LineAlignment = StringAlignment.Center
        graphics.Clear(Color.FromArgb(0,128,128))
        graphics.FillEllipse(fill,4,4,56,56)
        graphics.DrawEllipse(pen,4,4,56,56)
        graphics.DrawString(str(number),font,brush,RectangleF(0.,0.,64.,64.),formatting)
        bitmap.Save(path,ImageFormat.Bmp)
    finally:
        for resource in reversed(resources):
            resource.Dispose()


class StationGraphics(object):
    def __init__(self,document,view_id,records,api=None,icon_writer=None):
        self.document,self.view_id,self.records = document,view_id,list(records)
        self.api,self.icon_writer = api,icon_writer or write_marker
        self.manager,self.directory = None,None
        self.indices = []

    def __enter__(self):
        if self.api is None:
            from Autodesk.Revit import DB as api
            self.api = api
        try:
            self.manager = self.api.TemporaryGraphicsManager.GetTemporaryGraphicsManager(self.document)
            self.directory = tempfile.mkdtemp(prefix='robmep-station-review-')
            for record in self.records:
                path = os.path.join(self.directory,'station-{}.bmp'.format(record['number']))
                self.icon_writer(path,record['number'])
                data = self.api.InCanvasControlData(path,self.api.XYZ(*point(record['point_ft'])))
                try:
                    index = self.manager.AddControl(data,self.view_id)
                    if index < 0:
                        raise ValueError('Revit did not create a temporary marker')
                    self.indices.append(index)
                finally:
                    data.Dispose()
            return self
        except Exception:
            self.close()
            raise

    def close(self):
        failures = []
        for index in reversed(self.indices):
            try:
                self.manager.RemoveControl(index)
            except Exception:
                failures.append(index)
        self.indices = list(reversed(failures))
        if failures:
            # Keep their BMP resources available; never erase another add-in's
            # graphics via Clear(), or proceed to a test after uncertain cleanup.
            raise ValueError('Temporary marker cleanup failed for indices {}; no hanger test started'.format(failures))
        if self.directory is not None:
            shutil.rmtree(self.directory)
            self.directory = None

    def __exit__(self,kind,value,traceback):
        self.close()
        return False


def choose_station(uidoc,records,forms,api=None):
    """Pan/zoom during native PickObject, then choose a station on that host."""
    if not records:
        return None
    if api is None:
        from Autodesk.Revit import DB as api
    from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
    from Autodesk.Revit.Exceptions import OperationCanceledException
    allowed = set(r['element_id'] for r in records)
    class CandidateFilter(ISelectionFilter):
        def AllowElement(self,element):
            try:
                return int(element.Id.Value) in allowed
            except AttributeError:
                return int(element.Id.IntegerValue) in allowed
        def AllowReference(self,reference,position):
            return False
    with StationGraphics(uidoc.Document,uidoc.ActiveView.Id,records,api):
        uidoc.RefreshActiveView()
        forms.alert('Numbered markers are proposed station coordinates, not hangers.\n'
                    'Pan/zoom in the next selection step. Click a marked duct to choose a test station.\n'
                    'Press Esc to finish visual review without a hanger test. All our markers are removed.')
        try:
            reference = uidoc.Selection.PickObject(ObjectType.Element,CandidateFilter(),
                'Review station markers; pick a candidate duct for a rolled-back test, or Esc to finish')
        except OperationCanceledException:
            return None
        try:
            host_id = int(reference.ElementId.Value)
        except AttributeError:
            host_id = int(reference.ElementId.IntegerValue)
        candidates = [r for r in records if r['element_id']==host_id]
        if not candidates:
            raise ValueError('Selected host has no displayed candidate station')
        labels = dict(('#{} | route {} | host {} | station {:.3f} ft'.format(
            r['number'],r['route_number'],r['element_id'],r['station_ft']),r) for r in candidates)
        selected = forms.SelectFromList.show(sorted(labels,key=lambda label:labels[label]['number']),multiselect=False,
            title='Choose the exact preview station',button_name='Select station')
        return labels.get(selected)
