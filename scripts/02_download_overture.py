"""Download Overture Maps Foundation buildings for Almaty + Astana bbox
and apply a fixed alignment shift so footprints line up with imagery.

Uses the official `overturemaps` CLI (pip install overturemaps). The
downloaded raw polygons are systematically offset from the GeoTIFF imagery
in our region. The shift was tuned via independent 2-D grid-search
(scripts/02b_finetune_shift.py): each axis swept from 0 to +0.75 of the
originally measured offset in 0.05 steps (256 pairs). The pair that
maximised OOB-F1 of the building classifier was lat_factor = 0.35,
lon_factor = 0.50, giving:
    Δlat = +0.0000339°  (~3.7 m north)
    Δlon = +0.0000155°  (~1.2 m east at 51° lat)
We subtract these from every coordinate so that saved polygons align with
the imagery. The shift is applied in-script before writing the GeoJSON.

Output:
  aoi/overture/buildings_Almaty.geojson  (with shift applied)
  aoi/overture/buildings_Astana.geojson  (with shift applied)
"""
from pathlib import Path
import sys
import subprocess

import geopandas as gpd
from shapely.affinity import translate

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.logging_config import setup_logger
log = setup_logger("02_download_overture")


# Tuned via 2-D grid-search (scripts/02b_finetune_shift.py): 256 pairs
# scanned over [0, 0.75] step 0.05; lat_factor=0.35, lon_factor=0.50 won
# with OOB-F1 = 0.7162 on a 4-scene subset.
DLAT = 0.35 * 0.0000969    # = 0.0000339°  ~3.7 m latitude shift
DLON = 0.50 * 0.0000309    # = 0.0000155°  ~1.2 m longitude shift


def _bbox_for_city(city: str) -> tuple[float, float, float, float]:
    """Compute bbox covering all scenes of the city with a small pad."""
    aoi = gpd.read_file(ROOT / "aoi" / "scenes.geojson")
    sub = aoi[aoi["city"] == city]
    if sub.empty:
        raise ValueError(f"No scenes for {city}")
    minx, miny, maxx, maxy = sub.total_bounds
    pad = 0.002  # ~200 m buffer
    return (minx - pad, miny - pad, maxx + pad, maxy + pad)


def _shift_geometries(gdf: gpd.GeoDataFrame, dlon: float, dlat: float) -> gpd.GeoDataFrame:
    """Translate every geometry by (-dlon, -dlat) so polygons match imagery."""
    out = gdf.copy()
    out["geometry"] = out.geometry.apply(
        lambda g: translate(g, xoff=-dlon, yoff=-dlat) if g is not None else g
    )
    return out


def download_city(city: str):
    bbox = _bbox_for_city(city)
    out = ROOT / "aoi" / "overture" / f"buildings_{city}.geojson"
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "python3", "-m", "overturemaps", "download",
        f"--bbox={bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}",
        "-f", "geojson",
        "-t", "building",
        "-o", str(out),
    ]
    log.info("%s: downloading bbox=%s", city, bbox)
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        log.error("%s download failed: %s", city, res.stderr[:500])
        return

    # Apply the alignment shift to every footprint and overwrite the file.
    gdf = gpd.read_file(out)
    n = len(gdf)
    gdf = _shift_geometries(gdf, dlon=DLON, dlat=DLAT)
    gdf.to_file(out, driver="GeoJSON")
    log.info("%s: %d buildings shifted by Δlon=-%g Δlat=-%g -> %s",
             city, n, DLON, DLAT, out.relative_to(ROOT))


def main():
    for city in ["Almaty", "Astana"]:
        download_city(city)
    log.info("Done.")


if __name__ == "__main__":
    main()
