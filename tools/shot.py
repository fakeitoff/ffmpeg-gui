# -*- coding: utf-8 -*-
"""开发辅助：激活指定标题的窗口并截图，用于检查界面排版。"""
import ctypes
import ctypes.wintypes as wt
import sys
import time

from PIL import ImageGrab

# 截图进程也必须是 DPI 感知的，否则拿到的是被系统缩放过的模糊画面
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

user32 = ctypes.windll.user32


def find_windows(substr):
    found = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(hwnd, _lparam):
        length = user32.GetWindowTextLengthW(hwnd)
        if length:
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            if substr.lower() in buf.value.lower() and user32.IsWindowVisible(hwnd):
                found.append((hwnd, buf.value))
        return True

    user32.EnumWindows(cb, 0)
    return found


def main():
    title = sys.argv[1] if len(sys.argv) > 1 else "FFmpeg GUI"
    out = sys.argv[2] if len(sys.argv) > 2 else "shot.png"
    wins = find_windows(title)
    if not wins:
        print("未找到窗口：", title)
        return 1
    hwnd, name = wins[0]
    print(f"窗口：{name}  hwnd={hwnd}")

    user32.ShowWindow(hwnd, 9)          # SW_RESTORE
    user32.SetForegroundWindow(hwnd)
    time.sleep(1.2)

    rect = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    box = (rect.left, rect.top, rect.right, rect.bottom)
    print("窗口区域：", box)
    img = ImageGrab.grab(bbox=box)
    img.save(out)
    print(f"已保存 {out}  尺寸 {img.size}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
