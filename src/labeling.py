"""Label segments using Overture Maps Foundation building polygons.

Weak labeling for SLIC segments using reference building polygons. Two outputs per segment:
  - label (0/1)        — binary building / non-building (for RF training)
  - overture_subtype   — Overture subtype string when overlap is substantial
  - overture_class     — Overture class string when overlap is substantial
  - overture_overlap   — fraction of segment area inside Overture polygons

Used by:
  - src/pipeline.py  (during initial extraction)
  - scripts/06b_relabel_with_overture.py  (re-label without re-running SLIC)
"""
from __future__ import annotations
from typing import Optional

import geopandas as gpd
import pandas as pd
from shapely.strtree import STRtree


POS_OVERLAP = 0.5    # segment is BUILDING if >50% inside Overture building
NEG_OVERLAP = 0.05   # segment is NON-BLD if <5% inside Overture
MASK_OVERLAP = 0.5   # excluded from train if >50% in veg/shadow/soil


def label_segments(segments_gdf: gpd.GeoDataFrame,
                   overture_buildings: gpd.GeoDataFrame,
                   features_df: pd.DataFrame) -> pd.DataFrame:
    """Assign label/overture_subtype/overture_class/overture_overlap per segment.

    Parameters
    ----------
    segments_gdf : GeoDataFrame
        One row per segment with at least `segment_id` and Polygon geometry.
    overture_buildings : GeoDataFrame
        Overture polygons in the same CRS. Optional cols: `subtype`, `class`.
    features_df : DataFrame
        Existing per-segment features with `segment_id`, `frac_vegetation`,
        `frac_shadow`, `frac_soil`. Will receive new columns.
    """
    geoms = list(overture_buildings.geometry.values)
    tree = STRtree(geoms)
    has_subtype = "subtype" in overture_buildings.columns
    has_class = "class" in overture_buildings.columns
    subtype_arr = (overture_buildings["subtype"].astype(str).where(
                       overture_buildings["subtype"].notna(), None).tolist()
                   if has_subtype else [None] * len(geoms))
    class_arr = (overture_buildings["class"].astype(str).where(
                     overture_buildings["class"].notna(), None).tolist()
                 if has_class else [None] * len(geoms))

    labels = []
    subtypes = []
    classes = []
    overlap_frac = []

    for seg_geom, _ in zip(segments_gdf.geometry, segments_gdf["segment_id"]):
        if seg_geom.is_empty or seg_geom.area <= 0:
            labels.append(-1); subtypes.append(None); classes.append(None); overlap_frac.append(0.0)
            continue
        seg_a = seg_geom.area
        idxs = tree.query(seg_geom)

        # Aggregate overlapping polygons; track best (largest-overlap) tag
        total_overlap = 0.0
        best_overlap = 0.0
        best_subtype = None
        best_class = None
        for i in idxs:
            i = int(i)
            inter = seg_geom.intersection(geoms[i]).area
            if inter > 0:
                total_overlap += inter
                if inter > best_overlap:
                    best_overlap = inter
                    best_subtype = subtype_arr[i] if subtype_arr[i] not in (None, "None", "nan") else None
                    best_class = class_arr[i] if class_arr[i] not in (None, "None", "nan") else None
        frac = total_overlap / seg_a
        overlap_frac.append(frac)

        if frac >= POS_OVERLAP:
            labels.append(1)
            subtypes.append(best_subtype)
            classes.append(best_class)
        elif frac <= NEG_OVERLAP:
            labels.append(0)
            subtypes.append(None)
            classes.append(None)
        else:
            labels.append(-1)
            subtypes.append(None)
            classes.append(None)

    out = features_df.copy()
    seg_to_label = dict(zip(segments_gdf["segment_id"], labels))
    seg_to_subtype = dict(zip(segments_gdf["segment_id"], subtypes))
    seg_to_class = dict(zip(segments_gdf["segment_id"], classes))
    seg_to_frac = dict(zip(segments_gdf["segment_id"], overlap_frac))
    out["label"] = out["segment_id"].map(seg_to_label)
    out["overture_subtype"] = out["segment_id"].map(seg_to_subtype)
    out["overture_class"] = out["segment_id"].map(seg_to_class)
    out["overture_overlap"] = out["segment_id"].map(seg_to_frac)

    drop_train = (
        (out["label"] == -1) |
        (out["frac_vegetation"] > MASK_OVERLAP) |
        (out["frac_shadow"] > MASK_OVERLAP) |
        (out["frac_soil"] > MASK_OVERLAP)
    )
    out["use_for_train"] = ~drop_train
    return out
