# -*- coding: utf-8 -*-
"""「跟随活跃屏」的回归测试。

    python _tools/follow_test.py

测四件事：
  A. 活跃屏判定：前台窗口优先、桌面/任务栏退回鼠标
  B. 滞回：候选屏要连续稳定几秒才转移，抖动一次就重置
  C. keep_others：控制权转移后，旧屏的补偿不能被撤掉
  D. 配置：老配置没有这两个字段时要走默认值

用桩对象驱动 App 的方法，不碰真显示器。
"""
import os
import sys
import time
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from screenmode import app as A          # noqa: E402
from screenmode import apply as AP       # noqa: E402
from screenmode import config            # noqa: E402
from screenmode import winapi            # noqa: E402

OK = [0, 0]


def check(name, cond, extra=""):
    if cond:
        OK[0] += 1
        print("  [OK]   %s %s" % (name, extra))
    else:
        OK[1] += 1
        print("  [FAIL] %s %s" % (name, extra))


class FakeGamma(object):
    def __init__(self):
        self.written = {}
        self.restored = []
        self.last_error = ""

    def outputs(self):
        return [{"device": "\\\\.\\DISPLAY5", "desc": "", "primary": True},
                {"device": "\\\\.\\DISPLAY6", "desc": "", "primary": False}]

    def devices(self):
        return ["\\\\.\\DISPLAY5", "\\\\.\\DISPLAY6"]

    def apply(self, device, params):
        self.written[device] = dict(params)
        return True

    def restore(self, device):
        self.restored.append(device)
        self.written.pop(device, None)
        return True

    def applied_devices(self):
        return list(self.written)

    def restore_all(self):
        for d in list(self.written):
            self.restore(d)
        return True


def make_stub(adopted, stable=3.0):
    """造一个只有跟随时钟和映射的假 App。"""
    s = types.SimpleNamespace()
    s.monitors = [{"index": 0, "device": "\\\\.\\DISPLAY5"},
                  {"index": 1, "device": "\\\\.\\DISPLAY6"}]
    s.cfg = {"monitors": {"follow_active": True,
                          "follow_stable_seconds": stable}}
    s._follow_dev = ""
    s._follow_pending = ""
    s._follow_pending_at = 0.0
    s._follow_how = ""
    s.log = lambda *a: None
    for name in ("follow_active", "follow_stable_seconds", "_index_of_device",
                 "follow_index", "_track_active"):
        setattr(s, name, types.MethodType(getattr(A.App, name), s))
    s._adopt_active = lambda idx, how="", first=False: adopted.append(
        (idx, how, first))
    return s


def test_detect():
    print("\n[A] 活跃屏判定")
    # 用一个真窗口：Win32 下任何前台窗口都能通过 MonitorFromWindow
    dev, how = winapi.active_display()
    check("能返回一个显示器名", dev.startswith("\\\\.\\DISPLAY"), repr(dev))
    check("依据合理", how in ("window", "cursor"), how)

    h = winapi.user32.GetForegroundWindow()
    check("能读到前台窗口类名", isinstance(winapi.window_class(h), str))
    check("桌面类被列进跳过名单", "Progman" in winapi._SHELL_CLASSES)
    check("自己的窗口也在跳过名单",
          "ScreenModeWindow" in winapi._SHELL_CLASSES)


def test_hysteresis():
    print("\n[B] 滞回：稳定才转移，抖动要重置")

    calls = []

    def fake_active(_box):
        return calls[-1] if calls else ("", "")

    real = winapi.active_display
    winapi.active_display = lambda: fake_active(None)
    try:
        adopted = []
        s = make_stub(adopted, stable=3.0)

        calls.append(("\\\\.\\DISPLAY5", "window"))
        s._track_active()
        check("启动第一次直接采纳", adopted[-1][0] == 0 if adopted else False,
              str(adopted))
        check("第一次标记为启动定位",
              bool(adopted and adopted[-1][2] is True), str(adopted))

        calls.append(("\\\\.\\DISPLAY6", "window"))
        s._track_active()
        check("刚变过去还不转移", len(adopted) == 1, str(adopted))

        s._track_active()
        check("再调一次（没过 3 秒）仍然不转移", len(adopted) == 1, str(adopted))

        s._follow_pending_at -= 4.0        # 假装已经过了 4 秒
        s._track_active()
        check("够 3 秒了才转移", len(adopted) == 2 and adopted[-1][0] == 1,
              str(adopted))

        # 抖动：去副屏一下马上回主屏，不该被采纳
        calls.append(("\\\\.\\DISPLAY5", "window"))
        s._track_active()
        calls.append(("\\\\.\\DISPLAY6", "window"))
        s._track_active()
        check("抖动一次就重置计时", len(adopted) == 2, str(adopted))

        # 抖动被重置了，得重新在 DISPLAY5 上待够时间才会转移
        calls.append(("\\\\.\\DISPLAY5", "window"))
        s._track_active()
        s._follow_pending_at -= 4.0
        s._track_active()
        check("回到稳定后再转移", len(adopted) == 3 and adopted[-1][0] == 0,
              str(adopted))

        # 鼠标兜底那条依据也要能传下去
        calls.append(("\\\\.\\DISPLAY6", "cursor"))
        s._track_active()
        s._follow_pending_at -= 4.0
        s._track_active()
        check("鼠标兜底也能触发转移",
              len(adopted) == 4 and adopted[-1][1] == "cursor", str(adopted))

        # 关掉跟随就完全不动作
        s.cfg["monitors"]["follow_active"] = False
        before = len(adopted)
        calls.append(("\\\\.\\DISPLAY5", "window"))
        s._track_active()
        check("关掉跟随后不再动", len(adopted) == before, str(adopted))

        # 不认识的屏（刚插上还没重新检测）不能被采纳
        s.cfg["monitors"]["follow_active"] = True
        s._follow_dev = "\\\\.\\DISPLAY6"
        before = len(adopted)
        calls.append(("\\\\.\\DISPLAY9", "window"))
        s._track_active()
        s._follow_pending_at -= 10.0
        s._track_active()
        check("陌生设备不触发转移", len(adopted) == before, str(adopted))
    finally:
        winapi.active_display = real


def test_keep_others():
    print("\n[C] keep_others：旧屏的补偿要留着")
    mode = {"name": "阅读", "vcp": None, "gamma": {"warm": 1.1}}

    gch = FakeGamma()
    gch.apply("\\\\.\\DISPLAY5", {"warm": 1.2})
    gch.apply("\\\\.\\DISPLAY6", {"warm": 1.2})
    AP.apply_mode(mode, gch=gch,
                  monitors=[{"index": 0, "device": "\\\\.\\DISPLAY5"},
                            {"index": 1, "device": "\\\\.\\DISPLAY6"}],
                  controlled=[1], keep_others=True)
    check("旧屏 DISPLAY5 没被撤", "\\\\.\\DISPLAY5" not in gch.restored,
          str(gch.restored))
    check("新屏换成新参数",
          gch.written.get("\\\\.\\DISPLAY6", {}).get("warm") == 1.1,
          str(gch.written.get("\\\\.\\DISPLAY6")))

    # 手动取消勾选走的还是老路子：范围外的要撤掉
    gch2 = FakeGamma()
    gch2.apply("\\\\.\\DISPLAY5", {"warm": 1.2})
    gch2.apply("\\\\.\\DISPLAY6", {"warm": 1.2})
    AP.apply_mode(mode, gch=gch2,
                  monitors=[{"index": 0, "device": "\\\\.\\DISPLAY5"},
                            {"index": 1, "device": "\\\\.\\DISPLAY6"}],
                  controlled=[1], keep_others=False)
    check("不开 keep_others 时旧屏照样被撤",
          "\\\\.\\DISPLAY5" in gch2.restored, str(gch2.restored))


def test_config():
    print("\n[D] 配置默认值与迁移")
    d = config.default_config()
    check("默认不开跟随", d["monitors"]["follow_active"] is False)
    check("默认 3 秒", d["monitors"]["follow_stable_seconds"] == 3.0)

    old = {"version": 2, "monitors": {"enabled": [1], "vcp": {},
                                      "setup_done": {"1": True}}}
    cfg = config.migrate(old)
    check("老配置补上 follow_active", cfg["monitors"]["follow_active"] is False)
    check("老配置补上 stable", cfg["monitors"]["follow_stable_seconds"] == 3.0)
    check("老的 enabled 没被弄丢", cfg["monitors"]["enabled"] == [1],
          str(cfg["monitors"]["enabled"]))

    bad = {"version": 2, "monitors": {"follow_active": True,
                                      "follow_stable_seconds": 999}}
    cfg2 = config.migrate(bad)
    check("离谱的滞回值被夹到 30 秒",
          cfg2["monitors"]["follow_stable_seconds"] == 30.0,
          str(cfg2["monitors"]["follow_stable_seconds"]))
    check("follow_active 保住了", cfg2["monitors"]["follow_active"] is True)


def test_status_label():
    print("\n[E] 状态卡文案")
    s = types.SimpleNamespace()
    s.monitors = [{"index": 0, "device": "\\\\.\\DISPLAY5",
                   "label": "显示器 1 · 27M1"},
                  {"index": 1, "device": "\\\\.\\DISPLAY6",
                   "label": "显示器 2 · H24T09P"}]
    s.cfg = {"monitors": {"follow_active": True}}
    s._follow_dev = "\\\\.\\DISPLAY6"
    s._follow_how = "window"
    s.log = lambda *a: None
    for name in ("follow_active", "follow_index", "_index_of_device",
                 "monitor_labels", "monitor_label", "cfg_indices",
                 "ddc_indices"):
        setattr(s, name, types.MethodType(getattr(A.App, name), s))
    s.ddc_indices = types.MethodType(A.App.ddc_indices, s)
    label = s.monitor_label()
    check("跟随模式写明跟的是哪台", "H24T09P" in label, label)
    check("并标出判定依据", "前台窗口" in label, label)

    s.cfg["monitors"]["follow_active"] = False
    s.cfg["monitors"]["enabled"] = [0, 1]
    label2 = s.monitor_label()
    check("关掉后回到普通文案", "共 2 台" in label2, label2)


def main():
    test_detect()
    test_hysteresis()
    test_keep_others()
    test_config()
    test_status_label()
    print("\n结果：OK %d / FAIL %d" % (OK[0], OK[1]))
    return 0 if OK[1] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
