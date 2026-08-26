"""土地覆盖模块测试：依赖已缓存的瓦片（首次运行 demo 后生效），无缓存时跳过。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from swmm_copilot.landcover import CACHE_DIR, fetch_landcover, impervious_grid

HAS_CACHE = any(CACHE_DIR.glob("*.tif"))


@unittest.skipUnless(HAS_CACHE, "无本地土地覆盖缓存（先联网运行一次 demo）")
class TestLandcover(unittest.TestCase):
    def test_fetch_and_imperv(self):
        bbox = (114.03, 22.52, 114.09, 22.57)  # 深圳福田
        cover, transform, crs = fetch_landcover(bbox, offline=True)
        self.assertGreater(cover.size, 10000)
        g = impervious_grid(cover, 8, 8)
        self.assertEqual(g.shape, (8, 8))
        built_share = (cover == 50).mean()
        self.assertGreater(built_share, 0.1, "福田建成区占比应显著")  # 福田是高密度城区
        self.assertTrue(g.max() <= 90.0 + 1e-6)


if __name__ == "__main__":
    unittest.main(verbosity=2)
