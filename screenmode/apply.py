# -*- coding: utf-8 -*-
r"""混合通道调度：一个模式，按每台屏的实际情况挑通道落地。

为什么要这一层
--------------
DDC/CI 和 Gamma Ramp 两条通道的「能做什么」完全不同：

  DDC   -> 显示器自己换 OSD 预设，连背光亮度、动态对比都跟着变。最正
           宗，但依赖显示器固件 + 驱动放行 I2C。实测有屏写进去石沉大海。
  Gamma -> 改显卡查找表，一定能生效，但只能改像素值（色温/对比/gamma/
           饱和），改不了背光。

所以策略是「**能写真值就写真值，写不动才降级模拟**」，每台屏单独判断，
互不影响。这一层就是把这个判断集中起来，并且产出一份**人能看懂的结果**，
直接显示到主页状态卡上 —— 用户点一下切换，能立刻知道哪台屏走了哪条
通道、哪台屏没救回来。

判定顺序（每台屏）
------------------
  ① 写显示器自己的模式预设（0xDC / 私有码）+ 读回一致 -> 完成，不再补 Gamma
  ② 只写了亮度/对比度 + 读回一致                    -> 弱模拟，**再补 Gamma**
  ③ DDC 写入但读回对不上（静默丢弃）                 -> 降级到 Gamma
  ④ DDC 不通（打不开 / 无可用 VCP 码）               -> 降级到 Gamma
  ⑤ 没有 Gamma 参数，或 HDR 开着挡住 Gamma           -> 这台屏宣告「无通道」

② 为什么要额外补 Gamma：亮度/对比度只动硬件背光和增益，颜色一点没变。
只靠它「切换情景模式」，用户看到的就是"亮度变了点，别的没差别"。
真机实测副屏 H24T09P 就是这种屏：能力串里有 0x10 / 0x12（写进去读回一致），
但没有 0xDC。所以它走得通"亮度/对比度"，却永远模拟不出暖色阅读模式 ——
必须叠加 Gamma 才算真的换了情景模式。

为什么必须读回比对
------------------
`set_vcp_feature` 成功 + `get_vcp_feature` 也返回数字，看起来一切正常，
但读到的其实是显示器自己的原值。本机副屏实测：写 0xDC=1 读回 4、
写 0xCC=4 读回 144。API 层没有任何错误码，只有比对才露馅。
这也是「主页点了没反应」最隐蔽的一个原因。
"""
from screenmode import gamma as G
from screenmode import hdr as HDR

# 结果里每个通道状态的简短标签（状态页直接显示）
STATUS_OK = "ok"
STATUS_FALLBACK = "fallback"     # 走了 Gamma 补偿
STATUS_HDR = "hdr"               # HDR 开着，Gamma 不生效
STATUS_NONE = "none"             # 没任何可用通道


def _device_map(monitors):
    """[{index, device}] -> {index: "\\\\.\\DISPLAY5"}"""
    out = {}
    for m in monitors or []:
        d = m.get("device")
        if d:
            out[int(m["index"])] = d
    return out


def _applied_devices(gch):
    """当前还套着补偿的显示器（用来清理上一个模式留下的效果）。"""
    fn = getattr(gch, "applied_devices", None)
    if not callable(fn):
        return []
    try:
        return list(fn())
    except Exception:
        return []


def apply_mode(mode, ddc=None, gch=None, monitors=None, use_gamma=True,
               verify=True, gamma_params=None, controlled=None,
               keep_others=False):
    """把一个模式落到所有显示器上。

    mode         配置里的模式字典（含 vcp / monitor_vcp / per_monitor / gamma）
    ddc          DDCController，可为 None
    gch          gamma.GammaChannel，可为 None
    monitors     app.monitors（用来把 ddc 序号映射到 \\\\.\\DISPLAYn）
    use_gamma    全局开关（配置里 gamma.enabled）
    verify       是否读回比对 DDC 写入（慢约 60ms/台，但能发现静默失败）
    gamma_params 显式指定补偿参数（默认取 mode["gamma"]）
    controlled   **受控的显示器序号集合**（None = 全部）。
                 用户在「显示器与模式」里只勾了一台，另一台就不能动 ——
                 连 Gamma 补偿也不能套。之前的写法是拿"全部屏 - DDC 写成功的屏"
                 当补偿目标，于是没勾的屏会被补上一层色温，用户看到的就是
                 「副屏切阅读模式，主屏明明没动也跟着变暖」。
    keep_others  True = **不清理受控范围之外**的屏。
                 给「跟随活跃屏」用：控制权从 A 屏转到 B 屏时，A 屏要
                 保持上一次的样子（用户明确要的），不能被当成"上个模式
                 留下的残留"给撤掉。手动取消勾选仍然要撤，那是另一码事。

    返回结果字典，字段见下方 result 初始化。
    """
    per_state = {}
    errors = []

    value = mode.get("vcp")
    per = mode.get("per_monitor") or {}
    mvcp = mode.get("monitor_vcp") or {}
    params = gamma_params
    if params is None:
        raw = mode.get("gamma")
        params = G.normalize(raw) if isinstance(raw, dict) else None
    if params is not None and G.is_neutral(params):
        params = None

    # ---------------- ① DDC 通道 ----------------
    ddc_written, ddc_unverified, ddc_failed = [], [], []
    native_idx = set()
    if ddc is not None:
        try:
            ddc.apply_mode(mode, verify=verify)
            ddc_written = list(ddc.written)
            ddc_unverified = list(ddc.unverified)
            ddc_failed = list(ddc.failed)
            # 写了显示器自己的模式预设才算「真换档」；只写了亮度/对比度的
            # 还要接着补 Gamma，否则颜色不会变。
            native_idx = {i for i in ddc_written
                          if (getattr(ddc, "native", {}) or {}).get(i)}
            for idx, label in (ddc.channels or {}).items():
                if idx in native_idx:
                    status, short = STATUS_OK, label
                elif idx in ddc_written:      # 只有亮度/对比度，颜色还没动
                    status, short = STATUS_FALLBACK, "亮/对+补偿"
                    label = "%s + 补偿" % label
                elif idx in ddc_unverified:
                    status, short = STATUS_FALLBACK, "补偿"
                else:
                    status, short = STATUS_NONE, label or "无通道"
                per_state[idx] = {"channel": label, "status": status,
                                  "short": short}
        except Exception as e:
            errors.append("DDC 通道异常：%r" % (e,))
            ddc_failed = list(getattr(ddc, "monitors", {}) or {})

    ok_idx = native_idx

    # ---------------- ② Gamma 兜底 ----------------
    gamma_applied, gamma_skipped, gamma_failed = [], [], []
    gamma_restored = []
    if gch is not None:
        devs = _device_map(monitors)
        if not devs:
            # 没拿到映射就按枚举顺序补（EnumDisplayDevices 的第一块通常是主屏）
            try:
                outs = gch.outputs()
            except Exception:
                outs = []
            devs = {i: o["device"] for i, o in enumerate(outs)}

        # 这次该套补偿的屏：受控范围内、DDC 没写成自家档位的全部。
        # **先按 controlled 收窄**，再排除 DDC 已经写成功的 ——
        # 顺序反了就等于「没勾的屏照样被补偿」。
        scope = set(devs)
        if controlled is not None:
            scope = {i for i in scope if i in set(controlled)}
        targets = set()
        if use_gamma and params:
            targets = {devs[i] for i in sorted(scope - ok_idx) if devs.get(i)}

        # 先把「上次套过、这次不该套」的撤掉。
        # 不撤的话会出两个坑：
        #   ① 切到没有补偿参数的模式（比如用户模式），画面停在上一个模式的色调上，
        #      用户会以为"切不回去"；
        #   ② 原来 DDC 不通靠补偿顶着，后来 DDC 通了，补偿还叠在上面。
        rev_idx = {d: i for i, d in devs.items()}
        # keep_others 时只清理"本次受控范围内、但这次用不上"的；
        # 范围外的是上一次控制过的屏，要原样留着。
        keep_devs = None
        if keep_others:
            keep_devs = {devs[i] for i in scope if devs.get(i)}
        for dev in _applied_devices(gch):
            if dev in targets:
                continue
            if keep_devs is not None and dev not in keep_devs:
                continue
            try:
                if gch.restore(dev):
                    gamma_restored.append(dev)
                    # 撤掉了就得在结果里说一声"保持原样"，
                    # 否则切回用户模式时摘要还写着「2号 无通道」——
                    # 画面明明已经恢复原始了，看着像没成功。
                    idx = rev_idx.get(dev)
                    if idx is not None:
                        ps = per_state.setdefault(idx, {})
                        if ps.get("status") in (None, STATUS_NONE):
                            ps.update({"channel": "保持原样",
                                       "status": STATUS_OK,
                                       "short": "保持原样"})
            except Exception as e:
                errors.append("%s 撤销补偿失败：%r" % (dev, e))

        if targets:
            hdr_on = set()
            try:
                hdr_on = HDR.hdr_devices()
            except Exception as e:
                errors.append("查 HDR 状态失败：%r" % (e,))

            rev = {d: i for i, d in devs.items()}
            for dev in sorted(targets):
                idx = rev.get(dev)
                if dev in hdr_on:
                    gamma_skipped.append((dev, "HDR 已开启"))
                    if idx is not None:
                        per_state.setdefault(idx, {})
                        per_state[idx].update({"channel": "补偿",
                                               "status": STATUS_HDR,
                                               "short": "HDR 阻止"})
                    continue
                if gch.apply(dev, params):
                    gamma_applied.append(dev)
                    if idx is not None:
                        ps = per_state.setdefault(idx, {})
                        if ps.get("status") in (None, STATUS_NONE):
                            # DDC 一点没写进去：通道就是纯补偿
                            ps["short"] = "补偿"
                            ps["channel"] = "补偿"
                        else:
                            # 之前只写过亮度/对比度，保留「亮/对+补偿」
                            ps.setdefault("short", "补偿")
                            ps.setdefault("channel", "补偿")
                        ps["status"] = STATUS_FALLBACK
                else:
                    gamma_failed.append(dev)
                    if idx is not None:
                        per_state.setdefault(idx, {})
                        per_state[idx].update({"channel": "补偿失败",
                                               "status": STATUS_NONE,
                                               "short": "补偿失败"})
                    errors.append(gch.last_error or ("%s 写入 gamma 失败" % dev))

    # ---------------- ③ 汇总 ----------------
    # 撤销也算"达成了目标状态"：切到没有补偿参数的模式（用户模式）时，
    # 副屏本来就该回到原样。只把写入算成功的话，这种情况会报"切换失败"，
    # 而屏幕上明明已经恢复成原始画面了 —— 用户会以为程序在瞎报错。
    total = len(ok_idx) + len(gamma_applied) + len(gamma_restored)
    result = {
        "ok": bool(total),
        "mode": mode.get("name", ""),
        "per_state": per_state,
        "ddc_written": ddc_written,
        "ddc_unverified": ddc_unverified,
        "ddc_failed": ddc_failed,
        "gamma_applied": gamma_applied,
        "gamma_restored": gamma_restored,
        "gamma_skipped": gamma_skipped,
        "gamma_failed": gamma_failed,
        "hdr_on": sorted({d for d, _ in gamma_skipped}),
        "errors": errors,
        "summary": "",
    }
    result["summary"] = summarize(result, len(monitors or []))
    return result


def summarize(result, monitor_count=0):
    """一行摘要，给状态卡 / 日志用。

    例：`1号 档位 · 2号 补偿`；`1号 档位 · 2号 HDR 阻止`
    """
    st = result.get("per_state") or {}
    if not st:
        return "没有可控制的显示器"
    parts = []
    for idx in sorted(st):
        info = st[idx]
        tag = info.get("short") or info.get("channel") or {
            STATUS_OK: "档位",
            STATUS_FALLBACK: "补偿",
            STATUS_HDR: "HDR 阻止",
            STATUS_NONE: "无通道",
        }.get(info.get("status"), "?")
        parts.append("%d号 %s" % (idx + 1, tag))
    if monitor_count and len(st) < monitor_count:
        parts.append("另 %d 台未参与" % (monitor_count - len(st)))
    return " · ".join(parts)


def needs_gamma_notice(result):
    """要不要提醒用户「HDR 开着，画面补偿不生效」。"""
    return bool(result.get("gamma_skipped"))


def describe_channels(mode):
    """这个模式配置了哪些通道 -> 一句话。"""
    bits = []
    if mode.get("vcp") is not None:
        bits.append("档位 %s" % mode["vcp"])
    if mode.get("monitor_vcp"):
        bits.append("私有码 %d 台" % len(mode["monitor_vcp"]))
    if mode.get("per_monitor"):
        bits.append("亮度/对比度 %d 台" % len(mode["per_monitor"]))
    p = G.normalize(mode.get("gamma") or {})
    if not G.is_neutral(p):
        bits.append("画面补偿 %s" % G.describe(p))
    return " · ".join(bits) or "未配置任何通道"
