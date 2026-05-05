"""Run segment extraction + Overture labeling on all 20 scenes.

This is the data-preparation phase: per-segment features and Overture-derived
labels for the 16 train scenes; features only for the 4 hold-out scenes.
"""
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import geopandas as gpd
import pandas as pd

from src.pipeline import process_scene
from src.logging_config import setup_logger
log = setup_logger("04_extract_segments")

ROOT = Path(__file__).resolve().parents[1]


def main():
    aoi = gpd.read_file(ROOT / "aoi" / "scenes.geojson")
    buildings_ref = gpd.read_file(ROOT / "aoi" / "overture" / "buildings_clipped.geojson")
    log.info("Loaded %d scenes, %d Overture building polygons.", len(aoi), len(buildings_ref))
    log.info("Train scenes: %d, Hold-out: %d",
             (aoi['split'] == 'train').sum(), (aoi['split'] == 'holdout').sum())

    summaries = []
    t0 = time.time()
    for _, row in aoi.iterrows():
        log.info("=== %s (%s) ===", row['scene_id'], row['split'])
        summary = process_scene(
            scene_path=ROOT / row["file"],
            scene_id=row["scene_id"],
            city=row["city"],
            buildings_ref=buildings_ref,
            out_dir=ROOT / "outputs",
        )
        summary["split"] = row["split"]
        summaries.append(summary)
        elapsed = time.time() - t0
        done = len(summaries)
        log.info("total elapsed: %.0fs (%.0fs/scene avg)", elapsed, elapsed / done)

    df = pd.DataFrame(summaries)
    out = ROOT / "outputs" / "segments" / "summary.csv"
    df.to_csv(out, index=False)
    log.info("=== Summary ===")
    for line in df.to_string().splitlines():
        log.info("%s", line)
    log.info("Saved -> %s", out)


if __name__ == "__main__":
    main()
