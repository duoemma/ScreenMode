# -*- coding: utf-8 -*-
"""验证 Windows Gamma Ramp —— 完全绕开 DDC/CI 的通用底层通道。

Gamma Ramp 是显卡 DAC 输出的查找表，per-display 可单独设置。
任何显卡、任何显示器都支持，不需要显示器配合、不问品牌、不看 DDC。
"""
import ctypes
from ctypes import wintypes as wt

gdi = ctypes.windll.gdi32
user32 = ctypes.windll.user32
user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))


class DISPLAY_DEVICEW(ctypes.Structure):
    _fields_ = [("cb", wt.DWORD), ("DeviceName", wt.WCHAR * 32),
                ("DeviceString", wt.WCHAR * 128),
                ("StateFlags", wt.DWORD), ("DeviceID", wt.WCHAR * 128),
                ("DeviceKey", wt.WCHAR * 128)]


DISPLAY_DEVICE_ATTACHED_TO_DESKTOP = 0x1


def enum_adapters():
    """枚举显卡适配器（每个输出一个）。"""
    out = []
    i = 0
    while True:
        d = DISPLAY_DEVICEW()
        d.cb = ctypes.sizeof(d)
        if not user32.EnumDisplayDevicesW(None, i, ctypes.byref(d), 0):
            break
        if d.StateFlags & DISPLAY_DEVICE_ATTACHED_TO_DESKTOP:
            out.append((d.DeviceName, d.DeviceString,
                        bool(d.StateFlags & 0x4)))     # 0x4 = PRIMARY
        i += 1
    return out


def open_dc(device):
    return gdi.CreateDCW(device, None, None, None)


def get_ramp(hdc):
    buf = (wt.WORD * 256 * 3)()
    if gdi.GetDeviceGammaRamp(hdc, ctypes.byref(buf)):
        return [list(buf[c]) for c in range(3)]
    return None


def set_ramp(hdc, ramp):
    buf = (wt.WORD * 256 * 3)()
    for c in range(3):
        for i in range(256):
            buf[c][i] = int(ramp[c][i])
    return bool(gdi.SetDeviceGammaRamp(hdc, ctypes.byref(buf)))


def build(warm=1.0, gamma=1.0, contrast=1.0):
    """warm>1 偏暖（加红减蓝），gamma>1 变暗，contrast 调对比。"""
    out = []
    for c in range(3):
        gain = 1.0
        if c == 0:
            gain = warm
        elif c == 2:
            gain = 1.0 / warm
        vals = []
        for i in range(256):
            x = i / 255.0
            x = ((x - 0.5) * contrast + 0.5)
            x = max(0.0, min(1.0, x))
            x = x ** gamma
            v = x * gain * 65535
            vals.append(max(0, min(65535, int(v))))
        out.append(vals)
    return out


def main():
    adapters = enum_adapters()
    print("显示输出：")
    for name, desc, primary in adapters:
        print("  %s  %s  %s" % (name, desc, "主屏" if primary else ""))

    for name, desc, primary in adapters:
        hdc = open_dc(name)
        if not hdc:
            print("%s 打不开 DC" % name)
            continue
        orig = get_ramp(hdc)
        if orig is None:
            print("%s 读不到 gamma ramp" % name)
            gdi.DeleteDC(hdc)
            continue
        print("\n=== %s（%s）===" % (name, "主屏" if primary else "副屏"))
        print("  原始 ramp: R[0]=%d R[128]=%d R[255]=%d | B[128]=%d"
              % (orig[0][0], orig[0][128], orig[0][255], orig[2][128]))
        for label, kw in (("偏暖 + 降对比（≈阅读/护眼）", dict(warm=1.12, contrast=0.9)),
                          ("偏冷 + 提对比（≈电影）", dict(warm=0.9, contrast=1.12)),
                          ("明显变暗（≈节能）", dict(gamma=1.6))):
            ok = set_ramp(hdc, build(**kw))
            back = get_ramp(hdc)
            changed = back and back[0][128] != orig[0][128]
            print("  %-24s 写入=%s  读回中间调 R=%s（原 %d）%s"
                  % (label, ok, back[0][128] if back else "?", orig[0][128],
                     "  生效" if changed else ""))
        set_ramp(hdc, orig)
        print("  已恢复原值：R[128]=%d" % get_ramp(hdc)[0][128])
        gdi.DeleteDC(hdc)


if __name__ == "__main__":
    main()
