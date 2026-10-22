# -*- coding: utf-8 -*-
"""Windows 系统能力：前台窗口、空闲时间、运行中的程序、开机自启、打开文件。"""
import ctypes
import os
import subprocess
import sys
import time
import winreg
from ctypes import wintypes as wt

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
shell32 = ctypes.windll.shell32

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "ScreenMode"

user32.GetForegroundWindow.restype = wt.HWND
user32.GetWindowThreadProcessId.argtypes = [wt.HWND,
                                            ctypes.POINTER(wt.DWORD)]
user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.GetWindowTextLengthW.argtypes = [wt.HWND]
user32.IsWindowVisible.argtypes = [wt.HWND]
user32.GetWindow.argtypes = [wt.HWND, wt.UINT]

user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.GetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int]

kernel32.OpenProcess.restype = wt.HANDLE
kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
kernel32.QueryFullProcessImageNameW.argtypes = [
    wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
kernel32.CloseHandle.argtypes = [wt.HANDLE]
kernel32.GetTickCount64.restype = ctypes.c_ulonglong
kernel32.CreateMutexW.restype = wt.HANDLE
kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.LPCWSTR]

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.UINT), ("dwTime", wt.DWORD)]


def process_name(pid):
    """pid -> 小写 exe 文件名（拿不到返回空串）"""
    if not pid:
        return ""
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(512)
        size = wt.DWORD(512)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf,
                                               ctypes.byref(size)):
            return os.path.basename(buf.value).lower()
        return ""
    finally:
        kernel32.CloseHandle(handle)


def get_foreground_info():
    """返回 (进程名, 窗口标题, pid)。拿不到 pid 时是 0。"""
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return "", "", 0
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    name = process_name(pid.value)
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buf, 512)
    return name, (buf.value or ""), pid.value


def get_foreground():
    """返回 (进程名, 窗口标题)。"""
    name, title, _ = get_foreground_info()
    return name, title


class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", _RECT),
                ("rcWork", _RECT), ("dwFlags", wt.DWORD)]


# 注意：这里**不能**给 GetWindowRect / GetMonitorInfoW 设 argtypes。
# ddc.py 里有一套自己的 MONITORINFOEXW 结构体，如果这里把参数类型钉死成
# _MONITORINFO*，ctypes 会直接抛 ArgumentError，显示器枚举就整个失败了
# （表现为启动日志只剩"显示器 1"，没有分辨率和设备名）。
# 只设 restype（64 位下句柄必须声明成 HMONITOR，否则会被截断）。
user32.MonitorFromWindow.restype = wt.HMONITOR
user32.MonitorFromWindow.argtypes = [wt.HWND, wt.DWORD]

MONITOR_DEFAULTTONEAREST = 0x00000002


def foreground_fullscreen():
    """前台窗口是不是"铺满整块显示器"的全屏程序（游戏）。

    用来把全屏游戏和其它普通窗口区分开：全屏程序在前台时，前台窗口本身
    容易因为加载画面 / 覆盖层 / 系统弹窗而短暂跳到别的进程上，这种情况下
    不应该跟着切模式。
    注意比的是 **整块显示器** 而不是工作区，所以最大化的窗口不会被误判
    （最大化只占工作区，扣掉了任务栏）。
    """
    try:
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return False
        rc = _RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rc)):
            return False
        wid = rc.right - rc.left
        hei = rc.bottom - rc.top
        if wid <= 0 or hei <= 0:
            return False
        hmon = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
        if not hmon:
            return False
        mi = _MONITORINFO()
        mi.cbSize = ctypes.sizeof(mi)
        if not user32.GetMonitorInfoW(ctypes.c_void_p(hmon), ctypes.byref(mi)):
            return False
        m = mi.rcMonitor
        # 允许 2 像素误差（个别显卡驱动会差 1px）
        return (abs(rc.left - m.left) <= 2 and abs(rc.top - m.top) <= 2
                and abs(rc.right - m.right) <= 2
                and abs(rc.bottom - m.bottom) <= 2)
    except Exception:
        return False


def get_idle_seconds():
    """距最后一次键鼠输入过去了多少秒。"""
    lii = LASTINPUTINFO()
    lii.cbSize = ctypes.sizeof(lii)
    if not user32.GetLastInputInfo(ctypes.byref(lii)):
        return 0.0
    return (kernel32.GetTickCount64() - lii.dwTime) / 1000.0


TH32CS_SNAPPROCESS = 0x00000002


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD),
        ("cntUsage", wt.DWORD),
        ("th32ProcessID", wt.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wt.DWORD),
        ("cntThreads", wt.DWORD),
        ("th32ParentProcessID", wt.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wt.DWORD),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


kernel32.CreateToolhelp32Snapshot.restype = wt.HANDLE
kernel32.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
kernel32.Process32FirstW.argtypes = [wt.HANDLE,
                                     ctypes.POINTER(PROCESSENTRY32W)]
kernel32.Process32NextW.argtypes = [wt.HANDLE,
                                    ctypes.POINTER(PROCESSENTRY32W)]


def list_process_names():
    """所有正在运行的进程名（小写）集合。"""
    names = set()
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap in (None, 0) or ctypes.c_ssize_t(snap).value == -1:
        return names
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        if not kernel32.Process32FirstW(snap, ctypes.byref(entry)):
            return names
        while True:
            if entry.szExeFile:
                names.add(entry.szExeFile.lower())
            if not kernel32.Process32NextW(snap, ctypes.byref(entry)):
                break
    finally:
        kernel32.CloseHandle(snap)
    return names


def process_running(exe):
    """这个进程名现在还活着吗？用来判断"前台那个程序是不是关了"。"""
    if not exe:
        return False
    return exe.lower() in list_process_names()


def process_map():
    """{pid: (exe 小写, 父 pid)}，一次快照拿全表。"""
    out = {}
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap in (None, 0) or ctypes.c_ssize_t(snap).value == -1:
        return out
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        if not kernel32.Process32FirstW(snap, ctypes.byref(entry)):
            return out
        while True:
            out[int(entry.th32ProcessID)] = (
                (entry.szExeFile or "").lower(), int(entry.th32ParentProcessID))
            if not kernel32.Process32NextW(snap, ctypes.byref(entry)):
                break
    finally:
        kernel32.CloseHandle(snap)
    return out


def parent_chain(pid, depth=4):
    """从父进程往上找，返回 ['execpubg.exe', 'steam.exe', ...]（最多 depth 层）。

    游戏常把启动器、本体拆成好几代进程，靠这个把它们归成同一个应用。
    """
    if not pid:
        return []
    table = process_map()
    chain, seen = [], {pid}
    cur = table.get(int(pid), ("", 0))[1]
    while cur and cur in table and cur not in seen and len(chain) < depth:
        seen.add(cur)
        exe = table[cur][0]
        if exe:
            chain.append(exe)
        cur = table[cur][1]
    return chain


def list_running_apps():
    """枚举有可见窗口的进程： [{exe, title, name}]，按名字排序。"""
    found = {}
    own = os.getpid()

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def _cb(hwnd, lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        if user32.GetWindowTextLengthW(hwnd) <= 0:
            return True
        if user32.GetWindowLongPtrW(hwnd, -8) & 0x00000080:  # WS_EX_TOOLWINDOW
            return True
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == own:
            return True
        exe = process_name(pid.value)
        if not exe or exe in found:
            return True
        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, buf, 512)
        found[exe] = {"exe": exe, "title": buf.value or "",
                      "name": buf.value or exe}
        return True

    try:
        user32.EnumWindows(_cb, 0)
    except Exception:
        pass
    return sorted(found.values(), key=lambda a: a["name"].lower())


# ------------------------------------------------------------------ 开机自启
def startup_command():
    if getattr(sys, "frozen", False):
        return '"%s"' % sys.executable
    script = os.path.join(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))), "main.py")
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.exists(pythonw):
        pythonw = sys.executable
    return '"%s" "%s"' % (pythonw, script)


def startup_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, RUN_VALUE)
        return bool(value)
    except OSError:
        return False


def set_startup(enable):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                            winreg.KEY_SET_VALUE) as key:
            if enable:
                winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ,
                                  startup_command())
            else:
                try:
                    winreg.DeleteValue(key, RUN_VALUE)
                except OSError:
                    pass
        return True
    except OSError:
        return False


def startup_target():
    """自启项当前指向的路径（没开自启就是空串）。"""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, RUN_VALUE)
        return str(value or "").strip().strip('"')
    except OSError:
        return ""


def ensure_startup_path():
    """自启开着的话，把它的目标修正成"现在正在跑的这个 exe"。

    绿色版没有安装程序，用户随时可能把整个文件夹挪走、改名、或者复制一份
    到别处。挪完之后注册表里还指着旧路径 —— 开机要么启动不起来，要么
    启动的是被留下的旧副本（然后和手上这个抢单实例锁）。

    这里每次启动顺手校正一下，返回 True 表示真的改过。
    """
    if not getattr(sys, "frozen", False):
        return False
    now = startup_target()
    if not now:
        return False                       # 没开自启，不去碰它
    want = os.path.abspath(sys.executable)
    if os.path.normcase(now) == os.path.normcase(want):
        return False
    return set_startup(True)


# ------------------------------------------------------------------ 杂项
def open_path(path):
    """资源管理器打开文件 / 文件夹。"""
    try:
        if os.path.isdir(path):
            os.startfile(path)
        elif os.path.exists(path):
            subprocess.Popen(["notepad.exe", path])
        else:
            os.startfile(os.path.dirname(path))
    except Exception:
        pass


def message_box(text, title="屏效助手", flags=0x40):
    user32.MessageBoxW(0, text, title, flags)


def ensure_single_instance(name="ScreenModeSingletonMutex"):
    kernel32.CreateMutexW(None, True, name)
    return kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS


# ---------------------------------------------------------------- 音频活动
# 看视频 / 听音乐的时候人是不会碰键盘鼠标的，GetLastInputInfo 一直涨，
# 光靠它判断"空闲"就会在看片中途把屏幕切成节能模式。
# 所以再加一路信号：默认输出设备上到底有没有声音在放。
#
# 用的是 Core Audio 的 IAudioMeterInformation::GetPeakValue（返回 0.0~1.0 的峰值电平）。
# 覆盖浏览器（B站/YouTube/腾讯视频…）、本地播放器、音乐软件，全部通用。
ole32 = ctypes.windll.ole32

CLSCTX_ALL = 0x17


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]

    @classmethod
    def parse(cls, s):
        import uuid
        return cls.from_buffer_copy(uuid.UUID(s).bytes_le)


CLSID_MMDeviceEnumerator = _GUID.parse("BCDE0395-E52F-467C-8E3D-C4579291692E")
IID_IMMDeviceEnumerator = _GUID.parse("A95664D2-9614-4F35-A746-DE8DB63617E6")
IID_IAudioMeterInformation = _GUID.parse("C02216F6-8C67-4B5B-9D00-D008E73E0064")


def _com_fn(ptr, index, argtypes, restype=ctypes.c_long):
    """按 vtable 下标取一个 COM 方法（x64 下 stdcall 与默认调用约定一致）。"""
    if not ptr:
        return None
    vtbl = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
    proto = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)
    return proto(vtbl[index])


class _AudioMeter(object):
    """默认播放设备上的音量峰值表。"""

    def __init__(self):
        self.meter = None
        self.err = ""

    def open(self):
        try:
            try:
                ole32.CoInitializeEx(None, 0)   # COINIT_MULTITHREADED
            except Exception:
                pass
            p_enum = ctypes.c_void_p()
            hr = ole32.CoCreateInstance(
                ctypes.byref(CLSID_MMDeviceEnumerator), None, CLSCTX_ALL,
                ctypes.byref(IID_IMMDeviceEnumerator), ctypes.byref(p_enum))
            if (hr & 0xFFFFFFFF) != 0 or not p_enum.value:
                self.err = "CoCreateInstance hr=0x%08X" % (hr & 0xFFFFFFFF)
                return False

            # IMMDeviceEnumerator::GetDefaultAudioEndpoint(eRender, eConsole, &dev)
            p_dev = ctypes.c_void_p()
            fn = _com_fn(p_enum, 4, [ctypes.c_int, ctypes.c_int,
                                     ctypes.POINTER(ctypes.c_void_p)])
            hr = fn(p_enum, 0, 0, ctypes.byref(p_dev))
            self._release(p_enum)
            if (hr & 0xFFFFFFFF) != 0 or not p_dev.value:
                self.err = "GetDefaultAudioEndpoint hr=0x%08X" % (hr & 0xFFFFFFFF)
                return False

            # IMMDevice::Activate(&IID_IAudioMeterInformation, CLSCTX_ALL, NULL, &meter)
            p_meter = ctypes.c_void_p()
            fn = _com_fn(p_dev, 3, [ctypes.POINTER(_GUID), ctypes.c_uint,
                                    ctypes.c_void_p,
                                    ctypes.POINTER(ctypes.c_void_p)])
            hr = fn(p_dev, ctypes.byref(IID_IAudioMeterInformation),
                    CLSCTX_ALL, None, ctypes.byref(p_meter))
            self._release(p_dev)
            if (hr & 0xFFFFFFFF) != 0 or not p_meter.value:
                self.err = "Activate hr=0x%08X" % (hr & 0xFFFFFFFF)
                return False

            self.meter = p_meter
            self.err = ""
            return True
        except Exception as e:
            self.err = repr(e)
            return False

    @staticmethod
    def _release(p):
        try:
            fn = _com_fn(p, 2, [])          # IUnknown::Release
            fn(p)
        except Exception:
            pass

    def close(self):
        if self.meter:
            self._release(self.meter)
            self.meter = None

    def peak(self):
        """当前峰值电平 0.0~1.0；读不到返回 None。"""
        if not self.meter:
            return None
        try:
            fn = _com_fn(self.meter, 3, [ctypes.POINTER(ctypes.c_float)])
            f = ctypes.c_float(0.0)
            hr = fn(self.meter, ctypes.byref(f))
            if (hr & 0xFFFFFFFF) != 0:
                self.err = "GetPeakValue hr=0x%08X" % (hr & 0xFFFFFFFF)
                self.close()
                return None
            return float(f.value)
        except Exception:
            self.close()
            return None


_AUDIO = {"meter": None, "last_active": 0.0, "retry_at": 0.0, "err": ""}


def audio_peak():
    """默认输出设备的音量峰值（0.0~1.0）。拿不到返回 None。"""
    m = _AUDIO["meter"]
    if m is None:
        if time.time() < _AUDIO["retry_at"]:
            return None
        m = _AudioMeter()
        if not m.open():
            _AUDIO["err"] = m.err
            _AUDIO["retry_at"] = time.time() + 60   # 失败后一分钟内不再重试
            return None
        _AUDIO["meter"] = m
        _AUDIO["err"] = ""
    p = m.peak()
    if p is None:                    # 设备被切走/拔掉了，下次重建
        m.close()
        _AUDIO["meter"] = None
    return p


def audio_active(window=90.0, threshold=0.0005):
    """最近 window 秒内有没有放过声音。

    不是看"此刻是否有声"，而是看一段时间内有没有响过 —— 视频里的对白停顿、
    音乐曲间静音都不该被判成"人走了"。
    """
    now = time.time()
    p = audio_peak()
    if p is not None and p > threshold:
        _AUDIO["last_active"] = now
        return True
    return (now - _AUDIO["last_active"]) < window


def audio_error():
    return _AUDIO["err"]


# ---------------------------------------------------------------- 活跃屏幕
# 「用户正在用哪块屏」只有窗口和鼠标两个信号可用，两者回答的问题不一样：
#   窗口 -> 我正在操作的那个程序显示在哪（键盘操作时依然准确）
#   鼠标 -> 我的手在哪（前台是桌面这种"没在用程序"的情况下垫底）
MONITOR_DEFAULTTONEAREST = 2


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD),
                ("rcMonitor", wt.RECT),
                ("rcWork", wt.RECT),
                ("dwFlags", wt.DWORD),
                ("szDevice", wt.WCHAR * 32)]


# 这些窗口只是"桌面本身"，不是用户在操作的软件。
# 不解掉的话，一次 Tab 回到桌面就会把控制权甩回主屏。
_SHELL_CLASSES = {
    "Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd",
    "NotifyIconOverflowWindow", "MultitaskingViewFrame",
    "ForegroundStaging", "XamlExplorerHostIslandWindow",
    # 自己的主界面：点开查看状态不等于"我要在这块屏上干活"，
    # 算进去的话看一眼配置就把控制权拽过去了，关掉又要等好几秒才回来。
    "ScreenModeWindow",
}

user32.MonitorFromWindow.argtypes = [wt.HWND, wt.DWORD]
user32.MonitorFromWindow.restype = ctypes.c_void_p
user32.MonitorFromPoint.argtypes = [wt.POINT, wt.DWORD]
user32.MonitorFromPoint.restype = ctypes.c_void_p
user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
user32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]


def _device_of(hmon):
    if not hmon:
        return ""
    info = MONITORINFOEXW()
    info.cbSize = ctypes.sizeof(MONITORINFOEXW)
    if user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
        return info.szDevice
    return ""


def window_class(hwnd):
    if not hwnd:
        return ""
    buf = ctypes.create_unicode_buffer(128)
    user32.GetClassNameW(hwnd, buf, 128)
    return buf.value


def active_display():
    """用户此刻正在用的那块屏：返回 (device, 依据)。

    device 形如 ``\\\\.\\DISPLAY5``，和 ddc.enum_displays() 里存的名字一模一样，
    调用方直接相等比较就行，不用另做映射。判不出来返回 ("", "")。
    依据是 "window" / "cursor"，只用来写日志。

    **前台窗口优先**：它回答"我正在操作的程序显示在哪"。用键盘写文档、
    打游戏时鼠标可能一直停在另一块屏上，只看鼠标会长期判错。

    **前台是桌面/任务栏时退回鼠标**：这时 MonitorFromWindow 一律给主屏，
    但那是"什么都没在用"，不是"在主屏干活"，跟过去只会让控制权乱跳。
    """
    hwnd = user32.GetForegroundWindow()
    if hwnd and window_class(hwnd) not in _SHELL_CLASSES:
        dev = _device_of(user32.MonitorFromWindow(
            hwnd, MONITOR_DEFAULTTONEAREST))
        if dev:
            return dev, "window"
    pt = wt.POINT()
    if user32.GetCursorPos(ctypes.byref(pt)):
        dev = _device_of(user32.MonitorFromPoint(
            pt, MONITOR_DEFAULTTONEAREST))
        if dev:
            return dev, "cursor"
    return "", ""
