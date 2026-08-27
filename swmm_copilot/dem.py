"""DEM 获取：Copernicus GLO-30 COG 窗口读取 + 本地缓存（除 LLM 外全程可离线）。

数据源：Copernicus DEM GLO-30（AWS 开放数据，免认证）
  https://registry.opendata.aws/copernicus-dem/
获取方式：COG HTTP Range 窗口读取（只传输 bbox 所需数据块），窗口结果缓存为
本地 GeoTIFF，之后完全离线。支持跨多个 1°×1° 瓦片（如全市级范围）自动拼接。
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import rasterio
from rasterio.merge import merge as rio_merge
from rasterio.windows import from_bounds

CACHE_DIR = Path(__file__).resolve().parent.parent / "cache" / "dem"
_TILE_URL = (
    "https://copernicus-dem-30m.s3.amazonaws.com/"
    "Copernicus_DSM_COG_10_{ns}{lat:02d}_00_{ew}{lon:03d}_00_DEM/"
    "Copernicus_DSM_COG_10_{ns}{lat:02d}_00_{ew}{lon:03d}_00_DEM.tif"
)


def _tile_span(start: float, end: float) -> list[int]:
    """覆盖 [start, end) 的 1° 瓦片序号列表。"""
    return list(range(math.floor(start), math.ceil(end)))


def fetch_dem(bbox: tuple[float, float, float, float], offline: bool = False):
    """取 bbox=(west, south, east, north) 范围的 DEM（自动跨瓦片拼接）。

    返回 (elev: ndarray, transform, crs)。缓存命中则零网络访问（离线可用）。
    """
    west, south, east, north = bbox
    cache = CACHE_DIR / f"dem_{west:.3f}_{south:.3f}_{east:.3f}_{north:.3f}.tif"
    if cache.exists():
        with rasterio.open(cache) as src:
            return src.read(1).astype(np.float64), src.transform, src.crs
    if offline:
        raise FileNotFoundError(f"离线模式下无缓存 {cache}，请先联网运行一次")

    lats = _tile_span(south, north)
    lons = _tile_span(west, east)
    # 大范围（如全市）逐瓦片按 overview 层降采样读取（等效 ~90m），网络量降约一个量级；
    # 小片区仍按 30m 全分辨率窗口合并
    city_mode = (east - west) * (north - south) > 0.15
    opened = []
    try:
        if not city_mode:
            for la in lats:
                for lo in lons:
                    ns = "N" if la >= 0 else "S"
                    ez = "E" if lo >= 0 else "W"
                    opened.append(rasterio.open(f"/vsicurl/{_TILE_URL.format(ns=ns, lat=abs(la), ew=ez, lon=abs(lo))}"))
            arr, transform = rio_merge(opened, bounds=(west, south, east, north))
            elev = arr[0].astype(np.float64)
            crs = opened[0].crs
        else:
            from rasterio.enums import Resampling
            from rasterio.transform import from_origin

            res = 0.00027778 * 3
            dh = math.ceil((north - south) / res)
            dw = math.ceil((east - west) / res)
            dst_north = south + dh * res
            elev = np.zeros((dh, dw))
            transform = from_origin(west, dst_north, res, res)
            crs = "EPSG:4326"
            for la in lats:
                for lo in lons:
                    ns = "N" if la >= 0 else "S"
                    ez = "E" if lo >= 0 else "W"
                    url = _TILE_URL.format(ns=ns, lat=abs(la), ew=ez, lon=abs(lo))
                    print(f"在线读取 DEM 窗口（COG overview，之后离线可用）：{ns}{abs(la):02d}_{ez}{abs(lo):03d}")
                    with rasterio.open(f"/vsicurl/{url}") as src:
                        x0, y0 = max(west, lo), max(south, la)
                        x1, y1 = min(east, lo + 1), min(north, la + 1)
                        win = from_bounds(x0, y0, x1, y1, transform=src.transform)
                        oh = max(1, round(win.height / 3))
                        ow = max(1, round(win.width / 3))
                        arr = src.read(1, window=win, out_shape=(oh, ow),
                                       resampling=Resampling.average).astype(np.float64)
                        dr0 = max(0, round((dst_north - y1) / res))
                        dc0 = max(0, round((x0 - west) / res))
                        elev[dr0:dr0 + oh, dc0:dc0 + ow] = arr
    finally:
        for s in opened:
            s.close()

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    profile = dict(driver="GTiff", dtype="float32", height=elev.shape[0], width=elev.shape[1],
                   count=1, crs=crs, transform=transform, compress="lzw", nodata=0)
    with rasterio.open(cache, "w", **profile) as dst:
        dst.write(elev.astype(np.float32), 1)
    return elev, transform, crs
