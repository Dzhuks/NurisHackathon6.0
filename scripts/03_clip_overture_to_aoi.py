"""Clip Overture buildings to scene AOIs and tag each feature with scene_id.

Output:
  aoi/overture/buildings_clipped.geojson — Overture buildings inside our 20 scenes,
    with scene_id column attached. Used as weak labels by the labeling script.
"""
from pathlib import Path
import sys
import geopandas as gpd
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.logging_config import setup_logger
log = setup_logger("03_clip_overture_to_aoi")


# Columns we want to keep from Overture buildings (most are NULL but
# meaningful when present):
KEEP_COLS = ["id", "subtype", "class", "names", "num_floors", "height",
             "roof_shape", "roof_material", "geometry"]


def main():
    aoi = gpd.read_file(ROOT / "aoi" / "scenes.geojson")
    out_features = []
    for city in ["Almaty", "Astana"]:
        src = ROOT / "aoi" / "overture" / f"buildings_{city}.geojson"
        if not src.exists():
            log.warning("missing %s, run 02_download_overture.py first", src.name)
            continue
        gdf = gpd.read_file(src)
        gdf = gdf[gdf.geometry.type.isin(["Polygon", "MultiPolygon"])].copy()
        # Keep only useful columns (subtype/class are the main labels)
        keep = [c for c in KEEP_COLS if c in gdf.columns]
        gdf = gdf[keep]

        scenes = aoi[aoi["city"] == city][["scene_id", "geometry"]]
        joined = gpd.sjoin(gdf, scenes, predicate="intersects", how="inner")
        clipped_rows = []
        for scene_id, group in joined.groupby("scene_id"):
            scene_geom = scenes[scenes["scene_id"] == scene_id].geometry.iloc[0]
            for _, row in group.iterrows():
                geom = row.geometry.intersection(scene_geom)
                if geom.is_empty:
                    continue
                if geom.geom_type not in ("Polygon", "MultiPolygon"):
                    continue
                d = {k: v for k, v in row.items()
                     if k not in ("geometry", "index_right")}
                d["geometry"] = geom
                d["scene_id"] = scene_id
                clipped_rows.append(d)
        if clipped_rows:
            out = gpd.GeoDataFrame(clipped_rows, crs=gdf.crs)
            out_features.append(out)
            log.info("%s: %d clipped buildings (from %d in bbox)",
                     city, len(out), len(gdf))

    if out_features:
        all_clipped = pd.concat(out_features, ignore_index=True)
        all_clipped = gpd.GeoDataFrame(all_clipped, crs="EPSG:4326")
        out_path = ROOT / "aoi" / "overture" / "buildings_clipped.geojson"
        all_clipped.to_file(out_path, driver="GeoJSON")
        log.info("-> %s: %d features total", out_path.name, len(all_clipped))


if __name__ == "__main__":
    main()
