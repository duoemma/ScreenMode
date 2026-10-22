# -*- coding: utf-8 -*-
"""主窗口：左侧导航 + 四个页面（运行状态 / 场景分组 / 显示器与模式 / 高级设置）。"""
import ctypes
import time

from screenmode import APP_NAME, VERSION, config, ddc, presets
from screenmode import gamma as G
from screenmode.ui import base as B
from screenmode.ui import dialogs as D
from screenmode.ui import theme as T

WM_APP = 0x8000
WM_APP_DIALOG = WM_APP + 1     # 轮询线程 -> 主线程：弹切换确认窗
WM_APP_TRAY = WM_APP + 3       # 托盘 -> 主线程：菜单动作

NAV = [
    ("运行状态", "实时监控前台程序，按分组自动切换显示器情景模式"),
    ("场景分组", "把常用软件归类，只有列表里的程序才会触发切换"),
    ("显示器与模式", "自动识别显示器，维护 OSD 情景模式与显示值"),
    ("高级设置", "空闲节能、回退策略、弹窗确认与开机自启"),
]


# ====================================================================== 页面基类
class Page(B.Win):
    bg = T.PAGE_BG
    index = 0

    def __init__(self, app, main):
        super().__init__()
        self.app = app
        self.main = main
        self.toast = ""
        self.toast_at = 0.0

    # ---------------- 创建 ----------------
    def create_page(self):
        x, y, w, h = self.main.page_rect()
        self.create(NAV[self.index][0], x, y, w, h, parent=self.main.hwnd,
                    style=B.WS_CHILD | B.WS_CLIPSIBLINGS | B.WS_CLIPCHILDREN,
                    exstyle=0)
        if not self.hwnd:
            return
        self.build_footer()

    def content(self):
        w, h = self.client_rect()
        return T.PAGE_PAD, T.HEADER_H, w - 2 * T.PAGE_PAD, \
            h - T.HEADER_H - T.FOOTER_H

    def build_footer(self):
        w, h = self.client_rect()
        self.add_button("save", "保存设置", w - T.PAGE_PAD - 132,
                        h - T.FOOTER_H + 12, 132, 38, kind="primary",
                        on_click=self._save_clicked)

    def _save_clicked(self, btn):
        try:
            self.collect()
        except Exception as exc:
            self.app.log("保存时出错：%r" % (exc,))
        self.app.save_config()
        self.app.reset_ask_state()
        self.app.refresh_menu()
        self.set_toast("已保存 %s" % time.strftime("%H:%M:%S"))

    def collect(self):
        pass

    def set_toast(self, msg):
        self.toast = msg
        self.toast_at = time.time()
        self.invalidate()

    # ---------------- 绘制 ----------------
    def paint_header(self, hdc, w, h):
        title, sub = NAV[self.index]
        B.text(hdc, title, T.PAGE_PAD, 20, w - 2 * T.PAGE_PAD, 32,
               color=T.TEXT, size=T.F_H1, bold=True)
        B.text(hdc, sub, T.PAGE_PAD, 54, w - 2 * T.PAGE_PAD, 20,
               color=T.TEXT_SUB, size=T.F_SMALL)

    def paint_footer(self, hdc, w, h):
        B.hline(hdc, T.PAGE_PAD, h - T.FOOTER_H + 6, w - T.PAGE_PAD,
                T.DIVIDER)
        if self.toast and time.time() - self.toast_at < 4:
            msg, color = self.toast, T.SUCCESS
        else:
            msg, color = "配置保存在程序目录的 config.json", T.TEXT_FAINT
        B.text(hdc, msg, T.PAGE_PAD, h - T.FOOTER_H + 16,
               w - 2 * T.PAGE_PAD - 150, 36, color=color, size=T.F_SMALL)

    def paint(self, hdc, w, h):
        self.paint_header(hdc, w, h)
        self.paint_body(hdc, w, h)
        self.paint_footer(hdc, w, h)

    def paint_body(self, hdc, w, h):
        pass

    def on_tick(self):
        sig = self.signature()
        if sig != getattr(self, "_sig", None):
            self._sig = sig
            self.invalidate()

    def signature(self):
        return (self.toast,) if time.time() - self.toast_at < 4 else ("",)

    def on_show(self):
        self.invalidate()


# ====================================================================== 运行状态
class StatusPage(Page):
    index = 0

    def __init__(self, app, main):
        super().__init__(app, main)
        self._mode_sig = None

    def build_footer(self):
        # 页头右上角：一键切回自动识别模式
        w, h = self.client_rect()
        self.add_button("auto", "自动识别模式", w - T.PAGE_PAD - 152, 18, 152, 38,
                        kind="soft", size=T.F_BODY, bold=True,
                        on_click=self._auto_clicked)
        self._sync_auto_btn()

    def _auto_clicked(self, btn):
        self.app.enable_auto("界面按钮")
        self._sync_auto_btn()
        self.set_toast("已切回自动识别模式，切换程序就会自动识别")

    def _sync_auto_btn(self):
        b = self.find_button("auto")
        if b is None:
            return
        if self.app.auto_active():
            b.kind, b.label = "soft", "● 自动识别中"
        elif self.app.auto_detect:
            b.kind, b.label = "primary", "恢复自动识别"
        else:
            b.kind, b.label = "primary", "手动模式 · 恢复"
        return

    # ---------------- 快捷切换按钮 ----------------
    def rebuild_modes(self):
        # 签名里带上「每个模式有哪些通道」—— 只比名字的话，
        # 给某个模式新加了画面补偿，主页按钮不会跟着刷新出来。
        sig = tuple((n, "|".join(config.mode_channels(
            config.mode_by_name(self.app.cfg, n) or {})))
            for n in self.app.mode_names())
        if sig == self._mode_sig:
            return
        self._mode_sig = sig
        self.buttons = [b for b in self.buttons if b.id != "quick"]
        # 只要这个模式**有任意一条可用通道**就该出现在主页：
        # 档位 / 私有码 / 亮度对比度 / 画面补偿，任意一个都算。
        # 以前这里只认 vcp，结果「只有画面补偿」的模式在主页根本不出现 ——
        # 这正是用户说的"主页也改不了"。
        names = [n for n, ch in sig if ch]
        if not names:
            return
        w, h = self.client_rect()
        inner = w - 2 * T.PAGE_PAD - 48
        n = min(len(names), 6)
        gap = 10
        bw = max(96, min(140, (inner - gap * (n - 1)) // n))
        for i, name in enumerate(names[:6]):
            color = config.mode_color(self.app.cfg, name)
            self.add_button("quick", name, T.PAGE_PAD + 24 + i * (bw + gap),
                            332, bw, 44,
                            kind="primary" if name == self.app.applied_mode
                            else "secondary",
                            size=T.F_BODY, bold=True,
                            on_click=self._make_click(name))
            self.buttons[-1].tag = color

    @staticmethod
    def _group_hint(st):
        if st.get("group", "—") == "—":
            return ""
        hint = "建议切到「%s」" % st.get("group_mode")
        if st.get("group_via"):
            hint += " · %s" % st["group_via"]
        return hint

    def _make_click(self, name):
        return lambda b: self.app.do_manual(name)

    def on_tick(self):
        self.rebuild_modes()
        self._sync_auto_btn()
        for b in self.buttons:
            if b.id == "quick":
                b.kind = ("primary" if b.label == self.app.applied_mode
                          else "secondary")
        super().on_tick()

    def signature(self):
        st = self.app.status or {}
        return (st.get("mode"), st.get("vcp"), st.get("fg_label"),
                st.get("fg_title"), st.get("group"), st.get("group_via"),
                st.get("auto"), st.get("auto_hint"), st.get("idle"),
                st.get("channel_note"), st.get("channel_ok"),
                len(st.get("hdr_on") or ()),
                self.toast, len(self.app.events))

    def _badge(self, st):
        """状态卡上的小徽章：这个模式靠哪条通道落地。"""
        v = st.get("vcp")
        if v is not None:
            return ("0xDC = %s" % v,
                    T.ACCENT if st.get("channel_ok", True) else T.DANGER)
        mode = config.mode_by_name(self.app.cfg, st.get("mode") or "")
        chans = config.mode_channels(mode or {})
        color = T.ACCENT if st.get("channel_ok", True) else T.DANGER
        if "补偿" in chans:
            return "画面补偿", color
        if "亮/对" in chans:
            return "亮度 / 对比度", color
        return "尚未配置", T.TEXT_FAINT

    # ---------------- 绘制 ----------------
    def paint_body(self, hdc, w, h):
        st = self.app.status or {}
        x0, y0 = T.PAGE_PAD, 96
        cw = w - 2 * T.PAGE_PAD

        # --- 当前状态卡 ---
        B.card(hdc, x0, y0, cw, 186)
        B.text(hdc, "当前模式", x0 + 24, y0 + 14, 200, 18,
               color=T.TEXT_FAINT, size=T.F_SMALL)
        B.text(hdc, st.get("mode", "—"), x0 + 24, y0 + 34, 340, 46,
               color=st.get("color", T.TEXT), size=T.F_BIG, bold=True)
        # 徽章说明"这个模式靠什么落到显示器上"。只有画面补偿的模式不写
        # 「0xDC = — 」——那会让人以为没配置成功。
        badge, badge_color = self._badge(st)
        B.pill(hdc, x0 + 24, y0 + 84, badge, badge_color)
        B.text(hdc, st.get("monitor", "—"), x0 + 24, y0 + 112, 330, 18,
               color=T.TEXT_SUB, size=T.F_SMALL)
        note = st.get("channel_note") or ""
        if note:
            B.text(hdc, note, x0 + 24, y0 + 132, 340, 18,
                   color=T.TEXT if st.get("channel_ok", True) else T.DANGER,
                   size=T.F_TINY)
        hdr_on = st.get("hdr_on") or []
        if hdr_on:
            # 这里只列「要靠画面补偿、却被高级颜色挡住」的屏。
            # 走自带档位的屏不列 —— 它开没开 HDR 跟补偿无关，
            # 列出来只会让人以为程序在瞎报（原来就写成"HDR 已开启"，
            # 而 advancedColorEnabled 在「自动管理颜色」下同样是 1）。
            B.text(hdc, "高级颜色挡着画面补偿：%s" % "、".join(hdr_on),
                   x0 + 24, y0 + 152, 340, 18, color=T.WARNING, size=T.F_TINY)

        B.vline(hdc, x0 + 382, y0 + 22, y0 + 164, T.DIVIDER)

        rows = [
            ("前台程序", st.get("fg_label", "—"),
             (st.get("fg_title") or "")[:30]),
            ("匹配分组", st.get("group", "—"), self._group_hint(st)),
            ("自动切换", st.get("auto", "—"), st.get("auto_hint", "")),
            ("配置概览", "%d 个分组 / %d 个应用"
             % (st.get("groups", 0), st.get("apps", 0)),
             "仅列表内触发"),
        ]
        ry = y0 + 20
        for label, value, hint in rows:
            B.text(hdc, label, x0 + 404, ry, 84, 24, color=T.TEXT_FAINT,
                   size=T.F_SMALL)
            B.text(hdc, value, x0 + 488, ry, cw - 520, 24, color=T.TEXT,
                   size=T.F_BODY, bold=True)
            if hint:
                tw = B.text_width(hdc, value, T.F_BODY, True)
                B.text(hdc, "· " + hint, x0 + 496 + tw, ry,
                       max(40, cw - 520 - tw), 24, color=T.TEXT_FAINT,
                       size=T.F_TINY)
            ry += 36

        # --- 快捷切换 ---
        y1 = y0 + 196
        B.card(hdc, x0, y1, cw, 112)
        B.text(hdc, "快捷切换", x0 + 24, y1 + 14, 200, 20, color=T.TEXT,
               size=T.F_H2, bold=True)
        B.text(hdc, "点一下立即切换；之后进入手动模式，"
                    "等你正在用的那个程序关掉就自动恢复识别",
               x0 + 110, y1 + 16, cw - 160, 18, color=T.TEXT_FAINT,
               size=T.F_TINY)
        if not [b for b in self.buttons if b.id == "quick"]:
            B.text(hdc, "还没有配置任何模式，请到「显示器与模式」里添加。",
                   x0 + 24, y1 + 58, cw - 48, 22, color=T.TEXT_FAINT,
                   size=T.F_BODY)

        # --- 最近事件 ---
        y2 = y1 + 128
        ch = max(120, h - y2 - 78)
        B.card(hdc, x0, y2, cw, ch)
        B.text(hdc, "最近事件", x0 + 24, y2 + 14, 200, 20, color=T.TEXT,
               size=T.F_H2, bold=True)
        B.text(hdc, "排障看这里，也可在程序目录打开 app.log", x0 + 110,
               y2 + 16, 400, 18, color=T.TEXT_FAINT, size=T.F_TINY)
        events = list(self.app.events)[-6:]
        if not events:
            B.text(hdc, "暂时没有事件", x0 + 24, y2 + 50, 300, 22,
                   color=T.TEXT_FAINT, size=T.F_SMALL)
        for i, (stamp, msg) in enumerate(events):
            ry = y2 + 44 + i * 25
            if ry > y2 + ch - 26:
                break
            B.text(hdc, stamp, x0 + 24, ry, 56, 20, color=T.TEXT_FAINT,
                   size=T.F_TINY)
            B.text(hdc, msg, x0 + 84, ry, cw - 108, 20, color=T.TEXT_SUB,
                   size=T.F_SMALL)


# ====================================================================== 场景分组
ID_GROUP_LIST = 201
ID_GROUP_NAME = 202
ID_GROUP_MODE = 203
ID_GROUP_ON = 204
ID_GROUP_APPS = 205


class GroupsPage(Page):
    index = 1

    def __init__(self, app, main):
        super().__init__(app, main)
        self.lb = None
        self.lv = None
        self.e_name = None
        self.cb_mode = None
        self.chk_on = None
        self.current = None      # 当前编辑的分组 id
        self._dirty = False

    # ---------------- 创建 ----------------
    def on_create(self):
        w, h = self.client_rect()
        x0, y0 = T.PAGE_PAD, 96
        rw = w - 2 * T.PAGE_PAD - 244          # 右侧卡片宽度

        self.lb = B.ListBox(self.hwnd, x0 + 16, y0 + 40, 200, 348,
                            font_size=T.F_BODY, cid=ID_GROUP_LIST)
        self.add_button("g_new", "新建", x0 + 16, y0 + 400, 96, 32,
                        size=T.F_SMALL, on_click=lambda b: self._new_group())
        self.add_button("g_del", "删除", x0 + 120, y0 + 400, 96, 32,
                        size=T.F_SMALL, kind="danger",
                        on_click=lambda b: self._del_group())

        rx = x0 + 244
        self.e_name = B.create_native(
            self.hwnd, "Edit", "",
            B.WS_CHILD | B.WS_VISIBLE | B.WS_TABSTOP | B.ES_AUTOHSCROLL,
            rx + 16, y0 + 64, 168, 28, cid=ID_GROUP_NAME, font_size=T.F_BODY)
        self.cb_mode = B.create_native(
            self.hwnd, "ComboBox", "",
            B.WS_CHILD | B.WS_VISIBLE | B.WS_TABSTOP | B.CBS_DROPDOWNLIST,
            rx + 196, y0 + 64, 150, 220, cid=ID_GROUP_MODE,
            font_size=T.F_BODY)
        self.chk_on = B.create_native(
            self.hwnd, "Button", "启用该分组",
            B.WS_CHILD | B.WS_VISIBLE | B.WS_TABSTOP | B.BS_AUTOCHECKBOX,
            rx + 360, y0 + 66, 110, 24, font_size=T.F_SMALL)
        B.set_check(self.chk_on, True)
        self.add_button("g_save", "保存分组", rx + rw - 96, y0 + 10, 84, 28,
                        size=T.F_SMALL, kind="soft",
                        on_click=lambda b: self._save_group())

        self.lv = B.ListView(self.hwnd, rx + 16, y0 + 130, rw - 32, 240,
                             [("应用", 200), ("进程名 / 标题", 200),
                              ("来源", 88)])
        by = y0 + 382
        self.add_button("a_preset", "从预设添加", rx + 16, by, 118, 34,
                        size=T.F_SMALL, on_click=lambda b: self._add_preset())
        self.add_button("a_add", "手动添加", rx + 142, by, 108, 34,
                        size=T.F_SMALL, on_click=lambda b: self._add_app())
        self.add_button("a_edit", "编辑", rx + 258, by, 88, 34,
                        size=T.F_SMALL, on_click=lambda b: self._edit_app())
        self.add_button("a_del", "移除", rx + 354, by, 88, 34,
                        size=T.F_SMALL, kind="danger",
                        on_click=lambda b: self._del_app())

    # ---------------- 绘制 ----------------
    def paint_body(self, hdc, w, h):
        x0, y0 = T.PAGE_PAD, 96
        cw = w - 2 * T.PAGE_PAD
        rw = cw - 244
        B.card(hdc, x0, y0, 232, 470)
        B.text(hdc, "分组列表", x0 + 16, y0 + 14, 180, 20, color=T.TEXT,
               size=T.F_H2, bold=True)

        rx = x0 + 244
        B.card(hdc, rx, y0, rw, 470)
        B.text(hdc, "分组设置", rx + 16, y0 + 14, 200, 20, color=T.TEXT,
               size=T.F_H2, bold=True)
        B.text(hdc, "名称", rx + 16, y0 + 42, 100, 18, color=T.TEXT_SUB,
               size=T.F_TINY)
        B.text(hdc, "对应模式", rx + 196, y0 + 42, 120, 18,
               color=T.TEXT_SUB, size=T.F_TINY)
        B.text(hdc, "应用列表", rx + 16, y0 + 106, 120, 18, color=T.TEXT_SUB,
               size=T.F_SMALL)

        group = config.group_by_id(self.app.cfg, self.current)
        if group:
            kind = group.get("kind", "custom")
            hint = presets.archetype(kind).get("hint", "")
            B.text(hdc, "%s ｜ %s" % (presets.GROUP_LABEL.get(kind, "自定义"),
                                      hint),
                   rx + 80, y0 + 106, rw - 100, 18, color=T.TEXT_FAINT,
                   size=T.F_TINY)
            B.text(hdc,
                   "共 %d 个应用 · 只有这些程序的窗口在前台时才会触发切换"
                   % len(group.get("apps", [])),
                   rx + 16, y0 + 420, rw - 32, 20, color=T.TEXT_FAINT,
                   size=T.F_TINY)
        else:
            B.text(hdc, "还没有分组，点左边的「新建」创建一个。", rx + 16,
                   y0 + 106, rw - 32, 20, color=T.TEXT_FAINT, size=T.F_SMALL)

        B.text(hdc, "提示：同名进程只认映像名（如 winword.exe），比窗口标题稳定；"
                    "窗口标题匹配适合没有固定进程名的客户端。",
               x0, y0 + 486, cw, 20, color=T.TEXT_FAINT, size=T.F_TINY)

    # ---------------- 消息 ----------------
    def handle(self, msg, wp, lp):
        if msg == B.WM_COMMAND:
            cid, code = B._loword(wp), B._hiword(wp)
            if cid == ID_GROUP_LIST and code == 1:   # LBN_SELCHANGE
                self._load_group()
                return 0
        return super().handle(msg, wp, lp)

    # ---------------- 数据 ----------------
    def on_show(self):
        self.refresh_groups()
        super().on_show()

    def refresh_groups(self, keep=None):
        groups = self.app.cfg.get("groups", [])
        target = keep or self.current
        self.lb.clear()
        for g in groups:
            self.lb.add("%s（%d）" % (g["name"], len(g.get("apps", []))),
                        g["id"])
        if not groups:
            self.current = None
            self._fill_fields(None)
            return
        idx = 0
        for i, g in enumerate(groups):
            if g["id"] == target:
                idx = i
                break
        self.lb.select(idx)
        self._load_group(idx)

    def _selected_id(self):
        idx = self.lb.selected_index() if self.lb else -1
        groups = self.app.cfg.get("groups", [])
        if 0 <= idx < len(groups):
            return groups[idx]["id"]
        return None

    def _load_group(self, idx=None):
        gid = self._selected_id()
        self.current = gid
        self._fill_fields(config.group_by_id(self.app.cfg, gid))

    def _fill_fields(self, group):
        modes = self.app.mode_names()
        B.set_combo_items(self.cb_mode, modes,
                          group.get("mode") if group else None)
        B.set_text(self.e_name, group["name"] if group else "")
        B.set_check(self.chk_on, group.get("enabled", True) if group else True)
        self.refresh_apps()

    def refresh_apps(self):
        self.lv.clear()
        group = config.group_by_id(self.app.cfg, self.current)
        if not group:
            return
        for app in group.get("apps", []):
            target = app.get("exe") or ("标题含 " + app.get("title", ""))
            is_preset = (app.get("src") == "preset"
                         or presets.is_preset(group.get("kind", ""),
                                              app.get("exe")))
            self.lv.add([app.get("name", "?"), target,
                         "预设" if is_preset else "自定义"], app)

    def collect(self):
        group = config.group_by_id(self.app.cfg, self.current)
        if group:
            self._apply_fields(group)

    def _apply_fields(self, group):
        name = B.get_text(self.e_name).strip()
        mode = B.combo_selection(self.cb_mode, self.app.mode_names())
        if name:
            group["name"] = name
        if mode:
            group["mode"] = mode
        group["enabled"] = B.get_check(self.chk_on)

    # ---------------- 操作 ----------------
    def _save_group(self):
        group = config.group_by_id(self.app.cfg, self.current)
        if not group:
            return
        self._apply_fields(group)
        self.app.save_config()
        self.app.reset_ask_state()
        self.refresh_groups(keep=group["id"])
        self.set_toast("分组「%s」已保存" % group["name"])
        self.app.log("保存分组：%s（%d 个应用）"
                     % (group["name"], len(group.get("apps", []))))

    def _new_group(self):
        data = D.GroupDialog(self.main.hwnd, self.app.mode_names()).run()
        if not data:
            return
        groups = self.app.cfg.setdefault("groups", [])
        gid = data["kind"] if data["kind"] not in [
            g["id"] for g in groups] else "g%d" % int(time.time())
        apps = [dict(a, src="preset")
                for a in presets.default_apps(data["kind"])]
        groups.append({"id": gid, "name": data["name"], "mode": data["mode"],
                       "kind": data["kind"], "enabled": True, "apps": apps})
        self.app.save_config()
        self.app.reset_ask_state()
        self.current = gid
        self.refresh_groups(keep=gid)
        self.set_toast("已创建分组「%s」" % data["name"])
        self.app.log("新建分组：%s（%d 个预设应用）"
                     % (data["name"], len(apps)))

    def _del_group(self):
        group = config.group_by_id(self.app.cfg, self.current)
        if not group:
            return
        ok = D.ConfirmDialog(
            self.main.hwnd, "删除分组",
            "确定删除分组「%s」吗？\n里面的 %d 个应用配置会一起删除。"
            % (group["name"], len(group.get("apps", []))),
            ok_text="删除", danger=True).run()
        if not ok:
            return
        self.app.cfg["groups"] = [g for g in self.app.cfg.get("groups", [])
                                  if g["id"] != group["id"]]
        self.app.save_config()
        self.app.reset_ask_state()
        self.current = None
        self.refresh_groups()
        self.set_toast("分组已删除")
        self.app.log("删除分组：%s" % group["name"])

    def _add_preset(self):
        group = config.group_by_id(self.app.cfg, self.current)
        if not group:
            return
        picked = D.PresetDialog(self.main.hwnd, group.get("kind", "custom"),
                                [a.get("exe") for a in group.get("apps", [])]
                                ).run()
        if not picked:
            return
        for a in picked:
            group.setdefault("apps", []).append(dict(a, src="preset"))
        self.app.save_config()
        self.app.reset_ask_state()
        self.refresh_groups(keep=group["id"])
        self.set_toast("已添加 %d 个应用" % len(picked))
        self.app.log("从预设添加：%s" % "、".join(a["name"] for a in picked))

    def _add_app(self):
        group = config.group_by_id(self.app.cfg, self.current)
        if not group:
            return
        data = D.AppDialog(self.main.hwnd, "添加应用").run()
        if not data:
            return
        group.setdefault("apps", []).append(dict(data, src="custom"))
        self.app.save_config()
        self.app.reset_ask_state()
        self.refresh_groups(keep=group["id"])
        self.set_toast("已添加「%s」" % data["name"])
        self.app.log("手动添加应用：%s -> %s"
                     % (data["name"], data["exe"] or data["title"]))

    def _edit_app(self):
        app = self.lv.selected()
        if not app:
            return
        data = D.AppDialog(self.main.hwnd, "编辑应用", app.get("name", ""),
                           app.get("exe", ""), app.get("title", "")).run()
        if not data:
            return
        app.update(data)
        app["src"] = "custom"
        self.app.save_config()
        self.app.reset_ask_state()
        self.refresh_groups(keep=self.current)
        self.set_toast("已更新「%s」" % data["name"])

    def _del_app(self):
        app = self.lv.selected()
        group = config.group_by_id(self.app.cfg, self.current)
        if not app or not group:
            return
        group["apps"] = [a for a in group.get("apps", []) if a is not app]
        self.app.save_config()
        self.app.reset_ask_state()
        self.refresh_groups(keep=group["id"])
        self.set_toast("已移除「%s」" % app.get("name", ""))


# ====================================================================== 显示器与模式
ID_MON_COMBO = 301
ID_MODE_LIST = 302
ID_MON_CHK0 = 311          # 311..314：最多 4 台显示器的勾选框
MON_SLOTS = 4
ID_FOLLOW = 315            # 「跟随活跃屏」开关


class ModesPage(Page):
    index = 2

    def on_create(self):
        w, h = self.client_rect()
        x0, y0 = T.PAGE_PAD, 96
        cw = w - 2 * T.PAGE_PAD
        # 多显示器勾选：2 列 × 2 行
        self.mon_checks = []
        for i in range(MON_SLOTS):
            cx = x0 + 16 + (i % 2) * 268
            cy = y0 + 42 + (i // 2) * 30
            chk = B.create_native(
                self.hwnd, "Button", "显示器 %d" % (i + 1),
                B.WS_CHILD | B.WS_VISIBLE | B.WS_TABSTOP | B.BS_AUTOCHECKBOX,
                cx, cy, 258, 24, cid=ID_MON_CHK0 + i, font_size=T.F_SMALL)
            self.mon_checks.append(chk)
        # 「跟随活跃屏」开关。只能塞在标题行右边 ——
        # 这张卡片已经排满了，加高会顶到底部那条「保存设置」上。
        self.chk_follow = B.create_native(
            self.hwnd, "Button", "跟随活跃屏",
            B.WS_CHILD | B.WS_VISIBLE | B.WS_TABSTOP | B.BS_AUTOCHECKBOX,
            x0 + 612, y0 + 10, 190, 24, cid=ID_FOLLOW, font_size=T.F_SMALL)
        self.add_button("m_wizard", "引导配置", x0 + 584, y0 + 52, 108, 32,
                        size=T.F_SMALL, kind="primary",
                        on_click=lambda b: self._wizard())
        self.add_button("m_rescan", "重新检测", x0 + 700, y0 + 52, 100, 32,
                        size=T.F_SMALL, on_click=lambda b: self._rescan())
        # 卡片 2 从 y0+176 起（卡片 1 高 166）。列表必须落在卡片标题下方，
        # 所以是 y0+176+44，不能贴着卡片顶。
        self.lv = B.ListView(self.hwnd, x0 + 16, y0 + 220, cw - 32, 190,
                             [("模式名称", 200), ("切换通道", 250),
                              ("说明", 320)])
        by = y0 + 420
        self.add_button("md_add", "添加模式", x0 + 16, by, 104, 34,
                        size=T.F_SMALL, kind="soft",
                        on_click=lambda b: self._add_mode())
        self.add_button("md_edit", "编辑", x0 + 128, by, 92, 34,
                        size=T.F_SMALL, on_click=lambda b: self._edit_mode())
        self.add_button("md_del", "删除", x0 + 228, by, 92, 34,
                        size=T.F_SMALL, kind="danger",
                        on_click=lambda b: self._del_mode())
        self.add_button("md_test", "切换测试", x0 + 328, by, 104, 34,
                        size=T.F_SMALL, on_click=lambda b: self._test_mode())
        self.add_button("md_read", "用当前值更正", x0 + 440, by, 124, 34,
                        size=T.F_SMALL, on_click=lambda b: self._read_mode())
        self.add_button("md_restore", "恢复原始画面", x0 + 576, by, 118, 34,
                        size=T.F_SMALL, on_click=lambda b: self._restore())

    # ---------------- 绘制 ----------------
    def paint_body(self, hdc, w, h):
        # 页面内可用高度 = 客户区 720 - 标题栏 44 - 底部操作条 64 = 612。
        # 三块纵向排布必须收在 594 以内，否则会压到底部「保存设置」那一条上。
        x0, y0 = T.PAGE_PAD, 96
        cw = w - 2 * T.PAGE_PAD
        B.card(hdc, x0, y0, cw, 166)
        B.text(hdc, "显示器", x0 + 16, y0 + 14, 120, 20, color=T.TEXT,
               size=T.F_H2, bold=True)
        if self.app.follow_active():
            sub = "自动跟随你正在操作的屏；其余屏保持上一次的样子"
        else:
            sub = "只有勾选的屏才跟着场景变；没勾的屏完全不动"
        B.text(hdc, sub, x0 + 80, y0 + 16, 520, 18, color=T.TEXT_FAINT,
               size=T.F_TINY)
        info = self._monitor_info()
        B.text(hdc, info, x0 + 16, y0 + 100, cw - 32, 18, color=T.TEXT_SUB,
               size=T.F_TINY)
        hdr = self.app.hdr_report()
        B.text(hdc, hdr, x0 + 16, y0 + 120, cw - 32, 18,
               color=(T.WARNING if "补偿失效" in hdr else T.TEXT_FAINT),
               size=T.F_TINY)
        B.text(hdc, "勾选的屏里，DDC 写不动的会自动改用「画面补偿」（显卡通道，"
                    "改色温/对比/中间调/饱和度）；点「恢复原始画面」可撤销全部补偿。",
               x0 + 16, y0 + 140, cw - 32, 18, color=T.TEXT_FAINT,
               size=T.F_TINY)

        y1 = y0 + 176
        B.card(hdc, x0, y1, cw, 294)
        B.text(hdc, "显示器模式（OSD 预设 + 画面补偿）", x0 + 16, y1 + 14, 320,
               20, color=T.TEXT, size=T.F_H2, bold=True)
        B.text(hdc, "「切换通道」列写的就是这个模式落到显示器的方式",
               x0 + 300, y1 + 16, 480, 18, color=T.TEXT_FAINT,
               size=T.F_TINY)

        y2 = y1 + 302
        B.text(hdc, "新增模式的方法：用显示器实体按键切到想要的画面，回到这里点"
                    "「添加模式」→「用当前值更正」即可自动记录档位；"
                    "也可以只配画面补偿。",
               x0, y2, cw, 20, color=T.TEXT_FAINT, size=T.F_TINY)

    def _monitor_info(self):
        mon = self.app.monitors or []
        if not mon:
            return "没有检测到显示器。"
        done = self.app.setup_done_map()
        chunks = []
        for m in mon:
            n = m["index"] + 1
            if not m["controllable"]:
                chunks.append("%d：DDC 不通" % n)
            elif not m["mode_capable"] and not done.get(m["index"]):
                chunks.append("%d：待配置（点「引导配置」）" % n)
            elif not m["mode_capable"]:
                # 2.2.0 起这种屏默认走画面补偿，说"只能用亮度/对比度"会让人
                # 以为只能动背光（其实色温/对比/中间调都能变）
                chunks.append("%d：只能用画面补偿" % n)
            else:
                chunks.append("%d：%s，当前 %s" % (
                    n,
                    ddc.VCP_NAMES.get(m["mode_vcp"], hex(m["mode_vcp"])),
                    m["current"]))
        return " ｜ ".join(chunks)

    # ---------------- 消息 ----------------
    def handle(self, msg, wp, lp):
        if msg == B.WM_COMMAND:
            cid, code = B._loword(wp), B._hiword(wp)
            if ID_MON_CHK0 <= cid < ID_MON_CHK0 + MON_SLOTS and code == 0:
                self._apply_checks()
                return 0
            if cid == ID_FOLLOW and code == 0:
                self._toggle_follow()
                return 0
        return super().handle(msg, wp, lp)

    def _toggle_follow(self):
        on = bool(B.get_check(self.chk_follow))
        self.app.set_follow_active(on)
        self.refresh_monitors()
        self.refresh_modes()
        self.invalidate()
        if on:
            self.set_toast("已开启：只调你正在用的那块屏，其余保持上一次的样子")
        else:
            self.set_toast("已关闭跟随，改回按勾选控制")

    def _apply_checks(self):
        """勾选框变了 -> 立刻生效（不需要点保存）。"""
        mons = self.app.monitors or []
        picked = [i for i, chk in enumerate(self.mon_checks)
                  if i < len(mons) and B.get_check(chk)]
        if picked:
            self.app.set_monitor_indices(picked)
            self.set_toast("只控制 %d 台显示器，其余屏不再跟着变" % len(picked))
        else:
            # 一台都没勾 = 全部控制（跟 config 里 enabled 为空同义）
            self.app.set_monitor_indices([])
            self.set_toast("没勾任何一台，已按「全部控制」处理")
        self.refresh_monitors()
        self.refresh_modes()

    def _select_all(self):
        self.app.set_monitor_indices([])
        self.refresh_monitors()
        self.refresh_modes()
        self.set_toast("已改为控制所有显示器")

    def _wizard(self):
        """打开「添加显示器引导」：自动识别这台屏的情景模式挂在哪个码上。"""
        need = self.app.monitors_needing_setup()
        mons = self.app.monitors or []
        # 优先引导还没配过的那台；都配过了就让用户从头选
        idx = need[0]["index"] if need else (mons[0]["index"] if mons else None)
        res = self.app.open_monitor_wizard(idx)
        self.refresh_monitors()
        self.refresh_modes()
        if res:
            self.set_toast("显示器 %d 配置完成，记录了 %d 个模式"
                           % (res.get("index", 0) + 1, res.get("records", 0)))
        else:
            self.set_toast("已跳过引导，可以随时点「引导配置」再来")

    # ---------------- 数据 ----------------
    def on_show(self):
        self.refresh_monitors()
        self.refresh_modes()
        super().on_show()

    def refresh_monitors(self):
        mons = self.app.monitors or []
        active = set(self.app.ddc_indices())
        done = self.app.setup_done_map()
        follow = self.app.follow_active()
        B.set_check(self.chk_follow, follow)
        for i, chk in enumerate(self.mon_checks):
            if i < len(mons):
                m = mons[i]
                label = m.get("short") or ("显示器 %d" % (i + 1))
                if not m["controllable"]:
                    label += "（DDC 不通）"
                elif m["mode_capable"]:
                    if m["mode_vcp"] != ddc.VCP_MODE:
                        name = ddc.VCP_NAMES.get(m["mode_vcp"],
                                                 "0x%02X" % m["mode_vcp"])
                        label += "（%s）" % name
                elif not done.get(m["index"]):
                    # 0xDC 报不出来：不判死，可能是挂在私有码上，引导一下才知道
                    label += "（待配置）"
                else:
                    label += "（画面补偿）"
                B.set_text(chk, label)
                B.set_check(chk, i in active)
                # 跟随模式下勾选不决定控谁（控的是当前活跃屏），
                # 置灰免得用户以为"勾了没用"是个 bug。勾选状态照常显示，
                # 跑起来能看到它跟着活跃屏跳。
                B.user32.EnableWindow(chk, not follow)
                B.user32.ShowWindow(chk, B.SW_SHOW)
            else:
                B.user32.ShowWindow(chk, B.SW_HIDE)

    def refresh_modes(self):
        self.lv.clear()
        for m in config.modes(self.app.cfg):
            self.lv.add([m.get("name", "?"), self._channels_text(m),
                         self._usage(m.get("name"))], m)

    @staticmethod
    def _channels_text(m):
        """「切换通道」列：这个模式究竟靠什么落地。

        列出全部四条（档位 / 私有码 / 亮对 / 补偿），因为一个模式可以同时
        配多条 —— 主屏走档位、副屏走补偿，一次切换两台一起变。
        """
        parts = []
        v = m.get("vcp")
        if v is not None:
            parts.append("0xDC=%s" % v)
        mv = m.get("monitor_vcp") or {}
        if mv:
            parts.append("私有码 %d 台" % len(mv))
        per = m.get("per_monitor") or {}
        if per:
            parts.append("亮/对 %d 台" % len(per))
        p = config.mode_gamma_of(m)
        if p:
            parts.append(G.describe(p))
        return " · ".join(parts) or "未配置（切换无效）"

    def _usage(self, name):
        used = []
        for g in self.app.cfg.get("groups", []):
            if g.get("mode") == name:
                used.append(g["name"])
        if self.app.cfg.get("return_default", {}).get("mode") == name:
            used.append("默认回退")
        if self.app.cfg.get("idle", {}).get("mode") == name:
            used.append("空闲节能")
        return "、".join(used) or "未被引用"

    def collect(self):
        pass

    # ---------------- 操作 ----------------
    def _rescan(self):
        self.app.refresh_monitors()
        self.app.rebuild_ddc()
        self.refresh_monitors()
        self.refresh_modes()
        self.set_toast("已重新检测显示器")

    def _add_mode(self):
        data = D.ModeDialog(self.main.hwnd, self.app).run()
        if not data:
            return
        if config.mode_by_name(self.app.cfg, data["name"]):
            B.message_box("已经有同名模式了，换个名字吧。", "重名", 0x30)
            return
        data["color"] = config.next_mode_color(self.app.cfg)
        if G.is_neutral(data.get("gamma") or {}):
            data.pop("gamma", None)
        self.app.cfg.setdefault("modes", []).append(data)
        self.app.save_config()
        self.app.reset_ask_state()
        self.refresh_modes()
        self.set_toast("已添加模式「%s」" % data["name"])
        self.app.log("新增模式：%s (%s)" % (data["name"],
                                         self._channels_text(data)))

    def _edit_mode(self):
        mode = self.lv.selected()
        if not mode:
            return
        data = D.ModeDialog(self.main.hwnd, self.app, mode.get("name", ""),
                            mode.get("vcp"), mode.get("gamma")).run()
        if not data:
            return
        old = mode.get("name")
        mode["name"] = data["name"]
        mode["vcp"] = data["vcp"]
        if G.is_neutral(data.get("gamma") or {}):
            mode.pop("gamma", None)
        else:
            mode["gamma"] = data["gamma"]
        if old != data["name"]:
            self._rename_refs(old, data["name"])
        self.app.save_config()
        self.app.reset_ask_state()
        self.refresh_modes()
        self.set_toast("模式已更新")
        self.app.log("修改模式：%s -> %s (%s)"
                     % (old, data["name"], self._channels_text(mode)))

    def _rename_refs(self, old, new):
        cfg = self.app.cfg
        for g in cfg.get("groups", []):
            if g.get("mode") == old:
                g["mode"] = new
        for key in ("return_default", "idle"):
            if cfg.get(key, {}).get("mode") == old:
                cfg[key]["mode"] = new

    def _del_mode(self):
        mode = self.lv.selected()
        if not mode:
            return
        ok = D.ConfirmDialog(
            self.main.hwnd, "删除模式",
            "确定删除模式「%s」吗？\n引用它的分组会自动改回第一个模式。"
            % mode.get("name"), ok_text="删除", danger=True).run()
        if not ok:
            return
        self.app.cfg["modes"] = [m for m in config.modes(self.app.cfg)
                                 if m is not mode]
        first = self.app.mode_names()
        fallback = first[0] if first else "用户模式"
        for g in self.app.cfg.get("groups", []):
            if g.get("mode") == mode.get("name"):
                g["mode"] = fallback
        for key in ("return_default", "idle"):
            if self.app.cfg.get(key, {}).get("mode") == mode.get("name"):
                self.app.cfg[key]["mode"] = fallback
        self.app.save_config()
        self.app.reset_ask_state()
        self.refresh_modes()
        self.set_toast("模式已删除")
        self.app.log("删除模式：%s" % mode.get("name"))

    def _test_mode(self):
        mode = self.lv.selected()
        if not mode:
            return
        if self.app.preview_mode(mode["name"]):
            self.set_toast("已切换到「%s」" % mode["name"])
            res = self.app.last_apply or {}
            if res.get("summary"):
                self.set_toast("已切换到「%s」：%s"
                               % (mode["name"], res["summary"]))
        # 切换会改变通道状态（走补偿还是走档位），列表里的「说明」不用变，
        # 但显示器信息的「当前值」可能变了
        self.refresh_monitors()

    def _restore(self):
        """撤销所有画面补偿，回到显卡的原始查找表。

        这是 Gamma 通道唯一的"退路"：程序退出时会保留补偿效果（用户切到
        电影模式后关程序，不该变回去），所以必须留一个显式的恢复入口。
        """
        res = D.ConfirmDialog(
            self.main.hwnd, "恢复原始画面",
            "会撤销所有显示器上的「画面补偿」，回到显卡原本的输出。\n\n"
            "显示器自己的情景模式（OSD 预设）不受影响 —— 那是显示器内部状态，"
            "程序只能改回去做不到。",
            ok_text="恢复").run()
        if not res:
            return
        ok = self.app.restore_gamma()
        self.set_toast("已恢复原始画面" if ok else "恢复失败，请看日志")
        self.refresh_monitors()

    def _read_mode(self):
        """把"显示器此刻的样子"记到这个模式上（多台一起记）。

        支持情景模式 VCP 的显示器记显示值；
        不支持的（比如只能调亮度/对比度的副屏）记下它当前的亮度和对比度，
        切换时用这两个值来模拟这个模式。
        """
        mode = self.lv.selected()
        if not mode:
            return
        snap = self.app.ddc.snapshot()
        if not snap:
            B.message_box("读不到显示器当前值，请确认显示器已开启 DDC/CI。",
                          "读取失败", 0x30)
            return

        primary = None
        per = {}
        notes = []
        for idx in sorted(snap):
            info = snap[idx]
            if info.get("vcp") is not None and info.get("value") is not None:
                if primary is None:
                    primary = info["value"]
                notes.append("%d 号=%s" % (idx + 1, info["value"]))
            elif (info.get("brightness") is not None
                    or info.get("contrast") is not None):
                per[str(idx)] = {
                    k: info[k] for k in ("brightness", "contrast")
                    if info.get(k) is not None
                }
                notes.append("%d 号=亮度%s/对比度%s" % (
                    idx + 1, info.get("brightness"), info.get("contrast")))

        if primary is None and not per:
            B.message_box("这台显示器既不支持情景模式，也读不到亮度/对比度。",
                          "读取失败", 0x30)
            return

        if primary is not None:
            mode["vcp"] = primary
        if per:
            mode["per_monitor"] = per
        else:
            mode.pop("per_monitor", None)
        self.app.save_config()
        self.app.reset_ask_state()
        self.refresh_modes()
        self.set_toast("「%s」已记录：%s" % (mode["name"], "，".join(notes)))
        self.app.log("记录模式 %s：%s" % (mode["name"], "，".join(notes)))


# ====================================================================== 高级设置
ID_SET_IDLE_ON = 401
ID_SET_IDLE_MIN = 402
ID_SET_IDLE_MODE = 403
ID_SET_IDLE_MEDIA = 404
ID_SET_IDLE_FS = 405
ID_SET_RETURN_ON = 411
ID_SET_RETURN_MODE = 412
ID_SET_ASK = 421
ID_SET_TIMEOUT = 422
ID_SET_POLL = 431
ID_SET_PAUSE = 432
ID_SET_STARTUP = 433
ID_SET_GAMMA = 434


class SettingsPage(Page):
    index = 3

    def on_create(self):
        w, h = self.client_rect()
        x0, y0 = T.PAGE_PAD, 96
        cw = w - 2 * T.PAGE_PAD

        self.chk_idle = B.create_native(
            self.hwnd, "Button", "启用空闲节能",
            B.WS_CHILD | B.WS_VISIBLE | B.WS_TABSTOP | B.BS_AUTOCHECKBOX,
            x0 + 16, y0 + 20, 150, 24, cid=ID_SET_IDLE_ON,
            font_size=T.F_BODY)
        # 看视频/听音乐时人不会碰键鼠，光看"多久没输入"会误判成空闲。
        # 这两个开关就是给这种情况开的口子。
        self.chk_media = B.create_native(
            self.hwnd, "Button", "看视频/听歌时不算空闲",
            B.WS_CHILD | B.WS_VISIBLE | B.WS_TABSTOP | B.BS_AUTOCHECKBOX,
            x0 + 300, y0 + 18, 210, 24, cid=ID_SET_IDLE_MEDIA,
            font_size=T.F_SMALL)
        self.chk_idle_fs = B.create_native(
            self.hwnd, "Button", "全屏播放时不算空闲",
            B.WS_CHILD | B.WS_VISIBLE | B.WS_TABSTOP | B.BS_AUTOCHECKBOX,
            x0 + 520, y0 + 18, 210, 24, cid=ID_SET_IDLE_FS,
            font_size=T.F_SMALL)
        self.e_idle = B.create_native(
            self.hwnd, "Edit", "",
            B.WS_CHILD | B.WS_VISIBLE | B.WS_TABSTOP | B.ES_NUMBER,
            x0 + 82, y0 + 56, 56, 28, cid=ID_SET_IDLE_MIN,
            font_size=T.F_BODY)
        self.cb_idle = B.create_native(
            self.hwnd, "ComboBox", "",
            B.WS_CHILD | B.WS_VISIBLE | B.WS_TABSTOP | B.CBS_DROPDOWNLIST,
            x0 + 300, y0 + 56, 150, 200, cid=ID_SET_IDLE_MODE,
            font_size=T.F_BODY)

        y1 = y0 + 124
        self.chk_return = B.create_native(
            self.hwnd, "Button", "离开情景后切回默认模式",
            B.WS_CHILD | B.WS_VISIBLE | B.WS_TABSTOP | B.BS_AUTOCHECKBOX,
            x0 + 16, y1 + 20, 240, 24, cid=ID_SET_RETURN_ON,
            font_size=T.F_BODY)
        self.cb_return = B.create_native(
            self.hwnd, "ComboBox", "",
            B.WS_CHILD | B.WS_VISIBLE | B.WS_TABSTOP | B.CBS_DROPDOWNLIST,
            x0 + 300, y1 + 56, 150, 200, cid=ID_SET_RETURN_MODE,
            font_size=T.F_BODY)

        y2 = y1 + 112
        self.chk_ask = B.create_native(
            self.hwnd, "Button", "切换前弹窗让我确认",
            B.WS_CHILD | B.WS_VISIBLE | B.WS_TABSTOP | B.BS_AUTOCHECKBOX,
            x0 + 16, y2 + 20, 220, 24, cid=ID_SET_ASK,
            font_size=T.F_BODY)
        self.e_timeout = B.create_native(
            self.hwnd, "Edit", "",
            B.WS_CHILD | B.WS_VISIBLE | B.WS_TABSTOP | B.ES_NUMBER,
            x0 + 150, y2 + 56, 56, 28, cid=ID_SET_TIMEOUT,
            font_size=T.F_BODY)

        y3 = y2 + 112
        self.e_poll = B.create_native(
            self.hwnd, "Edit", "",
            B.WS_CHILD | B.WS_VISIBLE | B.WS_TABSTOP,
            x0 + 16, y3 + 40, 56, 28, cid=ID_SET_POLL,
            font_size=T.F_BODY)
        self.e_pause = B.create_native(
            self.hwnd, "Edit", "",
            B.WS_CHILD | B.WS_VISIBLE | B.WS_TABSTOP | B.ES_NUMBER,
            x0 + 150, y3 + 40, 56, 28, cid=ID_SET_PAUSE,
            font_size=T.F_BODY)
        self.chk_startup = B.create_native(
            self.hwnd, "Button", "开机自动启动",
            B.WS_CHILD | B.WS_VISIBLE | B.WS_TABSTOP | B.BS_AUTOCHECKBOX,
            x0 + cw - 156, y3 + 76, 140, 24, cid=ID_SET_STARTUP,
            font_size=T.F_BODY)
        # 全局开关：有人用校色仪校过屏，不希望任何软件动显卡查找表。
        # 关掉后 Gamma 通道完全不参与，纯 DDC 行为。
        self.chk_gamma = B.create_native(
            self.hwnd, "Button", "DDC 写不动时用画面补偿兜底",
            B.WS_CHILD | B.WS_VISIBLE | B.WS_TABSTOP | B.BS_AUTOCHECKBOX,
            x0 + 16, y3 + 76, 260, 24, cid=ID_SET_GAMMA,
            font_size=T.F_BODY)
        self.add_button("open_log", "查看运行日志", x0 + 400, y3 + 36, 116, 32,
                        size=T.F_SMALL, on_click=lambda b: self._open("log"))
        self.add_button("open_dir", "打开程序目录", x0 + 524, y3 + 36, 116, 32,
                        size=T.F_SMALL, on_click=lambda b: self._open("dir"))

    # ---------------- 绘制 ----------------
    def paint_body(self, hdc, w, h):
        x0, y0 = T.PAGE_PAD, 96
        cw = w - 2 * T.PAGE_PAD

        B.card(hdc, x0, y0, cw, 116)
        B.text(hdc, "空闲节能", x0 + 16, y0 + 52, 60, 20, color=T.TEXT_SUB,
               size=T.F_SMALL)
        B.text(hdc, "分钟后切换到", x0 + 144, y0 + 60, 150, 18,
               color=T.TEXT_SUB, size=T.F_SMALL)
        B.text(hdc, "省电预设，一动就恢复原模式", x0 + 460, y0 + 62,
               cw - 480, 18, color=T.TEXT_FAINT, size=T.F_TINY)

        y1 = y0 + 124
        B.card(hdc, x0, y1, cw, 104)
        B.text(hdc, "当前程序不属于任何分组时：", x0 + 16, y1 + 60, 180, 20,
               color=T.TEXT_SUB, size=T.F_SMALL)
        B.text(hdc, "默认回退到", x0 + 200, y1 + 60, 90, 20,
               color=T.TEXT_SUB, size=T.F_SMALL)
        B.text(hdc, "避免停留在上一个情景", x0 + 460, y1 + 20, cw - 480, 18,
               color=T.TEXT_FAINT, size=T.F_TINY)

        y2 = y1 + 112
        B.card(hdc, x0, y2, cw, 104)
        B.text(hdc, "弹窗倒计时", x0 + 16, y2 + 60, 120, 20,
               color=T.TEXT_SUB, size=T.F_SMALL)
        B.text(hdc, "秒（倒计时结束自动采用下拉里的选择）", x0 + 216, y2 + 60,
               300, 20, color=T.TEXT_SUB, size=T.F_SMALL)
        self.paint_hint(hdc, x0 + 460, y2 + 20, cw - 480,
                        "关掉后检测到情景会直接切换")

        y3 = y2 + 112
        B.card(hdc, x0, y3, cw, 146)
        B.text(hdc, "轮询间隔（秒）", x0 + 16, y3 + 18, 130, 18,
               color=T.TEXT_SUB, size=T.F_SMALL)
        B.text(hdc, "暂停时长（分钟）", x0 + 150, y3 + 18, 190, 18,
               color=T.TEXT_SUB, size=T.F_SMALL)
        B.text(hdc, "补偿改的是显卡查找表（色温/对比/中间调/饱和度），"
                    "改不了背光；HDR 开启时自动让路。",
               x0 + 16, y3 + 108, cw - 236, 18, color=T.TEXT_FAINT,
               size=T.F_TINY)
        # 「保存设置」这句原来放在 y3+76 的右侧，正好压在「开机自动启动」
        # 那个复选框上（截图里能看到半截字）。挪到卡片右下角，右对齐。
        B.text(hdc, "改动点右下角「保存设置」才生效",
               x0 + cw - 196, y3 + 108, 180, 18, color=T.TEXT_FAINT,
               size=T.F_TINY, align="right")

    def paint_hint(self, hdc, x, y, w, s):
        B.text(hdc, s, x, y, w, 18, color=T.TEXT_FAINT, size=T.F_TINY)

    # ---------------- 数据 ----------------
    def on_show(self):
        cfg = self.app.cfg
        modes = self.app.mode_names()
        B.set_check(self.chk_idle, cfg["idle"].get("enabled", True))
        B.set_check(self.chk_media, cfg["idle"].get("ignore_media", True))
        B.set_check(self.chk_idle_fs,
                    cfg["idle"].get("ignore_fullscreen", True))
        B.set_text(self.e_idle, "%d" % int(cfg["idle"].get("minutes", 10)))
        B.set_combo_items(self.cb_idle, modes, cfg["idle"].get("mode"))
        B.set_check(self.chk_return, cfg["return_default"].get("enabled", True))
        B.set_combo_items(self.cb_return, modes,
                          cfg["return_default"].get("mode"))
        B.set_check(self.chk_ask, cfg.get("ask_before_switch", True))
        B.set_text(self.e_timeout,
                   "%d" % int(cfg.get("dialog_timeout_seconds", 10)))
        B.set_text(self.e_poll, "%g" % float(cfg.get("poll_seconds", 1.5)))
        B.set_text(self.e_pause, "%d" % int(
            cfg.get("manual_override_pause_minutes", 10)))
        from screenmode import winapi
        B.set_check(self.chk_startup, winapi.startup_enabled())
        B.set_check(self.chk_gamma, config.gamma_enabled(cfg))
        super().on_show()

    def collect(self):
        cfg = self.app.cfg
        modes = self.app.mode_names()
        cfg["idle"]["enabled"] = B.get_check(self.chk_idle)
        cfg["idle"]["ignore_media"] = B.get_check(self.chk_media)
        cfg["idle"]["ignore_fullscreen"] = B.get_check(self.chk_idle_fs)
        try:
            cfg["idle"]["minutes"] = max(1, int(B.get_text(self.e_idle)))
        except ValueError:
            pass
        cfg["idle"]["mode"] = B.combo_selection(self.cb_idle, modes) or \
            cfg["idle"].get("mode")
        cfg["return_default"]["enabled"] = B.get_check(self.chk_return)
        cfg["return_default"]["mode"] = \
            B.combo_selection(self.cb_return, modes) or \
            cfg["return_default"].get("mode")
        cfg["ask_before_switch"] = B.get_check(self.chk_ask)
        try:
            cfg["dialog_timeout_seconds"] = max(1, int(
                B.get_text(self.e_timeout)))
        except ValueError:
            pass
        try:
            cfg["poll_seconds"] = max(0.5, float(B.get_text(self.e_poll)))
        except ValueError:
            pass
        try:
            cfg["manual_override_pause_minutes"] = max(0, int(
                B.get_text(self.e_pause)))
        except ValueError:
            pass
        from screenmode import winapi
        winapi.set_startup(B.get_check(self.chk_startup))
        cfg.setdefault("gamma", {})["enabled"] = B.get_check(self.chk_gamma)

    def _open(self, what):
        from screenmode import app as app_mod
        from screenmode import winapi
        if what == "log":
            winapi.open_path(app_mod.LOG_PATH)
        else:
            winapi.open_path(app_mod.BASE_DIR)


# ====================================================================== 主窗口
class MainWindow(B.Win):
    bg = T.SIDEBAR

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.pages = []
        self.active = 0

    def create_window(self):
        w, h = T.WIN_W, T.WIN_H
        sx = (B.user32.GetSystemMetrics(B.SM_CXSCREEN) - w) // 2
        sy = max(20, (B.user32.GetSystemMetrics(B.SM_CYSCREEN) - h) // 2 - 60)
        # 无系统标题栏，标题栏由 paint() 自绘；顶部 44px 可拖动（drag_height）
        self.create(APP_NAME, sx, sy, w, h, parent=None,
                    style=B.WS_POPUP | B.WS_VISIBLE | B.WS_CLIPCHILDREN,
                    exstyle=0)
        self.drag_height = T.TITLEBAR_H
        if self.hwnd:
            B.style_caption(self.hwnd, T.SIDEBAR, "#FFFFFF", T.SIDEBAR)
        return bool(self.hwnd)

    # ---------------- 创建 ----------------
    def on_create(self):
        w, h = self.client_rect()
        top = T.TITLEBAR_H
        for i, (label, _) in enumerate(NAV):
            b = self.add_button("nav%d" % i, label, 14, top + 20 + i * 52,
                                T.SIDEBAR_W - 28, 46, kind="nav",
                                size=T.F_BODY, on_click=self._nav_click(i))
            b.active = (i == 0)
        self.add_button("min", "—", w - 76, 8, 34, 28, kind="close",
                        size=T.F_H2,
                        on_click=lambda b: B.user32.ShowWindow(
                            self.hwnd, B.SW_MINIMIZE))
        self.add_button("close", "✕", w - 40, 8, 34, 28, kind="close",
                        size=T.F_SMALL, hover_bg=T.CLOSE_HOVER,
                        on_click=lambda b: B.user32.PostMessageW(
                            self.hwnd, B.WM_CLOSE, 0, 0))
        self.add_button("hide", "隐藏到托盘", 14, h - 56, 118, 34,
                        kind="nav", size=T.F_SMALL,
                        on_click=lambda b: B.user32.ShowWindow(
                            self.hwnd, B.SW_HIDE))
        self.add_button("quit", "退出", 140, h - 56, 70, 34, kind="nav",
                        size=T.F_SMALL,
                        on_click=lambda b: self.app.request_quit())

        for cls in (StatusPage, GroupsPage, ModesPage, SettingsPage):
            page = cls(self.app, self)
            page.create_page()
            self.pages.append(page)
        self.show_page(0)
        self._setup_offered = False     # 首次引导是否已经问过（只问一次）
        B.user32.SetTimer(self.hwnd, 1, 500, None)

    def _maybe_offer_setup(self):
        """检测到还没配过的显示器时，主动问一次要不要走引导。

        为什么不能自动判定「不支持情景模式」：有的屏压根不在能力串里报 0xDC，
        菜单里却有完整的情景模式（用户手上这台就是）。只有引导跑一遍，
        靠「用户切、程序读」才能知道它的模式挂在哪个码上。
        """
        if not B.user32.IsWindowVisible(self.hwnd):
            return                      # 启动时直接收进托盘了，先不打扰
        need = self.app.monitors_needing_setup()
        if not need:
            return
        m = need[0]
        name = m.get("short") or ("显示器 %d" % (m["index"] + 1))
        msg = ("检测到「%s」还没配置过。\n\n"
               "它的「情景模式」挂在哪个 VCP 码上，程序没法凭空猜 ——"
               "配一次（约 1 分钟）之后，切换模式就能把这台屏一起带上。\n\n"
               "要现在开始吗？" % name)
        ok = D.ConfirmDialog(self.hwnd, "配置新显示器", msg,
                             ok_text="开始引导", height=336).run()
        if ok:
            self.app.open_monitor_wizard(m["index"])
            self.refresh_all()
        else:
            # 用户说不用 -> 记下来，别每次启动都问；随时可以点「引导配置」
            self.app.mark_setup_done(m["index"])

    def refresh_all(self):
        for page in self.pages:
            fn = getattr(page, "refresh_monitors", None)
            if fn:
                try:
                    fn()
                except Exception:
                    pass

    def _nav_click(self, index):
        return lambda b: self.show_page(index)

    def page_rect(self):
        w, h = self.client_rect()
        return (T.SIDEBAR_W, T.TITLEBAR_H, w - T.SIDEBAR_W,
                h - T.TITLEBAR_H)

    def show_page(self, index):
        self.active = index
        for i, page in enumerate(self.pages):
            if not page.hwnd:
                continue
            if i == index:
                page.on_show()
                B.user32.ShowWindow(page.hwnd, B.SW_SHOW)
                B.user32.InvalidateRect(page.hwnd, None, False)
            else:
                B.user32.ShowWindow(page.hwnd, B.SW_HIDE)
        for b in self.buttons:
            if str(b.id).startswith("nav"):
                b.active = (b.id == "nav%d" % index)
        self.invalidate()

    # ---------------- 绘制 ----------------
    def paint(self, hdc, w, h):
        sw = T.SIDEBAR_W
        tb = T.TITLEBAR_H
        # 侧栏底色（含标题栏所在的一整列）
        B.fill_rect(hdc, 0, 0, sw, h, T.SIDEBAR)
        # 顶部标题栏：整条深色带 + 底部一条细线
        B.fill_rect(hdc, 0, 0, w, tb, T.SIDEBAR)
        B.hline(hdc, 0, tb - 1, w, T.SIDEBAR_LINE)

        # 标题栏左侧：logo + 名称 + 版本
        B.round_rect(hdc, 20, 9, 26, 26, 8, fill=T.ACCENT)
        B.text(hdc, "屏", 20, 9, 26, 26, color="#FFFFFF", size=T.F_SMALL,
               bold=True, align="center")
        B.text(hdc, APP_NAME, 54, 10, 120, 24, color="#FFFFFF",
               size=T.F_BODY, bold=True)
        B.text(hdc, "v%s" % VERSION, 116, 12, 80, 20,
               color="#5C6577", size=T.F_TINY)

        # 标题栏下的侧栏内容
        st = self.app.status or {}
        B.hline(hdc, 16, h - 152, sw - 16, T.SIDEBAR_LINE)
        B.text(hdc, "当前模式", 26, h - 132, 140, 18, color="#5C6577",
               size=T.F_TINY)
        B.dot(hdc, 30, h - 100, 5, st.get("color", "#8A8F99"))
        B.text(hdc, st.get("mode", "—"), 42, h - 110, sw - 60, 22,
               color="#E6E9F0", size=T.F_BODY, bold=True)

    # ---------------- 消息 ----------------
    def handle(self, msg, wp, lp):
        if msg == WM_APP_DIALOG:
            self._show_switch_dialog()
            return 0
        if msg == WM_APP_TRAY:
            self.app.on_tray_action(int(wp))
            return 0
        if msg == B.WM_CLOSE:
            # 点右上角 × = 收进托盘；程序已经在退出流程里时才真的关掉
            if getattr(self.app, "running", True):
                B.user32.ShowWindow(self.hwnd, B.SW_HIDE)
            else:
                B.user32.DestroyWindow(self.hwnd)
            return 0
        if msg == B.WM_TIMER and wp == 1:
            if 0 <= self.active < len(self.pages):
                self.pages[self.active].on_tick()
            self.invalidate()
            # 首次发现没配过的显示器 -> 主动引导一次（只问一次，问过就记账）
            if not self._setup_offered:
                self._setup_offered = True
                self._maybe_offer_setup()
            return 0
        if msg == B.WM_DESTROY:
            B.user32.KillTimer(self.hwnd, 1)
            B.user32.PostQuitMessage(0)
            return super().handle(msg, wp, lp)
        return super().handle(msg, wp, lp)

    def _show_switch_dialog(self):
        req = self.app.take_dialog_request()
        if not req:
            return
        # 主界面没开着（在托盘里 / 已经收起）时，弹窗不挂在主窗口上：
        # 这样选完模式只在后台静默切换，不会顺手把主界面顶出来。
        was_visible = bool(B.user32.IsWindowVisible(self.hwnd))
        owner = self.hwnd if was_visible else None
        prev = B.user32.GetForegroundWindow()
        choice = D.SwitchDialog(
            owner, req.get("suggested"), req.get("options", []),
            req.get("timeout", 10), req.get("context", "")).run()
        if was_visible:
            B.user32.SetForegroundWindow(self.hwnd)
        else:
            B.user32.ShowWindow(self.hwnd, B.SW_HIDE)   # 兜底：确保没被带出来
            # 选完把焦点还给刚才那个程序，静默切换、不打断
            if prev and prev != self.hwnd and B.user32.IsWindow(prev):
                B.user32.SetForegroundWindow(prev)
        self.app.finish_dialog_request(choice)

    def message_loop(self):
        msg = B.MSG()
        while B.user32.GetMessageW(ctypes.byref(msg), 0, 0, 0) > 0:
            B.user32.TranslateMessage(ctypes.byref(msg))
            B.user32.DispatchMessageW(ctypes.byref(msg))
        return True
