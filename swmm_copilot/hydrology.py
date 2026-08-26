"""栅格水文分析：填洼、D8 流向、汇流累积、坡度（纯 numpy/heapq，无网络依赖）。"""

from __future__ import annotations

import heapq

import numpy as np


def fill_depressions(dem: np.ndarray) -> np.ndarray:
    """优先级填洼（Barnes 2014 简化版）：边界入堆，向内传播，洼地抬升至出口。"""
    m, n = dem.shape
    filled = np.full_like(dem, np.inf)
    visited = np.zeros(dem.shape, dtype=bool)
    heap: list[tuple[float, int, int]] = []
    for i in range(m):
        for j in range(n):
            if i in (0, m - 1) or j in (0, n - 1):
                filled[i, j] = dem[i, j]
                visited[i, j] = True
                heapq.heappush(heap, (dem[i, j], i, j))
    while heap:
        z, i, j = heapq.heappop(heap)
        for di, dj in ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)):
            ni, nj = i + di, j + dj
            if 0 <= ni < m and 0 <= nj < n and not visited[ni, nj]:
                visited[ni, nj] = True
                filled[ni, nj] = max(dem[ni, nj], z)
                heapq.heappush(heap, (filled[ni, nj], ni, nj))
    return filled


def d8_flowdir(dem: np.ndarray) -> np.ndarray:
    """D8 流向：返回每像元下游像元的扁平索引，-1 表示区域出口（无更低邻居）。"""
    m, n = dem.shape
    flat = dem.ravel()
    down = np.full(flat.size, -1, dtype=np.int64)
    cell = 1.0  # 像元尺寸归一（D8 只需相对比较）
    for k in range(flat.size):
        i, j = divmod(k, n)
        best, best_slope = -1, 0.0
        for di, dj in ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)):
            ni, nj = i + di, j + dj
            if 0 <= ni < m and 0 <= nj < n:
                dist = cell * (2**0.5 if di and dj else 1)
                slope = (flat[k] - flat[ni * n + nj]) / dist
                if slope > best_slope:
                    best, best_slope = ni * n + nj, slope
        down[k] = best
    return down


def flow_accum(dem: np.ndarray, down: np.ndarray) -> np.ndarray:
    """汇流累积（像元数）：按高程降序逐像元向下游累加。"""
    flat = dem.ravel()
    acc = np.ones(flat.size, dtype=np.float64)
    for k in np.argsort(-flat):  # 高的先处理，其汇流已定
        d = down[k]
        if d >= 0:
            acc[d] += acc[k]
    return acc.reshape(dem.shape)


def slope_percent(dem: np.ndarray, cell_m: float) -> float:
    """平均坡度（%）：中心差分梯度模的均值。"""
    gy, gx = np.gradient(dem, cell_m)
    return float(np.mean(np.hypot(gx, gy)) * 100)
