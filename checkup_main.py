# -*- coding: utf-8 -*-
"""「屏幕体检」入口 —— 安装主程序之前先跑这个，确认你的显示器能不能用。

    python checkup_main.py

它和主程序**完全独立**：不读主程序的 config.json，不需要先安装，
绿色版双击就能跑。全程只读（唯一的写操作是把 0xDC 的当前值原样写回去），
最后会问你一句「画面变了吗」来确认显卡通道到底通不通。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 和 main.py 同样的兜底：--windowed 打包后 sys.stderr 是 None，
# ctypes 回调里抛异常会让解释器往 stderr 打 traceback，直接把进程带走。
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

if __name__ == "__main__":
    from screenmode.ui.checkupwin import CheckupWindow
    sys.exit(CheckupWindow().run() and 0 or 0)
