# -*- coding: utf-8 -*-
"""逻辑自测：不碰真实显示器（--dry-run），把前台程序换成假数据驱动 tick()。

覆盖三条新需求：
  ① 自己的窗口在前台 -> 保持刚检测到的模式，不回默认模式
  ② 弹窗 / 静默切换（不涉及 UI，这里只验状态机）
  ③ 手动模式 + 被检测应用关闭后自动恢复自动识别
"""
import os
import shutil
import sys
import tempfile
import time

if "--dry-run" not in sys.argv:
    sys.argv.append("--dry-run")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from screenmode import app as A          # noqa: E402

tmp = tempfile.mkdtemp(prefix="sm_test_")
A.CONFIG_PATH = os.path.join(tmp, "config.json")
A.LOG_PATH = os.path.join(tmp, "app.log")

FG = {"proc": "explorer.exe", "title": "桌面", "pid": 0}
A.winapi.get_foreground = lambda: (FG["proc"], FG["title"])
A.winapi.get_foreground_info = lambda: (FG["proc"], FG["title"], 0)
A.winapi.parent_chain = lambda pid, depth=4: []
FS = {"on": False}          # 前台窗口是不是全屏（游戏）
A.winapi.foreground_fullscreen = lambda: FS["on"]

# 空闲时间 / 音频活动都换成可控开关
IDLE = {"s": 0.0}
AUD = {"on": False}
A.winapi.get_idle_seconds = lambda: IDLE["s"]
A.winapi.audio_active = lambda *a, **k: AUD["on"]

# 假进程表：判断"被检测的应用是不是关了"用，不依赖本机真的开着记事本
RUNNING = {"explorer.exe", "notepad.exe", "chrome.exe"}
A.winapi.process_running = lambda exe: (exe or "").lower() in RUNNING

OK, BAD = [], []


def check(name, cond, extra=""):
    (OK if cond else BAD).append(name)
    print(("  [OK]   " if cond else "  [FAIL] ") + name + ("  " + extra if extra else ""))


def run(app, n=2):
    for _ in range(n):
        app.tick()


def main():
    a = A.App()
    asked = []
    real_ask = a.request_dialog
    def _ask(**kw):
        asked.append(kw.get("suggested"))
        return real_ask(**kw)
    a.request_dialog = _ask
    a.cfg["debounce_seconds"] = 0
    # 老段落测的是"逻辑对不对"，把宽限期关掉才等价于旧行为；
    # 宽限期本身由 [11] 专门测。
    a.cfg["leave_grace_seconds"] = 0
    a.cfg["leave_grace_fullscreen_seconds"] = 0
    a.cfg["ask_before_switch"] = True
    print("自身进程名：", sorted(a._self_procs))

    print("\n[1] 打开记事本 -> 应切到阅读模式")
    FG.update(proc="notepad.exe", title="a.txt - 记事本")
    run(a)
    check("记事本触发阅读模式", a.applied_mode == "阅读模式", str(a.applied_mode))

    print("\n[2] 切到屏效助手自己的窗口 -> 模式必须保持不变")
    FG.update(proc="屏效助手.exe", title="屏效助手")
    before = a.applied_mode
    run(a, 4)
    check("模式没被改回默认", a.applied_mode == before, str(a.applied_mode))
    check("前台程序没被记成自己",
          a.status.get("fg_proc") == "notepad.exe",
          str(a.status.get("fg_proc")))
    check("日志里没有把自记成前台",
          not any(e[1].startswith("前台：屏效助手") for e in a.events),
          str([e[1] for e in a.events][-3:]))
    check("已经问过的状态没被清掉", a._ask_resolved_key is not None)

    print("\n[3] 关掉界面回到别的程序 -> 正常回到默认模式（用户模式）")
    FG.update(proc="explorer.exe", title="桌面")
    run(a, 2)
    check("回到用户模式", a.applied_mode == "用户模式", str(a.applied_mode))

    print("\n[4] 手动切电影模式 -> 进入手动模式，挂靠记事本")
    FG.update(proc="notepad.exe", title="a.txt - 记事本")
    run(a)
    check("手动前是阅读模式", a.applied_mode == "阅读模式", str(a.applied_mode))
    a.do_manual("电影模式")
    run(a)
    check("电影模式已生效", a.applied_mode == "电影模式", str(a.applied_mode))
    check("auto_detect 关掉了", a.auto_detect is False)
    check("挂靠 notepad.exe", a._hold_proc == "notepad.exe", a._hold_proc)
    check("状态卡显示手动模式", a.status.get("auto") == "手动模式",
          str(a.status.get("auto")))

    print("\n[5] 手动模式下打开 chrome -> 不许自己切")
    FG.update(proc="chrome.exe", title="Google Chrome")
    run(a, 3)
    check("仍然是电影模式", a.applied_mode == "电影模式", str(a.applied_mode))
    check("仍然是手动模式", a.auto_detect is False)

    print("\n[6] 记事本关掉 -> 自动恢复识别，chrome 立刻被识别")
    RUNNING.discard("notepad.exe")
    run(a, 3)
    check("自动识别已恢复", a.auto_detect is True)
    check("chrome 被识别成阅读模式", a.applied_mode == "阅读模式",
          str(a.applied_mode))
    check("状态卡回到运行中/手动已退出",
          a.status.get("auto") in ("运行中", "空闲节能中"),
          str(a.status.get("auto")))
    RUNNING.add("notepad.exe")

    print("\n[7] 界面按钮：切回自动识别模式")
    a.do_manual("FPS模式")
    run(a)
    check("先进入手动模式", a.auto_detect is False and a.applied_mode == "FPS模式",
          str(a.applied_mode))
    a.enable_auto("测试按钮")
    check("enable_auto 后 auto_detect=True", a.auto_detect is True)
    check("挂靠已清空", a._hold_proc == "")
    run(a, 2)
    check("重新识别成阅读模式", a.applied_mode == "阅读模式", str(a.applied_mode))
    check("auto_detect 只是运行期状态，不写进配置",
          "auto_detect" not in a.cfg)

    print("\n[8] 同一个分组只问一次：离开再回来不该重新弹窗")
    a.reset_ask_state()          # 从"什么都没确认过"开始
    FG.update(proc="explorer.exe", title="桌面")
    run(a, 2)                    # 先回到默认模式（用户模式）
    asked.clear()
    FG.update(proc="notepad.exe", title="a.txt - 记事本")
    run(a, 2)
    first = len(asked)
    check("第一次进办公分组会问一次", first == 1, "问了 %d 次" % first)
    FG.update(proc="explorer.exe", title="桌面")
    run(a, 2)
    check("离开后回默认模式", a.applied_mode == "用户模式", str(a.applied_mode))
    FG.update(proc="notepad.exe", title="a.txt - 记事本")
    run(a, 2)
    check("再回来不弹窗", len(asked) == first, "累计问了 %d 次" % len(asked))
    check("直接静默切回阅读模式", a.applied_mode == "阅读模式",
          str(a.applied_mode))
    # 换了同分组的另一个程序，也不该重新问
    FG.update(proc="chrome.exe", title="Google Chrome")
    run(a, 2)
    check("同组另一个程序也不再弹窗", len(asked) == first,
          "累计问了 %d 次" % len(asked))

    print("\n[9] 同一款游戏换了进程名（同族/父进程）也认得住")
    FG.update(proc="tslgame.exe", title="PUBG：绝地求生")
    run(a, 2)
    before = len(asked)
    check("第一次进 FPS 分组问一次", before == 2, "累计问了 %d 次" % before)
    FG.update(proc="tslgame_be.exe", title="PUBG")
    run(a, 2)
    check("TslGame_BE.exe 认成 FPS 分组", a.status.get("group") == "FPS 游戏类",
          str(a.status.get("group")))
    check("换进程不再弹窗", len(asked) == before, "累计问了 %d 次" % len(asked))
    check("模式仍是 FPS", a.applied_mode == "FPS模式", str(a.applied_mode))

    print("\n[10] 桌面上手动切换（explorer.exe 常驻）不能挂靠成手动模式")
    a.enable_auto("测试前置")
    a.pause_until = 0.0
    a._last_proc = "explorer.exe"
    a.do_manual("电影模式")
    run(a, 2)
    check("没有进入死锁的手动模式", a.auto_detect is True)
    check("挂靠对象是空的", a._hold_proc == "", a._hold_proc)
    check("改成暂停 10 分钟", a.paused() is True)
    a.pause_until = 0.0

    # ---------------------------------------------------------------- [11]
    print("\n[11] 全屏游戏前台抖动：不能跟着反复切模式（掉帧的根因）")
    a.enable_auto("测试前置")
    a.cfg["leave_grace_seconds"] = 4.0
    a.cfg["leave_grace_fullscreen_seconds"] = 90.0
    FS["on"] = True
    RUNNING.add("tslgame.exe")

    # 进游戏：认成 FPS 分组
    FG.update(proc="tslgame.exe", title="PUBG：绝地求生", pid=0)
    run(a, 2)
    check("游戏里是 FPS 模式", a.applied_mode == "FPS模式", str(a.applied_mode))
    sw = len([e for e in a.events if e[1].startswith("切换")])
    check("记下了这是全屏程序", a._grp_fs is True, str(a._grp_fs))

    # 模拟游戏期间前台反复跳到 explorer / 别的东西上（加载、覆盖层、系统弹窗）
    flips = 0
    for _ in range(12):
        FG.update(proc="explorer.exe", title="桌面")
        run(a, 1)
        if a.applied_mode != "FPS模式":
            flips += 1
        FG.update(proc="tslgame.exe", title="PUBG：绝地求生")
        run(a, 1)
        if a.applied_mode != "FPS模式":
            flips += 1
    check("前台抖动 24 次都没切走", flips == 0, "切走了 %d 次" % flips)
    sw2 = len([e for e in a.events if e[1].startswith("切换")])
    check("期间没有产生任何切换动作", sw2 == sw, "切换记录 %d -> %d" % (sw, sw2))

    # 游戏真的退出了（进程没了）-> 宽限期到点就回默认模式
    RUNNING.discard("tslgame.exe")
    FG.update(proc="explorer.exe", title="桌面")
    a._grp_leave = time.time() - 100      # 假装已经离开很久
    run(a, 3)
    check("游戏退出后回默认模式", a.applied_mode == "用户模式",
          str(a.applied_mode))
    check("按住的分组已清掉", a._grp_id is None, str(a._grp_id))

    # ---------------------------------------------------------------- [12]
    print("\n[12] 全屏游戏跑着但人走开了很久 -> 也回默认模式（不能永远不切）")
    FS["on"] = True
    RUNNING.add("tslgame.exe")
    a.enable_auto("测试前置")
    FG.update(proc="tslgame.exe", title="PUBG：绝地求生")
    run(a, 2)
    check("又进 FPS 模式", a.applied_mode == "FPS模式", str(a.applied_mode))
    FG.update(proc="explorer.exe", title="桌面")
    a._grp_leave = time.time() - 200      # 超过 90 秒宽限
    run(a, 3)
    check("超过宽限照样回默认模式", a.applied_mode == "用户模式",
          str(a.applied_mode))

    print("\n[13] 非全屏程序：离开后按短宽限走，不会赖着")
    a.enable_auto("测试前置")
    FS["on"] = False
    FG.update(proc="notepad.exe", title="a.txt - 记事本")
    run(a, 2)
    check("记事本是阅读模式", a.applied_mode == "阅读模式", str(a.applied_mode))
    check("非全屏不记成全屏", a._grp_fs is False, str(a._grp_fs))
    FG.update(proc="explorer.exe", title="桌面")
    a._grp_leave = time.time() - 10
    run(a, 3)
    check("记事本离开后回默认模式", a.applied_mode == "用户模式",
          str(a.applied_mode))

    # ---------------------------------------------------------------- [14]
    print("\n[14] 看视频时不该被判成空闲（节能模式误触发）")
    a.enable_auto("测试前置")
    a.cfg["idle"]["minutes"] = 10
    FS["on"] = False
    AUD["on"] = False
    IDLE["s"] = 0.0
    # 用不在任何分组里的进程，才会真的走到「空闲节能」这条分支
    # （默认预设里 chrome.exe 是归在办公阅读类的）
    FG.update(proc="movieplayer.exe", title="某播放器 - 视频")
    run(a, 2)

    # 人在电脑前，只是没碰键鼠、也没声音 -> 正常进节能
    a.switch_to("用户模式")
    a.idle_active = False
    IDLE["s"] = 11 * 60
    run(a, 3)
    check("没声音又真的没人动 -> 进节能", a.applied_mode == "节能模式",
          str(a.applied_mode))

    # 有声（在看视频）-> 不许进节能
    a.enable_auto("测试前置")
    a.switch_to("用户模式")
    AUD["on"] = True
    IDLE["s"] = 30 * 60
    run(a, 3)
    check("有声音（在看视频）-> 不进节能", a.idle_active is False,
          "idle_active=%s" % a.idle_active)
    check("模式保持不变", a.applied_mode == "用户模式", str(a.applied_mode))

    # 已经在节能模式里，开始放视频 -> 应该自己恢复
    # （只看恢复那一刻：恢复之后前台程序仍不在任何分组里，下一轮会正常回落
    #   到默认模式，那是另一条逻辑，不在这里断言）
    a.idle_active = True
    a.pre_idle_mode = "FPS模式"
    a.switch_to("节能模式")
    AUD["on"] = True
    run(a, 1)
    check("节能中开始放视频 -> 自动恢复", a.applied_mode == "FPS模式",
          str(a.applied_mode))

    # 关掉开关就该恢复老行为
    a.enable_auto("测试前置")
    a.switch_to("用户模式")
    a.cfg["idle"]["ignore_media"] = False
    AUD["on"] = True
    IDLE["s"] = 30 * 60
    run(a, 3)
    check("关掉 ignore_media 后照旧会节能", a.applied_mode == "节能模式",
          str(a.applied_mode))
    a.cfg["idle"]["ignore_media"] = True

    # ---------------------------------------------------------------- [15]
    print("\n[15] 视频/游戏过程中前台抖动，不能一把掉进节能模式")
    a.enable_auto("测试前置")
    a.switch_to("用户模式")
    AUD["on"] = False
    FS["on"] = True
    RUNNING.add("tslgame.exe")
    IDLE["s"] = 0.0
    FG.update(proc="tslgame.exe", title="PUBG：绝地求生")
    run(a, 2)
    check("先进入 FPS 模式", a.applied_mode == "FPS模式", str(a.applied_mode))

    IDLE["s"] = 40 * 60              # 打了 40 分钟，一直没碰键鼠
    flips = 0
    for _ in range(6):
        FG.update(proc="explorer.exe", title="桌面")
        run(a, 1)
        if a.idle_active:
            flips += 1
        FG.update(proc="tslgame.exe", title="PUBG：绝地求生")
        run(a, 1)
        if a.idle_active:
            flips += 1
    check("抖动 12 次都没进节能", flips == 0, "进了 %d 次" % flips)
    check("还停在 FPS 模式", a.applied_mode == "FPS模式", str(a.applied_mode))

    print("\n结果：OK %d / FAIL %d" % (len(OK), len(BAD)))
    for name in BAD:
        print("  失败：", name)
    return 0 if not BAD else 1


if __name__ == "__main__":
    try:
        code = main()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    sys.exit(code)
