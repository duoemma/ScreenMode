# -*- coding: utf-8 -*-
"""冒烟测试：模拟点击走完「添加显示器引导」全流程。

不切模式，所以必然走「识别失败 -> 改用亮度/对比度」这条兜底路径，
正好把最坏情况跑一遍，确认每个步骤切换都不会崩。
"""
import os
import sys
import threading
import time

import ctypes

u = ctypes.windll.user32
u.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

TITLE = "添加显示器引导"
W, H = 680, 530
FAIL = []


def win():
    return u.FindWindowW(None, TITLE)


def click(hwnd, x, y):
    lp = ((y & 0xFFFF) << 16) | (x & 0xFFFF)
    u.PostMessageW(hwnd, 0x0200, 0, lp)
    u.PostMessageW(hwnd, 0x0201, 1, lp)
    u.PostMessageW(hwnd, 0x0202, 0, lp)


def shot(hwnd, name):
    from PIL import ImageGrab
    from ctypes import wintypes as wt
    r = wt.RECT()
    u.GetWindowRect(hwnd, ctypes.byref(r))
    ImageGrab.grab(bbox=(r.left, r.top, r.right, r.bottom),
                   all_screens=True).save(
        os.path.join(ROOT, "_shots", "smoke_%s.png" % name))


def wait_step(wiz, want, timeout=12):
    """轮询等 step 变成期望值 —— 读能力串 / 扫 24 个码都要时间，
    固定 sleep 会把"还没轮到"误判成"没生效"。"""
    end = time.time() + timeout
    while time.time() < end:
        if wiz.step == want:
            return True
        time.sleep(0.2)
    return False


def check(name, cond, extra=""):
    print(("  [OK]   " if cond else "  [FAIL] ") + name
          + ("  " + extra if extra else ""))
    if not cond:
        FAIL.append(name)


def main():
    from screenmode.app import App
    app = App()
    app.refresh_monitors()
    from screenmode.ui import wizard

    wiz = wizard.AddMonitorWizard(app, index=1)
    t = threading.Thread(target=wiz.run, daemon=True)
    t.start()

    hwnd = None
    for _ in range(50):
        hwnd = win()
        if hwnd:
            break
        time.sleep(0.1)
    check("向导窗口已创建", hwnd is not None)
    if not hwnd:
        return 1
    time.sleep(0.6)

    print("\n[1] 选显示器 -> 开始识别")
    click(hwnd, W - 85, H - 42)
    ok1 = wait_step(wiz, wizard.S_CUT_A)
    check("进入切模式步骤", ok1, "step=%d" % wiz.step)
    check("扫到了码", len(wiz.codes) > 5, "%d 个" % len(wiz.codes))
    shot(hwnd, "1_cut_a")

    print("\n[2] 第一次「已切好」（没切模式）")
    click(hwnd, W - 100, H - 42)
    ok2 = wait_step(wiz, wizard.S_CUT_B)
    check("进入第二次切模式", ok2, "step=%d" % wiz.step)
    check("拿到了快照 A", len(wiz.snap_a) > 5, "%d 个码" % len(wiz.snap_a))

    print("\n[3] 第二次「已切好」（还是没切）-> 应该识别失败")
    click(hwnd, W - 100, H - 42)
    ok3 = wait_step(wiz, wizard.S_FAIL)
    check("走到失败兜底页", ok3, "step=%d" % wiz.step)
    shot(hwnd, "2_fail")

    print("\n[4] 改用亮度/对比度")
    click(hwnd, W - 120, H - 42)
    time.sleep(1.0)
    check("进入逐模式记录", wiz.step == wizard.S_RECORD, "step=%d" % wiz.step)
    check("标记为亮度对比度通道", wiz.use_bc is True)

    print("\n[5] 依次记录 5 个模式")
    modes = wiz._mode_names()
    for i in range(len(modes)):
        # 只点「记录」按钮（左下角是取消，别误点）
        click(hwnd, W - 110, H - 42)
        for _ in range(40):
            if len(wiz.records) > i or wiz.step == wizard.S_DONE:
                break
            time.sleep(0.15)
        print("      第 %d/%d 次 -> step=%d, 已记录 %d"
              % (i + 1, len(modes), wiz.step, len(wiz.records)))
    check("全部记录完", len(wiz.records) == len(modes),
          "%d/%d" % (len(wiz.records), len(modes)))
    check("走到完成页", wiz.step == wizard.S_DONE, "step=%d" % wiz.step)
    if wiz.step == wizard.S_DONE:
        shot(hwnd, "3_done")

    print("\n[6] 点完成")
    click(hwnd, W - 85, H - 42)
    time.sleep(1.0)
    check("窗口已关闭", not u.IsWindow(win() or 0))
    check("返回了结果", wiz.result is not None, str(wiz.result))
    if wiz.result:
        cfg = app.cfg
        done = (cfg.get("monitors") or {}).get("setup_done") or {}
        check("配置里记了 setup_done", done.get("1") is True, str(done))
        per = [(m["name"], m.get("per_monitor")) for m in cfg["modes"]]
        check("模式里记了副屏亮度/对比度",
              any(p and p.get("1") for _, p in per), str(per))

    print("\n结果：%s" % ("全部通过" if not FAIL
                        else "失败 %d 项：%s" % (len(FAIL), "、".join(FAIL))))
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
