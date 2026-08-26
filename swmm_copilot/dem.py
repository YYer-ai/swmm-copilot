"""DEM 获取：首次在线下载 GLO-30 瓦片至本地缓存，之后完全离线。

数据源：Copernicus DEM GLO-30（AWS 开放数据，免认证）
  https://registry.opendata.aws/copernicus-dem/
瓦片按 1°×1° 切分，本模块假设 bbox 落在单一瓦片内（<1° 范围，演示评估片区足够）。
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import rasterio
from rasterio.windows import from_bounds

CACHE_DIR = Path(__file__).resolve().parent.parent / "cache" / "dem"
_TILE_URL = (
    "https://copernicus-dem-30m.s3.amazonaws.com/"
    "Copernicus_DSM_COG_10_{ns}{lat:02d}_00_{ew}{lon:03d}_00_DEM/"
    "Copernicus_DSM_COG_10_{ns}{lat:02d}_00_{ew}{lon:03d}_00_DEM.tif"
)


def _tile_parts(west: float, south: float) -> tuple[str, int, str, int]:
    ns, lat = ("N", math.floor(south)) if south >= 0 else ("S", abs(math.floor(south)))
    ew, lon = ("E", math.floor(west)) if west >= 0 else ("W", abs(math.floor(west)))
    return ns, lat, ew, lon


def fetch_dem(bbox: tuple[float, float, float, float], offline: bool = False):
    """取 bbox=(west, south, east, north) 范围的 DEM。

    返回 (elev: ndarray[m], transform, crs)。缓存命中则零网络访问（离线可用）。
    """
    west, south, _, _ = bbox
    ns, lat, ew, lon = _tile_parts(west, south)
    name = f"Copernicus_DSM_COG_10_{ns}{lat:02d}_00_{ew}{lon:03d}_00_DEM"
    tile = CACHE_DIR / f"{name}.tif"
    if not tile.exists():
        if offline:
            raise FileNotFoundError(
                f"离线模式下无缓存瓦片 {tile}，请先联网运行一次以缓存数据"
            )
        import urllib.request

        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        url = _TILE_URL.format(ns=ns, lat=lat, ew=ew, lon=lon)
        print(f"下载 DEM 瓦片（首次，之后离线可用）：{name}.tif")
        urllib.request.urlretrieve(url, tile)

    with rasterio.open(tile) as src:
        win = from_bounds(*bbox, transform=src.transform).round_offsets().round_lengths()
        win = win.intersection(rasterio.windows.Window(0, 0, src.width, src.height))
        elev = src.read(1, window=win).astype(np.float64)
        transform = src.window_transform(win)
        crs = src.crs
    return elev, transform, crs
