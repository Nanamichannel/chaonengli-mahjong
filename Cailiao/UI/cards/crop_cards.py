# -*- coding: utf-8 -*-
"""裁剪 card_01~card_46.png 的指定区域，另存为新图片。

裁剪范围（用户确认：行=横向/宽，列=纵向/高）：
    left = 63, top = 139, right = 63 + 386 = 449, bottom = 139 + 385 = 524
结果尺寸：386 宽 × 385 高
"""
import os
from PIL import Image

SRC_DIR = r"N:\apps\tianma\Cailiao\UI\cards"
BOX = (63, 139, 63 + 386, 139 + 385)   # (left, top, right, bottom)

def main():
    names = [f"card_{i:02d}.png" for i in range(1, 47)]
    for name in names:
        src = os.path.join(SRC_DIR, name)
        with Image.open(src) as im:
            w, h = im.size
            # 校验裁剪范围不超过图片边界
            if BOX[2] > w or BOX[3] > h:
                raise RuntimeError(
                    f"{name} 尺寸 {w}x{h} 不足，裁剪框右{BOX[2]}下{BOX[3]}越界"
                )
            cropped = im.crop(BOX)
            stem = name.rsplit(".", 1)[0]
            out = os.path.join(SRC_DIR, f"{stem}_crop.png")
            cropped.save(out, format="PNG")
            print(f"{name} -> {os.path.basename(out)}  {cropped.size[0]}x{cropped.size[1]}")

if __name__ == "__main__":
    main()
