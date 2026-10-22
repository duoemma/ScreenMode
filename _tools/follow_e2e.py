# -*- coding: utf-8 -*-
"""跟随活跃屏 —— 真机端到端验证（不是桩，真的切前台窗口、真的写 gamma）。

和 follow_test.py 的分工：
  follow_test.py  纯逻辑，把 active_display 用桩替换掉，验证滞回/边界。
  follow_e2e.py   这一份：真的造两个窗口丢到两块屏上、真的把它们抬成前台，
                  真的让 App 的 tick() 跑起来，再用 GetDeviceGammaRamp 读回
                  两块屏的画面，确认"补偿只跟着活跃屏走、旧屏一点没动"。

跑之前必须先退出正在运行的屏效助手 —— 单实例锁是全局命名互斥体，
而且 DDC 连接同一时间只能有一个主人（不然读能力会返回"不支持"）。

    python _tools/follow_e2e.py

**会真的改显示器画面**，结束时无条件 restore_all() 还原。
"""
import ctypes
import json
import os
import shutil
import sys
import tempfile
import time
import traceback
from ctypes import wintypes as wt

SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# --------------------------------------------------------------- 测试专用数据目录
# 绝不能用用户真配置：这里会为了跑得快把滞回改成 1.5 秒、把 enabled 改成两台，
# 落到 real config 上就是把人家设置改了。
HOME = os.path.join(tempfile.gettempdir(), "screenmode-follow-e2e")
if os.path.isdir(HOME):
    shutil.rmtree(HOME, ignore_errors=True)
os.makedirs(HOME)
with open(os.path.join(SRC, "config.json"), encoding="utf-8") as f:
    _cfg = json.load(f)
_m = _cfg.setdefault("monitors", {})
_m["follow_active"] = True
_m["follow_stable_seconds"] = 1.5      # 测试里等不起 3 秒 × 好几轮
_m["enabled"] = [0, 1]
os.environ["SCREENMODE_HOME"] = HOME
with open(os.path.join(HOME, "config.json"), "w", encoding="utf-8") as f:
    json.dump(_cfg, f, ensure_ascii=False, indent=2)

sys.path.insert(0, SRC)
from screenmode import gamma as G          # noqa: E402
from screenmode import winapi              # noqa: E402
import screenmode.app as appmod            # noqa: E402

user32 = ctypes.WinDLL("user32", use_last_error=True)

user32.EnumDisplayMonitors.argtypes = [wt.HDC, ctypes.c_void_p,
                                       ctypes.c_void_p, wt.LPARAM]


class _MONITORINFOEXW(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT),
                ("rcWork", wt.RECT), ("dwFlags", wt.DWORD),
                ("szDevice", wt.WCHAR * 32)]


def real_monitors():
    """真实枚举 {} 拿到 设备名 -> 屏幕矩形，用来把窗口摆到指定屏上。"""
    out = []
    MI = _MONITORINFOEXW
    proto = ctypes.WINFUNCTYPE(wt.BOOL, ctypes.c_void_p, wt.HDC,
                               ctypes.POINTER(wt.RECT), wt.LPARAM)

    def cb(hmon, hdc, rect, data):
        info = MI()
        info.cbSize = ctypes.sizeof(MI)
        if user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            r = info.rcMonitor
            out.append({"device": info.szDevice,
                        "x": r.left, "y": r.top,
                        "w": r.right - r.left, "h": r.bottom - r.top,
                        "primary": bool(info.dwFlags & 1)})
        return True

    user32.EnumDisplayMonitors(None, None, proto(cb), 0)
    out.sort(key=lambda m: (not m["primary"], m["x"]))
    return out


k32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32.GetWindowThreadProcessId.argtypes = [wt.HWND,
                                            ctypes.POINTER(wt.DWORD)]
user32.AttachThreadInput.argtypes = [wt.DWORD, wt.DWORD, wt.BOOL]
user32.BringWindowToTop.argtypes = [wt.HWND]
user32.SetForegroundWindow.argtypes = [wt.HWND]
k32.GetCurrentThreadId.restype = wt.DWORD


def force_foreground(hwnd, tries=10):
    """把窗口抬成前台。

    直接 SetForegroundWindow 会被系统拒（而且拒绝时返回值不可靠，
    唯一可信的判据是拿 GetForegroundWindow 回来比）。标准解法是
    AttachThreadInput 挂到当前前台线程上再切 —— **不要用敲 ALT 那个偏方**：
    ALT 是很多软件的全局热键前缀（微信截图就是 Alt+A），
    在用户正在用电脑的时候往系统里注入 ALT，等于乱按人家的快捷键。
    """
    tid_me = k32.GetCurrentThreadId()
    for _ in range(tries):
        fg = user32.GetForegroundWindow()
        if fg == hwnd:
            return True
        tid_fg = user32.GetWindowThreadProcessId(fg, None) if fg else 0
        attached = False
        if tid_fg and tid_fg != tid_me:
            attached = bool(user32.AttachThreadInput(tid_me, tid_fg, True))
        try:
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
        finally:
            if attached:
                user32.AttachThreadInput(tid_me, tid_fg, False)
        time.sleep(0.1)
        if user32.GetForegroundWindow() == hwnd:
            return True
        time.sleep(0.1)
    return False


# -------------------------------------------------------------- 造两个真窗口
# 不用 tkinter：托管解释器里没带 tcl/tk，而这个测试恰恰必须跑在装了 pystray
# 的那个解释器里（要 import App）。直接用 Win32 建窗口，反而更贴近被测对象。
_WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wt.HWND, wt.UINT,
                              wt.WPARAM, wt.LPARAM)


class _WNDCLASSEXW(ctypes.Structure):
    _fields_ = [("cbSize", wt.UINT), ("style", wt.UINT),
                ("lpfnWndProc", _WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wt.HINSTANCE),
                ("hIcon", wt.HICON), ("hCursor", wt.HANDLE),
                ("hbrBackground", wt.HBRUSH), ("lpszMenuName", wt.LPCWSTR),
                ("lpszClassName", wt.LPCWSTR), ("hIconSm", wt.HICON)]


user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.DefWindowProcW.restype = ctypes.c_ssize_t
user32.CreateWindowExW.restype = wt.HWND
user32.CreateWindowExW.argtypes = [
    wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID]
user32.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, wt.UINT]
user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT,
                               wt.UINT]
user32.PeekMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT,
                                wt.UINT, wt.UINT]

WS_OVERLAPPEDWINDOW = 0x00CF0000
WS_VISIBLE = 0x10000000
SWP_NOZORDER, SWP_SHOWWINDOW = 0x0004, 0x0040
PM_REMOVE = 0x0001
_CLASS_NAME = "ScreenModeFollowE2E"
_wndprocs = []


def pump(ms=60):
    """转一圈消息泵。窗口不处理消息也能被判定，但画不出来、也抢不到前台。"""
    msg = wt.MSG()
    end = time.time() + ms / 1000.0
    while time.time() < end:
        while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        time.sleep(0.01)


def make_window(title, x, y, w, h):
    hinst = ctypes.WinDLL("kernel32").GetModuleHandleW(None)

    def proc(hwnd, msg, wp, lp):
        return user32.DefWindowProcW(hwnd, msg, wp, lp)

    wc = _WNDCLASSEXW()
    wc.cbSize = ctypes.sizeof(_WNDCLASSEXW)
    wc.lpfnWndProc = _WNDPROC(proc)
    wc.hInstance = hinst
    wc.lpszClassName = _CLASS_NAME
    _wndprocs.append(wc.lpfnWndProc)          # 别让回调被 GC 掉
    if not user32.RegisterClassExW(ctypes.byref(wc)):
        err = ctypes.get_last_error()
        if err != 1410:                        # 1410 = 类已注册，正常
            raise ctypes.WinError(err)
    hwnd = user32.CreateWindowExW(
        0, _CLASS_NAME, title, WS_OVERLAPPEDWINDOW | WS_VISIBLE,
        x, y, w, h, None, None, hinst, None)
    if not hwnd:
        raise ctypes.WinError(ctypes.get_last_error())
    user32.SetWindowPos(hwnd, None, x, y, w, h, SWP_NOZORDER | SWP_SHOWWINDOW)
    pump(150)
    return hwnd


OK, FAIL = [], []
OSD_BACKUP = {}          # device -> 测试前的 0xDC 值，收尾时写回

def check(name, cond, detail=""):
    if cond:
        OK.append(name)
        print("  [OK]   %s%s" % (name, ("  " + str(detail)) if detail else ""))
    else:
        FAIL.append(name)
        print("  [FAIL] %s%s" % (name, ("  " + str(detail)) if detail else ""))
    return cond


def ramp_mid(ch, dev):
    r = ch.read(dev)
    if not r:
        return None
    return (r[0][128], r[1][128], r[2][128])

# --------------------------------------------------------------------- 主流程
def main():
    mons = real_monitors()
    print("物理显示器：")
    for m in mons:
        print("  %-14s %dx%d @ (%d,%d)%s"
              % (m["device"], m["w"], m["h"], m["x"], m["y"],
                 "  [主屏]" if m["primary"] else ""))
    if len(mons) < 2:
        print("只有一台显示器，跟随逻辑无从验证。")
        return 2

    dev_a, dev_b = mons[0]["device"], mons[1]["device"]

    # ---------------------------------------------------------- 造两个窗口
    wins = []
    for i, m in enumerate(mons[:2]):
        hwnd = make_window("follow-e2e-%d" % i,
                           m["x"] + m["w"] // 2 - 300,
                           m["y"] + m["h"] // 2 - 150, 600, 300)
        wins.append({"hwnd": hwnd, "dev": m["device"]})
        print("  窗口 %d -> %s  hwnd=0x%X  class=%s"
              % (i, m["device"], hwnd, winapi.window_class(hwnd)))

    ch = G.GammaChannel(store_path=os.path.join(HOME, "gamma_base.json"))
    app = None
    try:
        # ============================================ A 判定层（真窗口真前台）
        print("\n[A] 活跃屏判定：前台窗口优先")
        w_a, w_b = wins[0], wins[1]
        ok = force_foreground(w_a["hwnd"])
        check("窗口A 能抬起前台", ok)
        dev, how = winapi.active_display()
        check("前台在 %s → 判定正确" % dev_a,
              (dev, how) == (dev_a, "window"), (dev, how))

        ok = force_foreground(w_b["hwnd"])
        check("窗口B 能抬起前台", ok)
        dev, how = winapi.active_display()
        check("前台在 %s → 判定正确" % dev_b,
              (dev, how) == (dev_b, "window"), (dev, how))

        print("\n[A2] 前台是桌面/任务栏时退回鼠标位置")
        # 真实桌面没法用脚本可靠地抢到前台（Win+D 在注入输入下经常被吞），
        # 所以把本测试窗口的类名临时塞进跳过名单，来打这条分支：判定走的是
        # 同一个 if 里的同一个 else，MonitorFromPoint 也是真的。
        pt0 = wt.POINT()
        user32.GetCursorPos(ctypes.byref(pt0))
        winapi._SHELL_CLASSES.add(_CLASS_NAME)
        try:
            force_foreground(w_b["hwnd"])
            m = mons[0]
            user32.SetCursorPos(m["x"] + m["w"] // 2, m["y"] + m["h"] // 2)
            dev, how = winapi.active_display()
            check("前台算作桌面时 → 改按鼠标位置判",
                  (dev, how) == (dev_a, "cursor"), (dev, how))
            check("窗口明明在 B 屏，也不会被判成 B",
                  dev != dev_b, dev)
        finally:
            winapi._SHELL_CLASSES.discard(_CLASS_NAME)
            user32.SetCursorPos(pt0.x, pt0.y)      # 把鼠标还给用户

        # ============================================ B 应用层（真 App 真 tick）
        print("\n[B] 控制目标转移：补偿跟着人走，旧屏保持原样")
        app = appmod.App()
        app.refresh_monitors()
        # 关掉自动识别：这一轮要单独验证"控制目标跟人跑"，不能让下面那些
        # 按前台程序匹配分组的逻辑顺手切模式，把画面搅浑。
        app.auto_detect = False
        check("App 认得两块屏", len(app.monitors) == 2,
              [x["device"] for x in app.monitors])
        check("跟随开关读到的是开", app.follow_active() is True)

        # 记住显示器原来的档位。下面会真的写 0xDC，跑完得写回去 ——
        # 画面补偿能 restore，OSD 档位可没有"原始值"可查，只能自己留底。
        for m in app.monitors:
            if m.get("mode_capable") and m.get("current") is not None:
                OSD_BACKUP[m["device"]] = int(m["current"])
                break
        if OSD_BACKUP:
            print("      0xDC 原值：%s" % OSD_BACKUP)

        # 起点：人站在 A 屏上
        force_foreground(w_a["hwnd"])
        app._follow_dev = ""
        app._follow_pending = ""
        app._track_active()
        check("启动定位直接采纳 A（不等滞回）",
              app._follow_dev == dev_a, app._follow_dev)
        check("控制目标就是 A", app.ddc_indices() == [0], app.ddc_indices())

        # 切到阅读模式，让 A 屏真的变暖 —— 这样后面才能看出"有没有动"
        app.switch_to("阅读模式", "e2e")
        time.sleep(0.6)
        base_a = ramp_mid(ch, dev_a)
        base_b = ramp_mid(ch, dev_b)
        print("      A=%s  B=%s" % (base_a, base_b))

        # 人走到 B 屏。每一拍都确认前台还在 B 上 ——
        # 测试是跑在用户自己正在用的电脑上的，微信/浏览器随时会抢走前台。
        force_foreground(w_b["hwnd"])
        t0 = time.time()
        moved_at = None
        stolen = 0
        while time.time() - t0 < 8.0:
            if user32.GetForegroundWindow() != w_b["hwnd"]:
                stolen += 1
                force_foreground(w_b["hwnd"])
            app.tick()
            if app._follow_dev == dev_b and moved_at is None:
                moved_at = time.time() - t0
                break
            time.sleep(0.15)
        print("      期间前台被抢 %d 次" % stolen)
        check("控制目标转移到 B", app._follow_dev == dev_b, app._follow_dev)
        check("转移耗时 ≥ 滞回 1.5 秒且不拖沓",
              moved_at is not None and 1.4 <= moved_at <= 4.5,
              "%.2fs" % (moved_at if moved_at is not None else -1))
        time.sleep(0.4)
        now_a = ramp_mid(ch, dev_a)
        now_b = ramp_mid(ch, dev_b)
        print("      A=%s  B=%s" % (now_a, now_b))
        check("旧屏 A 一点没动（保持上一次的样子）", now_a == base_a, base_a)
        check("活跃屏 B 被补上了暖色", now_b != base_b, (base_b, now_b))
        check("B 是往暖了走（R 通道抬、B 通道压）",
              now_b and base_b and now_b[0] > base_b[0] and now_b[2] < base_b[2],
              (base_b, now_b))

        # ============================================ C 滞回（真抖动）
        print("\n[C] 滞回：在 A/B 之间来回晃不超过 1.5 秒，不该来回切")
        before = app._follow_dev
        for _ in range(3):
            force_foreground(w_a["hwnd"])
            app.tick()
            time.sleep(0.35)
            force_foreground(w_b["hwnd"])
            app.tick()
            time.sleep(0.35)
        check("抖动期间控制目标没变", app._follow_dev == before, app._follow_dev)
        # 停在 A 上再拍一拍：这一刻 A 是"待定"，B 还是控制目标
        force_foreground(w_a["hwnd"])
        app.tick()
        check("抖动只是记成「待定」，没真切",
              app._follow_dev == before and app._follow_pending == dev_a,
              (app._follow_dev, app._follow_pending))
        check("待定期间活跃屏 B 的画面也没被撤",
              ramp_mid(ch, dev_b) == now_b, ramp_mid(ch, dev_b))

        # ============================================ D 关掉跟随回到勾选逻辑
        print("\n[D] 关掉跟随 → 回到按勾选控制")
        app.set_follow_active(False)
        check("follow_active 已关", app.follow_active() is False)
        check("定位状态被清空", app._follow_dev == "", app._follow_dev)
        check("控制目标回到勾选的两台", sorted(app.ddc_indices()) == [0, 1],
              app.ddc_indices())

    except Exception:
        traceback.print_exc()
        FAIL.append("异常中断")
    finally:
        print("\n[Z] 收尾：还原画面")
        try:
            if app is not None:
                app.gch.restore_all()
                app.gch.close()
            else:
                ch.restore_all()
            print("  已 restore_all()")
        except Exception as e:
            print("  还原失败：%r" % (e,))
        try:
            # 把 OSD 档位写回测试前的值 —— gamma 能恢复，档位只能自己记
            if app is not None and OSD_BACKUP:
                for _dev, val in OSD_BACKUP.items():
                    app.ddc.set_mode(val)
                print("  已写回 0xDC：%s" % OSD_BACKUP)
        except Exception as e:
            print("  档位还原失败：%r" % (e,))
        try:
            if app is not None:
                app.ddc.close()
        except Exception:
            pass
        try:
            ch.close()
        except Exception:
            pass
        try:
            for w in wins:
                user32.DestroyWindow(w["hwnd"])
        except Exception:
            pass
        # 测试目录里全是本机专属基线，留着没意义
        shutil.rmtree(HOME, ignore_errors=True)

    print("\n结果：OK %d / FAIL %d" % (len(OK), len(FAIL)))
    for n in FAIL:
        print("  未通过：%s" % n)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
