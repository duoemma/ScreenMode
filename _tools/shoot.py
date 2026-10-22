# -*- coding: utf-8 -*-
"""开发辅助：给运行中的主窗口发鼠标消息并截图（仅用于本地验证 UI）。"""
import ctypes
import sys
import time
from ctypes import wintypes as wt

from PIL import ImageGrab

u = ctypes.windll.user32
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202


def find_main():
    return u.FindWindowW("ScreenModeWindow", "屏效助手")


def click(hwnd, x, y):
    lp = (y << 16) | x
    u.PostMessageW(hwnd, WM_LBUTTONDOWN, 1, lp)
    u.PostMessageW(hwnd, WM_LBUTTONUP, 0, lp)


def shot(path, hwnd):
    r = wt.RECT()
    u.GetWindowRect(hwnd, ctypes.byref(r))
    time.sleep(0.6)
    ImageGrab.grab().crop((r.left, r.top, r.right, r.bottom)).save(path)
    print("saved", path)


if __name__ == "__main__":
    hwnd = find_main()
    print("hwnd", hwnd)
    if not hwnd:
        sys.exit(1)
    u.SetForegroundWindow(hwnd)
    for i in range(4):
        click(hwnd, 100, 118 + i * 52 + 23)
        time.sleep(0.8)
        shot("page%d.png" % i, hwnd)
