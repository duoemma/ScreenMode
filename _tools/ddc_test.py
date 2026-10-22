# -*- coding: utf-8 -*-
"""多显示器 / 双通道切换的单元测试（不需要真实显示器）。

把 monitorcontrol.get_monitors 换成假对象，验证：
  ① 多台都支持 0xDC -> 一起写
  ② 某台不支持 0xDC 但有亮度/对比度 -> 走辅助通道
  ③ 只写选中的那几台
  ④ 写失败的台会被记进 failed，不会拖垮其它台
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

VCP_MODE = 0xDC
VCP_COLOR = 0x14
VCP_BRI = 0x10
VCP_CON = 0x12

OK, BAD = [], []


def check(name, cond, extra=""):
    (OK if cond else BAD).append(name)
    print(("  [OK]   " if cond else "  [FAIL] ") + name
          + ("  " + extra if extra else ""))


class FakeVCP(object):
    def __init__(self, caps, wrong_write=()):
        self.caps = dict(caps)
        self.writes = []
        # wrong_write：写进去的值会被改成别的（真机实测就是这样：
        # 写 8 读回 5、写 1 读回 4），所以不能拿来当情景模式通道
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
            self.caps[code] = ((int(value) + 3) % 12, self.caps[code][1])
            return
        self.caps[code] = (int(value), self.caps[code][1])


class FakeMonitor(object):
    def __init__(self, caps, wrong_write=()):
        self.vcp = FakeVCP(caps, wrong_write)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def install(monitors):
    import monitorcontrol
    monitorcontrol.get_monitors = lambda: monitors


def main():
    from screenmode import ddc

    # ---------------- ① 两台都支持 0xDC ----------------
    print("\n[1] 两台都支持 0xDC -> 一起切")
    a = FakeMonitor({VCP_MODE: (1, 11), VCP_BRI: (70, 100), VCP_CON: (50, 100)})
    b = FakeMonitor({VCP_MODE: (2, 11), VCP_BRI: (75, 100), VCP_CON: (55, 100)})
    install([a, b])
    c = ddc.DDCController(indices=[0, 1])
    check("打开了 2 台", c.ensure() and len(c.monitors) == 2)
    check("两台都选了 0xDC", c.vcps == {0: VCP_MODE, 1: VCP_MODE}, str(c.vcps))
    check("apply_mode 成功", c.apply_mode({"vcp": 7}) is True)
    check("第 1 台写到 0xDC=7", (VCP_MODE, 7) in a.vcp.writes, str(a.vcp.writes))
    check("第 2 台也写到 0xDC=7", (VCP_MODE, 7) in b.vcp.writes, str(b.vcp.writes))
    check("没有失败项", c.failed == [], str(c.failed))
    c.close()

    # ---------------- ② 只有 0x14 的副屏 ----------------
    print("\n[2a] 副屏只有 0x14，且显式指定 forced_vcp -> 用它")
    main_m = FakeMonitor({VCP_MODE: (1, 11), VCP_BRI: (70, 100),
                          VCP_CON: (50, 100)})
    sub_m = FakeMonitor({VCP_COLOR: (8, 11), VCP_BRI: (75, 100),
                         VCP_CON: (55, 100)})
    install([main_m, sub_m])
    c = ddc.DDCController(indices=[0, 1], forced_vcp={1: VCP_COLOR})
    c.ensure()
    check("第 2 台按指定用了 0x14", c.vcps[1] == VCP_COLOR, str(c.vcps))
    check("describe 标明用了 0x14", "0x14" in c.describe(), c.describe())
    c.apply_mode({"vcp": 2})
    check("副屏也写 0x14=2", (VCP_COLOR, 2) in sub_m.vcp.writes,
          str(sub_m.vcp.writes))
    c.close()

    print("\n[2b] 副屏只有 0x14、没显式指定 -> 默认不碰它（真机写入不可靠）")
    main_m = FakeMonitor({VCP_MODE: (1, 11), VCP_BRI: (70, 100),
                          VCP_CON: (50, 100)})
    sub_m = FakeMonitor({VCP_COLOR: (8, 11), VCP_BRI: (75, 100),
                         VCP_CON: (55, 100)}, wrong_write={VCP_COLOR})
    install([main_m, sub_m])
    c = ddc.DDCController(indices=[0, 1])
    c.ensure()
    check("第 2 台判定为没有模式通道", c.vcps[1] is None, str(c.vcps))
    check("describe 标成走亮度/对比度通道", "亮度/对比度" in c.describe(),
          c.describe())
    check("仍能打开 2 台", len(c.monitors) == 2, str(list(c.monitors)))
    check("探测阶段一次都没写它", sub_m.vcp.writes == [],
          str(sub_m.vcp.writes))

    print("     -> 给它配 per_monitor 后用亮度/对比度模拟")
    mode = {"vcp": 2, "per_monitor": {"1": {"brightness": 60,
                                            "contrast": 62}}}
    check("apply_mode 成功", c.apply_mode(mode) is True)
    check("主屏写 0xDC=2", (VCP_MODE, 2) in main_m.vcp.writes,
          str(main_m.vcp.writes))
    check("副屏写亮度=60", (VCP_BRI, 60) in sub_m.vcp.writes,
          str(sub_m.vcp.writes))
    check("副屏写对比度=62", (VCP_CON, 62) in sub_m.vcp.writes,
          str(sub_m.vcp.writes))
    check("副屏的 0x14 没被乱写", (VCP_COLOR, 2) not in sub_m.vcp.writes,
          str(sub_m.vcp.writes))
    check("两台都算成功", sorted(c.written) == [0, 1], str(c.written))
    c.close()

    # ---------------- ③ 只控选中的那几台 ----------------
    print("\n[3] 只勾选一台 -> 另一台不该被动")
    m0 = FakeMonitor({VCP_MODE: (1, 11)})
    m1 = FakeMonitor({VCP_MODE: (1, 11)})
    install([m0, m1])
    c = ddc.DDCController(indices=[0])
    check("只打开 1 台", c.ensure() and list(c.monitors) == [0],
          str(list(c.monitors)))
    c.apply_mode({"vcp": 5})
    check("第 1 台被写", (VCP_MODE, 5) in m0.vcp.writes, str(m0.vcp.writes))
    check("第 2 台完全没动", m1.vcp.writes == [], str(m1.vcp.writes))
    c.close()

    # ---------------- ④ 一台失败不影响另一台 ----------------
    print("\n[4] 某台写失败 -> 记进 failed，其它台照常")
    good = FakeMonitor({VCP_MODE: (1, 11)})

    class Boom(object):
        class vcp(object):
            @staticmethod
            def get_vcp_feature(code):
                return (1, 11)

            @staticmethod
            def set_vcp_feature(code, value):
                raise RuntimeError("I2C 错误")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    install([good, Boom()])
    c = ddc.DDCController(indices=[0, 1])
    c.ensure()
    check("apply_mode 仍算成功", c.apply_mode({"vcp": 3}) is True)
    check("成功的台是 1 号", c.written == [0], str(c.written))
    check("失败的台是 2 号", c.failed == [1], str(c.failed))
    c.close()

    # ---------------- ⑤ snapshot ----------------
    print("\n[5] snapshot 能读回每台的可用通道")
    main_m = FakeMonitor({VCP_MODE: (2, 11), VCP_BRI: (70, 100),
                          VCP_CON: (50, 100)})
    sub_m = FakeMonitor({VCP_BRI: (75, 100), VCP_CON: (55, 100)})
    install([main_m, sub_m])
    c = ddc.DDCController(indices=[0, 1])
    snap = c.snapshot()
    check("主屏读到 vcp 值", snap[0].get("value") == 2, str(snap[0]))
    check("副屏没有 vcp 通道", snap[1].get("vcp") is None, str(snap[1]))
    check("副屏读到亮度", snap[1].get("brightness") == 75, str(snap[1]))
    check("副屏读到对比度", snap[1].get("contrast") == 55, str(snap[1]))
    c.close()

    # ---------------- ⑥ 每台屏各自的档位（向导记录的 monitor_vcp） ----------------
    print("\n[6] monitor_vcp：每台屏用各自的档位号，不共用 vcp")
    # 模拟向导识别出的情况：主屏 0xDC 的"阅读模式"是 5，
    # 副屏挂在 0xCC 上、同一个模式是 4。共用 vcp 必错。
    main_m = FakeMonitor({VCP_MODE: (1, 11), 0xCC: (1, 13)})
    sub_m = FakeMonitor({0xCC: (1, 13)})
    install([main_m, sub_m])
    c = ddc.DDCController(indices=[0, 1],
                          forced_vcp={1: 0xCC})
    c.ensure()
    check("副屏用 0xCC 当通道", c.vcps.get(1) == 0xCC, str(c.vcps))
    ok = c.apply_mode({"vcp": 5, "monitor_vcp": {"1": 4}})
    check("apply_mode 成功", ok is True)
    check("两台都写了", c.written == [0, 1], str(c.written))
    check("主屏写通用档位 5", main_m.vcp.caps[VCP_MODE][0] == 5,
          str(main_m.vcp.caps[VCP_MODE]))
    check("副屏写自己的档位 4", sub_m.vcp.caps[0xCC][0] == 4,
          str(sub_m.vcp.caps[0xCC]))
    c.close()

    # ---------------- ⑦ monitor_vcp 优先于 per_monitor ----------------
    print("\n[7] 同一台屏：monitor_vcp 优先于 per_monitor")
    m = FakeMonitor({VCP_MODE: (1, 11), VCP_BRI: (70, 100), VCP_CON: (50, 100)})
    install([m])
    c = ddc.DDCController(indices=[0])
    c.ensure()
    c.apply_mode({"vcp": 2,
                  "monitor_vcp": {"0": 6},
                  "per_monitor": {"0": {"brightness": 30, "contrast": 40}}})
    check("写了档位而不是亮度", m.vcp.caps[VCP_MODE][0] == 6,
          str(m.vcp.caps[VCP_MODE]))
    check("亮度没被动", m.vcp.caps[VCP_BRI][0] == 70,
          str(m.vcp.caps[VCP_BRI]))
    c.close()

    # ---------------- ⑧ 差分识别 ----------------
    print("\n[8] diff_scans：靠两次快照找出变了的码")
    a = {0x10: 75, 0xCC: 3, 0x14: 5, 0x60: 18}
    b = {0x10: 75, 0xCC: 4, 0x14: 5, 0x60: 18}
    ch = ddc.diff_scans(a, b)
    check("只找到 0xCC", [c[0] for c in ch] == [0xCC], str(ch))
    check("记下了前后值", ch[0][1] == 3 and ch[0][2] == 4, str(ch))
    check("全都没变就返回空",
          ddc.diff_scans(a, dict(a)) == [], str(ddc.diff_scans(a, dict(a))))
    check("读失败的码不算变化",
          ddc.diff_scans({0x10: None}, {0x10: 5}) == [], "None 应被跳过")

    # ---------------- ⑨ 能力串驱动候选码 ----------------
    print("\n[9] capability_codes 从能力串拿码，而不是硬编码")

    class CapMonitor(object):
        def __init__(self, cap):
            self._cap = cap

        def get_vcp_capabilities(self):
            if self._cap is None:
                raise RuntimeError("读不到")
            return self._cap

    codes = ddc.capability_codes(
        CapMonitor({"vcp": {"16": {}, "204": {}, "220": {}}}))
    check("拿到能力串里的码", codes == [16, 204, 220], str(codes))
    fallback = ddc.capability_codes(CapMonitor(None))
    check("读不到能力串时退回常见码",
          ddc.VCP_MODE in fallback and ddc.VCP_BRIGHTNESS in fallback,
          str(fallback))

    print("\n结果：OK %d / FAIL %d" % (len(OK), len(BAD)))
    for n in BAD:
        print("  失败：", n)
    return 0 if not BAD else 1


if __name__ == "__main__":
    sys.exit(main())
