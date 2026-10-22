# -*- coding: utf-8 -*-
"""开发辅助：用 GitHub API 建 Release 并上传 exe（走本机已登录的 git 凭据）。

    python _tools/gh_release.py            # 建 v2.5.0 并传两个 exe
    python _tools/gh_release.py --dry      # 只看要传什么

令牌从 `git credential fill` 现取（GCM 里已经存着），**不打印、不落盘**。
`api.github.com` 直连是通的；`uploads.github.com` 不一定，所以每个请求都
先直连、失败了再走 Clash 代理重试。
"""
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OWNER, REPO = "duoemma", "ScreenMode"
TAG = "v2.5.0"
TITLE = "屏效助手 v2.5.0"
PROXY = "http://127.0.0.1:7897"

ASSETS = [
    os.path.join(os.path.expanduser("~"), "Desktop", "屏效助手 v2.5", "屏效助手.exe"),
    os.path.join(os.path.expanduser("~"), "Desktop", "屏效助手 v2.5", "屏幕体检.exe"),
]

BODY = """\
**屏效助手 v2.5.0** —— 按你正在用的软件，自动切换外接显示器的 OSD 情景预设
（阅读 / 电影 / 节能 / FPS…）。不用厂商软件，不用记快捷键。

## 下载哪个

| 文件 | 干什么 | 要不要下 |
| --- | --- | --- |
| `屏效助手.exe` | 主程序：托盘常驻、按前台程序自动切模式 | **必下** |
| `屏幕体检.exe` | 装之前先查这台屏行不行（全程只读，不改任何设置） | 可选 |

**绿色单文件，双击就运行** —— 不用装 Python、不用装运行库、没有安装步骤。
配置、日志、画面基线都写在 exe 旁边；不想用了把文件夹删掉即可，不留垃圾。

## 这一版新增

- **跟随活跃屏**：控制目标自动跟着你此刻正在操作的那块屏走。在哪块屏上开 Word，
  哪块屏进阅读模式；换到另一块屏干活，3 秒后跟过去，**旧屏保持上一次的样子**
  （不会"我一走它就弹回原样"）。
- 判定依据：以前台窗口落在哪块屏为主，只有前台是桌面/任务栏/开始菜单时才退回鼠标位置
  —— 用键盘写文档、打游戏时鼠标可以几十分钟不动，只看鼠标会长期判错。
- 3 秒滞回：鼠标划到另一块屏取个东西不会来回切档位，画面不会闪。
- 顺手修掉 exe 属性页版本号一直停在 2.3.0 的问题（`filevers` 原来是写死的）。

## 第一次运行

- 需要 **Windows 10 / 11（x64）**。
- 会弹"Windows 已保护你的电脑"：这个 exe 没买代码签名证书（个人项目常见），
  点 **更多信息 → 仍要运行** 即可。杀软报"未知程序"同理，加信任就行 ——
  源码全在仓库里，也可以 `python main.py` 自己跑。
- 放在**能写的目录**（桌面、D 盘、U 盘都行），**别放 `C:\\Program Files`**，
  那里写不进配置和日志。

## 它能做什么

- 打开 Word / 浏览器文档 → **阅读模式**；打开 PUBG / CS2 / 无畏契约 → **FPS 模式**；
  看视频 → **电影模式**；离开键盘 10 分钟 → **节能模式**
- 两条通道一起上，每台屏单独判断走哪条：
  **DDC/CI 真值**（让显示器换 OSD 预设，连背光都跟着变）／
  **画面补偿**（改显卡 Gamma 表，不依赖固件和 DDC，任何屏都能用）
- 多屏：可以只控其中几台，也可以让它自动跟着你正在操作的那台
- 写入后读回比对，能认出"set 成功但被显示器忽略"的假成功并自动降级

有问题、想提需求、或者想帮忙试新屏，直接开
[Issue](https://github.com/duoemma/ScreenMode/issues) —— 模板里写了要贴哪些信息。
"""


def token():
    """从 git 凭据管理器取 GitHub 令牌（GCM 里已经存着了）。"""
    out = subprocess.run(
        ["git", "credential", "fill"],
        input="protocol=https\nhost=github.com\n\n",
        capture_output=True, text=True, timeout=20,
        env=dict(os.environ, GIT_TERMINAL_PROMPT="0")).stdout
    for line in out.splitlines():
        if line.startswith("password="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError("凭据管理器里没有 github.com 的令牌")


def call(url, tok, data=None, method=None, use_proxy=False, ctype="application/json"):
    h = {"Authorization": "Bearer %s" % tok,
         "Accept": "application/vnd.github+json",
         "User-Agent": "screenmode-release",
         "Content-Type": ctype}
    req = urllib.request.Request(url, data=data, headers=h,
                                 method=method or ("POST" if data else "GET"))
    if use_proxy:
        req.set_proxy("127.0.0.1", 7897)
    with urllib.request.urlopen(req, timeout=300) as r:
        body = r.read().decode("utf-8", "replace")
    return json.loads(body) if body.strip().startswith(("{", "[")) else body


def call_any(url, tok, data=None, method=None, ctype="application/json"):
    """先直连，失败再走代理 —— uploads.github.com 有时候直连不通。"""
    try:
        return call(url, tok, data, method, False, ctype)
    except (urllib.error.URLError, TimeoutError) as e:
        print("  直连失败（%s），改走代理…" % e.__class__.__name__)
        return call(url, tok, data, method, True, ctype)


def main():
    dry = "--dry" in sys.argv
    print("要传的文件：")
    for p in ASSETS:
        print("  %8.1f MB  %s" % (os.path.getsize(p) / 1048576.0, p))
    if dry:
        return 0

    tok = token()
    print("拿到令牌（长度 %d，不打印内容）" % len(tok))

    # 已经建过同名 tag 的 Release 就跳过，避免重复
    try:
        ex = call("https://api.github.com/repos/%s/%s/releases/tags/%s"
                  % (OWNER, REPO, TAG), tok)
        print("这个 tag 已经有 Release 了：%s" % ex.get("html_url"))
        rel = ex
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        payload = json.dumps({"tag_name": TAG, "target_commitish": "main",
                              "name": TITLE, "body": BODY,
                              "draft": False, "prerelease": False}).encode()
        rel = call_any("https://api.github.com/repos/%s/%s/releases"
                       % (OWNER, REPO), tok, payload)
        print("建好 Release：%s" % rel.get("html_url"))

    up = "https://uploads.github.com/repos/%s/%s/releases/%s/assets?name=" % (
        OWNER, REPO, rel["id"])
    have = {a["name"] for a in (rel.get("assets") or [])}
    for p in ASSETS:
        name = os.path.basename(p)
        if name in have:
            print("  %s 已经传过了，跳过" % name)
            continue
        with open(p, "rb") as f:
            blob = f.read()
        url = up + urllib.parse.quote(name)
        try:
            a = call_any(url, tok, blob, method="POST",
                         ctype="application/octet-stream")
            print("  传好 %s（%.1f MB）" % (a.get("name"),
                                         a.get("size", 0) / 1048576.0))
        except urllib.error.HTTPError as e:
            print("  %s 失败：%s %s" % (name, e.code,
                                       e.read().decode("utf-8", "replace")[:200]))
    print("\n发布页：https://github.com/%s/%s/releases" % (OWNER, REPO))
    return 0


if __name__ == "__main__":
    sys.exit(main())
