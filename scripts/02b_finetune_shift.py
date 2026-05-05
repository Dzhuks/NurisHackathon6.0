"""2-D grid search over independent lat / lon shift factors for Overture.

Each candidate is a pair (factor_lat, factor_lon) where each runs from
0.0 to 0.75 in steps of 0.05, giving 16 × 16 = 256 pairs. Final shift:
   Δlat = factor_lat × DLAT_BASE
   Δlon = factor_lon × DLON_BASE
   shifted = raw − (Δlon, Δlat)

Range extended to [0, 0.75] after the [0, 0.5] sweep showed several top
candidates clustered at the upper edge (lat=0.5).

For each pair we:
  1. Apply the shift to a cached raw Overture (loaded once).
  2. Re-clip to AOI in memory using the spatial join from script 03.
  3. Re-label every per-scene parquet via src.labeling.label_segments.
  4. Train a fast Random Forest with out-of-bag F1 as metric.

We use a SUBSET of 4 representative scenes for speed (per-iteration ~17 s).
The full grid (256 pairs) takes ~75 min. Results dumped to
outputs/shift_finetune_2d.csv.
"""
from __future__ import annotations
from pathlib import Path
import sys
import time

import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.affinity import translate
from shapely.strtree import STRtree
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import f1_score, precision_score, recall_score

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.labeling import label_segments
from src.features.segment_features import ALL_FEATURES
from src.logging_config import setup_logger
log = setup_logger("02b_finetune_shift")


# Originally measured offset (full magnitude). Each axis is searched
# independently as a multiple of this.
DLAT_BASE = 0.0000969
DLON_BASE = 0.0000309

# Grid: 16 lat values x 16 lon values = 256 pairs (0.0 to 0.75, step 0.05)
FACTORS = [0.05 * i for i in range(16)]

# Subset of scenes for speed during search (mix of city/size).
SEARCH_SCENES = ["Almaty_3", "Almaty_8", "Astana_3", "Astana_8"]


def _load_raw_overture() -> gpd.GeoDataFrame:
    parts = []
    for city in ("Almaty", "Astana"):
        p = ROOT / "aoi" / "overture" / f"buildings_{city}_raw.geojson"
        parts.append(gpd.read_file(p))
    return gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs="EPSG:4326")


def _load_scene_data(scene_ids: list[str]) -> dict:
    """Load per-scene segments, features, and AOI polygons once."""
    aoi = gpd.read_file(ROOT / "aoi" / "scenes.geojson")
    out = {}
    for sid in scene_ids:
        row = aoi[aoi["scene_id"] == sid]
        if row.empty:
            continue
        f = ROOT / "outputs" / "segments" / f"{sid}.parquet"
        s = ROOT / "outputs" / "segments" / f"{sid}.geojson"
        if not f.exists() or not s.exists():
            log.warning("[%s] missing inputs", sid)
            continue
        out[sid] = {
            "df_base": pd.read_parquet(f),
            "seg": gpd.read_file(s),
            "aoi_geom": row.geometry.iloc[0],
        }
    return out


def _shift_and_clip(raw: gpd.GeoDataFrame, factor_lat: float, factor_lon: float,
                    aoi_geom_per_scene: dict) -> dict:
    """Shift raw geometries by (factor_lon * DLON, factor_lat * DLAT) and
    clip to each scene's AOI polygon. Returns dict scene_id -> clipped gdf."""
    dlat = factor_lat * DLAT_BASE
    dlon = factor_lon * DLON_BASE
    shifted = raw.copy()
    if dlat != 0.0 or dlon != 0.0:
        shifted["geometry"] = shifted.geometry.apply(
            lambda g: translate(g, xoff=-dlon, yoff=-dlat) if g is not None else g
        )
    out = {}
    tree = STRtree(list(shifted.geometry.values))
    geom_arr = list(shifted.geometry.values)
    for sid, aoi_poly in aoi_geom_per_scene.items():
        idxs = tree.query(aoi_poly)
        clipped_rows = []
        for i in idxs:
            i = int(i)
            inter = geom_arr[i].intersection(aoi_poly)
            if inter.is_empty:
                continue
            if inter.geom_type not in ("Polygon", "MultiPolygon"):
                continue
            row = shifted.iloc[i].to_dict()
            row["geometry"] = inter
            row["scene_id"] = sid
            clipped_rows.append(row)
        if clipped_rows:
            out[sid] = gpd.GeoDataFrame(clipped_rows, crs="EPSG:4326")
        else:
            out[sid] = gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
    return out


def _evaluate_pair(scene_data: dict, clipped_per_scene: dict) -> dict:
    """Re-label and train a fast RF; return OOB stats."""
    frames = []
    for sid, packet in scene_data.items():
        df = packet["df_base"].copy()
        seg = packet["seg"]
        # remove old label cols if present
        for col in ("label", "use_for_train", "overture_subtype",
                    "overture_class", "overture_overlap"):
            if col in df.columns:
                df = df.drop(columns=col)
        ov = clipped_per_scene.get(sid)
        if ov is None or ov.empty:
            df["label"] = 0
            df["overture_subtype"] = None
            df["overture_class"] = None
            df["overture_overlap"] = 0.0
            df["use_for_train"] = ~(
                (df["frac_vegetation"] > 0.5)
                | (df["frac_shadow"] > 0.5)
                | (df["frac_soil"] > 0.5)
            )
        else:
            df = label_segments(seg, ov, df)
        frames.append(df)

    big = pd.concat(frames, ignore_index=True)
    if "use_for_train" not in big.columns:
        big["use_for_train"] = (big["label"] != -1)
    train_mask = big["use_for_train"] & big["label"].isin([0, 1])
    feats = [c for c in ALL_FEATURES if c in big.columns]
    X = big.loc[train_mask, feats].astype(np.float32).fillna(0.0).values
    X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
    y = big.loc[train_mask, "label"].astype(int).values

    rf = RandomForestClassifier(
        n_estimators=80, max_depth=18, min_samples_leaf=10,
        class_weight="balanced", n_jobs=-1, random_state=42,
        oob_score=True, bootstrap=True,
    )
    rf.fit(X, y)
    oob_pred = rf.oob_decision_function_[:, 1] >= 0.5
    return {
        "oob_acc": float(rf.oob_score_),
        "oob_f1": float(f1_score(y, oob_pred)),
        "oob_p": float(precision_score(y, oob_pred)),
        "oob_r": float(recall_score(y, oob_pred)),
        "n_train": int(len(y)),
        "n_pos": int((y == 1).sum()),
    }


def main():
    log.info("Loading raw Overture (cached) and segment data for subset…")
    raw = _load_raw_overture()
    scene_data = _load_scene_data(SEARCH_SCENES)
    aoi_polys = {sid: d["aoi_geom"] for sid, d in scene_data.items()}
    log.info("Subset of %d scenes: %s", len(scene_data), list(scene_data.keys()))

    rows = []
    t0 = time.time()
    pair_idx = 0
    total_pairs = len(FACTORS) * len(FACTORS)
    for fac_lat in FACTORS:
        for fac_lon in FACTORS:
            pair_idx += 1
            t = time.time()
            clipped = _shift_and_clip(raw, fac_lat, fac_lon, aoi_polys)
            scores = _evaluate_pair(scene_data, clipped)
            elapsed = time.time() - t
            row = {
                "factor_lat": fac_lat, "factor_lon": fac_lon,
                "dlat_m": round(fac_lat * DLAT_BASE * 110540, 1),
                "dlon_m": round(fac_lon * DLON_BASE * 80000, 1),
                **scores,
                "elapsed_s": round(elapsed, 1),
            }
            rows.append(row)
            log.info("[%3d/%3d] lat=%+.2f lon=%+.2f  OOB-F1=%.4f P=%.3f R=%.3f  (%.0fs)",
                     pair_idx, total_pairs, fac_lat, fac_lon,
                     scores["oob_f1"], scores["oob_p"], scores["oob_r"], elapsed)

    df = pd.DataFrame(rows)
    out = ROOT / "outputs" / "shift_finetune_2d.csv"
    df.to_csv(out, index=False)
    log.info("=" * 60)
    log.info("Total time: %.0f min", (time.time() - t0) / 60)

    best = df.loc[df["oob_f1"].idxmax()]
    log.info("BEST pair: lat=%+.2f lon=%+.2f  OOB-F1=%.4f",
             best["factor_lat"], best["factor_lon"], best["oob_f1"])
    log.info("Saved -> %s", out)

    # Print top 10
    top = df.sort_values("oob_f1", ascending=False).head(10)
    log.info("Top 10 pairs:")
    for _, r in top.iterrows():
        log.info("  lat=%+.1f lon=%+.1f  OOB-F1=%.4f  P=%.3f R=%.3f",
                 r["factor_lat"], r["factor_lon"],
                 r["oob_f1"], r["oob_p"], r["oob_r"])


if __name__ == "__main__":
    main()
