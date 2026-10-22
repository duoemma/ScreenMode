# -*- coding: utf-8 -*-
"""开发辅助：验证「跟随活跃屏」这个界面开关是不是真的接上了。

    python _tools/follow_ui_test.py

为什么要单独测这一条：跟随逻辑本身有 follow_test.py（纯逻辑）和
follow_e2e.py（真机），但"界面上那个复选框按下去会不会真的改配置"是另一段
代码 —— 它是原生子窗口，鼠标消息得打到它自己身上才认（往父窗口 PostMessage
坐标是没反应的，白测）。

做法：把主窗口**在本进程里**建出来（不启动 run()，所以不抢单实例锁、
不碰用户正在用的那份配置，数据目录指到临时目录），然后给按钮发 BM_CLICK，
看配置文件、勾选状态、置灰状态三处是否一致。
"""
import ctypes
import json
import os
import shutil
import sys
import tempfile
import time
import traceback
from ctypes import wintypes as wt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = os.path.join(tempfile.gettempdir(), "screenmode-ui-test")
if os.path.isdir(HOME):
    shutil.rmtree(HOME, ignore_errors=True)
os.makedirs(HOME)
os.environ["SCREENMODE_HOME"] = HOME
sys.path.insert(0, ROOT)

u = ctypes.windll.user32
BM_CLICK, BM_GETCHECK = 0x00F5, 0x00F0
SW_HIDE = 0
LABEL = "跟随活跃屏"
CFG = os.path.join(HOME, "config.json")

OK = [0, 0]


def check(name, cond, extra=""):
    if cond:
        OK[0] += 1
        print("  [OK]   %s %s" % (name, extra))
    else:
        OK[1] += 1
        print("  [FAIL] %s %s" % (name, extra))


def child_text(h):
    n = u.GetWindowTextLengthW(h)
    if not n:
        return ""
    b = ctypes.create_unicode_buffer(n + 1)
    u.GetWindowTextW(h, b, n + 1)
    return b.value


def children(parent):
    out = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(h, _):
        out.append((h, child_text(h), bool(u.IsWindowEnabled(h))))
        return True

    u.EnumChildWindows(parent, cb, 0)
    return out


def reals(kids):
    """真正挂着显示器的勾选框（"显示器 1  2560×1440" 这种带分辨率）。"""
    return [k for k in kids if k[1].startswith("显示器 ") and "×" in k[1]]


def main():
    from screenmode.app import App
    from screenmode.ui.mainwindow import MainWindow

    app = App()
    app.refresh_monitors()
    app.ui = MainWindow(app)
    if not app.ui.create_window():
        print("主窗口建不出来")
        return 2
    hwnd = app.ui.hwnd
    u.ShowWindow(hwnd, SW_HIDE)        # 别在用户屏幕上闪一下

    kids = children(hwnd)
    names = [k[1] for k in kids if k[1]]
    print("子窗口（前 12 个）：%s" % names[:12])

    try:
        print("\n[A] 复选框存在且默认不勾")
        box = [k[0] for k in kids if k[1] == LABEL]
        check("界面上有「%s」按钮" % LABEL, bool(box))
        if not box:
            return 1
        box = box[0]
        check("默认没勾", u.SendMessageW(box, BM_GETCHECK, 0, 0) == 0)
        check("配置里默认是关的", app.follow_active() is False)

        print("\n[B] 点一下 → 配置、勾选、置灰三处都要对上")
        u.SendMessageW(box, BM_CLICK, 0, 0)
        time.sleep(0.8)
        with open(CFG, encoding="utf-8") as f:
            saved = json.load(f)
        check("配置里 follow_active 变成 true",
              bool(saved["monitors"]["follow_active"]),
              saved["monitors"]["follow_active"])
        check("App 内存里也是开", app.follow_active() is True)
        check("勾选框画的是勾上的",
              u.SendMessageW(box, BM_GETCHECK, 0, 0) == 1)

        mon = reals(children(hwnd))
        check("显示器勾选框被置灰（跟随模式下勾选不决定控谁）",
              bool(mon) and all(not k[2] for k in mon),
              [(k[1], k[2]) for k in mon])

        print("\n[C] 再点一下 → 全部还原")
        u.SendMessageW(box, BM_CLICK, 0, 0)
        time.sleep(0.8)
        with open(CFG, encoding="utf-8") as f:
            saved = json.load(f)
        check("配置回到 false", bool(saved["monitors"]["follow_active"]) is False)
        check("勾选框回到没勾",
              u.SendMessageW(box, BM_GETCHECK, 0, 0) == 0)
        mon = reals(children(hwnd))
        check("显示器勾选框恢复可用",
              bool(mon) and all(k[2] for k in mon),
              [(k[1], k[2]) for k in mon])
        check("控制目标回到按勾选算", app.follow_index() is None)

    except Exception:
        traceback.print_exc()
        OK[1] += 1
    finally:
        try:
            u.DestroyWindow(hwnd)
        except Exception:
            pass
        try:
            app.gch.close()
            app.ddc.close()
        except Exception:
            pass
        shutil.rmtree(HOME, ignore_errors=True)

    print("\n结果：OK %d / FAIL %d" % (OK[0], OK[1]))
    return 0 if OK[1] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
