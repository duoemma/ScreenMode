# -*- coding: utf-8 -*-
"""开发辅助：看看每块屏的 gamma 查找表现在是什么样（判断有没有残留补偿）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from screenmode import gamma as G   # noqa: E402


def main():
    ch = G.GammaChannel(store_path=None)
    for i in range(1, 9):
        dev = "\\\\.\\DISPLAY%d" % i
        r = ch.read(dev)
        if not r:
            continue
        print("%-16s R=%6d G=%6d B=%6d" % (dev, r[0][128], r[1][128], r[2][128]))
    ch.close()
    print("（恒等斜坡的三通道都应该是 32896）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
