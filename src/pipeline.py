"""End-to-end pipeline for one scene.

Flow:
  1. open scene, iterate over tiles with overlap
  2. for each tile:
     a. read RGB+alpha
     b. compute land-cover masks (vegetation, shadow, soil)
     c. SLIC segmentation
     d. extract features per segment
     e. (training mode) label segments via Overture overlap
  3. concatenate features across tiles
  4. write to parquet/CSV plus segment polygons GeoJSON

This is the "data preparation" half of the pipeline. Training and
inference scripts run on the resulting per-segment dataset.
"""

from __future__ import annotations
import logging
from pathlib import Path
import time
from typing import Optional

import numpy as np
import pandas as pd
import geopandas as gpd
import rasterio
from rasterio.windows import Window

from src.io.raster import read_rgba, scene_metadata
from src.tile import iter_tiles, count_tiles
from src.features.masks import composite_landcover
from src.features.segmentation import segment_tile_slic, labels_to_polygons
from src.features.segment_features import extract_features, ALL_FEATURES
from src.labeling import label_segments

log = logging.getLogger(__name__)


def process_scene(scene_path: str | Path,
                  scene_id: str,
                  city: str,
                  buildings_ref: Optional[gpd.GeoDataFrame] = None,
                  out_dir: str | Path = "outputs",
                  tile_size: int = 1024,
                  overlap: int = 128,
                  n_segments_per_tile: int = 200,
                  compactness: float = 15.0,
                  verbose: bool = True) -> dict:
    """Process a single scene tile-by-tile and write per-segment data.

    Outputs (under out_dir):
      outputs/segments/<scene_id>.geojson    -- one row per segment
      outputs/segments/<scene_id>.parquet    -- feature matrix

    Returns a dict with summary stats.
    """
    out_dir = Path(out_dir)
    seg_out = out_dir / "segments"
    seg_out.mkdir(parents=True, exist_ok=True)

    scene_path = Path(scene_path)
    meta = scene_metadata(scene_path)
    if verbose:
        log.info("[%s] %dx%d px, CRS %s", scene_id, meta['width'], meta['height'], meta['crs'])

    n_tiles = count_tiles(meta["width"], meta["height"], tile_size, overlap)
    if verbose:
        log.info("  Tiling: %dpx tiles with %dpx overlap -> %d tiles",
                 tile_size, overlap, n_tiles)

    # If we got reference buildings, restrict to this scene to speed up STRtree
    ref_local = None
    if buildings_ref is not None and len(buildings_ref) > 0:
        if "scene_id" in buildings_ref.columns:
            ref_local = buildings_ref[
                buildings_ref["scene_id"] == scene_id
            ].copy()
        else:
            ref_local = buildings_ref.copy()
        if verbose:
            log.info("  Reference labels available: %d buildings", len(ref_local))

    feature_frames = []
    seg_polygon_frames = []
    t_total_start = time.time()

    for tile_idx, win in enumerate(iter_tiles(meta["width"], meta["height"],
                                              tile_size, overlap)):
        try:
            rgb, valid, transform, crs = read_rgba(scene_path, window=win)
        except Exception as e:
            log.warning("tile %d: read error %s, skip", tile_idx, e)
            continue
        if valid.sum() < 1000:
            continue
        if rgb[..., :3].mean() < 5:
            continue

        masks = composite_landcover(rgb, valid=valid)
        try:
            labels = segment_tile_slic(rgb, valid=valid,
                                       n_segments=n_segments_per_tile,
                                       compactness=compactness)
        except Exception as e:
            log.warning("tile %d: SLIC error %s, skip", tile_idx, e)
            continue
        if labels.max() == 0:
            continue

        try:
            df = extract_features(rgb, labels,
                                  veg_mask=masks["vegetation"],
                                  sha_mask=masks["shadow"],
                                  soi_mask=masks["bare_soil"])
        except Exception as e:
            log.warning("tile %d: feature error %s, skip", tile_idx, e)
            continue

        # Polygons for the tile (use scene's full transform via window_transform)
        seg_gdf = labels_to_polygons(labels, transform=transform, crs=crs)
        # Make segment_id unique across tiles by tagging tile_idx
        seg_gdf["tile_idx"] = tile_idx
        seg_gdf["segment_id"] = (tile_idx * 100000 + seg_gdf["segment_id"]).astype(int)
        df["tile_idx"] = tile_idx
        df["segment_id"] = (tile_idx * 100000 + df["segment_id"]).astype(int)

        # Weak labeling against reference buildings (Overture)
        if ref_local is not None and len(ref_local) > 0:
            df = label_segments(seg_gdf, ref_local, df)

        df["scene_id"] = scene_id
        df["city"] = city
        seg_gdf["scene_id"] = scene_id
        seg_gdf["city"] = city

        feature_frames.append(df)
        seg_polygon_frames.append(seg_gdf)

        if verbose and (tile_idx + 1) % 25 == 0:
            elapsed = time.time() - t_total_start
            eta = elapsed / (tile_idx + 1) * (n_tiles - tile_idx - 1)
            log.info("  tile %d/%d, %.0fs elapsed, ETA %.0fs",
                     tile_idx + 1, n_tiles, elapsed, eta)

    if not feature_frames:
        log.warning("no features extracted for %s", scene_id)
        return {"scene_id": scene_id, "n_segments": 0}

    all_features = pd.concat(feature_frames, ignore_index=True)
    all_segments = gpd.GeoDataFrame(
        pd.concat(seg_polygon_frames, ignore_index=True),
        crs=seg_polygon_frames[0].crs,
    )

    feat_path = seg_out / f"{scene_id}.parquet"
    seg_path = seg_out / f"{scene_id}.geojson"
    all_features.to_parquet(feat_path, index=False)
    all_segments.to_file(seg_path, driver="GeoJSON")

    summary = {
        "scene_id": scene_id,
        "n_tiles_total": n_tiles,
        "n_tiles_processed": len(feature_frames),
        "n_segments": len(all_features),
        "n_pos_label": int((all_features.get("label", -1) == 1).sum()) if "label" in all_features.columns else None,
        "n_neg_label": int((all_features.get("label", -1) == 0).sum()) if "label" in all_features.columns else None,
        "elapsed_s": round(time.time() - t_total_start, 1),
        "features_path": str(feat_path),
        "segments_path": str(seg_path),
    }
    if verbose:
        log.info("Done %s: %d segments (pos=%s, neg=%s) in %.0fs",
                 scene_id, summary['n_segments'],
                 summary['n_pos_label'], summary['n_neg_label'],
                 summary['elapsed_s'])
    return summary
