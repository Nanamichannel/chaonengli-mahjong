# -*- coding: utf-8 -*-
"""为全部 46 张角色卡生成 4 个朝向的技能按钮/气泡图片。
   技能名：华文行楷
   技能详情：微软雅黑（不变）
   图片里的背景按卡牌朝向旋转，文字保持正置。
"""
import io, sys, os, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from PIL import Image, ImageDraw, ImageFont

BASE = 'Cailiao/UI'
OUT = 'Cailiao/skill/ui'
BTN_DIR = os.path.join(OUT, 'buttons')
BUB_DIR = os.path.join(OUT, 'bubbles')
os.makedirs(BTN_DIR, exist_ok=True)
os.makedirs(BUB_DIR, exist_ok=True)

FONT_NAME = 'C:/Windows/Fonts/STXINGKA.TTF'   # 华文行楷
FONT_DESC = 'C:/Windows/Fonts/msyh.ttc'       # 技能详情保持微软雅黑

with open(os.path.join(OUT, 'skills.json'), encoding='utf-8') as f:
    data = json.load(f)

# 删除旧的 92 张无后缀图，避免和新图混用
for d in (BTN_DIR, BUB_DIR):
    for fn in os.listdir(d):
        if fn.endswith('.png') and '_r' not in fn:
            os.remove(os.path.join(d, fn))

btn_base = Image.open(os.path.join(BASE, 'skillbutton.png')).convert('RGBA')
bub_base = Image.open(os.path.join(BASE, '技能气泡.png')).convert('RGBA')

# 卡牌旋转 → 文件名后缀。背景按这个角度旋转，文字保持 0°。
VARIANTS = [('r0', 0), ('r90', 90), ('r180', 180), ('rm90', -90)]

def fit_font(draw, text, max_w, max_h, start=104):
    size = start
    while size > 26:
        ft = ImageFont.truetype(FONT_NAME, size)
        box = draw.textbbox((0, 0), text, font=ft, stroke_width=4)
        if box[2] - box[0] <= max_w and box[3] - box[1] <= max_h:
            return ft, box
        size -= 2
    ft = ImageFont.truetype(FONT_NAME, 26)
    return ft, draw.textbbox((0, 0), text, font=ft, stroke_width=4)

def _btn_lines(name, angle):
    """竖版（±90）把技能名拆成多行：含空格按「词」拆，否则逐字拆。
       例：风神 -> 风/神 ；NO MISS -> NO/MISS ；南风 -> 南/风
       横版（0/180）保持一行。"""
    if angle not in (90, -90):
        return [name]
    nm = name.strip()
    parts = [w for w in nm.replace('\u3000', ' ').split(' ') if w]
    if len(parts) > 1:
        return parts
    return list(nm)


def _fit_lines(draw, lines, max_w, max_h, start=104, min_size=26):
    """给多行文字挑一个统一字号：每行宽度 <= max_w，总高度 <= max_h。"""
    size = start
    while size > min_size:
        ft = ImageFont.truetype(FONT_NAME, size)
        ws, hs = [], []
        for ln in lines:
            b = draw.textbbox((0, 0), ln, font=ft, stroke_width=4)
            ws.append(b[2] - b[0])
            hs.append(b[3] - b[1])
        gap = int(size * 0.12)
        if max(ws) <= max_w and sum(hs) + gap * (len(lines) - 1) <= max_h:
            return ft, ws, hs, gap
        size -= 2
    ft = ImageFont.truetype(FONT_NAME, min_size)
    ws, hs = [], []
    for ln in lines:
        b = draw.textbbox((0, 0), ln, font=ft, stroke_width=4)
        ws.append(b[2] - b[0])
        hs.append(b[3] - b[1])
    return ft, ws, hs, int(min_size * 0.12)


def make_button(name, tag, angle):
    if angle in (90, -90):
        cw, ch = 250, 446
        max_w, max_h = 230, 420
    else:
        cw, ch = 446, 250
        max_w, max_h = 410, 220
    bg = btn_base.rotate(angle, expand=True).resize((cw, ch), Image.LANCZOS)
    im = bg.copy()
    d = ImageDraw.Draw(im)
    lines = _btn_lines(name, angle)
    ft, ws, hs, gap = _fit_lines(d, lines, max_w, max_h)
    total_h = sum(hs) + gap * (len(lines) - 1)
    y = (ch - total_h) * 0.5
    for i, ln in enumerate(lines):
        b = d.textbbox((0, 0), ln, font=ft, stroke_width=4)
        x = (cw - ws[i]) * 0.5 - b[0]
        d.text((x, y - b[1]), ln, font=ft, fill=(240, 250, 255, 255),
               stroke_width=4, stroke_fill=(8, 34, 72, 255))
        y += hs[i] + gap
    im.save(os.path.join(BTN_DIR, tag))

def wrap_cn(draw, text, ft, max_w):
    lines, cur = [], ''
    for ch in text:
        if ch == '\n':
            lines.append(cur)
            cur = ''
            continue
        test = cur + ch
        if draw.textlength(test, font=ft) <= max_w:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = ch
    if cur:
        lines.append(cur)
    return lines

def make_bubble(desc, tag, angle):
    bw = 760
    pad_l, pad_r, pad_t, pad_b = 44, 44, 34, 34
    line_gap = 8
    ft = ImageFont.truetype(FONT_DESC, 30)
    probe = ImageDraw.Draw(Image.new('RGBA', (10, 10)))
    lines = wrap_cn(probe, desc, ft, bw - pad_l - pad_r)
    line_h = 44
    h = max(180, pad_t + pad_b + line_h * len(lines) + line_gap * max(0, len(lines) - 1))
    # 背景先按卡牌朝向旋转，再不等比缩放到文字所需的画布
    bg = bub_base.rotate(angle, expand=True).resize((bw, h), Image.LANCZOS)
    im = bg.copy()
    d = ImageDraw.Draw(im)
    y = pad_t
    for ln in lines:
        d.text((pad_l, y), ln, font=ft, fill=(22, 36, 54, 255))
        y += line_h + line_gap
    im.save(os.path.join(BUB_DIR, tag))

count = 0
for n in range(1, 47):
    arr = data[str(n)]['skills']
    for i, s in enumerate(arr[:2], start=1):
        for vtag, angle in VARIANTS:
            make_button(s['name'], f'card_{n:02d}_{i}_{vtag}.png', angle)
            make_bubble(s['desc'], f'card_{n:02d}_{i}_{vtag}.png', angle)
            count += 2

print('generated', count, 'images')
