"""Finalize TZ-compliant outputs.

Combines per-scene predictions (buildings + cars) plus rule-based
landcover (vegetation + bare_soil) into TZ §5 GeoJSON layers and
TZ §4.2 summary CSV per scene + overall.

Input expectations:
  outputs/geojson/<scene_id>_buildings.geojson  (from script 08)
  outputs/geojson/<scene_id>_cars.geojson       (from script 09)
  outputs/segments/<scene_id>.geojson           (for landcover, from
    rule-based mask fractions stored in features.parquet)

Outputs (everything goes into outputs/geojson/):
  Per-scene (60 files):
    <scene_id>_buildings.geojson  (overwritten with city/scene_id cols)
    <scene_id>_cars.geojson       (same)
    <scene_id>_landcover.geojson  (created here)
  Per-type (one file per class, aggregated across all scenes):
    building_<cls>.geojson        — house, apartment_block, school,
                                    hospital, religious, civic, commercial,
                                    industrial, outbuilding, …
    landcover_<cls>.geojson       — vegetation, bare_soil
    cars.geojson                  — single class so just one file
  Combined:
    all.geojson                   — every feature from every class in one
                                     FeatureCollection (Polygon + Point mix)
  Summaries:
    buildings_summary.csv         — per-scene house/apt counts + density
    cars_summary.csv
    landcover_summary.csv
  At outputs/ root:
    results.gpkg                  — multi-layer for QGIS
    scene_metrics.csv             — TZ §4.2 cross-class numbers
"""
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.io.vector import to_tz_schema, write_geojson, write_geopackage
from src.io.raster import utm_epsg_for_scene
from src.logging_config import setup_logger
log = setup_logger("08_finalize_outputs")


def landcover_for_scene(scene_id: str,
                        buildings: gpd.GeoDataFrame | None = None,
                        utm_epsg: int | None = None
                        ) -> gpd.GeoDataFrame:
    """Build a vegetation / bare_soil polygon layer from rule-based mask
    fractions stored alongside SLIC segments.

    Building priority: if `buildings` is provided, every landcover polygon
    has the union of predicted buildings subtracted from it. This prevents
    pixels classified as a building from also appearing under bare_soil
    (terracotta roofs satisfy R≥G>B and intensity rules, so they otherwise
    leak into the soil layer).
    """
    feat_path = ROOT / "outputs" / "segments" / f"{scene_id}.parquet"
    seg_path = ROOT / "outputs" / "segments" / f"{scene_id}.geojson"
    if not feat_path.exists() or not seg_path.exists():
        return gpd.GeoDataFrame(columns=["class", "confidence", "geometry"], crs="EPSG:4326")
    df = pd.read_parquet(feat_path)
    seg = gpd.read_file(seg_path)
    rows = []
    veg_thr = 0.5
    soi_thr = 0.5
    veg_seg = df.loc[df["frac_vegetation"] >= veg_thr, "segment_id"]
    soi_seg = df.loc[df["frac_soil"] >= soi_thr, "segment_id"]
    veg_g = seg[seg["segment_id"].isin(veg_seg)].copy()
    soi_g = seg[seg["segment_id"].isin(soi_seg)].copy()
    if not veg_g.empty:
        veg_g["class"] = "vegetation"
        veg_g["confidence"] = (df.set_index("segment_id")
                                  .loc[veg_g["segment_id"], "frac_vegetation"]
                                  .values * 100).round().astype(int)
        rows.append(veg_g[["class", "confidence", "geometry"]])
    if not soi_g.empty:
        soi_g["class"] = "bare_soil"
        soi_g["confidence"] = (df.set_index("segment_id")
                                  .loc[soi_g["segment_id"], "frac_soil"]
                                  .values * 100).round().astype(int)
        rows.append(soi_g[["class", "confidence", "geometry"]])
    if not rows:
        return gpd.GeoDataFrame(columns=["class", "confidence", "geometry"], crs="EPSG:4326")
    out = gpd.GeoDataFrame(pd.concat(rows, ignore_index=True), crs=seg.crs)

    # ---- Building priority: subtract building polygons from landcover ----
    if buildings is not None and not buildings.empty:
        # Work in metric CRS to avoid degree-unit artefacts
        target_epsg = utm_epsg if utm_epsg is not None else 3857
        bld_m = buildings.to_crs(epsg=target_epsg)
        # Fix invalid geometries before union (buildings are dissolved
        # SLIC blobs, sometimes self-intersecting after reprojection).
        bld_geoms = [
            (g if g.is_valid else g.buffer(0))
            for g in bld_m.geometry.values
            if g is not None and not g.is_empty
        ]
        try:
            bld_union = unary_union(bld_geoms)
        except Exception:
            # Last-resort fallback: tiny positive buffer to repair
            bld_union = unary_union([g.buffer(0.01) for g in bld_geoms])
        if not bld_union.is_empty:
            out_m = out.to_crs(epsg=target_epsg)

            def _safe_diff(g):
                if g is None or g.is_empty:
                    return g
                if not g.is_valid:
                    g = g.buffer(0)
                try:
                    return g.difference(bld_union)
                except Exception:
                    try:
                        return g.buffer(0).difference(bld_union.buffer(0))
                    except Exception:
                        return g  # leave unchanged on persistent failure
            out_m["geometry"] = out_m.geometry.apply(_safe_diff)
            out_m = out_m[out_m.geometry.notna() & ~out_m.geometry.is_empty].copy()
            # Drop tiny slivers that survived the difference (<5 m²)
            out_m = out_m[out_m.geometry.area > 5.0].copy()
            out = out_m.to_crs(epsg=4326)
    return out


def main():
    aoi = gpd.read_file(ROOT / "aoi" / "scenes.geojson")
    out_root = ROOT / "outputs"
    geo_dir = out_root / "geojson"
    geo_dir.mkdir(parents=True, exist_ok=True)
    gpkg_path = out_root / "results.gpkg"
    if gpkg_path.exists():
        gpkg_path.unlink()

    all_buildings = []
    all_cars = []
    all_landcover = []
    metrics_rows = []

    for _, row in aoi.iterrows():
        sid = row["scene_id"]
        scene_path = ROOT / row["file"]
        utm_epsg = utm_epsg_for_scene(scene_path)
        # Buildings
        bld_path = geo_dir / f"{sid}_buildings.geojson"
        if bld_path.exists():
            bld = gpd.read_file(bld_path)
        else:
            bld = gpd.GeoDataFrame(columns=["class", "confidence", "geometry"], crs="EPSG:4326")
        # Cars
        car_path = geo_dir / f"{sid}_cars.geojson"
        if car_path.exists():
            car = gpd.read_file(car_path)
        else:
            car = gpd.GeoDataFrame(columns=["class", "confidence", "geometry"], crs="EPSG:4326")
        # Landcover from segment fractions, with building priority enforced.
        lcv = landcover_for_scene(sid, buildings=bld, utm_epsg=utm_epsg)

        # Per-scene exports (overwrite buildings/cars with city+scene_id cols;
        # landcover is created here)
        write_geojson(bld, geo_dir / f"{sid}_buildings.geojson")
        write_geojson(car, geo_dir / f"{sid}_cars.geojson")
        write_geojson(lcv, geo_dir / f"{sid}_landcover.geojson")

        # Tag with scene_id, accumulate
        for g in (bld, car, lcv):
            if not g.empty:
                g["scene_id"] = sid
                g["city"] = row["city"]
        if not bld.empty:
            all_buildings.append(bld)
        if not car.empty:
            all_cars.append(car)
        if not lcv.empty:
            all_landcover.append(lcv)

        # Metrics per scene (TZ §4.2)
        aoi_area_km2 = float(row["area_km2"])
        n_house = int((bld["class"] == "house").sum()) if not bld.empty else 0
        n_apt = int((bld["class"] == "apartment_block").sum()) if not bld.empty else 0
        bld_area = float(bld["area_m2"].sum()) if (not bld.empty and "area_m2" in bld.columns) else 0.0
        n_cars = len(car)
        # Vegetation / soil area in m^2 (compute in UTM)
        veg_area = 0.0
        soi_area = 0.0
        if not lcv.empty:
            lcv_utm = lcv.to_crs(epsg=utm_epsg)
            veg_area = float(lcv_utm[lcv_utm["class"] == "vegetation"].geometry.area.sum())
            soi_area = float(lcv_utm[lcv_utm["class"] == "bare_soil"].geometry.area.sum())
        metrics_rows.append({
            "scene_id": sid,
            "city": row["city"],
            "split": row["split"],
            "aoi_area_km2": aoi_area_km2,
            "n_house": n_house,
            "n_apartment_block": n_apt,
            "n_buildings_total": n_house + n_apt,
            "buildings_density_per_km2": round((n_house + n_apt) / aoi_area_km2, 1) if aoi_area_km2 > 0 else 0.0,
            "buildings_total_area_m2": round(bld_area, 1),
            "buildings_share_of_aoi_pct": round(100 * bld_area / (aoi_area_km2 * 1e6 + 1e-9), 2),
            "n_cars": n_cars,
            "cars_density_per_km2": round(n_cars / aoi_area_km2, 1) if aoi_area_km2 > 0 else 0.0,
            "vegetation_area_m2": round(veg_area, 1),
            "vegetation_share_pct": round(100 * veg_area / (aoi_area_km2 * 1e6 + 1e-9), 2),
            "bare_soil_area_m2": round(soi_area, 1),
            "bare_soil_share_pct": round(100 * soi_area / (aoi_area_km2 * 1e6 + 1e-9), 2),
        })

    # ----- Combined per-family exports (buildings, cars, landcover) -----
    cb = cc = cl = None
    if all_buildings:
        cb = gpd.GeoDataFrame(pd.concat(all_buildings, ignore_index=True), crs="EPSG:4326")
        write_geopackage(cb, gpkg_path, "buildings")
    if all_cars:
        cc = gpd.GeoDataFrame(pd.concat(all_cars, ignore_index=True), crs="EPSG:4326")
        write_geopackage(cc, gpkg_path, "cars")
        # Cars only have a single class — write a single tidy file.
        write_geojson(cc, geo_dir / "cars.geojson")
    if all_landcover:
        cl = gpd.GeoDataFrame(pd.concat(all_landcover, ignore_index=True), crs="EPSG:4326")
        write_geopackage(cl, gpkg_path, "landcover")
    write_geopackage(aoi, gpkg_path, "aoi")

    # ----- Per-type splits across all scenes (one file per class) -----
    # Buildings: building_<class>.geojson (e.g., building_house.geojson)
    if cb is not None and not cb.empty and "class" in cb.columns:
        for cls in sorted(cb["class"].dropna().unique()):
            sub = cb[cb["class"] == cls]
            if sub.empty:
                continue
            write_geojson(sub, geo_dir / f"building_{cls}.geojson")
        log.info("Wrote per-type building files: building_<class>.geojson")
    # Landcover: landcover_<class>.geojson
    if cl is not None and not cl.empty and "class" in cl.columns:
        for cls in sorted(cl["class"].dropna().unique()):
            sub = cl[cl["class"] == cls]
            if sub.empty:
                continue
            write_geojson(sub, geo_dir / f"landcover_{cls}.geojson")
        log.info("Wrote per-type landcover files: landcover_<class>.geojson")

    # ----- Combined "all.geojson" — every feature from every class -----
    # GeoJSON FeatureCollection allows mixed geometry (Polygon + Point).
    parts = [g for g in (cb, cc, cl) if g is not None and not g.empty]
    if parts:
        all_combined = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs="EPSG:4326")
        write_geojson(all_combined, geo_dir / "all.geojson")

    # Per-class summaries (count, area, share by scene)
    metrics_df = pd.DataFrame(metrics_rows)
    bld_cols = ["scene_id", "city", "split", "aoi_area_km2", "n_house",
                "n_apartment_block", "n_buildings_total",
                "buildings_density_per_km2", "buildings_total_area_m2",
                "buildings_share_of_aoi_pct"]
    car_cols = ["scene_id", "city", "split", "aoi_area_km2", "n_cars",
                "cars_density_per_km2"]
    lcv_cols = ["scene_id", "city", "split", "aoi_area_km2",
                "vegetation_area_m2", "vegetation_share_pct",
                "bare_soil_area_m2", "bare_soil_share_pct"]
    metrics_df[bld_cols].to_csv(geo_dir / "buildings_summary.csv", index=False)
    metrics_df[car_cols].to_csv(geo_dir / "cars_summary.csv", index=False)
    metrics_df[lcv_cols].to_csv(geo_dir / "landcover_summary.csv", index=False)

    # Cross-class TZ §4.2 metrics at outputs/ root
    out_csv = ROOT / "outputs" / "scene_metrics.csv"
    metrics_df.to_csv(out_csv, index=False)
    for line in metrics_df.to_string().splitlines():
        log.info("%s", line)
    log.info("Wrote per-class summaries to outputs/geojson/{buildings,cars,landcover}_summary.csv")
    log.info("Wrote scene metrics to %s", out_csv)
    log.info("Wrote multi-layer GeoPackage: %s", gpkg_path)
    log.info("Wrote unified all.geojson with %d features", len(all_combined) if parts else 0)


if __name__ == "__main__":
    main()
