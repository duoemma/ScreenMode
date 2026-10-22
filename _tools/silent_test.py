# -*- coding: utf-8 -*-
"""端到端验证需求 ②：弹窗选完模式后，不再把主界面顶出来（后台静默切换）。

思路：本机前台一直被「跨屏协作」(miscreenshare.exe) 占着，正好借它当
"被检测到的应用" —— 临时往 config.json 里加一个测试分组，让程序启动后
自然弹出切换确认窗，然后在弹窗里点「立即切换」，检查主界面是否始终隐藏。

跑完自动恢复原 config.json。
"""
import ctypes
import json
import os
import shutil
import subprocess
import sys
import time
from ctypes import wintypes as wt

u = ctypes.windll.user32
u.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG = os.path.join(ROOT, "config.json")
BAK = CFG + ".testbak"
LOG = os.path.join(ROOT, "app.log")
PY = sys.executable
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
WM_CLOSE = 0x0010

FAIL = []


def check(name, cond, extra=""):
    print(("  [OK]   " if cond else "  [FAIL] ") + name
          + ("  " + extra if extra else ""))
    if not cond:
        FAIL.append(name)


def windows():
    out = {}

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(h, _):
        n = u.GetWindowTextLengthW(h)
        if n:
            b = ctypes.create_unicode_buffer(n + 1)
            u.GetWindowTextW(h, b, n + 1)
            out.setdefault(b.value, []).append(h)
        return True

    u.EnumWindows(cb, 0)
    return out


def find(title, visible=True):
    for h in windows().get(title, []):
        if not visible or u.IsWindowVisible(h):
            return h
    return None


def box(h):
    r = wt.RECT()
    u.GetWindowRect(h, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def click(h, cx, cy):
    l, t = box(h)[:2]
    u.ShowWindow(h, 9)
    u.SetForegroundWindow(h)
    u.BringWindowToTop(h)
    time.sleep(0.3)
    u.SetCursorPos(l + cx, t + cy)
    time.sleep(0.15)
    u.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.06)
    u.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


def tail(n=8):
    try:
        with open(LOG, "r", encoding="utf-8", errors="ignore") as f:
            return f.readlines()[-n:]
    except OSError:
        return []


def kill_app(proc):
    """按 PID 杀被测进程（它也是 python.exe，不能按镜像名杀）。"""
    if proc is not None:
        try:
            proc.kill()
            proc.wait(timeout=5)
        except Exception:
            pass
    subprocess.run(["taskkill", "/F", "/IM", "屏效助手.exe"],
                   capture_output=True)


def main():
    shutil.copy2(CFG, BAK)
    cfg = json.load(open(CFG, encoding="utf-8"))
    cfg["dialog_timeout_seconds"] = 30
    groups = [g for g in cfg["groups"] if g.get("id") != "__e2e__"]
    groups.append({
        "id": "__e2e__", "name": "E2E 测试组", "mode": "电影模式",
        "kind": "custom", "enabled": True,
        "apps": [{"name": "跨屏协作", "exe": "miscreenshare.exe",
                  "title": "", "src": "custom"}],
    })
    cfg["groups"] = groups
    with open(CFG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

    app_proc = None
    try:
        app_proc = subprocess.Popen(
            [PY, os.path.join(ROOT, "main.py"), "--dry-run"], cwd=ROOT)
        main_hwnd = None
        for _ in range(40):
            main_hwnd = find("屏效助手")
            if main_hwnd and u.IsWindowVisible(main_hwnd):
                break
            time.sleep(0.3)
        check("主界面已启动", main_hwnd is not None)
        if not main_hwnd:
            return 1

        print("\n[1] 把主界面收进托盘（等价于点右上角 ×）")
        u.PostMessageW(main_hwnd, WM_CLOSE, 0, 0)
        time.sleep(0.8)
        check("主界面已隐藏", not u.IsWindowVisible(main_hwnd))

        print("\n[2] 等切换确认弹窗（前台一直是 miscreenshare.exe）")
        dlg = None
        end = time.time() + 25
        while time.time() < end and dlg is None:
            dlg = find("切换显示器情景模式")
            time.sleep(0.4)
        check("弹出了切换确认窗", dlg is not None)
        if not dlg:
            print("     日志：", "".join(tail(5)).strip())
            return 1
        print("     弹窗 rect =", box(dlg))
        check("弹窗出现时主界面仍然隐藏", not u.IsWindowVisible(main_hwnd))

        print("\n[3] 在弹窗里点「立即切换」")
        click(dlg, 90, 300 - 35)
        time.sleep(1.5)
        check("弹窗已关闭", find("切换显示器情景模式") is None)
        latest = "".join(tail(6))
        check("已经按选择切换了模式", "电影模式" in latest,
              " | ".join(x.strip() for x in tail(3)))
        check("选完后主界面依然是隐藏的", not u.IsWindowVisible(main_hwnd))

        print("\n[4] 记录前台日志，确认没把自己当成前台应用")
        check("日志里没有「前台：屏效助手」",
              not any("前台：屏效助手" in x for x in tail(40)))
    finally:
        kill_app(app_proc)
        time.sleep(0.8)
        if os.path.exists(BAK):
            shutil.move(BAK, CFG)

    print("\n结果：%s" % ("全部通过" if not FAIL
                        else "失败 %d 项：%s" % (len(FAIL), "、".join(FAIL))))
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
