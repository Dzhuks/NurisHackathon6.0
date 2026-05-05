"""Per-segment feature extractor.

For each segmented region, compute a feature vector combining:
  * Color statistics (mean+std in RGB and HSV, mean ExG/CIVE/v/VIg)
  * Texture (GLCM: contrast, homogeneity, ASM; LBP histogram)
  * Geometry (area, perimeter, compactness, eccentricity, solidity,
    rectangularity, shape index)
  * Mask occupation (% pixels in vegetation/shadow/soil masks)

Features adapted from:
  Hossain & Chen (2024), Geomatica 76 — Table 1
  Chen, Li, Li (2018), Remote Sensing 10:451 — §3.4
  Marcial-Pablo et al. (2019), IJRS 40 — vegetation indices
"""
from __future__ import annotations
from typing import List, Optional

import numpy as np
import pandas as pd
from skimage.color import rgb2hsv
from skimage.measure import regionprops_table, regionprops
from skimage.feature import graycomatrix, graycoprops, local_binary_pattern

from src.features.masks import (
    excess_green, color_invariance_v, cive, vig_normalized,
)


# Feature column names — kept stable so train/predict produce identical schemas
COLOR_FEATURES = [
    "R_mean", "G_mean", "B_mean",
    "R_std", "G_std", "B_std",
    "H_mean", "S_mean", "V_mean",
    "H_std", "S_std", "V_std",
    "exg_mean", "v_idx_mean", "cive_mean", "vig_mean",
    "intensity_mean", "intensity_std",
]
TEXTURE_FEATURES = [
    "glcm_contrast", "glcm_homogeneity", "glcm_asm",
    "glcm_correlation", "glcm_dissimilarity",
    "lbp_h0", "lbp_h1", "lbp_h2", "lbp_h3", "lbp_h4",
    "lbp_h5", "lbp_h6", "lbp_h7", "lbp_h8", "lbp_h9",
]
GEOMETRY_FEATURES = [
    "area_px", "perimeter_px", "eccentricity", "solidity",
    "extent", "orientation", "major_axis_len", "minor_axis_len",
    "shape_index", "compactness",
]
MASK_FEATURES = [
    "frac_vegetation", "frac_shadow", "frac_soil",
]
ALL_FEATURES = COLOR_FEATURES + TEXTURE_FEATURES + GEOMETRY_FEATURES + MASK_FEATURES


def _glcm_features(intensity: np.ndarray, mask: np.ndarray) -> dict:
    """Compute GLCM stats restricted to the segment.

    To avoid bias from the bounding-box background, we replace pixels
    outside `mask` with the segment's mean intensity. Then GLCM on the
    bounding-box patch.
    """
    if mask.sum() < 4:
        return {k: 0.0 for k in ["glcm_contrast", "glcm_homogeneity", "glcm_asm",
                                  "glcm_correlation", "glcm_dissimilarity"]}
    patch = intensity.copy()
    mean_in = patch[mask].mean()
    patch[~mask] = mean_in
    # Quantize to 32 levels for tractable GLCM
    q = (patch / 8).astype(np.uint8)
    # Distance=1, angle=0 (horizontal) — compact, fast
    glcm = graycomatrix(q, distances=[1], angles=[0], levels=32,
                        symmetric=True, normed=True)
    return {
        "glcm_contrast": float(graycoprops(glcm, "contrast")[0, 0]),
        "glcm_homogeneity": float(graycoprops(glcm, "homogeneity")[0, 0]),
        "glcm_asm": float(graycoprops(glcm, "ASM")[0, 0]),
        "glcm_correlation": float(graycoprops(glcm, "correlation")[0, 0]),
        "glcm_dissimilarity": float(graycoprops(glcm, "dissimilarity")[0, 0]),
    }


def _lbp_histogram(intensity: np.ndarray, mask: np.ndarray, P: int = 8, R: int = 1) -> list:
    """LBP histogram (10 bins for uniform-rotation-invariant pattern with P=8)."""
    if mask.sum() < 4:
        return [0.0] * 10
    lbp = local_binary_pattern(intensity, P=P, R=R, method="uniform")
    vals = lbp[mask]
    # Uniform LBP with P=8 has P+2 = 10 distinct values
    hist, _ = np.histogram(vals, bins=np.arange(P + 3) - 0.5)
    if hist.sum() > 0:
        hist = hist.astype(np.float32) / hist.sum()
    else:
        hist = hist.astype(np.float32)
    return hist.tolist()


def extract_features(rgb: np.ndarray,
                     labels: np.ndarray,
                     veg_mask: Optional[np.ndarray] = None,
                     sha_mask: Optional[np.ndarray] = None,
                     soi_mask: Optional[np.ndarray] = None,
                     ) -> pd.DataFrame:
    """Compute features for every label > 0 in `labels`.

    Returns a DataFrame with one row per segment, columns ALL_FEATURES + segment_id.
    """
    H, W = labels.shape
    R = rgb[..., 0].astype(np.float32)
    G = rgb[..., 1].astype(np.float32)
    B = rgb[..., 2].astype(np.float32)
    intensity = (R + G + B) / 3.0

    # Pre-compute spectral indices once (vectorized, fast)
    exg_full = excess_green(rgb)
    v_full = color_invariance_v(rgb)
    cive_full = cive(rgb)
    vig_full = vig_normalized(rgb)
    hsv = rgb2hsv(rgb)  # values in [0, 1]
    intensity_u8 = intensity.astype(np.uint8)

    if veg_mask is None:
        veg_mask = np.zeros_like(intensity, dtype=bool)
    if sha_mask is None:
        sha_mask = np.zeros_like(intensity, dtype=bool)
    if soi_mask is None:
        soi_mask = np.zeros_like(intensity, dtype=bool)

    # Geometry via regionprops_table (vectorized, fast)
    geom_props = ("label", "area", "perimeter", "eccentricity", "solidity",
                  "extent", "orientation", "major_axis_length",
                  "minor_axis_length", "bbox")
    gp = regionprops_table(labels, properties=geom_props)
    df_geom = pd.DataFrame(gp).rename(columns={
        "label": "segment_id",
        "area": "area_px",
        "perimeter": "perimeter_px",
        "major_axis_length": "major_axis_len",
        "minor_axis_length": "minor_axis_len",
    })
    # Derived geometry
    eps = 1e-6
    df_geom["shape_index"] = df_geom["perimeter_px"] / (
        4 * np.sqrt(df_geom["area_px"] + eps))
    df_geom["compactness"] = (4 * np.pi * df_geom["area_px"]) / (
        df_geom["perimeter_px"] ** 2 + eps)

    # Per-segment color/texture/mask — slower; iterate but with bbox
    rows = []
    for prop in regionprops(labels):
        seg_id = prop.label
        # bbox
        minr, minc, maxr, maxc = prop.bbox
        local_label = labels[minr:maxr, minc:maxc] == seg_id
        if local_label.sum() < 1:
            continue
        # color
        rec = {"segment_id": int(seg_id)}
        rec["R_mean"] = float(R[minr:maxr, minc:maxc][local_label].mean())
        rec["G_mean"] = float(G[minr:maxr, minc:maxc][local_label].mean())
        rec["B_mean"] = float(B[minr:maxr, minc:maxc][local_label].mean())
        rec["R_std"] = float(R[minr:maxr, minc:maxc][local_label].std())
        rec["G_std"] = float(G[minr:maxr, minc:maxc][local_label].std())
        rec["B_std"] = float(B[minr:maxr, minc:maxc][local_label].std())
        rec["H_mean"] = float(hsv[minr:maxr, minc:maxc, 0][local_label].mean())
        rec["S_mean"] = float(hsv[minr:maxr, minc:maxc, 1][local_label].mean())
        rec["V_mean"] = float(hsv[minr:maxr, minc:maxc, 2][local_label].mean())
        rec["H_std"] = float(hsv[minr:maxr, minc:maxc, 0][local_label].std())
        rec["S_std"] = float(hsv[minr:maxr, minc:maxc, 1][local_label].std())
        rec["V_std"] = float(hsv[minr:maxr, minc:maxc, 2][local_label].std())
        rec["exg_mean"] = float(exg_full[minr:maxr, minc:maxc][local_label].mean())
        rec["v_idx_mean"] = float(v_full[minr:maxr, minc:maxc][local_label].mean())
        rec["cive_mean"] = float(cive_full[minr:maxr, minc:maxc][local_label].mean())
        rec["vig_mean"] = float(vig_full[minr:maxr, minc:maxc][local_label].mean())
        rec["intensity_mean"] = float(intensity[minr:maxr, minc:maxc][local_label].mean())
        rec["intensity_std"] = float(intensity[minr:maxr, minc:maxc][local_label].std())

        # texture
        rec.update(_glcm_features(
            intensity_u8[minr:maxr, minc:maxc], local_label))
        lbp_h = _lbp_histogram(
            intensity[minr:maxr, minc:maxc], local_label)
        for i, h in enumerate(lbp_h):
            rec[f"lbp_h{i}"] = h

        # mask occupation
        n = local_label.sum()
        rec["frac_vegetation"] = float(
            (veg_mask[minr:maxr, minc:maxc] & local_label).sum() / n)
        rec["frac_shadow"] = float(
            (sha_mask[minr:maxr, minc:maxc] & local_label).sum() / n)
        rec["frac_soil"] = float(
            (soi_mask[minr:maxr, minc:maxc] & local_label).sum() / n)

        rows.append(rec)

    df_other = pd.DataFrame(rows)
    df = df_other.merge(df_geom, on="segment_id", how="left")
    # Drop bbox columns
    for c in [c for c in df.columns if c.startswith("bbox-")]:
        df = df.drop(columns=c)
    # Reorder
    cols = ["segment_id"] + [c for c in ALL_FEATURES if c in df.columns]
    return df[cols]
