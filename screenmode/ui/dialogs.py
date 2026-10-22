# -*- coding: utf-8 -*-
"""各种模态对话框：切换确认、添加应用、从预设选择、模式编辑、新建分组。

约定：on_create() 只创建原生控件（编辑框 / 下拉框 / 列表），
所有静态文字都放进 paint_body()，由 WM_PAINT 统一绘制
（否则会被双缓冲覆盖掉，看起来像"白板"）。
"""
from screenmode import gamma as G
from screenmode import presets
from screenmode.ui import base as B
from screenmode.ui import theme as T

EDIT = (B.WS_CHILD | B.WS_VISIBLE | B.WS_TABSTOP | B.WS_BORDER
        | B.ES_AUTOHSCROLL)
NUM = B.WS_CHILD | B.WS_VISIBLE | B.WS_TABSTOP | B.WS_BORDER | B.ES_NUMBER
COMBO = B.WS_CHILD | B.WS_VISIBLE | B.WS_TABSTOP | B.CBS_DROPDOWNLIST


# ------------------------------------------------------------------ 切换确认
class SwitchDialog(B.Dialog):
    """检测到情景分组时弹出：让我选要切到哪个模式，带倒计时。"""

    header_h = 66

    def __init__(self, parent, suggested, options, timeout, context):
        super().__init__(parent, "切换显示器情景模式", 560, 300)
        self.suggested = suggested
        self.options = list(options)
        self.context = context
        self.remaining = max(1, int(timeout))
        self.combo = None
        self.topmost = True

    def on_create(self):
        w, h = self.client_rect()
        self.combo = B.create_native(self.hwnd, "ComboBox", "", COMBO,
                                     24, 128, 420, 120, cid=101,
                                     font_size=T.F_H2)
        B.set_combo_items(self.combo, self.options, self.suggested)
        self.add_button(1, "立即切换", 24, h - 56, 132, 42, kind="primary",
                        on_click=lambda b: self._accept())
        self.add_button(2, "保持不变", 168, h - 56, 132, 42,
                        kind="secondary", on_click=lambda b: self._keep())
        B.user32.SetTimer(self.hwnd, 1, 1000, None)
        B.user32.SetForegroundWindow(self.hwnd)

    def paint_body(self, hdc, w, h):
        B.text(hdc, self.context, 24, 84, w - 72, 22, color=T.TEXT_SUB,
               size=T.F_BODY)
        B.text(hdc, "请选择要切换到的模式：", 24, 108, 320, 18,
               color=T.TEXT_FAINT, size=T.F_SMALL)
        B.text(hdc, "%d 秒后自动采用当前选择（Esc 保持不变）" % self.remaining,
               24, h - 88, w - 48, 20, color=T.TEXT_FAINT, size=T.F_SMALL)

    def on_timer(self, tid):
        if tid != 1:
            return 0
        self.remaining -= 1
        if self.remaining <= 0:
            self._accept()
        else:
            self.invalidate()
        return 0

    def _accept(self):
        name = B.combo_selection(self.combo, self.options)
        self.ok(name or self.suggested)

    def _keep(self):
        self.ok(None)

    def on_enter(self):
        self._accept()
        return True

    def on_destroy(self):
        B.user32.KillTimer(self.hwnd, 1)
        super().on_destroy()


# ------------------------------------------------------------------ 运行中的程序
class PickRunningDialog(B.Dialog):
    header_h = 60

    def __init__(self, parent):
        super().__init__(parent, "从正在运行的程序中选择", 560, 460)
        self.list = None
        self.apps = []

    def on_create(self):
        w, h = self.client_rect()
        self.list = B.ListView(self.hwnd, 24, 100, w - 48, h - 100 - 76,
                               [("程序", 296), ("进程名", 204)])
        from screenmode import winapi
        self.apps = winapi.list_running_apps()
        for a in self.apps:
            self.list.add([a["name"][:40], a["exe"]], a)
        if self.apps:
            self.list.select(0)
        self.add_button(1, "取消", 24, h - 62, 110, 38,
                        on_click=lambda b: self.ok(None))
        self.add_button(2, "使用选中项", w - 146, h - 62, 122, 38,
                        kind="primary", on_click=lambda b: self._accept())

    def paint_body(self, hdc, w, h):
        B.text(hdc, "挑一个当前有窗口的程序，自动填入进程名。", 24, 74,
               w - 48, 20, color=T.TEXT_SUB, size=T.F_SMALL)
        if not self.apps:
            B.text(hdc, "没有找到带窗口的程序。", 24, 200, w - 48, 22,
                   color=T.TEXT_FAINT, size=T.F_BODY)

    def _accept(self):
        self.ok(self.list.selected())

    def on_enter(self):
        self._accept()
        return True


# ------------------------------------------------------------------ 添加/编辑应用
class AppDialog(B.Dialog):
    header_h = 60

    def __init__(self, parent, title="添加应用", name="", exe="", keyword=""):
        super().__init__(parent, title, 540, 372)
        self.v_name, self.v_exe, self.v_kw = name, exe, keyword
        self.e_name = self.e_exe = self.e_kw = None

    def on_create(self):
        w, h = self.client_rect()
        self.e_name = B.create_native(self.hwnd, "Edit", self.v_name, EDIT,
                                      24, 98, 300, 28, cid=101,
                                      font_size=T.F_BODY)
        self.e_exe = B.create_native(self.hwnd, "Edit", self.v_exe, EDIT,
                                     24, 160, 300, 28, cid=102,
                                     font_size=T.F_BODY)
        self.e_kw = B.create_native(self.hwnd, "Edit", self.v_kw, EDIT,
                                    24, 222, 300, 28, cid=103,
                                    font_size=T.F_BODY)
        self.add_button(11, "从运行中的程序选择", 336, 158, 160, 32,
                        size=T.F_SMALL, on_click=lambda b: self._pick())
        self.add_button(1, "取消", 24, h - 56, 110, 38,
                        on_click=lambda b: self.ok(None))
        self.add_button(2, "确定", w - 142, h - 56, 118, 38, kind="primary",
                        on_click=lambda b: self._accept())

    def paint_body(self, hdc, w, h):
        B.text(hdc, "应用名称（显示在列表里，随便写）", 24, 74, 340, 18,
               color=T.TEXT_SUB, size=T.F_SMALL)
        B.text(hdc, "进程名（.exe）", 24, 136, 200, 18, color=T.TEXT_SUB,
               size=T.F_SMALL)
        B.text(hdc, "或：窗口标题包含（进程名留空时生效）", 24, 198, 320, 18,
               color=T.TEXT_SUB, size=T.F_SMALL)
        B.text(hdc,
               "进程名怎么看：任务管理器 →「详细信息」→ 右键列标题勾选「映像名称」。\n"
               "填 winword.exe 这类映像名最稳；拿不到固定进程名时才用标题关键字。",
               24, 256, w - 48, 48, color=T.TEXT_FAINT, size=T.F_TINY,
               wrap=True)

    def _pick(self):
        chosen = PickRunningDialog(self.hwnd).run()
        if chosen:
            B.set_text(self.e_exe, chosen["exe"])
            if not B.get_text(self.e_name).strip():
                B.set_text(self.e_name, chosen["name"][:40])

    def _accept(self):
        name = B.get_text(self.e_name).strip()
        exe = B.get_text(self.e_exe).strip().lower()
        kw = B.get_text(self.e_kw).strip()
        if exe and "." not in exe:
            exe += ".exe"
        if not exe and not kw:
            B.message_box("请至少填写「进程名」或「窗口标题关键字」其中之一。",
                          "还差一点", 0x30)
            return
        if not name:
            name = presets.friendly_name(exe) if exe else kw
        self.ok({"name": name, "exe": exe, "title": kw})

    def on_enter(self):
        self._accept()
        return True


# ------------------------------------------------------------------ 预设选择
class PresetDialog(B.Dialog):
    header_h = 60

    def __init__(self, parent, kind, existing_exes):
        meta = presets.archetype(kind)
        super().__init__(parent, "从预设库添加 · %s" % meta["name"], 600, 500)
        self.kind = kind
        self.existing = {(e or "").lower() for e in existing_exes}
        self.list = None
        self.pool = []

    def on_create(self):
        w, h = self.client_rect()
        self.list = B.ListBox(self.hwnd, 24, 100, w - 48, h - 100 - 84,
                              multi=True)
        for a in presets.presets_for(self.kind):
            exe = (a.get("exe") or "").lower()
            if exe and exe in self.existing:
                continue
            label = a["name"] + ("（%s）" % a["exe"] if a.get("exe")
                                 else "（按标题匹配）")
            self.list.add(label, a)
            self.pool.append(a)
        self.add_button(1, "取消", 24, h - 62, 110, 38,
                        on_click=lambda b: self.ok(None))
        self.add_button(2, "添加选中项", w - 158, h - 62, 134, 38,
                        kind="primary", on_click=lambda b: self._accept())

    def paint_body(self, hdc, w, h):
        B.text(hdc, "按住 Ctrl 多选，已经在分组里的会自动跳过。", 24, 74,
               w - 48, 20, color=T.TEXT_SUB, size=T.F_SMALL)
        if not self.pool:
            B.text(hdc, "这个分类的预设都已经加进分组了。", 24, 190,
                   w - 48, 22, color=T.TEXT_FAINT, size=T.F_BODY)

    def _accept(self):
        picked = [self.pool[i] for i in self.list.selected_indices()
                  if i < len(self.pool)]
        self.ok(picked or [])

    def on_enter(self):
        self._accept()
        return True


# ------------------------------------------------------------------ 模式编辑
class ModeDialog(B.Dialog):
    """添加 / 编辑一个模式。

    一个模式可以配两条互相独立的通道：
      显示值（VCP 0xDC）—— 让显示器自己切 OSD 预设，最正宗
      画面补偿         —— 显卡查找表模拟，DDC 写不动时兜底
    两条不会同时作用于同一台屏（见 apply.py 的判定顺序），所以都留着最保险：
    主屏走档位、副屏走补偿，一次切换两台一起变。
    """

    header_h = 60

    def __init__(self, parent, app, name="", vcp=None, params=None):
        super().__init__(parent,
                         "编辑显示器模式" if name else "添加显示器模式",
                         560, 520)
        self.app = app
        self.v_name = name
        self.v_vcp = "" if vcp is None else str(vcp)
        self.v_params = G.normalize(params or {})
        self.e_name = self.e_vcp = None
        self.g_edits = {}

    def on_create(self):
        w, h = self.client_rect()
        self.e_name = B.create_native(self.hwnd, "Edit", self.v_name, EDIT,
                                      24, 98, 300, 28, cid=101,
                                      font_size=T.F_BODY)
        self.e_vcp = B.create_native(self.hwnd, "Edit", self.v_vcp, EDIT,
                                     24, 162, 120, 28, cid=102,
                                     font_size=T.F_BODY)
        self.add_button(11, "读取显示器当前值", 156, 160, 150, 32,
                        size=T.F_SMALL, on_click=lambda b: self._read())
        # 5 个补偿参数：24 + i*102，宽 92
        for i, key in enumerate(G.PARAM_KEYS):
            self.g_edits[key] = B.create_native(
                self.hwnd, "Edit", self._fmt(self.v_params[key]), EDIT,
                24 + i * 102, 280, 92, 30, cid=110 + i,
                font_size=T.F_BODY)
        self.add_button(12, "补偿参数全部重置为 1", 24, 364, 176, 32,
                        size=T.F_SMALL, kind="soft",
                        on_click=lambda b: self._reset_params())
        self.add_button(1, "取消", 24, h - 56, 110, 38,
                        on_click=lambda b: self.ok(None))
        self.add_button(2, "确定", w - 142, h - 56, 118, 38, kind="primary",
                        on_click=lambda b: self._accept())

    @staticmethod
    def _fmt(v):
        v = float(v)
        if abs(v - round(v)) < 1e-9:
            return "%d" % round(v)
        return ("%.2f" % v).rstrip("0").rstrip(".")

    def paint_body(self, hdc, w, h):
        B.text(hdc, "模式名称（和显示器 OSD 里的一致最好）", 24, 74, 400, 18,
               color=T.TEXT_SUB, size=T.F_SMALL)
        B.text(hdc, "显示值（VCP 0xDC，0-255）—— 留空表示这台屏只能走画面补偿",
               24, 138, 480, 18, color=T.TEXT_SUB, size=T.F_SMALL)

        B.hline(hdc, 24, 204, w - 24, T.DIVIDER)
        B.text(hdc, "画面补偿（显卡通道）", 24, 208, 300, 22,
               color=T.TEXT, size=T.F_H2, bold=True)
        B.text(hdc, "显示器不接受 DDC 写入时，用这组参数在显卡端模拟，"
                    "毫秒级实时生效。填 1 表示不改变。",
               24, 234, w - 48, 18, color=T.TEXT_FAINT, size=T.F_TINY)

        for i, key in enumerate(G.PARAM_KEYS):
            x = 24 + i * 102
            B.text(hdc, G.PARAM_LABELS[key], x, 258, 92, 16,
                   color=T.TEXT_SUB, size=T.F_TINY)
            B.text(hdc, G.PARAM_HINTS[key], x, 316, 96, 40,
                   color=T.TEXT_FAINT, size=T.F_TINY, wrap=True)

        B.text(hdc,
               "面板上的背光亮度、动态对比这类由显示器硬件负责，"
               "显卡通道改不了；它能改的是色温、对比、中间调、饱和度。",
               24, 400, w - 228, 40, color=T.TEXT_FAINT, size=T.F_TINY,
               wrap=True)

    def _reset_params(self):
        for key in G.PARAM_KEYS:
            B.set_text(self.g_edits[key], "1")

    def _read(self):
        value = self.app.ddc.get_mode()
        if value is None:
            B.message_box("读不到显示器的当前值。\n"
                          "这台屏可能不支持 DDC/CI —— 那就把「显示值」留空，"
                          "改用下面的「画面补偿」。", "读取失败", 0x30)
            return
        B.set_text(self.e_vcp, str(value))

    def _accept(self):
        name = B.get_text(self.e_name).strip()
        if not name:
            B.message_box("请填写模式名称。", "还差一点", 0x30)
            return
        raw = B.get_text(self.e_vcp).strip()
        if raw:
            try:
                vcp = int(raw)
            except ValueError:
                B.message_box("显示值请填数字（0-255），或者留空。",
                              "还差一点", 0x30)
                return
        else:
            vcp = None
        params = {}
        for key in G.PARAM_KEYS:
            txt = B.get_text(self.g_edits[key]).strip()
            if not txt:
                continue
            try:
                params[key] = float(txt)
            except ValueError:
                B.message_box(
                    "「%s」请填数字，例如 1.10。留空等于 1。"
                    % G.PARAM_LABELS[key], "还差一点", 0x30)
                return
        params = G.normalize(params)
        if vcp is None and G.is_neutral(params):
            B.message_box("这个模式两条通道都是空的，切过去不会有任何变化。\n\n"
                          "请至少填一个「显示值」，或者调整一下「画面补偿」。",
                          "还差一点", 0x30)
            return
        self.ok({"name": name, "vcp": vcp, "gamma": params})

    def on_enter(self):
        self._accept()
        return True


# ------------------------------------------------------------------ 新建分组
class GroupDialog(B.Dialog):
    header_h = 60

    def __init__(self, parent, mode_names):
        super().__init__(parent, "新建情景分组", 540, 380)
        self.mode_names = list(mode_names)
        self.e_name = self.cb_kind = self.cb_mode = None
        self.kinds = [k for k, _ in presets.NEW_GROUP_KINDS]
        self.labels = [v["name"] for _, v in presets.NEW_GROUP_KINDS]

    def on_create(self):
        w, h = self.client_rect()
        self.e_name = B.create_native(self.hwnd, "Edit", "自定义分组", EDIT,
                                      24, 100, 336, 28, cid=101,
                                      font_size=T.F_BODY)
        self.cb_kind = B.create_native(self.hwnd, "ComboBox", "", COMBO,
                                       24, 162, 236, 120, cid=102,
                                       font_size=T.F_BODY)
        B.set_combo_items(self.cb_kind, self.labels, self.labels[-1])
        self.cb_mode = B.create_native(self.hwnd, "ComboBox", "", COMBO,
                                       276, 162, 236, 120, cid=103,
                                       font_size=T.F_BODY)
        B.set_combo_items(self.cb_mode, self.mode_names,
                          self.mode_names[0] if self.mode_names else None)
        self.add_button(1, "取消", 24, h - 56, 110, 38,
                        on_click=lambda b: self.ok(None))
        self.add_button(2, "创建", w - 142, h - 56, 118, 38, kind="primary",
                        on_click=lambda b: self._accept())

    def paint_body(self, hdc, w, h):
        B.text(hdc, "分组名称", 24, 78, 220, 18, color=T.TEXT_SUB,
               size=T.F_SMALL)
        B.text(hdc, "分组模板（决定带哪些内置应用预设）", 24, 140, 240, 18,
               color=T.TEXT_SUB, size=T.F_SMALL)
        B.text(hdc, "默认切换到的模式", 276, 140, 240, 18, color=T.TEXT_SUB,
               size=T.F_SMALL)
        B.text(hdc, "选模板会自动带上该类的常用软件，创建完还能继续增删。",
               24, 292, w - 48, 20, color=T.TEXT_FAINT, size=T.F_TINY)

    def handle(self, msg, wp, lp):
        if msg == B.WM_COMMAND and B._hiword(wp) == 1:  # CBN_SELCHANGE
            if B._loword(wp) == 102:
                idx = int(B.user32.SendMessageW(self.cb_kind, B.CB_GETCURSEL,
                                                0, 0))
                if 0 <= idx < len(self.kinds):
                    meta = presets.archetype(self.kinds[idx])
                    B.set_text(self.e_name, meta["name"])
                    if meta["mode"] in self.mode_names:
                        B.user32.SendMessageW(
                            self.cb_mode, B.CB_SETCURSEL,
                            self.mode_names.index(meta["mode"]), 0)
            return 0
        return super().handle(msg, wp, lp)

    def _accept(self):
        name = B.get_text(self.e_name).strip()
        idx = int(B.user32.SendMessageW(self.cb_kind, B.CB_GETCURSEL, 0, 0))
        kind = self.kinds[idx] if 0 <= idx < len(self.kinds) else "custom"
        mode = B.combo_selection(self.cb_mode, self.mode_names) or (
            self.mode_names[0] if self.mode_names else "用户模式")
        if not name:
            B.message_box("请填写分组名称。", "还差一点", 0x30)
            return
        self.ok({"name": name, "kind": kind, "mode": mode})

    def on_enter(self):
        self._accept()
        return True


# ------------------------------------------------------------------ 简单确认
class ConfirmDialog(B.Dialog):
    header_h = 60

    def __init__(self, parent, title, message, ok_text="确定", danger=False,
                 height=262):
        super().__init__(parent, title, 460, height)
        self.message = message
        self.ok_text = ok_text
        self.danger = danger

    def on_create(self):
        w, h = self.client_rect()
        self.add_button(1, "取消", 24, h - 56, 106, 38,
                        on_click=lambda b: self.ok(False))
        self.add_button(2, self.ok_text, w - 138, h - 56, 114, 38,
                        kind="danger" if self.danger else "primary",
                        on_click=lambda b: self.ok(True))

    def paint_body(self, hdc, w, h):
        B.text(hdc, self.message, 24, 78, w - 48, h - 78 - 68,
               color=T.TEXT, size=T.F_BODY, wrap=True)

    def on_enter(self):
        self.ok(True)
        return True
