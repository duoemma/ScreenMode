# -*- coding: utf-8 -*-
"""开发辅助：按屏幕坐标点击运行中的界面并截图。

用法：python _tools/act.py 552 495 out.png
"""
import ctypes
import sys
import time
from ctypes import wintypes as wt

from PIL import ImageGrab

u = ctypes.windll.user32


def click_at(sx, sy):
    hwnd = u.WindowFromPoint(wt.POINT(sx, sy))
    pt = wt.POINT(sx, sy)
    u.ScreenToClient(hwnd, ctypes.byref(pt))
    lp = ((pt.y & 0xFFFF) << 16) | (pt.x & 0xFFFF)
    u.PostMessageW(hwnd, 0x0201, 1, lp)
    u.PostMessageW(hwnd, 0x0202, 0, lp)
    return hwnd


def shot_all(path):
    ImageGrab.grab().save(path)


if __name__ == "__main__":
    x, y = int(sys.argv[1]), int(sys.argv[2])
    out = sys.argv[3] if len(sys.argv) > 3 else "act.png"
    h = click_at(x, y)
    print("hwnd", h)
    time.sleep(1.0)
    shot_all(out)
    print("saved", out)
