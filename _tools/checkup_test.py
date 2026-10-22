# -*- coding: utf-8 -*-
"""屏幕体检的纯逻辑测试（不碰真显示器）。

重点验两件事：
  1. 三种结论（自带档位 / 只能用补偿 / 用不了）判定得对不对
  2. 报告文本里该有的关键信息一条都不能少 —— 用户是要拿这份报告
     去判断"要不要装主程序"的，少一行就可能得出相反结论
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from screenmode import checkup as C    # noqa: E402
# 卡片高度估算在窗口类里（纯函数，构造窗口对象不需要真的开窗）
from screenmode.ui.checkupwin import CheckupWindow   # noqa: E402

OK = []
FAIL = []


def chk(name, cond, extra=""):
    (OK if cond else FAIL).append(name)
    print("  [%s] %s%s" % ("OK" if cond else "FAIL", name,
                           ("  " + str(extra)) if extra else ""))


def row(**kw):
    base = {
        "index": 0, "device": "\\\\.\\DISPLAY9", "name": "TEST", "size": "1×1",
        "primary": False,
        "color": {"mode": "SDR", "advanced": False, "bpc": 8, "text": "SDR（8bit）"},
        "ddc_ok": True, "ddc_note": "", "caps_len": 100,
        "reads": [], "writes": [], "mode_vcp": None, "write_ok": False,
        "verdict": C.VERDICT_NONE, "advice": "",
    }
    base.update(kw)
    return base


def main():
    print("\n[A] 结论判定")
    r = row(mode_vcp=0xDC, write_ok=True)
    v, _a = C._judge(r)
    chk("0xDC 写得进去 -> 自带档位", v == C.VERDICT_NATIVE, v)

    r = row(ddc_ok=False, ddc_note="打不开")
    v, a = C._judge(r)
    chk("DDC 打不开 -> 只能补偿", v == C.VERDICT_COMP, v)
    chk("  建议里提到画面补偿", "补偿" in a)

    r = row(reads=[(0x10, "亮度", 70), (0x14, "色彩预设", 5)])
    v, a = C._judge(r)
    chk("只能读不能写 0xDC -> 补偿", v == C.VERDICT_COMP, v)
    chk("  明确说了 0x14 不给它试写", "刻意不试写" in a, a[:30])

    r = row(color={"advanced": True, "text": "高级颜色已开启"})
    v, a = C._judge(r)
    chk("高级颜色挡着 -> 提示先关 HDR/自动管理颜色",
        v == C.VERDICT_COMP and "自动管理颜色" in a, v)

    print("\n[B] 报告文本")
    rep = {"at": "2026-01-01 00:00:00", "rows": [
        row(index=0, name="主屏甲", size="2560×1440", primary=True,
            device="\\\\.\\DISPLAY5", mode_vcp=0xDC, write_ok=True,
            verdict=C.VERDICT_NATIVE, reads=[(0xDC, "情景模式", 1)],
            writes=[(0xDC, "情景模式", True, "写入被确认")],
            advice="这台屏的情景模式走 0xDC。"),
        row(index=1, name="副屏乙", size="1920×1080",
            device="\\\\.\\DISPLAY6", verdict=C.VERDICT_COMP,
            reads=[(0x10, "亮度", 75)],
            advice="程序会改用画面补偿。"),
    ]}
    t = C.report_text(rep)
    for key in ("主屏甲", "副屏乙", "2560×1440", "写入被确认",
                "可以用（走显示器自己的档位）", "可以用（只能走画面补偿）"):
        chk("报告里有 %s" % key, key in t)

    s = C.summary_line(rep)
    chk("总结提到 2 台都可用", "共 2 台" in s and "都能跟着场景变" in s, s)

    rep2 = {"at": "", "rows": [row(verdict=C.VERDICT_NONE)]}
    chk("有用不了的屏时总结会说", "用不了" in C.summary_line(rep2),
        C.summary_line(rep2))

    print("\n[C] 卡片高度估算")
    w = 932                      # 980 的窗口减去左右各 24 的内边距
    # 一行大约放得下 77 个汉字（(932-36)/11.6），所以 30 字是一行、200 字要三行
    chk("30 个汉字算一行", CheckupWindow._advice_lines("啊" * 30, w) == 1,
        CheckupWindow._advice_lines("啊" * 30, w))
    chk("200 个汉字要三行以上",
        CheckupWindow._advice_lines("啊" * 200, w) >= 3,
        CheckupWindow._advice_lines("啊" * 200, w))
    chk("空文本算 0 行", CheckupWindow._advice_lines("", w) == 0)
    chk("英文同样字符数占的行数更少",
        CheckupWindow._advice_lines("a" * 400, w)
        < CheckupWindow._advice_lines("啊" * 400, w))

    print("\n结果：OK %d / FAIL %d" % (len(OK), len(FAIL)))
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
