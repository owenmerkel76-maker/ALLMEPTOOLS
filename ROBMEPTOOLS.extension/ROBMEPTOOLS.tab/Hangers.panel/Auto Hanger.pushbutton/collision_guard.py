# -*- coding: utf-8 -*-
"""Fail-safe broad phase for fabrication hanger rod-to-MEP interference.

Feet throughout. AABB results are *potential* clashes, not geometry proofs.
Designed to run under IronPython and for standalone CPython tests.
"""

def intersects(a, b, clearance=0.0):
    """a/b=(xmin,ymin,zmin,xmax,ymax,zmax)."""
    return all(a[i] <= b[i+3]+clearance and b[i] <= a[i+3]+clearance
               for i in range(3))


def rod_envelope(end, length, radius=0.10):
    """Envelopes both possible vertical rod directions because API end position
    is not documented as the rod's upper or lower end. This can be overly
    conservative but never silently treats a possible clash as clear.
    """
    x,y,z=end
    return (x-radius,y-radius,z-length-radius,
            x+radius,y+radius,z+length+radius)


def bbox_from_corners(corners):
    if not corners:
        return None
    return (min(p[0] for p in corners),min(p[1] for p in corners),
            min(p[2] for p in corners),max(p[0] for p in corners),
            max(p[1] for p in corners),max(p[2] for p in corners))


def reason_for_clash(rod_idx, element_id, category):
    return 'Rod {} potential 3D clash with {} element {} (bounding-box screening; verify in 3D)'.format(
        rod_idx,category,element_id)
