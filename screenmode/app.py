# -*- coding: utf-8 -*-
"""屏效助手 —— 控制器。

线程模型：
  主线程      : 主窗口 UI + 切换确认弹窗（Win32 窗口必须在创建它的线程里收消息）
  轮询线程    : 读前台程序 / 空闲时间 / 写 DDC（有看门狗，卡住自动重启）
  看门狗线程  : 45 秒收不到心跳就重建轮询线程和 DDC 连接
  托盘线程    : pystray
任何一处卡死都不会拖死其他部分。
"""
import collections
import os
import sys
import threading
import time
from datetime import datetime

import pystray
from PIL import Image, ImageDraw

from screenmode import (APP_NAME, VERSION, app_dir, apply as apply_mod,
                        config, ddc, gamma as G, hdr as HDR, matcher,
                        presets, winapi)
from screenmode.ddc import DDCController, list_monitors
from screenmode.ui import theme as T

DRY_RUN = "--dry-run" in sys.argv
LOG_MAX_LINES = 2000
_UNSET = object()          # "这个分组还没问过" 的哨兵值

# 这些是常驻的系统外壳进程，桌面/开始菜单/输入法之类。
# 手动切换时如果前台正好是它们，"等它关闭再恢复识别"永远等不到 —— 不能当挂靠对象。
_SHELL_PROCS = {
    "explorer.exe", "dwm.exe", "sihost.exe", "shellhost.exe",
    "shellexperiencehost.exe", "startmenuexperiencehost.exe",
    "searchhost.exe", "textinputhost.exe", "applicationframehost.exe",
    "lockapp.exe", "widgets.exe", "widgetservice.exe", "ctfmon.exe",
}

# 托盘动作
TRAY_OPEN = 1
TRAY_PAUSE = 2
TRAY_ASK = 3
TRAY_STARTUP = 4
TRAY_QUIT = 5
TRAY_AUTO = 6


def self_process_names():
    """屏效助手自己的进程名（小写）。

    自己的窗口（主界面 / 切换弹窗）被点开时也会变成"前台程序"，
    但它不是用户真正在用的软件 —— 必须排除掉，
    否则一开界面就被当成"不在任何分组里"，立刻切回默认情景。
    """
    names = {"屏效助手.exe", "screenmode.exe"}
    try:
        names.add(os.path.basename(sys.executable).lower())
    except Exception:
        pass
    if getattr(sys, "frozen", False):
        try:
            names.add(os.path.basename(sys.executable).lower())
        except Exception:
            pass
    return names


BASE_DIR = app_dir()
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
LOG_PATH = os.path.join(BASE_DIR, "app.log")


class App:
    def __init__(self):
        self.cfg, created = config.load(CONFIG_PATH)
        self.events = collections.deque(maxlen=8)
        self.monitors = []
        self.ddc = DDCController(indices=self.cfg_indices())
        # Gamma 兜底通道：DDC 写不动的屏靠它模拟情景模式。
        # 不调用任何 API 直到第一次真正要用，所以启动零开销。
        self.gch = G.GammaChannel(
            store_path=os.path.join(BASE_DIR, "gamma_base.json"))
        self.last_apply = {}        # 上次切换的完整结果（给状态页显示）
        self._hdr_notice = {}       # device -> 上次提醒 HDR 的时间（节流）
        self._hdr_state = {}        # device -> 是否 HDR 开启（缓存，5 秒过期）
        self._hdr_at = 0.0
        self.applied_mode = None
        self.applied_value = None
        self.pause_until = 0.0
        self.manual_target = None
        self.running = True
        self.status = {}
        self.ui = None
        self.main_hwnd = None
        self.icon = None

        self.idle_active = False
        self.pre_idle_mode = None
        # 每个分组只问一次：{分组 id: 用户选的模式}；"" 表示"保持不变"
        self._ask_choice = {}
        self._ask_resolved_key = None
        self._ask_resolved_mode = None
        self._pending_key = None
        self._pending_since = 0.0
        self._override_streak = 0
        # DDC/CI 读一次要 ~60ms（走 I2C，会卡住显示栈），全屏游戏里这 60ms
        # 足够掉好几帧。没必要每一轮轮询都读，隔一段时间查一次完全够用。
        self._override_at = 0.0
        self._warned = set()
        self._last_fg = None
        self._last_fg_at = 0.0
        self._last_via = None

        # 「刚才命中的那个程序」—— 用来判断前台窗口是短暂跳走了，还是真的关了。
        # 全屏游戏在前台时，前台窗口会周期性跳到别的进程上（加载画面、Steam
        # 覆盖层、系统弹窗），下一轮又跳回来。如果每一轮都跟着切回默认模式，
        # 显示器就会反复换画质档位、画面一下一下地断 —— 玩家体感就是"卡顿"。
        self._grp_id = None
        self._grp_name = ""
        self._grp_proc = ""
        self._grp_fs = False        # 命中时那个窗口是不是全屏（游戏）
        self._grp_leave = 0.0       # 什么时候开始"前台不在这个分组"
        self._leave_log_at = 0.0    # 上面那条日志的节流时间
        self._idle_log_at = 0.0     # "在看视频所以不算空闲"那条日志的节流
        self._alive_at = 0.0        # "进程还在吗"的缓存
        self._alive_val = False
        self._alive_exe = ""

        # 自动识别模式：True = 跟着前台程序自动切；False = 手动模式（只在运行期有效，
        # 不写进配置 —— 否则"手动模式下退出程序"会让下次启动也一直不动）
        self.auto_detect = True
        self._self_procs = self_process_names()
        self._hold_proc = ""        # 手动模式挂靠的程序，它退出后自动恢复识别
        self._last_proc = ""        # 最近一个"不是自己"的前台进程 / 标题
        self._last_title = ""

        # 跟随活跃屏：_follow_dev 是当前认定的"用户正在用的那块屏"，
        # _follow_pending 是刚出现、还没稳定够的候选项（滞回用）。
        self._follow_dev = ""
        self._follow_pending = ""
        self._follow_pending_at = 0.0
        self._follow_how = ""       # 最近一次判定依据，状态卡上写给人看

        # 线程
        self._worker_gen = 0
        self._heartbeat = time.time()
        self._dialog_req = None
        self._dialog_event = threading.Event()

        if created:
            self.log("首次运行：已生成默认配置（3 个分组 / %d 个应用）"
                     % config.all_app_count(self.cfg))
        else:
            # 老配置里的内置模式没有画面补偿参数 -> 补上，否则升级后
            # DDC 写不动的副屏还是不会有任何变化。
            n = config.backfill_gamma(self.cfg)
            if n:
                self.save_config()
                self.log("已为 %d 个内置模式补上默认画面补偿参数"
                         "（DDC 写不动的屏切换时会自动用它）" % n)
        if DRY_RUN:
            self.log("*** 演练模式：只写日志，不会真正改显示器 ***")

        # 绿色版：整个文件夹随时可能被挪走/改名，自启项得跟上当前 exe。
        # 不校正的话，开机启动的是旧位置那份（可能已经不存在，或者是个副本，
        # 起来后还会和手上这个抢单实例锁，表现为"点了图标没反应"）。
        try:
            if winapi.ensure_startup_path():
                # 写进注册表的是 exe 的完整路径，日志就照这个记 ——
                # 以前这里打的是数据目录（BASE_DIR），排查时对着
                # `...\Temp\xxx` 这种路径完全看不出自启指向哪儿。
                self.log("开机自启项已改为指向当前位置：%s" % sys.executable)
        except Exception:
            pass

    # ------------------------------------------------------------ 日志
    def log(self, msg):
        stamp = datetime.now().strftime("%H:%M:%S")
        line = "[%s] %s" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
        self.events.append((stamp, msg))
        try:
            print(line)
        except Exception:
            pass
        try:
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass
        try:
            self._trim_log()
        except Exception:
            pass

    def _trim_log(self):
        try:
            if os.path.getsize(LOG_PATH) < 400 * 1024:
                return
            with open(LOG_PATH, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()[-LOG_MAX_LINES:]
            with open(LOG_PATH, "w", encoding="utf-8") as f:
                f.writelines(lines)
        except Exception:
            pass

    def notify(self, title, msg):
        if self.icon is not None:
            try:
                self.icon.notify(msg, title)
            except Exception:
                pass

    # ------------------------------------------------------------ 配置
    def save_config(self):
        try:
            config.save(CONFIG_PATH, self.cfg)
            return True
        except Exception as e:
            self.log("保存配置失败：%r" % (e,))
            return False

    def mode_names(self):
        return config.mode_names(self.cfg)

    def mode_color(self, name):
        return config.mode_color(self.cfg, name)

    def reset_ask_state(self):
        """清空"问过没"的记忆 —— 配置改了以后下次要重新确认一遍。"""
        self._ask_choice = {}
        self._ask_resolved_key = None
        self._ask_resolved_mode = None
        self._pending_key = None
        self._clear_group()

    # ------------------------------------------------------------ 显示器
    def cfg_indices(self):
        """配置里勾选的显示器序号。没勾（空）就返回 None，表示"所有能控的"。"""
        m = self.cfg.get("monitors") or {}
        raw = m.get("enabled")
        if isinstance(raw, list) and raw:
            return [int(i) for i in raw]
        return None

    def ddc_indices(self):
        """实际要控制的显示器序号列表。

        配置里没勾 -> 所有检测到的显示器（接几台控几台）。
        **勾了但已经拔掉的屏要剔掉**：配置里留着旧序号，日志就会写
        「控制目标：共 3 台」而你明明只插了 2 台，看着像程序数错了；
        DDC 那边也会对不存在的序号反复报错。

        「跟随活跃屏」打开时这两条都不算数 —— 控的就是用户此刻在用的那台。
        """
        if self.follow_active():
            fi = self.follow_index()
            if fi is not None:
                return [fi]
        picked = self.cfg_indices()
        live = set(m["index"] for m in self.monitors)
        if picked is not None:
            kept = [i for i in picked if i in live]
            if kept:
                return kept
            if live:
                # 勾的那几台全拔了，就当没勾过，免得整个程序静默不干活
                self.log("原来勾选的显示器都不在了，改为控制当前 %d 台"
                         % len(live))
        return [m["index"] for m in self.monitors] or [0]

    # ------------------------------------------------------ 跟随活跃屏
    def follow_active(self):
        """要不要跟着「用户正在用的那块屏」走。"""
        return bool((self.cfg.get("monitors") or {}).get("follow_active"))

    def follow_stable_seconds(self):
        try:
            return float((self.cfg.get("monitors") or {}).get(
                "follow_stable_seconds", 3.0))
        except (TypeError, ValueError):
            return 3.0

    def _index_of_device(self, dev):
        for m in self.monitors or []:
            if m.get("device") == dev:
                return int(m["index"])
        return None

    def follow_index(self):
        """跟随模式下当前该控哪一台（还没定位到时返回 None）。"""
        if not self.follow_active():
            return None
        return self._index_of_device(self._follow_dev)

    def _track_active(self):
        """看用户在哪个屏上，必要时把控制目标挪过去。

        三条规则（都是按用户选的来的）：
          ① 前台窗口所在屏为准；前台是桌面/任务栏时退回鼠标位置。
             只看窗口的话，从桌面点个图标就把控制权甩回主屏；只看鼠标的话，
             用键盘写文档、打游戏时鼠标停着不动，会长期判错。
          ② 候选屏要**连续稳定 N 秒**才真的转移。鼠标划到另一块屏取个东西
             就重切一次 DDC，画面会闪 —— 这是这个功能唯一真正的坑。
          ③ 原来那块屏**保持上一次的样子**，不撤补偿（见 _adopt_active）。
        """
        if not self.follow_active() or not self.monitors:
            return
        dev, how = winapi.active_display()
        if not dev:
            return
        idx = self._index_of_device(dev)
        if idx is None:
            # 不认识的屏（刚插上还没重新检测），先别乱切
            return

        if not self._follow_dev:
            # 启动后第一次定位：直接采纳，不用等滞回 ——
            # 否则程序刚起来那几秒是"没有控制目标"的空窗。
            self._follow_dev = dev
            self._adopt_active(idx, how, first=True)
            return

        if dev == self._follow_dev:
            self._follow_pending = ""
            return

        now = time.time()
        if dev != self._follow_pending:
            self._follow_pending = dev
            self._follow_pending_at = now
            return
        if now - self._follow_pending_at < self.follow_stable_seconds():
            return

        self._follow_dev = dev
        self._follow_pending = ""
        self._adopt_active(idx, how)

    def _adopt_active(self, idx, how="", first=False):
        """把控制目标交给 idx，并把当前模式补到那块屏上。

        **旧屏什么都不做** —— 它保持最后一次切到的样子。这是用户明确要的
        （"主屏保持上次检测后的模式"），所以调 apply_mode 时要带
        keep_others=True，否则那边的清理逻辑会把旧屏的补偿当成残留撤掉。
        """
        self.rebuild_ddc(log=False)
        self._follow_how = how
        self.log("控制目标跟随到显示器 %d（依据：%s）%s"
                 % (idx + 1,
                    "前台窗口" if how == "window" else "鼠标位置",
                    "（启动时定位）" if first else ""))

        name = (self.applied_mode
                or (self.cfg.get("return_default") or {}).get("mode") or "")
        mode = config.mode_by_name(self.cfg, name) if name else None
        if not mode or not config.mode_channels(mode):
            return
        try:
            res = apply_mod.apply_mode(
                mode, ddc=self.ddc, gch=self.gch, monitors=self.monitors,
                use_gamma=config.gamma_enabled(self.cfg), verify=True,
                controlled=[idx], keep_others=True)
        except Exception as e:
            self.log("跟随切换失败：%r" % (e,))
            return
        self.last_apply = res
        self.log("已把【%s】补到显示器 %d：%s"
                 % (name, idx + 1, res.get("summary") or ""))

    def set_follow_active(self, on):
        """开/关「跟随活跃屏」。关掉时清掉定位，回到勾选逻辑。"""
        m = self.cfg.setdefault("monitors", {})
        m["follow_active"] = bool(on)
        self._follow_dev = ""
        self._follow_pending = ""
        self.rebuild_ddc(log=False)
        self.save_config()
        self.log("跟随活跃屏：%s" % ("开" if on else "关"))
        if on:
            self._track_active()    # 立刻定位一次，别等下一个轮询
        else:
            self.sync_applied_from_monitor()
        return True

    def forced_vcp_map(self):
        """config 里显式指定"某台用哪个 VCP 码"（{"1": 20}）。"""
        raw = (self.cfg.get("monitors") or {}).get("vcp") or {}
        out = {}
        for k, v in raw.items():
            try:
                out[int(k)] = int(v)
            except (TypeError, ValueError):
                pass
        return out

    def rebuild_ddc(self, log=True):
        indices = self.ddc_indices()
        try:
            self.ddc.close()
        except Exception:
            pass
        self.ddc = DDCController(indices=indices,
                                 forced_vcp=self.forced_vcp_map())
        if log:
            self.log("控制目标：共 %d 台 —— %s"
                     % (len(indices),
                        self.ddc.describe(config.gamma_enabled(self.cfg))
                        or "无"))

    # ------------------------------------------------------------ 引导配置
    def setup_done_map(self):
        raw = (self.cfg.get("monitors") or {}).get("setup_done") or {}
        out = {}
        for k, v in raw.items():
            try:
                out[int(k)] = bool(v)
            except (TypeError, ValueError):
                pass
        return out

    def monitors_needing_setup(self):
        """还没走过引导、且 DDC 通的显示器。

        注意不能拿「支不支持 0xDC」来判断已配置 —— 有的屏压根不报 0xDC，
        但它的情景模式挂在厂商私有码上，只有引导跑一遍才知道。
        """
        done = self.setup_done_map()
        out = []
        for m in self.monitors:
            if not m["controllable"]:
                continue
            if done.get(m["index"]):
                continue
            # 能自动识别 0xDC 的屏不用引导 —— 它的档位就是 modes[].vcp 里
            # 已经记好的那些值。只有"菜单里有模式、DDC 却报不出来"的屏才需要。
            if m["mode_capable"]:
                continue
            out.append(m)
        return out

    def open_monitor_wizard(self, index=None):
        """打开「添加显示器引导」。返回向导结果。"""
        from screenmode.ui import wizard
        self.refresh_monitors()
        win = wizard.AddMonitorWizard(self, index=index)
        res = win.run()
        if res:
            if res.get("use_gamma"):
                chan = "画面补偿"
            elif res.get("mode_vcp"):
                chan = "0x%02X" % res["mode_vcp"]
            else:
                chan = "亮度/对比度"
            self.log("显示器 %d 配置完成（通道 %s，记录 %d 个模式）"
                     % (res.get("index", 0) + 1, chan, res.get("records", 0)))
            self.refresh_monitors()
            self.rebuild_ddc()
        else:
            # 用户取消/跳过 -> 记下来，别每次都弹
            self.mark_setup_done(index)
        return res

    def mark_setup_done(self, index):
        """标记某台屏不用再提示引导（用户主动跳过时用）。"""
        if index is None:
            return
        m = self.cfg.setdefault("monitors", {})
        m.setdefault("setup_done", {})[str(int(index))] = True
        try:
            self.save_config()
        except Exception:
            pass

    def refresh_monitors(self):
        self.monitors = list_monitors(self.forced_vcp_map())
        # 显示器换了/插拔了，Gamma 通道的枚举和 DC 句柄也要跟着刷新
        try:
            self.gch.outputs(refresh=True)
            self.gch.close()
        except Exception:
            pass
        # label 里已经写清每台的能力（「不支持 DDC」/「不支持情景模式」/
        # 「改用 0x14 色彩预设」），所以这里只补一句当前值，别再重述一遍。
        for m in self.monitors:
            if m["mode_capable"]:
                self.log("检测到显示器：%s（%s 当前 %s）"
                         % (m["label"],
                            ddc.VCP_NAMES.get(m["mode_vcp"], hex(m["mode_vcp"])),
                            m["current"]))
            else:
                self.log("检测到显示器：%s" % m["label"])
        try:
            self.log("画面通道：%s" % self.hdr_report())
        except Exception:
            pass
        return self.monitors

    def monitor_labels(self):
        """正在控制的所有显示器的显示名。"""
        idxs = self.ddc_indices()
        names = []
        for i in idxs:
            for m in self.monitors:
                if m["index"] == i:
                    names.append(m["label"])
                    break
        return names or ["未检测到可控制显示器"]

    def monitor_label(self, index=None):
        """状态卡上显示的"正在控制哪几台"。"""
        if index is not None:
            for m in self.monitors:
                if m["index"] == index:
                    return m["label"]
            return "未检测到可控制显示器"
        labels = self.monitor_labels()
        if self.follow_active():
            # 跟随模式下要让人一眼看出「这台是跟着我在走的那台」，
            # 否则状态卡写个「显示器 2」看不出任何名堂
            how = {"window": "前台窗口", "cursor": "鼠标位置"}.get(
                self._follow_how, "定位中")
            return "%s · 跟随中（%s）" % (labels[0], how)
        if len(labels) == 1:
            return labels[0]
        return "共 %d 台（%s）" % (
            len(labels),
            "、".join(l.split(" · ")[0] for l in labels))

    def set_monitor_indices(self, indices):
        """设置要控制哪几台（空列表 = 所有能控的）。"""
        indices = [int(i) for i in indices]
        self.cfg.setdefault("monitors", {})["enabled"] = indices
        self.rebuild_ddc(log=False)
        self.save_config()
        self.release_uncontrolled()
        self.sync_applied_from_monitor()
        self.reset_ask_state()
        self.log("控制目标已更新：%s"
                 % (self.ddc.describe(config.gamma_enabled(self.cfg)) or "无"))

    def release_uncontrolled(self):
        """把「已经不归我们管」的屏上的画面补偿撤掉。

        用户在主界面取消勾选某台屏时，那台屏可能正套着上一个模式的补偿。
        不撤的话它会定格在那个色调上 —— 用户看到的正是
        「我明明没勾它，它怎么还是变暖了」，其实就是**变过之后没恢复**。
        返回被恢复的显示器列表。
        """
        try:
            applied = list(self.gch.applied_devices() or [])
        except Exception:
            return []
        keep = set(self.ddc_indices())
        rev = {}
        for m in self.monitors or []:
            if m.get("device"):
                rev[m["device"]] = m["index"]
        freed = []
        for dev in applied:
            idx = rev.get(dev)
            if idx is not None and idx in keep:
                continue            # 还在控制范围里，别动
            try:
                if self.gch.restore(dev):
                    freed.append(dev)
            except Exception:
                pass
        if freed:
            self.log("已撤销 %d 台不再控制的屏的画面补偿" % len(freed))
        return freed

    def set_monitor_index(self, index):
        """兼容旧调用：只控制一台。"""
        self.set_monitor_indices([int(index)])

    def sync_applied_from_monitor(self):
        """把「当前模式」对齐到显示器实际值。"""
        actual = None if DRY_RUN else self.ddc.get_mode()
        if actual is None:
            # 受控的那几台读不到档位（走画面补偿的屏压根没有 0xDC），
            # 就借一台读得到的来认——**只读，不写**，不会改人家。
            # 不做这一步的话，只勾副屏时状态卡会一直显示「当前模式未知」，
            # 看着像程序没干活。
            for m in self.monitors or []:
                if m.get("mode_capable") and m.get("current") is not None:
                    actual = m["current"]
                    break
        if actual is None:
            return
        self.applied_value = actual
        self.applied_mode = None
        for name in self.mode_names():
            if config.mode_vcp(self.cfg, name) == actual:
                self.applied_mode = name
                break
        self.log("显示器当前值 %s（%s）"
                 % (actual, self.applied_mode or "未登记的模式"))

    # ------------------------------------------------------------ 切换
    def switch_to(self, mode_name, reason=""):
        mode = config.mode_by_name(self.cfg, mode_name) or {}
        value = config.mode_vcp(self.cfg, mode_name)
        channels = config.mode_channels(mode)
        if not channels:
            if mode_name not in self._warned:
                self._warned.add(mode_name)
                self.log("模式【%s】还没有记录任何通道，已跳过"
                         "（请到「显示器与模式」里配一个档位或画面补偿）"
                         % mode_name)
            return False
        if self.applied_value == value and self.applied_mode == mode_name:
            return True
        if DRY_RUN:
            self.log("[演练] 切换到【%s】(0xDC=%s / %s) %s"
                     % (mode_name, value, "、".join(channels), reason))
            self.applied_mode, self.applied_value = mode_name, value
            self._update_icon()
            return True

        res = self._apply_channels(mode)
        self.last_apply = res
        if res.get("ok"):
            extra = ""
            if res.get("ddc_unverified"):
                extra = "；第 %s 台写入被显示器忽略，已改用画面补偿" % (
                    "、".join(str(i + 1) for i in res["ddc_unverified"]))
            elif res.get("ddc_failed"):
                extra = "；第 %s 台没有可用通道" % "、".join(
                    str(i + 1) for i in res["ddc_failed"])
            self.log("切换到【%s】(0xDC=%s) %s → %s%s"
                     % (mode_name, value, reason, res["summary"], extra))
            self.applied_mode, self.applied_value = mode_name, value
            # 刚刚写过一次了，别马上又读一遍
            self._override_at = time.time()
            self._warn_hdr(res)
            self._update_icon()
            return True
        self.last_apply = res
        self.log("切换【%s】失败：%s%s"
                 % (mode_name, res.get("summary") or "",
                    ("；" + res["errors"][0]) if res.get("errors") else ""))
        self._warn_hdr(res)
        return False

    def _apply_channels(self, mode):
        """走混合通道把这个模式落下（DDC 真值 -> Gamma 补偿）。

        单独抽出来，是为了让「切换测试」「恢复画面」「托盘切换」
        都走同一套判定，不会出现「有的入口能用有的不能用」。
        """
        try:
            return apply_mod.apply_mode(
                mode, ddc=self.ddc, gch=self.gch, monitors=self.monitors,
                use_gamma=config.gamma_enabled(self.cfg), verify=True,
                controlled=self.ddc_indices(),
                # 跟随模式下旧屏要"保持最后一次的样子"，切场景时也不能被清掉
                keep_others=self.follow_active())
        except Exception as e:
            return {"ok": False, "summary": "通道调度异常",
                    "errors": [repr(e)], "per_state": {},
                    "ddc_written": [], "ddc_unverified": [], "ddc_failed": [],
                    "gamma_applied": [], "gamma_skipped": [],
                    "gamma_failed": [], "hdr_on": []}

    def _warn_hdr(self, res):
        """这台屏正处在高级颜色模式，画面补偿写进去也不生效 —— 提醒一次。

        只提醒，不自动去关：HDR 是用户为了游戏/影片主动开的，
        替人关掉比不生效更糟。每块屏 10 分钟最多提醒一次。

        文案不说死"HDR"：`advancedColorEnabled` 在 Windows 的
        「自动管理颜色」下同样是置位的，实际可能是 ACM 而不是 HDR。
        """
        if not config.gamma_warn_hdr(self.cfg):
            return
        now = time.time()
        fresh = []
        for dev in res.get("hdr_on") or []:
            if now - self._hdr_notice.get(dev, 0) < 600:
                continue
            self._hdr_notice[dev] = now
            fresh.append(dev)
        if not fresh:
            return
        names = "、".join(self.hdr_labels(fresh)) or "这台显示器"
        self.log("提示：%s 处于高级颜色模式（HDR 或自动管理颜色），"
                 "画面补偿在这种模式下不生效" % names)
        self.notify("画面补偿被高级颜色挡住",
                    "%s 正处在高级颜色模式，画面补偿写进去不会生效。\n"
                    "需要补偿效果的话，到 设置 → 系统 → 显示 → 高级显示 里\n"
                    "关掉 HDR 或「自动管理颜色」。" % names)

    def restore_gamma(self, all_devices=True):
        """恢复显卡查找表（撤销所有画面补偿）。"""
        try:
            if all_devices:
                ok = self.gch.restore_all()
            else:
                ok = True
                for d in self.gch.devices():
                    ok = self.gch.restore(d) and ok
        except Exception as e:
            self.log("恢复原始画面失败：%r" % (e,))
            return False
        self.log("已恢复原始画面%s" % ("" if ok else "（部分显示器未成功）"))
        self.last_apply = {}
        return ok

    def do_manual(self, mode_name):
        """UI / 托盘里的手动切换：立即切，然后进入「手动模式」。

        手动模式会挂靠当前正在用的那个程序 —— 只要它还没关，
        就不再自动切换；它一关掉，自动识别马上自己同步开启（见 tick）。
        """
        self.manual_target = mode_name
        hold = (self._last_proc or "").lower()
        if not hold or self._is_self(hold) or hold in _SHELL_PROCS:
            hold = ""
        minutes = int(self.cfg.get("manual_override_pause_minutes", 10))
        if hold:
            self.auto_detect = False
            self._hold_proc = hold
            self.pause_until = 0.0
            self.log("手动切换到【%s】，进入手动模式（%s 关闭后自动恢复识别）"
                     % (mode_name, hold))
        else:
            # 桌面上点的（explorer 之类常驻进程）：退回"暂停 N 分钟"
            self.auto_detect = True
            self._hold_proc = ""
            if minutes > 0:
                self.pause_until = time.time() + minutes * 60
            self.log("手动切换到【%s】，自动切换暂停 %d 分钟"
                     % (mode_name, minutes))
        self.refresh_menu()

    def enable_auto(self, reason=""):
        """切回自动识别模式：清掉手动 / 暂停状态，立刻重新识别当前前台程序。"""
        was_off = (not self.auto_detect) or self.paused()
        self.auto_detect = True
        self._hold_proc = ""
        self.pause_until = 0.0
        self.manual_target = None
        self.idle_active = False
        self.pre_idle_mode = None
        self._override_streak = 0
        self._last_fg = None          # 允许重新记一条前台日志
        self.reset_ask_state()        # 当前应用重新走一遍识别
        if was_off or reason:
            self.log("已切回自动识别模式%s"
                     % ("（%s）" % reason if reason else ""))
            self.notify("自动识别模式", "已恢复自动切换，下次切换前台程序就会识别")
        self._update_status()
        self.refresh_menu()

    def preview_mode(self, mode_name):
        """测试切换到某模式（不暂停自动切换）。"""
        ok = self.switch_to(mode_name, "(测试)")
        self.notify("测试切换", "已切换到【%s】" % mode_name if ok
                    else "切换失败，请看日志")
        return ok

    # ------------------------------------------------------------ 弹窗调度
    def request_dialog(self, suggested, options, timeout, context):
        """轮询线程调用；弹窗在主线程里弹，这里是同步等待。"""
        if not self.main_hwnd:
            return suggested
        self._dialog_req = {"suggested": suggested, "options": options,
                            "timeout": timeout, "context": context,
                            "result": None}
        self._dialog_event.clear()
        self._heartbeat = time.time()
        from screenmode.ui.mainwindow import WM_APP_DIALOG
        try:
            winapi.user32.PostMessageW(self.main_hwnd, WM_APP_DIALOG, 0, 0)
        except Exception as e:
            self.log("弹窗请求失败：%r" % (e,))
            return suggested
        ok = self._dialog_event.wait(timeout + 25)
        req = self._dialog_req
        self._dialog_req = None
        if not ok:
            self.log("弹窗没有响应，按建议模式处理")
            return suggested
        return (req or {}).get("result")

    def take_dialog_request(self):
        return self._dialog_req

    def finish_dialog_request(self, chosen):
        if self._dialog_req is not None:
            self._dialog_req["result"] = chosen
        self._dialog_event.set()

    # ------------------------------------------------------------ 轮询
    def start_worker(self, fresh_ddc=False):
        self._worker_gen += 1
        gen = self._worker_gen
        if fresh_ddc:
            self.rebuild_ddc(log=False)
            self.log("看门狗：已重建 DDC 连接（%s）"
                     % (self.ddc.describe() or "无"))
        threading.Thread(target=self._worker_loop, args=(gen,),
                         daemon=True).start()

    def _worker_loop(self, gen):
        self.log("轮询线程启动 (#%d)" % gen)
        while self.running and gen == self._worker_gen:
            try:
                self.tick()
            except Exception as e:
                self.log("轮询出错：%r" % (e,))
            self._heartbeat = time.time()
            if gen != self._worker_gen:
                break
            time.sleep(max(0.5, float(self.cfg.get("poll_seconds", 1.5))))
        self.log("轮询线程退出 (#%d)" % gen)

    def _watchdog_loop(self):
        while self.running:
            time.sleep(5)
            try:
                if self.running and time.time() - self._heartbeat > 45:
                    self.log("看门狗：轮询线程 %.0f 秒无心跳，重启中"
                             % (time.time() - self._heartbeat))
                    self.start_worker(fresh_ddc=True)
            except Exception:
                pass

    def paused(self):
        return time.time() < self.pause_until

    def _is_self(self, proc):
        """是不是屏效助手自己的窗口在前台。"""
        return bool(proc) and proc.lower() in self._self_procs

    def auto_active(self):
        """自动识别是否真的在起作用（开着且没被暂停）。"""
        return self.auto_detect and not self.paused()

    def tick(self):
        cfg = self.cfg
        now = time.time()

        # 跟随活跃屏放在最前面：它只看窗口落在哪块屏、鼠标在哪块屏，
        # 跟前台是哪个程序无关，也不该被下面那些提前 return 的分支跳过。
        self._track_active()

        # 手动切换优先
        if self.manual_target is not None:
            target, self.manual_target = self.manual_target, None
            self.switch_to(target, "(手动)")
            self.reset_ask_state()
            self._update_status()
            return

        proc, title, pid = winapi.get_foreground_info()

        # ① 自己的窗口 / 取不到前台窗口（切窗口的瞬间）都不算"前台应用"：
        #    保持刚刚检测到的应用模式 —— 不重新匹配、不切回默认模式、
        #    也不清掉"已经问过"的状态。
        if not proc or self._is_self(proc):
            self._update_status()
            return

        self._last_proc, self._last_title = proc, title

        # ② 手动模式下挂靠的那个程序被关掉了 -> 自动同步开启自动识别，
        #    这样下一次打开别的软件就能无缝接上。
        if not self.auto_detect:
            if self._hold_proc and not winapi.process_running(self._hold_proc):
                self.enable_auto(reason="%s 已关闭" % self._hold_proc)
            else:
                self._update_status()
                return

        if self.paused():
            self._update_status()
            return

        self._log_foreground(proc, title, now)
        # 精确匹配 -> 同族进程 -> 父进程链，游戏换进程/加启动器都能认住
        group, app, via = matcher.match_deep(cfg, proc, title, pid)
        if via:
            self._log_via(via, group)
        idle = winapi.get_idle_seconds()
        idle_cfg = cfg.get("idle", {})
        idle_threshold = float(idle_cfg.get("minutes", 10)) * 60
        idle_on = bool(idle_cfg.get("enabled", True)) and idle_threshold > 0

        # 每轮都采一次音频电平（预热后约 0.2ms）。必须是"每轮"，因为
        # audio_active() 判断的是"最近一段时间有没有响过"——如果只在超时那
        # 一刻才第一次采样，恰好碰上对白间歇就会被误判成人走了。
        audio_now = winapi.audio_active()

        # 看视频 / 听音乐时人不会碰键鼠，光看"多久没输入"必然误判成空闲。
        # 所以在超时之后先确认一下：是不是真的在看/在听。
        busy = ""
        if idle_on and idle >= idle_threshold:
            busy = self._media_busy(cfg, now, audio_now)
            if busy:
                idle = 0.0
                if now - self._idle_log_at > 300:
                    self._idle_log_at = now
                    self.log("检测到%s，不算空闲（不回节能模式）" % busy)

        # ③ 从节能模式恢复
        if self.idle_active and idle < idle_threshold:
            restore = self.pre_idle_mode or cfg.get("return_default", {}).get(
                "mode")
            self.idle_active = False
            self.pre_idle_mode = None
            self.log("检测到操作，从节能模式恢复到【%s】" % restore)
            self.switch_to(restore, "(节能恢复)")
            self._check_manual_override(now)
            self._update_status()
            return

        # ④ 空闲节能（不弹窗）
        #    group is None 还不够：视频/游戏过程中前台窗口会短暂跳到别的进程上，
        #    那一瞬间 group 就变成 None 了，配上已经超时的 idle 会误进节能。
        #    所以再加一道"刚才那个分组还在宽限期内"的检查。
        if (idle_on and idle >= idle_threshold and group is None
                and not self._still_near_group(cfg, now)):
            if not self.idle_active:
                self.pre_idle_mode = self.applied_mode or cfg.get(
                    "return_default", {}).get("mode")
                self.idle_active = True
                self.switch_to(idle_cfg.get("mode") or "节能模式",
                               "(空闲 %.0f 分钟)" % (idle / 60))
            self._update_status()
            return

        # ⑤ 命中分组 -> 切换（同一个分组只问一次，之后都按记住的选择静默切）
        if group is not None:
            mode = group.get("mode")
            label = matcher.app_label(app, proc)
            gid = group.get("id") or group.get("name")
            self._mark_group(gid, group, proc)
            context = "检测到【%s】正在使用 · 分组「%s」" % (label, group["name"])
            if via:
                context += " · " + via
            if not self._debounce(gid, now):
                self._update_status()
                return
            remembered = self._ask_choice.get(gid, _UNSET)
            if remembered is _UNSET:
                if mode and mode == self.applied_mode:
                    # 显示器已经就是这个模式了，没必要再问一遍
                    self._ask_choice[gid] = mode
                elif cfg.get("ask_before_switch", True):
                    options = [m for m in self.mode_names()
                               if config.mode_vcp(cfg, m) is not None]
                    chosen = self.request_dialog(
                        suggested=mode, options=options,
                        timeout=int(cfg.get("dialog_timeout_seconds", 10)),
                        context=context)
                    # 记住这次的选择："" 表示用户选了「保持不变」
                    self._ask_choice[gid] = chosen or ""
                    self._ask_resolved_key = gid
                    self._ask_resolved_mode = chosen or self.applied_mode
                    if chosen:
                        self.switch_to(chosen, "(弹窗选择 · %s)" % context)
                    else:
                        self.log("弹窗：保持不变 · %s" % context)
                else:
                    self._ask_choice[gid] = mode
                    self.switch_to(mode, "(%s)" % context)
            elif remembered:
                # 之前确认过的选择：直接静默切回去，不再弹窗
                if remembered != self.applied_mode:
                    self.switch_to(remembered, "(按上次的选择 · %s)" % context)
                self._ask_resolved_key = gid
                self._ask_resolved_mode = remembered
            self._check_manual_override(now)
            self._update_status()
            return

        # ⑥ 前台不在任何分组里 —— 但先别急着回默认模式
        #
        # 全屏游戏在前台时，前台窗口会周期性跳到别的进程上：读图加载、Steam
        # 覆盖层、反作弊提示、系统弹窗都会抢一瞬间前台。这一轮看不到 tslgame.exe，
        # 下一轮又看到了。如果每轮都执行"回默认模式"，显示器就跟着来回换画质档位
        # （切换要重走图像处理管线，画面会断一下）—— 玩家体感就是每隔几秒卡一下。
        #
        # 所以这里先给一段宽限期：全屏程序还在跑就等久一点（前台抖动是常态），
        # 普通程序用短宽限（这样切到记事本之类还是很快就回默认模式）。
        if self._grp_id is not None:
            grace = self._leave_grace(cfg, now)
            if not self._grp_leave:
                self._grp_leave = now
                if now - self._leave_log_at > 30:
                    self._leave_log_at = now
                    self.log("前台离开「%s」（现在是 %s %s），%d 秒内不切模式"
                             % (self._grp_name, proc, (title or "")[:24],
                                int(grace)))
            if now - self._grp_leave < grace:
                self._check_manual_override(now)
                self._update_status()
                return
            self.log("「%s」已离开超过 %d 秒，回默认模式"
                     % (self._grp_name, int(grace)))
            self._clear_group()

        rd = cfg.get("return_default", {})
        if rd.get("enabled", True) and rd.get("mode"):
            key = ("__default__",)
            if not self._debounce(key, now):
                self._update_status()
                return
            if rd["mode"] != self.applied_mode:
                self.switch_to(rd["mode"], "(不在情景分组内，回默认模式)")
        self._check_manual_override(now)
        self._update_status()

    # ------------------------------------------------- 前台离开的宽限期
    def _mark_group(self, gid, group, proc):
        """记下刚刚命中的分组和程序，供"前台短暂跳走"时判断用。"""
        if self._grp_id != gid:
            # 换组了：重新记全屏状态
            self._grp_fs = winapi.foreground_fullscreen()
        self._grp_id = gid
        self._grp_name = group.get("name") or str(gid)
        self._grp_proc = (proc or "").lower()
        self._grp_leave = 0.0          # 回到分组内 -> 重新计时

    def _clear_group(self):
        self._grp_id = None
        self._grp_name = ""
        self._grp_proc = ""
        self._grp_fs = False
        self._grp_leave = 0.0

    def _alive(self, exe, now):
        """进程还在不在（带 3 秒缓存：枚举进程表要 7ms，别每轮都枚举）。"""
        exe = (exe or "").lower()
        if not exe:
            return False
        if self._alive_exe == exe and now - self._alive_at < 3.0:
            return self._alive_val
        val = winapi.process_running(exe)
        self._alive_at, self._alive_val, self._alive_exe = now, val, exe
        return val

    def _still_near_group(self, cfg, now):
        """刚才命中的分组还在 "在场" 状态（没超出宽限期）。"""
        if self._grp_id is None:
            return False
        if not self._grp_leave:
            return True
        return (now - self._grp_leave) < self._leave_grace(cfg, now)

    def _media_busy(self, cfg, now, audio_now=None):
        """现在是不是"在放东西"—— 这些情况不该算空闲。

        返回一句说明（给日志用），不是的话返回空串。
        """
        idle_cfg = cfg.get("idle", {})
        if bool(idle_cfg.get("ignore_media", True)):
            if audio_now is None:
                audio_now = winapi.audio_active()
            if audio_now:
                return "正在播放声音（视频 / 音乐）"
        if bool(idle_cfg.get("ignore_fullscreen", True)):
            if winapi.foreground_fullscreen():
                return "前台正在全屏播放"
            if self._grp_fs and self._still_near_group(cfg, now):
                return "全屏程序还在运行"
        return ""

    def _leave_grace(self, cfg, now=0.0):
        """离开分组后要等多久才回默认模式。"""
        short = float(cfg.get("leave_grace_seconds", 4.0))
        # 全屏游戏：只要进程还在，就当成"中途跳出去一下"，给很长的宽限。
        # 玩家打了个把小时，前台抖动几十次，一次都不该切。
        if self._grp_fs and self._grp_proc:
            if self._alive(self._grp_proc, now or time.time()):
                return float(cfg.get("leave_grace_fullscreen_seconds", 90.0))
        return short

    def _debounce(self, key, now):
        """同一个情景要稳定出现 debounce 秒才动作。"""
        if key != self._pending_key:
            self._pending_key = key
            self._pending_since = now
            return False
        return now - self._pending_since >= float(
            self.cfg.get("debounce_seconds", 2.0))

    def _log_foreground(self, proc, title, now):
        if self._is_self(proc):
            return
        fg = (proc, title)
        if fg == self._last_fg:
            return
        if self._last_fg_at and now - self._last_fg_at < 2.0:
            return
        self._last_fg = fg
        self._last_fg_at = now
        self.log("前台：%s  %s" % (proc or "?", (title or "")[:48]))

    def _log_via(self, via, group):
        """靠同族/父进程才认出来的情况，记一条日志（同样的不重复记）。"""
        if not group:
            return
        key = (via, group.get("id"))
        if key == self._last_via:
            return
        self._last_via = key
        self.log("按 %s 归入分组「%s」" % (via, group["name"]))

    def _check_manual_override(self, now):
        """连续两次发现显示值被改成了别的值 -> 认定用户按了 OSD 按键。

        注意：这里每次都要读一次显示器的 VCP 值，而 DDC/CI 走 I2C 总线，
        实测一次约 60ms，期间显示栈是被占住的 —— 在 60fps 的游戏里这 60ms
        足够丢 3~4 帧。所以绝对不能每一轮轮询（1.5 秒）都读一次，那样本身
        就变成了周期性卡顿的来源。隔十几秒查一次，对"用户按了 OSD 按键"
        这种手工操作完全够用。
        """
        if DRY_RUN:
            return
        if now - self._override_at < float(
                self.cfg.get("override_check_seconds", 15.0)):
            return
        self._override_at = now
        actual = self.ddc.get_mode()
        if actual is None or self.applied_value is None:
            self._override_streak = 0
            return
        if actual == self.applied_value:
            self._override_streak = 0
            return
        self._override_streak += 1
        if self._override_streak < 2:
            return
        minutes = int(self.cfg.get("manual_override_pause_minutes", 10))
        self.pause_until = now + minutes * 60
        self.applied_value = actual
        self._override_streak = 0
        self.log("检测到显示器模式被手动改动（0xDC=%s），自动切换暂停 %d 分钟"
                 % (actual, minutes))
        self.notify("已暂停自动切换",
                    "检测到你用显示器按键改了模式，自动切换暂停 %d 分钟。" % minutes)

    # ------------------------------------------------------------ 状态
    def _update_status(self):
        proc, title, pid = winapi.get_foreground_info()
        if self._is_self(proc) or not proc:
            # 自己的界面在前台时，状态卡继续显示刚才那个真正在用的程序
            proc, title = self._last_proc, self._last_title
            pid = 0
        group, app, via = matcher.match_deep(self.cfg, proc, title, pid)
        idle_text = "%.0f 分钟无操作" % (winapi.get_idle_seconds() / 60)
        if not self.auto_detect:
            auto, auto_hint = "手动模式", "%s 关闭后自动恢复" % (
                self._hold_proc or "当前程序")
        elif self.paused():
            auto, auto_hint = "已暂停", "%d 分钟后恢复" % max(
                0, int((self.pause_until - time.time()) / 60) + 1)
        elif self.idle_active:
            auto, auto_hint = "空闲节能中", "有操作就恢复"
        elif not self.mode_names():
            auto, auto_hint = "未配置模式", "请先到「显示器与模式」添加"
        else:
            auto, auto_hint = "运行中", idle_text
        self.status = {
            "mode": self.applied_mode or "未知",
            "color": self.mode_color(self.applied_mode)
            if self.applied_mode else T.TEXT_FAINT,
            "vcp": self.applied_value,
            "monitor": self.monitor_label(),
            # 上次切换到底落到哪条通道 —— 用户点一下就能看见结果，
            # 不用去翻 app.log。没有可用通道时这条会写成「无通道」。
            "channel_note": (self.last_apply or {}).get("summary", ""),
            "channel_ok": bool((self.last_apply or {}).get("ok", True)),
            "hdr_on": self.hdr_labels(self.gamma_blocked()),
            "fg_proc": proc or "—",
            "fg_title": title or "",
            "fg_label": (matcher.app_label(app, proc) if group
                         else presets.friendly_name(proc or "")),
            "group": group["name"] if group else "—",
            "group_mode": group.get("mode") if group else "—",
            "group_via": via,
            "auto": auto,
            "auto_hint": auto_hint,
            "auto_detect": bool(self.auto_detect),
            "auto_active": self.auto_active(),
            "hold_proc": self._hold_proc,
            "paused": self.paused(),
            "idle": idle_text,
            "groups": len(self.cfg.get("groups", [])),
            "apps": config.all_app_count(self.cfg),
        }

    def status_snapshot(self):
        return dict(self.status)

    # ------------------------------------------------------------ HDR / Gamma
    def hdr_devices(self, refresh=False):
        """当前处于高级颜色模式（HDR / 自动管理颜色）的显示器（带 5 秒缓存）。

        状态页每次重绘都会问一遍，而 QueryDisplayConfig 虽然快但没必要
        每帧都查。5 秒足够反映用户手动开关 HDR。
        """
        now = time.time()
        if refresh or now - self._hdr_at > 5.0:
            self._hdr_at = now
            try:
                self._hdr_state = {m["device"]: m for m in HDR.query()}
            except Exception:
                self._hdr_state = {}
        return [d for d, m in self._hdr_state.items()
                if m.get("advanced") or m.get("hdr_enabled")]

    def hdr_labels(self, devices=None):
        """把 device 名换成用户认得出的显示器名（EDID 里的型号，如 27M1）。"""
        devices = self.hdr_devices() if devices is None else devices
        out = []
        for d in devices:
            info = self._hdr_state.get(d) or {}
            name = info.get("friendly")
            if not name:
                # 退回 list_monitors 里的短名（显示器 N  WxH）
                for m in self.monitors or []:
                    if m.get("device") == d:
                        name = m.get("short")
                        break
            out.append(name or d.replace("\\\\.\\", ""))
        return out

    def hdr_report(self):
        """给「显示器与模式」页显示的一行高级颜色摘要。

        刻意不写「HDR 已开启」：`advancedColorEnabled` 这一位在 Windows 的
        「自动管理颜色」下也会置起来，一口咬定是 HDR 会让人以为程序瞎报。
        另外只有**要靠画面补偿的屏**才说"补偿失效"，走自带档位的屏标
        "不影响" —— 免得两块屏一起看时以为全都废了。
        """
        rows = list(self._hdr_state.values())
        if not rows:
            try:
                rows = HDR.query()
                self._hdr_state = {m["device"]: m for m in rows}
            except Exception:
                return "查不到高级颜色状态"
        need = set(self.gamma_targets().values())
        parts = []
        for m in rows:
            dev = m.get("device") or ""
            name = m.get("friendly") or dev.replace("\\\\.\\", "")
            if not m.get("ok"):
                parts.append("%s：SDR（查不到状态）" % name)
            elif m.get("advanced"):
                parts.append("%s：%s%s" % (
                    name, m.get("mode_text", "高级颜色已开启"),
                    "，补偿失效" if dev in need else "，不影响（走自带档位）"))
            else:
                parts.append("%s：%s" % (name, m.get("mode_text", "SDR")))
        return " ｜ ".join(parts)

    def gamma_targets(self):
        """哪些屏**根本没法自己换档**，只能靠画面补偿。

        用静态能力判断（有没有可用的 0xDC），不去看"这次切成功没有" ——
        状态卡每次重绘都会问一遍，不能为了这个反复写显示器。
        """
        return {m["index"]: m.get("device") for m in self.monitors
                if m.get("device") and not m.get("mode_capable")}

    def gamma_blocked(self):
        """「需要画面补偿、却被高级颜色挡住」的屏。

        **只有这几种屏才值得提醒**。主屏走 DDC 自带档位，它开没开 HDR
        跟补偿一点关系都没有，列在状态卡上只会让人怀疑程序在瞎报 ——
        用户就专门问过："我明明没开 HDR，为什么说我开了"。
        """
        need = set(self.gamma_targets().values())
        return [d for d in self.hdr_devices() if d in need]

    # ------------------------------------------------------------ 托盘
    @staticmethod
    def make_icon(color):
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        c = T.rgb(color) if isinstance(color, str) else color
        rgb = (c & 0xFF, (c >> 8) & 0xFF, (c >> 16) & 0xFF)
        d.rounded_rectangle([4, 10, 60, 46], radius=7, fill=rgb)
        d.rectangle([27, 46, 37, 54], fill=rgb)
        d.rectangle([17, 54, 47, 60], fill=rgb)
        return img

    def _update_icon(self):
        if self.icon is None:
            return
        try:
            self.icon.icon = self.make_icon(
                self.mode_color(self.applied_mode) if self.applied_mode
                else "#8A8F99")
        except Exception:
            pass

    def _make_switch(self, name):
        return lambda icon, item: self.do_manual(name)

    def build_menu(self):
        modes = [m for m in self.mode_names()
                 if config.mode_vcp(self.cfg, m) is not None]
        items = [pystray.MenuItem(
            "当前：%s" % (self.applied_mode or "未知"), None, enabled=False),
            pystray.Menu.SEPARATOR]
        if modes:
            items.append(pystray.MenuItem("立即切换", pystray.Menu(*[
                pystray.MenuItem(m, self._make_switch(m)) for m in modes])))
        items += [
            pystray.MenuItem("打开主界面",
                             lambda icon, item: self._post(TRAY_OPEN),
                             default=True),
            pystray.MenuItem(
                "自动识别模式：已开启" if self.auto_active()
                else "切回自动识别模式",
                lambda icon, item: self._post(TRAY_AUTO),
                enabled=not self.auto_active()),
            pystray.MenuItem(
                "恢复自动切换" if self.paused() else "暂停自动切换 10 分钟",
                lambda icon, item: self._post(TRAY_PAUSE)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "切换前询问我：%s" % ("开" if self.cfg.get("ask_before_switch")
                                      else "关"),
                lambda icon, item: self._post(TRAY_ASK)),
            pystray.MenuItem(
                "开机自启：%s" % ("开" if winapi.startup_enabled() else "关"),
                lambda icon, item: self._post(TRAY_STARTUP)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", lambda icon, item: self._post(TRAY_QUIT)),
        ]
        return pystray.Menu(*items)

    def _post(self, action):
        if self.main_hwnd:
            try:
                from screenmode.ui.mainwindow import WM_APP_TRAY
                winapi.user32.PostMessageW(self.main_hwnd, WM_APP_TRAY,
                                           action, 0)
            except Exception:
                pass

    def start_tray(self):
        self.icon = pystray.Icon(
            "ScreenMode",
            self.make_icon(self.mode_color(self.applied_mode)
                           if self.applied_mode else "#8A8F99"),
            "%s · 显示器情景模式自动切换" % APP_NAME)
        self.icon.menu = self.build_menu()
        try:
            self.icon.run_detached()
        except Exception as e:
            self.log("托盘启动失败：%r" % (e,))

    def refresh_menu(self):
        if self.icon is None:
            return
        try:
            self.icon.menu = self.build_menu()
            self.icon.update_menu()
        except Exception:
            pass

    def on_tray_action(self, action):
        if action == TRAY_OPEN:
            if self.ui:
                self.ui.show()
        elif action == TRAY_PAUSE:
            if self.paused():
                self.pause_until = 0.0
                self.log("恢复自动切换")
            else:
                self.pause_until = time.time() + 10 * 60
                self.log("暂停自动切换 10 分钟")
        elif action == TRAY_AUTO:
            self.enable_auto("托盘菜单")
        elif action == TRAY_ASK:
            self.cfg["ask_before_switch"] = not self.cfg.get(
                "ask_before_switch", True)
            self.save_config()
            self.log("切换前询问：%s"
                     % ("开" if self.cfg["ask_before_switch"] else "关"))
        elif action == TRAY_STARTUP:
            want = not winapi.startup_enabled()
            winapi.set_startup(want)
            self.log("开机自启：%s" % ("开" if want else "关"))
            self.notify("开机自启", "已%s" % ("开启" if want else "关闭"))
        elif action == TRAY_QUIT:
            self.request_quit()
        self.refresh_menu()

    # ------------------------------------------------------------ 生命周期
    def request_quit(self):
        self.log("退出程序")
        self.running = False
        try:
            self.ddc.close()
        except Exception:
            pass
        # 只释放 DC，不恢复画面 —— 用户切到电影模式后关程序，
        # 期待的是画面保持电影模式，而不是"一关就变回去"。
        try:
            self.gch.close()
        except Exception:
            pass
        if self.icon is not None:
            try:
                self.icon.stop()
            except Exception:
                pass
        if self.main_hwnd:
            winapi.user32.PostMessageW(self.main_hwnd, 0x0010, 0, 0)  # WM_CLOSE

    def quit_immediately(self):
        self.running = False
        try:
            self.ddc.close()
        except Exception:
            pass
        try:
            self.gch.close()
        except Exception:
            pass
        if self.icon is not None:
            try:
                self.icon.stop()
            except Exception:
                pass
        if self.main_hwnd:
            winapi.user32.PostMessageW(self.main_hwnd, 0x0002, 0, 0)  # WM_DESTROY

    def run(self):
        if not winapi.ensure_single_instance():
            winapi.message_box(
                "%s 已经在运行了。\n\n请在任务栏右下角的系统托盘"
                "（可能被折叠在 ^ 里）找到显示器图标，\n右键它 →「打开主界面」。"
                % APP_NAME, APP_NAME, 0x40)
            return 0

        self.log("启动 %s v%s" % (APP_NAME, VERSION))
        self.refresh_monitors()
        self.rebuild_ddc()
        self.sync_applied_from_monitor()

        from screenmode.ui.mainwindow import MainWindow
        self.ui = MainWindow(self)
        if not self.ui.create_window():
            winapi.message_box("主窗口创建失败，程序无法启动。", APP_NAME, 0x10)
            return 1
        self.main_hwnd = self.ui.hwnd

        self.start_tray()
        self.start_worker()
        threading.Thread(target=self._watchdog_loop, daemon=True).start()
        self.notify("屏效助手已启动",
                    "托盘图标在任务栏右下角（可能在 ^ 里）。右键图标可快速切换模式。")

        self.ui.message_loop()
        self.log("主循环结束")
        return 0
