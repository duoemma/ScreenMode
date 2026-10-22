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
              "checkup_base.json", "build_log.txt"}
SKIP_EXT = (".pyc", ".pyo", ".spec", ".lnk", ".log")


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
    sys.exit(main())
