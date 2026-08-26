"""SWMM 网格概化建模与模拟：DEM → 网格子汇水区+管网 → .inp → pyswmm 运行。

概化方法（快速评估级，非工程级）：
- 将评估区均匀划分为 nx×ny 格，每格 = 1 个子汇水区 + 1 个检查井
- 管道：每格向邻格中「平均高程(平局按索引)最低」者连接，树形拓扑保证无环
- 出口：高程最低的格 → 自由出流排放口
- 不透水率暂为固定值（M1 后续接入 ESA WorldCover 自动估算）
- 地表积水深 = 节点溢流量 / 格面积（简化折算，不做二维地表漫流）
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

M_PER_DEG_LAT = 111_320.0


def _neighbors(i: int, j: int, ny: int, nx: int):
    for di in (-1, 0, 1):
        for dj in (-1, 0, 1):
            if di == 0 and dj == 0:
                continue
            ni, nj = i + di, j + dj
            if 0 <= ni < ny and 0 <= nj < nx:
                yield ni, nj


def build_grid_inp(
    elev: np.ndarray,
    transform,
    nx: int,
    ny: int,
    hyetograph: list[tuple[float, float]],
    inp_path: Path,
    imperv: float = 50.0,
    base_diameter_m: float = 1.0,
    lat_center: float = 22.5,
) -> dict:
    """生成网格概化 SWMM 模型。返回网格元信息（高程/坐标/连接关系）供制图复用。"""
    m, n = elev.shape
    rgs = np.array_split(np.arange(m), ny)
    cgs = np.array_split(np.arange(n), nx)
    lon0, lat0 = transform * (0, 0)  # 左上角 (经度, 纬度)
    lon1, lat1 = transform * (n, m)  # 右下角
    dlon_m = (lon1 - lon0) / nx * M_PER_DEG_LAT * np.cos(np.radians(lat_center))
    dlat_m = (lat0 - lat1) / ny * M_PER_DEG_LAT

    ce = np.zeros((ny, nx))          # 格平均高程
    cy = np.zeros((ny, nx))          # 格中心纬度
    cx = np.zeros((ny, nx))          # 格中心经度
    cslope = np.zeros((ny, nx))      # 格内平均坡度(%)
    for i in range(ny):
        for j in range(nx):
            block = elev[rgs[i][0] : rgs[i][-1] + 1, cgs[j][0] : cgs[j][-1] + 1]
            ce[i, j] = block.mean()
            gy, gx = np.gradient(block, 30.0)
            cslope[i, j] = max(0.2, float(np.mean(np.hypot(gx, gy)) * 100))
            r_lo, r_hi = rgs[i][0], rgs[i][-1] + 1
            c_lo, c_hi = cgs[j][0], cgs[j][-1] + 1
            cy[i, j], cx[i, j] = (transform * ((c_lo + c_hi) / 2, (r_lo + r_hi) / 2))[::-1]

    area_ha = dlat_m * dlon_m / 10_000.0
    width_m = float(np.sqrt(dlat_m * dlon_m))

    # 连接：仅当邻格 (高程, 索引) 字典序小于自身时连接（严格递减 → 无环）；
    # 局部最低格（含平地）即排水出路 → 各自设为排放口（洼地=泵站/低洼排放口，就近排水）
    down: dict[tuple[int, int], tuple[int, int] | None] = {}
    for i in range(ny):
        for j in range(nx):
            best = min((ce[ni, nj], (ni, nj)) for ni, nj in _neighbors(i, j, ny, nx))
            down[(i, j)] = best[1] if best < (ce[i, j], (i, j)) else None

    outfall_cells = [p for p, d in down.items() if d is None]
    outfall_id = {p: f"OUT{k + 1}" for k, p in enumerate(outfall_cells)}

    def jid(i, j):
        return f"J{i}_{j}"

    L: list[str] = []
    L += ["[TITLE]", "swmm-copilot 网格概化模型（快速评估）", ""]
    L += ["[OPTIONS]", "FLOW_UNITS CMS", "INFILTRATION HORTON", "FLOW_ROUTING DYNWAVE",
          "START_DATE 01/01/2026", "START_TIME 00:00:00", "END_DATE 01/01/2026", "END_TIME 02:00:00",
          "REPORT_STEP 00:05:00", "WET_STEP 00:01:00", "DRY_STEP 01:00:00", "ROUTING_STEP 00:00:30",
          "ALLOW_PONDING NO", ""]
    L += ["[EVAPORATION]", "CONSTANT 0.0", ""]
    L += ["[RAINGAGES]", "RG1 INTENSITY 0:05 1.0 TIMESERIES storm", ""]

    L += ["[SUBCATCHMENTS]", ";;名称 雨量计 出口 面积(ha) 不透水% 宽度(m) 坡度% 路缘长"]
    for i in range(ny):
        for j in range(nx):
            L.append(f"S{i}_{j} RG1 {jid(i, j)} {area_ha:.2f} {imperv} {width_m:.0f} {cslope[i, j]:.2f} 0")
    L.append("")
    L += ["[SUBAREAS]", ";;名称 N不透 N透 蓄水不透 蓄水透 零积水% 汇流路径"]
    for i in range(ny):
        for j in range(nx):
            L.append(f"S{i}_{j} 0.013 0.10 1.5 3.0 25 OUTLET")
    L.append("")
    L += ["[INFILTRATION]", ";;名称 最大渗速 最小渗速 衰减 干燥天数 最大入渗"]
    for i in range(ny):
        for j in range(nx):
            L.append(f"S{i}_{j} 75 25 4.14 7 0")
    L.append("")

    # 井底高程（invert）自各排放口沿管道树上溯递推：保证最小设计坡度，不依赖地面高差
    from collections import defaultdict, deque

    parents: dict[tuple[int, int], list[tuple[int, int]]] = defaultdict(list)
    for q, d in down.items():
        if d is not None:
            parents[d].append(q)
    min_slope, bury_depth = 0.003, 1.5
    invert: dict[tuple[int, int], float] = {}
    for p in outfall_cells:
        invert[p] = ce[p] - bury_depth
        dq = deque([p])
        while dq:
            cur = dq.popleft()
            for q in parents[cur]:
                dist = float(np.hypot((q[0] - cur[0]) * dlat_m, (q[1] - cur[1]) * dlon_m))
                invert[q] = min(ce[q] - bury_depth, invert[cur] - dist * min_slope)
                dq.append(q)

    L += ["[JUNCTIONS]", ";;名称 井底高程(m) 最大水深(m) 初始水深 超载深 积水面积"]
    for i in range(ny):
        for j in range(nx):
            L.append(f"{jid(i, j)} {invert[(i, j)]:.2f} 3.0 0 0 0")
    L.append("")
    L += ["[OUTFALLS]", ";;名称 高程(m) 类型"]
    for p, oid in outfall_id.items():
        L.append(f"{oid} {invert[p] - 0.2:.2f} FREE NO")
    L.append("")
    # 管径随上游汇流格数分级（模拟真实管网"下游管更大"）；排放口段按主干级
    ups = {(i, j): 1 for i in range(ny) for j in range(nx)}  # 上游格数（含自身）
    for _, p in sorted(((ce[p], p) for p in ups), reverse=True):  # 高程降序累加
        d = down[p]
        if p in outfall_id or d is None:
            continue
        ups[d] += ups[p]

    # 管径按上游汇流格数 3/8 次幂增长（曼宁满流 Q∝D^(8/3) 的反解），封顶主干级
    def pipe_dia(p) -> float:
        return round(min(3.0, base_diameter_m * ups[p] ** 0.375), 2)

    L += ["[CONDUITS]", ";;名称 起点 终点 长度(m) 曼宁 入口偏移 出口偏移 初始流量 最大流量"]
    cid = 0
    diameters: list[float] = []
    for i in range(ny):
        for j in range(nx):
            if (i, j) in outfall_id:
                to = outfall_id[(i, j)]
                dist = float(min(dlat_m, dlon_m))
            else:
                d = down[(i, j)]
                to = jid(*d)
                dist = float(np.hypot((i - d[0]) * dlat_m, (j - d[1]) * dlon_m))
            diameters.append(pipe_dia((i, j)))
            L.append(f"C{cid} {jid(i, j)} {to} {dist:.0f} 0.013 0 0 0 0")
            cid += 1
    L.append("")
    L += ["[XSECTIONS]", ";;名称 断面 直径(m)"]
    for k, dia in enumerate(diameters):
        L.append(f"C{k} CIRCULAR {dia} 0 0 0 1")
    L.append("")

    L += ["[TIMESERIES]", ";;时刻 强度(mm/hr)"]
    for t0, mm in hyetograph:
        hh, mmn = divmod(int(t0), 60)
        L.append(f"storm {hh:02d}:{mmn:02d} {mm * 12:.3f}")  # 5min 雨量 → mm/hr
    L.append("")
    L += ["[REPORT]", "INPUT NO", "CONTROLS NO", "SUBCATCHMENTS ALL", "NODES ALL", "LINKS ALL", ""]
    L += ["[COORDINATES]", ";;节点 经度 纬度"]
    for i in range(ny):
        for j in range(nx):
            L.append(f"{jid(i, j)} {cx[i, j]:.6f} {cy[i, j]:.6f}")
    for p, oid in outfall_id.items():
        L.append(f"{oid} {cx[p]:.6f} {cy[p]:.6f}")
    L.append("")

    inp_path.write_text("\n".join(L), encoding="utf-8")
    return {"cell_elev": ce, "cx": cx, "cy": cy, "down": down, "outfalls": outfall_cells,
            "area_m2": dlat_m * dlon_m}


def run_swmm(inp_path: Path) -> dict[str, dict]:
    """运行模拟，返回 {节点名: statistics字典}。"""
    from pyswmm import Nodes, Simulation

    stats: dict[str, dict] = {}
    with Simulation(str(inp_path)) as sim:
        for _ in sim:
            pass
        for node in Nodes(sim):
            stats[node.nodeid] = dict(node.statistics)
    return stats
