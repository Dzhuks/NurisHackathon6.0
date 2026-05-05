"""Raster I/O helpers — reading scenes, picking UTM CRS, reading RGB-only data.

Conventions:
- Source rasters are in EPSG:4326 (lon/lat) and have 4 bands (R, G, B, alpha).
- For metric calculations we reproject to UTM zone matching the scene
  (Almaty -> 32643, Astana -> 32642).
- Alpha band is treated as nodata: alpha==0 means "no data" pixel.
"""
from __future__ import annotations
from pathlib import Path
from typing import Tuple, Optional

import numpy as np
import rasterio
from rasterio.windows import Window


# UTM zone helpers ---------------------------------------------------------
def utm_epsg_for_lon(lon: float) -> int:
    """Return EPSG code for UTM zone covering this longitude (Northern hemisphere).

    Almaty lon ~76.9 -> zone 43 -> EPSG:32643
    Astana lon ~71.4 -> zone 42 -> EPSG:32642
    """
    zone = int((lon + 180.0) // 6) + 1
    return 32600 + zone


def utm_epsg_for_scene(path: Path | str) -> int:
    """Pick UTM EPSG by reading the scene's bounds."""
    with rasterio.open(path) as ds:
        lon_c = (ds.bounds.left + ds.bounds.right) / 2.0
        return utm_epsg_for_lon(lon_c)


# Reading ------------------------------------------------------------------
def read_rgba(path: Path | str, window: Optional[Window] = None
              ) -> Tuple[np.ndarray, np.ndarray, rasterio.Affine, str]:
    """Read RGB + alpha-derived nodata mask.

    Returns
    -------
    rgb : np.ndarray (H, W, 3) uint8
    nodata_mask : np.ndarray (H, W) bool — True means VALID pixel
    transform : rasterio.Affine — for the (possibly windowed) read
    crs : str — source CRS (e.g., 'EPSG:4326')
    """
    with rasterio.open(path) as ds:
        if window is None:
            window = Window(0, 0, ds.width, ds.height)
        # Read R, G, B, A as separate bands
        r = ds.read(1, window=window)
        g = ds.read(2, window=window)
        b = ds.read(3, window=window)
        rgb = np.stack([r, g, b], axis=-1)
        # Alpha band gives the validity mask; treat alpha==0 as nodata
        if ds.count >= 4:
            a = ds.read(4, window=window)
            valid = a > 0
        else:
            # Fallback: treat black pixels as nodata
            valid = (r > 0) | (g > 0) | (b > 0)
        transform = ds.window_transform(window)
        crs = str(ds.crs)
    return rgb, valid, transform, crs


def scene_metadata(path: Path | str) -> dict:
    """Return a dict of scene-level metadata."""
    with rasterio.open(path) as ds:
        return {
            "width": ds.width,
            "height": ds.height,
            "count": ds.count,
            "crs": str(ds.crs),
            "transform": ds.transform,
            "bounds": tuple(ds.bounds),
            "dtypes": ds.dtypes,
            "utm_epsg": utm_epsg_for_lon((ds.bounds.left + ds.bounds.right) / 2.0),
        }
