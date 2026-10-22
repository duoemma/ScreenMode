# -*- coding: utf-8 -*-
"""内置应用预设库 + 分组模板。

想给软件加一个"基础选项"，只需要往下面的列表里加一行：
    {"name": "应用显示名", "exe": "进程名.exe"}
其他功能（预设里勾选、按类别过滤、去重）都会自动生效。
"""

# 分组模板：kind 决定用哪一套预设
GROUP_ARCHETYPES = [
    ("office", {"name": "办公阅读类", "mode": "阅读模式",
                "hint": "Word / PDF / 浏览器文档等，适合低蓝光阅读预设"}),
    ("fps", {"name": "FPS 游戏类", "mode": "FPS模式",
             "hint": "射击类游戏，适合高响应、暗部增强的预设"}),
    ("video", {"name": "影视类", "mode": "电影模式",
               "hint": "视频客户端与本地播放器，适合高对比色彩预设"}),
]

# 新建分组时可选的模板（含"自定义"）
NEW_GROUP_KINDS = GROUP_ARCHETYPES + [
    ("game", {"name": "其他游戏类", "mode": "用户模式",
              "hint": "非 FPS 游戏（MOBA / 开放世界等）"}),
    ("custom", {"name": "自定义分组", "mode": "用户模式",
                "hint": "空白分组，全部应用自己添加"}),
]

GROUP_LABEL = {k: v["name"] for k, v in NEW_GROUP_KINDS}

# 默认启用的分组（首次运行时的三组）
DEFAULT_KINDS = [k for k, _ in GROUP_ARCHETYPES]


PRESETS = {
    # ---------------- 办公阅读 ----------------
    "office": [
        {"name": "Word", "exe": "winword.exe"},
        {"name": "Excel", "exe": "excel.exe"},
        {"name": "PowerPoint", "exe": "powerpnt.exe"},
        {"name": "OneNote", "exe": "onenote.exe"},
        {"name": "WPS 文字", "exe": "wps.exe"},
        {"name": "WPS 表格", "exe": "et.exe"},
        {"name": "WPS 演示", "exe": "wpp.exe"},
        {"name": "WPS PDF", "exe": "wpspdf.exe"},
        {"name": "记事本", "exe": "notepad.exe"},
        {"name": "写字板", "exe": "wordpad.exe"},
        {"name": "Adobe Acrobat", "exe": "acrobat.exe"},
        {"name": "福昕阅读器", "exe": "foxitpdfreader.exe"},
        {"name": "SumatraPDF", "exe": "sumatrapdf.exe"},
        {"name": "Edge 浏览器", "exe": "msedge.exe"},
        {"name": "Chrome 浏览器", "exe": "chrome.exe"},
        {"name": "Firefox 浏览器", "exe": "firefox.exe"},
        {"name": "Typora", "exe": "typora.exe"},
        {"name": "Obsidian", "exe": "obsidian.exe"},
        {"name": "Notion", "exe": "notion.exe"},
        {"name": "印象笔记", "exe": "evernote.exe"},
        {"name": "微信读书", "exe": "weread.exe"},
        {"name": "XMind 思维导图", "exe": "xmind.exe"},
    ],
    # ---------------- FPS 游戏 ----------------
    "fps": [
        {"name": "绝地求生 PUBG", "exe": "tslgame.exe"},
        {"name": "CS2", "exe": "cs2.exe"},
        {"name": "CS:GO", "exe": "csgo.exe"},
        {"name": "穿越火线 CF", "exe": "crossfire.exe"},
        {"name": "无畏契约 VALORANT", "exe": "valorant.exe"},
        {"name": "Apex 英雄", "exe": "r5apex.exe"},
        {"name": "守望先锋", "exe": "overwatch.exe"},
        {"name": "三角洲行动", "exe": "deltaforceclient-win64-shipping.exe"},
        {"name": "使命召唤", "exe": "cod.exe"},
        {"name": "彩虹六号：围攻", "exe": "rainbowsix.exe"},
        {"name": "战地 2042", "exe": "bf2042.exe"},
        {"name": "泰坦陨落 2", "exe": "titanfall2.exe"},
    ],
    # ---------------- 影视 ----------------
    "video": [
        {"name": "腾讯视频", "exe": "qqlive.exe"},
        {"name": "爱奇艺", "exe": "qyclient.exe"},
        {"name": "优酷", "exe": "youkudesktop.exe"},
        {"name": "哔哩哔哩", "exe": "bilibili.exe"},
        {"name": "芒果 TV", "exe": "mangotv.exe"},
        {"name": "咪咕视频", "exe": "miguvideo.exe"},
        {"name": "搜狐视频", "exe": "sohuva.exe"},
        {"name": "抖音", "exe": "douyin.exe"},
        {"name": "PotPlayer", "exe": "potplayermini64.exe"},
        {"name": "VLC", "exe": "vlc.exe"},
        {"name": "MPV", "exe": "mpv.exe"},
        {"name": "迅雷影音", "exe": "thunderplayer.exe"},
        {"name": "UZN 视频", "exe": "uzn.exe"},
        {"name": "猫爪视频", "exe": "", "title": "猫爪"},
    ],
    # ---------------- 其他游戏 ----------------
    "game": [
        {"name": "英雄联盟", "exe": "league of legends.exe"},
        {"name": "英雄联盟客户端", "exe": "leagueclient.exe"},
        {"name": "永劫无间", "exe": "narakabladepoint.exe"},
        {"name": "原神", "exe": "genshinimpact.exe"},
        {"name": "崩坏：星穹铁道", "exe": "starrail.exe"},
        {"name": "我的世界", "exe": "javaw.exe"},
        {"name": "赛博朋克 2077", "exe": "cyberpunk2077.exe"},
        {"name": "艾尔登法环", "exe": "eldenring.exe"},
        {"name": "极限竞速：地平线 5", "exe": "forzahorizon5.exe"},
    ],
    "custom": [],
}


def default_apps(kind):
    return list(PRESETS.get(kind, []))


def presets_for(kind):
    return list(PRESETS.get(kind, []))


def friendly_name(exe):
    """winword.exe -> Word（找不到就用文件名）"""
    exe_l = (exe or "").lower()
    for apps in PRESETS.values():
        for a in apps:
            if a.get("exe") and a["exe"].lower() == exe_l:
                return a["name"]
    if not exe_l:
        return "未命名"
    stem = exe_l[:-4] if exe_l.endswith(".exe") else exe_l
    return stem.capitalize()


def is_preset(kind, exe):
    exe_l = (exe or "").lower()
    return any(a.get("exe", "").lower() == exe_l and exe_l
               for a in PRESETS.get(kind, []))


def archetype(kind):
    for k, meta in NEW_GROUP_KINDS:
        if k == kind:
            return dict(meta)
    return {"name": GROUP_LABEL.get(kind, "自定义分组"),
            "mode": "用户模式", "hint": ""}
