"""Web 界面启动入口。

用法：python examples/webui.py  →  自动打开 http://127.0.0.1:8788
"""

import sys
import threading
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import uvicorn

if __name__ == "__main__":
    threading.Timer(1.5, lambda: webbrowser.open("http://127.0.0.1:8788")).start()
    uvicorn.run("swmm_copilot.server:app", host="127.0.0.1", port=8788, log_level="warning")
