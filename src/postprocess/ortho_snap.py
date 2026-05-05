"""Orthogonalisation (ortho-snap) of building polygons.

Pipeline per polygon (in metric CRS):
  1. Simplify with Douglas-Peucker (default 0.5 m) — removes zigzag noise.
  2. Find principal axis by taking the longest edge of the minimum
     rotated bounding rectangle.
  3. Rotate the polygon so the principal axis lies on the X-axis.
  4. Walk the polygon vertex-by-vertex; each edge that is "more horizontal
     than vertical" is forced to be perfectly horizontal (set Δy=0), and
     the converse for vertical edges. This snaps every corner to 90°.
  5. Rotate back.
  6. buffer(0) to repair any micro self-intersections.

The result preserves L / U / + shapes (no rectangle bound), but every
edge is at right angles to its neighbours, like a real building plan.
"""
from __future__ import annotations
import math
from typing import Iterable

from shapely.geometry import Polygon, MultiPolygon
from shapely.affinity import rotate
import geopandas as gpd


def _principal_angle_deg(poly: Polygon) -> float:
    """Angle of the longest edge of the minimum oriented bounding box (deg)."""
    rect = poly.minimum_rotated_rectangle
    coords = list(rect.exterior.coords)[:4]
    best_len = 0.0
    best_angle = 0.0
    for i in range(4):
        x1, y1 = coords[i]
        x2, y2 = coords[(i + 1) % 4]
        dx = x2 - x1; dy = y2 - y1
        length = math.hypot(dx, dy)
        if length > best_len:
            best_len = length
            best_angle = math.degrees(math.atan2(dy, dx))
    return best_angle


def _snap_ring(coords: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Snap each edge to horizontal or vertical (whichever is dominant)."""
    if len(coords) < 4:
        return coords
    # Drop closing duplicate
    if coords[0] == coords[-1]:
        coords = coords[:-1]
    new = [coords[0]]
    for i in range(1, len(coords) + 1):
        cur = coords[i % len(coords)]
        prev = new[-1]
        dx = cur[0] - prev[0]
        dy = cur[1] - prev[1]
        if abs(dx) > abs(dy):
            # Horizontal edge — keep prev.y
            new.append((cur[0], prev[1]))
        else:
            # Vertical edge — keep prev.x
            new.append((prev[0], cur[1]))
    # Close
    if new[-1] != new[0]:
        new.append(new[0])
    return new


def ortho_snap_polygon(poly: Polygon, simplify_tol: float = 0.5,
                       min_area_m2: float = 5.0) -> Polygon | MultiPolygon | None:
    """Apply ortho-snap to a single polygon (assumes metric CRS)."""
    if poly is None or poly.is_empty:
        return poly

    # Multi-polygon: snap each part independently
    if poly.geom_type == "MultiPolygon":
        parts = [ortho_snap_polygon(p, simplify_tol, min_area_m2)
                 for p in poly.geoms]
        parts = [p for p in parts if p is not None and not p.is_empty]
        if not parts:
            return None
        if len(parts) == 1:
            return parts[0]
        return MultiPolygon(parts)

    # 1. Simplify
    simp = poly.simplify(simplify_tol, preserve_topology=True)
    if not simp.is_valid:
        simp = simp.buffer(0)
    if simp.is_empty or simp.area < min_area_m2:
        return None

    # 2-3. Find principal axis & rotate to align it with X
    try:
        angle = _principal_angle_deg(simp)
    except Exception:
        return simp
    centroid = simp.centroid
    rotated = rotate(simp, -angle, origin=centroid)
    if rotated.is_empty:
        return simp

    # 4. Snap exterior + interior rings
    if rotated.geom_type != "Polygon":
        return simp
    ext_coords = list(rotated.exterior.coords)
    snapped_ext = _snap_ring(ext_coords)
    snapped_holes = []
    for hole in rotated.interiors:
        snapped_holes.append(_snap_ring(list(hole.coords)))
    try:
        snapped = Polygon(snapped_ext, snapped_holes)
    except Exception:
        return simp
    if not snapped.is_valid:
        snapped = snapped.buffer(0)
    if snapped.is_empty or snapped.area < min_area_m2:
        return simp

    # 5. Rotate back
    final = rotate(snapped, angle, origin=centroid)
    if not final.is_valid:
        final = final.buffer(0)
    if final.is_empty:
        return simp
    return final


def ortho_snap_gdf(gdf: gpd.GeoDataFrame,
                   simplify_tol: float = 0.5,
                   min_area_m2: float = 5.0) -> gpd.GeoDataFrame:
    """Apply ortho_snap_polygon to every geometry in a metric-CRS GeoDataFrame."""
    out = gdf.copy()
    new_geoms = []
    for g in out.geometry.values:
        snapped = ortho_snap_polygon(g, simplify_tol, min_area_m2)
        new_geoms.append(snapped)
    out["geometry"] = new_geoms
    out = out[out.geometry.notna() & ~out.geometry.is_empty].copy()
    return out
