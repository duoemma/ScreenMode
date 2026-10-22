# -*- coding: utf-8 -*-
"""屏效助手 ScreenMode —— 根据前台程序自动切换显示器 OSD 情景模式。"""
import os
import sys

APP_NAME = "屏效助手"
APP_NAME_EN = "ScreenMode"
VERSION = "2.5.0"
AUTHOR = "MECHREVO"

# 绿色版：配置、日志、补偿基线、体检基线全放在 exe 旁边。
# 用户把文件夹整个删掉就等于卸载干净，不写注册表、不散落文件。
ENV_DIR = "SCREENMODE_HOME"     # 想强制指定数据目录时设它（便携 U 盘等）


def app_dir():
    """程序所在目录 —— 所有运行期文件都落在这里。

    放在 __init__ 而不是 app.py，是为了让「屏幕体检」也能用：
    它不能 import app（那边会拖进托盘库），但同样需要知道"我旁边是哪儿"。
    """
    forced = os.environ.get(ENV_DIR)
    if forced:
        return forced
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    # 开发态：screenmode/ 的上一层就是项目根
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
