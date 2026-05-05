"""Sliding-window inference for U-Net building segmentation.

Per scene:
  1. Iterate over patches with overlap (default 256 px, stride 192 px = 25%).
  2. Run model on each patch, accumulate sigmoid probabilities into a
     full-scene float32 array (with overlap-averaging via sum / count).
  3. Threshold (default 0.5) to a binary mask.
  4. Vectorise via rasterio.features.shapes -> shapely Polygons in 4326.

Output: list of Polygon, plus per-polygon mean confidence.
"""
from __future__ import annotations
from pathlib import Path
from typing import Iterable

import numpy as np
import rasterio
from rasterio.windows import Window
from rasterio.features import shapes as rio_shapes
import torch
from shapely.geometry import shape as shp_shape, Polygon


def predict_scene(model: torch.nn.Module,
                  scene_path: str | Path,
                  *,
                  device: torch.device,
                  patch_size: int = 256,
                  stride: int = 192,
                  threshold: float = 0.5,
                  batch_size: int = 8,
                  log: callable = print,
                  ) -> tuple[list[Polygon], list[float], np.ndarray]:
    """Return (polygons, mean_confidences, scene_prob_map[float32])."""
    with rasterio.open(scene_path) as ds:
        W, H = ds.width, ds.height
        full_transform = ds.transform
        crs = ds.crs

        prob_sum = np.zeros((H, W), dtype=np.float32)
        prob_cnt = np.zeros((H, W), dtype=np.uint16)

        # Generate patch positions
        positions = []
        for r in range(0, H - patch_size + 1, stride):
            for c in range(0, W - patch_size + 1, stride):
                positions.append((c, r))
        # Also add right and bottom edges if not aligned
        if (W - patch_size) % stride != 0:
            for r in range(0, H - patch_size + 1, stride):
                positions.append((W - patch_size, r))
        if (H - patch_size) % stride != 0:
            for c in range(0, W - patch_size + 1, stride):
                positions.append((c, H - patch_size))
        positions.append((W - patch_size, H - patch_size))
        # Deduplicate
        positions = list(dict.fromkeys(positions))

        log(f"  {Path(scene_path).name}: {W}x{H} px, {len(positions)} patches")

        # Pre-read alpha to skip empty patches
        try:
            alpha_full = ds.read(4) if ds.count >= 4 else None
        except Exception:
            alpha_full = None

        model.eval()
        i = 0
        while i < len(positions):
            chunk = positions[i:i + batch_size]
            i += batch_size

            # Read RGB+alpha into batch
            xs = []
            valids = []
            keep_idx = []
            for k, (c, r) in enumerate(chunk):
                win = Window(c, r, patch_size, patch_size)
                rgb = ds.read([1, 2, 3], window=win)
                if alpha_full is not None:
                    valid = alpha_full[r:r+patch_size, c:c+patch_size] > 0
                else:
                    valid = np.any(rgb > 0, axis=0)
                if valid.mean() < 0.1:
                    continue
                rgb = rgb * valid.astype(np.uint8)[None, :, :]
                xs.append(rgb)
                valids.append(valid)
                keep_idx.append(k)
            if not xs:
                continue
            x_t = torch.from_numpy(np.stack(xs).astype(np.float32) / 255.0).to(device)
            with torch.no_grad():
                logits = model(x_t)
                probs = torch.sigmoid(logits).cpu().numpy()[:, 0, :, :]
            for j, k in enumerate(keep_idx):
                c, r = chunk[k]
                prob_sum[r:r+patch_size, c:c+patch_size] += probs[j]
                prob_cnt[r:r+patch_size, c:c+patch_size] += 1

        prob_avg = np.divide(prob_sum, np.maximum(prob_cnt, 1),
                             out=np.zeros_like(prob_sum), where=prob_cnt > 0)
        binary = (prob_avg >= threshold).astype(np.uint8)

    # ---- vectorise binary mask to polygons in scene CRS ----
    polygons: list[Polygon] = []
    confidences: list[float] = []
    for geom_dict, val in rio_shapes(binary, mask=binary == 1, transform=full_transform):
        if val != 1:
            continue
        poly = shp_shape(geom_dict)
        if not poly.is_valid:
            poly = poly.buffer(0)
        if poly.is_empty or poly.area <= 0:
            continue
        polygons.append(poly)
        confidences.append(float(prob_avg.mean()))  # scene-level proxy

    return polygons, confidences, prob_avg
