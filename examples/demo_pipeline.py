"""M1 链路示例：片区 → DEM+土地覆盖 → 水文分析 → 网格概化 SWMM → 积水图（支持离线）。

用法：
  python examples/demo_pipeline.py                          # 默认：深圳福田 50 年一遇
  python examples/demo_pipeline.py --aoi 广州天河 --p 20     # 指定片区与重现期
  python examples/demo_pipeline.py --offline                # 强制离线（仅本地缓存）
输出：output/<片区>/model.inp、flood_map.png
"""

import argparse
import sys
from pathlib import Path

import yaml

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
from swmm_copilot.landcover import fetch_landcover, impervious_grid
from swmm_copilot.swmm_model import build_grid_inp, run_swmm

GRID = 8

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
plt.rcParams["axes.unicode_minus"] = False


def main():
    ap = argparse.ArgumentParser(description="城市内涝快速评估演示")
    ap.add_argument("--aoi", default="深圳福田", help="评估片区名（见 data/aoi.yaml）")
    ap.add_argument("--p", type=int, default=50, help="设计重现期（年）")
    ap.add_argument("--offline", action="store_true", help="仅用本地缓存，不联网")
    args = ap.parse_args()

    aoi = yaml.safe_load((ROOT / "data" / "aoi.yaml").read_text(encoding="utf-8"))["aois"][args.aoi]
    bbox = tuple(aoi["bbox"])
    out_dir = ROOT / "output" / aoi["slug"]  # SWMM 引擎要求 ASCII 路径，故用 slug 命名目录
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[1/6] 获取数据（{'离线' if args.offline else '在线/缓存'}） {args.aoi} bbox={bbox}")
    elev, transform, _ = fetch_dem(bbox, offline=args.offline)
    print(f"      DEM {elev.shape[1]}×{elev.shape[0]} 像元，高程 {elev.min():.0f}~{elev.max():.0f} m")
    cover, _, _ = fetch_landcover(bbox, offline=args.offline)
    imp_grid = impervious_grid(cover, GRID, GRID)
    print(f"      土地覆盖 {cover.shape[1]}×{cover.shape[0]} 像元，"
          f"不透水率 {imp_grid.min():.0f}%~{imp_grid.max():.0f}%（WorldCover 建成区×0.9）")

    print("[2/6] 水文分析：填洼 → D8 流向 → 汇流累积")
    filled = fill_depressions(elev)
    acc = flow_accum(filled, d8_flowdir(filled))
    k = int(np.argmax(acc))
    exit_lon, exit_lat = xy(transform, *np.unravel_index(k, acc.shape))
    print(f"      区域最大汇流出口 ({exit_lon:.4f}E, {exit_lat:.4f}N)，累积 {acc.max():.0f} 像元")

    zone = load_db()[aoi["city"]][aoi["zone"]]
    print(f"[3/6] 设计暴雨：{aoi['city']}·{aoi['zone']} {args.p} 年一遇 120min（芝加哥 r=0.4）")
    hy = chicago_hyetograph(zone, P=args.p, duration=120, dt=5, r=0.4)
    print(f"      总雨量 {sum(v for _, v in hy):.1f} mm")

    print(f"[4/6] 网格概化建模并运行 SWMM（{GRID}×{GRID}）")
    info = build_grid_inp(filled, transform, nx=GRID, ny=GRID, hyetograph=hy,
                          inp_path=out_dir / "model.inp", imperv=imp_grid)
    stats = run_swmm(out_dir / "model.inp")

    print("[5/6] 结果：节点溢流 → 折算地表积水深")
    rows = []
    for name, st in stats.items():
        vol = st.get("flooding_volume", 0.0) or 0.0
        if "J" in name:
            i, j = name[1:].split("_")
            rows.append((int(i), int(j), vol, vol / info["area_m2"] * 1000))
    rows.sort(key=lambda x: -x[3])
    n_flood = sum(1 for r in rows if r[3] > 0)
    print(f"      溢流节点 {n_flood}/{len(rows)}；最深 {rows[0][3]:.0f} mm")
    for i, j, vol, d in rows[:5]:
        print(f"      节点 J{i}_{j}: 溢流 {vol:9.1f} m³ → 积水深 {d:5.0f} mm")

    print("[6/6] 制图（matplotlib 本地渲染）")
    fig, axes = plt.subplots(1, 2, figsize=(13, 6))
    for ax, title in zip(axes, (f"{args.aoi}：地形与概化管网", f"内涝积水点（{args.p} 年一遇）")):
        im = ax.imshow(filled, cmap="terrain", extent=(bbox[0], bbox[2], bbox[1], bbox[3]), origin="upper")
        ax.set_title(title)
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
    if show.any():
        ax.scatter(cx[show], cy[show], s=20 + dep[show] * 8, c=dep[show], cmap="Reds",
                   edgecolors="k", lw=0.5, vmin=0)
        for i, j, vol, d in rows[:3]:
            ax.annotate(f"{d:.0f}mm", (cx[i, j], cy[i, j]), ha="center", va="bottom", fontsize=9)
    fig.suptitle("swmm-copilot 快速评估（规划级，非工程设计）", y=0.99)
    fig.tight_layout(w_pad=3.0)
    fig.savefig(out_dir / "flood_map.png", dpi=150)
    print(f"      已输出 {out_dir / 'flood_map.png'}")


if __name__ == "__main__":
    main()
