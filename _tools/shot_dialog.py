# -*- coding: utf-8 -*-
"""开发辅助：渲染「添加 / 编辑显示器模式」对话框并截图。

2.2.0 把这个对话框从 342 高扩到 500 高，塞进 5 个画面补偿输入框。
高度一改，标签、提示、说明文字都很容易互相压字，必须目视确认，
所以单独留一个只抓对话框的脚本（主页面由 pages.py 负责）。

用法：python _tools/shot_dialog.py
"""
import ctypes
import os
import sys
import threading
import time
from ctypes import wintypes as wt

u = ctypes.windll.user32
gdi = ctypes.windll.gdi32
u.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
# 64 位下 HDC/HBITMAP 句柄会超 32 位，不设 restype 会 OverflowError
gdi.CreateCompatibleDC.restype = ctypes.c_void_p
gdi.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
gdi.CreateCompatibleBitmap.restype = ctypes.c_void_p
gdi.CreateCompatibleBitmap.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                       ctypes.c_int]
gdi.SelectObject.restype = ctypes.c_void_p
gdi.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
u.GetDC.restype = ctypes.c_void_p
u.GetDC.argtypes = [ctypes.c_void_p]
u.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
u.PrintWindow.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
gdi.GetDIBits.restype = ctypes.c_int
gdi.GetDIBits.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint,
                          ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p,
                          ctypes.c_uint]
gdi.DeleteObject.argtypes = [ctypes.c_void_p]
gdi.DeleteDC.argtypes = [ctypes.c_void_p]

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def grab(hwnd, path):
    """PrintWindow(hwnd, mem, PW_RENDERFULLCONTENT) -> PIL -> 存盘。"""
    r = wt.RECT()
    u.GetWindowRect(hwnd, ctypes.byref(r))
    w, h = r.right - r.left, r.bottom - r.top
    src = u.GetDC(0)
    mem = gdi.CreateCompatibleDC(src)
    bmp = gdi.CreateCompatibleBitmap(src, w, h)
    old = gdi.SelectObject(mem, bmp)
    ok = u.PrintWindow(hwnd, mem, 2)
    gdi.SelectObject(mem, old)
    u.ReleaseDC(0, src)
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
    bi.biHeight = -h
    bi.biPlanes = 1
    bi.biBitCount = 32
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bi), 0)
    gdi.DeleteObject(bmp)
    gdi.DeleteDC(mem)
    from PIL import Image
    Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1)\
         .convert("RGB").save(path)
    return True


# (文件名, 标题, 构造参数)
SHOTS = [
    ("dialog-add", "添加显示器模式", {}),
    ("dialog-edit", "编辑显示器模式",
     {"name": "阅读模式", "vcp": 5,
      "params": {"warm": 1.10, "contrast": 0.92}}),
]


def shoot_one(app, title, kwargs, path):
    from screenmode.ui import dialogs

    dlg = dialogs.ModeDialog(None, app, **kwargs)
    t = threading.Thread(target=dlg.run, daemon=True)
    t.start()

    hwnd = None
    for _ in range(60):
        hwnd = u.FindWindowW(None, title)
        if hwnd and u.IsWindowVisible(hwnd):
            break
        time.sleep(0.1)
    if not hwnd:
        print("  ! 没等到窗口：%s" % title)
        return False

    time.sleep(0.45)          # 等首次 WM_PAINT 走完
    ok = grab(hwnd, path)
    print("  %s %s" % ("saved" if ok else "grab failed", path))
    u.PostMessageW(hwnd, 0x0010, 0, 0)    # WM_CLOSE，结束嵌套消息循环
    time.sleep(0.5)
    return ok


def main():
    from screenmode.app import App

    out_dir = os.path.join(ROOT, "docs")
    os.makedirs(out_dir, exist_ok=True)
    app = App()
    app.refresh_monitors()

    rc = 0
    for name, title, kwargs in SHOTS:
        path = os.path.join(out_dir, "screenshot-%s.png" % name)
        if not shoot_one(app, title, kwargs, path):
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
