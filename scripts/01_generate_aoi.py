"""Generate AOI (Area of Interest) footprint polygons for selected scenes.

For each GeoTIFF, reads the bounds and writes a polygon in EPSG:4326 to
aoi/scenes.geojson with attributes: scene_id, city, file, width_px,
height_px, res_lon_deg, res_lat_deg, area_km2.
"""
from pathlib import Path
import sys
import json
import math

import rasterio
from shapely.geometry import box, mapping
import geopandas as gpd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.logging_config import setup_logger
log = setup_logger("01_generate_aoi")

SCENES = [
    ("Almaty",  "Almaty/Almaty_1.tif"),
    ("Almaty",  "Almaty/Almaty_2.tif"),
    ("Almaty",  "Almaty/Almaty_3.tif"),
    ("Almaty",  "Almaty/Almaty_4.tif"),
    ("Almaty",  "Almaty/Almaty_5.tif"),
    ("Almaty",  "Almaty/Almaty_6.tif"),
    ("Almaty",  "Almaty/Almaty_7.tif"),
    ("Almaty",  "Almaty/Almaty_8.tif"),
    ("Almaty",  "Almaty/Almaty_9.tif"),
    ("Almaty",  "Almaty/Almaty_10.tif"),
    ("Astana",  "Astana/Astana_1.tif"),
    ("Astana",  "Astana/Astana_2.tif"),
    ("Astana",  "Astana/Astana_3.tif"),
    ("Astana",  "Astana/Astana_4.tif"),
    ("Astana",  "Astana/Astana_5.tif"),
    ("Astana",  "Astana/Astana_6.tif"),
    ("Astana",  "Astana/Astana_7.tif"),
    ("Astana",  "Astana/Astana_8.tif"),
    ("Astana",  "Astana/Astana_9.tif"),
    ("Astana",  "Astana/Astana_10.tif"),
]

# Hold-out for validation (model never sees Overture labels from these during training)
HOLDOUT_SCENES = {"Almaty_1", "Almaty_4", "Astana_2", "Astana_4"}


def main():
    rows = []
    for city, rel in SCENES:
        path = ROOT / rel
        if not path.exists():
            log.warning("MISSING: %s", path)
            continue
        with rasterio.open(path) as ds:
            b = ds.bounds
            poly = box(b.left, b.bottom, b.right, b.top)
            lat_c = (b.top + b.bottom) / 2.0
            mx = abs(ds.transform.a) * 111320 * math.cos(math.radians(lat_c))
            my = abs(ds.transform.e) * 110540
            width_m = (b.right - b.left) * 111320 * math.cos(math.radians(lat_c))
            height_m = (b.top - b.bottom) * 110540
            area_km2 = (width_m * height_m) / 1e6
            scene_id = path.stem
            rows.append({
                "scene_id": scene_id,
                "city": city,
                "file": str(path.relative_to(ROOT)),
                "split": "holdout" if scene_id in HOLDOUT_SCENES else "train",
                "width_px": ds.width,
                "height_px": ds.height,
                "res_m_x": round(mx, 4),
                "res_m_y": round(my, 4),
                "area_km2": round(area_km2, 4),
                "geometry": poly,
            })
            log.info("%s: %dx%d px, ~%.3fx%.3f m/px, %.4f km²",
                     scene_id, ds.width, ds.height, mx, my, area_km2)
    gdf = gpd.GeoDataFrame(rows, crs="EPSG:4326")
    out = ROOT / "aoi" / "scenes.geojson"
    gdf.to_file(out, driver="GeoJSON")
    log.info("Wrote %d AOI polygons -> %s", len(gdf), out)
    csv = ROOT / "aoi" / "summary.csv"
    gdf.drop(columns="geometry").to_csv(csv, index=False)
    log.info("Wrote summary -> %s", csv)


if __name__ == "__main__":
    main()
