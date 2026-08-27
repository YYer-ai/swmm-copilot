"""M4 评估报告测试（TDD：先写失败测试，再实现 swmm_copilot/report.py）。

依赖本地数据缓存（先联网跑过一次 demo），无缓存跳过。
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from swmm_copilot.pipeline import ROOT, assess

from swmm_copilot.report import analyze_impact, generate_docx, generate_markdown  # 待实现

HAS_CACHE = any((ROOT / "cache" / "dem").glob("dem_114.030*"))


@unittest.skipUnless(HAS_CACHE, "无深圳福田缓存（先联网运行一次 demo）")
class TestReport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = assess("深圳福田", p=50, offline=True)

    def test_markdown_sections(self):
        md = generate_markdown(self.result)
        for kw in ("城市内涝快速评估报告", "深圳福田", "50 年一遇", "145.9",
                   "受影响", "J6_3", "规划级", "暴雨强度公式"):
            self.assertIn(kw, md, f"报告缺少关键内容：{kw}")

    def test_impact_communities(self):
        impact = analyze_impact(self.result["viz"])
        self.assertIn("communities", impact)
        self.assertGreater(len(impact["communities"]), 0, "福田积水区内应有受影响社区")
        for c in impact["communities"]:
            self.assertTrue(c["name"])
            self.assertGreater(c["depth_mm"], 0)
        # 按深度降序
        depths = [c["depth_mm"] for c in impact["communities"]]
        self.assertEqual(depths, sorted(depths, reverse=True))

    def test_impact_roads_structure(self):
        impact = analyze_impact(self.result["viz"])
        self.assertIn("roads", impact)
        for rd in impact["roads"]:
            self.assertIn("depth_mm", rd)

    def test_report_file_written(self):
        self.assertIn("report_md", self.result, "assess 结果应含报告路径")
        self.assertTrue(Path(self.result["report_md"]).exists())
        self.assertTrue(Path(self.result["report_md"]).stat().st_size > 1000)

    def test_report_docx_written(self):
        """Word 版报告：assess 结果含路径且文件有效（>10KB）。"""
        self.assertIn("report_docx", self.result)
        p = Path(self.result["report_docx"])
        self.assertTrue(p.exists() and p.stat().st_size > 10_000)
        self.assertEqual(p.read_bytes()[:2], b"PK", "应为 docx（zip）格式")

    def test_docx_direct(self):
        """generate_docx 独立可调，内容含关键段。"""
        out = Path(self.result["report_md"]).with_name("t_report.docx")
        generate_docx(self.result, out)
        self.assertTrue(out.stat().st_size > 10_000)
        out.unlink()


if __name__ == "__main__":
    unittest.main(verbosity=2)
