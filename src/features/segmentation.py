"""Image segmentation for GEOBIA.

We replace the Chen 2018 watershed+merge pipeline with SLIC superpixels
because it (a) is implemented and well-tested in skimage, (b) gives more
controllable scale via `n_segments`, and (c) is faster on CPU. Both
methods serve the same purpose: produce homogeneous regions whose
features we then classify.

For a 1024×1024 tile at ~5 cm/pixel:
  n_segments=200, compactness=15 => ~5×5 m segments, well-suited to
  small structures (cars) up to medium roof sections.

The approach matches GEOBIA philosophy in:
  * Hossain & Chen (2024) — they used watershed+RAG merging
  * Chen, Li, Li (2018) — same family
"""
from __future__ import annotations
import numpy as np
from skimage.segmentation import slic
from skimage.measure import regionprops, label as relabel
from rasterio.features import shapes as rio_shapes
from shapely.geometry import shape, Polygon
import geopandas as gpd


def segment_tile_slic(rgb: np.ndarray, valid: np.ndarray | None = None,
                      n_segments: int = 200, compactness: float = 15.0,
                      sigma: float = 1.0) -> np.ndarray:
    """SLIC superpixels on RGB image. Returns int label array (H, W).

    Labels start at 1; nodata pixels get label 0.
    """
    img = rgb.astype(np.float32) / 255.0
    # mask=valid tells SLIC to skip nodata pixels; output has 0 there.
    if valid is None:
        valid = np.ones(rgb.shape[:2], dtype=bool)
    labels = slic(
        img,
        n_segments=n_segments,
        compactness=compactness,
        sigma=sigma,
        mask=valid,
        start_label=1,
        channel_axis=-1,
    )
    return labels.astype(np.int32)


def labels_to_polygons(labels: np.ndarray, transform,
                       crs: str = "EPSG:4326") -> gpd.GeoDataFrame:
    """Vectorize a label array to a GeoDataFrame, one row per segment.

    Output columns:
      segment_id : int (matches label value)
      area_px    : pixel count
      geometry   : Polygon in `crs`
    """
    rows = []
    for geom_dict, val in rio_shapes(labels, mask=labels > 0, transform=transform):
        seg_id = int(val)
        poly = shape(geom_dict)
        if not poly.is_valid:
            poly = poly.buffer(0)
        if poly.is_empty:
            continue
        rows.append({
            "segment_id": seg_id,
            "geometry": poly,
        })
    gdf = gpd.GeoDataFrame(rows, crs=crs)
    # If a segment is split across non-contiguous pieces (rare for SLIC),
    # we keep them as separate rows; this is okay for OBIA.
    return gdf
