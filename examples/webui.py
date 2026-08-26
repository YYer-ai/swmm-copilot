"""Web 界面启动入口。

用法：python examples/webui.py  →  浏览器打开 http://127.0.0.1:8788
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import uvicorn

if __name__ == "__main__":
    uvicorn.run("swmm_copilot.server:app", host="127.0.0.1", port=8788, log_level="warning")
