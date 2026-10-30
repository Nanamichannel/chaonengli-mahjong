# -*- coding: utf-8 -*-
"""离线生成 Card01 Skill2 用的「东南西北」四个小按钮贴图。

运行：python gen_wind_ui.py
输出：Cailiao/skill/ui/winds/{dong,nan,xi,bei}.png（128x128，透明底）

样式：深色圆底 + 细亮边 + 白色字（带深色描边），缩到很小也看得清。
"""
from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "Cailiao", "skill", "ui", "winds")
FONT = "C:/Windows/Fonts/msyhbd.ttc"        # 微软雅黑粗体
FONT_ALT = "C:/Windows/Fonts/msyh.ttc"

SIZE = 128
CHARS = [("dong", "东"), ("nan", "南"), ("xi", "西"), ("bei", "北")]


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    font_path = FONT if os.path.exists(FONT) else FONT_ALT
    font = ImageFont.truetype(font_path, 84)

    for key, ch in CHARS:
        img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        # 圆底
        d.ellipse((6, 6, SIZE - 7, SIZE - 7), fill=(16, 26, 44, 235),
                  outline=(120, 190, 255, 255), width=5)
        # 字（白色 + 深色描边）：先量一下居中
        box = d.textbbox((0, 0), ch, font=font, stroke_width=4)
        w = box[2] - box[0]
        h = box[3] - box[1]
        xy = ((SIZE - w) / 2 - box[0], (SIZE - h) / 2 - box[1])
        d.text(xy, ch, font=font, fill=(255, 255, 255, 255),
               stroke_width=4, stroke_fill=(6, 14, 28, 255))
        path = os.path.join(OUT_DIR, f"{key}.png")
        img.save(path)
        print("生成", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
