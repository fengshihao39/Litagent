"""
星火文献 Agent - 启动入口

运行方式：
    # 方式1：用 venv（推荐）
    source venv/bin/activate
    python xinghuo_agent/main.py

    # 方式2：直接用系统 Python
    python3 xinghuo_agent/main.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent.literature_agent import LiteratureAgent

BANNER = """
╔══════════════════════════════════════════════════════════╗
║         星火文献 Agent  v1.1                             ║
║         西安电子科技大学 · 第37届星火杯参赛项目           ║
║         领域：电子信息 / 人工智能 / 雷达信号处理          ║
║         数据源：arXiv + Semantic Scholar + IEEE Xplore   ║
╚══════════════════════════════════════════════════════════╝

可用指令（直接用中文说就行）：
  搜索方向    →  transformer 雷达目标检测
  解析论文    →  分析 1  /  解析第2篇
  对比论文    →  对比 1 2 3
  生成综述    →  综述 雷达目标检测
  获取引用    →  引用 2
  清空历史    →  清空
  退出        →  退出
"""


def main():
    print(BANNER)

    try:
        agent = LiteratureAgent()
    except Exception as e:
        print(f"[初始化失败] {e}")
        sys.exit(1)

    print("Agent 初始化成功，开始对话！\n")
    print("-" * 58)

    while True:
        try:
            user_input = input("\n你: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n\n再见！结果已保存在 output/ 目录。")
            break

        if not user_input:
            continue

        if user_input in ("退出", "exit", "quit", "q"):
            print("再见！结果已保存在 output/ 目录。")
            break

        if user_input in ("清空", "clear"):
            agent.clear_history()
            continue

        print("\nAgent: ", end="", flush=True)
        try:
            response = agent.chat(user_input)
            print(response)
        except Exception as e:
            print(f"[出错了] {e}")

        print("\n" + "-" * 58)


if __name__ == "__main__":
    main()
