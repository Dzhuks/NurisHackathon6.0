"""Detect cars on all 20 scenes using a pretrained YOLOv8 (DOTA-aerial weights).

Strategy:
  * Use ultralytics YOLOv8 pretrained on COCO as a strong starting point.
    DOTA-specific weights (oriented bounding box) would be ideal but require
    extra setup; we report COCO-vehicle detection ('car', 'truck', 'bus')
    in our final output.
  * Per scene: tile the raster, run YOLO inference per tile, project boxes
    back to lon/lat using the tile's affine transform, then dedup/NMS
    across overlapping tiles.

Output: outputs/geojson/<scene_id>_cars.geojson — Point layer
with TZ-compliant attributes.
"""
from pathlib import Path
import sys
import time

import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point
from shapely.strtree import STRtree
import rasterio
from rasterio.windows import Window

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.io.raster import read_rgba, scene_metadata
from src.tile import iter_tiles
from src.io.vector import write_geojson, to_tz_schema
from src.logging_config import setup_logger
log = setup_logger("07_run_yolo_cars")

# Lazy import of YOLO so script can be loaded without ultralytics
def _get_model():
    from ultralytics import YOLO
    # YOLOv8s-OBB pretrained on DOTA-v1 — proper aerial-imagery classes
    # including 'small vehicle' (=car) and 'large vehicle' (=bus/truck).
    return YOLO("yolov8s-obb.pt")


# DOTA class IDs we treat as "car"-family
CAR_CLASSES = {10: "car", 9: "large_vehicle"}  # 10=small vehicle, 9=large vehicle


def detect_in_scene(scene_path: Path, scene_id: str, model,
                    tile_size: int = 1024, overlap: int = 128,
                    conf_thr: float = 0.25, nms_dist_m: float = 2.0):
    meta = scene_metadata(scene_path)
    transform = meta["transform"]
    detections = []  # list of (lon, lat, conf, cls)

    n_tiles = 0
    t0 = time.time()
    for win in iter_tiles(meta["width"], meta["height"], tile_size, overlap):
        try:
            rgb, valid, t_local, _ = read_rgba(scene_path, window=win)
        except Exception:
            continue
        if valid.sum() < 1000 or rgb[..., :3].mean() < 5:
            continue
        n_tiles += 1
        # YOLO expects HWC, BGR? It actually accepts RGB ndarray
        results = model.predict(rgb, imgsz=1024, conf=conf_thr,
                                 verbose=False, device="cpu")
        for r in results:
            # OBB models put detections in r.obb instead of r.boxes
            obb = getattr(r, "obb", None)
            if obb is None or len(obb) == 0:
                continue
            cls_arr = obb.cls.cpu().numpy().astype(int)
            conf_arr = obb.conf.cpu().numpy()
            # xyxyxyxy returns [N, 4, 2] polygon corner coords; use centroid
            xyxyxyxy = obb.xyxyxyxy.cpu().numpy()
            for cls_id, conf, box4 in zip(cls_arr, conf_arr, xyxyxyxy):
                if cls_id not in CAR_CLASSES:
                    continue
                cx_pix = float(box4[:, 0].mean())
                cy_pix = float(box4[:, 1].mean())
                lon, lat = t_local * (cx_pix, cy_pix)
                detections.append((lon, lat, float(conf), CAR_CLASSES[cls_id]))

    if not detections:
        return gpd.GeoDataFrame(columns=["confidence", "cls", "geometry"], crs="EPSG:4326")

    arr = np.array([(d[0], d[1], d[2]) for d in detections])
    cls_arr = [d[3] for d in detections]
    pts = [Point(x, y) for x, y, _ in arr]
    gdf = gpd.GeoDataFrame({
        "confidence": (arr[:, 2] * 100).round().astype(int),
        "cls_label": cls_arr,
        "geometry": pts,
    }, crs="EPSG:4326")

    # NMS-by-distance: dedup across overlapping tiles. Convert to a meter CRS.
    from src.io.raster import utm_epsg_for_scene
    utm_epsg = utm_epsg_for_scene(scene_path)
    g_utm = gdf.to_crs(epsg=utm_epsg)
    coords = np.column_stack([g_utm.geometry.x.values, g_utm.geometry.y.values])
    confs = gdf["confidence"].values
    keep_idx = _greedy_nms_points(coords, confs, radius_m=nms_dist_m)
    gdf = gdf.iloc[keep_idx].reset_index(drop=True)
    return gdf


def _greedy_nms_points(coords: np.ndarray, confs: np.ndarray, radius_m: float):
    """Keep the highest-confidence point in each radius_m cluster."""
    order = np.argsort(-confs)
    kept = []
    suppressed = np.zeros(len(coords), dtype=bool)
    for i in order:
        if suppressed[i]:
            continue
        kept.append(i)
        # suppress neighbors within radius
        d = np.linalg.norm(coords - coords[i], axis=1)
        suppressed |= (d < radius_m)
    return sorted(kept)


def main():
    log.info("Loading YOLOv8s-OBB...")
    model = _get_model()
    log.info("Model loaded.")

    aoi = gpd.read_file(ROOT / "aoi" / "scenes.geojson")
    out_dir = ROOT / "outputs" / "geojson"
    out_dir.mkdir(parents=True, exist_ok=True)

    summaries = []
    for _, row in aoi.iterrows():
        scene_id = row["scene_id"]
        log.info("=== %s ===", scene_id)
        t0 = time.time()
        gdf = detect_in_scene(ROOT / row["file"], scene_id, model)
        n_total = len(gdf)
        if n_total == 0:
            log.info("[%s] no cars found", scene_id)
            summaries.append({"scene_id": scene_id, "n_cars": 0,
                              "geojson_path": None})
            continue
        gdf["source"] = f"{scene_id}.tif"
        gdf["date"] = "2026-04-01"
        gdf["change_flag"] = None
        gdf["class"] = "car"
        out_gdf = to_tz_schema(
            gdf[["class", "confidence", "source", "geometry"]],
            source=f"{scene_id}.tif",
            default_class="car",
            id_prefix=f"car_{scene_id}",
        )
        out_path = out_dir / f"{scene_id}_cars.geojson"
        write_geojson(out_gdf, out_path)
        elapsed = time.time() - t0
        log.info("[%s] -> %d cars in %.0fs", scene_id, n_total, elapsed)
        summaries.append({
            "scene_id": scene_id,
            "n_cars": n_total,
            "elapsed_s": round(elapsed, 1),
            "geojson_path": str(out_path.relative_to(ROOT)),
        })

    df = pd.DataFrame(summaries)
    out_csv = ROOT / "outputs" / "geojson" / "cars_summary.csv"
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_csv, index=False)
    log.info("Saved -> %s", out_csv)
    for line in df.to_string().splitlines():
        log.info("%s", line)


if __name__ == "__main__":
    main()
