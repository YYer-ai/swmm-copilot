"""示例：生成设计暴雨雨型（芝加哥雨型）。

用法：python examples/demo_storm.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from swmm_copilot import chicago_hyetograph, load_db, rain_depth


def main():
    db = load_db()

    print("公式库已加载城市:", "、".join(db.keys()))
    print()

    # 示例 1：深圳中部流域 50 年一遇、历时 120min、芝加哥雨型（r=0.4）
    zone = db["深圳市"]["中部流域和水系"]
    P, duration, dt, r = 50, 120, 5, 0.4
    hy = chicago_hyetograph(zone, P, duration, dt, r)
    print(f"深圳市·中部流域和水系 {P} 年一遇设计暴雨（{duration}min，芝加哥雨型 r={r}）")
    print(f"{'时段(min)':<12}{'雨量(mm)':<10}分布")
    peak = max(v for _, v in hy)
    for t0, v in hy:
        bar = "█" * max(1, round(v / peak * 40))
        print(f"{t0:>4}-{t0 + dt:<6}{v:<10.2f}{bar}")
    total = sum(v for _, v in hy)
    print(f"总雨量 {total:.1f} mm（H({duration})={rain_depth(zone, P, duration):.1f} mm，守恒）")
    print()

    # 示例 2：不同重现期对比（广州中心城区，历时 120min）
    zone = db["广州市"]["中心城区"]
    print("广州市·中心城区 不同重现期 120min 设计总雨量：")
    for p in (2, 5, 10, 20, 50, 100):
        print(f"  {p:>3} 年一遇: {rain_depth(zone, p, 120):6.1f} mm")


if __name__ == "__main__":
    main()
