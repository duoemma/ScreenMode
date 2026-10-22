# -*- coding: utf-8 -*-
"""配置读写与数据模型。

config.json 结构（v2）：
{
  "version": 2,
  "monitor_index": 0,                  # 旧字段（单台），仅用于兼容老配置
  "monitors": {
    "enabled": [],                     # 要控制哪几台（序号从 0 起）；[] = 所有能控的
    "vcp": {},                         # 可选覆盖：{"1": 20} 强制某台用 0x14
  },
  "poll_seconds": 1.5,                 # 轮询间隔
  "debounce_seconds": 2.0,             # 前台程序变化后等多久才动作（防抖）
  "leave_grace_seconds": 4.0,          # 前台离开分组后等多久才回默认模式
  "leave_grace_fullscreen_seconds": 90.0,  # 全屏游戏还在跑时的宽限（防抖动的关键）
  "override_check_seconds": 15.0,      # 多久查一次"显示器被手动改了"（DDC 读很慢）
  "idle":       {"enabled": true, "minutes": 10, "mode": "节能模式",
                 "ignore_media": true,      # 有声音在放就不算空闲（看视频用）
                 "ignore_fullscreen": true},  # 全屏播放/全屏游戏也不算空闲
  "return_default": {"enabled": true, "mode": "用户模式"},
  "ask_before_switch": true,
  "dialog_timeout_seconds": 10,
  "manual_override_pause_minutes": 10,
  "gamma": {"enabled": true, "warn_hdr": true},   # 画面补偿（Gamma 兜底通道）
  "modes": [
    # 有的模式只有"档位"；有的只有"补偿"；也可以两样都有
    {"name": "阅读模式", "vcp": 5, "color": "#3478F6",
     "gamma": {"warm": 1.10, "contrast": 0.92, "brightness": 1.0,
               "gamma": 1.0, "sat": 1.0}},
    ...
  ],
  "groups": [
    {"id": "office", "name": "办公阅读类", "mode": "阅读模式",
     "kind": "office", "enabled": true,
     "apps": [{"name": "Word", "exe": "winword.exe", "src": "preset"}]}
  ]
}
"""
import copy
import json
import os
import uuid

from screenmode import gamma, presets
from screenmode.ui import theme as T

CONFIG_VERSION = 2


def _default_modes():
    """默认 5 个模式。

    每个都同时给了「档位」和「画面补偿」：
      档位     —— 给 DDC 通的屏用（写显示器自己的 OSD 预设）
      画面补偿 —— 给 DDC 写不动的屏兜底（改显卡查找表）
    两条通道互斥，按每台屏的实际情况自动选，不会叠加。
    """
    return [
        {"name": "用户模式", "vcp": 1, "color": "#6E7480"},
        {"name": "阅读模式", "vcp": 5, "color": "#3478F6",
         "gamma": {"warm": 1.10, "contrast": 0.92}},
        {"name": "电影模式", "vcp": 2, "color": "#8B5CF6",
         "gamma": {"warm": 1.05, "contrast": 1.06}},
        {"name": "节能模式", "vcp": 4, "color": "#12A150",
         "gamma": {"brightness": 0.82, "gamma": 1.25}},
        {"name": "FPS模式", "vcp": 7, "color": "#E5484D",
         "gamma": {"warm": 0.97, "contrast": 1.10, "sat": 1.15}},
    ]


def _default_groups():
    out = []
    for kind, meta in presets.GROUP_ARCHETYPES:
        apps = [dict(a, src="preset") for a in presets.default_apps(kind)]
        out.append({
            "id": kind,
            "name": meta["name"],
            "mode": meta["mode"],
            "kind": kind,
            "enabled": True,
            "apps": apps,
        })
    return out


def default_config():
    return {
        "version": CONFIG_VERSION,
        "monitor_index": 0,
        # 空列表 = 控制所有能控情景模式的显示器（接几台控几台）
        "monitors": {
            "enabled": [], "vcp": {}, "setup_done": {},
            # 跟随活跃屏：把「控制目标」从固定勾选改成"用户此刻在用的那一块"。
            # 打开后 enabled 不再决定控谁，只是"允许被控的候选范围"。
            "follow_active": False,
            # 候选屏要连续稳定多少秒才算"真的在用"。
            # 不给滞回的话，鼠标划到另一块屏取个东西，控制权当场转移 ——
            # DDC 重切一次，画面闪一下。
            "follow_stable_seconds": 3.0,
        },
        # 画面补偿（Gamma 兜底通道）。
        # enabled=False 时完全不碰显卡查找表 —— 有人用校色仪校过屏，
        # 不想让任何软件动它。warn_hdr 控制要不要弹「HDR 开着，补偿不生效」。
        "gamma": {"enabled": True, "warn_hdr": True},
        "poll_seconds": 1.5,
        "debounce_seconds": 2.0,
        "leave_grace_seconds": 4.0,
        "leave_grace_fullscreen_seconds": 90.0,
        "override_check_seconds": 15.0,
        "idle": {"enabled": True, "minutes": 10, "mode": "节能模式",
                 "ignore_media": True, "ignore_fullscreen": True},
        "return_default": {"enabled": True, "mode": "用户模式"},
        "ask_before_switch": True,
        "dialog_timeout_seconds": 10,
        "manual_override_pause_minutes": 10,
        "modes": _default_modes(),
        "groups": _default_groups(),
    }


# ------------------------------------------------------------------ 读取 / 保存
def load(path):
    """返回 (config, 是否新建)。文件损坏时备份并重建。"""
    if not os.path.exists(path):
        cfg = default_config()
        save(path, cfg)
        return cfg, True
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        try:
            os.replace(path, path + ".broken")
        except Exception:
            pass
        cfg = default_config()
        save(path, cfg)
        return cfg, True
    return migrate(raw), False


def save(path, cfg):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


# ------------------------------------------------------------------ 迁移
_KIND_BY_MODE = {"阅读模式": "office", "电影模式": "video", "FPS模式": "fps"}


def migrate(raw):
    """把任意旧版本配置补齐成 v2。"""
    cfg = default_config()
    if not isinstance(raw, dict):
        return cfg

    # ---- 旧版 modes 是 dict：{"阅读模式": {"vcp": 5}} ----
    old_modes = raw.get("modes")
    if isinstance(old_modes, dict):
        palette = list(T.MODE_PALETTE)
        modes = []
        for i, (name, info) in enumerate(old_modes.items()):
            vcp = None
            if isinstance(info, dict):
                vcp = info.get("vcp")
            elif isinstance(info, int):
                vcp = info
            modes.append({"name": name,
                          "vcp": vcp,
                          "color": palette[i % len(palette)]})
        if modes:
            cfg["modes"] = modes
    elif isinstance(old_modes, list) and old_modes:
        cleaned = [_clean_mode(m) for m in old_modes if isinstance(m, dict)
                   and m.get("name")]
        cfg["modes"] = [m for m in cleaned if m]

    # ---- 旧版 rules: [{"name": 模式, "processes": [], "titles": []}] ----
    old_rules = raw.get("rules")
    if isinstance(old_rules, list) and old_rules:
        groups = []
        for rule in old_rules:
            mode = rule.get("name") or "阅读模式"
            kind = _KIND_BY_MODE.get(mode, "custom")
            apps = []
            for proc in rule.get("processes") or []:
                apps.append({"name": presets.friendly_name(proc),
                             "exe": proc.lower(), "src": "custom"})
            for title in rule.get("titles") or []:
                apps.append({"name": title, "exe": "",
                             "title": title, "src": "custom"})
            groups.append({
                "id": _new_id(groups, mode),
                "name": (presets.GROUP_LABEL.get(kind) or mode + "类"),
                "mode": mode, "kind": kind, "enabled": True, "apps": apps,
            })
        if groups:
            cfg["groups"] = groups

    # ---- 新增的 groups（v2 原生） ----
    if isinstance(raw.get("groups"), list):
        cleaned = []
        for g in raw["groups"]:
            if not isinstance(g, dict) or not g.get("name"):
                continue
            cleaned.append({
                "id": g.get("id") or uuid.uuid4().hex[:8],
                "name": g["name"],
                "mode": g.get("mode") or "阅读模式",
                "kind": g.get("kind") or "custom",
                "enabled": bool(g.get("enabled", True)),
                "apps": [_clean_app(a) for a in g.get("apps", [])
                         if isinstance(a, dict)],
            })
        if cleaned:
            cfg["groups"] = cleaned

    # ---- 扁平字段 ----
    if "monitor_index" in raw:
        cfg["monitor_index"] = int(raw["monitor_index"] or 0)
    # ---- 多显示器 ----
    # 老配置里只有 monitor_index（单台）。这里不拿它去限制 monitors.enabled，
    # 否则升级后还是只控制一台 —— 默认变成"所有能控的都控制"。
    if isinstance(raw.get("monitors"), dict):
        m = raw["monitors"]
        if isinstance(m.get("enabled"), list):
            idxs = []
            for v in m["enabled"]:
                try:
                    idxs.append(int(v))
                except (TypeError, ValueError):
                    pass
            cfg["monitors"]["enabled"] = idxs
        if isinstance(m.get("vcp"), dict):
            vcp = {}
            for k, v in m["vcp"].items():
                try:
                    vcp[str(int(k))] = int(v)
                except (TypeError, ValueError):
                    pass
            cfg["monitors"]["vcp"] = vcp
        if isinstance(m.get("setup_done"), dict):
            done = {}
            for k, v in m["setup_done"].items():
                try:
                    done[str(int(k))] = bool(v)
                except (TypeError, ValueError):
                    pass
            cfg["monitors"]["setup_done"] = done
        # 跟随活跃屏（2.5.0）。老配置没有这两项，走默认：关、3 秒。
        cfg["monitors"]["follow_active"] = bool(
            m.get("follow_active", False))
        try:
            sec = float(m.get("follow_stable_seconds", 3.0))
        except (TypeError, ValueError):
            sec = 3.0
        # 低于 1 秒等于没有滞回，画面会跟着鼠标闪；超过 30 秒又迟钝得没法用
        cfg["monitors"]["follow_stable_seconds"] = max(1.0, min(30.0, sec))
    # ---- 画面补偿（Gamma 通道）开关 ----
    if isinstance(raw.get("gamma"), dict):
        if raw["gamma"].get("enabled") is not None:
            cfg["gamma"]["enabled"] = bool(raw["gamma"]["enabled"])
        if raw["gamma"].get("warn_hdr") is not None:
            cfg["gamma"]["warn_hdr"] = bool(raw["gamma"]["warn_hdr"])

    for key in ("poll_seconds", "debounce_seconds",
                "leave_grace_seconds", "leave_grace_fullscreen_seconds",
                "override_check_seconds",
                "dialog_timeout_seconds", "manual_override_pause_minutes"):
        if raw.get(key) is not None:
            try:
                cfg[key] = float(raw[key]) if key.endswith("seconds") \
                    else int(raw[key])
            except (TypeError, ValueError):
                pass
    if raw.get("ask_before_switch") is not None:
        cfg["ask_before_switch"] = bool(raw["ask_before_switch"])

    # 旧版 idle_minutes / default_mode
    if isinstance(raw.get("idle"), dict):
        cfg["idle"].update({k: raw["idle"][k] for k in raw["idle"]
                            if k in cfg["idle"]})
    elif raw.get("idle_minutes") is not None:
        try:
            cfg["idle"]["minutes"] = float(raw["idle_minutes"])
        except (TypeError, ValueError):
            pass
    if isinstance(raw.get("return_default"), dict):
        cfg["return_default"].update(
            {k: raw["return_default"][k] for k in raw["return_default"]
             if k in cfg["return_default"]})
    elif raw.get("default_mode"):
        cfg["return_default"]["mode"] = raw["default_mode"]

    cfg["version"] = CONFIG_VERSION
    return cfg


def _clean_mode(m):
    """把一个模式条目洗成规范形态，丢掉无效字段。

    允许的模式形态（三者可以任意组合）：
      {"name": "阅读模式", "vcp": 5}                      # 靠显示器自己的档位
      {"name": "护眼模式", "gamma": {...}}                # 靠显卡查找表模拟
      {"name": "某某", "per_monitor": {"1": {...}}}        # 靠亮度/对比度
    """
    if not isinstance(m, dict) or not (m.get("name") or "").strip():
        return None
    out = {"name": m["name"].strip(),
           "color": m.get("color") or T.ACCENT}
    v = m.get("vcp")
    try:
        out["vcp"] = None if v is None else int(v)
    except (TypeError, ValueError):
        out["vcp"] = None

    mv = m.get("monitor_vcp")
    if isinstance(mv, dict):
        clean = {}
        for k, val in mv.items():
            try:
                clean[str(int(k))] = int(val)
            except (TypeError, ValueError):
                pass
        if clean:
            out["monitor_vcp"] = clean

    per = m.get("per_monitor")
    if isinstance(per, dict):
        clean = {}
        for k, val in per.items():
            if not isinstance(val, dict):
                continue
            try:
                key = str(int(k))
            except (TypeError, ValueError):
                continue
            d = {}
            for field in ("brightness", "contrast"):
                try:
                    if val.get(field) is not None:
                        d[field] = max(0, min(100, int(val[field])))
                except (TypeError, ValueError):
                    pass
            if d:
                clean[key] = d
        if clean:
            out["per_monitor"] = clean

    # 画面补偿参数：全 1.0（等于不改）就不落盘，让配置干净
    g = m.get("gamma")
    if isinstance(g, dict):
        norm = gamma.normalize(g)
        if not gamma.is_neutral(norm):
            out["gamma"] = norm
    return out


def _clean_app(a):
    exe = (a.get("exe") or "").strip().lower()
    if exe and "." not in exe:
        exe += ".exe"
    return {"name": (a.get("name") or exe or a.get("title") or "未命名").strip(),
            "exe": exe,
            "title": (a.get("title") or "").strip(),
            "src": a.get("src") or "custom"}


def _new_id(existing, base):
    base = (base or "group").strip() or "group"
    taken = {g.get("id") for g in existing}
    cand, i = base, 2
    while cand in taken:
        cand = "%s%d" % (base, i)
        i += 1
    return cand


# ------------------------------------------------------------------ 访问器
def modes(cfg):
    return cfg.get("modes", [])


def mode_names(cfg):
    return [m["name"] for m in modes(cfg) if m.get("name")]


def mode_vcp(cfg, name):
    for m in modes(cfg):
        if m.get("name") == name:
            v = m.get("vcp")
            try:
                return int(v)
            except (TypeError, ValueError):
                return None
    return None


def mode_color(cfg, name):
    for m in modes(cfg):
        if m.get("name") == name:
            return m.get("color") or T.ACCENT
    return T.ACCENT


def backfill_gamma(cfg):
    """给老配置里的**内置模式**补上默认画面补偿参数，返回补了几个。

    为什么不在 migrate 里做：migrate 每次加载都跑，补一次就够。
    只在「模式还没有 gamma 字段」且「名字正好是内置那 5 个之一」时补，
    用户自建的模式一律不碰 —— 不能替人瞎调画面。

    这一步是升级体验的关键：1.x 用户的配置里 5 个模式都没有补偿参数，
    升级后如果什么都不做，副屏照样不会变，等于功能没上。
    """
    defaults = {m["name"]: m.get("gamma") for m in _default_modes()}
    n = 0
    for m in cfg.get("modes", []):
        if not isinstance(m, dict) or "gamma" in m:
            continue
        g = defaults.get(m.get("name"))
        if isinstance(g, dict) and g:
            m["gamma"] = dict(g)
            n += 1
    return n


def mode_by_name(cfg, name):
    for m in modes(cfg):
        if m.get("name") == name:
            return m
    return None


def mode_gamma(cfg, name):
    """某个模式的画面补偿参数（已归一化）；没有或全中性返回 None。"""
    m = mode_by_name(cfg, name)
    return mode_gamma_of(m)


def mode_gamma_of(mode):
    if not isinstance(mode, dict):
        return None
    raw = mode.get("gamma")
    if not isinstance(raw, dict):
        return None
    g = gamma.normalize(raw)
    return None if gamma.is_neutral(g) else g


def mode_channels(mode):
    """这个模式能用上哪些通道 -> ["档位", "私有码", "亮/对", "补偿"]。

    主页「快捷切换」和 App.switch_to 都靠它判断"这个模式到底有没有东西可写"。
    以前只看 `vcp is not None`，导致「只有画面补偿」的模式在主页根本不显示 ——
    这正是用户反馈"主页也改不了"的原因之一。
    """
    if not isinstance(mode, dict):
        return []
    out = []
    if mode.get("vcp") is not None:
        out.append("档位")
    if mode.get("monitor_vcp"):
        out.append("私有码")
    if mode.get("per_monitor"):
        out.append("亮/对")
    if mode_gamma_of(mode):
        out.append("补偿")
    return out


def mode_usable(cfg, name):
    return bool(mode_channels(mode_by_name(cfg, name) or {}))


def gamma_enabled(cfg):
    return bool((cfg.get("gamma") or {}).get("enabled", True))


def gamma_warn_hdr(cfg):
    return bool((cfg.get("gamma") or {}).get("warn_hdr", True))


def next_mode_color(cfg):
    used = {m.get("color") for m in modes(cfg)}
    for c in T.MODE_PALETTE:
        if c not in used:
            return c
    return T.MODE_PALETTE[len(modes(cfg)) % len(T.MODE_PALETTE)]


def group_by_id(cfg, gid):
    for g in cfg.get("groups", []):
        if g.get("id") == gid:
            return g
    return None


def clone(cfg):
    return copy.deepcopy(cfg)


def all_app_count(cfg):
    return sum(len(g.get("apps", [])) for g in cfg.get("groups", []))
