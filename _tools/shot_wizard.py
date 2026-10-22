# -*- coding: utf-8 -*-
"""开发辅助：把「添加显示器引导」的每一步渲染出来并截图。"""
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
gdi.CreateCompatibleDC.restype = ctypes.c_void_p
gdi.DeleteObject.argtypes = [ctypes.c_void_p]
gdi.DeleteDC.argtypes = [ctypes.c_void_p]

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def grab(hwnd, path):
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


def main():
    from screenmode.app import App
    from screenmode.ui import wizard

    app = App()
    app.refresh_monitors()
    print("显示器：", [(m["index"], m["label"]) for m in app.monitors])

    steps = [(wizard.S_PICK, "1_pick"),
             (wizard.S_CUT_A, "2_cut_a"),
             (wizard.S_CUT_B2, "3_cut_b2"),
             (wizard.S_RECORD, "4_record"),
             (wizard.S_FAIL, "5_fail")]

    for step, name in steps:
        wiz = wizard.AddMonitorWizard(app, index=1)
        wiz.step = step
        if step in (wizard.S_CUT_A, wizard.S_CUT_B2):
            wiz.codes = list(range(2, 30))
            wiz.candidates = [0xCC, 0x14, 0xC8]
        if step == wizard.S_RECORD:
            wiz.mode_vcp = 0xCC
            wiz.records = {"用户模式": {"vcp": 1}, "阅读模式": {"vcp": 4}}
        if step == wizard.S_FAIL:
            wiz.codes = [2, 4, 20, 204]

        t = threading.Thread(target=wiz.run, daemon=True)
        t.start()

        hwnd = None
        for _ in range(40):
            hwnd = u.FindWindowW(None, "添加显示器引导")
            if hwnd:
                break
            time.sleep(0.1)
        if not hwnd:
            print("step %s 没找到窗口" % name)
            continue
        time.sleep(0.5)
        path = os.path.join(ROOT, "_shots", "wiz_%s.png" % name)
        grab(hwnd, path)
        print("saved", path)
        u.PostMessageW(hwnd, 0x0010, 0, 0)
        time.sleep(0.6)
    return 0


if __name__ == "__main__":
    sys.exit(main())
