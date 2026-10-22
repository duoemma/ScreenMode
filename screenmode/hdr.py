# -*- coding: utf-8 -*-
r"""查每台显示器的高级颜色状态（HDR / 广色域 / 色深）。

为什么需要单独查
----------------
开启 HDR 后，Windows 把显示输出切成 scRGB / HDR10 管线，**驱动接管 gamma
查找表**。此时 `SetDeviceGammaRamp` 依然返回 True（API 层面没失败），
但画面一个像素都不会变 —— 这是 Gamma 通道最容易踩的坑：
程序自以为切了模式，用户看到的却什么都没发生。

本机实测：主屏 HDR 已开启（10bit + 广色域）；副屏支持 HDR 但没开，
8bit。所以副屏上 Gamma 通道是能用的 —— 关键看 `hdr_enabled` 这一位，
`hdr_supported` 为 True 不影响。

用了哪些 API
------------
`QueryDisplayConfig`（不是 GetDisplayConfig —— Win32 里根本没这个函数，
只有 `GetDisplayConfigBufferSizes` / `QueryDisplayConfig` 这一对）。

流程：
  1. QueryDisplayConfig 拿所有 path（source ↔ target 的配对）
  2. 对每个 source 查 `DISPLAYCONFIG_DEVICE_INFO_GET_SOURCE_NAME`(type 1)
     -> viewGdiDeviceName 就是 "\\\\.\\DISPLAY5"，能和 gamma/ddc 的
        device 字段直接对上。**不要靠数组下标猜顺序**，多屏热插拔后顺序会变。
  3. 对每个 target 查 `GET_ADVANCED_COLOR_INFO`(type 9) 拿 HDR 位。

返回 rc=87 的那台按「纯 SDR」处理 —— 这是安全的：既然它连状态都问不出来，
就不可能出现「报不了但确实开着 HDR」的情况（HDR 是驱动侧状态，一定会报）。

⚠️ 一个曾经踩过的坑：`DISPLAYCONFIG_PATH_TARGET_INFO.refreshRate` 是
`DISPLAYCONFIG_RATIONAL`（两个 UINT，8 字节），不是单个 UINT。写成 UINT
会让整个结构体从 52 字节错成 48 字节，`DISPLAYCONFIG_PATH_INFO` 的数组步长
跟着从 72 错成 68 —— **第一块屏看起来完全正常，第二块屏读到的全是垃圾**，
表现出来就是「副屏 rc=87」。见 _tools/probe_hdr.py 的历史版本。
"""
import ctypes
from ctypes import wintypes as wt

user32 = ctypes.windll.user32

# 枚举显示路径时用的标志：只要当前激活的
QDC_ONLY_ACTIVE_PATHS = 0x2

TYPE_GET_SOURCE_NAME = 1
TYPE_GET_TARGET_NAME = 2
TYPE_GET_ADVANCED_COLOR_INFO = 9

# ADVANCED_COLOR_INFO.value 的位定义
#
# ⚠️ 第 2 位叫 advancedColorEnabled，中文对应「高级颜色已启用」——
# **它不是"HDR 已开启"**：Windows 11 的「自动管理颜色」(ACM) 和广色域模式
# 同样会把这一位置起来。光看这一位分不出是 HDR 还是 ACM
# （真要区分得用 DISPLAYCONFIG_GET_ADVANCED_COLOR_INFO_2，但本机
# Win11 26200 上这个 type 返回 87，用不了）。
#
# 所以对外一律说「高级颜色」，只在 wideColorEnforced 没起来时才敢说 HDR。
AC_HDR_SUPPORTED = 0x1
AC_HDR_ENABLED = 0x2
AC_WIDE_COLOR_ENFORCED = 0x4
AC_FORCE_DISABLED = 0x8


class LUID(ctypes.Structure):
    _fields_ = [("LowPart", wt.DWORD), ("HighPart", wt.LONG)]


class DISPLAYCONFIG_RATIONAL(ctypes.Structure):
    _fields_ = [("Numerator", wt.UINT), ("Denominator", wt.UINT)]


class DISPLAYCONFIG_PATH_SOURCE_INFO(ctypes.Structure):
    _fields_ = [("adapterId", LUID), ("id", wt.UINT),
                ("modeInfoIdx", wt.UINT), ("statusFlags", wt.UINT)]


class DISPLAYCONFIG_PATH_TARGET_INFO(ctypes.Structure):
    # 顺序、类型必须和 MSDN 完全一致，错一个字段后面全部错位。
    # 特别注意 refreshRate 是 RATIONAL（两个 UINT），不是单个 UINT ——
    # 网上不少示例在这里写错，只用到结构体前段的字段时才碰巧能跑。
    _fields_ = [("adapterId", LUID), ("id", wt.UINT),
                ("modeInfoIdx", wt.UINT),
                ("outputTechnology", wt.UINT), ("rotation", wt.UINT),
                ("scaling", wt.UINT),
                ("refreshRate", DISPLAYCONFIG_RATIONAL),
                ("scanLineOrdering", wt.UINT),
                ("targetAvailable", wt.BOOL), ("statusFlags", wt.UINT)]


class DISPLAYCONFIG_PATH_INFO(ctypes.Structure):
    _fields_ = [("sourceInfo", DISPLAYCONFIG_PATH_SOURCE_INFO),
                ("targetInfo", DISPLAYCONFIG_PATH_TARGET_INFO),
                ("flags", wt.UINT)]


class DISPLAYCONFIG_MODE_INFO(ctypes.Structure):
    # 里面是 union，实际最大成员约 64 字节；留 128 有余量。
    # 我们不解析它，只是 QueryDisplayConfig 要求有这个输出缓冲。
    _fields_ = [("infoType", wt.UINT), ("id", wt.UINT),
                ("adapterId", LUID), ("mode", ctypes.c_byte * 128)]


class DISPLAYCONFIG_DEVICE_INFO_HEADER(ctypes.Structure):
    _fields_ = [("type", wt.UINT), ("size", wt.UINT),
                ("adapterId", LUID), ("id", wt.UINT)]


class SOURCE_DEVICE_NAME(ctypes.Structure):
    _fields_ = [("header", DISPLAYCONFIG_DEVICE_INFO_HEADER),
                ("viewGdiDeviceName", wt.WCHAR * 32)]


class TARGET_NAME(ctypes.Structure):
    # monitorDevicePath 虽然用不到，但**必须留着**：
    # DisplayConfigGetDeviceInfo 会拿 size 跟真实结构体比对，少一个字段
    # 尺寸对不上就直接返回 87（ERROR_INVALID_PARAMETER），友好名永远是空串。
    _fields_ = [("header", DISPLAYCONFIG_DEVICE_INFO_HEADER),
                ("flags", wt.UINT), ("outputTechnology", wt.UINT),
                ("edidManufactureId", wt.USHORT),
                ("edidProductCodeId", wt.USHORT),
                ("connectorInstance", wt.UINT),
                ("friendlyName", wt.WCHAR * 64),
                ("monitorDevicePath", wt.WCHAR * 128)]


class ADVANCED_COLOR_INFO(ctypes.Structure):
    _fields_ = [("header", DISPLAYCONFIG_DEVICE_INFO_HEADER),
                ("value", wt.UINT), ("colorEncoding", wt.UINT),
                ("bitsPerColorChannel", wt.UINT)]


def _query_paths():
    """QueryDisplayConfig -> (paths, rc)。失败返回 ([], rc)。"""
    n_paths = wt.UINT()
    n_modes = wt.UINT()
    if user32.GetDisplayConfigBufferSizes(
            QDC_ONLY_ACTIVE_PATHS, ctypes.byref(n_paths),
            ctypes.byref(n_modes)) != 0:
        return [], -1
    if not n_paths.value:
        return [], 0
    paths = (DISPLAYCONFIG_PATH_INFO * n_paths.value)()
    modes = (DISPLAYCONFIG_MODE_INFO * max(1, n_modes.value))()
    # 第 5/6 个参数：当前配置标志 / 顶层显示器句柄。传 None 是合法的。
    rc = user32.QueryDisplayConfig(
        QDC_ONLY_ACTIVE_PATHS, ctypes.byref(n_paths), paths,
        ctypes.byref(n_modes), modes, None)
    if rc != 0:
        return [], rc
    return [paths[i] for i in range(n_paths.value)], 0


def _source_device(path):
    """path -> "\\\\.\\DISPLAY5"（GDI 设备名），失败返回 ""。"""
    info = SOURCE_DEVICE_NAME()
    info.header.type = TYPE_GET_SOURCE_NAME
    info.header.size = ctypes.sizeof(info)
    info.header.adapterId = path.sourceInfo.adapterId
    info.header.id = path.sourceInfo.id
    if user32.DisplayConfigGetDeviceInfo(ctypes.byref(info)) != 0:
        return ""
    return info.viewGdiDeviceName or ""


def _friendly(path):
    info = TARGET_NAME()
    info.header.type = TYPE_GET_TARGET_NAME
    info.header.size = ctypes.sizeof(info)
    info.header.adapterId = path.targetInfo.adapterId
    info.header.id = path.targetInfo.id
    if user32.DisplayConfigGetDeviceInfo(ctypes.byref(info)) != 0:
        return ""
    return info.friendlyName or ""


def _advanced_color(path):
    """-> (dict, rc)。rc != 0 表示该输出不支持查询。"""
    info = ADVANCED_COLOR_INFO()
    info.header.type = TYPE_GET_ADVANCED_COLOR_INFO
    info.header.size = ctypes.sizeof(info)
    info.header.adapterId = path.targetInfo.adapterId
    info.header.id = path.targetInfo.id
    rc = user32.DisplayConfigGetDeviceInfo(ctypes.byref(info))
    if rc != 0:
        return None, rc
    v = info.value
    advanced = bool(v & AC_HDR_ENABLED)
    wcg = bool(v & AC_WIDE_COLOR_ENFORCED)
    bpc = int(info.bitsPerColorChannel)
    # 只有「没有强制广色域」的情况下才敢说这是 HDR；否则就是笼统的高级颜色。
    # 用户看到「你的屏开了 HDR」而自己明明没开，只会觉得程序在瞎报。
    if advanced and not wcg:
        mode = "HDR"
        mode_text = "HDR 已开启（%dbit）" % bpc
    elif advanced:
        mode = "advanced"
        mode_text = "高级颜色已开启（HDR 或自动管理颜色，%dbit）" % bpc
    else:
        mode = "SDR"
        if v & AC_HDR_SUPPORTED:
            mode_text = "SDR（支持 HDR 但没开，%dbit）" % bpc
        else:
            mode_text = "SDR（%dbit）" % bpc
    return {
        "hdr_supported": bool(v & AC_HDR_SUPPORTED),
        "hdr_enabled": advanced,      # 兼容旧调用：实际含义是"高级颜色已启用"
        "advanced": advanced,
        "wide_gamut": wcg,
        "mode": mode,
        "mode_text": mode_text,
        "bpc": bpc,
    }, 0


def query():
    """每台显示器的高级颜色状态。

    返回 [{"device": "\\\\.\\DISPLAY5", "friendly": "SKG 27M1",
           "ok": True, "rc": 0, "hdr_supported": True, "hdr_enabled": True,
           "wide_gamut": True, "bpc": 10}]

    ok=False 的项（rc=87 之类）表示这块输出问不出 HDR 状态，
    按「纯 SDR」处理 —— 既然它不报 HDR，就不可能正处在 HDR 模式。
    """
    paths, rc = _query_paths()
    if not paths:
        return []
    out = []
    for p in paths:
        item = {"device": _source_device(p), "friendly": _friendly(p)}
        info, rc2 = _advanced_color(p)
        item["rc"] = rc2
        item["ok"] = info is not None
        if info:
            item.update(info)
        else:
            item.update({"hdr_supported": False, "hdr_enabled": False,
                         "advanced": False, "wide_gamut": False, "bpc": 0,
                         "mode": "SDR", "mode_text": "查不到（按 SDR 处理）"})
        out.append(item)
    return out


def hdr_devices():
    """当前处于「高级颜色」模式的 device 集合。

    名字保留 hdr_devices 是为了不动老的调用点；语义以 advanced_color 为准 ——
    HDR 和 Windows 的「自动管理颜色」都会被算进来，因为这两种状态
    都会让驱动接管 gamma 查找表，对画面补偿来说后果一样。
    """
    return {m["device"] for m in query() if m.get("advanced")}


def is_hdr_on(device):
    """某块屏是否处于高级颜色模式（HDR / 自动管理颜色）。

    查不到就返回 False（按 SDR 处理）—— 连状态都问不出来的屏不可能
    正处在 HDR 里，HDR 是驱动侧状态，一定会报。
    """
    for m in query():
        if m.get("device") == device:
            return bool(m.get("advanced"))
    return False


def describe(device=None):
    """给人看的一句话。"""
    rows = query()
    if device:
        rows = [m for m in rows if m.get("device") == device]
    if not rows:
        return "查不到高级颜色状态"
    parts = []
    for m in rows:
        if not m.get("ok"):
            parts.append("%s 纯 SDR（rc=%d）" % (m["device"], m["rc"]))
        elif m.get("advanced"):
            parts.append("%s %s" % (m["device"], m.get("mode_text", "")))
        elif m.get("hdr_supported"):
            parts.append("%s 支持 HDR（未开启）" % m["device"])
        else:
            parts.append("%s 不支持 HDR" % m["device"])
    return "；".join(parts)
