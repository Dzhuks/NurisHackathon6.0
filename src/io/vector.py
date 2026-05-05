"""Vector I/O — TZ-compliant GeoJSON and GeoPackage writers.

TZ §5 mandatory schema for each feature:
  - id          : unique identifier (string)
  - class       : category
  - confidence  : 0–100 score
  - source      : source scene id
  - geometry    : Point or Polygon
  - optional    : area_m2, length_m, date, change_flag

Convention:
- Compute area_m2 / length_m in the scene's UTM CRS (metric).
- Export GeoJSON in EPSG:4326 (RFC 7946).
- GeoPackage may stay in UTM or 4326; we pick 4326 for consistency.
"""
from __future__ import annotations
from pathlib import Path
from typing import Optional
import uuid

import geopandas as gpd
import pandas as pd

from src.io.raster import utm_epsg_for_scene


REQUIRED_COLS = ["id", "class", "confidence", "source", "area_m2", "length_m",
                 "date", "change_flag"]


def _ensure_id(gdf: gpd.GeoDataFrame, prefix: str = "f") -> gpd.GeoDataFrame:
    if "id" not in gdf.columns or gdf["id"].isna().any():
        gdf = gdf.copy()
        gdf["id"] = [f"{prefix}_{i:06d}" for i in range(len(gdf))]
    return gdf


def add_metric_attrs(gdf: gpd.GeoDataFrame, scene_path: Optional[str] = None,
                     utm_epsg: Optional[int] = None) -> gpd.GeoDataFrame:
    """Add area_m2 and length_m attributes computed in UTM.

    Either pass scene_path (we'll auto-pick UTM zone) or utm_epsg directly.
    """
    if utm_epsg is None and scene_path is not None:
        utm_epsg = utm_epsg_for_scene(scene_path)
    if utm_epsg is None:
        raise ValueError("Need either utm_epsg or scene_path")

    g_utm = gdf.to_crs(epsg=utm_epsg)
    out = gdf.copy()
    out["area_m2"] = g_utm.geometry.area.round(2)
    # length_m: for polygons it's perimeter; for lines it's length
    out["length_m"] = g_utm.geometry.length.round(2)
    return out


def to_tz_schema(gdf: gpd.GeoDataFrame, *,
                 source: str,
                 default_class: str = "building",
                 default_confidence: int = 80,
                 date: Optional[str] = None,
                 change_flag: Optional[str] = None,
                 id_prefix: str = "f") -> gpd.GeoDataFrame:
    """Make sure the dataframe has all TZ §5 columns. Missing fields filled with defaults."""
    out = gdf.copy()
    if "class" not in out.columns:
        out["class"] = default_class
    if "confidence" not in out.columns:
        out["confidence"] = default_confidence
    if "source" not in out.columns:
        out["source"] = source
    if "date" not in out.columns:
        out["date"] = date
    if "change_flag" not in out.columns:
        out["change_flag"] = change_flag
    out = _ensure_id(out, prefix=id_prefix)
    # Reorder columns: required first, then geometry last
    extra = [c for c in out.columns if c not in REQUIRED_COLS + ["geometry"]]
    cols = [c for c in REQUIRED_COLS if c in out.columns] + extra + ["geometry"]
    return out[cols]


def write_geojson(gdf: gpd.GeoDataFrame, path: Path | str) -> None:
    """Write to GeoJSON in EPSG:4326 (RFC 7946 compliant)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    g = gdf.to_crs(epsg=4326) if gdf.crs and gdf.crs.to_epsg() != 4326 else gdf
    if path.exists():
        path.unlink()
    g.to_file(path, driver="GeoJSON")


def write_geopackage(gdf: gpd.GeoDataFrame, path: Path | str,
                     layer: str, in_4326: bool = True) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if in_4326 and gdf.crs and gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)
    gdf.to_file(path, driver="GPKG", layer=layer)


def fix_geometries(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Fix invalid geometries via buffer(0). Drop empties."""
    out = gdf.copy()
    bad = ~out.geometry.is_valid
    if bad.any():
        out.loc[bad, "geometry"] = out.loc[bad, "geometry"].buffer(0)
    out = out[~out.geometry.is_empty].copy()
    return out
