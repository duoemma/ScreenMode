# -*- coding: utf-8 -*-
r"""安装前体检：这台显示器到底能不能被「屏效助手」控制。

为什么要单独做一个体检程序
--------------------------
主程序装完才知道"自己这台屏压根不支持"，是很挫的体验 —— 用户白白折腾一场。
所以体检只做**探针**，并且**不依赖主程序配置**：

  1. 这台屏有没有 DDC/CI（能不能用软件读它）
  2. 情景模式挂在哪个 VCP 码上（标准 0xDC？厂商私有码？还是根本没有）
  3. **写命令认不认** —— 读得出来不代表写得进去，写进去也不代表显示器会执行
  4. 高级颜色（HDR / 广色域）是不是开着 —— 开着的话画面补偿这条路会失效
  5. 显卡的 gamma 通道能不能用（这一条只能靠用户的眼睛确认）

第 3 条是重点：很多屏 `set_vcp_feature` 返回成功、`get_vcp_feature` 也照常
返回数字，但读回来的不是刚写进去的值 —— API 层面一点错都不报。

⚠️ 写测试只做 **0xDC 一个码**，而且写的是「读到的当前值」
（等于什么都没改），原因见下面 _write_back 的注释 ——
实测对 0x14 试写会真的改掉显示器的色彩预设，是必须避免的副作用。

结论只有三档：
  native —— 能用显示器自己的档位（最正宗，背光/色彩一起变）
  comp   —— 只能改显卡查找表模拟（色温/对比/中间调/饱和度）
  none   —— 两条路都走不通
"""
import time

from screenmode import ddc, gamma as G, hdr as HDR

# 只读探测用的码。不是随便凑的：
#   0x10 亮度、0x12 对比度 —— MCCS 里几乎必报
#   0x14 色彩预设         —— 一部分屏用它代替 0xDC
#   0xDC 显示模式         —— 标准里就是"情景模式"
#   0xCC / 0x60           —— 厂商私有、输入源，顺带看看能不能读
PROBE_CODES = [
    (ddc.VCP_BRIGHTNESS, "亮度"),
    (ddc.VCP_CONTRAST, "对比度"),
    (0x14, "色彩预设"),
    (ddc.VCP_MODE, "情景模式"),
    (0xCC, "厂商私有"),
    (0x60, "输入源"),
]

VERDICT_NATIVE = "native"
VERDICT_COMP = "comp"
VERDICT_NONE = "none"

VERDICT_TEXT = {
    VERDICT_NATIVE: "可以用（走显示器自己的档位）",
    VERDICT_COMP: "可以用（只能走画面补偿）",
    VERDICT_NONE: "基本用不了",
}


def _open_monitor(index):
    """打开第 index 台显示器的 DDC 通道。失败返回 (None, 原因)。"""
    try:
        from monitorcontrol import get_monitors
        mons = get_monitors()
    except Exception as exc:
        return None, "拿不到显示器列表：%r" % (exc,)
    if index >= len(mons):
        return None, "系统里枚举不到第 %d 台" % (index + 1)
    m = mons[index]
    try:
        m.__enter__()
    except Exception as exc:
        return None, "打不开 DDC 通道（%r）" % (exc,)
    return m, ""


def _close_monitor(m):
    try:
        m.__exit__(None, None, None)
    except Exception:
        pass


def _read_code(m, code):
    """读一个 VCP 码 -> (值, 错误)。"""
    try:
        cur, _mx = m.vcp.get_vcp_feature(code)
        return int(cur), ""
    except Exception as exc:
        return None, str(exc)


def _write_back(m, code, value):
    """把读到的值原样写回去，再读回来比对。

    ⚠️ **只给 0xDC 用**。本来这套"写回同值"想通用于所有码，实测当场翻车：
    对副屏 0x14 写「读到的 5」，读回变成 8（6500K → 9300K），画面当场变冷；
    0xCC 写 3 读回 0。也就是说**这类码的写入语义和我们读到的不一致**，
    写回去并不等于没改，会实实在在改掉用户的色彩预设。
    0xDC 是标准控件、值域就是模式枚举，写当前值才是真正的空操作。

    也正因为如此，体检对 0x14 / 0xCC 只读不写 —— 宁可少测一项，
    也不能为了多测一条通道去动别人的画面。
    """
    try:
        m.vcp.set_vcp_feature(code, value)
    except Exception as exc:
        return False, "写命令被拒绝（%s）" % exc
    time.sleep(ddc.VERIFY_SETTLE)
    for _ in range(3):
        back, err = _read_code(m, code)
        if back is not None:
            if back == value:
                return True, "写入被确认"
            return False, "写了 %s 读回 %s，写入被忽略" % (value, back)
        time.sleep(0.16)
    return False, "写完读不回来（%s）" % (err or "超时")


def _probe_one(index, mon_info, color):
    """跑一台屏的 DDC 探针（只读 + 仅 0xDC 一次空写）。"""
    row = {
        "index": index,
        "device": mon_info.get("device", ""),
        "name": "",                      # 下面用 EDID 型号补
        "size": "",
        "primary": bool(mon_info.get("primary")),
        "color": color,
        "ddc_ok": False,
        "ddc_note": "",
        "caps_len": 0,
        "reads": [],                     # [(code, 名称, 值)]
        "writes": [],                    # [(code, 名称, OK, 说明)]
        "mode_vcp": None,
        "write_ok": False,
        "verdict": VERDICT_NONE,
        "advice": "",
    }
    w, h = mon_info.get("w", 0), mon_info.get("h", 0)
    row["size"] = "%d×%d" % (w, h) if w and h else "分辨率未知"

    m, err = _open_monitor(index)
    if m is None:
        row["ddc_note"] = err
        row["advice"] = ("这台屏读不到 DDC/CI。先在显示器菜单里找「DDC/CI」"
                         "或「显示器控制」并打开；如果菜单里根本没有这一项，"
                         "那就只能用画面补偿。")
        return row

    try:
        row["ddc_ok"] = True
        cap = ""
        try:
            cap = m.vcp.get_vcp_capabilities() or ""
        except Exception:
            pass
        row["caps_len"] = len(cap or "")

        for code, label in PROBE_CODES:
            val, _e = _read_code(m, code)
            if val is not None:
                row["reads"].append((code, label, val))

        readable = {c for c, _l, _v in row["reads"]}

        # 只对 0xDC 做空写测试 —— 它是标准控件，写当前值真的什么都不改。
        # 0x14 / 0xCC 一律不测：实测写它们会直接改掉用户的色彩预设。
        if ddc.VCP_MODE in readable:
            ok, note = _write_back(m, ddc.VCP_MODE,
                                   _val_of(row, ddc.VCP_MODE))
            row["writes"].append((ddc.VCP_MODE, "情景模式", ok, note))
            if ok:
                row["mode_vcp"] = ddc.VCP_MODE
                row["write_ok"] = True
    finally:
        _close_monitor(m)

    row["verdict"], row["advice"] = _judge(row)
    return row


def _val_of(row, code):
    for c, _l, v in row["reads"]:
        if c == code:
            return v
    return None


def _label_of(code):
    for c, label in PROBE_CODES:
        if c == code:
            return label
    return "0x%02X" % code


def _judge(row):
    """根据探针结果给结论和一句人话建议。"""
    if row["mode_vcp"] is not None:
        return VERDICT_NATIVE, (
            "这台屏的情景模式走 %s，程序能直接让它自己换档 —— "
            "背光和色彩会一起变，效果最正宗。"
            % ddc.VCP_NAMES.get(row["mode_vcp"],
                                "0x%02X" % row["mode_vcp"]))
    if not row["ddc_ok"]:
        return VERDICT_COMP, (
            "读不到 DDC/CI，显示器自己的档位切不了。"
            "但显卡层的画面补偿不依赖 DDC，仍然能跟着场景变色温/对比度。")
    if row["color"].get("advanced"):
        return VERDICT_COMP, (
            "显示器没暴露可写的情景模式码，本来该用画面补偿顶上；"
            "但这台屏正处在高级颜色模式（HDR 或系统「自动管理颜色」），"
            "显卡查找表会被系统接管，补偿大概率不生效。"
            "先到 设置 → 系统 → 显示 → 高级显示 里关掉 HDR / 自动管理颜色，再测一次。")
    others = ["0x%02X %s" % (c, l) for c, l, _v in row["reads"]
              if c in (0x14, 0xCC)]
    extra = ""
    if others:
        extra = ("（它倒是能读 %s，但这类码写下去会直接改掉你的色彩预设，"
                 "本工具刻意不试写 —— 所以别指望靠它们切档。）"
                 % "、".join(others))
    return VERDICT_COMP, (
        "0xDC 读不到或写不进去，显示器自己的档位切不了。"
        "程序会改用画面补偿：色温 / 对比 / 中间调 / 饱和度都归它管，"
        "照样能跟着场景变。" + extra)


def _color_of(device, hdr_rows):
    """把 hdr.query() 的结果折成一句人话（用词与主程序保持一致）。"""
    info = None
    for m in hdr_rows:
        if m.get("device") == device:
            info = m
            break
    if not info:
        return {"mode": "未知", "advanced": False, "bpc": 0,
                "text": "查不到高级颜色状态"}
    return {
        "mode": info.get("mode") or ("SDR" if not info.get("ok") else "?"),
        "advanced": bool(info.get("advanced")),
        "bpc": info.get("bpc") or 0,
        "text": info.get("mode_text") or "查不到（按 SDR 处理）",
    }


def run(progress=None):
    """跑一遍完整体检，返回报告 dict。

    progress(stage, text) 可选，用来给界面报进度。
    """
    def say(stage, text):
        if progress:
            try:
                progress(stage, text)
            except Exception:
                pass

    say("scan", "正在枚举显示器…")
    infos = ddc.list_monitors()
    try:
        hdr_rows = HDR.query()
    except Exception:
        hdr_rows = []

    rows = []
    for i, info in enumerate(infos):
        say("ddc", "正在测第 %d 台（%d/%d）…" % (i + 1, i + 1, len(infos)))
        color = _color_of(info.get("device", ""), hdr_rows)
        row = _probe_one(info["index"], info, color)
        # 型号名：优先 EDID 友好名（27M1 / H24T09P），比「显示器 2」好认
        for hr in hdr_rows:
            if hr.get("device") == row["device"] and hr.get("friendly"):
                row["name"] = hr["friendly"]
        if not row["name"]:
            row["name"] = "显示器 %d" % (i + 1)
        rows.append(row)

    say("done", "体检完成")
    return {
        "at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "rows": rows,
        "gamma_ok": not any(r["color"].get("advanced") for r in rows),
    }


def report_text(rep):
    """把报告折成纯文本（保存成 .txt 发给别人看）。"""
    lines = ["屏效助手 · 屏幕体检报告", "时间：%s" % rep.get("at", ""), ""]
    for i, r in enumerate(rep.get("rows") or [], start=1):
        lines.append("=" * 46)
        lines.append("显示器 %d：%s  %s%s"
                     % (i, r["name"], r["size"],
                        "  （主屏）" if r["primary"] else ""))
        lines.append("设备：%s" % (r["device"] or "—"))
        lines.append("高级颜色：%s" % r["color"].get("text", ""))
        if r["ddc_ok"]:
            lines.append("DDC/CI：可用（能力串 %d 字节）" % r["caps_len"])
        else:
            lines.append("DDC/CI：不可用（%s）" % (r["ddc_note"] or "打不开"))
        if r["reads"]:
            lines.append("能读的码：" + "、".join(
                "0x%02X %s=%s" % (c, l, v) for c, l, v in r["reads"]))
        else:
            lines.append("能读的码：无")
        for code, label, ok, note in r["writes"]:
            lines.append("写测试 0x%02X %s：%s（%s）"
                         % (code, label, "通过" if ok else "失败", note))
        lines.append("结论：%s" % VERDICT_TEXT.get(r["verdict"], "?"))
        if r["advice"]:
            lines.append("说明：%s" % r["advice"])
        lines.append("")
    return "\n".join(lines)


def summary_line(rep):
    """一行总结，放在窗口顶部。"""
    rows = rep.get("rows") or []
    if not rows:
        return "一台显示器都没检测到"
    native = sum(1 for r in rows if r["verdict"] == VERDICT_NATIVE)
    comp = sum(1 for r in rows if r["verdict"] == VERDICT_COMP)
    if native == len(rows):
        return "共 %d 台，全部支持显示器自带档位，装上就能用" % len(rows)
    if native + comp == len(rows):
        return ("共 %d 台：%d 台走自带档位，%d 台走画面补偿，都能跟着场景变"
                % (len(rows), native, comp))
    return "共 %d 台，其中 %d 台可能用不了" % (len(rows), len(rows) - native - comp)


# ------------------------------------------------------------ 画面通道自测
class GammaProbe:
    """画面补偿的「看得见吗」测试。

    为什么必须让用户自己看：gamma 改的是显示器收到的查找表，
    截图画面上抓不到任何变化 —— 程序永远没法自己确认"生效了没有"。
    所以这里只负责「改成明显的样子」和「改回去」，中间那一眼交给用户。
    """

    def __init__(self, devices, store_dir=None):
        import os
        path = os.path.join(store_dir, "checkup_base.json") if store_dir else None
        self.ch = G.GammaChannel(store_path=path)
        self.devices = [d for d in (devices or []) if d]
        self.active = False

    def start(self):
        """把目标屏调成明显偏红 + 变亮，让人一眼能看出来。"""
        params = {"warm": 1.22, "contrast": 1.06, "brightness": 1.05}
        ok = []
        for d in self.devices:
            if self.ch.apply(d, params):
                ok.append(d)
        self.active = bool(ok)
        return ok

    def stop(self):
        """恢复原始查找表（写回采样到的基线，不是恒等斜坡）。"""
        ok = self.ch.restore_all()
        self.active = False
        return ok

    def close(self):
        try:
            self.ch.close()
        except Exception:
            pass
