# -*- coding: utf-8 -*-
r"""「屏幕体检」窗口 —— 安装主程序之前先跑一遍。

设计上的三条硬规矩
------------------
1. **只读**。除了「把 0xDC 的当前值原样写回去」这一下（等于什么都没改），
   全程不做任何写入。0x14 / 0xCC 这类码连试都不试 ——
   实测写它们会真的改掉显示器的色彩预设（见 checkup._write_back 注释）。
2. **不依赖主程序的配置**。这个 exe 可以独立分发，用户还没装主程序也能用。
3. **画面通道必须让用户自己看一眼**。gamma 改的是显示器收到的查找表，
   截图抓不到任何变化，程序没法自证"生效了"。所以最后一步是问一句
   「画面变了吗？」，用人的眼睛做裁判。
"""
import ctypes
import datetime
import math
import os
import threading
from ctypes import wintypes as wt

from screenmode import app_dir
from screenmode import checkup as C
from screenmode.ui import base as B
from screenmode.ui import theme as T

user32 = ctypes.windll.user32
gdi = ctypes.windll.gdi32
# 64 位下 HDC/HBITMAP 句柄会超 32 位，不设 restype 会在 _snapshot 里溢出报错
gdi.CreateCompatibleDC.restype = ctypes.c_void_p
gdi.CreateCompatibleBitmap.restype = ctypes.c_void_p
gdi.SelectObject.restype = ctypes.c_void_p
user32.GetDC.restype = ctypes.c_void_p

BADGE = {
    C.VERDICT_NATIVE: ("可以用 · 自带档位", T.SUCCESS),
    C.VERDICT_COMP: ("可以用 · 画面补偿", T.WARNING),
    C.VERDICT_NONE: ("用不了", T.DANGER),
}


class CheckupWindow(B.Dialog):
    header_h = 70

    def __init__(self):
        super().__init__(None, "屏幕体检", 980, 720)
        self.rep = None
        self.phase = "idle"        # idle / probing / ask / done
        self.status = "正在检测，请稍等几秒…"
        self.dirty = True
        self.gamma = None
        self.gamma_devices = []
        self.saved_to = ""
        self._worker = None
        self._fitted = False

    # ------------------------------------------------------------ 创建
    def on_create(self):
        w, h = self.client_rect()
        bx = w - 24
        self.add_button("save", "保存报告", bx - 108, h - 58, 108, 38,
                        kind="soft", size=T.F_SMALL, on_click=self._save)
        bx -= 118
        self.add_button("gamma", "测试画面通道", bx - 132, h - 58, 132, 38,
                        kind="soft", size=T.F_SMALL, on_click=self._gamma_start)
        bx -= 142
        self.add_button("again", "重新检测", bx - 108, h - 58, 108, 38,
                        kind="secondary", size=T.F_SMALL,
                        on_click=self._again)
        # 关闭按钮由 Dialog.run() 统一加（右上角那个 ×），这里不再重复加一个
        # 「看到了 / 没看到」两个按钮平时藏在窗口外，等画面测试时才挪出来
        self.add_button("seen", "看到了，变了", 24, -200, 150, 40,
                        kind="primary", bold=True, on_click=self._gamma_seen)
        self.add_button("nope", "没变化", 184, -200, 110, 40,
                        kind="secondary", on_click=self._gamma_nosee)
        user32.SetTimer(self.hwnd, 1, 150, None)
        self._start()

    # ------------------------------------------------------------ 检测
    def _start(self):
        self.phase = "probing"
        self.rep = None
        self._fitted = False
        self.status = "正在检测，请稍等几秒…（只会读，不会改你任何设置）"
        self.invalidate()

        def work():
            try:
                rep = C.run(progress=self._progress)
            except Exception as exc:
                rep = {"error": repr(exc), "rows": []}
            self.rep = rep
            self.phase = "error" if rep.get("error") else "done"
            if not rep.get("error"):
                self.status = C.summary_line(rep)
            self.dirty = True

        self._worker = threading.Thread(target=work, daemon=True)
        self._worker.start()

    def _progress(self, stage, text):
        self.status = text
        self.dirty = True

    def _again(self, _b=None):
        if self.phase == "ask":
            self._gamma_cancel()
        self._start()

    def on_timer(self, tid):
        if tid == 2:
            # 10 秒没回答，当"没看到"处理并恢复画面 —— 别把用户的屏一直留在偏暖状态
            self._gamma_finish(False)
            self.status = "10 秒没有选择，已按「没变化」处理并恢复原样"
            self.dirty = True
            return 0
        if self.dirty:
            self.dirty = False
            if self.phase == "done" and not self._fitted:
                self._fitted = True
                self._fit()
            self.invalidate()
        return 0

    # ------------------------------------------------------------ 画面测试
    def _gamma_start(self, _b=None):
        rows = (self.rep or {}).get("rows") or []
        # 只测那些「走不了自带档位」的屏 —— 走得通的屏压根不需要补偿
        devs = [r["device"] for r in rows
                if r["verdict"] != C.VERDICT_NATIVE and r.get("device")]
        if not devs:
            self.status = "没有需要测画面通道的显示器"
            self.dirty = True
            return
        self.gamma_devices = devs
        g = C.GammaProbe(devs, store_dir=self._store_dir())
        ok = g.start()
        if not ok:
            self.status = "这台屏不接受 gamma 写入，画面通道不可用"
            g.close()
            self.dirty = True
            return
        self.gamma = g
        self.phase = "ask"
        self.status = ("画面已经调成明显偏暖、偏亮 —— 你看这块屏变了吗？"
                       "（10 秒内不选会自动恢复）")
        self._fit(extra=52)
        user32.SetTimer(self.hwnd, 2, 10000, None)
        self.dirty = True

    def _gamma_finish(self, visible):
        if self.gamma is not None:
            self.gamma.stop()
            self.gamma.close()
            self.gamma = None
        user32.KillTimer(self.hwnd, 2)
        self.phase = "done"
        for r in (self.rep or {}).get("rows") or []:
            if r["device"] in self.gamma_devices:
                r["gamma_visible"] = bool(visible)
                if not visible and r["verdict"] == C.VERDICT_COMP:
                    r["verdict"] = C.VERDICT_NONE
                    r["advice"] = (
                        "显卡的查找表写进去了，但画面没有变化 —— "
                        "系统很可能正把显示输出交给 HDR / 自动管理颜色接管。"
                        "到 设置 → 系统 → 显示 → 高级显示 里关掉它们再测一次；"
                        "关不掉的话，这台屏就没法跟着场景变了。")
        self.status = ("画面通道可用：这台屏能跟着场景变色温/对比度"
                       if visible else
                       "画面通道不可用：写进去了但画面没变")
        # 多了一行「画面测试」，卡片会变高，这里重算一次窗口尺寸
        self._fit()
        self.dirty = True

    def _gamma_seen(self, _b=None):
        self._gamma_finish(True)

    def _gamma_nosee(self, _b=None):
        self._gamma_finish(False)

    def _gamma_cancel(self):
        self._gamma_finish(False)

    # ------------------------------------------------------------ 保存
    def _store_dir(self):
        """存 gamma 基线用的小目录 —— **跟着 exe 走**，不往别处写。

        绿色版的原则是"删文件夹就等于卸载"，所以缓存也得在人眼皮底下：
        放在 %LOCALAPPDATA%\\ScreenMode 的话，用户把文件夹删了、以为干净了，
        那儿还留着一个 checkup_base.json。

        只有真的写不进去才退回家目录 —— 万一程序被放在 Program Files 这种
        只读位置。这时候宁可多一个文件，也不能没有基线：没基线就等于下次
        「恢复原样」时把驱动自带的校色表抹成恒等斜坡。
        """
        here = app_dir()
        try:
            probe = os.path.join(here, ".write_test")
            with open(probe, "w", encoding="utf-8") as f:
                f.write("ok")
            os.remove(probe)
            return here
        except Exception:
            pass
        root = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        path = os.path.join(root, "ScreenMode")
        try:
            os.makedirs(path, exist_ok=True)
        except Exception:
            path = os.path.expanduser("~")
        return path

    def _save(self, _b=None):
        if not self.rep:
            self.status = "还没检测完"
            self.dirty = True
            return
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M")
        desk = os.path.join(os.path.expanduser("~"), "Desktop")
        out_dir = desk if os.path.isdir(desk) else self._store_dir()
        base = os.path.join(out_dir, "屏幕体检报告-%s" % stamp)
        try:
            with open(base + ".txt", "w", encoding="utf-8") as f:
                f.write(C.report_text(self.rep))
            png_ok = self._snapshot(base + ".png")
            self.saved_to = base + (".png" if png_ok else ".txt")
            self.status = "已保存：%s" % self.saved_to
        except Exception as exc:
            self.status = "保存失败：%r" % (exc,)
        self.dirty = True

    def _snapshot(self, path):
        """把窗口本身抓成 png（出问题直接连着图一起发出去）。"""
        try:
            r = wt.RECT()
            user32.GetWindowRect(self.hwnd, ctypes.byref(r))
            w, h = r.right - r.left, r.bottom - r.top
            src = user32.GetDC(0)
            mem = gdi.CreateCompatibleDC(ctypes.c_void_p(src))
            bmp = gdi.CreateCompatibleBitmap(ctypes.c_void_p(src), w, h)
            old = gdi.SelectObject(ctypes.c_void_p(mem),
                                   ctypes.c_void_p(bmp))
            ok = user32.PrintWindow(ctypes.c_void_p(self.hwnd),
                                    ctypes.c_void_p(mem), 2)
            gdi.SelectObject(ctypes.c_void_p(mem), ctypes.c_void_p(old))
            if not ok:
                return False

            class BIH(ctypes.Structure):
                _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG),
                            ("biHeight", wt.LONG), ("biPlanes", wt.WORD),
                            ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                            ("biSizeImage", wt.DWORD),
                            ("biXPelsPerMeter", wt.LONG),
                            ("biYPelsPerMeter", wt.LONG),
                            ("biClrUsed", wt.DWORD),
                            ("biClrImportant", wt.DWORD)]

            bi = BIH()
            bi.biSize = ctypes.sizeof(bi)
            bi.biWidth = w
            bi.biHeight = -h
            bi.biPlanes = 1
            bi.biBitCount = 32
            buf = ctypes.create_string_buffer(w * h * 4)
            gdi.GetDIBits(ctypes.c_void_p(mem), ctypes.c_void_p(bmp), 0, h,
                          buf, ctypes.byref(bi), 0)
            gdi.DeleteObject(ctypes.c_void_p(bmp))
            gdi.DeleteDC(ctypes.c_void_p(mem))
            user32.ReleaseDC(0, ctypes.c_void_p(src))
            from PIL import Image
            Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1)\
                 .convert("RGB").save(path)
            return True
        except Exception:
            return False

    # ------------------------------------------------------------ 布局
    @staticmethod
    def _lines_of(row):
        """一张卡片要显示哪几行（标签, 内容, 颜色）。"""
        out = []
        col = row["color"]
        out.append(("高级颜色", col.get("text", ""),
                    T.WARNING if col.get("advanced") else T.TEXT_SUB))
        if row["ddc_ok"]:
            out.append(("DDC/CI", "可用 · 能力串 %d 字节" % row["caps_len"],
                        T.TEXT_SUB))
        else:
            out.append(("DDC/CI", "不可用 · %s" % (row["ddc_note"] or "打不开"),
                        T.DANGER))
        if row["reads"]:
            out.append(("能读的码", "、".join(
                "0x%02X=%s" % (c, v) for c, _l, v in row["reads"]),
                T.TEXT_SUB))
        else:
            out.append(("能读的码", "一个都读不到", T.DANGER))
        if row["writes"]:
            out.append(("写测试", " · ".join(
                "0x%02X %s：%s（%s）" % (c, l, "通过" if ok else "失败", note)
                for c, l, ok, note in row["writes"]),
                T.TEXT_SUB))
        else:
            out.append(("写测试", "未做（0xDC 读不到，盲写可能改掉画面）",
                        T.TEXT_FAINT))
        if "gamma_visible" in row:
            out.append(("画面测试", "看得见变化" if row["gamma_visible"]
                        else "看不出变化",
                        T.SUCCESS if row["gamma_visible"] else T.DANGER))
        return out

    @staticmethod
    def _advice_lines(text, w):
        """估算建议文字要占几行。

        中文字宽约 11.6px，ASCII 约 6px，按权重折算成"几个汉字宽"，
        再除以一行能放几个。误差最多差一行，用来定卡片高度足够了 ——
        这里没有 HDC，没法真的量字宽。
        """
        if not text:
            return 0
        units = sum(1.0 if ord(c) > 127 else 0.52 for c in text)
        per = max(1.0, (w - 36) / 11.6)
        return max(1, int(math.ceil(units / per)))

    def _cards(self, w):
        """-> [(row, y, h)]，同时给出内容总高。"""
        rows = (self.rep or {}).get("rows") or []
        out = []
        y = 112
        for row in rows:
            lines = self._lines_of(row)
            al = self._advice_lines(row.get("advice") or "", w)
            h = 44 + 20 * len(lines) + 18 * al + 22
            out.append((row, y, h))
            y += h + 10
        return out, y

    def _fit(self, extra=0):
        """按内容把窗口高度收到刚好的尺寸。

        extra 是给「画面测试」那条提问横幅留的高度 —— 不加的话横幅会
        直接压到最后一张卡片上（第一版就是这样，把说明文字盖住了）。
        """
        if not self.rep or not (self.rep.get("rows")):
            return
        w, _h = self.client_rect()
        _cards, content_bottom = self._cards(w)
        want = content_bottom + 62 + extra
        want = max(420, min(880, want))
        # NOMOVE(0x2) | NOZORDER(0x4)：只改高度，别把窗口挪走
        user32.SetWindowPos(self.hwnd, 0, 0, 0, self.win_w, want, 0x0006)
        self._place_footer()

    def _place_footer(self):
        w, h = self.client_rect()
        bx = w - 24
        for bid, bw in (("save", 108), ("gamma", 132), ("again", 108)):
            b = self.find_button(bid)
            if b:
                b.x = bx - bw
                b.y = h - 58
                b.w = bw
                bx -= bw + 10
        b = self.find_button("seen")
        if b:
            b.y = h - 60 if self.phase == "ask" else -200
        b = self.find_button("nope")
        if b:
            b.y = h - 60 if self.phase == "ask" else -200

    # ------------------------------------------------------------ 绘制
    def paint(self, hdc, w, h):
        B.fill_rect(hdc, 0, 0, w, self.header_h, T.ACCENT)
        B.text(hdc, "屏幕体检", 24, 10, 400, 30, color="#FFFFFF",
               size=T.F_H1, bold=True)
        B.text(hdc, "安装主程序之前先跑一遍：告诉你这台显示器是能用、"
                    "只能用画面补偿，还是根本用不了",
               24, 42, w - 80, 22, color="#DCE8FB", size=T.F_TINY)
        self.paint_body(hdc, w, h)

    def paint_body(self, hdc, w, h):
        rows = (self.rep or {}).get("rows") or []
        err = (self.rep or {}).get("error")

        B.text(hdc, self.status, 24, 80, w - 48, 20,
               color=T.SUCCESS if self.phase == "done" else T.TEXT_SUB,
               size=T.F_SMALL)

        if err:
            B.text(hdc, "检测出错了：%s" % err, 24, 112, w - 48, 40,
                   color=T.DANGER, size=T.F_SMALL, wrap=True)
            return
        if not rows:
            B.text(hdc, "正在读取每台显示器的 DDC 能力…", 24, 126, w - 48, 24,
                   color=T.TEXT_FAINT, size=T.F_BODY)
            return

        cards, bottom = self._cards(w)
        for i, (row, y, ch) in enumerate(cards):
            self._card(hdc, 24, y, w - 48, ch, row, i)

        if self.phase == "ask":
            self._ask_strip(hdc, w, bottom)
        elif self.saved_to:
            B.text(hdc, "报告已保存：%s" % self.saved_to, 24, h - 52,
                   w - 300, 18, color=T.TEXT_FAINT, size=T.F_TINY)

    def _card(self, hdc, x, y, w, h, row, i):
        B.card(hdc, x, y, w, h)
        title = "显示器 %d · %s · %s%s" % (
            i + 1, row["name"], row["size"],
            "  （主屏）" if row["primary"] else "")
        B.text(hdc, title, x + 18, y + 10, w - 260, 24, color=T.TEXT,
               size=T.F_H2, bold=True)
        label, color = BADGE.get(row["verdict"], ("?", T.TEXT_FAINT))
        B.text(hdc, label, x + w - 240, y + 12, 220, 22, color=color,
               size=T.F_BODY, bold=True, align="right")

        lines = self._lines_of(row)
        ly = y + 42
        for label, text, color in lines:
            B.text(hdc, label, x + 18, ly, 76, 18, color=T.TEXT_FAINT,
                   size=T.F_TINY)
            B.text(hdc, text, x + 98, ly, w - 120, 18, color=color,
                   size=T.F_TINY)
            ly += 20

        adv = row.get("advice") or ""
        if adv:
            B.text(hdc, adv, x + 18, ly + 4, w - 36, h - (ly - y) - 10,
                   color=T.TEXT_FAINT, size=T.F_TINY, wrap=True)

    def _ask_strip(self, hdc, w, y):
        B.card(hdc, 24, y, w - 48, 42)
        B.text(hdc, "现在这块屏应该明显偏暖、偏亮。看到了就点左边的按钮，"
                    "没变化就点「没变化」—— 10 秒不选会自动恢复原样。",
               38, y, w - 76, 42, color=T.TEXT, size=T.F_SMALL)

    # ------------------------------------------------------------ 收尾
    def on_destroy(self):
        # 关窗口时一定要把画面恢复回去，否则用户的屏会一直偏暖
        if self.gamma is not None:
            try:
                self.gamma.stop()
                self.gamma.close()
            except Exception:
                pass
            self.gamma = None
        super().on_destroy()

    def on_escape(self):
        self.ok(None)


def main():
    w = CheckupWindow()
    w.run()
    return 0
