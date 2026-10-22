# -*- coding: utf-8 -*-
"""生成程序图标 assets/icon.ico（蓝色圆角方块 + 白色显示器）。

    python _tools/make_icon.py
"""
import os

from PIL import Image, ImageDraw

ACCENT = (52, 120, 246, 255)
DARK = (23, 27, 38, 255)


def rounded(draw, box, radius, fill):
    draw.rounded_rectangle(box, radius=radius, fill=fill)


def make(size):
    scale = size / 256.0
    img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # 底：蓝色圆角方块
    rounded(d, (8, 8, 248, 248), 56, ACCENT)
    # 显示器外框
    rounded(d, (52, 62, 204, 158), 12, (255, 255, 255, 235))
    rounded(d, (66, 76, 190, 144), 6, ACCENT)
    # 支架
    d.rectangle((114, 158, 142, 180), fill=(255, 255, 255, 235))
    rounded(d, (88, 180, 168, 196), 8, (255, 255, 255, 235))
    # 屏幕内的小亮点
    d.rounded_rectangle((84, 92, 132, 100), radius=4,
                        fill=(255, 255, 255, 240))
    d.rounded_rectangle((84, 110, 156, 118), radius=4,
                        fill=(255, 255, 255, 160))
    return img.resize((size, size), Image.LANCZOS) if scale != 1.0 else img


def main():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = os.path.join(here, "assets", "icon.ico")
    sizes = [16, 24, 32, 48, 64, 128, 256]
    imgs = [make(s) for s in sizes]
    imgs[-1].save(out, format="ICO",
                  sizes=[(s, s) for s in sizes])
    print("saved", out)


if __name__ == "__main__":
    main()
