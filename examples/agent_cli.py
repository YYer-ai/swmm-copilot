"""交互式 Agent 命令行：自然语言驱动的内涝评估会话。

用法：
  设置环境变量后运行：python examples/agent_cli.py
  （SWMM_COPILOT_BASE_URL / SWMM_COPILOT_API_KEY / SWMM_COPILOT_MODEL）
命令：/reset 清空会话；/exit 退出
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from swmm_copilot.agent import Agent


def main():
    agent = Agent()
    print(f"内涝快评 Agent 已连接（模型 {agent.model}）。输入自然语言开始，/exit 退出。")
    history: list[dict] = []
    while True:
        try:
            user = input("\n你> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not user:
            continue
        if user == "/exit":
            break
        if user == "/reset":
            history.clear()
            print("（会话已清空）")
            continue
        reply = agent.ask(user, history)
        history += [{"role": "user", "content": user},
                    {"role": "assistant", "content": reply}]
        print(f"\n助手> {reply}")
    print("再见。")


if __name__ == "__main__":
    main()
