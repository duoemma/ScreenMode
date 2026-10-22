# -*- coding: utf-8 -*-
r"""真机端到端验证：混合通道是否真的让「每台屏都跟着变」。

会真的改显示器：主屏写 DDC 0xDC 档位、副屏写显卡查找表。
跑完会把两台都恢复原状（档位回 1、gamma 回基线）。

    python _tools/gamma_e2e.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from screenmode import apply as AP
from screenmode import config, ddc, gamma as G, hdr as HDR


def ramps(gch, devs):
    return {d: gch.read(d)[0][128] for d in devs}


def main():
    cfg = config.default_config()
    print("=== 环境 ===")
    for m in HDR.query():
        print("  %s  %-10s HDR=%s 色深=%s"
              % (m["device"], m.get("friendly") or "?",
                 "开" if m["hdr_enabled"] else "关", m["bpc"]))

    mons = ddc.list_monitors()
    for m in mons:
        print("  %d 号  %-15s %s  通道=%s"
              % (m["index"] + 1, m["device"],
                 "DDC 通" if m["controllable"] else "DDC 不通",
                 ("0x%02X" % m["mode_vcp"]) if m["mode_vcp"] else "无"))

    gch = G.GammaChannel(store_path=os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "_tools", "_gamma_base_test.json"))
    devs = [o["device"] for o in gch.outputs()]
    base = ramps(gch, devs)
    print("  基线中间调：%s" % base)

    ctl = ddc.DDCController(indices=[m["index"] for m in mons] or [0])

    for name in ("阅读模式", "电影模式", "FPS模式", "用户模式"):
        mode = config.mode_by_name(cfg, name)
        print("\n=== 切换到【%s】 ===" % name)
        print("  配置：%s" % AP.describe_channels(mode))
        res = AP.apply_mode(mode, ddc=ctl, gch=gch, monitors=mons,
                            use_gamma=True, verify=True)
        print("  摘要：%s" % res["summary"])
        print("  DDC 写成：%s  被忽略：%s  无通道：%s"
              % (res["ddc_written"], res["ddc_unverified"], res["ddc_failed"]))
        print("  Gamma 套上：%s  撤销：%s  让路：%s"
              % (res["gamma_applied"], res["gamma_restored"],
                 [d for d, _ in res["gamma_skipped"]]))
        if res["errors"]:
            print("  异常：%s" % res["errors"])
        after = ramps(gch, devs)
        for d in devs:
            mark = "变了" if after[d] != base[d] else "没变"
            print("    %s 中间调 %d -> %d  %s" % (d, base[d], after[d], mark))
        time.sleep(1.0)

    print("\n=== 收尾 ===")
    gch.restore_all()
    if ctl.monitors and ctl.vcps.get(0) is not None:
        try:
            ctl.monitors[0].vcp.set_vcp_feature(ctl.vcps[0], 1)
            print("  主屏档位已写回 1")
        except Exception as e:
            print("  主屏档位恢复失败：%r" % (e,))
    ctl.close()
    gch.close()
    time.sleep(0.3)
    gch2 = G.GammaChannel()
    back = ramps(gch2, devs)
    print("  恢复后中间调：%s（与基线一致：%s）"
          % (back, {d: back[d] == base[d] for d in devs}))
    gch2.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
