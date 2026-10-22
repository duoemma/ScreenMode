# -*- coding: utf-8 -*-
"""单独跑各个对话框看外观：python _tools/test_dialog.py [switch|app|mode|group|confirm|preset]"""
import ctypes
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ctypes.windll.user32.SetProcessDPIAware()

from PIL import ImageGrab

from screenmode.ui import dialogs as D


class FakeDDC:
    def get_mode(self):
        return 5


class FakeApp:
    ddc = FakeDDC()

    def log(self, msg):
        print(msg)


def shoot(path, delay=1.2):
    time.sleep(delay)
    ImageGrab.grab().save(path)
    print("saved", path)


def main():
    kind = sys.argv[1] if len(sys.argv) > 1 else "switch"
    if kind == "switch":
        threading.Thread(target=shoot, args=("t_switch.png", 1.5),
                         daemon=True).start()
        r = D.SwitchDialog(None, "阅读模式",
                           ["用户模式", "阅读模式", "电影模式", "节能模式",
                            "FPS模式"], 10,
                           "检测到【猫爪视频】正在使用 · 分组「影视类」").run()
    elif kind == "app":
        threading.Thread(target=shoot, args=("t_app.png", 1.2),
                         daemon=True).start()
        r = D.AppDialog(None, "添加应用").run()
    elif kind == "mode":
        threading.Thread(target=shoot, args=("t_mode.png", 1.2),
                         daemon=True).start()
        r = D.ModeDialog(None, FakeApp(), "护眼模式", 3).run()
    elif kind == "group":
        threading.Thread(target=shoot, args=("t_group.png", 1.2),
                         daemon=True).start()
        r = D.GroupDialog(None, ["用户模式", "阅读模式", "电影模式",
                                 "节能模式", "FPS模式"]).run()
    elif kind == "preset":
        threading.Thread(target=shoot, args=("t_preset.png", 1.2),
                         daemon=True).start()
        r = D.PresetDialog(None, "fps", ["cs2.exe"]).run()
    else:
        threading.Thread(target=shoot, args=("t_confirm.png", 1.2),
                         daemon=True).start()
        r = D.ConfirmDialog(None, "删除分组",
                            "确定删除分组「办公阅读类」吗？\n里面的 5 个应用配置会一起删除。",
                            ok_text="删除", danger=True).run()
    print("result:", r)


if __name__ == "__main__":
    main()
