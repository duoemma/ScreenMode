# -*- coding: utf-8 -*-
"""屏效助手 ScreenMode —— 开发环境入口。

    python main.py               正常启动
    python main.py --dry-run     演练模式（只写日志，不动显示器）

**绿色程序：没有安装，也没有卸载。** 想要卸载就退出程序、把整个文件夹删掉 ——
配置、日志、补偿基线全在同一个文件夹里，删完不留任何东西（唯一的例外是
你手动开过开机自启，那就到 任务管理器 → 启动 里把它关掉）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# PyInstaller --windowed 打包后 sys.stdout / sys.stderr 是 None。
# 这很致命：ctypes 回调里一旦抛异常，解释器要往 stderr 打 traceback，
# 遇到 None 就直接把整个进程带走 —— 表现为「程序启动后自己消失了、日志也没有」。
#
# 所以：stdout 丢到 null（日志函数里有 print，别让它污染文件），
#       stderr 接到 crash.log（真正的异常堆栈要留下来）。
if sys.stderr is None or sys.stdout is None:
    try:
        _base = (os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
                 else os.path.dirname(os.path.abspath(__file__)))
        if sys.stdout is None:
            sys.stdout = open(os.devnull, "w")
        if sys.stderr is None:
            sys.stderr = open(os.path.join(_base, "crash.log"), "a",
                              encoding="utf-8", errors="replace")
    except Exception:
        pass

try:
    import ctypes
    ctypes.windll.user32.SetProcessDPIAware()
except Exception:
    pass

from screenmode.app import App, BASE_DIR

if __name__ == "__main__":
    try:
        sys.exit(App().run() or 0)
    except SystemExit:
        raise
    except BaseException:
        # 兜底：别让程序"静默消失"，把堆栈留在 crash.log 里
        import traceback
        try:
            with open(os.path.join(BASE_DIR, "crash.log"), "a",
                      encoding="utf-8") as f:
                f.write("\n==== %s ====\n" % __import__("time").strftime(
                    "%Y-%m-%d %H:%M:%S"))
                f.write(traceback.format_exc())
        except Exception:
            pass
        raise
