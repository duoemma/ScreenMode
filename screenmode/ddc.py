# -*- coding: utf-8 -*-
"""显示器识别 + DDC/CI 控制（支持多台显示器）。

DDC  = Display Data Channel，显示器与显卡之间的数据通道（走 I2C）。
CI   = Command Interface，跑在这条通道上的命令集（MCCS 标准）。

显示器自带的情景预设通过 VCP 0xDC（Display Mode Select）切换，
不需要厂商软件，也不用热键。可读的显示器型号/分辨率由 EnumDisplayMonitors
自动探测，DDC 通道由 monitorcontrol 负责。

不是每台显示器都实现了 0xDC。实测有些屏（便携屏 / 用 Realtek 桥接芯片的）
只支持 0x14 色彩预设，那就退而用 0x14 当"情景模式"，见 MODE_VCP_CANDIDATES。
"""
import ctypes
import re
import time
from ctypes import wintypes as wt

VCP_MODE = 0xDC          # 情景模式（OSD 预设）Display Mode Select
VCP_COLOR_PRESET = 0x14  # 色彩预设（很多不实现 0xDC 的屏用它）
VCP_BRIGHTNESS = 0x10    # 亮度
VCP_CONTRAST = 0x12      # 对比度

# 切情景模式用哪个 VCP 码。
# 默认只认 0xDC —— 它是标准控件，也是唯一"能写就一定能切档"的。
# 0x14 色彩预设虽然很多屏都有，但**写入行为不可靠**：实测某副屏写 8 读回 5、
# 写 1 读回 4，等于偷偷改了人家的画面。所以 0x14 不自动启用，
# 只在 config 的 monitors.vcp 里显式指定时才用。
MODE_VCP_CANDIDATES = (VCP_MODE,)

VCP_NAMES = {
    VCP_MODE: "0xDC 情景模式",
    VCP_COLOR_PRESET: "0x14 色彩预设",
    0xCC: "0xCC 显示应用",
}

# 写完 DDC 立刻读回会失败 —— 显示器还没处理完上一条命令，I2C 直接回
# 「DDC/CI 消息的命令字段中的值无效」。这个等待就是给显示器留的处理时间。
# 实测 0.22 秒足够（本机 27M1 从"读报错"变成"写 5 读 5"）。
VERIFY_SETTLE = 0.22

# 一条额外经验：**屏幕截图抓不到显示器硬件做的调整**。
# 亮度 / 情景模式都是显示器后处理，截屏拿到的是显卡帧缓冲，所以
# 「写值 -> 截图对比」这种验证方式对 DDC 完全无效（实测写亮度 30 和 100，
# 画面平均亮度一模一样）。判断某台屏用哪个码，只能靠
# 「让用户手动切 OSD，程序读所有码看哪个跟着变」——见 scan_vcps / diff_scans。


def capability_codes(monitor):
    """这台屏能力串（MCCS）里上报的所有 VCP 码，升序。

    能力串才是"这屏真支持什么"的权威依据。比硬编码一堆候选码靠谱。
    读不到能力串就退回几个常见码。
    """
    try:
        cap = monitor.get_vcp_capabilities()
    except Exception:
        cap = None
    if isinstance(cap, dict):
        raw = cap.get("vcp") or {}
        codes = []
        for k in raw:
            try:
                codes.append(int(k))
            except (TypeError, ValueError):
                pass
        if codes:
            return sorted(codes)
    return [VCP_BRIGHTNESS, VCP_CONTRAST, VCP_COLOR_PRESET, VCP_MODE]


def scan_vcps(monitor, codes=None):
    """读一批 VCP 码的当前值 -> {code: value 或 None}。

    只读，不写。读失败的码记 None。
    """
    if codes is None:
        codes = capability_codes(monitor)
    out = {}
    for c in codes:
        try:
            out[c] = monitor.vcp.get_vcp_feature(c)[0]
        except Exception:
            out[c] = None
    return out


def diff_scans(a, b):
    """两次快照里「值变了」的码 -> [(code, 前值, 后值)]。

    这就是识别"情景模式到底挂在哪个 VCP 码上"的唯一可靠办法：
    用户在显示器菜单里切一次模式，前后两次快照对比，变了的那个码就是它。
    能力串可能报一堆码（实测某副屏 28 个），但用户切一次模式只会动其中一两个。
    """
    changed = []
    for code in sorted(set(a) & set(b)):
        va, vb = a[code], b[code]
        if va is None or vb is None:
            continue
        if va != vb:
            changed.append((code, va, vb))
    return changed

user32 = ctypes.windll.user32


class DEVMODEW(ctypes.Structure):
    _fields_ = [("dmDeviceName", wt.WCHAR * 32),
                ("dmSpecVersion", wt.WORD), ("dmDriverVersion", wt.WORD),
                ("dmSize", wt.WORD), ("dmDriverExtra", wt.WORD),
                ("dmFields", wt.DWORD),
                ("dmPositionX", wt.LONG), ("dmPositionY", wt.LONG),
                ("dmDisplayOrientation", wt.DWORD),
                ("dmDisplayFixedOutput", wt.DWORD),
                ("dmColor", wt.SHORT), ("dmDuplex", wt.SHORT),
                ("dmYResolution", wt.SHORT), ("dmTTOption", wt.SHORT),
                ("dmCollate", wt.SHORT), ("dmFormName", wt.WCHAR * 32),
                ("dmLogPixels", wt.WORD), ("dmBitsPerPel", wt.DWORD),
                ("dmPelsWidth", wt.DWORD), ("dmPelsHeight", wt.DWORD),
                ("dmDisplayFlags", wt.DWORD),
                ("dmDisplayFrequency", wt.DWORD),
                ("dmICMMethod", wt.DWORD), ("dmICMIntent", wt.DWORD),
                ("dmMediaType", wt.DWORD), ("dmDitherType", wt.DWORD),
                ("dmReserved1", wt.DWORD), ("dmReserved2", wt.DWORD),
                ("dmPanningWidth", wt.DWORD), ("dmPanningHeight", wt.DWORD)]

ENUM_CURRENT_SETTINGS = 0xFFFFFFFF


def physical_size(device):
    """这块输出的**真实像素尺寸** -> (w, h)，读不到返回 (0, 0)。

    为什么不直接用 GetMonitorInfo：进程若不是每显示器 DPI 感知的，
    系统会把坐标按缩放比例虚拟化。实测在 125% 缩放的屏上，
    GetMonitorInfo 报 3200×1800，而它其实是 2560×1440 的面板 ——
    界面标签写错分辨率，用户会以为程序坏了。EnumDisplaySettings 报的是
    显示模式本身，跟 DPI 无关。
    """
    try:
        d = DEVMODEW()
        d.dmSize = ctypes.sizeof(DEVMODEW)
        if user32.EnumDisplaySettingsW(device, ENUM_CURRENT_SETTINGS,
                                       ctypes.byref(d)):
            return int(d.dmPelsWidth), int(d.dmPelsHeight)
    except Exception:
        pass
    return 0, 0


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT),
                ("rcWork", wt.RECT), ("dwFlags", wt.DWORD),
                ("szDevice", wt.WCHAR * 32)]


MONITORENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_int, wt.HMONITOR, wt.HDC,
                                     ctypes.POINTER(wt.RECT), wt.LPARAM)


def enum_displays():
    """枚举当前激活的显示输出（含分辨率 / 位置 / 是否主屏）。"""
    out = []

    def _cb(hmon, hdc, lprc, lparam):
        info = MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(MONITORINFOEXW)
        if user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            r = info.rcMonitor
            out.append({
                "device": info.szDevice,
                "x": r.left, "y": r.top,
                "w": r.right - r.left, "h": r.bottom - r.top,
                "primary": bool(info.dwFlags & 1),
            })
        return 1

    user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(_cb), 0)
    return out


def probe_mode_vcp(monitor, forced=None):
    """这台显示器用哪个 VCP 码来切情景模式。

    返回 (code, cur, max)；不支持返回 (None, None, None)。

    forced 是 config 里显式指定的码（比如某台屏确认能用 0x14 就填 0x14）。
    **只读判断，不做写测试** —— 启动时反复写会把画面的色彩预设改乱。
    """
    codes = (forced,) if forced else MODE_VCP_CANDIDATES
    for code in codes:
        if code is None:
            continue
        try:
            cur, mx = monitor.vcp.get_vcp_feature(code)
        except Exception:
            continue
        return code, cur, mx
    return None, None, None


def list_monitors(forced_map=None):
    """返回检测到的显示器列表。

    forced_map：{index: vcp 码}，config 里显式指定的通道（可选）。

    每项：index / label / short / current / controllable / mode_vcp /
          mode_capable / device / desc / supported
    """
    forced_map = forced_map or {}
    displays = enum_displays()
    result = []
    try:
        from monitorcontrol import get_monitors
        monitors = get_monitors()
    except Exception:
        monitors = []

    for i in range(max(len(monitors), len(displays))):
        d = displays[i] if i < len(displays) else {}
        # 分辨率用显示模式本身，不用 GetMonitorInfo（会被 DPI 缩放虚拟化）
        pw, ph = physical_size(d.get("device", "")) if d.get("device") \
            else (0, 0)
        item = {
            "index": i,
            "controllable": i < len(monitors),   # DDC 通道能用
            "mode_capable": False,               # 能不能切情景模式
            "mode_vcp": None,                    # 用哪个 VCP 码
            "mode_max": None,
            "device": d.get("device", ""),
            "w": pw or d.get("w", 0),
            "h": ph or d.get("h", 0),
            "primary": d.get("primary", False),
            "desc": "",
            "current": None,
            "supported": [],
            "error": "",
        }
        if item["controllable"]:
            m = monitors[i]
            try:
                m.__enter__()
                item["desc"] = getattr(m.vcp, "description", "") or ""
                code, cur, mx = probe_mode_vcp(m, forced_map.get(i))
                item["mode_vcp"] = code
                item["mode_max"] = mx
                item["current"] = cur
                item["mode_capable"] = code is not None
                try:
                    item["supported"] = parse_supported(
                        m.vcp.get_vcp_capabilities(), code)
                except Exception:
                    pass
            except Exception as e:
                item["controllable"] = False
                item["error"] = repr(e)
            finally:
                try:
                    m.__exit__(None, None, None)
                except Exception:
                    pass
        result.append(item)

    # 友好的显示名
    for n, item in enumerate(result, start=1):
        item["short"] = "显示器 %d" % n
        if item["w"] and item["h"]:
            item["short"] += "  %d×%d" % (item["w"], item["h"])

        parts = ["显示器 %d" % n]
        if item["w"] and item["h"]:
            parts.append("%d×%d" % (item["w"], item["h"]))
        if item["primary"]:
            parts.append("主屏")
        if item["device"]:
            parts.append(item["device"].replace("\\\\.\\", ""))
        if not item["controllable"]:
            parts.append("不支持 DDC")
        elif not item["mode_capable"]:
            # 别写"不支持情景模式"——很多屏菜单里有，只是没在能力串里报 0xDC，
            # 需要走一遍引导才知道挂在哪个码上。
            parts.append("情景模式待识别")
        elif item["mode_vcp"] != VCP_MODE:
            parts.append("改用 %s" % VCP_NAMES.get(item["mode_vcp"],
                                                  hex(item["mode_vcp"] or 0)))
        item["label"] = " · ".join(parts)
    return result


def parse_supported(cap, code=VCP_MODE):
    """从 MCCS 能力串里解析某个 VCP 码上报支持的取值（仅作参考）。"""
    if not isinstance(cap, str) or code is None:
        return []
    m = re.search(r"%02X\(([^)]*)\)" % code, cap, re.I)
    if not m:
        return []
    vals = []
    for tok in m.group(1).split():
        try:
            vals.append(int(tok, 16))
        except ValueError:
            pass
    return vals


class DDCController:
    """多台显示器的 DDC/CI 控制器。

    indices 是要控制的显示器序号（monitorcontrol 的枚举顺序）。
    每台自己决定用哪个 VCP 码当"情景模式"：优先 0xDC，
    不支持时退到 0x14 色彩预设；两个都不行就不参与模式切换。

    切换时会对**所有选中的显示器**一起写，所以"接几台就控几台"。
    """

    def __init__(self, indices=None, index=None, forced_vcp=None):
        if indices is None:
            indices = [0 if index is None else int(index)]
        self.indices = [int(i) for i in indices]
        self.forced_vcp = {int(k): int(v)
                           for k, v in (forced_vcp or {}).items()}
        self.monitors = {}          # index -> 已打开的 monitor 对象
        self.vcps = {}              # index -> 模式 VCP 码
        self.written = []           # 上次成功写入**且读回一致**的显示器
        self.unverified = []        # 写了但读回对不上（写入被静默丢弃）
        self.failed = []            # 上次写入失败的显示器
        self.channels = {}          # index -> 走的是哪条通道（给人看的）
        # index -> 写的是不是显示器**自己的模式预设**
        #   True  写了 0xDC / 厂商私有码 = 真·换档，画面用不着再补
        #   False 只写了亮度/对比度 = 弱模拟，颜色一点没变，还需要 Gamma 补
        self.native = {}
        self.last_error = ""

    # ---------------- 连接 ----------------
    def targets(self):
        return self.indices or [0]

    def _close(self):
        for idx, m in list(self.monitors.items()):
            try:
                m.__exit__(None, None, None)
            except Exception:
                pass
        self.monitors.clear()
        self.vcps.clear()

    def ensure(self):
        """打开所有目标显示器，并探测各自可用的模式 VCP 码。"""
        if self.monitors:
            return True
        try:
            from monitorcontrol import get_monitors
            monitors = get_monitors()
        except Exception as e:
            self.last_error = "打开显示器失败：%r" % (e,)
            return False
        if not monitors:
            self.last_error = "没有找到可控制的显示器"
            return False

        problems = []
        for idx in self.targets():
            if idx >= len(monitors):
                problems.append("第 %d 台不存在" % (idx + 1))
                continue
            m = monitors[idx]
            try:
                m.__enter__()
            except Exception as e:
                problems.append("第 %d 台打不开（%r）" % (idx + 1, e))
                continue
            code, _cur, _mx = probe_mode_vcp(m, self.forced_vcp.get(idx))
            self.monitors[idx] = m
            self.vcps[idx] = code
            if code is None:
                problems.append("第 %d 台不支持情景模式" % (idx + 1))

        self.last_error = "；".join(problems)
        return bool(self.monitors)

    def _retry(self, action, tries=3):
        for attempt in range(tries):
            if attempt:
                self._close()
                time.sleep(0.4)
            if not self.ensure():
                continue
            try:
                return action()
            except Exception as e:
                self.last_error = "VCP 操作失败：%r" % (e,)
        return None

    # ---------------- 读写 ----------------
    def capable(self):
        """有没有至少一台能切情景模式的显示器。"""
        self.ensure()
        return any(v is not None for v in self.vcps.values())

    def describe(self, gamma_fallback=False):
        """给人看的"正在控制哪些显示器"。

        这里只说明每台用什么通道，不叫"不可控"——不支持情景模式的屏
        照样能通过 brightness/contrast 或画面补偿调，只是不能写档位号。
        gamma_fallback=True 表示程序有 Gamma 兜底通道，这些屏实际会
        改用画面补偿，而不是只调亮度对比度。
        """
        self.ensure()
        names = []
        for idx in sorted(self.monitors):
            code = self.vcps.get(idx)
            if code is None:
                names.append("%d(%s)" % (idx + 1, "画面补偿"
                                         if gamma_fallback else "亮度/对比度"))
            elif code == VCP_MODE:
                names.append("%d" % (idx + 1))
            else:
                names.append("%d(%s)" % (idx + 1, VCP_NAMES.get(code, hex(code))))
        return "、".join(names)

    def get_mode(self):
        """读当前情景模式值。多台时以第一台能读到的为准。"""
        def act():
            for idx in sorted(self.monitors):
                code = self.vcps.get(idx)
                if code is None:
                    continue
                try:
                    return self.monitors[idx].vcp.get_vcp_feature(code)[0]
                except Exception:
                    continue
            raise RuntimeError("没有可读的情景模式值")
        return self._retry(act)

    def read_all(self):
        """{index: 当前值}，读不到的跳过。"""
        out = {}
        self.ensure()
        for idx in sorted(self.monitors):
            code = self.vcps.get(idx)
            if code is None:
                continue
            try:
                out[idx] = self.monitors[idx].vcp.get_vcp_feature(code)[0]
            except Exception:
                pass
        return out

    def apply_mode(self, mode, verify=False):
        """按一个"模式"设置所有显示器。

        mode = {"vcp": 2,                        # 通用档位（所有支持主通道的屏共用）
                "monitor_vcp": {"1": 4},         # 这台屏自己的档位（引导记录下来的）
                "per_monitor": {"1": {"brightness": 60, "contrast": 62}}}

        优先级（每台屏单独算）：
        1. monitor_vcp 里有它的档位 -> 写自己的档位号（不同屏档位号往往不同）
        2. per_monitor 里有亮度/对比度 -> 写亮度对比度
        3. 通用 vcp -> 写通用档位

        「引导向导」会把每台屏各自的档位记进 monitor_vcp —— 因为 0x14 这类
        厂商码的档位编号各屏都不一样，共用 `vcp` 必然错。

        verify=True 时写完会**读回比对**。这一步是必须的：实测有的屏
        `set_vcp_feature` 返回成功、`get_vcp_feature` 也照常返回数字，
        但读到的其实是显示器自己原来的值（写 1 读回 4、写 4 读回 144）——
        API 层完全看不出失败，只有比对才发现「写入被静默丢弃」。
        这类屏会被记进 self.unverified，然后由上层的 Gamma 通道兜底。
        """
        value = mode.get("vcp")
        per = mode.get("per_monitor") or {}
        mvcp = mode.get("monitor_vcp") or {}

        def act():
            self.written, self.failed = [], []
            self.unverified, self.channels = [], {}
            self.native = {}
            pending = []        # 待读回比对的：[(idx, [(code, val)], is_native)]
            for idx in sorted(self.monitors):
                m = self.monitors[idx]
                over = per.get(str(idx)) or {}
                own = mvcp.get(str(idx))
                plan = []           # [(vcp 码, 值, 通道名)]
                is_native = False
                try:
                    # ① 这台屏自己的档位：优先级最高
                    if own is not None:
                        code = self.vcps.get(idx)
                        if code is None:
                            self.failed.append(idx)
                            self.channels[idx] = "无通道"
                            continue
                        plan = [(code, int(own),
                                 VCP_NAMES.get(code, "0x%02X" % code))]
                        is_native = True
                    # ② 亮度/对比度通道
                    elif (over.get("brightness") is not None
                          or over.get("contrast") is not None):
                        if over.get("brightness") is not None:
                            plan.append((VCP_BRIGHTNESS,
                                         int(over["brightness"]), "亮度"))
                        if over.get("contrast") is not None:
                            plan.append((VCP_CONTRAST,
                                         int(over["contrast"]), "对比度"))
                        is_native = False
                    # ③ 通用档位
                    else:
                        code = self.vcps.get(idx)
                        if code is None or value is None:
                            self.failed.append(idx)
                            self.channels[idx] = "无通道"
                            continue
                        plan = [(code, int(value),
                                 VCP_NAMES.get(code, "0x%02X" % code))]
                        is_native = True

                    for code, val, _label in plan:
                        m.vcp.set_vcp_feature(code, val)
                    pending.append((idx, [(c, v) for c, v, _l in plan],
                                    " + ".join(l for _, _, l in plan),
                                    is_native))
                except Exception as e:
                    self.failed.append(idx)
                    self.channels[idx] = "写入失败"
                    self.last_error = "显示器 %d 写入失败：%r" % (idx + 1, e)

            # 读回比对**必须等显示器处理完上一条命令**再读。
            # 实测紧接着读会抛「DDC/CI 消息的命令字段中的值无效」；
            # 那不是写入失败，只是显示器还没处理完。所以先统一等一会儿，
            # 再逐台读 —— 比一台一台等省时间（N 台只等一次）。
            if verify and pending:
                time.sleep(VERIFY_SETTLE)
                for idx, pairs, label, is_native in pending:
                    m = self.monitors[idx]
                    bad = [code for code, val in pairs
                           if not self._readback_ok(m, code, val)]
                    if bad:
                        self.unverified.append(idx)
                        self.channels[idx] = "%s 写入被忽略" % (
                            VCP_NAMES.get(bad[0], "0x%02X" % bad[0]))
                    else:
                        self.written.append(idx)
                        self.native[idx] = is_native
                        self.channels[idx] = label
            else:
                for idx, _pairs, label, is_native in pending:
                    self.written.append(idx)
                    self.native[idx] = is_native
                    self.channels[idx] = label

            # 只要碰过显示器就算这一轮跑通了 —— 具体成败看 written /
            # unverified / failed 三个列表，别让上层用返回值猜。
            return bool(self.written or self.unverified)

        return bool(self._retry(act))

    @staticmethod
    def _readback_ok(m, code, want, tol=0, tries=3, gap=0.16):
        """读回比对。读不到就当没通过 —— 宁可降级到其它通道，也不要
        假装成功，让用户面对一个「点了没反应」的界面。

        读失败会重试几次：DDC/CI 走 I2C，偶发超时很常见，一次失败不代表
        写入被丢弃。等 VERIFY_SETTLE 之后仍连续失败，才判定为被忽略。
        """
        for i in range(tries):
            if i:
                time.sleep(gap)
            try:
                got = m.vcp.get_vcp_feature(code)[0]
            except Exception:
                continue
            try:
                return abs(int(got) - int(want)) <= tol
            except (TypeError, ValueError):
                return False
        return False

    def set_mode(self, value):
        """兼容旧调用：只写主通道。"""
        return self.apply_mode({"vcp": value})

    def snapshot(self):
        """读每台当前的状态，给「用当前值更正」记录模式用。

        返回 {index: {"vcp": code|None, "value": v,
                      "brightness": b, "contrast": c}}
        """
        out = {}
        self.ensure()
        for idx in sorted(self.monitors):
            m = self.monitors[idx]
            info = {"vcp": self.vcps.get(idx)}
            code = self.vcps.get(idx)
            if code is not None:
                try:
                    info["value"] = m.vcp.get_vcp_feature(code)[0]
                except Exception:
                    pass
            for key, vcp in (("brightness", VCP_BRIGHTNESS),
                             ("contrast", VCP_CONTRAST)):
                try:
                    info[key] = m.vcp.get_vcp_feature(vcp)[0]
                except Exception:
                    pass
            out[idx] = info
        return out

    def close(self):
        self._close()
