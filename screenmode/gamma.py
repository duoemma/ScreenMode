# -*- coding: utf-8 -*-
r"""Gamma Ramp —— 完全绕开 DDC/CI 的通用显示通道。

为什么需要它
------------
DDC/CI 要过三关：显示器固件得实现 MCCS、显卡驱动得放行 I2C、
写入的值显示器得真采纳。三关里任何一关不通，「切换情景模式」就失效。
本机实测就踩到了：某台副屏能力串里报了 0xDC / 0x14 / 0xCC 三个码，
写进去全部返回成功，读回来却是显示器自己的值（写 1 读回 4、写 4 读回 144）
—— 写入被静默丢弃，画面毫无变化。

Gamma Ramp 是另一条路：它是显卡 DAC 的 256×3 查找表，
`SetDeviceGammaRamp` 直接把表塞给显卡，显示器全程不参与。

  ✅ 不看品牌、不看型号、不看 DDC 能力串
  ✅ 任何显卡（NVIDIA / AMD / Intel）、任何显示器都成立
  ✅ per-display 独立：`CreateDCW("\\.\DISPLAY5")` 只改那一块
  ✅ 毫秒级实时，不用等显示器固件刷新
  ❌ 改不了显示器硬件的亮度 / 对比度档位（那是面板背光，Gamma 动不了）
  ❌ HDR 开启时被驱动接管，写进去返回 True 但画面不变（见 hdr.py）

能模拟什么
----------
Gamma 只能改「显卡输出的像素值」，所以能模拟的都是像素级效果：

  色温 warm        加红减蓝，模拟暖色 / 冷色预设
  对比度 contrast  绕中点缩放
  亮度 brightness  整体增益（注意不是背光亮度）
  Gamma            中间调曲线，改明暗层次
  饱和度 sat       绕灰轴展开，模拟游戏模式的高饱和

不能模拟：背光亮度（真·变暗）、显示器自己的锐度/降噪/动态对比。
所以参数命名为「画面补偿」而不是「亮度」——避免和显示器的背光亮度混淆。

一条实测经验
------------
**屏幕截图抓不到这条通道的效果判断。** 截图抓的是显卡帧缓冲，
如果 gamma 已生效，截图里其实能看到（因为改的就是帧缓冲的输出映射），
但更可靠的验证方式是 `GetDeviceGammaRamp` 读回比较 —— 见 probe_gamma.py。
"""
import ctypes
import os
from ctypes import wintypes as wt

gdi = ctypes.windll.gdi32
user32 = ctypes.windll.user32

# 64 位下 HDC 是句柄（指针宽度），不钉死 restype 会 OverflowError: int too long。
gdi.CreateDCW.restype = ctypes.c_void_p
gdi.CreateDCW.argtypes = [wt.LPCWSTR, wt.LPCWSTR, wt.LPCWSTR, ctypes.c_void_p]
gdi.DeleteDC.restype = wt.BOOL
gdi.DeleteDC.argtypes = [ctypes.c_void_p]
gdi.GetDeviceGammaRamp.restype = wt.BOOL
gdi.GetDeviceGammaRamp.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
gdi.SetDeviceGammaRamp.restype = wt.BOOL
gdi.SetDeviceGammaRamp.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

DISPLAY_DEVICE_ATTACHED_TO_DESKTOP = 0x1
DISPLAY_DEVICE_PRIMARY_DEVICE = 0x4
DISPLAY_DEVICE_MIRRORING_DRIVER = 0x8


class DISPLAY_DEVICEW(ctypes.Structure):
    _fields_ = [("cb", wt.DWORD), ("DeviceName", wt.WCHAR * 32),
                ("DeviceString", wt.WCHAR * 128),
                ("StateFlags", wt.DWORD), ("DeviceID", wt.WCHAR * 128),
                ("DeviceKey", wt.WCHAR * 128)]


# ------------------------------------------------------------------ 参数定义
# 全部以 1.0 为「不改变」。这样 is_neutral() 一判就知道要不要动显卡。
PARAM_KEYS = ("warm", "contrast", "brightness", "gamma", "sat")

PARAM_RANGE = {
    "warm": (0.60, 1.50),        # >1 偏暖（加红减蓝）
    "contrast": (0.50, 1.60),
    "brightness": (0.30, 1.60),
    "gamma": (0.50, 2.50),       # >1 中间调变暗
    "sat": (0.00, 1.80),
}

PARAM_LABELS = {
    "warm": "色温", "contrast": "对比度", "brightness": "亮度",
    "gamma": "Gamma", "sat": "饱和度",
}

# 提示文案自己带换行：对话框里每格只有 92px 宽，让 DrawText 自动折行会
# 折在「>1 偏暖，<1 偏」/「冷」这种地方，看着像排版坏了。手动断成两行更整齐。
PARAM_HINTS = {
    "warm": ">1 偏暖\n<1 偏冷",
    "contrast": ">1 更硬\n<1 更柔",
    "brightness": "整体明暗\n（非背光）",
    "gamma": ">1 中间调\n变暗",
    "sat": ">1 更艳\n<1 更淡",
}


def normalize(params):
    """把任意来源的参数字典洗成 5 个键的浮点，缺的按 1.0，超范围夹紧。"""
    out = {}
    src = params if isinstance(params, dict) else {}
    for k in PARAM_KEYS:
        try:
            v = float(src.get(k, 1.0))
        except (TypeError, ValueError):
            v = 1.0
        lo, hi = PARAM_RANGE[k]
        out[k] = round(max(lo, min(hi, v)), 3)
    return out


def is_neutral(params):
    """全是 1.0 = 不需要动显卡（等于原始画面）。"""
    p = normalize(params) if isinstance(params, dict) else {}
    return all(abs(p.get(k, 1.0) - 1.0) < 1e-6 for k in PARAM_KEYS)


def describe(params):
    """给人看的一行摘要，例如「偏暖 8% · 对比 0.90 · Gamma 1.20」。"""
    if not isinstance(params, dict) or is_neutral(params):
        return "原始画面"
    p = normalize(params)
    parts = []
    warm = p["warm"]
    if abs(warm - 1.0) > 1e-6:
        pct = int(round((warm - 1.0) * 100))
        parts.append("偏暖 %d%%" % pct if pct > 0 else "偏冷 %d%%" % -pct)
    for k in ("contrast", "brightness", "gamma", "sat"):
        if abs(p[k] - 1.0) > 1e-6:
            parts.append("%s %.2f" % (PARAM_LABELS[k], p[k]))
    return " · ".join(parts) or "原始画面"


# ------------------------------------------------------------------ 曲线生成
_IDENTITY = None


def identity():
    """恒等斜坡：输入 i 原样输出 i，Windows 的「无校正」基准。"""
    global _IDENTITY
    if _IDENTITY is None:
        _IDENTITY = [[int(round(i * 65535 / 255.0)) for i in range(256)]
                     for _ in range(3)]
    return [list(ch) for ch in _IDENTITY]


def _channel_curve(gain, contrast, brightness, gamma_exp):
    vals = []
    for i in range(256):
        x = i / 255.0
        # 对比度绕 0.5 缩放：0.5 这个锚点不动，纯黑纯白向两端拉/压
        x = (x - 0.5) * contrast + 0.5
        if x < 0.0:
            x = 0.0
        elif x > 1.0:
            x = 1.0
        if gamma_exp and abs(gamma_exp - 1.0) > 1e-9:
            x = x ** gamma_exp
        x = x * brightness * gain
        vals.append(x)
    return vals


def build(params):
    """参数 -> 3×256 的 WORD 斜坡（float 已转 int，夹在 0..65535）。

    处理顺序：对比度 -> gamma -> 亮度*增益 -> 饱和度。
    饱和度必须在三通道横向做（要知道中性灰在哪），所以分两遍。
    """
    p = normalize(params)
    warm = p["warm"] or 1.0
    # 暖 = 提红压蓝，绿不动。红蓝增益互为倒数，中间调的亮度总和基本不变，
    # 这样"只调色温"不会顺带把画面整体拉亮或压暗。
    gains = (warm, 1.0, 1.0 / warm)          # (R, G, B)
    rgb = [_channel_curve(g, p["contrast"], p["brightness"], p["gamma"])
           for g in gains]

    sat = p["sat"]
    if abs(sat - 1.0) > 1e-9:
        out = [[0.0] * 256 for _ in range(3)]
        for i in range(256):
            r, g, b = rgb[0][i], rgb[1][i], rgb[2][i]
            luma = 0.299 * r + 0.587 * g + 0.114 * b
            out[0][i] = luma + (r - luma) * sat
            out[1][i] = luma + (g - luma) * sat
            out[2][i] = luma + (b - luma) * sat
        rgb = out

    result = []
    for ch in rgb:
        result.append([max(0, min(65535, int(v * 65535 + 0.5))) for v in ch])
    return result


# ------------------------------------------------------------------ 底层读写
def _new_buf():
    return (wt.WORD * 256 * 3)()


def read_ramp(hdc):
    """读一条 HDC 的当前斜坡 -> [R[256], G[256], B[256]]，失败返回 None。"""
    buf = _new_buf()
    if not gdi.GetDeviceGammaRamp(hdc, ctypes.byref(buf)):
        return None
    return [[int(buf[c][i]) for i in range(256)] for c in range(3)]


def write_ramp(hdc, ramp):
    """写斜坡。缓冲区结构是 WORD[3][256]，即「通道优先」，不是交错。"""
    if not ramp or len(ramp) < 3:
        return False
    buf = _new_buf()
    for c in range(3):
        ch = ramp[c]
        for i in range(256):
            buf[c][i] = max(0, min(65535, int(ch[i])))
    return bool(gdi.SetDeviceGammaRamp(hdc, ctypes.byref(buf)))


def enum_outputs():
    """枚举当前激活的显示输出。

    返回 [{"device": "\\\\.\\DISPLAY5", "desc": "NVIDIA ...",
           "primary": True}]，顺序与 `EnumDisplayMonitors` 的 szDevice 同一套
    命名，所以可以直接和 ddc.list_monitors() 的 device 字段做字符串匹配。
    """
    out = []
    i = 0
    while True:
        d = DISPLAY_DEVICEW()
        d.cb = ctypes.sizeof(d)
        if not user32.EnumDisplayDevicesW(None, i, ctypes.byref(d), 0):
            break
        flags = d.StateFlags
        if (flags & DISPLAY_DEVICE_ATTACHED_TO_DESKTOP
                and not flags & DISPLAY_DEVICE_MIRRORING_DRIVER):
            out.append({
                "device": d.DeviceName,
                "desc": d.DeviceString,
                "primary": bool(flags & DISPLAY_DEVICE_PRIMARY_DEVICE),
            })
        i += 1
    return out


class GammaChannel:
    """每块屏一条独立通道。

    关键设计：**基线（base）**。原斜坡不一定是恒等的 —— 驱动自己的色彩
    校正、Windows 的「颜色校准」都会写这张表（实测本机原值 R[128]=30840，
    而恒等值应是 32768，说明驱动压过一点）。所以：

      apply()   用绝对曲线覆盖（参数 1.0 = 恒等，不看基线）
      restore() 写回**第一次读到的那份**原始斜坡，尽量无损
      rebase()  重新采样当前画面当基线（用户觉得恢复得不对时用）
    """

    def __init__(self, store_path=None):
        self._hdc = {}
        self._base = {}
        self._applied = {}
        self._outputs = []
        self.store_path = store_path
        self.last_error = ""
        self._load_base()

    # ---------------- 枚举 ----------------
    def outputs(self, refresh=False):
        if self._outputs and not refresh:
            return self._outputs
        try:
            self._outputs = enum_outputs()
        except Exception as e:
            self.last_error = "枚举显示输出失败：%r" % (e,)
            self._outputs = []
        return self._outputs

    def devices(self):
        return [o["device"] for o in self.outputs()]

    # ---------------- 基线持久化 ----------------
    def _load_base(self):
        """基线要存盘。

        不存的话，重启程序后 `_applied` 和 `_base` 都是空的：
        画面还带着上个会话的补偿色调，「恢复原始画面」却不知道该恢复成
        什么，只能写恒等斜坡 —— 那会把驱动原本的色彩校正抹掉
        （实测主屏原值 123.5/255，恒等是 128/255，肉眼能看出轻微变亮）。
        """
        if not self.store_path:
            return
        try:
            import json
            if not os.path.exists(self.store_path):
                return
            with open(self.store_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception:
            return
        for dev, ramp in (raw or {}).items():
            try:
                if len(ramp) == 3 and all(len(ch) == 256 for ch in ramp):
                    self._base[dev] = [[int(v) for v in ch] for ch in ramp]
            except Exception:
                continue

    def _save_base(self):
        if not self.store_path:
            return
        try:
            import json
            tmp = self.store_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._base, f, separators=(",", ":"))
            os.replace(tmp, self.store_path)
        except Exception:
            pass

    # ---------------- 句柄 ----------------
    def _dc(self, device):
        h = self._hdc.get(device)
        if h:
            return h
        h = gdi.CreateDCW(device, None, None, None)
        if not h:
            self.last_error = "打不开 %s 的显示上下文" % device
            return None
        self._hdc[device] = h
        return h

    # ---------------- 读写 ----------------
    def read(self, device):
        h = self._dc(device)
        return None if h is None else read_ramp(h)

    def write(self, device, ramp):
        h = self._dc(device)
        if h is None:
            return False
        return write_ramp(h, ramp)

    def base(self, device):
        """基线斜坡：**只在没被我们改过时采样**，否则会把脏值当原始画面。"""
        if device in self._base:
            return self._base[device]
        if device in self._applied:
            return None
        ramp = self.read(device)
        if ramp is not None:
            self._base[device] = ramp
            self._save_base()
        return ramp

    def rebase(self, device=None):
        """重新采样基线。device=None 表示全部重采。"""
        targets = [device] if device else list(self._base) + self.devices()
        for d in targets:
            if d in self._applied:
                continue
            ramp = self.read(d)
            if ramp is not None:
                self._base[d] = ramp
        self._save_base()

    # ---------------- 应用 / 恢复 ----------------
    def apply(self, device, params):
        """把一组画面补偿参数写到这块屏。参数全 1.0 等于恢复原始画面。"""
        p = normalize(params)
        if is_neutral(p):
            return self.restore(device)
        self.base(device)          # 先抢在改之前留一份基线
        if self.write(device, build(p)):
            self._applied[device] = p
            return True
        self.last_error = "%s 拒绝写入 gamma（驱动或 HDR 可能占用了查找表）" % device
        return False

    def restore(self, device):
        """恢复成基线（没有基线就写恒等）。"""
        ramp = self._base.get(device) or identity()
        if self.write(device, ramp):
            self._applied.pop(device, None)
            return True
        self.last_error = "%s 恢复失败" % device
        return False

    def restore_all(self):
        """恢复所有**我们碰过的**屏。

        为什么不无脑写恒等斜坡：恒等 ≠ 原始。驱动自己的色彩校正、Windows 的
        颜色校准都可能改过这张表（实测主屏原始中间调 30840，恒等是 32896）。
        对没碰过的屏写恒等，等于悄悄改掉人家校好的画面。
        """
        ok = True
        for d in sorted(set(self._applied) | set(self._base)):
            if not self.restore(d):
                ok = False
        return ok

    def applied_params(self, device):
        return self._applied.get(device)

    def applied_devices(self):
        """还套着补偿的显示器列表（切模式时用来清理上一个模式的效果）。"""
        return list(self._applied)

    def is_applied(self, device):
        return device in self._applied

    # ---------------- 收尾 ----------------
    def close(self):
        """只释放 DC，**不恢复画面**。

        切到「电影模式」后关程序，用户期待画面还是电影模式。
        恢复要靠显式的「恢复原始画面」按钮。
        """
        for d, h in list(self._hdc.items()):
            try:
                gdi.DeleteDC(h)
            except Exception:
                pass
        self._hdc.clear()
