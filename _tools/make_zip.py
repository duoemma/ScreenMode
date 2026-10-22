# -*- coding: utf-8 -*-
"""开发辅助：把源码打成可分发的 zip（不含运行时文件）。

    python _tools/make_zip.py           生成 桌面/屏效助手-源码-v2.2.zip

排除的东西都是"跑起来才有"的：config.json / app.log / gamma_base.json /
build / dist / __pycache__ / _shots / _legacy。
_tools/ 要留着 —— 里面是这几个版本攒下来的探测脚本和测试，
换个环境排查问题时少走很多弯路。
"""
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from screenmode import VERSION            # noqa: E402

SKIP_DIRS = {"__pycache__", "build", "dist", "_legacy", "_shots", ".git",
             ".idea", ".vscode"}
SKIP_FILES = {"config.json", "config.json.tmp", "config.json.broken",
              "config.json.bak-before-2.1", "config.json.bak-before-2.4",
              "app.log", "crash.log", "gamma_base.json",
              # 体检工具的画面基线：也是本机专属，拿到别的机器上会把人画面改歪
              "checkup_base.json", "build_log.txt",
              # 发布脚本（连本机凭据/桌面路径），不随源码包走
              "gh_push.py", "gh_release.py",
              # 视频策划/口播稿属于拍摄资料，不随源码包发
              "视频介绍策划.md",
              # 一键发布脚本里就这台机器的仓库地址和桌面路径
              "一键发布到GitHub.bat"}
SKIP_EXT = (".pyc", ".pyo", ".spec", ".lnk", ".log")


SHARE_NOTE = """\
屏效助手 v{ver}  ·  绿色版（免安装）

────────────────────────────────
先看这里，30 秒能用起来
────────────────────────────────

【1】怎么打开
    双击「屏效助手.exe」。
    第一次 Windows 会拦一下，弹「Windows 已保护你的电脑」——
    点左边的「更多信息」，再点「仍要运行」。
    （因为这个 exe 没买代码签名证书，不是程序有问题。杀软报「未知程序」同理。）

    放哪儿都行：桌面、D 盘、U 盘。就是别放 Program Files（C 盘那个系统目录）——
    那里没有写权限，配置和日志会存不下来。

【2】第一次要点的两下
    ① 右键任务栏右下角的托盘图标（可能折叠在 ^ 里）→「打开主界面」
    ② 到「显示器与模式」页，把每个模式确认一遍（后面有说明）

【3】它自己会做什么
    打开 Word / PDF → 切阅读模式
    打开 PUBG / CS2  → 切 FPS 模式
    看视频          → 切电影模式
    离开键盘 10 分钟 → 切节能模式，一动就回来

────────────────────────────────
两个 exe 分别是干什么的
────────────────────────────────
屏效助手.exe    ← 主程序，日常用的就是它（约 16 MB）
屏幕体检.exe    ← 装之前先查这台屏行不行，只读不改，查完可以删

────────────────────────────────
不想用了
────────────────────────────────
退出程序，把整个文件夹删掉就行。
没有安装程序、没有卸载程序、不散落文件、不写注册表。
（唯一的例外：你手动开过「开机自启」，那就再到 任务管理器 → 启动 里关掉。）

各个文件是干什么的：
    config.json       你的配置（分组、模式、补偿参数）
    app.log           运行日志 —— 提问题的时候贴这个
    gamma_base.json   显卡原始画面曲线（撤销补偿时要写回去的基线）

────────────────────────────────
想知道更多
────────────────────────────────
完整说明：同一文件夹里的「使用说明.md」
问题反馈：https://github.com/duoemma/ScreenMode/issues
"""


def build_share():
    """打「开箱即用」包：两个 exe + 说明文字。

    和源码包分开，是因为分享对象不同 —— 收到源码包的人多半想改代码，
    收到这个包的人只想双击用。把 README/源码塞进来只会让人更迷茫。
    """
    dist = os.path.join(ROOT, "dist")
    pairs = [("屏效助手.exe", "屏效助手.exe"),
             ("屏幕体检.exe", "屏幕体检.exe")]
    for name, _ in pairs:
        p = os.path.join(dist, name)
        if not os.path.exists(p):
            print("缺 %s，先跑 python build.py --all" % p)
            return 1
    short = ".".join(VERSION.split(".")[:2])
    out = os.path.join(os.path.expanduser("~"), "Desktop",
                       "屏效助手-v%s-绿色版.zip" % short)
    note = SHARE_NOTE.format(ver=VERSION)
    guide = os.path.join(ROOT, "docs", "使用说明.md")
    root_dir = "屏效助手 v%s" % VERSION
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for name, arc in pairs:
            z.write(os.path.join(dist, name), root_dir + "/" + arc)
        # BOM 是为了老版记事本别把中文显示成乱码
        # 老版记事本不认 LF：不用 CRLF 的话整篇会挤成一行。
        # 加 BOM 是同一个原因 —— 别让中文变乱码。
        z.writestr(root_dir + "/运行说明.txt",
                   note.replace("\n", "\r\n").encode("utf-8-sig"))
        if os.path.exists(guide):
            z.write(guide, root_dir + "/使用说明.md")
    total = sum(i.file_size for i in zipfile.ZipFile(out).infolist())
    print("打好 %s" % out)
    print("解压后 %.1f MB，压缩包 %.1f MB"
          % (total / 1048576.0, os.path.getsize(out) / 1048576.0))
    return 0


def main():
    # 和上一版的命名对齐：文件名只写 major.minor（v2.1 → v2.2），
    # 补丁版本不进文件名，免得同一代源码出现好几个包。
    short = ".".join(VERSION.split(".")[:2])
    out = os.path.join(os.path.expanduser("~"), "Desktop",
                       "屏效助手-源码-v%s.zip" % short)
    n = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for base, dirs, files in os.walk(ROOT):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
            for f in sorted(files):
                if f in SKIP_FILES or f.endswith(SKIP_EXT):
                    continue
                full = os.path.join(base, f)
                rel = os.path.relpath(full, ROOT)
                z.write(full, os.path.join("screenmode-src", rel))
                n += 1
    print("打包 %d 个文件 -> %s" % (n, out))
    print("大小 %.1f KB" % (os.path.getsize(out) / 1024.0))
    return 0


if __name__ == "__main__":
    if "--share" in sys.argv:
        sys.exit(build_share())
    sys.exit(main())
