"""DEM 获取：Copernicus GLO-30 COG 窗口读取 + 本地缓存（除 LLM 外全程可离线）。

数据源：Copernicus DEM GLO-30（AWS 开放数据，免认证）
  https://registry.opendata.aws/copernicus-dem/
获取方式：COG HTTP Range 窗口读取（只传输 bbox 所需数据块，通常 < 1MB），
窗口结果缓存为本地 GeoTIFF，之后完全离线。
瓦片按 1°×1° 切分，本模块假设 bbox 落在单一瓦片内（<1° 范围，评估片区足够）。
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

    返回 (elev: ndarray, transform, crs)。缓存命中则零网络访问（离线可用）。
    """
    west, south, _, _ = bbox
    ns, lat, ew, lon = _tile_parts(west, south)
    cache = CACHE_DIR / f"dem_{west:.3f}_{south:.3f}_{bbox[2]:.3f}_{bbox[3]:.3f}.tif"
    if cache.exists():
        with rasterio.open(cache) as src:
            return src.read(1).astype(np.float64), src.transform, src.crs
    if offline:
        raise FileNotFoundError(f"离线模式下无缓存 {cache}，请先联网运行一次")

    url = _TILE_URL.format(ns=ns, lat=lat, ew=ew, lon=lon)
    print(f"在线读取 DEM 窗口（COG Range，之后离线可用）：{cache.name}")
    with rasterio.open(f"/vsicurl/{url}") as src:
        win = from_bounds(*bbox, transform=src.transform).round_offsets().round_lengths()
        win = win.intersection(rasterio.windows.Window(0, 0, src.width, src.height))
        elev = src.read(1, window=win).astype(np.float64)
        transform = src.window_transform(win)
        crs = src.crs
        profile = dict(driver="GTiff", dtype="float32", height=elev.shape[0], width=elev.shape[1],
                       count=1, crs=crs, transform=transform, compress="lzw", nodata=0)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with rasterio.open(cache, "w", **profile) as dst:
        dst.write(elev.astype(np.float32), 1)
    return elev, transform, crs
