# -*- coding: utf-8 -*-
"""查每台显示器的 HDR / 高级颜色状态（HDR 开着时 Gamma Ramp 会被禁用）。"""
import ctypes
from ctypes import wintypes as wt

u = ctypes.windll.user32
u.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))


class LUID(ctypes.Structure):
    _fields_ = [("LowPart", wt.DWORD), ("HighPart", wt.LONG)]


class DISPLAYCONFIG_PATH_SOURCE_INFO(ctypes.Structure):
    _fields_ = [("adapterId", LUID), ("id", wt.UINT), ("modeInfoIdx", wt.UINT),
                ("statusFlags", wt.UINT)]


class DISPLAYCONFIG_PATH_TARGET_INFO(ctypes.Structure):
    _fields_ = [("adapterId", LUID), ("id", wt.UINT), ("modeInfoIdx", wt.UINT),
                ("outputTechnology", wt.UINT), ("rotation", wt.UINT),
                ("scaling", wt.UINT), ("refreshRate", wt.UINT),
                ("scanLineOrdering", wt.UINT), ("targetAvailable", wt.BOOL),
                ("statusFlags", wt.UINT)]


class DISPLAYCONFIG_PATH_INFO(ctypes.Structure):
    _fields_ = [("sourceInfo", DISPLAYCONFIG_PATH_SOURCE_INFO),
                ("targetInfo", DISPLAYCONFIG_PATH_TARGET_INFO),
                ("flags", wt.UINT)]


class DISPLAYCONFIG_MODE_INFO(ctypes.Structure):
    _fields_ = [("infoType", wt.UINT), ("id", wt.UINT),
                ("adapterId", LUID), ("union", ctypes.c_byte * 64)]


class DISPLAYCONFIG_DEVICE_INFO_HEADER(ctypes.Structure):
    _fields_ = [("type", wt.UINT), ("size", wt.UINT),
                ("adapterId", LUID), ("id", wt.UINT)]


class ADVANCED_COLOR_INFO(ctypes.Structure):
    _fields_ = [("header", DISPLAYCONFIG_DEVICE_INFO_HEADER),
                ("value", wt.UINT), ("colorEncoding", wt.UINT),
                ("bitsPerColorChannel", wt.UINT)]


class TARGET_NAME(ctypes.Structure):
    _fields_ = [("header", DISPLAYCONFIG_DEVICE_INFO_HEADER),
                ("flags", wt.UINT), ("outputTechnology", wt.UINT),
                ("edidManufactureId", wt.USHORT),
                ("edidProductCodeId", wt.USHORT),
                ("connectorInstance", wt.UINT),
                ("friendlyName", wt.WCHAR * 64)]


n = wt.UINT()
flags = wt.UINT()
buf = (DISPLAYCONFIG_PATH_INFO * 32)()
mode = (DISPLAYCONFIG_MODE_INFO * 64)()
u.GetDisplayConfigBufferSizes(2, ctypes.byref(n), ctypes.byref(flags))
buf = (DISPLAYCONFIG_PATH_INFO * n.value)()
mode = (DISPLAYCONFIG_MODE_INFO * flags.value)()
if u.QueryDisplayConfig(2, ctypes.byref(n), buf,
                        ctypes.byref(flags), mode, None) != 0:
    print("GetDisplayConfig 失败")
    raise SystemExit(1)

for i in range(n.value):
    p = buf[i]
    hdr = ADVANCED_COLOR_INFO()
    hdr.header.type = 9          # GET_ADVANCED_COLOR_INFO
    hdr.header.size = ctypes.sizeof(hdr)
    hdr.header.adapterId = p.targetInfo.adapterId
    hdr.header.id = p.targetInfo.id
    rc = u.DisplayConfigGetDeviceInfo(ctypes.byref(hdr))

    name = TARGET_NAME()
    name.header.type = 2         # GET_TARGET_NAME
    name.header.size = ctypes.sizeof(name)
    name.header.adapterId = p.targetInfo.adapterId
    name.header.id = p.targetInfo.id
    u.DisplayConfigGetDeviceInfo(ctypes.byref(name))

    friendly = name.friendlyName or "?"
    if rc != 0:
        print("目标 %d  %-24s  高级颜色信息读失败 rc=%d" % (i, friendly, rc))
        continue
    v = hdr.value
    supported = bool(v & 0x1)
    enabled = bool(v & 0x2)
    wide = bool(v & 0x4)
    print("目标 %d  %-24s  HDR支持=%s  已开启=%s  广色域=%s  色深=%dbit"
          % (i, friendly, supported, enabled, wide, hdr.bitsPerColorChannel))
