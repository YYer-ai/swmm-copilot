"""公式库自检：与官方公布的雨量表/单一重现期公式交叉验证。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from swmm_copilot import chicago_hyetograph, intensity, load_db, rain_depth


class TestFormulaLibrary(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = load_db()

    def test_shenzhen_official_tables(self):
        """深圳官方《各历时各重现期降雨量表》抽样点，区间公式复算误差应 < 0.5%。"""
        for zone_name, zone in self.db["深圳市"].items():
            for v in zone.get("validation", []):
                got = rain_depth(zone, v["P"], v["t"])
                rel = abs(got - v["depth"]) / v["depth"]
                self.assertLess(
                    rel, 0.005,
                    f"{zone_name} P={v['P']} t={v['t']}: {got:.3f} vs 官方 {v['depth']} (误差 {rel:.3%})",
                )

    def test_guangzhou_interval_vs_single(self):
        """广州区间公式与单一重现期公式交叉验证（官方精度：相对均方误差 ≤5%）。"""
        zone = self.db["广州市"]["中心城区"]
        for P in (2, 5, 10, 20, 50, 100):
            s = zone["single"][P]
            for t in (30, 60, 120):
                q_single = s["A"] / (t + s["b"]) ** s["n"]
                rel = abs(intensity(zone, P, t) - q_single) / q_single
                self.assertLess(rel, 0.05, f"P={P} t={t}: 区间 vs 单一误差 {rel:.2%}")

    def test_general_form_beijing(self):
        """经典总公式形式（北京）数值合理。"""
        q = intensity(self.db["北京市"]["默认"], P=2, t=20)
        self.assertTrue(120 < q < 260, f"北京 P=2 t=20 得 q={q:.1f}，应在常识范围")

    def test_out_of_range(self):
        zone = self.db["深圳市"]["西部流域和水系"]
        with self.assertRaises(ValueError):
            intensity(zone, P=200, t=30)

    def test_chicago_total_conserved(self):
        """芝加哥雨型各步雨量之和应等于 H(duration)（守恒归一）。"""
        zone = self.db["深圳市"]["中部流域和水系"]
        hy = chicago_hyetograph(zone, P=50, duration=120, dt=5, r=0.4)
        self.assertEqual(len(hy), 24)
        total = sum(v for _, v in hy)
        target = rain_depth(zone, 50, 120)
        self.assertLess(abs(total - target) / target, 1e-9)
        self.assertTrue(all(v > 0 for _, v in hy))

    def test_chicago_peak_position(self):
        """峰值应出现在雨峰位置系数 r 附近（0.4 → 第 10 步左右，48~52min 处）。"""
        zone = self.db["广州市"]["中心城区"]
        hy = chicago_hyetograph(zone, P=10, duration=120, dt=5, r=0.4)
        peak_t = max(hy, key=lambda x: x[1])[0]
        self.assertIn(peak_t, (40, 45, 50), f"峰值出现于 {peak_t}min")


if __name__ == "__main__":
    unittest.main(verbosity=2)
