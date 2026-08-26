"""命令行评估示例（pipeline 的薄壳）。

用法：
  python examples/demo_pipeline.py                          # 默认：深圳福田 50 年一遇
  python examples/demo_pipeline.py --aoi 广州天河 --p 20
  python examples/demo_pipeline.py --offline
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from swmm_copilot.pipeline import assess, load_aois


def main():
    ap = argparse.ArgumentParser(description="城市内涝快速评估")
    ap.add_argument("--aoi", default="深圳福田", help=f"评估片区名，可选：{'、'.join(load_aois())}")
    ap.add_argument("--p", type=int, default=50, help="设计重现期（年）")
    ap.add_argument("--offline", action="store_true", help="仅用本地缓存，不联网")
    args = ap.parse_args()

    r = assess(args.aoi, p=args.p, offline=args.offline)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    print(f"\n积水风险图：{r['map']}")


if __name__ == "__main__":
    main()
