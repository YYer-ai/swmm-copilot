"""LLM Agent：自然语言 → 工具调用（列片区/执行评估）→ 中文解读。

模型接入：任意 OpenAI 兼容接口（支持 tools 函数调用）。
配置经环境变量注入（密钥绝不写入代码与仓库）：
  SWMM_COPILOT_BASE_URL / SWMM_COPILOT_API_KEY / SWMM_COPILOT_MODEL
"""

from __future__ import annotations

import json
import os
import urllib.request

from .pipeline import assess, load_aois

MAX_TOOL_ROUNDS = 6

_SYSTEM = """你是「内涝快评」助手，帮助用户完成城市内涝快速评估（swmm-copilot）。
可用工具：
- list_aois：列出当前支持的评估片区
- run_assessment：执行一次评估（参数：aoi 片区名、P 重现期年）
规则：
1. 用户未指明片区或重现期时，先调用 list_aois 并追问；用户说"默认/随便"则选深圳福田、50 年一遇。
2. 评估完成后，用中文解读结果：总雨量、溢流范围、最深处位置与深度、风险图路径；说明这是规划级快速评估（管网为概化生成）。
3. 用户要求改重现期/换片区时再次调用 run_assessment。
4. 不编造工具未返回的数值。"""

_TOOLS = [
    {"type": "function", "function": {
        "name": "list_aois",
        "description": "列出当前支持的评估片区（名称、所属城市、暴雨公式分区）",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "run_assessment",
        "description": "对指定片区按设计重现期执行内涝快速评估（SWMM 概化模拟）",
        "parameters": {"type": "object", "properties": {
            "aoi": {"type": "string", "description": "片区名，必须是 list_aois 中的名称"},
            "P": {"type": "integer", "description": "设计重现期（年），2~100，默认 50"}},
            "required": ["aoi"]}}},
]

_REGISTRY = {
    "list_aois": lambda **kw: [{"aoi": k, "city": v["city"], "formula_zone": v["zone"]}
                               for k, v in load_aois().items()],
    "run_assessment": lambda aoi, P=50: assess(aoi, p=int(P), offline=True),
}


class Agent:
    def __init__(self, base_url: str | None = None, api_key: str | None = None,
                 model: str | None = None, timeout: int = 300):
        self.base_url = (base_url or os.environ.get("SWMM_COPILOT_BASE_URL", "")).rstrip("/")
        self.api_key = api_key or os.environ.get("SWMM_COPILOT_API_KEY", "")
        self.model = model or os.environ.get("SWMM_COPILOT_MODEL", "")
        self.timeout = timeout
        if not (self.base_url and self.api_key and self.model):
            raise RuntimeError(
                "缺少模型配置：请设置环境变量 SWMM_COPILOT_BASE_URL / "
                "SWMM_COPILOT_API_KEY / SWMM_COPILOT_MODEL"
            )

    def _chat(self, messages: list) -> dict:
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps({
                "model": self.model, "messages": messages,
                "tools": _TOOLS, "temperature": 0.2,
            }).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.api_key}"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read())

    def ask(self, user_input: str, history: list[dict] | None = None) -> str:
        """处理一轮用户输入，返回助手回复文本（history 可跨轮累积）。"""
        messages = [{"role": "system", "content": _SYSTEM}] + (history or []) + \
                   [{"role": "user", "content": user_input}]
        for _ in range(MAX_TOOL_ROUNDS):
            out = self._chat(messages)["choices"][0]["message"]
            tool_calls = out.get("tool_calls") or []
            if not tool_calls:
                return out.get("content") or ""
            messages.append({"role": "assistant", "content": out.get("content") or "",
                             "tool_calls": tool_calls})
            for tc in tool_calls:
                fn, raw = tc["function"]["name"], tc["function"]["arguments"]
                try:
                    args = json.loads(raw or "{}")
                    result = _REGISTRY[fn](**args)
                except Exception as e:  # 工具失败也回填，让模型向用户说明
                    result = {"error": f"{type(e).__name__}: {e}"}
                messages.append({"role": "tool", "tool_call_id": tc["id"],
                                 "content": json.dumps(result, ensure_ascii=False, default=str)})
        return "评估工具调用轮数超限，请缩小请求范围后重试。"
