"""本地 Web 界面：模型配置（含测试连接）+ 自然语言评估对话。

启动：python examples/webui.py  →  http://127.0.0.1:8765
除 LLM API 外全部本地资源（前端无 CDN 依赖，可离线打开）。
配置持久化到项目根 .env（已被 .gitignore 排除，密钥不入仓库）。
"""

from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from .agent import Agent
from .pipeline import load_aois

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
STATIC = ROOT / "static" / "index.html"

app = FastAPI(title="swmm-copilot 内涝快评")

_K = {"base": "SWMM_COPILOT_BASE_URL", "key": "SWMM_COPILOT_API_KEY", "model": "SWMM_COPILOT_MODEL"}


def _load_env() -> dict:
    cfg = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip()
    return cfg


class ConfigIn(BaseModel):
    base_url: str = ""
    api_key: str = ""
    model: str = ""


class ChatIn(BaseModel):
    message: str
    history: list[dict] = []


@app.get("/")
def index():
    return FileResponse(STATIC)


@app.get("/api/config")
def get_config():
    cfg = _load_env()
    key = cfg.get(_K["key"], "")
    return {
        "base_url": cfg.get(_K["base"], ""),
        "api_key": key[:8] + "…" if len(key) > 8 else key,  # 脱敏回显
        "model": cfg.get(_K["model"], ""),
    }


@app.post("/api/config")
def save_config(c: ConfigIn):
    if not (c.base_url and c.model):
        return JSONResponse({"ok": False, "error": "Base URL 与模型名不能为空"}, status_code=400)
    cfg = _load_env()
    cfg[_K["base"]] = c.base_url.strip().rstrip("/")
    if c.api_key and not c.api_key.endswith("…"):  # 脱敏回显值不覆盖已有密钥
        cfg[_K["key"]] = c.api_key.strip()
    cfg[_K["model"]] = c.model.strip()
    ENV_FILE.write_text("\n".join(f"{k}={v}" for k, v in cfg.items()) + "\n", encoding="utf-8")
    return {"ok": True}


@app.post("/api/test")
def test_connection(c: ConfigIn):
    """测试模型连通性：GET {base}/models，返回延迟与可用模型列表。"""
    cfg = _load_env()
    base = (c.base_url or cfg.get(_K["base"], "")).strip().rstrip("/")
    key = cfg.get(_K["key"], "")
    if c.api_key and not c.api_key.endswith("…"):
        key = c.api_key.strip()
    if not base:
        return {"ok": False, "error": "请先填写 Base URL"}
    req = urllib.request.Request(f"{base}/models",
                                 headers={"Authorization": f"Bearer {key}"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        models = [m.get("id") for m in data.get("data", [])]
        return {"ok": True, "latency_ms": round((time.time() - t0) * 1000), "models": models}
    except Exception as e:
        msg = str(e)
        if "401" in msg:
            hint = "认证失败（401）：请检查 API Key"
        elif "timed out" in msg:
            hint = "连接超时：请检查地址可达性（注意应为 http(s)://…/v1 形式）"
        else:
            hint = f"连接失败：{msg}"
        return {"ok": False, "error": hint}


@app.get("/api/aois")
def aois():
    return [{"aoi": k, "city": v["city"], "zone": v["zone"]} for k, v in load_aois().items()]


@app.post("/api/chat")
def chat(ci: ChatIn):
    cfg = _load_env()
    try:
        agent = Agent(base_url=cfg.get(_K["base"]), api_key=cfg.get(_K["key"]),
                      model=cfg.get(_K["model"]))
    except RuntimeError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    try:
        agent = Agent(base_url=cfg.get(_K["base"]), api_key=cfg.get(_K["key"]),
                      model=cfg.get(_K["model"]))
        Agent.last_result = None
        reply = agent.ask(ci.message, ci.history)
        return {"ok": True, "reply": reply, "result": Agent.last_result}
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"{type(e).__name__}: {e}"}, status_code=500)


@app.get("/api/artifact")
def artifact(aoi: str, p: int, name: str = "flood_map.png"):
    """评估产物文件服务（限 output/ 下白名单文件，防路径穿越）。"""
    if name not in ("flood_map.png", "model.inp") or "/" in aoi or ".." in aoi:
        return JSONResponse({"ok": False, "error": "非法请求"}, status_code=400)
    f = ROOT / "output" / aoi / f"P{p}" / name
    if not f.exists():
        return JSONResponse({"ok": False, "error": "文件不存在"}, status_code=404)
    return FileResponse(f)
