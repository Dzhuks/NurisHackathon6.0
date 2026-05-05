"""Evaluate predictions on the 4 hold-out scenes against Overture ground truth.

PRIMARY metric: object-level "any-intersection" matching.
   For each GT building polygon, check whether at least one predicted
   polygon intersects it (any positive area of overlap counts).
       TP_gt   = #GT polygons matched by ≥1 prediction
       FN      = #GT polygons matched by 0 predictions
       TP_pred = #predicted polygons matching ≥1 GT
       FP      = #predicted polygons matching 0 GT
       Recall    = TP_gt   / total_GT
       Precision = TP_pred / total_pred
       F1        = 2·P·R / (P + R)
   This matches the practical question: "did the model find this building".

SECONDARY metric (informational): pixel-level coverage agreement.
   Compares unioned pred mask vs unioned GT mask in m². Same TP/FP/FN
   but in area units. Lower than object-level because it penalises
   imperfect polygon shapes.

Output: outputs/holdout_metrics.csv (per scene + AGGREGATE row).
"""
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.ops import unary_union
from shapely.strtree import STRtree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.io.raster import utm_epsg_for_scene
from src.logging_config import setup_logger
log = setup_logger("09_evaluate_holdout")


def _fix_geoms(geoms):
    out = []
    for g in geoms:
        if g is None or g.is_empty:
            continue
        if not g.is_valid:
            g = g.buffer(0)
        if g.is_empty:
            continue
        out.append(g)
    return out


def _object_level_match(pred_geoms: list, gt_geoms: list) -> dict:
    """Count how many GT polygons are matched by ≥1 prediction (any
    intersection), and how many predictions match ≥1 GT."""
    if not pred_geoms or not gt_geoms:
        return {"tp_gt": 0, "tp_pred": 0,
                "n_gt": len(gt_geoms), "n_pred": len(pred_geoms),
                "fn": len(gt_geoms), "fp": len(pred_geoms)}

    pred_tree = STRtree(pred_geoms)
    tp_gt = 0
    for g in gt_geoms:
        idxs = pred_tree.query(g)
        for i in idxs:
            i = int(i)
            try:
                if g.intersects(pred_geoms[i]):
                    tp_gt += 1
                    break
            except Exception:
                # Topology issue: try with buffer(0)
                try:
                    if g.buffer(0).intersects(pred_geoms[i].buffer(0)):
                        tp_gt += 1
                        break
                except Exception:
                    pass

    gt_tree = STRtree(gt_geoms)
    tp_pred = 0
    for p in pred_geoms:
        idxs = gt_tree.query(p)
        for i in idxs:
            i = int(i)
            try:
                if p.intersects(gt_geoms[i]):
                    tp_pred += 1
                    break
            except Exception:
                try:
                    if p.buffer(0).intersects(gt_geoms[i].buffer(0)):
                        tp_pred += 1
                        break
                except Exception:
                    pass
    return {
        "tp_gt": tp_gt,
        "tp_pred": tp_pred,
        "n_gt": len(gt_geoms),
        "n_pred": len(pred_geoms),
        "fn": len(gt_geoms) - tp_gt,
        "fp": len(pred_geoms) - tp_pred,
    }


def _pixel_level(pred_geoms: list, gt_geoms: list,
                 aoi_geom_utm) -> dict:
    """Pixel-level coverage agreement (m²-based). Secondary metric."""
    if not pred_geoms and not gt_geoms:
        return {"tp_m2": 0.0, "fp_m2": 0.0, "fn_m2": 0.0,
                "tn_m2": float(aoi_geom_utm.area)}
    try:
        pred_union = unary_union(pred_geoms) if pred_geoms else None
        gt_union = unary_union(gt_geoms) if gt_geoms else None
    except Exception as e:
        log.warning("pixel-level union failed: %s", e)
        return {"tp_m2": 0.0, "fp_m2": 0.0, "fn_m2": 0.0, "tn_m2": 0.0}
    aoi_area = float(aoi_geom_utm.area)
    if pred_union is None:
        tp = 0.0; fp = 0.0
        fn = float(gt_union.area) if gt_union else 0.0
    elif gt_union is None:
        tp = 0.0
        fp = float(pred_union.area)
        fn = 0.0
    else:
        tp = float(pred_union.intersection(gt_union).area)
        fp = float(pred_union.area - tp)
        fn = float(gt_union.area - tp)
    tn = max(0.0, aoi_area - tp - fp - fn)
    return {"tp_m2": tp, "fp_m2": fp, "fn_m2": fn, "tn_m2": tn}


def evaluate_scene(scene_id: str, scene_path: Path, aoi_geom_4326,
                   overture: gpd.GeoDataFrame) -> dict | None:
    pred_path = ROOT / "outputs" / "geojson" / f"{scene_id}_buildings.geojson"
    if not pred_path.exists():
        log.warning("[%s] no prediction, skip", scene_id)
        return None
    pred = gpd.read_file(pred_path)
    gt = overture[overture["scene_id"] == scene_id]
    if gt.empty:
        log.warning("[%s] no Overture ground truth, skip", scene_id)
        return None

    utm_epsg = utm_epsg_for_scene(scene_path)
    pred_u = pred.to_crs(epsg=utm_epsg)
    gt_u = gt.to_crs(epsg=utm_epsg)
    aoi_geom_utm = (
        gpd.GeoSeries([aoi_geom_4326], crs="EPSG:4326").to_crs(utm_epsg).iloc[0]
    )

    pred_geoms = _fix_geoms(list(pred_u.geometry.values))
    gt_geoms = _fix_geoms(list(gt_u.geometry.values))

    obj = _object_level_match(pred_geoms, gt_geoms)
    pix = _pixel_level(pred_geoms, gt_geoms, aoi_geom_utm)

    eps = 1e-9
    # Object-level (PRIMARY)
    P = obj["tp_pred"] / (obj["n_pred"] + eps) if obj["n_pred"] > 0 else 0.0
    R = obj["tp_gt"]   / (obj["n_gt"]   + eps) if obj["n_gt"]   > 0 else 0.0
    F = 2 * P * R / (P + R + eps)

    # Pixel-level (SECONDARY, informational only)
    aoi_area = pix["tn_m2"] + pix["tp_m2"] + pix["fp_m2"] + pix["fn_m2"]
    pP = pix["tp_m2"] / (pix["tp_m2"] + pix["fp_m2"] + eps)
    pR = pix["tp_m2"] / (pix["tp_m2"] + pix["fn_m2"] + eps)
    pF = 2 * pP * pR / (pP + pR + eps)
    pAcc = (pix["tp_m2"] + pix["tn_m2"]) / (aoi_area + eps)

    return {
        "scene_id": scene_id,
        "n_pred": obj["n_pred"], "n_gt": obj["n_gt"],
        "tp_gt": obj["tp_gt"], "tp_pred": obj["tp_pred"],
        "fp": obj["fp"], "fn": obj["fn"],
        "precision": round(P, 4),
        "recall": round(R, 4),
        "f1": round(F, 4),
        "pixel_precision": round(pP, 4),
        "pixel_recall": round(pR, 4),
        "pixel_f1": round(pF, 4),
        "pixel_accuracy": round(pAcc, 4),
    }


def main():
    aoi = gpd.read_file(ROOT / "aoi" / "scenes.geojson")
    overture = gpd.read_file(ROOT / "aoi" / "overture" / "buildings_clipped.geojson")
    holdout = aoi[aoi["split"] == "holdout"]
    log.info("Hold-out scenes (%d): %s",
             len(holdout), holdout["scene_id"].tolist())

    rows = []
    agg = {"tp_gt": 0, "tp_pred": 0, "n_gt": 0, "n_pred": 0}
    for _, row in holdout.iterrows():
        m = evaluate_scene(row["scene_id"], ROOT / row["file"],
                            row.geometry, overture)
        if m is None:
            continue
        rows.append(m)
        agg["tp_gt"] += m["tp_gt"]; agg["tp_pred"] += m["tp_pred"]
        agg["n_gt"] += m["n_gt"]; agg["n_pred"] += m["n_pred"]
        log.info("%s: P=%.3f R=%.3f F1=%.3f  (TP=%d/%d gt matched, %d/%d pred matched)",
                 m["scene_id"], m["precision"], m["recall"], m["f1"],
                 m["tp_gt"], m["n_gt"], m["tp_pred"], m["n_pred"])

    if rows:
        eps = 1e-9
        P = agg["tp_pred"] / (agg["n_pred"] + eps)
        R = agg["tp_gt"]   / (agg["n_gt"]   + eps)
        F = 2 * P * R / (P + R + eps)
        rows.append({
            "scene_id": "AGGREGATE",
            "n_pred": agg["n_pred"], "n_gt": agg["n_gt"],
            "tp_gt": agg["tp_gt"], "tp_pred": agg["tp_pred"],
            "fp": agg["n_pred"] - agg["tp_pred"], "fn": agg["n_gt"] - agg["tp_gt"],
            "precision": round(P, 4),
            "recall": round(R, 4),
            "f1": round(F, 4),
            "pixel_precision": "", "pixel_recall": "",
            "pixel_f1": "", "pixel_accuracy": "",
        })
        df = pd.DataFrame(rows)
        out = ROOT / "outputs" / "holdout_metrics.csv"
        df.to_csv(out, index=False)
        log.info("Saved -> %s", out)
        log.info("=== Object-level (any-intersection) ===")
        log.info("    Precision = %.3f  Recall = %.3f  F1 = %.3f", P, R, F)


if __name__ == "__main__":
    main()
