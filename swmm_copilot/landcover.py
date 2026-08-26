"""土地覆盖获取与不透水率估算：ESA WorldCover 10m（免认证）。

数据源：ESA WorldCover v200 (2021)，AWS 开放数据桶 esa-worldcover（eu-central-1）
  https://registry.opendata.aws/esa-worldcover/  （CC-BY 4.0）
获取方式：COG HTTP Range 窗口读取（只传输 bbox 所需数据块，通常 < 1MB），
窗口结果缓存为本地 GeoTIFF，之后完全离线。
瓦片按 3°×3° 分块，命名 N{floor(lat/3)*3:02d}E{floor(lon/3)*3:03d}。
类目：50=建成区；不透水率 ≈ 建成区占比 × 0.9（建成区典型不透水系数）。
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import rasterio
from rasterio.windows import from_bounds

CACHE_DIR = Path(__file__).resolve().parent.parent / "cache" / "landcover"
_URL = (
    "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/"
    "ESA_WorldCover_10m_2021_v200_{ns}{lat:02d}{ew}{lon:03d}_Map.tif"
)

BUILT = 50  # WorldCover 建成区类目码
IMPERV_FACTOR = 0.9


def fetch_landcover(bbox: tuple[float, float, float, float], offline: bool = False):
    """取 bbox=(west, south, east, north) 的 WorldCover 类目栅格。

    首次经 COG Range 请求在线读取窗口并缓存；缓存命中零网络（离线可用）。
    """
    west, south, _, _ = bbox
    ns, lat = ("N", math.floor(south / 3) * 3) if south >= 0 else ("S", abs(math.floor(south / 3) * 3))
    ew, lon = ("E", math.floor(west / 3) * 3) if west >= 0 else ("W", abs(math.floor(west / 3) * 3))
    cache = CACHE_DIR / f"wc_{west:.3f}_{south:.3f}_{bbox[2]:.3f}_{bbox[3]:.3f}.tif"
    if cache.exists():
        with rasterio.open(cache) as src:
            return src.read(1), src.transform, src.crs
    if offline:
        raise FileNotFoundError(f"离线模式下无缓存 {cache}，请先联网运行一次")

    url = _URL.format(ns=ns, lat=lat, ew=ew, lon=lon)
    print(f"在线读取土地覆盖窗口（COG Range，之后离线可用）：{cache.name}")
    with rasterio.open(f"/vsicurl/{url}") as src:
        win = from_bounds(*bbox, transform=src.transform).round_offsets().round_lengths()
        win = win.intersection(rasterio.windows.Window(0, 0, src.width, src.height))
        arr = src.read(1, window=win)
        transform = src.window_transform(win)
        crs = src.crs
        profile = dict(driver="GTiff", dtype=arr.dtype, height=arr.shape[0], width=arr.shape[1],
                       count=1, crs=crs, transform=transform, compress="lzw")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with rasterio.open(cache, "w", **profile) as dst:
        dst.write(arr, 1)
    return arr, transform, crs


def impervious_grid(cover: np.ndarray, ny: int, nx: int) -> np.ndarray:
    """按 ny×nx 网格统计建成区占比 → 不透水率(%)。"""
    m, n = cover.shape
    rgs = np.array_split(np.arange(m), ny)
    cgs = np.array_split(np.arange(n), nx)
    g = np.zeros((ny, nx))
    for i in range(ny):
        for j in range(nx):
            block = cover[rgs[i][0] : rgs[i][-1] + 1, cgs[j][0] : cgs[j][-1] + 1]
            g[i, j] = float(np.mean(block == BUILT)) * 100 * IMPERV_FACTOR
    return g
