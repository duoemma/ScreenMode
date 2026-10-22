# -*- coding: utf-8 -*-
"""开发辅助：用真实鼠标事件（SetCursorPos + mouse_event）点击窗口，
走完整的 WM_NCHITTEST → 命中测试链路。PostMessage 会绕过命中测试，测不出这类 bug。

用法：
  python _tools/realclick.py <窗口标题> "<x,y;x,y>" [前缀]
坐标是窗口客户区坐标。
"""
import ctypes
import sys
import time
from ctypes import wintypes as wt

from PIL import ImageGrab

u = ctypes.windll.user32
u.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004


def find_window(title):
    hits = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(hwnd, _):
        n = u.GetWindowTextLengthW(hwnd)
        if n:
            b = ctypes.create_unicode_buffer(n + 1)
            u.GetWindowTextW(hwnd, b, n + 1)
            if b.value == title and u.IsWindowVisible(hwnd):
                r = wt.RECT()
                u.GetWindowRect(hwnd, ctypes.byref(r))
                hits.append((hwnd, r.left, r.top, r.right, r.bottom))
        return True

    u.EnumWindows(cb, 0)
    return hits[0] if hits else None


def real_click(hwnd, box, cx, cy):
    l, t = box[1], box[2]
    u.ShowWindow(hwnd, 9)
    u.SetForegroundWindow(hwnd)
    u.BringWindowToTop(hwnd)
    time.sleep(0.25)
    u.SetCursorPos(l + cx, t + cy)
    time.sleep(0.2)
    u.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.06)
    u.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


def main():
    title = sys.argv[1]
    seq = sys.argv[2]
    prefix = sys.argv[3] if len(sys.argv) > 3 else "click"
    win = find_window(title)
    if not win:
        print("窗口没找到：", title)
        return 1
    hwnd, l, t, r, b = win
    print("window", (l, t, r, b))
    steps = [s for s in seq.split(";") if s.strip()]
    for i, item in enumerate(steps, 1):
        cx, cy = [int(v) for v in item.split(",")]
        real_click(hwnd, win, cx, cy)
        time.sleep(0.9)
        path = "_shots/%s_%d.png" % (prefix, i)
        ImageGrab.grab(bbox=(l, t, r, b)).save(path)
        print("clicked", (cx, cy), "->", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
