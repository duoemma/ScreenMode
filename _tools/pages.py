# -*- coding: utf-8 -*-
"""开发辅助：附着到正在运行的「屏效助手」窗口，逐个页面截图保存到 docs/。

用法：先运行 main.py，再执行
  python _tools/pages.py
"""
import ctypes
import os
import sys
import time
from ctypes import wintypes as wt

from PIL import Image, ImageGrab

u = ctypes.windll.user32
gdi = ctypes.windll.gdi32
u.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))

TITLE = "屏效助手"
NAV_X = 112
NAV_Y0 = 44 + 20 + 23
NAV_STEP = 52
NAMES = ["status", "groups", "modes", "settings"]


def find_window():
    hits = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(hwnd, _):
        n = u.GetWindowTextLengthW(hwnd)
        if n:
            b = ctypes.create_unicode_buffer(n + 1)
            u.GetWindowTextW(hwnd, b, n + 1)
            if b.value == TITLE and u.IsWindowVisible(hwnd):
                r = wt.RECT()
                u.GetWindowRect(hwnd, ctypes.byref(r))
                if r.bottom - r.top > 400:
                    hits.append((hwnd, r.left, r.top, r.right, r.bottom))
        return True

    u.EnumWindows(cb, 0)
    return hits[0] if hits else None


def click(hwnd, x, y):
    lp = ((y & 0xFFFF) << 16) | (x & 0xFFFF)
    u.PostMessageW(hwnd, 0x0200, 0, lp)
    u.PostMessageW(hwnd, 0x0201, 1, lp)
    u.PostMessageW(hwnd, 0x0202, 0, lp)


def grab_window(hwnd, path):
    """用 PrintWindow 抓窗口自身内容，窗口被别的程序盖住也能截到。"""
    r = wt.RECT()
    u.GetWindowRect(hwnd, ctypes.byref(r))
    w, h = r.right - r.left, r.bottom - r.top
    hdc_screen = u.GetDC(0)
    mem = gdi.CreateCompatibleDC(hdc_screen)
    bmp = gdi.CreateCompatibleBitmap(hdc_screen, w, h)
    old = gdi.SelectObject(mem, bmp)
    ok = u.PrintWindow(hwnd, mem, 2)      # 2 = PW_RENDERFULLCONTENT
    gdi.SelectObject(mem, old)
    u.ReleaseDC(0, hdc_screen)
    if not ok:
        return False

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG),
                    ("biHeight", wt.LONG), ("biPlanes", wt.WORD),
                    ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                    ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", wt.LONG),
                    ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD),
                    ("biClrImportant", wt.DWORD)]

    bi = BITMAPINFOHEADER()
    bi.biSize = ctypes.sizeof(bi)
    bi.biWidth = w
    bi.biHeight = -h                  # 负数 = 自上而下
    bi.biPlanes = 1
    bi.biBitCount = 32
    bi.biCompression = 0
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bi), 0)
    gdi.DeleteObject(bmp)
    gdi.DeleteDC(mem)
    img = Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1)
    img.convert("RGB").save(path)
    return True


def main():
    out_dir = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "docs")
    os.makedirs(out_dir, exist_ok=True)
    win = find_window()
    if not win:
        print("没有找到运行中的窗口，请先启动 main.py")
        return 1
    hwnd, l, t, r, b = win
    print("window", (l, t, r, b))
    u.ShowWindow(hwnd, 9)
    u.SetForegroundWindow(hwnd)
    u.BringWindowToTop(hwnd)
    time.sleep(0.8)
    for i, name in enumerate(NAMES):
        click(hwnd, NAV_X, NAV_Y0 + i * NAV_STEP)
        time.sleep(1.0)
        path = os.path.join(out_dir, "screenshot-%s.png" % name)
        if not grab_window(hwnd, path):
            ImageGrab.grab(bbox=(l, t, r, b)).save(path)
        print("saved", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
