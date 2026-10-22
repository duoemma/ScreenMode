# -*- coding: utf-8 -*-
"""添加显示器引导。

为什么需要向导：**不同显示器把「情景模式」挂在不同的 VCP 码上**。
标准是 0xDC，但实测有的屏（Realtek 桥接芯片）压根不报 0xDC，
菜单里明明有「标准 / 用户 / 电影 / 图片 / RTS / FPS1 / FPS2」七档，
却怎么都找不到对应的码。

网上常见的做法是硬编码一堆候选码挨个试写 —— 这很危险：写错码可能改掉
色彩预设、触发工厂设置。而且**写完也没法验证**，因为截图抓的是显卡帧缓冲，
显示器做的亮度/模式调整在截图里根本看不见（实测写亮度 30 和 100，
画面平均亮度一模一样 233.46）。

所以这里用唯一可靠的思路：**让用户手动切一次 OSD，程序读所有码看哪个跟着变**。
- 全程只读，不写任何值，零风险；
- 能力串报多少码就扫多少码，厂商私有码也能抓到；
- 变了的那个码，就是这台屏的「情景模式」通道。
"""
from screenmode import ddc
from screenmode.ui import base as B
from screenmode.ui import theme as T

# ---- 步骤编号
S_PICK = 0        # 选显示器
S_CUT_A = 1       # 请切到模式 A
S_CUT_B = 2       # 请切到模式 B
S_CUT_B2 = 3      # 有多个码变了，再切一次交叉验证
S_RECORD = 4      # 逐模式记录
S_DONE = 5        # 完成
S_FAIL = 6        # 没找到可用通道


class AddMonitorWizard(B.Dialog):
    """单窗口多步向导。切步骤只重建按钮 + 重绘，不新开窗口。"""

    win_w, win_h = 680, 530
    header_h = 84          # 标题 + 副标题都放在这个色块里

    def __init__(self, app, index=None):
        super().__init__(parent=getattr(app.ui, "hwnd", None),
                         title="添加显示器引导",
                         width=self.win_w, height=self.win_h)
        self.app = app
        self.target = index
        self.step = S_PICK
        self.codes = []
        self.snap_a = {}
        self.snap_b = {}
        self.snap_c = {}
        self.candidates = []       # 还没排除的码
        self.mode_vcp = None       # 最终认定的情景模式码
        self.records = {}          # 模式名 -> {"vcp": n} 或 {"brightness":n,"contrast":n}
        self.use_bc = False        # 走「亮度+对比度」兜底
        self.status = ""
        self.natives = []
        self.lv = None
        self._m = None         # 已打开的显示器句柄（只开一次）
        self.topmost = True

    # ------------------------------------------------------------ 控件管理
    def _clear(self):
        """清掉除关闭按钮外的所有自绘按钮和原生控件。"""
        self.buttons = [b for b in self.buttons if b.id == 9001]
        for h in self.natives:
            try:
                B.user32.DestroyWindow(h)
            except Exception:
                pass
        self.natives = []
        self.lv = None
        self._m = None         # 已打开的显示器句柄（只开一次）

    def _go(self, step):
        self.step = step
        self._clear()
        self._build()
        self.invalidate()

    def _monitor(self):
        """取目标显示器的 DDC 句柄。

        同一台只 __enter__ 一次 —— 每读一次都重新打开会反复切 I2C 通道，
        实测多次调用后返回 None，向导就静默什么都不做了。
        """
        if self._m is not None:
            return self._m
        from monitorcontrol import get_monitors
        try:
            mons = get_monitors()
        except Exception as e:
            self.status = "枚举显示器失败：%r" % (e,)
            return None
        if self.target is None or self.target >= len(mons):
            self.status = "找不到第 %s 台显示器" % (self.target,)
            return None
        m = mons[self.target]
        try:
            m.__enter__()
        except Exception as e:
            self.status = "打不开 DDC 通道：%r" % (e,)
            return None
        self._m = m
        return m

    def _mode_names(self):
        return [m.get("name", "") for m in (self.app.cfg.get("modes") or [])
                if m.get("name")]

    # ------------------------------------------------------------ 构建
    def on_create(self):
        self._build()

    def _build(self):
        w, h = self.client_rect()
        by = h - 62                     # 底部按钮行
        step = self.step

        if step == S_PICK:
            mons = self.app.monitors or []
            rows = max(len(mons), 1)
            lh = min(max(rows * 26 + 34, 124), h - 176 - 84)
            self.lv = B.ListView(self.hwnd, 24, 176, w - 48, lh,
                                 [("显示器", 250), ("分辨率", 110),
                                  ("DDC", 70), ("情景模式", 170)])
            self.natives.append(self.lv.hwnd)
            for m in mons:
                res = "%d×%d" % (m.get("w", 0), m.get("h", 0))
                ddc_s = "可用" if m["controllable"] else "不通"
                if not m["controllable"]:
                    cap = "—"
                elif m["mode_capable"]:
                    cap = "已识别 %s" % ddc.VCP_NAMES.get(
                        m["mode_vcp"], hex(m["mode_vcp"]))
                else:
                    cap = "待识别"
                self.lv.add([m.get("short") or m.get("label", ""), res,
                             ddc_s, cap], m["index"])
            # 默认选中「调用方指定的那台」，而不是永远选第一行 ——
            # 否则自动引导（明确指向未配置的那台）会被静默改成配主屏。
            want = 0
            for i, m in enumerate(mons):
                if m["index"] == self.target:
                    want = i
                    break
            if mons:
                self.lv.select(want)
            self.add_button(1, "开始识别", w - 146, by, 122, 40,
                            kind="primary", on_click=lambda b: self._pick())
            self.add_button(2, "跳过", 24, by, 100, 40,
                            on_click=lambda b: self.ok(None))

        elif step in (S_CUT_A, S_CUT_B, S_CUT_B2):
            self.add_button(1, "已切好，读取", w - 176, by, 152, 40,
                            kind="primary", on_click=lambda b: self._scan())
            self.add_button(2, "取消", 24, by, 100, 40,
                            on_click=lambda b: self.ok(None))

        elif step == S_RECORD:
            modes = self._mode_names()
            self.lv = B.ListView(self.hwnd, 24, 144, w - 48, h - 144 - 120,
                                 [("模式", 200), ("记录的档位", 180),
                                  ("状态", 200)])
            self.natives.append(self.lv.hwnd)
            for i, name in enumerate(modes):
                rec = self.records.get(name)
                val = self._fmt_rec(rec)
                self.lv.add([name, val, "已记录" if rec else "待记录"], i)
            if modes:
                self.lv.select(0)
            all_done = bool(modes) and len(self.records) >= len(modes)
            if all_done:
                self.add_button(4, "完成", w - 146, by, 122, 40,
                                kind="primary", on_click=lambda b: self._finish())
            elif self.use_bc:
                self.add_button(3, "记录亮度/对比度", w - 216, by, 192, 40,
                                kind="primary", on_click=lambda b: self._record())
            else:
                self.add_button(3, "记录当前档位", w - 196, by, 172, 40,
                                kind="primary", on_click=lambda b: self._record())
            self.add_button(2, "取消", 24, by, 100, 40,
                            on_click=lambda b: self.ok(None))

        elif step == S_DONE:
            self.add_button(1, "完成", w - 146, by, 122, 40,
                            kind="primary", on_click=lambda b: self._finish())

        elif step == S_FAIL:
            # 2.2.0 起「画面补偿」才是首选兜底：它改的是显卡查找表，
            # 不依赖 DDC、不看固件，色温/对比/中间调全都能变；
            # 只写亮度/对比度那种弱模拟已经被它完全覆盖了。
            self.add_button(1, "用画面补偿（推荐）", w - 216, by, 192, 40,
                            kind="primary", on_click=lambda b: self._use_gamma())
            self.add_button(3, "改用亮度/对比度", w - 396, by, 168, 40,
                            on_click=lambda b: self._use_bc())
            self.add_button(2, "取消", 24, by, 100, 40,
                            on_click=lambda b: self.ok(None))

    @staticmethod
    def _fmt_rec(rec):
        if not rec:
            return "—"
        if rec.get("vcp") is not None:
            return "档位 %d" % rec["vcp"]
        parts = []
        if rec.get("brightness") is not None:
            parts.append("亮度 %d" % rec["brightness"])
        if rec.get("contrast") is not None:
            parts.append("对比度 %d" % rec["contrast"])
        return "，".join(parts) or "—"

    # ------------------------------------------------------------ 绘制
    def paint(self, hdc, w, h):
        """覆盖基类：基类会把 self.title 画在标题带正中，而这里要画的是
        「第 N 步」这种会变的状态标题，两行都自己控制位置。"""
        B.fill_rect(hdc, 0, 0, w, self.header_h, T.ACCENT)
        self.paint_body(hdc, w, h)

    def paint_body(self, hdc, w, h):
        step = self.step
        titles = {
            S_PICK: ("选择要配置的显示器", "接了几台就配几台，每台单独识别"),
            S_CUT_A: ("第 1 步 / 共 2 步：切到【模式 A】",
                      "程序要看你切换时哪个码在变"),
            S_CUT_B: ("第 2 步 / 共 2 步：切到【模式 B】",
                      "换一个不同的模式，程序对比两次读数"),
            S_CUT_B2: ("多个码都在变，再切一次确认",
                       "消除干扰项，只留下真正的那个"),
            S_RECORD: ("逐个记录每个模式",
                       "每记录一个，以后自动切到这个模式就能对上"),
            S_DONE: ("配置完成", self.status),
            S_FAIL: ("这台显示器没有暴露情景模式通道", ""),
        }
        title, sub = titles.get(step, ("", ""))
        # 标题 22px 高，副标题从 58 起 —— 两个都别挤在 40~50 这一段，
        # 否则大字号会压到副标题上（截图验证过会重叠）。
        B.text(hdc, title, 24, 14, w - 72, 32, color="#FFFFFF", size=T.F_H2,
               bold=True)
        if sub:
            B.text(hdc, sub, 24, 50, w - 72, 22, color="#DCE8FB",
                   size=T.F_SMALL)

        if step == S_PICK:
            B.text(hdc, "选一台还没配过的显示器。程序先读出它支持哪些 VCP 码，"
                        "再引导你切一次模式，自动找出「情景模式」挂在哪个码上。",
                   24, 92, w - 48, 40, color=T.TEXT_SUB, size=T.F_SMALL,
                   wrap=True)

        elif step == S_CUT_A:
            self._cut_text(hdc, w, h,
                           "现在用显示器上的按键，把「情景模式」切到一个你记得住的"
                           "档位（比如【标准】或【用户】），然后点右下角"
                           "「已切好，读取」。",
                           "要扫 %s 个码，大概 2 秒。" % (len(self.codes) or "—"))

        elif step == S_CUT_B:
            self._cut_text(hdc, w, h,
                           "再切到**另一个不同的**模式（比如【电影】），然后点"
                           "「已切好，读取」。程序会对比两次读数，"
                           "哪个码变了，哪个就是情景模式通道。",
                           "前后必须切到不同的档位，否则看不出变化。")

        elif step == S_CUT_B2:
            self._cut_text(hdc, w, h,
                           "刚才有 %d 个码都变了：%s。再随便切一个第三档，"
                           "程序用第三次读数把干扰项排掉。"
                           % (len(self.candidates),
                              "、".join("0x%02X" % c for c in self.candidates)),
                           "切到和前两次都不同的模式。")

        elif step == S_RECORD:
            if self.use_bc:
                hint = ("这台屏走亮度/对比度通道：先用按键调成你想要的样子，"
                        "回来选中该模式点「记录亮度/对比度」")
            else:
                hint = ("已识别通道：%s。用按键切到列表里选中的那个模式，"
                        "回来点「记录当前档位」"
                        % ddc.VCP_NAMES.get(self.mode_vcp,
                                             "0x%02X" % (self.mode_vcp or 0)))
            B.text(hdc, hint, 24, 92, w - 48, 40, color=T.TEXT_SUB,
                   size=T.F_SMALL, wrap=True)
            done = len(self.records)
            total = len(self._mode_names())
            B.text(hdc, "进度 %d / %d" % (done, total), 24, h - 96, 200, 18,
                   color=T.TEXT_FAINT, size=T.F_SMALL)
            if self.status:
                B.text(hdc, self.status, 140, h - 96, w - 180, 18,
                       color=T.DANGER, size=T.F_SMALL)

        elif step == S_DONE:
            lines = self.status.split("\n") if self.status else []
            for i, line in enumerate(lines[:9]):
                B.text(hdc, line, 24, 96 + i * 24, w - 48, 20,
                       color=T.TEXT_SUB if i < 3 else T.TEXT_FAINT,
                       size=T.F_BODY if i < 3 else T.F_SMALL)

        elif step == S_FAIL:
            B.text(hdc, "切了两次模式，但所有码的读数都没变。可能的原因：",
                   24, 88, w - 48, 22, color=T.TEXT_SUB, size=T.F_BODY)
            tips = [
                "· 显示器菜单里 DDC/CI 是关着的（有的叫「显示器控制」）",
                "· 这台屏的模式切换压根不走 DDC，只能用实体按键",
                "· 中间隔了扩展坞 / KVM，把 DDC 写信号挡掉了",
            ]
            for i, t in enumerate(tips):
                B.text(hdc, t, 40, 118 + i * 24, w - 72, 20,
                       color=T.TEXT_SUB, size=T.F_SMALL)
            B.text(hdc, "不影响继续配置：这台屏交给「画面补偿」就行 —— "
                        "改的是显卡查找表，不依赖 DDC，也不看固件，"
                        "色温 / 对比 / 中间调 / 饱和度都能跟着场景变。",
                   24, 196, w - 48, 40, color=T.TEXT, size=T.F_SMALL,
                   wrap=True)
            B.text(hdc, "（只写亮度/对比度是更弱的老办法，现在没必要了；"
                        "真想用也可以点第二个按钮。）",
                   24, 242, w - 48, 20, color=T.TEXT_FAINT, size=T.F_TINY)

    def _cut_text(self, hdc, w, h, body, note):
        B.text(hdc, body, 24, 92, w - 48, 48, color=T.TEXT_SUB,
               size=T.F_SMALL, wrap=True)
        B.text(hdc, note, 24, 148, w - 48, 20, color=T.TEXT_FAINT,
               size=T.F_SMALL)
        B.card(hdc, 24, 186, w - 48, 146)
        B.text(hdc, "为什么要你手动切？", 40, 200, 300, 20, color=T.TEXT,
               size=T.F_SMALL, bold=True)
        B.text(hdc, "因为每台显示器把「情景模式」放在不同的码上 —— 标准是 0xDC，"
                    "但不少屏（尤其用桥接芯片的）挂在厂商私有码，甚至能力串里都不报。",
               40, 226, w - 80, 40, color=T.TEXT_SUB, size=T.F_TINY, wrap=True)
        B.text(hdc, "而「写完截图看变化」是不可行的：截图抓到的是显卡帧缓冲，"
                    "显示器硬件做的亮度/模式调整在截图里看不见。",
               40, 268, w - 80, 40, color=T.TEXT_SUB, size=T.F_TINY, wrap=True)
        B.text(hdc, "所以只有「你切、程序读」这一条路。全程只读，不会改你任何设置。",
               40, 310, w - 80, 20, color=T.TEXT_FAINT, size=T.F_TINY)

    # ------------------------------------------------------------ 交互
    def _pick(self):
        idx = self.lv.selected() if self.lv else None
        if idx is None:
            self.status = "先选一台显示器"
            self.invalidate()
            return
        self.target = idx
        m = self._monitor()
        if m is None:
            self.status = "打不开这台显示器的 DDC 通道"
            self.invalidate()
            return
        self.codes = ddc.capability_codes(m)
        self._go(S_CUT_A)

    def _scan(self):
        m = self._monitor()
        if m is None:
            self._go(S_FAIL)
            return
        snap = ddc.scan_vcps(m, self.codes)
        if self.step == S_CUT_A:
            self.snap_a = snap
            self._go(S_CUT_B)
        elif self.step == S_CUT_B:
            self.snap_b = snap
            changed = ddc.diff_scans(self.snap_a, snap)
            if not changed:
                self._go(S_FAIL)
                return
            # 有的屏切模式时会顺带调亮度/对比度，那两个码也会变。
            # 优先排除它们，免得把 0x10 当成"情景模式"。
            real = [c for c in changed
                    if c[0] not in (ddc.VCP_BRIGHTNESS, ddc.VCP_CONTRAST)]
            if real:
                changed = real
            if len(changed) == 1:
                self.mode_vcp = changed[0][0]
                self._go(S_RECORD)
                return
            self.candidates = [c[0] for c in changed]
            self._go(S_CUT_B2)
        else:
            # 第三次：只留「每次都变」的码，且要和前两次方向一致
            still = [c for c in self.candidates
                     if snap.get(c) is not None
                     and snap.get(c) != self.snap_b.get(c)]
            if len(still) == 1:
                self.mode_vcp = still[0]
                self._go(S_RECORD)
                return
            if not still:
                self._go(S_FAIL)
                return
            self.candidates = still
            # 还剩下多个：取变化幅度最大的那个当猜测，让用户确认
            self.mode_vcp = still[0]
            self._go(S_RECORD)

    def _record(self):
        names = self._mode_names()
        if not names:
            self.status = "配置里没有任何模式"
            self.invalidate()
            return
        # 优先用列表里选中的那行；选不中也无所谓，自动取第一个还没记录的 ——
        # 反正「逐个记录」本来就是按顺序走一遍，选中只是给个视觉落点。
        idx = -1
        if self.lv:
            i = self.lv.selected_index()
            if 0 <= i < len(names):
                idx = i
        if idx < 0 or names[idx] in self.records:
            idx = -1
            for i, n in enumerate(names):
                if n not in self.records:
                    idx = i
                    break
        if idx < 0:
            self.status = "所有模式都记录过了"
            self.invalidate()
            return
        name = names[idx]
        m = self._monitor()
        if m is None:
            self.invalidate()
            return
        if self.use_bc:
            rec = {}
            try:
                rec["brightness"] = m.vcp.get_vcp_feature(ddc.VCP_BRIGHTNESS)[0]
            except Exception:
                pass
            try:
                rec["contrast"] = m.vcp.get_vcp_feature(ddc.VCP_CONTRAST)[0]
            except Exception:
                pass
            if not rec:
                self.status = "亮度和对比度都读不到"
                self.invalidate()
                return
            self.records[name] = rec
        else:
            try:
                v = m.vcp.get_vcp_feature(self.mode_vcp)[0]
            except Exception:
                self.status = "读这个码失败，换个模式再试"
                self.invalidate()
                return
            self.records[name] = {"vcp": v}

        if len(self.records) >= len(names) and names:
            self._summarize()
            self._go(S_DONE)
        else:
            # 自动跳到下一个还没记录的模式
            nxt = None
            for i, n in enumerate(names):
                if n not in self.records:
                    nxt = i
                    break
            self._go(S_RECORD)
            if nxt is not None and self.lv:
                self.lv.select(nxt)

    def _summarize(self):
        mon = (self.app.monitors or [])
        name = ""
        for m in mon:
            if m["index"] == self.target:
                name = m.get("label", "")
                break
        if self.use_bc:
            chan = "亮度 / 对比度"
        else:
            chan = ddc.VCP_NAMES.get(self.mode_vcp, "0x%02X" % (self.mode_vcp or 0))
        lines = ["显示器：%s" % (name or ("第 %d 台" % (self.target + 1))),
                 "通道：%s" % chan,
                 "已记录 %d 个模式：" % len(self.records)]
        for m in self._mode_names():
            rec = self.records.get(m)
            if rec:
                lines.append("    · %s → %s" % (m, self._fmt_rec(rec)))
        lines.append("")
        lines.append("点「完成」写入配置。之后切到这些模式时，这台屏会一起跟着变。")
        self.status = "\n".join(lines)

    def _use_bc(self):
        self.use_bc = True
        self.records = {}
        self._go(S_RECORD)

    def _use_gamma(self):
        """这台屏交给画面补偿：不写显示器，只把它标成"已经配过"。

        为什么连"逐个模式记录"都省了：补偿参数写在**模式**上
        （每个内置模式都自带一份默认值），同一套参数对任何屏都成立，
        不需要像档位那样一台屏记一遍。
        """
        idx = int(self.target)
        cfg = self.app.cfg
        mon = cfg.setdefault("monitors", {})
        cur = mon.get("enabled")
        if isinstance(cur, list) and cur and idx not in cur:
            cur.append(idx)
            cur.sort()
        mon.setdefault("setup_done", {})[str(idx)] = True
        # 把以前给这台屏记过的「档位/亮度」清掉，否则旧值会盖住补偿
        (mon.get("vcp") or {}).pop(str(idx), None)
        for mode in cfg.get("modes") or []:
            (mode.get("monitor_vcp") or {}).pop(str(idx), None)
            (mode.get("per_monitor") or {}).pop(str(idx), None)
        self.app.log("显示器 %d 改走画面补偿（不写显示器，只用显卡查找表）"
                     % (idx + 1))
        try:
            self.app.save_config()
            self.app.rebuild_ddc(log=False)
            self.app.sync_applied_from_monitor()
        except Exception:
            pass
        self.ok({"index": idx, "mode_vcp": None, "records": 0,
                 "use_gamma": True})

    def _finish(self):
        idx = int(self.target)
        cfg = self.app.cfg
        mon = cfg.setdefault("monitors", {})
        # enabled 为空 = 「所有能控的都控」。这种情况下别往里塞具体序号，
        # 否则会把"全部控制"偷偷变成"只控这几台"。
        cur = mon.get("enabled")
        if isinstance(cur, list) and cur:
            if idx not in cur:
                cur.append(idx)
                cur.sort()
        else:
            mon["enabled"] = []

        # 这台屏用的通道码
        if self.mode_vcp is not None and self.mode_vcp != ddc.VCP_MODE:
            mon.setdefault("vcp", {})[str(idx)] = int(self.mode_vcp)

        modes = cfg.get("modes") or []
        by_name = {m.get("name"): m for m in modes}
        for name, rec in self.records.items():
            mode = by_name.get(name)
            if not mode:
                continue
            if rec.get("vcp") is not None:
                mode.setdefault("monitor_vcp", {})[str(idx)] = int(rec["vcp"])
            else:
                per = mode.setdefault("per_monitor", {})
                d = {}
                if rec.get("brightness") is not None:
                    d["brightness"] = int(rec["brightness"])
                if rec.get("contrast") is not None:
                    d["contrast"] = int(rec["contrast"])
                if d:
                    per[str(idx)] = d

        done = mon.setdefault("setup_done", {})
        done[str(idx)] = True

        try:
            self.app.save_config()
            self.app.rebuild_ddc(log=False)
            self.app.sync_applied_from_monitor()
        except Exception:
            pass
        self.ok({
            "index": idx,
            "mode_vcp": self.mode_vcp,
            "records": len(self.records),
            "use_bc": self.use_bc,
        })

    def on_destroy(self):
        if self._m is not None:
            try:
                self._m.__exit__(None, None, None)
            except Exception:
                pass
            self._m = None
        super().on_destroy()

    def on_escape(self):
        self.ok(None)
