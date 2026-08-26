"""评估流水线测试：依赖本地数据缓存（先联网运行过一次 demo），无缓存时跳过。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from swmm_copilot.pipeline import assess, load_aois

HAS_CACHE = (Path(__file__).resolve().parent.parent / "cache" / "dem").glob("dem_*.tif")


@unittest.skipUnless(any(HAS_CACHE), "无本地 DEM 窗口缓存（先联网运行一次 demo）")
class TestPipeline(unittest.TestCase):
    def test_assess_futian_offline(self):
        r = assess("深圳福田", p=50, offline=True)
        self.assertEqual(r["aoi"], "深圳福田")
        self.assertEqual(r["city"], "深圳市")
        self.assertAlmostEqual(r["rain_total_mm"], 145.9, delta=0.1)  # 与官方雨量表核对过
        self.assertEqual(r["total_nodes"], 64)
        self.assertGreater(r["flood_nodes"], 0)
        self.assertGreater(r["max_depth_mm"], 50)
        self.assertTrue(Path(r["map"]).exists())
        self.assertEqual(len(r["top5"]), 5)

    def test_load_aois(self):
        aois = load_aois()
        self.assertIn("深圳福田", aois)
        for name, v in aois.items():
            self.assertIn("slug", v, f"{name} 缺 slug 字段")
            self.assertIn("city", v)


if __name__ == "__main__":
    unittest.main(verbosity=2)
