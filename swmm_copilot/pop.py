"""人口密度获取：GHSL GHS-POP 2020（JRC 开放数据，免认证）分块瓦片读取 + 本地缓存。

数据源：GHS-POP R2023A，30 弧秒（~1km），每格人数 → 转人口密度（人/km²）。
瓦片为 10°×10° 网格（实测探针标定）：行 r = 9 - floor((lat+0.9)/10)，
列 c = floor(lon/10) + 19；79°N 以上极区行不规则，本项目城市清单不涉及。
jeodpp 大文件吞吐极低，但单瓦片 zip 仅 ~1.5MB（约 20s），下载后永久离线。
"""

from __future__ import annotations

import io
import math
import zipfile
from pathlib import Path
from urllib.request import urlretrieve

import numpy as np
import rasterio
from rasterio.transform import from_origin
from rasterio.windows import from_bounds

CACHE_DIR = Path(__file__).resolve().parent.parent / "cache" / "pop"
_TILES_DIR = CACHE_DIR / "tiles"
_TILE_URL = (
    "https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/"
    "GHS_POP_GLOBE_R2023A/GHS_POP_E2020_GLOBE_R2023A_4326_30ss/V1-0/tiles/"
    "GHS_POP_E2020_GLOBE_R2023A_4326_30ss_V1_0_R{r}_C{c}.zip"
)
_RES = 1 / 120  # 30 弧秒


def _tile_tif(r: int, c: int) -> tuple[np.ndarray, "rasterio.Affine"]:
    """读瓦片（zip 缓存优先，未命中则下载），返回 (人数数组, transform)。"""
    zpath = _TILES_DIR / f"p30_R{r}_C{c}.zip"
    if not zpath.exists():
        _TILES_DIR.mkdir(parents=True, exist_ok=True)
        print(f"在线下载人口瓦片 R{r}_C{c}（~1.5MB，之后离线可用）")
        urlretrieve(_TILE_URL.format(r=r, c=c), zpath)
    with zipfile.ZipFile(zpath) as zf:
        name = [n for n in zf.namelist() if n.endswith(".tif")][0]
        with rasterio.open(io.BytesIO(zf.read(name))) as src:
            return src.read(1).astype(np.float64), src.transform


def fetch_pop(bbox: tuple[float, float, float, float], offline: bool = False):
    """取 bbox=(west, south, east, north) 人口密度（人/km²）。

    返回 (dens: ndarray, transform, crs)。缓存命中则零网络访问（离线可用）。
    """
    west, south, east, north = bbox
    cache = CACHE_DIR / f"pop_{west:.3f}_{south:.3f}_{east:.3f}_{north:.3f}.tif"
    if cache.exists():
        with rasterio.open(cache) as src:
            return src.read(1).astype(np.float64), src.transform, src.crs
    if offline:
        raise FileNotFoundError(f"离线模式下无缓存 {cache}，请先联网运行一次")

    dh = max(1, math.ceil((north - south) / _RES))
    dw = max(1, math.ceil((east - west) / _RES))
    dst_north = south + dh * _RES
    counts = np.zeros((dh, dw))  # 每格人数
    transform = from_origin(west, dst_north, _RES, _RES)

    rows = range(9 - math.floor((north + 0.9) / 10), 9 - math.floor((south + 0.9) / 10) + 1)
    cols = range(math.floor(west / 10) + 19, math.floor(east / 10) + 19 + 1)
    for r in rows:
        for c in cols:
            try:
                arr, t = _tile_tif(r, c)
            except Exception as ex:  # 瓦片不存在（极区/海洋边界）视为空
                print(f"人口瓦片 R{r}_C{c} 跳过（{ex}）")
                continue
            tb = rasterio.transform.array_bounds(arr.shape[0], arr.shape[1], t)
            x0, y0 = max(west, tb[0]), max(south, tb[1])
            x1, y1 = min(east, tb[2]), min(dst_north, tb[3])
            if x1 <= x0 or y1 <= y0:
                continue
            win = from_bounds(x0, y0, x1, y1, transform=t)
            sub = arr[math.floor(win.row_off):math.ceil(win.row_off + win.height),
                      math.floor(win.col_off):math.ceil(win.col_off + win.width)]
            dr0 = max(0, round((dst_north - y1) / _RES))
            dc0 = max(0, round((x0 - west) / _RES))
            counts[dr0:dh, dc0:dw][:sub.shape[0], :sub.shape[1]] = sub[:dh - dr0, :dw - dc0]

    counts[counts < 0] = 0  # GHSL nodata(-200) 置零
    # 人/格 → 人/km²（格边长随纬度变化）
    lats = dst_north - (np.arange(dh) + 0.5) * _RES
    cell_km2 = (_RES * 111.320 * np.cos(np.radians(lats))) * (_RES * 110.574)
    dens = counts / cell_km2[:, None]

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    profile = dict(driver="GTiff", dtype="float32", height=dh, width=dw, count=1,
                   crs="EPSG:4326", transform=transform, compress="lzw")
    with rasterio.open(cache, "w", **profile) as dst:
        dst.write(dens.astype(np.float32), 1)
    return dens, transform, "EPSG:4326"
