# -*- coding: utf-8 -*-
"""开发辅助：启动 exe（或附着已运行窗口），找主窗口截图，可按窗口内坐标点击。

用法：
  python _tools/probe.py <exe路径或 -> <输出png> [点击序列 "x,y;x,y"] [标题关键字]
"""
import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes as wt

from PIL import ImageGrab

u = ctypes.windll.user32
u.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))


def find_by_title(keyword, min_w=200, min_h=200):
    hits = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(hwnd, _):
        if not u.IsWindowVisible(hwnd):
            return True
        n = u.GetWindowTextLengthW(hwnd)
        if not n:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        u.GetWindowTextW(hwnd, buf, n + 1)
        if keyword in buf.value:
            r = wt.RECT()
            u.GetWindowRect(hwnd, ctypes.byref(r))
            if r.right - r.left >= min_w and r.bottom - r.top >= min_h:
                hits.append((hwnd, buf.value, r.left, r.top, r.right, r.bottom))
        return True

    u.EnumWindows(cb, 0)
    return hits


def shot(box, path):
    ImageGrab.grab(bbox=box).save(path)
    print("saved", path, box)


def main():
    target = sys.argv[1]
    out = sys.argv[2]
    clicks = sys.argv[3] if len(sys.argv) > 3 else ""
    keyword = sys.argv[4] if len(sys.argv) > 4 else ""

    proc = None
    if target != "-":
        proc = subprocess.Popen([target], cwd=os.path.dirname(target) or ".")

    hits = []
    for _ in range(80):
        time.sleep(0.4)
        hits = find_by_title(keyword) if keyword else []
        if hits:
            break
    if not hits:
        print("no window matching", keyword)
        return 1

    hwnd, title, l, t, r, b = hits[0]
    print("hwnd", hwnd, title, (l, t, r, b))
    time.sleep(1.2)
    shot((l, t, r, b), out if not clicks else out.replace(".png", "_0.png"))

    steps = [s for s in clicks.split(";") if s.strip()]
    for i, item in enumerate(steps, 1):
        cx, cy = [int(v) for v in item.split(",")]
        u.SetForegroundWindow(hwnd)
        time.sleep(0.3)
        lp = ((cy & 0xFFFF) << 16) | (cx & 0xFFFF)
        u.PostMessageW(hwnd, 0x0200, 0, lp)
        u.PostMessageW(hwnd, 0x0201, 1, lp)
        u.PostMessageW(hwnd, 0x0202, 0, lp)
        time.sleep(1.5)
        shot((l, t, r, b), out.replace(".png", "_%d.png" % i))
    if proc:
        print("pid", proc.pid)
    return 0


if __name__ == "__main__":
    sys.exit(main())
