# -*- coding: utf-8 -*-
"""开发辅助：把「高级颜色」的原始状态全打出来。

用来分清三件事：
  HDR 真的开着
  Windows 的「自动管理颜色」(ACM) 开着 —— 这个也会把 advancedColorEnabled 置位
  两者都没开

type 9（旧）只有 advancedColorEnabled 一位，分不出来；type 11
（DISPLAYCONFIG_GET_ADVANCED_COLOR_INFO_2）多一个 activeColorMode，
SDR=0 / WCG=1 / HDR=2，这才是能区分的那一位。
"""
import ctypes
import os
import sys
from ctypes import wintypes as wt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from screenmode import hdr as H   # noqa: E402

user32 = ctypes.windll.user32
TYPE_GET_SDR_WHITE_LEVEL = 8
TYPE_GET_ADVANCED_COLOR_INFO_2 = 11


class SDR_WHITE_LEVEL(ctypes.Structure):
    _fields_ = [("header", H.DISPLAYCONFIG_DEVICE_INFO_HEADER),
                ("sdrWhiteLevel", wt.UINT)]


class ADVANCED_COLOR_INFO_2(ctypes.Structure):
    _fields_ = [("header", H.DISPLAYCONFIG_DEVICE_INFO_HEADER),
                ("value", wt.UINT), ("colorEncoding", wt.UINT),
                ("bitsPerColorChannel", wt.UINT),
                ("activeColorMode", wt.UINT)]


MODE_NAMES = {0: "SDR", 1: "WCG(广色域)", 2: "HDR", 3: "?"}


def call(path, struct, ttype):
    struct.header.type = ttype
    struct.header.size = ctypes.sizeof(struct)
    struct.header.adapterId = path.targetInfo.adapterId
    struct.header.id = path.targetInfo.id
    return user32.DisplayConfigGetDeviceInfo(ctypes.byref(struct)), struct


def main():
    paths, rc = H._query_paths()
    print("paths=%d rc=%d" % (len(paths), rc))
    for p in paths:
        dev = H._source_device(p)
        name = H._friendly(p)
        print("\n=== %s  %s" % (dev, name))
        print("  target: tech=%d statusFlags=0x%x"
              % (p.targetInfo.outputTechnology, p.targetInfo.statusFlags))

        rc9, i9 = call(p, H.ADVANCED_COLOR_INFO(),
                       H.TYPE_GET_ADVANCED_COLOR_INFO)
        if rc9:
            print("  [type9] rc=%d" % rc9)
        else:
            print("  [type9] value=0x%08x  supported=%d enabled=%d "
                  "wideEnforced=%d forceDisabled=%d enc=%d bpc=%d"
                  % (i9.value, i9.value & 1, (i9.value >> 1) & 1,
                     (i9.value >> 2) & 1, (i9.value >> 3) & 1,
                     i9.colorEncoding, i9.bitsPerColorChannel))

        rc11, i11 = call(p, ADVANCED_COLOR_INFO_2(),
                         TYPE_GET_ADVANCED_COLOR_INFO_2)
        if rc11:
            print("  [type11] rc=%d（这台系统不支持新的查询）" % rc11)
        else:
            print("  [type11] value=0x%08x  supported=%d active=%d "
                  "limitedByPolicy=%d forceDisabled=%d enc=%d bpc=%d "
                  "activeColorMode=%d(%s)"
                  % (i11.value, i11.value & 1, (i11.value >> 1) & 1,
                     (i11.value >> 2) & 1, (i11.value >> 3) & 1,
                     i11.colorEncoding, i11.bitsPerColorChannel,
                     i11.activeColorMode,
                     MODE_NAMES.get(i11.activeColorMode, "?")))

        rc8, i8 = call(p, SDR_WHITE_LEVEL(), TYPE_GET_SDR_WHITE_LEVEL)
        if rc8:
            print("  [type8] rc=%d" % rc8)
        else:
            print("  [type8] sdrWhiteLevel=%d（SDR 常见 1000；HDR 时通常不是）"
                  % i8.sdrWhiteLevel)
    return 0


if __name__ == "__main__":
    sys.exit(main())
