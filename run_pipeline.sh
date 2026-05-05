#!/usr/bin/env bash
# End-to-end pipeline. Idempotent: each step skipped if its output exists.
# Total time: ~3 hours on Apple M4 Pro (MPS) for a full from-scratch run.

set -e
cd "$(dirname "$0")"

step() {
  local label="$1"; shift
  echo ""
  echo "======================================================"
  echo "  $label"
  echo "======================================================"
  PYTHONWARNINGS=ignore python3 -u "$@"
}

# 1. AOI footprints (fast, idempotent — also writes train/holdout split)
step "01 AOI footprints"               scripts/01_generate_aoi.py

# 2. Overture buildings (with empirically-tuned alignment shift)
[[ ! -d aoi/overture ]] && step "02 Download Overture"            scripts/02_download_overture.py

# 3. Clip Overture to scene AOI polygons
step "03 Clip Overture to AOIs"        scripts/03_clip_overture_to_aoi.py

# 4. SLIC super-pixels for landcover (vegetation / bare_soil only).
#    Holdout-independent, so safe to skip if files already exist.
if ! ls outputs/segments/*.parquet 2>/dev/null | grep -q .; then
  step "04 SLIC segments + features"   scripts/04_extract_segments.py
fi

# 5. Train U-Net on Overture-derived masks (~1-2 hr on MPS)
[[ ! -f outputs/models/unet_best.pt ]] && step "05 Train U-Net"   scripts/05_train_unet.py --epochs 15 --encoder resnet34 --batch 8

# 6. U-Net inference + ortho-snap regularisation + sub-classification
if ! ls outputs/geojson/*_buildings.geojson 2>/dev/null | grep -q .; then
  step "06 Predict buildings"          scripts/06_predict_unet.py --encoder resnet34
fi

# 7. YOLOv8-OBB cars
if ! ls outputs/geojson/*_cars.geojson 2>/dev/null | grep -q .; then
  step "07 Detect cars"                scripts/07_run_yolo_cars.py
fi

# 8. Finalize: per-type GeoJSON + summary CSV + multi-layer GeoPackage
[[ ! -f outputs/results.gpkg ]] && step "08 Finalize outputs"     scripts/08_finalize_outputs.py

# 9. Object-level (any-intersection) test metrics on 4 hold-out scenes
[[ ! -f outputs/holdout_metrics.csv ]] && step "09 Evaluate hold-out" scripts/09_evaluate_holdout.py

echo ""
echo "======================================================"
echo "  PIPELINE COMPLETE"
echo "======================================================"
echo ""
echo "Outputs:"
echo "  GeoJSON layers:    outputs/geojson/"
echo "  GeoPackage:        outputs/results.gpkg"
echo "  Scene metrics:     outputs/scene_metrics.csv"
echo "  Test metrics:      outputs/holdout_metrics.csv"
echo "  Logs:              outputs/logs/"
