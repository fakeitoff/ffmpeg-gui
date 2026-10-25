# -*- coding: utf-8 -*-
"""开发辅助：启动界面并直接切到指定功能页 / 操作模式，方便人工看排版。

自检脚本不做截图比对，界面排版的回归由 selftest 里的几何检查负责；
这个工具只是把「打开界面 → 切到某一页 → 选好文件」压缩成一条命令。

用法： python tools/devshot.py <标签页序号> [操作类型关键字] 文件...
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ui.app import App  # noqa: E402


def main():
    args = sys.argv[1:]
    index = int(args[0]) if args and args[0].isdigit() else 0
    keyword = args[1] if len(args) > 1 and not os.path.exists(args[1]) else None
    files = [a for a in args[1:] if os.path.exists(a)]

    app = App(initial_files=files, initial_tab=index)
    tab = app.tabs[index]
    if keyword and hasattr(tab, "operation"):
        for label in getattr(tab, "OPERATIONS", []):
            pass
        from ui.tabs.tab_merge import OP_LABEL
        for key, label in OP_LABEL.items():
            if keyword in label:
                tab.operation.set(label)
                tab._on_operation()
                break
    app.mainloop()


if __name__ == "__main__":
    main()
