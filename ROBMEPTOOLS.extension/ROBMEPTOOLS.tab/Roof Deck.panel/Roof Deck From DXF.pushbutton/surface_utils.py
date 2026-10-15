# coding: utf-8
"""Pure Python Revit-independent geometry for underside planes (feet)."""
import math


def plane_from_point_normal(point, normal):
    """Return z = a*x + b*y + c for nonvertical planar face."""
    nx, ny, nz = normal
    if abs(nz) < 0.7:
        raise ValueError('Plane not sufficiently horizontal to make a floor')
    a = -nx / nz
    b = -ny / nz
    c = point[2] - a * point[0] - b * point[1]
    return (a, b, c)


def plane_z(plane, x, y):
    return plane[0]*x + plane[1]*y + plane[2]


def same_plane(p1, p2, x, y, gradient_tolerance=0.00005,
               elevation_tolerance=1.0/192.0):
    """Same gradient and elevation within 1/16 inch at test coordinate."""
    return (abs(p1[0]-p2[0]) <= gradient_tolerance and
            abs(p1[1]-p2[1]) <= gradient_tolerance and
            abs(plane_z(p1,x,y) - plane_z(p2,x,y)) <= elevation_tolerance)


def triangle_area_xy(p0, p1, p2):
    return 0.5*abs((p1[0]-p0[0])*(p2[1]-p0[1]) -
                   (p2[0]-p0[0])*(p1[1]-p0[1]))


def plane_drift(plane, points):
    zs = [plane_z(plane, p[0], p[1]) for p in points]
    return max(zs)-min(zs) if zs else 0.0


def pitch_in_per_foot(plane):
    return math.hypot(plane[0], plane[1])*12.0


def slope_arrow_xy(plane, center, length=1.0):
    a, b = plane[:2]
    pitch = math.hypot(a,b)
    if pitch < 1.e-5:
        return None, 0.0
    ux, uy = a/pitch, b/pitch
    x, y = center
    return ((x, y), (x+length*ux, y+length*uy)), pitch


def verify_at_points(source_plane, created_plane, points, tolerance=1.0/96.0):
    """Check underside plane elevation at every sampled footprint XY."""
    errors = [abs(plane_z(source_plane, p[0], p[1]) -
                  plane_z(created_plane,p[0],p[1])) for p in points]
    return (max(errors) <= tolerance if errors else False,
            max(errors) if errors else float('inf'))
