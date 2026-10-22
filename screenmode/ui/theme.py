# -*- coding: utf-8 -*-
"""配色 / 字号 / 尺寸常量。改这里就能整体换肤。"""

# ---------- 颜色 ----------
SIDEBAR = "#161A23"
SIDEBAR_ITEM = "#242B3A"
SIDEBAR_ITEM_HOVER = "#1E2431"
SIDEBAR_TEXT = "#9AA3B2"
SIDEBAR_TEXT_ACTIVE = "#FFFFFF"
SIDEBAR_LINE = "#242A36"

PAGE_BG = "#F5F6F9"
CARD_BG = "#FFFFFF"
CARD_BORDER = "#E7EAF0"
DIVIDER = "#EDEFF4"

TEXT = "#1B1F27"
TEXT_SUB = "#6B7280"
TEXT_FAINT = "#9CA3AF"

ACCENT = "#3478F6"
ACCENT_DARK = "#2A63D2"
ACCENT_LIGHT = "#EAF1FE"
DANGER = "#E5484D"
DANGER_LIGHT = "#FDECEC"
SUCCESS = "#12A150"
WARNING = "#E8A33D"

FIELD_BG = "#FFFFFF"
FIELD_BORDER = "#D8DEE9"

# ---------- 尺寸 ----------
WIN_W = 1080
WIN_H = 720
SIDEBAR_W = 224
TITLEBAR_H = 44        # 自绘标题栏高度（无系统标题栏）
PAGE_PAD = 28          # 内容区左右内边距
HEADER_H = 96          # 页面标题区高度
FOOTER_H = 64          # 页面底部操作条

CLOSE_HOVER = "#C42C1C"   # 关闭按钮 hover 红

RADIUS = 10            # 卡片圆角
BTN_RADIUS = 8

# ---------- 字号（负值 = 像素高度，Win32 约定） ----------
F_BIG = -34
F_H1 = -22
F_H2 = -17
F_BODY = -15
F_SMALL = -13
F_TINY = -12

FONT_FAMILY = "Microsoft YaHei UI"

# ---------- 模式默认配色（用户新增模式时轮换使用） ----------
MODE_PALETTE = ["#6E7480", "#3478F6", "#8B5CF6", "#12A150", "#E5484D",
                "#0EA5E9", "#F59E0B", "#EC4899", "#14B8A6", "#7C3AED"]


def rgb(color):
    """'#RRGGBB' -> Win32 COLORREF (0x00BBGGRR)"""
    if isinstance(color, int):
        return color
    c = color.lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    r = int(c[0:2], 16)
    g = int(c[2:4], 16)
    b = int(c[4:6], 16)
    return r | (g << 8) | (b << 16)


def mix(color, other, ratio):
    """按比例混合两个颜色，ratio=0 返回 color。"""
    c1 = color.lstrip("#")
    c2 = other.lstrip("#")
    out = []
    for i in (0, 2, 4):
        a = int(c1[i:i + 2], 16)
        b = int(c2[i:i + 2], 16)
        out.append(int(round(a + (b - a) * ratio)))
    return "#%02X%02X%02X" % tuple(out)


def darker(color, amount=0.12):
    return mix(color, "#000000", amount)


def lighter(color, amount=0.9):
    return mix(color, "#FFFFFF", amount)
