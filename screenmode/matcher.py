# -*- coding: utf-8 -*-
"""前台程序 -> 分组 -> 显示器模式的匹配逻辑。"""
from screenmode import presets, winapi

# 同一个游戏/软件常见的一堆"变体后缀"：
#   TslGame.exe / TslGame_BE.exe / Xxx-Win64-Shipping.exe / Xxx_dx12.exe …
# 去掉它们之后视为同一个应用，免得游戏一换进程就当成"新程序"重新问一遍。
_FAMILY_SUFFIX = (
    "-win64-shipping", "-win32-shipping", "_win64_shipping",
    "-shipping", "_shipping", "_be", "-be", "_dx11", "_dx12",
    "-dx11", "-dx12", "_x64", "-x64",
)


def family(exe):
    """把进程名归一成"应用族"名字（不含 .exe、不含变体后缀）。"""
    base = (exe or "").strip().lower()
    if base.endswith(".exe"):
        base = base[:-4]
    changed = True
    while changed:
        changed = False
        for suf in _FAMILY_SUFFIX:
            if base.endswith(suf) and len(base) - len(suf) >= 3:
                base = base[:-len(suf)]
                changed = True
    return base


def match(cfg, proc, title):
    """返回 (group, app)；没匹配到返回 (None, None)。

    只匹配用户配置过的应用：不在分组列表里的程序一律不触发切换。
    """
    proc_l = (proc or "").lower()
    title_l = (title or "").lower()
    for group in cfg.get("groups", []):
        if not group.get("enabled", True):
            continue
        for app in group.get("apps", []):
            exe = (app.get("exe") or "").lower()
            if exe:
                if exe == proc_l:
                    return group, app
                continue
            keyword = (app.get("title") or "").lower()
            if keyword and keyword in title_l:
                return group, app
    return None, None


def match_family(cfg, proc):
    """按"应用族"再匹配一次：TslGame_BE.exe 也能认成 TslGame.exe。"""
    fam = family(proc)
    if not fam:
        return None, None
    for group in cfg.get("groups", []):
        if not group.get("enabled", True):
            continue
        for app in group.get("apps", []):
            exe = (app.get("exe") or "").strip()
            if exe and family(exe) == fam:
                return group, app
    return None, None


def match_deep(cfg, proc, title, pid=0):
    """三层匹配：精确 -> 同族进程 -> 父进程链。

    返回 (group, app, via)；via 是"怎么匹配上的"说明（精确匹配时为空串）。
    游戏常把启动器/本体拆成好几个 exe（ExecPubg.exe -> TslGame.exe），
    这一层保证它们算同一个应用，不会因为换进程就重新弹窗。
    """
    group, app = match(cfg, proc, title)
    if group is not None:
        return group, app, ""

    group, app = match_family(cfg, proc)
    if group is not None:
        return group, app, "同族进程 %s" % proc

    for anc in winapi.parent_chain(pid):
        group, app = match(cfg, anc, "")
        if group is not None:
            return group, app, "父进程 %s" % anc
    return None, None, ""


def app_label(app, proc=""):
    if not app:
        return presets.friendly_name(proc)
    return app.get("name") or app.get("exe") or app.get("title") or "未知应用"
