# -*- coding: utf-8 -*-
"""Gamma 通道 + 混合调度的单元测试（不需要真实显示器）。

覆盖两层：
  A. 纯函数：参数归一化、曲线生成、单调性、恒等性
  B. 调度：DDC 能写 -> 只用 DDC；写不动 -> 自动降级 Gamma；HDR -> 让路

B 那部分是这次改动的核心，防的是「程序以为切了、用户什么都没看到」——
也就是 _tools/ddc_test.py 里 wrong_write 模拟的那种静默丢弃。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

VCP_MODE = 0xDC
VCP_BRI = 0x10
VCP_CON = 0x12

OK, BAD = [], []


def check(name, cond, extra=""):
    (OK if cond else BAD).append(name)
    print(("  [OK]   " if cond else "  [FAIL] ") + name
          + ("  " + extra if extra else ""))


# ------------------------------------------------------------------ 假对象
class FakeVCP(object):
    def __init__(self, caps, wrong_write=()):
        self.caps = dict(caps)
        self.writes = []
        self.wrong_write = set(wrong_write)

    def get_vcp_feature(self, code):
        if code not in self.caps:
            raise RuntimeError("该监视器不支持指定的 VCP 代码")
        return self.caps[code]

    def set_vcp_feature(self, code, value):
        if code not in self.caps:
            raise RuntimeError("该监视器不支持指定的 VCP 代码")
        self.writes.append((code, int(value)))
        if code in self.wrong_write:
            # 真机行为：不报错，但值没变（显示器自己又覆盖回去了）
            return
        self.caps[code] = (int(value), self.caps[code][1])


class FakeMonitor(object):
    def __init__(self, caps, wrong_write=()):
        self.vcp = FakeVCP(caps, wrong_write)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeGamma(object):
    """假 Gamma 通道：只记录被写了什么，不碰真显卡。"""

    def __init__(self, devices=None):
        self._devices = devices or ["\\\\.\\DISPLAY5", "\\\\.\\DISPLAY6"]
        self.written = {}
        self.restored = []
        self.last_error = ""

    def outputs(self):
        return [{"device": d, "desc": "", "primary": i == 0}
                for i, d in enumerate(self._devices)]

    def devices(self):
        return list(self._devices)

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
        for d in self._devices:
            self.restore(d)
        return True


def install(monitors):
    import monitorcontrol
    monitorcontrol.get_monitors = lambda: monitors


def make_monitors_payload(n=2):
    out = []
    for i in range(n):
        out.append({"index": i, "device": "\\\\.\\DISPLAY%d" % (i + 5),
                    "controllable": True, "mode_capable": True,
                    "mode_vcp": VCP_MODE, "current": 1,
                    "label": "显示器 %d" % (i + 1), "short": "显示器 %d" % (i + 1)})
    return out


def main():
    from screenmode import apply as AP
    from screenmode import ddc, gamma as G

    # ---------------- A. 纯函数 ----------------
    print("\n[A1] 参数归一化：缺的按 1.0，超范围夹紧")
    p = G.normalize({"warm": 1.2})
    check("只给 warm，其余是 1.0",
          p["warm"] == 1.2 and p["contrast"] == 1.0 and p["sat"] == 1.0, str(p))
    p = G.normalize({"warm": 9.9, "sat": -3})
    check("超上限被夹紧", p["warm"] == G.PARAM_RANGE["warm"][1], str(p["warm"]))
    check("超下限被夹紧", p["sat"] == G.PARAM_RANGE["sat"][0], str(p["sat"]))
    p = G.normalize({"gamma": "坏值"})
    check("非数字退回 1.0", p["gamma"] == 1.0, str(p["gamma"]))
    check("空字典仍是全中性", G.is_neutral(G.normalize({})))

    print("\n[A2] 曲线：恒等、单调、边界")
    ramp = G.build({})
    check("参数全 1 -> 与 identity() 完全一致", ramp == G.identity())
    check("恒等 R[0]=0", ramp[0][0] == 0, str(ramp[0][0]))
    check("恒等 R[255]=65535", ramp[0][255] == 65535, str(ramp[0][255]))
    check("恒等 R[128]≈32768", abs(ramp[0][128] - 32896) <= 128,
          str(ramp[0][128]))

    for name, params in (
            ("偏暖", {"warm": 1.15}),
            ("偏冷", {"warm": 0.85}),
            ("高对比", {"contrast": 1.4}),
            ("低对比", {"contrast": 0.7}),
            ("变暗", {"gamma": 1.8}),
            ("变亮", {"gamma": 0.6}),
            ("重饱和", {"sat": 1.6}),
            ("组合", {"warm": 1.09, "contrast": 0.93, "gamma": 1.1,
                      "sat": 1.2})):
        r = G.build(params)
        mono = all(r[c][k] <= r[c][k + 1] for c in range(3) for k in range(255))
        inrange = all(0 <= v <= 65535 for c in range(3) for v in r[c])
        check("%s 三通道单调不减" % name, mono)
        check("%s 取值不出界" % name, inrange)

    print("\n[A3] 参数方向对不对（拿中间调比）")
    base = G.build({})[0][128]
    warm = G.build({"warm": 1.2})[0][128]
    cool_b = G.build({"warm": 0.8})[2][128]
    check("偏暖让红通道变亮", warm > base, "%d > %d" % (warm, base))
    check("偏冷让蓝通道变亮", cool_b > base, "%d > %d" % (cool_b, base))
    dark = G.build({"gamma": 1.6})[1][128]
    check("gamma>1 中间调变暗", dark < base, "%d < %d" % (dark, base))
    hard = G.build({"contrast": 1.3})
    check("高对比把暗部压得更暗", hard[0][64] < base and hard[0][64] < 20000,
          str(hard[0][64]))

    print("\n[A4] describe 说人话")
    check("全中性 -> 原始画面", G.describe({}) == "原始画面")
    d = G.describe({"warm": 1.1})
    check("偏暖写百分数", "偏暖 10%" in d, d)
    d = G.describe({"warm": 0.9})
    check("偏冷写百分数", "偏冷 10%" in d, d)

    # ---------------- B. 混合调度 ----------------
    print("\n[B1] DDC 写进去且读回一致 -> 只用 DDC，不碰 Gamma")
    main_m = FakeMonitor({VCP_MODE: (1, 11), VCP_BRI: (70, 100)})
    sub_m = FakeMonitor({VCP_MODE: (2, 11), VCP_BRI: (75, 100)})
    install([main_m, sub_m])
    gch = FakeGamma()
    AP.HDR.hdr_devices = lambda: set()
    ctl = ddc.DDCController(indices=[0, 1])
    res = AP.apply_mode({"name": "阅读", "vcp": 5,
                         "gamma": {"warm": 1.1}},
                        ddc=ctl, gch=gch, monitors=make_monitors_payload())
    check("整体成功", res["ok"] is True, str(res["ok"]))
    check("两台都写进 0xDC=5",
          (VCP_MODE, 5) in main_m.vcp.writes
          and (VCP_MODE, 5) in sub_m.vcp.writes)
    check("两条都算 OK 通道",
          all(v["status"] == AP.STATUS_OK for v in res["per_state"].values()),
          str(res["per_state"]))
    check("Gamma 完全没动", gch.written == {}, str(gch.written))
    check("摘要写的是档位", "1号" in res["summary"] and "补偿" not in res["summary"],
          res["summary"])
    ctl.close()

    print("\n[B2] DDC 写入被静默丢弃 -> 自动降级 Gamma")
    main_m = FakeMonitor({VCP_MODE: (1, 11)})
    sub_m = FakeMonitor({VCP_MODE: (2, 11)}, wrong_write={VCP_MODE})
    install([main_m, sub_m])
    gch = FakeGamma()
    ctl = ddc.DDCController(indices=[0, 1])
    res = AP.apply_mode({"name": "阅读", "vcp": 5, "gamma": {"warm": 1.1}},
                        ddc=ctl, gch=gch, monitors=make_monitors_payload())
    check("主屏走 DDC", res["ddc_written"] == [0], str(res["ddc_written"]))
    check("副屏被识别为写入被忽略", res["ddc_unverified"] == [1],
          str(res["ddc_unverified"]))
    check("只有副屏套了 Gamma", list(gch.written) == ["\\\\.\\DISPLAY6"],
          str(list(gch.written)))
    check("副屏状态标成 fallback",
          res["per_state"][1]["status"] == AP.STATUS_FALLBACK,
          str(res["per_state"][1]))
    check("主屏没被 Gamma 碰", "\\\\.\\DISPLAY5" not in gch.written)
    check("摘要里能看出降级", "补偿" in res["summary"], res["summary"])
    ctl.close()

    print("\n[B2b] 只认亮度/对比度的屏（真机副屏就是这种）-> 再加一层 Gamma")
    # 真机 H24T09P 的能力串：有 0x10 / 0x12，没有 0xDC。
    # 亮度写进去读回一致（真的生效），但颜色完全没变，
    # 光靠它模拟不出暖色阅读模式，必须叠加 Gamma。
    main_m = FakeMonitor({VCP_MODE: (1, 11)})
    sub_m = FakeMonitor({VCP_BRI: (75, 100), VCP_CON: (55, 100)})
    install([main_m, sub_m])
    gch = FakeGamma()
    ctl = ddc.DDCController(indices=[0, 1])
    res = AP.apply_mode(
        {"name": "阅读", "vcp": 5, "gamma": {"warm": 1.1},
         "per_monitor": {"1": {"brightness": 40, "contrast": 62}}},
        ddc=ctl, gch=gch, monitors=make_monitors_payload())
    check("副屏写了亮度", (VCP_BRI, 40) in sub_m.vcp.writes,
          str(sub_m.vcp.writes))
    check("主屏没被 Gamma 碰", "\\\\.\\DISPLAY5" not in gch.written,
          str(list(gch.written)))
    check("副屏**额外**套了 Gamma", "\\\\.\\DISPLAY6" in gch.written,
          str(list(gch.written)))
    check("副屏短标是「亮/对+补偿」",
          res["per_state"][1].get("short") == "亮/对+补偿",
          str(res["per_state"][1]))
    check("摘要写成 亮/对+补偿", "亮/对+补偿" in res["summary"], res["summary"])
    ctl.close()

    print("\n[B3] DDC 完全不通 -> 全部走 Gamma")
    install([])                       # 一台都打不开
    gch = FakeGamma()
    ctl = ddc.DDCController(indices=[0, 1])
    res = AP.apply_mode({"name": "电影", "vcp": 2, "gamma": {"contrast": 1.1}},
                        ddc=ctl, gch=gch, monitors=make_monitors_payload())
    check("两台都套了 Gamma", len(gch.written) == 2, str(list(gch.written)))
    check("整体仍算成功", res["ok"] is True)
    check("摘要全是补偿", res["summary"].count("补偿") == 2, res["summary"])

    print("\n[B4] 目标屏 HDR 开着 -> Gamma 让路，并标出来")
    install([])
    gch = FakeGamma()
    AP.HDR.hdr_devices = lambda: {"\\\\.\\DISPLAY5"}
    ctl = ddc.DDCController(indices=[0, 1])
    ctl.ensure()
    res = AP.apply_mode({"name": "电影", "vcp": 2, "gamma": {"contrast": 1.1}},
                        ddc=ctl, gch=gch, monitors=make_monitors_payload())
    check("HDR 那块没写 Gamma", "\\\\.\\DISPLAY5" not in gch.written,
          str(list(gch.written)))
    check("另一块照常写", "\\\\.\\DISPLAY6" in gch.written)
    check("状态标成 hdr", res["per_state"][0]["status"] == AP.STATUS_HDR,
          str(res["per_state"][0]))
    check("需要提醒 HDR", AP.needs_gamma_notice(res) is True)
    check("摘要写了 HDR 阻止", "HDR" in res["summary"], res["summary"])

    print("\n[B5] 只有画面补偿的模式（vcp=None）也能落地")
    install([])
    gch = FakeGamma()
    AP.HDR.hdr_devices = lambda: set()      # B4 打过补丁，这里要还原
    ctl = ddc.DDCController(indices=[0, 1])
    res = AP.apply_mode({"name": "自建", "vcp": None,
                         "gamma": {"warm": 1.2, "sat": 1.1}},
                        ddc=ctl, gch=gch, monitors=make_monitors_payload())
    check("两台都套上补偿", len(gch.written) == 2, str(list(gch.written)))
    check("算成功", res["ok"] is True)
    check("参数原样传下去", gch.written["\\\\.\\DISPLAY5"]["warm"] == 1.2,
          str(gch.written["\\\\.\\DISPLAY5"]))

    print("\n[B6] Gamma 全局关闭 -> 无论 DDC 通不通都不动显卡")
    install([])
    gch = FakeGamma()
    ctl = ddc.DDCController(indices=[0, 1])
    res = AP.apply_mode({"name": "阅读", "vcp": 5, "gamma": {"warm": 1.1}},
                        ddc=ctl, gch=gch, monitors=make_monitors_payload(),
                        use_gamma=False)
    check("Gamma 一次都没写", gch.written == {}, str(gch.written))
    check("整体判为失败（无通道可用）", res["ok"] is False, str(res["ok"]))

    print("\n[B7] 模式参数全中性 -> 视为没有补偿，不做无用写入")
    install([])
    gch = FakeGamma()
    ctl = ddc.DDCController(indices=[0, 1])
    res = AP.apply_mode({"name": "空", "vcp": None,
                         "gamma": {"warm": 1.0, "sat": 1.0}},
                        ddc=ctl, gch=gch, monitors=make_monitors_payload())
    check("没有写入", gch.written == {}, str(gch.written))
    check("判为失败", res["ok"] is False)

    print("\n[B7b] 只勾副屏 -> 主屏连补偿都不许套")
    install([])
    gch = FakeGamma()
    ctl = ddc.DDCController(indices=[1])
    res = AP.apply_mode({"name": "纯补偿", "vcp": None, "gamma": {"warm": 1.1}},
                        ddc=ctl, gch=gch, monitors=make_monitors_payload(),
                        controlled=[1])
    check("只给勾的那块套补偿", list(gch.written) == ["\\\\.\\DISPLAY6"],
          str(list(gch.written)))
    check("主屏一次都没被碰", "\\\\.\\DISPLAY5" not in gch.written)
    check("主屏不出现在结果里", 0 not in res["per_state"],
          str(sorted(res["per_state"])))

    print("\n[B7c] 取消勾选后，主屏上残留的补偿要撤掉")
    gch = FakeGamma()
    gch.apply("\\\\.\\DISPLAY5", {"warm": 1.25})      # 上一轮留下的
    gch.apply("\\\\.\\DISPLAY6", {"warm": 1.25})
    ctl = ddc.DDCController(indices=[1])
    AP.apply_mode({"name": "纯补偿", "vcp": None, "gamma": {"warm": 1.1}},
                  ddc=ctl, gch=gch, monitors=make_monitors_payload(),
                  controlled=[1])
    check("主屏旧补偿被撤销", "\\\\.\\DISPLAY5" in gch.restored, str(gch.restored))
    check("副屏换成新参数",
          gch.written.get("\\\\.\\DISPLAY6", {}).get("warm") == 1.1,
          str(gch.written.get("\\\\.\\DISPLAY6")))

    print("\n[B8] restore 会把每块屏都拉回基线")
    gch = FakeGamma()
    gch.apply("\\\\.\\DISPLAY5", {"warm": 1.1})
    gch.apply("\\\\.\\DISPLAY6", {"warm": 1.1})
    gch.restore_all()
    check("两块都恢复", sorted(gch.restored) == ["\\\\.\\DISPLAY5",
                                                 "\\\\.\\DISPLAY6"],
          str(gch.restored))
    check("恢复后没有残留参数", gch.written == {})

    print("\n[B9] describe_channels：模式配置一目了然")
    s = AP.describe_channels({"vcp": 5, "gamma": {"warm": 1.1}})
    check("同时列出档位和补偿", "档位 5" in s and "偏暖" in s, s)
    s = AP.describe_channels({})
    check("空配置给出提示", "未配置" in s, s)

    print("\n[B10] 切到没有补偿的模式 -> 上一个模式留下的补偿要撤掉")
    # 不撤的话，切到「用户模式」画面会停在上一个模式的色调上，
    # 用户看到的就是"切不回去"。
    install([])
    gch = FakeGamma()
    ctl = ddc.DDCController(indices=[0, 1])
    AP.apply_mode({"name": "阅读", "vcp": None, "gamma": {"warm": 1.15}},
                  ddc=ctl, gch=gch, monitors=make_monitors_payload())
    check("先套上了补偿", len(gch.written) == 2, str(list(gch.written)))
    res = AP.apply_mode({"name": "用户模式", "vcp": None},
                        ddc=ctl, gch=gch, monitors=make_monitors_payload())
    check("切走后补偿被撤销", gch.written == {}, str(gch.written))
    check("结果里记了撤销了哪些", len(res["gamma_restored"]) == 2,
          str(res["gamma_restored"]))

    print("\n[B11] DDC 恢复能写之后 -> 该屏不再叠补偿")
    install([])
    gch = FakeGamma()
    ctl = ddc.DDCController(indices=[0, 1])
    AP.apply_mode({"name": "阅读", "vcp": None, "gamma": {"warm": 1.15}},
                  ddc=ctl, gch=gch, monitors=make_monitors_payload())
    check("两台都套着", len(gch.written) == 2, str(list(gch.written)))
    # 主屏这次 DDC 通了
    main_m = FakeMonitor({VCP_MODE: (1, 11)})
    sub_m = FakeMonitor({VCP_BRI: (75, 100)})
    install([main_m, sub_m])
    ctl2 = ddc.DDCController(indices=[0, 1])
    AP.apply_mode({"name": "阅读", "vcp": 5, "gamma": {"warm": 1.15}},
                  ddc=ctl2, gch=gch, monitors=make_monitors_payload())
    check("主屏的补偿被撤掉", "\\\\.\\DISPLAY5" not in gch.written,
          str(list(gch.written)))
    check("副屏继续套着", "\\\\.\\DISPLAY6" in gch.written, str(list(gch.written)))
    ctl2.close()

    print("\n结果：OK %d / FAIL %d" % (len(OK), len(BAD)))
    if BAD:
        for n in BAD:
            print("  失败：" + n)
    return 0 if not BAD else 1


if __name__ == "__main__":
    sys.exit(main())
