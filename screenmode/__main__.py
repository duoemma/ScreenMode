# -*- coding: utf-8 -*-
"""允许 python -m screenmode 启动。"""
import sys

try:
    import ctypes
    ctypes.windll.user32.SetProcessDPIAware()
except Exception:
    pass

from screenmode.app import App

if __name__ == "__main__":
    sys.exit(App().run() or 0)
