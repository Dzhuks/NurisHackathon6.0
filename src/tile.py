"""Tiling helpers — break a large raster into overlapping windows.

Pattern from gis_demo/05_tiling.py:
- TILE_SIZE pixels per side
- OVERLAP pixels between adjacent tiles
- STRIDE = TILE_SIZE - OVERLAP
- Use rasterio.windows.Window + window_transform to keep geo-reference

For our 5–7 cm/pixel imagery, TILE=1024 ≈ 50–70 m on the ground —
small enough for memory, big enough to contain whole buildings.
"""
from __future__ import annotations
from typing import Iterator, Tuple

from rasterio.windows import Window


def iter_tiles(width: int, height: int,
               tile_size: int = 1024, overlap: int = 128
               ) -> Iterator[Window]:
    """Yield rasterio Windows tiling [0..width] x [0..height] with overlap.

    Last tile in each row/column is clipped to the raster boundary.
    """
    stride = tile_size - overlap
    if stride <= 0:
        raise ValueError(f"overlap ({overlap}) must be < tile_size ({tile_size})")
    for row in range(0, height, stride):
        for col in range(0, width, stride):
            w = min(tile_size, width - col)
            h = min(tile_size, height - row)
            if w <= 0 or h <= 0:
                continue
            yield Window(col_off=col, row_off=row, width=w, height=h)


def count_tiles(width: int, height: int,
                tile_size: int = 1024, overlap: int = 128) -> int:
    return sum(1 for _ in iter_tiles(width, height, tile_size, overlap))


def window_bounds(window: Window, transform) -> Tuple[float, float, float, float]:
    """Return (minx, miny, maxx, maxy) in CRS coords for a window."""
    ul_x, ul_y = transform * (window.col_off, window.row_off)
    lr_x, lr_y = transform * (window.col_off + window.width,
                              window.row_off + window.height)
    return min(ul_x, lr_x), min(ul_y, lr_y), max(ul_x, lr_x), max(ul_y, lr_y)
