"""Run trained U-Net on all 20 scenes -> per-scene polygon GeoJSONs.

For each scene:
  1. Sliding-window inference (256x256 patches, stride 192).
  2. Vectorise binary mask to polygons (in scene CRS = EPSG:4326).
  3. Reproject to UTM, simplify (1 m tolerance), filter by area, dissolve
     by adjacency, validate.
  4. Sub-classify each polygon via Overture overlap + footprint area
     using the SAME taxonomy as scripts/08_predict_buildings.py.
  5. Write outputs/geojson/<scene>_buildings.geojson with TZ-compliant
     attributes.

This script REPLACES the SLIC+RF predictor for the buildings layer.
Cars (script 09) and landcover are unchanged; just rerun script 10 to
finalise after this step.
"""
from pathlib import Path
import sys
import time

import numpy as np
import pandas as pd
import geopandas as gpd
import torch
from shapely.ops import unary_union
from shapely.geometry import Polygon, MultiPolygon
from shapely.strtree import STRtree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.unet.model import build_unet
from src.unet.predict import predict_scene
from src.unet.train import get_device
from src.io.raster import utm_epsg_for_scene
from src.io.vector import to_tz_schema, write_geojson, fix_geometries
from src.postprocess.ortho_snap import ortho_snap_gdf
from src.postprocess.subclassify import subclass_from_overture
from src.logging_config import setup_logger

log = setup_logger("06_predict_unet")


MIN_AREA_M2 = 30.0
# No maximum cap — large industrial / shopping / civic complexes can
# legitimately exceed any fixed threshold we would pick.
SIMPLIFY_M = 1.0


def process_scene(scene_id: str, scene_path: Path,
                  model, device, overture_clipped: gpd.GeoDataFrame):
    t0 = time.time()
    polys, _, _ = predict_scene(model, scene_path, device=device,
                                 patch_size=256, stride=192,
                                 threshold=0.5, batch_size=16,
                                 log=log.info)
    log.info("[%s] %d raw polygons", scene_id, len(polys))
    if not polys:
        return _empty(scene_id)

    utm_epsg = utm_epsg_for_scene(scene_path)

    # Reproject to metric CRS, snap zigzag boundaries to right angles
    gdf = gpd.GeoDataFrame(geometry=polys, crs="EPSG:4326").to_crs(utm_epsg)
    gdf = ortho_snap_gdf(gdf, simplify_tol=SIMPLIFY_M, min_area_m2=5.0)
    # Filter out only the noise-tier (very small) polygons.
    a = gdf.geometry.area
    gdf = gdf[a >= MIN_AREA_M2].reset_index(drop=True)
    log.info("[%s] %d polygons after ortho-snap + area filter",
             scene_id, len(gdf))
    if gdf.empty:
        return _empty(scene_id)

    # Sub-classify each polygon via Overture overlap
    overture_local = overture_clipped[overture_clipped["scene_id"] == scene_id]
    if not overture_local.empty:
        ov_utm = overture_local.to_crs(utm_epsg).reset_index(drop=True)
        ov_tree = STRtree(list(ov_utm.geometry.values))
    else:
        ov_utm = None
        ov_tree = None

    final_classes = []
    final_matched = []
    for poly in gdf.geometry:
        a_m2 = poly.area
        ov_row = None
        if ov_tree is not None:
            best_overlap = 0.0
            for oi in ov_tree.query(poly):
                oi = int(oi)
                inter = poly.intersection(ov_utm.geometry.iloc[oi]).area
                if inter > best_overlap:
                    best_overlap = inter
                    raw = ov_utm.iloc[oi].to_dict()
                    ov_row = {
                        "overture_subtype": raw.get("subtype"),
                        "overture_class": raw.get("class"),
                        "num_floors": raw.get("num_floors"),
                        "height": raw.get("height"),
                    }
            if best_overlap / a_m2 < 0.3:
                ov_row = None
        sub = subclass_from_overture(ov_row, a_m2)
        final_classes.append(sub)
        final_matched.append(1 if ov_row else 0)

    out_gdf = gpd.GeoDataFrame({
        "class": final_classes,
        "confidence": 80,
        "overture_matched": final_matched,
        "geometry": gdf.geometry.values,
    }, crs=f"EPSG:{utm_epsg}")
    out_gdf = fix_geometries(out_gdf)
    out_gdf["area_m2"] = out_gdf.geometry.area.round(2)
    out_gdf["length_m"] = out_gdf.geometry.length.round(2)
    out_gdf["source"] = f"{scene_id}.tif"
    out_gdf["date"] = "2026-04-01"
    out_gdf["change_flag"] = None

    out_gdf = to_tz_schema(out_gdf, source=f"{scene_id}.tif",
                           default_class="building",
                           default_confidence=80,
                           id_prefix=f"bld_{scene_id}")
    out_path = ROOT / "outputs" / "geojson" / f"{scene_id}_buildings.geojson"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    write_geojson(out_gdf, out_path)
    elapsed = time.time() - t0

    n_house = int((out_gdf["class"] == "house").sum())
    n_apt = int((out_gdf["class"] == "apartment_block").sum())
    log.info("[%s] -> %d buildings (house=%d, apt=%d), %.0fs",
             scene_id, len(out_gdf), n_house, n_apt, elapsed)

    return {"scene_id": scene_id,
            "n_buildings_total": len(out_gdf),
            "n_house": n_house, "n_apartment_block": n_apt,
            "total_area_m2": float(out_gdf["area_m2"].sum()),
            "mean_area_m2": float(out_gdf["area_m2"].mean()) if len(out_gdf) else 0,
            "mean_confidence": float(out_gdf["confidence"].mean()) if len(out_gdf) else 0,
            "elapsed_s": round(elapsed, 1),
            "geojson_path": str(out_path.relative_to(ROOT))}


def _empty(scene_id):
    return {"scene_id": scene_id, "n_buildings_total": 0, "n_house": 0,
            "n_apartment_block": 0, "total_area_m2": 0, "mean_area_m2": 0,
            "mean_confidence": 0, "elapsed_s": 0, "geojson_path": None}


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", default="outputs/models/unet_best.pt")
    ap.add_argument("--encoder", default="efficientnet-b0")
    args = ap.parse_args()

    device = get_device()
    log.info("Device: %s", device)
    model = build_unet(encoder_name=args.encoder, in_channels=3, classes=1)
    state = torch.load(ROOT / args.checkpoint, map_location=device)
    model.load_state_dict(state)
    model.to(device).eval()
    log.info("Loaded %s", args.checkpoint)

    aoi = gpd.read_file(ROOT / "aoi" / "scenes.geojson")
    overture_clipped = gpd.read_file(ROOT / "aoi" / "overture" / "buildings_clipped.geojson")

    summaries = []
    t0 = time.time()
    for _, row in aoi.iterrows():
        sid = row["scene_id"]
        log.info("=== %s (%s) ===", sid, row["split"])
        s = process_scene(sid, ROOT / row["file"], model, device, overture_clipped)
        s["split"] = row["split"]
        s["city"] = row["city"]
        summaries.append(s)
    df = pd.DataFrame(summaries)
    out_csv = ROOT / "outputs" / "geojson" / "buildings_summary.csv"
    df.to_csv(out_csv, index=False)
    log.info("Total time: %.0fs", time.time() - t0)
    log.info("Saved -> %s", out_csv)


if __name__ == "__main__":
    main()
