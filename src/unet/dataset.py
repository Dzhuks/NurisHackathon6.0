"""PyTorch Dataset for binary building segmentation from GeoTIFF tiles.

Each item is a (RGB, mask) pair sampled from one of our 20 scenes:
  - RGB: float32 [3, H, W] in [0, 1]
  - Mask: float32 [1, H, W] with 1 = building (Overture polygon), 0 = other

The dataset:
  * lazily reads windows from each GeoTIFF (rasterio handles cached per worker);
  * rasterises Overture buildings on-the-fly into the same window;
  * supports either "stride" mode (deterministic patches over a tile) for
    validation/inference, or "random" mode (random crops within each tile)
    for training.

Memory: ~3 MB per 256x256 RGB float32 patch + 256 KB mask. With batch 16
that's ~52 MB per batch — comfortable for M4 Pro 24 GB.
"""
from __future__ import annotations
from pathlib import Path
import random
from typing import List, Optional

import numpy as np
import rasterio
from rasterio.windows import Window
from rasterio.features import rasterize
from shapely.strtree import STRtree
from shapely.geometry import box
import geopandas as gpd
import torch
from torch.utils.data import Dataset


class BuildingTileDataset(Dataset):
    """Sample (RGB, mask) patches from a list of scenes."""

    def __init__(self,
                 scene_files: dict,            # scene_id -> path to .tif
                 overture_per_scene: dict,     # scene_id -> GeoDataFrame in EPSG:4326
                 patch_size: int = 256,
                 mode: str = "random",         # "random" or "stride"
                 patches_per_tile: int = 4,
                 tile_size: int = 1024,
                 tile_overlap: int = 0,
                 augment: bool = False,
                 min_valid_frac: float = 0.5,
                 ):
        self.scene_files = scene_files
        self.patch_size = patch_size
        self.mode = mode
        self.patches_per_tile = patches_per_tile
        self.tile_size = tile_size
        self.augment = augment
        self.min_valid_frac = min_valid_frac

        # Pre-build per-scene spatial index for fast polygon lookup
        self._scene_trees: dict = {}
        self._scene_geoms: dict = {}
        for sid, gdf in overture_per_scene.items():
            geoms = list(gdf.geometry.values) if not gdf.empty else []
            self._scene_geoms[sid] = geoms
            self._scene_trees[sid] = STRtree(geoms) if geoms else None

        # Pre-compute per-scene tile windows (1024x1024 with stride) and metadata
        self._scene_meta: dict = {}
        self._items: list = []  # list of (sid, tile_window) — one per tile
        stride = max(1, tile_size - tile_overlap)
        for sid, path in scene_files.items():
            with rasterio.open(path) as ds:
                w, h = ds.width, ds.height
                self._scene_meta[sid] = {
                    "width": w, "height": h,
                    "transform": ds.transform,
                    "path": str(path),
                }
            for row in range(0, h, stride):
                for col in range(0, w, stride):
                    win = Window(col, row,
                                 min(tile_size, w - col),
                                 min(tile_size, h - row))
                    if win.width >= patch_size and win.height >= patch_size:
                        self._items.append((sid, win))

        # Cached file handles per worker (keyed by pid)
        self._handles: dict = {}

    def __len__(self):
        if self.mode == "random":
            return len(self._items) * self.patches_per_tile
        # stride mode: one patch per tile, deterministic
        return len(self._items)

    # --------- low-level helpers --------------------------------------
    def _get_handle(self, path: str):
        # Each DataLoader worker process has its own self._handles dict
        h = self._handles.get(path)
        if h is None:
            h = rasterio.open(path)
            self._handles[path] = h
        return h

    def _read_patch(self, sid: str, tile_win: Window, p_col: int, p_row: int):
        """Read a (patch_size, patch_size) patch from tile_win at offset (p_col, p_row)."""
        ps = self.patch_size
        # Translate patch offsets to absolute (col, row) in the scene
        abs_col = tile_win.col_off + p_col
        abs_row = tile_win.row_off + p_row
        path = self._scene_meta[sid]["path"]
        ds = self._get_handle(path)
        win = Window(abs_col, abs_row, ps, ps)
        rgb = ds.read([1, 2, 3], window=win)               # [3, H, W] uint8
        if ds.count >= 4:
            alpha = ds.read(4, window=win)                  # [H, W]
            valid = alpha > 0
        else:
            valid = np.ones((ps, ps), dtype=bool)
        transform = ds.window_transform(win)
        return rgb, valid, transform

    def _rasterize_buildings(self, sid: str, transform, shape) -> np.ndarray:
        """Rasterise Overture polygons that intersect this patch."""
        tree = self._scene_trees.get(sid)
        if tree is None:
            return np.zeros(shape, dtype=np.uint8)
        # Build a tiny query polygon for the patch in world coords
        xs0, ys0 = transform * (0, 0)
        xs1, ys1 = transform * (shape[1], shape[0])
        patch_box = box(min(xs0, xs1), min(ys0, ys1),
                        max(xs0, xs1), max(ys0, ys1))
        idxs = tree.query(patch_box)
        if len(idxs) == 0:
            return np.zeros(shape, dtype=np.uint8)
        geoms = self._scene_geoms[sid]
        polys = [geoms[int(i)] for i in idxs]
        try:
            mask = rasterize(
                [(g, 1) for g in polys if g is not None and not g.is_empty],
                out_shape=shape,
                transform=transform,
                fill=0,
                dtype=np.uint8,
            )
        except Exception:
            mask = np.zeros(shape, dtype=np.uint8)
        return mask

    # --------- main --------------------------------------------------
    def __getitem__(self, idx: int):
        ps = self.patch_size

        if self.mode == "random":
            tile_idx = idx // self.patches_per_tile
            sid, tile_win = self._items[tile_idx]
            # Random offset within this tile (must fit patch_size)
            max_dx = max(0, tile_win.width - ps)
            max_dy = max(0, tile_win.height - ps)
            p_col = random.randint(0, max_dx) if max_dx > 0 else 0
            p_row = random.randint(0, max_dy) if max_dy > 0 else 0
        else:
            # stride mode: take centre of tile, deterministic
            sid, tile_win = self._items[idx]
            p_col = max(0, (tile_win.width - ps) // 2)
            p_row = max(0, (tile_win.height - ps) // 2)

        rgb, valid, transform = self._read_patch(sid, tile_win, p_col, p_row)
        # Drop patches mostly outside imagery boundary
        if valid.mean() < self.min_valid_frac:
            # Fallback to a different random tile (random mode) or zero patch
            if self.mode == "random":
                return self.__getitem__(random.randint(0, len(self) - 1))
            mask = np.zeros((ps, ps), dtype=np.uint8)
            rgb = np.zeros((3, ps, ps), dtype=np.uint8)
        else:
            mask = self._rasterize_buildings(sid, transform, (ps, ps))
        # Apply alpha-mask to RGB so border pixels are zero
        rgb = rgb * valid.astype(np.uint8)[None, :, :]

        rgb_t = torch.from_numpy(rgb.astype(np.float32) / 255.0)            # [3, H, W]
        mask_t = torch.from_numpy(mask.astype(np.float32))[None, ...]         # [1, H, W]

        if self.augment:
            # Lightweight torch-only augmentation (no albumentations needed)
            if random.random() < 0.5:
                rgb_t = torch.flip(rgb_t, dims=[2]); mask_t = torch.flip(mask_t, dims=[2])
            if random.random() < 0.5:
                rgb_t = torch.flip(rgb_t, dims=[1]); mask_t = torch.flip(mask_t, dims=[1])
            if random.random() < 0.5:
                k = random.choice([1, 2, 3])
                rgb_t = torch.rot90(rgb_t, k, dims=[1, 2])
                mask_t = torch.rot90(mask_t, k, dims=[1, 2])
        return rgb_t, mask_t


def build_overture_lookup(overture_clipped_path: str | Path) -> dict:
    """Read clipped Overture buildings GeoJSON and split per scene_id."""
    gdf = gpd.read_file(overture_clipped_path)
    if gdf.crs is None or str(gdf.crs) != "EPSG:4326":
        gdf = gdf.to_crs("EPSG:4326")
    out = {}
    for sid, sub in gdf.groupby("scene_id"):
        out[sid] = sub.reset_index(drop=True)
    return out
