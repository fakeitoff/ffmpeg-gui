# -*- coding: utf-8 -*-
"""FFmpeg GUI —— 启动入口。

用法：
    python main.py                      启动图形界面
    python main.py 视频1.mp4 视频2.mkv   启动并预加载文件（可多选）
    python main.py --tab 4              启动后直接定位到第 5 个功能页（开发用）
"""
from __future__ import annotations

import os
import sys


def main():
    root = os.path.dirname(os.path.abspath(__file__))
    if root not in sys.path:
        sys.path.insert(0, root)

    try:
        from ui.app import App
    except ImportError as exc:
        print(f"导入界面模块失败：{exc}", file=sys.stderr)
        print("请确认 Python 自带 tkinter（Windows 官方安装包默认包含）。", file=sys.stderr)
        return 1

    argv = sys.argv[1:]
    initial_tab = None
    files = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ("--tab", "-t") and i + 1 < len(argv):
            try:
                initial_tab = int(argv[i + 1])
            except ValueError:
                pass
            i += 2
            continue
        if arg.startswith("--tab="):
            try:
                initial_tab = int(arg.split("=", 1)[1])
            except ValueError:
                pass
            i += 1
            continue
        if not arg.startswith("-"):
            files.append(arg)
        i += 1

    app = App(initial_files=files, initial_tab=initial_tab)
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
