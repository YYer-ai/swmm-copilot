"""评估流水线：片区 → 数据获取 → 水文分析 → SWMM 概化模拟 → 结果摘要与制图。

demo_pipeline 与 LLM Agent 共用此模块；数据获取遵循「首次在线 COG 窗口、之后离线缓存」。
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import yaml
from rasterio.transform import xy

from . import chicago_hyetograph, load_db
from .dem import fetch_dem
from .hydrology import d8_flowdir, fill_depressions, flow_accum
from .landcover import fetch_landcover, impervious_grid
from .swmm_model import build_grid_inp, run_swmm

ROOT = Path(__file__).resolve().parent.parent

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
plt.rcParams["axes.unicode_minus"] = False


def load_aois() -> dict:
    return yaml.safe_load((ROOT / "data" / "aoi.yaml").read_text(encoding="utf-8"))["aois"]


def _downsample(a: np.ndarray, step: int) -> list:
    """DEM 块平均降采样为二维列表（供前端可视化，控制体积）。"""
    h, w = a.shape
    rs = [(g[0], g[-1] + 1) for g in np.array_split(np.arange(h), max(1, h // step))]
    cs = [(g[0], g[-1] + 1) for g in np.array_split(np.arange(w), max(1, w // step))]
    return [[round(float(a[r0:r1, c0:c1].mean()), 1) for c0, c1 in cs] for r0, r1 in rs]


def assess(aoi_name: str, p: int = 50, offline: bool = False, grid: int = 8) -> dict:
    """执行一次内涝快速评估，返回结构化摘要与可视化数据（供 CLI/Agent/Web 复用）。"""
    aoi = load_aois()[aoi_name]
    bbox = tuple(aoi["bbox"])
    out_dir = ROOT / "output" / aoi["slug"] / f"P{p}"  # 按重现期分离，避免相互覆盖
    out_dir.mkdir(parents=True, exist_ok=True)

    elev, transform, _ = fetch_dem(bbox, offline=offline)
    cover, _, _ = fetch_landcover(bbox, offline=offline)
    imp_grid = impervious_grid(cover, grid, grid)

    filled = fill_depressions(elev)
    acc = flow_accum(filled, d8_flowdir(filled))
    exit_lon, exit_lat = xy(transform, *np.unravel_index(int(np.argmax(acc)), acc.shape))

    zone = load_db()[aoi["city"]][aoi["zone"]]
    hy = chicago_hyetograph(zone, P=p, duration=120, dt=5, r=0.4)
    rain_total = float(sum(v for _, v in hy))

    info = build_grid_inp(filled, transform, nx=grid, ny=grid, hyetograph=hy,
                          inp_path=out_dir / "model.inp", imperv=imp_grid)
    stats = run_swmm(out_dir / "model.inp")

    rows = []
    for name, st in stats.items():
        vol = st.get("flooding_volume", 0.0) or 0.0
        if "J" in name:
            i, j = name[1:].split("_")
            rows.append((int(i), int(j), vol, vol / info["area_m2"] * 1000))
    rows.sort(key=lambda x: -x[3])

    _plot(aoi_name, bbox, p, filled, info, rows, out_dir)

    cx, cy = info["cx"], info["cy"]
    viz = {
        "bbox": list(bbox),
        "dem": _downsample(filled, 3),
        "links": [[float(cx[i, j]), float(cy[i, j]), float(cx[d]), float(cy[d])]
                  for (i, j), d in info["down"].items() if d is not None],
        "outfalls": [[float(cx[q]), float(cy[q])] for q in info["outfalls"]],
        "nodes": [{"x": float(cx[i, j]), "y": float(cy[i, j]), "name": f"J{i}_{j}",
                   "depth": round(d)} for i, j, _, d in rows],
        "max_depth": round(rows[0][3], 0) if rows else 0,
        "slug": aoi["slug"], "p": p,
    }
    return {
        "aoi": aoi_name, "city": aoi["city"], "formula_zone": aoi["zone"],
        "return_period_yr": p, "rain_total_mm": round(rain_total, 1),
        "imperv_range_pct": (round(float(imp_grid.min()), 0), round(float(imp_grid.max()), 0)),
        "flood_nodes": sum(1 for r in rows if r[3] > 0), "total_nodes": len(rows),
        "max_depth_mm": round(rows[0][3], 0) if rows else 0.0,
        "top5": [{"node": f"J{i}_{j}", "depth_mm": round(d, 0)} for i, j, _, d in rows[:5]],
        "map": str(out_dir / "flood_map.png"), "inp": str(out_dir / "model.inp"),
        "viz": viz,
        "note": "快速评估级：管网为概化生成（隐含约3年一遇设计标准），积水深为节点溢流折算",
    }


def _plot(aoi_name, bbox, p, filled, info, rows, out_dir: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(13, 6))
    for ax, title in zip(axes, (f"{aoi_name}：地形与概化管网", f"内涝积水点（{p} 年一遇）")):
        im = ax.imshow(filled, cmap="terrain", extent=(bbox[0], bbox[2], bbox[1], bbox[3]), origin="upper")
        ax.set_title(title)
        ax.set_xlabel("经度"); ax.set_ylabel("纬度")
        fig.colorbar(im, ax=ax, label="高程 (m)", shrink=0.85)
    ce, cx, cy = info["cell_elev"], info["cx"], info["cy"]
    ax = axes[0]
    for (i, j), d in info["down"].items():
        if d is not None:
            ax.plot([cx[i, j], cx[d]], [cy[i, j], cy[d]], "b-", lw=1, alpha=0.7)
    for q in info["outfalls"]:
        ax.plot(cx[q], cy[q], "g^", ms=12)
    ax.plot([], [], "g^", label=f"排放口×{len(info['outfalls'])}")
    ax.legend()
    ax = axes[1]
    dep = np.zeros_like(ce)
    for i, j, vol, d in rows:
        dep[i, j] = d
    show = dep > 0
    if show.any():
        ax.scatter(cx[show], cy[show], s=20 + dep[show] * 8, c=dep[show], cmap="Reds",
                   edgecolors="k", lw=0.5, vmin=0)
        for i, j, vol, d in rows[:3]:
            ax.annotate(f"{d:.0f}mm", (cx[i, j], cy[i, j]), ha="center", va="bottom", fontsize=9)
    fig.suptitle("swmm-copilot 快速评估（规划级，非工程设计）", y=0.99)
    fig.tight_layout(w_pad=3.0)
    fig.savefig(out_dir / "flood_map.png", dpi=150)
    plt.close(fig)
