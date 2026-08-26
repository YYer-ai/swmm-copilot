"""M1 最小链路示例：bbox → DEM → 水文分析 → 网格概化 SWMM 模型 → 模拟 → 积水图。

用法：
  python examples/demo_pipeline.py            # 首次运行联网缓存 DEM，之后完全离线
  python examples/demo_pipeline.py --offline  # 强制离线（仅使用本地缓存）
输出：output/demo/model.inp、output/demo/flood_map.png
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from rasterio.transform import xy

from swmm_copilot import chicago_hyetograph, load_db
from swmm_copilot.dem import fetch_dem
from swmm_copilot.hydrology import d8_flowdir, fill_depressions, flow_accum
from swmm_copilot.swmm_model import build_grid_inp, run_swmm

BBOX = (114.03, 22.52, 114.09, 22.57)  # 深圳福田片区 ~5.6km × 5.5km
P, DURATION, DT, R = 50, 120, 5, 0.4   # 50 年一遇，120min，芝加哥雨型

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
plt.rcParams["axes.unicode_minus"] = False


def main():
    offline = "--offline" in sys.argv
    out_dir = ROOT / "output" / "demo"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[1/5] 获取 DEM（{'离线' if offline else '在线/缓存'}） bbox={BBOX}")
    elev, transform, crs = fetch_dem(BBOX, offline=offline)
    print(f"      {elev.shape[1]}×{elev.shape[0]} 像元，高程 {elev.min():.0f}~{elev.max():.0f} m，{crs}")

    print("[2/5] 水文分析：填洼 → D8 流向 → 汇流累积")
    filled = fill_depressions(elev)
    down = d8_flowdir(filled)
    acc = flow_accum(filled, down)
    k = int(np.argmax(acc))
    exit_rc = np.unravel_index(k, acc.shape)
    exit_lon, exit_lat = xy(transform, *exit_rc)
    print(f"      区域出口位于 ({exit_lon:.4f}E, {exit_lat:.4f}N)，汇流累积 {acc.max():.0f} 像元")

    print(f"[3/5] 设计暴雨：深圳·中部流域 {P} 年一遇 {DURATION}min（芝加哥 r={R}）")
    hy = chicago_hyetograph(load_db()["深圳市"]["中部流域和水系"], P, DURATION, DT, R)
    print(f"      总雨量 {sum(v for _, v in hy):.1f} mm")

    print("[4/5] 网格概化建模并运行 SWMM（8×8 网格）")
    info = build_grid_inp(filled, transform, nx=8, ny=8, hyetograph=hy,
                          inp_path=out_dir / "model.inp")
    stats = run_swmm(out_dir / "model.inp")

    print("[5/5] 结果：节点溢流 → 折算地表积水深")
    rows = []
    for name, st in stats.items():
        vol = st.get("flooding_volume", 0.0) or 0.0  # m³
        depth_mm = vol / info["area_m2"] * 1000
        if "J" in name:
            i, j = name[1:].split("_")
            rows.append((int(i), int(j), vol, depth_mm))
    rows.sort(key=lambda x: -x[2])
    print(f"      溢流节点 {sum(1 for r in rows if r[2] > 0)}/{len(rows)} 个；最深 {rows[0][3]:.0f} mm")
    for i, j, vol, d in rows[:5]:
        print(f"      节点 J{i}_{j}: 溢流 {vol:8.1f} m³ → 折算积水深 {d:5.0f} mm")

    # 制图（matplotlib 本地渲染，无在线底图依赖）
    fig, axes = plt.subplots(1, 2, figsize=(13, 6))
    for ax, title in zip(axes, ("填洼后 DEM 与概化管网", "内涝积水点（50 年一遇）")):
        im = ax.imshow(filled, cmap="terrain", extent=(BBOX[0], BBOX[2], BBOX[1], BBOX[3]),
                       origin="upper")
        ax.set_title(f"{title}｜深圳福田片区 {BBOX[2]-BBOX[0]:.2f}°×{BBOX[3]-BBOX[1]:.2f}°")
        ax.set_xlabel("经度"); ax.set_ylabel("纬度")
        fig.colorbar(im, ax=ax, label="高程 (m)", shrink=0.85)
    ce, cx, cy = info["cell_elev"], info["cx"], info["cy"]
    ax = axes[0]
    for (i, j), d in info["down"].items():
        if d is not None:
            ax.plot([cx[i, j], cx[d]], [cy[i, j], cy[d]], "b-", lw=1, alpha=0.7)
    for p in info["outfalls"]:
        ax.plot(cx[p], cy[p], "g^", ms=12)
    ax.plot([], [], "g^", label=f"排放口×{len(info['outfalls'])}")
    ax.legend()
    ax = axes[1]
    dep = np.zeros_like(ce)
    for i, j, vol, d in rows:
        dep[i, j] = d
    show = dep > 0
    ax.scatter(cx[show], cy[show], s=20 + dep[show] * 8, c=dep[show], cmap="Reds",
               edgecolors="k", lw=0.5, vmin=0)
    for i, j, vol, d in rows[:3]:
        ax.annotate(f"{d:.0f}mm", (cx[i, j], cy[i, j]), ha="center", va="bottom", fontsize=9)
    fig.suptitle("swmm-copilot M1 最小链路演示（快速评估，非工程级）", y=0.99)
    fig.tight_layout(w_pad=3.0)
    fig.savefig(out_dir / "flood_map.png", dpi=150)
    print(f"      已输出 {out_dir / 'flood_map.png'}")


if __name__ == "__main__":
    main()
