"""暴雨强度公式求值与芝加哥设计雨型生成。

公式库位于 data/rainfall/*.yaml，三种收录形式：
  general  总公式：  q = A·(1 + C·lgP) / (t + b)^n      A 已含 167 换算
  interval 区间公式：q = 167·A(P) / (t + b(P))^n(P)     A/b/n = p1 + p2·ln(P - p3)
  single   单一重现期：q = A / (t + b)^n（校验用）
统一归一为雨力形式：i_avg(t) = a / (t + b)^n  [mm/min]，累积雨量 H(t) = a·t/(t+b)^n。
单位：q [L/(s·公顷)]，t [min]，P [年]。
"""

from __future__ import annotations

import math
from pathlib import Path

import yaml

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "rainfall"

__all__ = ["load_db", "intensity", "rain_depth", "chicago_hyetograph"]


def load_db() -> dict:
    """读取全部公式库：{城市: {片区: zone字典}}。"""
    db: dict[str, dict] = {}
    for f in sorted(DATA_DIR.glob("*.yaml")):
        doc = yaml.safe_load(f.read_text(encoding="utf-8"))
        if not isinstance(doc, dict) or "zones" not in doc:
            continue
        if "city" in doc:
            db[doc["city"]] = doc["zones"]
        else:  # classic.yaml 类：zones 键即城市名，提升为城市级条目
            for name, zone in doc["zones"].items():
                db[name] = {"默认": zone}
    return db


def _poly(p, P: float) -> float:
    """p1 + p2·ln(P - p3)。"""
    return p[0] + p[1] * math.log(P - p[2])


def _params_at(zone: dict, P: float) -> tuple[float, float, float]:
    """给定重现期 P，返回 (a, b, n)；a 为雨力 [mm/min]。"""
    if "interval" in zone:
        segs = zone["interval"]
        lo0, hi0 = segs[0]["p_range"]
        loN, hiN = segs[-1]["p_range"]
        if P < lo0 or P > hiN:
            raise ValueError(f"重现期 P={P} 超出公式适用范围")
        for seg in reversed(segs):  # 从后向前匹配：边界重现期（如 P=10）归上段，与官方雨量表一致
            lo, hi = seg["p_range"]
            if lo <= P <= hi:
                return _poly(seg["A"], P), _poly(seg["b"], P), _poly(seg["n"], P)
        raise ValueError(f"重现期 P={P} 超出公式适用范围")
    g = zone.get("general")
    if g is None and all(k in zone for k in ("A", "C", "b", "n")):
        g = zone  # classic.yaml 形式：片区值即总公式参数
    if g is None:
        raise ValueError("公式条目缺少 interval/general 参数")
    a = g["A"] * (1 + g["C"] * math.log10(P)) / 167.0
    return a, g["b"], g["n"]


def intensity(zone: dict, P: float, t: float) -> float:
    """设计暴雨强度 q [L/(s·公顷)]。"""
    a, b, n = _params_at(zone, P)
    return 167.0 * a / (t + b) ** n


def rain_depth(zone: dict, P: float, t: float) -> float:
    """历时 t 的设计降雨总量 H(t) = a·t/(t+b)^n [mm]。"""
    a, b, n = _params_at(zone, P)
    return a * t / (t + b) ** n


def chicago_hyetograph(
    zone: dict, P: float, duration: int = 120, dt: int = 5, r: float = 0.4
) -> list[tuple[float, float]]:
    """芝加哥设计雨型（Keifer-Chu，离散构造）。

    瞬时强度取累积曲线导数 H'(τ) = a·(b+(1-n)τ)/(τ+b)^(n+1)，τ 为距峰历时；
    各步雨量按 H(duration) 归一以保证总雨量守恒。
    返回 [(步起点min, 雨量mm), ...]。
    """
    a, b, n = _params_at(zone, P)
    N = round(duration / dt)
    m = round(r * N)
    steps = []
    for k in range(N):
        tau = (abs(k - m) + 0.5) * dt
        steps.append(a * (b + (1 - n) * tau) / (tau + b) ** (n + 1) * dt)
    scale = rain_depth(zone, P, duration) / sum(steps)
    return [(k * dt, v * scale) for k, v in enumerate(steps)]
