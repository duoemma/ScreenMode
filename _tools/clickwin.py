# -*- coding: utf-8 -*-
"""开发辅助：按标题找窗口、按客户端坐标点一下、截图。

页面里的按钮是自绘的、挂在窗口自身上，所以直接 PostMessage 到窗口
就行（主窗口那种"页面是子窗口"的情况要另算，见 _tools/pages.py 的教训）。
"""
import ctypes
import os
import sys
import time
from ctypes import wintypes as wt

u = ctypes.windll.user32
u.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "_tools"))
import pages  # noqa: E402


def find(title):
    hits = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(h, _):
        n = u.GetWindowTextLengthW(h)
        if n:
            b = ctypes.create_unicode_buffer(n + 1)
            u.GetWindowTextW(h, b, n + 1)
            if b.value == title and u.IsWindowVisible(h):
                hits.append(h)
        return True

    u.EnumWindows(cb, 0)
    return hits[0] if hits else None


def rect(h):
    r = wt.RECT()
    u.GetWindowRect(h, ctypes.byref(r))
    return r.right - r.left, r.bottom - r.top


def main():
    title = sys.argv[1] if len(sys.argv) > 1 else "屏幕体检"
    h = find(title)
    if not h:
        print("没找到窗口：%s" % title)
        return 1
    print("hwnd=%s size=%s" % (h, rect(h)))
    for spec in sys.argv[2:]:
        kind, _, arg = spec.partition(":")
        if kind == "click":
            x, y = (int(v) for v in arg.split(","))
            pages.click(h, x, y)
            time.sleep(0.6)
            print("click", x, y, "-> size", rect(h))
        elif kind == "wait":
            time.sleep(float(arg))
        elif kind == "shot":
            path = os.path.join(ROOT, "_shots", arg)
            pages.grab_window(h, path)
            print("shot", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
