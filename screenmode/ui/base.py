# -*- coding: utf-8 -*-
"""Win32 底层封装：窗口、绘制、自绘按钮、原生控件、模态对话框。

整个界面不用 tkinter（本机 Python 不带 Tk），全部基于 ctypes 直接调用 Win32/GDI。
设计：卡片、标题、按钮等"装饰"由各页面自己 WM_PAINT 画出来，
只有真正需要输入的控件（编辑框 / 下拉框 / 列表）才创建原生子窗口。
这样既能精确控制外观，又不必重度自绘每个控件。
"""
import ctypes
import os
from ctypes import wintypes as wt

from screenmode.ui import theme as T

DEBUG = bool(os.environ.get("SM_DEBUG"))

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
kernel32 = ctypes.windll.kernel32
comctl32 = ctypes.windll.comctl32
uxtheme = ctypes.windll.uxtheme
shell32 = ctypes.windll.shell32

# ------------------------------------------------------------------ 常量
WS_CHILD = 0x40000000
WS_VISIBLE = 0x10000000
WS_POPUP = 0x80000000
WS_CAPTION = 0x00C00000
WS_SYSMENU = 0x00080000
WS_BORDER = 0x00800000
WS_VSCROLL = 0x00200000
WS_TABSTOP = 0x00010000
WS_CLIPCHILDREN = 0x02000000
WS_CLIPSIBLINGS = 0x04000000
WS_EX_DLGMODALFRAME = 0x00000001
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000

ES_AUTOHSCROLL = 0x0080
ES_NUMBER = 0x2000
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
RDW_INVALIDATE = 0x0001
RDW_UPDATENOW = 0x0100
RDW_ALLCHILDREN = 0x0080
RDW_FRAME = 0x0400
CBS_DROPDOWN = 0x0002
CBS_DROPDOWNLIST = 0x0003
CBS_HASSTRINGS = 0x0200
BS_PUSHBUTTON = 0x00000000
BS_AUTOCHECKBOX = 0x00000003
LBS_NOTIFY = 0x0001
LBS_NOINTEGRALHEIGHT = 0x0100
LVS_REPORT = 0x0001
LVS_SINGLESEL = 0x0004
LVS_SHOWSELALWAYS = 0x0008
LVS_NOSORTHEADER = 0x8000

WM_CREATE = 0x0001
WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_PAINT = 0x000F
WM_ERASEBKGND = 0x0014
WM_SETCURSOR = 0x0020
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_KEYDOWN = 0x0100
WM_COMMAND = 0x0111
WM_TIMER = 0x0113
WM_SETFONT = 0x0030
WM_GETFONT = 0x0031
WM_CTLCOLORSTATIC = 0x0138
WM_CTLCOLOREDIT = 0x0133
WM_CTLCOLORLISTBOX = 0x0134
WM_CTLCOLORBTN = 0x0135
WM_NCCREATE = 0x0081
WM_NCDESTROY = 0x0082
WM_NCHITTEST = 0x0084
# WM_NCHITTEST 的返回值：千万别用 0 —— 那是 HTNOWHERE，
# 系统会认为该点不属于本窗口，鼠标消息根本不会派发过来。
HTNOWHERE = 0
HTCLIENT = 1
HTCAPTION = 2
WM_APP = 0x8000
WM_MOUSELEAVE = 0x02A3
WM_SETTEXT = 0x000C
WM_GETTEXT = 0x000D
WM_GETTEXTLENGTH = 0x000E

GWLP_USERDATA = -21
TME_LEAVE = 0x00000002
IDC_ARROW = 32512
IDC_HAND = 32649
NULL_BRUSH = 5
TRANSPARENT = 1
DT_LEFT = 0x0000
DT_CENTER = 0x0001
DT_RIGHT = 0x0002
DT_VCENTER = 0x0004
DT_SINGLELINE = 0x0020
DT_WORDBREAK = 0x0010
DT_NOPREFIX = 0x0800
DT_END_ELLIPSIS = 0x8000
DT_PATH_ELLIPSIS = 0x4000
SRCCOPY = 0x00CC0020

# ListView / ComboBox / ListBox 消息
LVM_FIRST = 0x1000
LVM_DELETEALLITEMS = LVM_FIRST + 9
LVM_GETNEXTITEM = LVM_FIRST + 12
LVM_SETCOLUMNWIDTH = LVM_FIRST + 30
LVM_SETEXTENDEDLISTVIEWSTYLE = LVM_FIRST + 54
LVM_INSERTITEMW = LVM_FIRST + 77
LVM_INSERTCOLUMNW = LVM_FIRST + 97
LVM_SETITEMTEXTW = LVM_FIRST + 116
LVM_SETITEMSTATE = LVM_FIRST + 43
LVNI_SELECTED = 0x0002
LVIF_TEXT = 0x0001
LVCF_FMT = 0x0001
LVCF_WIDTH = 0x0002
LVCF_TEXT = 0x0004
LVCF_SUBITEM = 0x0008
LVCFMT_LEFT = 0x0000
LVS_EX_FULLROWSELECT = 0x00000020
LVS_EX_DOUBLEBUFFER = 0x00010000
CB_ADDSTRING = 0x0143
CB_GETCOUNT = 0x0146
CB_GETCURSEL = 0x0147
CB_GETLBTEXT = 0x0148
CB_GETLBTEXTLEN = 0x0149
CB_RESETCONTENT = 0x014B
CB_SETCURSEL = 0x014E
CB_GETLBTEXT = 0x0148
CB_SETITEMHEIGHT = 0x0153
LB_ADDSTRING = 0x0180
LB_RESETCONTENT = 0x0184
LB_GETCURSEL = 0x0188
LB_SETCURSEL = 0x0186
LB_GETCOUNT = 0x018B
LB_GETSELCOUNT = 0x0190
LB_GETSELITEMS = 0x0191
LBS_EXTENDEDSEL = 0x0800
BM_GETCHECK = 0x00F0
BM_SETCHECK = 0x00F1
BST_CHECKED = 1
SW_HIDE = 0
SW_SHOW = 5
SW_MINIMIZE = 6
ICC_LISTVIEW_CLASSES = 0x00000001
SM_CXSCREEN = 0
SM_CYSCREEN = 1

# ------------------------------------------------------------------ 类型
WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wt.HWND, wt.UINT,
                             wt.WPARAM, wt.LPARAM)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wt.UINT), ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
        ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON),
        ("hCursor", ctypes.c_void_p), ("hbrBackground", wt.HBRUSH),
        ("lpszMenuName", wt.LPCWSTR), ("lpszClassName", wt.LPCWSTR),
    ]


class CREATESTRUCTW(ctypes.Structure):
    _fields_ = [
        ("lpCreateParams", ctypes.c_void_p), ("hInstance", wt.HINSTANCE),
        ("hMenu", wt.HMENU), ("hwndParent", wt.HWND),
        ("cy", ctypes.c_int), ("cx", ctypes.c_int),
        ("y", ctypes.c_int), ("x", ctypes.c_int),
        ("style", ctypes.c_long), ("lpszName", wt.LPCWSTR),
        ("lpszClass", wt.LPCWSTR), ("dwExStyle", wt.DWORD),
    ]


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class PAINTSTRUCT(ctypes.Structure):
    _fields_ = [
        ("hdc", wt.HDC), ("fErase", wt.BOOL), ("rcPaint", RECT),
        ("fRestore", wt.BOOL), ("fIncUpdate", wt.BOOL),
        ("rgbReserved", ctypes.c_byte * 32),
    ]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wt.HWND), ("message", wt.UINT), ("wParam", wt.WPARAM),
        ("lParam", wt.LPARAM), ("time", wt.DWORD),
        ("pt_x", ctypes.c_long), ("pt_y", ctypes.c_long),
    ]


class TRACKMOUSEEVENT(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("dwFlags", wt.DWORD),
                ("hwndTrack", wt.HWND), ("dwHoverTime", wt.DWORD)]


class LVCOLUMNW(ctypes.Structure):
    _fields_ = [
        ("mask", wt.UINT), ("fmt", ctypes.c_int), ("cx", ctypes.c_int),
        ("pszText", wt.LPWSTR), ("cchText", ctypes.c_int),
        ("iSubItem", ctypes.c_int), ("iImage", ctypes.c_int),
        ("iOrder", ctypes.c_int), ("cxMin", ctypes.c_int),
        ("cxDefault", ctypes.c_int), ("cxIdeal", ctypes.c_int),
    ]


class LVITEMW(ctypes.Structure):
    _fields_ = [
        ("mask", wt.UINT), ("iItem", ctypes.c_int),
        ("iSubItem", ctypes.c_int), ("state", wt.UINT),
        ("stateMask", wt.UINT), ("pszText", wt.LPWSTR),
        ("cchTextMax", ctypes.c_int), ("iImage", ctypes.c_int),
        ("lParam", wt.LPARAM), ("iIndent", ctypes.c_int),
        ("iGroupId", ctypes.c_int), ("cColumns", wt.UINT),
        ("puColumns", ctypes.c_void_p), ("piColFmt", ctypes.c_void_p),
        ("iGroup", ctypes.c_int),
    ]


class INITCOMMONCONTROLSEX(ctypes.Structure):
    _fields_ = [("dwSize", wt.DWORD), ("dwICC", wt.DWORD)]


# ------------------------------------------------------------------ 函数原型
user32.CreateWindowExW.restype = wt.HWND
user32.CreateWindowExW.argtypes = [
    wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wt.HWND, wt.HMENU, wt.HINSTANCE, ctypes.c_void_p]
user32.DefWindowProcW.restype = ctypes.c_ssize_t
user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.RegisterClassW.restype = wt.ATOM
user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
user32.SendMessageW.restype = ctypes.c_ssize_t
user32.SendMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.PostMessageW.restype = wt.BOOL
user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.SetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_ssize_t]
user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.GetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int]
user32.SetTimer.restype = ctypes.c_size_t
user32.SetTimer.argtypes = [wt.HWND, ctypes.c_size_t, wt.UINT, ctypes.c_void_p]
user32.KillTimer.argtypes = [wt.HWND, ctypes.c_size_t]
user32.GetMessageW.restype = ctypes.c_int
user32.GetMessageW.argtypes = [ctypes.POINTER(MSG), wt.HWND, wt.UINT, wt.UINT]
user32.DispatchMessageW.restype = ctypes.c_ssize_t
user32.DispatchMessageW.argtypes = [ctypes.POINTER(MSG)]
user32.TranslateMessage.argtypes = [ctypes.POINTER(MSG)]
user32.BeginPaint.restype = wt.HDC
user32.BeginPaint.argtypes = [wt.HWND, ctypes.POINTER(PAINTSTRUCT)]
user32.EndPaint.restype = wt.BOOL
user32.EndPaint.argtypes = [wt.HWND, ctypes.POINTER(PAINTSTRUCT)]
user32.GetClientRect.argtypes = [wt.HWND, ctypes.POINTER(RECT)]
user32.FillRect.restype = ctypes.c_int
user32.FillRect.argtypes = [wt.HDC, ctypes.POINTER(RECT), wt.HBRUSH]
user32.DrawTextW.restype = ctypes.c_int
user32.DrawTextW.argtypes = [wt.HDC, wt.LPCWSTR, ctypes.c_int,
                             ctypes.POINTER(RECT), wt.UINT]
user32.InvalidateRect.argtypes = [wt.HWND, ctypes.c_void_p, wt.BOOL]
user32.UpdateWindow.argtypes = [wt.HWND]
user32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
user32.IsWindow.restype = wt.BOOL
user32.IsWindow.argtypes = [wt.HWND]
user32.IsWindowVisible.restype = wt.BOOL
user32.IsWindowVisible.argtypes = [wt.HWND]
user32.GetForegroundWindow.restype = wt.HWND
user32.GetForegroundWindow.argtypes = []
user32.DestroyWindow.argtypes = [wt.HWND]
user32.EnableWindow.argtypes = [wt.HWND, wt.BOOL]
user32.SetForegroundWindow.argtypes = [wt.HWND]
user32.SetFocus.argtypes = [wt.HWND]
user32.SetCapture.restype = wt.HWND
user32.SetCapture.argtypes = [wt.HWND]
user32.ReleaseCapture.argtypes = []
user32.LoadCursorW.restype = ctypes.c_void_p
user32.LoadCursorW.argtypes = [wt.HINSTANCE, ctypes.c_void_p]
user32.SetCursor.argtypes = [ctypes.c_void_p]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.SetWindowTextW.restype = wt.BOOL
user32.SetWindowTextW.argtypes = [wt.HWND, wt.LPCWSTR]
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetParent.restype = wt.HWND
user32.GetParent.argtypes = [wt.HWND]
user32.GetCursorPos.argtypes = [ctypes.POINTER(wt.POINT)]
user32.ScreenToClient.argtypes = [wt.HWND, ctypes.POINTER(wt.POINT)]
user32.TrackMouseEvent.argtypes = [ctypes.POINTER(TRACKMOUSEEVENT)]
uxtheme.SetWindowTheme.argtypes = [wt.HWND, wt.LPCWSTR, wt.LPCWSTR]

# ---- DWM：Win11 才有的标题栏着色（Win10 会自动失败，不影响使用）
dwmapi = ctypes.windll.dwmapi
DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_BORDER_COLOR = 34
DWMWA_CAPTION_COLOR = 35
DWMWA_TEXT_COLOR = 36
DWMWA_WINDOW_CORNER_PREFERENCE = 33


def style_caption(hwnd, caption_hex, text_hex="#FFFFFF", border_hex=None):
    """把系统标题栏刷成和界面一致的深色（Win11）；其他系统静默跳过。"""
    try:
        dark = ctypes.c_int(1)
        dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE,
            ctypes.byref(dark), ctypes.sizeof(dark))
        col = ctypes.c_uint(T.rgb(caption_hex))
        dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_CAPTION_COLOR, ctypes.byref(col), ctypes.sizeof(col))
        tc = ctypes.c_uint(T.rgb(text_hex))
        dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_TEXT_COLOR, ctypes.byref(tc), ctypes.sizeof(tc))
        if border_hex:
            bc = ctypes.c_uint(T.rgb(border_hex))
            dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_BORDER_COLOR, ctypes.byref(bc),
                ctypes.sizeof(bc))
        corner = ctypes.c_int(2)      # DWMWCP_ROUND
        dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_WINDOW_CORNER_PREFERENCE,
            ctypes.byref(corner), ctypes.sizeof(corner))
        # 强制重算非客户区并立即重绘标题栏，否则改色要等窗口被激活才生效
        user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0,
                            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER
                            | SWP_NOACTIVATE | SWP_FRAMECHANGED)
        user32.RedrawWindow(hwnd, None, 0, RDW_FRAME | RDW_INVALIDATE
                            | RDW_UPDATENOW | RDW_ALLCHILDREN)
    except Exception:
        pass

gdi32.CreateSolidBrush.restype = wt.HBRUSH
gdi32.CreateSolidBrush.argtypes = [wt.COLORREF]
gdi32.CreatePen.restype = wt.HPEN
gdi32.CreatePen.argtypes = [ctypes.c_int, ctypes.c_int, wt.COLORREF]
gdi32.CreateFontW.restype = wt.HFONT
gdi32.CreateFontW.argtypes = [
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wt.DWORD, wt.DWORD, wt.DWORD, wt.DWORD, wt.DWORD, wt.DWORD,
    wt.DWORD, wt.DWORD, wt.LPCWSTR]
gdi32.SelectObject.restype = ctypes.c_void_p
gdi32.SelectObject.argtypes = [wt.HDC, ctypes.c_void_p]
gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
gdi32.SetTextColor.argtypes = [wt.HDC, wt.COLORREF]
gdi32.SetBkColor.argtypes = [wt.HDC, wt.COLORREF]
gdi32.SetBkMode.argtypes = [wt.HDC, ctypes.c_int]
gdi32.RoundRect.restype = wt.BOOL
gdi32.RoundRect.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int,
                            ctypes.c_int, ctypes.c_int, ctypes.c_int,
                            ctypes.c_int]
gdi32.Rectangle.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int,
                            ctypes.c_int, ctypes.c_int]
gdi32.Ellipse.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int,
                          ctypes.c_int, ctypes.c_int]
gdi32.MoveToEx.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int,
                           ctypes.c_void_p]
gdi32.LineTo.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int]
gdi32.GetStockObject.restype = ctypes.c_void_p
gdi32.GetStockObject.argtypes = [ctypes.c_int]
gdi32.GetTextExtentPoint32W.argtypes = [
    wt.HDC, wt.LPCWSTR, ctypes.c_int, ctypes.POINTER(wt.SIZE)]
gdi32.SetTextAlign.argtypes = [wt.HDC, wt.UINT]
gdi32.CreateCompatibleDC.restype = wt.HDC
gdi32.CreateCompatibleDC.argtypes = [wt.HDC]
gdi32.CreateCompatibleBitmap.restype = wt.HBITMAP
gdi32.CreateCompatibleBitmap.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int]
gdi32.BitBlt.restype = wt.BOOL
gdi32.BitBlt.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                         ctypes.c_int, wt.HDC, ctypes.c_int, ctypes.c_int,
                         wt.DWORD]
gdi32.DeleteDC.argtypes = [wt.HDC]

kernel32.GetModuleHandleW.restype = wt.HINSTANCE
kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
kernel32.GetTickCount64.restype = ctypes.c_ulonglong

comctl32.InitCommonControlsEx.argtypes = [ctypes.POINTER(INITCOMMONCONTROLSEX)]


def _lp(struct_or_buf):
    """把结构体/缓冲区地址转成可塞进 LPARAM 的整数。"""
    return ctypes.cast(struct_or_buf, ctypes.c_void_p).value or 0


def _loword(v):
    return int(v) & 0xFFFF


def _hiword(v):
    return (int(v) >> 16) & 0xFFFF


def message_box(text, title="屏效助手", flags=0x40):
    user32.MessageBoxW(0, text, title, flags)


# ------------------------------------------------------------------ GDI 资源缓存
_brushes = {}
_pens = {}
_fonts = {}
_white = None


def brush(color):
    key = T.rgb(color)
    b = _brushes.get(key)
    if b is None:
        b = gdi32.CreateSolidBrush(key)
        _brushes[key] = b
    return b


def pen(color, width=1):
    key = (T.rgb(color), width)
    p = _pens.get(key)
    if p is None:
        p = gdi32.CreatePen(0, width, key[0])
        _pens[key] = p
    return p


def font(size=None, bold=False, family=None):
    size = T.F_BODY if size is None else size
    key = (size, bold, family or T.FONT_FAMILY)
    f = _fonts.get(key)
    if f is None:
        f = gdi32.CreateFontW(
            size, 0, 0, 0, 700 if bold else 400, 0, 0, 0, 1, 0, 0, 5, 0,
            key[2])
        _fonts[key] = f
    return f


# ------------------------------------------------------------------ 绘制原语
def fill_rect(hdc, x, y, w, h, color):
    r = RECT(x, y, x + w, y + h)
    user32.FillRect(hdc, ctypes.byref(r), brush(color))


def round_rect(hdc, x, y, w, h, radius=8, fill=None, border=None, bw=1):
    if fill:
        gdi32.SelectObject(hdc, brush(fill))
    else:
        gdi32.SelectObject(hdc, gdi32.GetStockObject(NULL_BRUSH))
    if border:
        gdi32.SelectObject(hdc, pen(border, bw))
    else:
        gdi32.SelectObject(hdc, pen(fill or "#FFFFFF", 1))
    gdi32.RoundRect(hdc, x, y, x + w, y + h, radius * 2, radius * 2)


def hline(hdc, x1, y, x2, color):
    gdi32.SelectObject(hdc, pen(color, 1))
    gdi32.MoveToEx(hdc, x1, y, None)
    gdi32.LineTo(hdc, x2, y)


def vline(hdc, x, y1, y2, color):
    gdi32.SelectObject(hdc, pen(color, 1))
    gdi32.MoveToEx(hdc, x, y1, None)
    gdi32.LineTo(hdc, x, y2)


def dot(hdc, cx, cy, r, color):
    gdi32.SelectObject(hdc, brush(color))
    gdi32.SelectObject(hdc, gdi32.GetStockObject(NULL_BRUSH))
    gdi32.Ellipse(hdc, cx - r, cy - r, cx + r, cy + r)


_ALIGN = {"left": DT_LEFT, "center": DT_CENTER, "right": DT_RIGHT}
_VALIGN = {"top": DT_SINGLELINE | 0x0000, "center": DT_VCENTER | DT_SINGLELINE}


def text(hdc, s, x, y, w, h=None, color=None, size=None, bold=False,
         align="left", valign="center", wrap=False, ellipsis=True,
         family=None):
    """在 (x, y, w, h) 区域里绘制文字（h 省略时按字号估算）。"""
    if s is None:
        return
    if h is None:
        h = abs(size or T.F_BODY) + 6
    gdi32.SelectObject(hdc, font(size, bold, family))
    gdi32.SetTextColor(hdc, T.rgb(color or T.TEXT))
    gdi32.SetBkMode(hdc, TRANSPARENT)
    flags = _ALIGN.get(align, DT_LEFT) | DT_NOPREFIX
    if wrap:
        flags |= DT_WORDBREAK
    else:
        flags |= DT_SINGLELINE | DT_VCENTER
    if ellipsis:
        flags |= DT_END_ELLIPSIS
    r = RECT(int(x), int(y), int(x + w), int(y + h))
    user32.DrawTextW(hdc, str(s), -1, ctypes.byref(r), flags)


def text_width(hdc, s, size=None, bold=False, family=None):
    gdi32.SelectObject(hdc, font(size, bold, family))
    sz = wt.SIZE()
    gdi32.GetTextExtentPoint32W(hdc, str(s), len(str(s)), ctypes.byref(sz))
    return sz.cx


def pill(hdc, x, y, label, color, size=T.F_TINY, pad=8, height=20):
    """胶囊小标签，返回占用的宽度。"""
    fg = color
    bg = T.lighter(color, 0.88)
    w = text_width(hdc, label, size) + pad * 2
    round_rect(hdc, x, y, w, height, height // 2, fill=bg)
    text(hdc, label, x, y, w, height, color=fg, size=size, align="center")
    return w


# ------------------------------------------------------------------ 窗口基础设施
_REG = {}
_CLASSES = {}
_CLASS_NAME = "ScreenModeWindow"


def _dispatch(hwnd, msg, wp, lp):
    if msg == WM_NCCREATE:
        cs = ctypes.cast(lp, ctypes.POINTER(CREATESTRUCTW)).contents
        oid = int(cs.lpCreateParams or 0)
        user32.SetWindowLongPtrW(hwnd, GWLP_USERDATA, oid)
        obj = _REG.get(oid)
        if obj is not None:
            obj.hwnd = hwnd
    oid = user32.GetWindowLongPtrW(hwnd, GWLP_USERDATA)
    oid &= 0xFFFFFFFFFFFFFFFF          # id() 是 48 位地址，别截断
    obj = _REG.get(oid)
    if obj is not None:
        try:
            return obj.handle(msg, wp, lp)
        except Exception as exc:  # 绝不让异常穿回 Win32
            try:
                obj.on_error(exc)
            except Exception:
                pass
    return user32.DefWindowProcW(hwnd, msg, wp, lp)


def _ensure_class():
    if _CLASS_NAME in _CLASSES:
        return
    icc = INITCOMMONCONTROLSEX(ctypes.sizeof(INITCOMMONCONTROLSEX),
                              ICC_LISTVIEW_CLASSES)
    comctl32.InitCommonControlsEx(ctypes.byref(icc))
    wc = WNDCLASSW()
    proc = WNDPROC(_dispatch)
    wc.style = 0x0002 | 0x0001          # CS_HREDRAW | CS_VREDRAW
    wc.lpfnWndProc = proc
    wc.cbClsExtra = 0
    wc.cbWndExtra = 0
    wc.hInstance = kernel32.GetModuleHandleW(None)
    wc.hIcon = 0
    wc.hCursor = user32.LoadCursorW(None, ctypes.c_void_p(IDC_ARROW))
    wc.hbrBackground = 0
    wc.lpszMenuName = None
    wc.lpszClassName = _CLASS_NAME
    user32.RegisterClassW(ctypes.byref(wc))
    _CLASSES[_CLASS_NAME] = proc


def create_native(parent, cls, text, style, x, y, w, h, cid=0, exstyle=0,
                  font_size=None, flat=True):
    hwnd = user32.CreateWindowExW(
        exstyle, cls, text if text is not None else "", style,
        x, y, w, h, parent, cid, kernel32.GetModuleHandleW(None), None)
    if hwnd:
        if font_size is not None:
            user32.SendMessageW(hwnd, WM_SETFONT, font(font_size), 1)
        if flat and cls.lower() in ("edit", "combobox"):
            try:
                uxtheme.SetWindowTheme(hwnd, "", "")
            except Exception:
                pass
    return hwnd


class Button:
    """自绘按钮（画在父窗口上，不是原生控件）。"""

    def __init__(self, bid, label, x, y, w, h, kind="secondary",
                 on_click=None, enabled=True, radius=T.BTN_RADIUS,
                 size=T.F_BODY, bold=False, tag=None, active=False,
                 bg=None, hover_bg=None):
        self.id = bid
        self.label = label
        self.x, self.y, self.w, self.h = x, y, w, h
        self.kind = kind
        self.on_click = on_click
        self.enabled = enabled
        self.radius = radius
        self.size = size
        self.bold = bold
        self.tag = tag
        self.active = active
        self.bg = bg
        self.hover_bg = hover_bg
        self.hover = False
        self.pressed = False

    def contains(self, px, py):
        return (self.x <= px < self.x + self.w
                and self.y <= py < self.y + self.h)

    def paint(self, hdc, bg_color):
        bg_color = self.bg or bg_color
        if self.kind == "close":
            base = bg_color
            fg = "#FFFFFF"
            if self.hover:
                base = self.hover_bg or T.mix(bg_color, "#FFFFFF", 0.22)
            if self.pressed:
                base = T.mix(base, "#000000", 0.12)
            round_rect(hdc, self.x, self.y, self.w, self.h, self.radius,
                       fill=base)
            text(hdc, self.label, self.x, self.y, self.w, self.h, color=fg,
                 size=self.size, align="center")
            return

        if self.kind == "nav":
            if self.active:
                base, fg, border = T.SIDEBAR_ITEM, T.SIDEBAR_TEXT_ACTIVE, None
            elif self.hover:
                base, fg, border = T.SIDEBAR_ITEM_HOVER, "#D5DAE4", None
            else:
                base, fg, border = bg_color, T.SIDEBAR_TEXT, None
            round_rect(hdc, self.x, self.y, self.w, self.h, 8, fill=base,
                       border=border)
            if self.active:
                round_rect(hdc, self.x + 8, self.y + self.h // 2 - 8, 3, 16,
                           2, fill=T.ACCENT)
            text(hdc, self.label, self.x + 26, self.y, self.w - 36, self.h,
                 color=fg, size=self.size, bold=self.active)
            return

        if self.kind == "primary":
            base, fg, border = T.ACCENT, "#FFFFFF", None
            if self.hover:
                base = T.mix(T.ACCENT, "#FFFFFF", 0.12)
            if self.pressed:
                base = T.ACCENT_DARK
        elif self.kind == "soft":
            base, fg, border = T.ACCENT_LIGHT, T.ACCENT, None
            if self.hover:
                base = T.mix(T.ACCENT_LIGHT, T.ACCENT, 0.12)
            if self.pressed:
                base = T.mix(T.ACCENT_LIGHT, T.ACCENT, 0.22)
        elif self.kind == "danger":
            base, fg, border = "#FFFFFF", T.DANGER, "#F3C6C7"
            if self.hover:
                base = T.DANGER_LIGHT
            if self.pressed:
                base = T.mix(T.DANGER_LIGHT, T.DANGER, 0.15)
        elif self.kind == "ghost":
            base, fg, border = bg_color, T.TEXT_SUB, None
            if self.hover:
                base = T.mix(bg_color, "#000000", 0.05)
            if self.pressed:
                base = T.mix(bg_color, "#000000", 0.10)
        else:  # secondary
            base, fg, border = "#FFFFFF", T.TEXT, T.FIELD_BORDER
            if self.hover:
                base = "#F6F8FC"
            if self.pressed:
                base = "#EDF1F7"
        if not self.enabled:
            base = T.mix(base if base.startswith("#") else "#FFFFFF",
                         "#F5F6F9", 0.5)
            fg = T.TEXT_FAINT
        round_rect(hdc, self.x, self.y, self.w, self.h, self.radius,
                   fill=base, border=border)
        text(hdc, self.label, self.x, self.y, self.w, self.h, color=fg,
             size=self.size, bold=self.bold, align="center")


class Win:
    """所有自绘窗口的基类。子类实现 paint()。"""

    bg = "#FFFFFF"

    def __init__(self):
        self.hwnd = None
        self.alive = True
        self.buttons = []
        self._hover_btn = None
        self._pressed_btn = None
        self._tracking = False
        self._hand_cursor = None
        self._arrow_cursor = None
        _ensure_class()

    # ---------------- 创建 ----------------
    def create(self, title, x, y, w, h, parent=None, style=0, exstyle=0):
        self._oid = id(self)
        _REG[self._oid] = self
        style = style or (WS_POPUP | WS_CAPTION | WS_SYSMENU | WS_VISIBLE)
        self.hwnd = user32.CreateWindowExW(
            exstyle, _CLASS_NAME, title, style, x, y, w, h,
            parent or 0, 0, kernel32.GetModuleHandleW(None),
            ctypes.c_void_p(self._oid))
        return self.hwnd

    def add_button(self, bid, label, x, y, w, h, **kw):
        b = Button(bid, label, x, y, w, h, **kw)
        self.buttons.append(b)
        return b

    def find_button(self, bid):
        for b in self.buttons:
            if b.id == bid:
                return b
        return None

    def invalidate(self):
        if self.hwnd:
            user32.InvalidateRect(self.hwnd, None, False)

    def client_rect(self):
        r = RECT()
        user32.GetClientRect(self.hwnd, ctypes.byref(r))
        return r.right - r.left, r.bottom - r.top

    # ---------------- 消息 ----------------
    def handle(self, msg, wp, lp):
        if msg == WM_CREATE:
            if DEBUG:
                print("[create]", type(self).__name__, "hwnd=", self.hwnd,
                      "client=", self.client_rect(), flush=True)
            self.on_create()
            return 0
        if msg == WM_ERASEBKGND:
            w, h = self.client_rect()
            fill_rect(wt.HDC(wp), 0, 0, w, h, self.bg)
            return 1
        if msg == WM_PAINT:
            ps = PAINTSTRUCT()
            hdc = user32.BeginPaint(self.hwnd, ctypes.byref(ps))
            w, h = self.client_rect()
            # 双缓冲：先画到内存 DC，再一次性贴上去，彻底避免闪烁
            mem = gdi32.CreateCompatibleDC(hdc)
            bmp = gdi32.CreateCompatibleBitmap(hdc, max(1, w), max(1, h))
            old = gdi32.SelectObject(mem, bmp)
            try:
                fill_rect(mem, 0, 0, w, h, self.bg)   # 内存位图先铺底色
                self.paint(mem, w, h)
                self.paint_buttons(mem)
                gdi32.BitBlt(hdc, 0, 0, w, h, mem, 0, 0, SRCCOPY)
            finally:
                gdi32.SelectObject(mem, old)
                gdi32.DeleteObject(bmp)
                gdi32.DeleteDC(mem)
                user32.EndPaint(self.hwnd, ctypes.byref(ps))
            return 0
        if msg == WM_CTLCOLORSTATIC or msg == WM_CTLCOLORBTN:
            hdc = wt.HDC(wp)
            gdi32.SetBkMode(hdc, TRANSPARENT)
            gdi32.SetTextColor(hdc, T.rgb(T.TEXT))
            gdi32.SetBkColor(hdc, T.rgb(T.CARD_BG))
            return brush(T.CARD_BG)
        if msg == WM_CTLCOLOREDIT or msg == WM_CTLCOLORLISTBOX:
            hdc = wt.HDC(wp)
            gdi32.SetTextColor(hdc, T.rgb(T.TEXT))
            gdi32.SetBkColor(hdc, T.rgb(T.FIELD_BG))
            return brush(T.FIELD_BG)
        if msg == WM_NCHITTEST:
            dh = getattr(self, "drag_height", 0)
            if dh:
                pt = wt.POINT(self._lo_x(lp), self._lo_y(lp))
                user32.ScreenToClient(self.hwnd, ctypes.byref(pt))
                if 0 <= pt.y < dh and self._hit_at(pt.x, pt.y) is None:
                    return HTCAPTION   # 没有系统标题栏也能拖动窗口
            return HTCLIENT            # 关键：必须返回 1，不能返回 0
        if msg == WM_SETCURSOR:
            b = self._hit_at_cursor()
            if b is not None and b.enabled:
                if self._hand_cursor is None:
                    self._hand_cursor = user32.LoadCursorW(
                        None, ctypes.c_void_p(IDC_HAND))
                user32.SetCursor(ctypes.c_void_p(self._hand_cursor))
                return 1
            return user32.DefWindowProcW(self.hwnd, msg, wp, lp)
        if msg == WM_MOUSEMOVE:
            self._on_mouse_move(self._lo_x(lp), self._lo_y(lp))
            return 0
        if msg == WM_MOUSELEAVE:
            self._tracking = False
            self._set_hover(None)
            return 0
        if msg == WM_LBUTTONDOWN:
            b = self._hit_at(self._lo_x(lp), self._lo_y(lp))
            if b is not None and b.enabled:
                self._pressed_btn = b
                b.pressed = True
                user32.SetCapture(self.hwnd)
                self.invalidate()
            return 0
        if msg == WM_LBUTTONUP:
            b = self._pressed_btn
            self._pressed_btn = None
            if b is not None:
                b.pressed = False
                hit = self._hit_at(self._lo_x(lp), self._lo_y(lp))
                user32.ReleaseCapture()
                self.invalidate()
                if hit is b and b.enabled and b.on_click:
                    b.on_click(b)
            return 0
        if msg == WM_TIMER:
            return self.on_timer(wp)
        if msg == WM_KEYDOWN:
            if wp == 0x1B and self.on_escape():
                return 0
            if wp == 0x0D and self.on_enter():
                return 0
            return 0
        if msg == WM_CLOSE:
            self.on_close()
            return 0
        if msg == WM_DESTROY:
            self.alive = False
            _REG.pop(getattr(self, "_oid", -1), None)
            self.on_destroy()
            return 0
        return user32.DefWindowProcW(self.hwnd, msg, wp, lp)

    # ---------------- 虚方法 ----------------
    def on_create(self):
        pass

    def paint(self, hdc, w, h):
        pass

    def paint_buttons(self, hdc):
        for b in self.buttons:
            b.paint(hdc, self.bg)

    def on_escape(self):
        return False

    def on_enter(self):
        return False

    def on_timer(self, tid):
        return 0

    def on_close(self):
        self.close()

    def on_destroy(self):
        self.alive = False

    def on_error(self, exc):
        import traceback
        traceback.print_exc()

    # ---------------- 鼠标 ----------------
    @staticmethod
    def _lo_x(lp):
        v = lp & 0xFFFF
        return v - 0x10000 if v > 0x7FFF else v

    @staticmethod
    def _lo_y(lp):
        v = (lp >> 16) & 0xFFFF
        return v - 0x10000 if v > 0x7FFF else v

    def _hit_at(self, px, py):
        for b in reversed(self.buttons):
            if b.contains(px, py):
                return b
        return None

    def _hit_at_cursor(self):
        pt = wt.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        user32.ScreenToClient(self.hwnd, ctypes.byref(pt))
        return self._hit_at(pt.x, pt.y)

    def _on_mouse_move(self, x, y):
        if not self._tracking:
            tme = TRACKMOUSEEVENT(ctypes.sizeof(TRACKMOUSEEVENT), TME_LEAVE,
                                  self.hwnd, 0)
            user32.TrackMouseEvent(ctypes.byref(tme))
            self._tracking = True
        self._set_hover(self._hit_at(x, y))

    def _set_hover(self, b):
        if self._hover_btn is b:
            return
        if self._hover_btn is not None:
            self._hover_btn.hover = False
        self._hover_btn = b
        if b is not None:
            b.hover = True
        self.invalidate()

    def close(self):
        if self.hwnd:
            user32.DestroyWindow(self.hwnd)

    def show(self):
        if self.hwnd:
            user32.ShowWindow(self.hwnd, SW_SHOW)
            user32.SetForegroundWindow(self.hwnd)


# ------------------------------------------------------------------ 原生控件封装
class ListView:
    """SysListView32 报表模式封装。"""

    def __init__(self, parent, x, y, w, h, columns, on_select=None,
                 font_size=T.F_SMALL, row_height=24):
        style = (WS_CHILD | WS_VISIBLE | WS_BORDER | LVS_REPORT
                 | LVS_SINGLESEL | LVS_SHOWSELALWAYS)
        self.hwnd = create_native(parent, "SysListView32", "", style, x, y,
                                  w, h, font_size=font_size)
        self.columns = list(columns)
        self.items = []
        self.on_select = on_select
        if self.hwnd:
            user32.SendMessageW(
                self.hwnd, LVM_SETEXTENDEDLISTVIEWSTYLE,
                LVS_EX_FULLROWSELECT | LVS_EX_DOUBLEBUFFER,
                LVS_EX_FULLROWSELECT | LVS_EX_DOUBLEBUFFER)
            for i, (title, width) in enumerate(self.columns):
                col = LVCOLUMNW()
                col.mask = LVCF_FMT | LVCF_WIDTH | LVCF_TEXT | LVCF_SUBITEM
                col.fmt = LVCFMT_LEFT
                col.cx = width
                col.pszText = ctypes.cast(ctypes.c_wchar_p(title),
                                          wt.LPWSTR)
                col.cchText = len(title)
                col.iSubItem = i
                user32.SendMessageW(self.hwnd, LVM_INSERTCOLUMNW, i,
                                    _lp(ctypes.byref(col)))

    def clear(self):
        if self.hwnd:
            user32.SendMessageW(self.hwnd, LVM_DELETEALLITEMS, 0, 0)
        self.items = []

    def add(self, values, data=None):
        idx = len(self.items)
        if not self.hwnd:
            return idx
        first = LVITEMW()
        first.mask = LVIF_TEXT
        first.iItem = idx
        first.iSubItem = 0
        buf0 = ctypes.create_unicode_buffer(str(values[0]))
        first.pszText = ctypes.cast(buf0, wt.LPWSTR)
        user32.SendMessageW(self.hwnd, LVM_INSERTITEMW, 0,
                            _lp(ctypes.byref(first)))
        for i in range(1, len(values)):
            sub = LVITEMW()
            sub.mask = LVIF_TEXT
            sub.iItem = idx
            sub.iSubItem = i
            buf = ctypes.create_unicode_buffer(str(values[i]))
            sub.pszText = ctypes.cast(buf, wt.LPWSTR)
            user32.SendMessageW(self.hwnd, LVM_SETITEMTEXTW, idx,
                                _lp(ctypes.byref(sub)))
        self.items.append(data if data is not None else values)
        return idx

    def selected_index(self):
        if not self.hwnd:
            return -1
        return int(user32.SendMessageW(self.hwnd, LVM_GETNEXTITEM, -1,
                                       LVNI_SELECTED))

    def selected(self):
        i = self.selected_index()
        if 0 <= i < len(self.items):
            return self.items[i]
        return None

    def select(self, idx):
        if self.hwnd and 0 <= idx < len(self.items):
            item = LVITEMW()
            item.state = 0x0002  # LVIS_SELECTED
            item.stateMask = 0x0002
            user32.SendMessageW(self.hwnd, LVM_SETITEMSTATE, idx,
                                _lp(ctypes.byref(item)))
            user32.SendMessageW(self.hwnd, LVM_FIRST + 19, idx, 0)  # ENSUREVISIBLE

    def show(self, visible=True):
        if self.hwnd:
            user32.ShowWindow(self.hwnd, SW_SHOW if visible else SW_HIDE)


def _send_str(hwnd, msg, s, wp=0):
    """给控件发字符串消息。缓冲区必须在调用期间保持存活，不能写成临时变量。"""
    buf = ctypes.create_unicode_buffer(str(s))
    return user32.SendMessageW(hwnd, msg, wp, _lp(buf))


class ListBox:
    """原生 ListBox 封装（支持多选）。"""

    def __init__(self, parent, x, y, w, h, multi=False,
                 font_size=T.F_SMALL, on_select=None, cid=0):
        style = (WS_CHILD | WS_VISIBLE | WS_BORDER | WS_VSCROLL
                 | LBS_NOTIFY | LBS_NOINTEGRALHEIGHT)
        if multi:
            style |= LBS_EXTENDEDSEL
        self.hwnd = create_native(parent, "LISTBOX", "", style, x, y, w, h,
                                  cid=cid, font_size=font_size)
        self.items = []
        self.on_select = on_select

    def clear(self):
        if self.hwnd:
            user32.SendMessageW(self.hwnd, LB_RESETCONTENT, 0, 0)
        self.items = []

    def add(self, label, data=None):
        idx = len(self.items)
        if self.hwnd:
            _send_str(self.hwnd, LB_ADDSTRING, label)
        self.items.append(data if data is not None else label)
        return idx

    def selected_index(self):
        if not self.hwnd:
            return -1
        return int(user32.SendMessageW(self.hwnd, LB_GETCURSEL, 0, 0))

    def selected(self):
        i = self.selected_index()
        return self.items[i] if 0 <= i < len(self.items) else None

    def selected_indices(self):
        if not self.hwnd:
            return []
        n = int(user32.SendMessageW(self.hwnd, LB_GETSELCOUNT, 0, 0))
        if n <= 0:
            return []
        buf = (ctypes.c_int * n)()
        got = int(user32.SendMessageW(self.hwnd, LB_GETSELITEMS, n,
                                      _lp(buf)))
        return [buf[i] for i in range(max(0, got))]

    def select(self, idx):
        if self.hwnd and 0 <= idx < len(self.items):
            user32.SendMessageW(self.hwnd, LB_SETCURSEL, idx, 0)


def set_combo_items(hwnd, items, selected=None):
    if not hwnd:
        return
    user32.SendMessageW(hwnd, CB_RESETCONTENT, 0, 0)  # 清空原有条目
    for it in items:
        _send_str(hwnd, CB_ADDSTRING, it)
    user32.SendMessageW(hwnd, CB_SETITEMHEIGHT, 0, 22)
    user32.SendMessageW(hwnd, CB_SETITEMHEIGHT, -1, 22)
    if selected is not None and selected in items:
        user32.SendMessageW(hwnd, CB_SETCURSEL, items.index(selected), 0)
    elif items:
        user32.SendMessageW(hwnd, CB_SETCURSEL, 0, 0)


def combo_selection(hwnd, items):
    if not hwnd:
        return None
    idx = int(user32.SendMessageW(hwnd, CB_GETCURSEL, 0, 0))
    if 0 <= idx < len(items):
        return items[idx]
    return None


def get_text(hwnd):
    if not hwnd:
        return ""
    n = int(user32.SendMessageW(hwnd, WM_GETTEXTLENGTH, 0, 0))
    buf = ctypes.create_unicode_buffer(n + 2)
    user32.SendMessageW(hwnd, WM_GETTEXT, n + 1, _lp(buf))
    return buf.value


def set_text(hwnd, s):
    if hwnd:
        user32.SetWindowTextW(hwnd, s or "")


def get_check(hwnd):
    return int(user32.SendMessageW(hwnd, BM_GETCHECK, 0, 0)) == BST_CHECKED


def set_check(hwnd, value):
    if hwnd:
        user32.SendMessageW(hwnd, BM_SETCHECK,
                            BST_CHECKED if value else 0, 0)


# ------------------------------------------------------------------ 模态对话框
class Dialog(Win):
    """模态对话框：在调用线程里跑一个嵌套消息循环，退出后返回结果。"""

    win_w, win_h = 480, 300
    resizable = False

    def __init__(self, parent=None, title="", width=None, height=None):
        super().__init__()
        self.parent = parent
        self.title = title
        self.win_w = width or self.win_w
        self.win_h = height or self.win_h
        self.result = None
        self.bg = "#FFFFFF"
        self.drag_height = self.header_h
        self.topmost = False

    def run(self):
        pw, ph = user32.GetSystemMetrics(SM_CXSCREEN), \
            user32.GetSystemMetrics(SM_CYSCREEN)
        x = (pw - self.win_w) // 2
        y = (ph - self.win_h) // 3
        exstyle = WS_EX_TOOLWINDOW
        if self.topmost:
            exstyle |= WS_EX_TOPMOST
        self.create(self.title, x, y, self.win_w, self.win_h,
                    parent=self.parent,
                    style=WS_POPUP | WS_VISIBLE, exstyle=exstyle)
        if not self.hwnd:
            return None
        w, h = self.client_rect()
        self.add_button(9001, "×", w - 40, 12, 28, 28, kind="close",
                        bg=T.ACCENT, size=T.F_H2, radius=8,
                        on_click=lambda b: self.on_escape())
        self.invalidate()
        if self.parent:
            user32.EnableWindow(self.parent, False)
        self.alive = True
        msg = MSG()
        while True:
            r = user32.GetMessageW(ctypes.byref(msg), 0, 0, 0)
            if r <= 0:
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
            if not self.alive or not user32.IsWindow(self.hwnd):
                break
        if self.parent:
            user32.EnableWindow(self.parent, True)
            # 父窗口本来就是隐藏的（用户把主界面收到托盘了），就别把它顶出来
            if user32.IsWindowVisible(self.parent):
                user32.SetForegroundWindow(self.parent)
        return self.result

    def ok(self, value=True):
        self.result = value
        user32.DestroyWindow(self.hwnd)

    def on_escape(self):
        self.result = None
        user32.DestroyWindow(self.hwnd)
        return True

    def on_enter(self):
        if self.has_default_action():
            self.default_action()
            return True
        return False

    def has_default_action(self):
        return False

    def default_action(self):
        pass

    # 顶部标题带
    header_h = 62

    def paint(self, hdc, w, h):
        fill_rect(hdc, 0, 0, w, self.header_h, T.ACCENT)
        text(hdc, self.title, 24, 0, w - 48, self.header_h, color="#FFFFFF",
             size=T.F_H2, bold=True)
        self.paint_body(hdc, w, h)

    def paint_body(self, hdc, w, h):
        pass


# ------------------------------------------------------------------ 常用小工具
def field(hdc, x, y, w, h, radius=6):
    """画一个输入框底（原生 EDIT 放在上面）。"""
    round_rect(hdc, x, y, w, h, radius, fill=T.FIELD_BG,
               border=T.FIELD_BORDER)


def card(hdc, x, y, w, h, radius=T.RADIUS):
    round_rect(hdc, x, y, w, h, radius, fill=T.CARD_BG,
               border=T.CARD_BORDER)


def section_title(hdc, s, x, y, hint=None, width=None):
    text(hdc, s, x, y, width or 300, 22, color=T.TEXT, size=T.F_H2,
         bold=True)
    if hint:
        tw = text_width(hdc, s, T.F_H2, True)
        text(hdc, hint, x + tw + 10, y, 400, 22, color=T.TEXT_FAINT,
             size=T.F_SMALL)
