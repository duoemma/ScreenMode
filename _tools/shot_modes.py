# -*- coding: utf-8 -*-
"""开发辅助：启动主程序，切到「显示器与模式」页并截图。

用法：python _tools/shot_modes.py [输出文件名]
默认输出 _shots/modes_multi.png（不覆盖 docs/ 里的正式截图）。
"""
import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes as wt

u = ctypes.windll.user32
gdi = ctypes.windll.gdi32
u.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable

NAV_X = 112
NAV_Y0 = 44 + 20 + 23
NAV_STEP = 52
MODES_INDEX = 2


def find_main():
    return u.FindWindowW("ScreenModeWindow", "屏效助手")


def click(hwnd, x, y):
    lp = ((y & 0xFFFF) << 16) | (x & 0xFFFF)
    u.PostMessageW(hwnd, 0x0200, 0, lp)
    u.PostMessageW(hwnd, 0x0201, 1, lp)
    u.PostMessageW(hwnd, 0x0202, 0, lp)


def grab_window(hwnd, path):
    r = wt.RECT()
    u.GetWindowRect(hwnd, ctypes.byref(r))
    w, h = r.right - r.left, r.bottom - r.top
    hdc_screen = u.GetDC(0)
    mem = gdi.CreateCompatibleDC(hdc_screen)
    bmp = gdi.CreateCompatibleBitmap(hdc_screen, w, h)
    old = gdi.SelectObject(mem, bmp)
    ok = u.PrintWindow(hwnd, mem, 2)          # PW_RENDERFULLCONTENT
    gdi.SelectObject(mem, old)
    u.ReleaseDC(0, hdc_screen)
    if not ok:
        return False

    class BIH(ctypes.Structure):
        _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG),
                    ("biHeight", wt.LONG), ("biPlanes", wt.WORD),
                    ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                    ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", wt.LONG),
                    ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD),
                    ("biClrImportant", wt.DWORD)]

    bi = BIH()
    bi.biSize = ctypes.sizeof(bi)
    bi.biWidth = w
    bi.biHeight = -h                          # 负数 = 自上而下
    bi.biPlanes = 1
    bi.biBitCount = 32
    bi.biCompression = 0
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bi), 0)
    gdi.DeleteObject(bmp)
    gdi.DeleteDC(mem)
    from PIL import Image
    img = Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1)
    img.convert("RGB").save(path)
    return True


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "modes_multi.png"
    path = os.path.join(ROOT, "_shots", out)
    os.makedirs(os.path.dirname(path), exist_ok=True)

    proc = subprocess.Popen([PY, os.path.join(ROOT, "main.py"), "--dry-run"],
                            cwd=ROOT)
    hwnd = None
    try:
        for _ in range(60):
            hwnd = find_main()
            if hwnd and u.IsWindowVisible(hwnd):
                break
            time.sleep(0.3)
        print("窗口:", bool(hwnd))
        if not hwnd:
            return 1
        u.ShowWindow(hwnd, 9)
        u.SetForegroundWindow(hwnd)
        time.sleep(0.6)
        click(hwnd, NAV_X, NAV_Y0 + MODES_INDEX * NAV_STEP)
        time.sleep(1.0)
        if grab_window(hwnd, path):
            print("saved", path)
        else:
            print("PrintWindow 失败")
            return 1
    finally:
        try:
            proc.kill()
            proc.wait(timeout=5)
        except Exception:
            pass
        subprocess.run(["taskkill", "/F", "/IM", "屏效助手.exe"],
                       capture_output=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
