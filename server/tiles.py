# -*- coding: utf-8 -*-
"""
牌的基础工具（数据库层和规则层共用）
=====================================================================
命名和客户端 main.gd 完全一致：
    万 m / 筒 p / 索 s： 1m 2m … 9m，赤宝牌是 0m
    字牌（z 记法）：1z=东 2z=南 3z=西 4z=北 5z=白 6z=发 7z=中
"""

from __future__ import annotations

import random

SUITS = ("m", "p", "s")
HONORS = ("dong", "nan", "xi", "bei", "bai", "fa", "zhong")      # 东南西北白发中

NUM_TILES = [f"{n}{s}" for s in ("m", "p", "s") for n in range(1, 10)]
TILE_KINDS = NUM_TILES + list(HONORS)                            # 34 种

RED_FIVES = {"0m": "5m", "0p": "5p", "0s": "5s"}                 # 赤宝牌 → 普通牌
RED_SET = set(RED_FIVES)

KIND_INDEX = {k: i for i, k in enumerate(TILE_KINDS)}
Z_FROM_HONOR = {"dong": "1", "nan": "2", "xi": "3", "bei": "4",
                "bai": "5", "fa": "6", "zhong": "7"}
HONOR_FROM_Z = {v: k for k, v in Z_FROM_HONOR.items()}

# 中文名（显示用）
HONOR_CN = {"dong": "东", "nan": "南", "xi": "西", "bei": "北",
            "bai": "白", "fa": "发", "zhong": "中"}

# 幺九牌（国士无双用）
ORPHAN_KINDS = [0, 8, 9, 17, 18, 26, 27, 28, 29, 30, 31, 32, 33]


# ── 基本换算 ────────────────────────────────────────────────────────────────
def kind_of(tile: str) -> str:
    """赤宝牌按普通 5 算：0m→5m。"""
    return RED_FIVES.get(tile, tile)


def is_red(tile: str) -> bool:
    return tile in RED_SET


def is_honor(tile: str) -> bool:
    return tile in HONORS


def tile_number(tile: str) -> int:
    """数牌 1..9；赤宝牌算 5；字牌返回 0。"""
    t = kind_of(tile)
    return 0 if t in HONORS else int(t[0])


def tile_suit(tile: str) -> str:
    """'m'/'p'/'s'；字牌返回 ''。"""
    t = kind_of(tile)
    return "" if t in HONORS else t[1]


def index_of(tile: str) -> int:
    """牌 → 0..33（赤宝牌算普通 5）。"""
    return KIND_INDEX[kind_of(tile)]


def kind_at(i: int) -> str:
    return TILE_KINDS[i]


def is_terminal_or_honor(i: int) -> bool:
    """幺九牌：1/9 数牌 或 字牌。"""
    return i in ORPHAN_KINDS


def dora_from_indicator(indicator: str) -> str:
    """宝牌指示牌 → 实际宝牌（9→1、东南西北循环、白发中循环）。"""
    t = kind_of(indicator)
    if t in HONORS:
        i = HONORS.index(t)
        if i < 4:
            return HONORS[(i + 1) % 4]
        return HONORS[4 + (i - 4 + 1) % 3]
    n = int(t[0])
    return f"{1 if n == 9 else n + 1}{t[1]}"


# ── 手牌表示 ────────────────────────────────────────────────────────────────
def counts_of(tiles) -> list[int]:
    """一组牌 → 34 格的张数表。"""
    c = [0] * 34
    for t in tiles:
        c[index_of(t)] += 1
    return c


def tiles_of(counts: list[int]) -> list[str]:
    out = []
    for i, n in enumerate(counts):
        out += [TILE_KINDS[i]] * n
    return out


def parse_hand(text: str) -> list[str]:
    """
    方便写测试：'123m456p77z'、'0m1m2m'。
    0 表示赤宝牌（0m/0p/0s）；z 组的 1..7 = 东南西北白发中。
    """
    out, buf = [], ""
    for ch in text:
        if ch.isdigit():
            buf += ch
        else:
            for d in buf:
                if ch == "z":
                    out.append(HONOR_FROM_Z[d])          # 1z=东 … 7z=中
                else:
                    out.append(f"0{ch}" if d == "0" else f"{d}{ch}")
            buf = ""
    assert not buf, f"手牌写法有问题：{text}"
    return out


def format_hand(tiles) -> str:
    """一组牌 → '123m456p77z'（排序后，方便看）。"""
    out = []
    for suit in ("m", "p", "s"):
        group = [t for t in tiles if tile_suit(t) == suit]
        if not group:
            continue
        group.sort(key=lambda t: (tile_number(t), is_red(t)))
        out.append("".join("0" if is_red(t) else str(tile_number(t)) for t in group) + suit)
    zs = sorted(HONORS.index(t) for t in tiles if is_honor(t))
    if zs:
        out.append("".join(str(i + 1) for i in zs) + "z")
    return "".join(out)


def sort_tiles(tiles) -> list[str]:
    """按客户端的手牌顺序排（万→筒→索→字，赤 5 排在 5 前面）。"""

    def rank(t):
        suit_order = {"m": 0, "p": 1, "s": 2, "": 3}[tile_suit(t)]
        if is_honor(t):
            return (suit_order, HONORS.index(t), 0)
        return (suit_order, tile_number(t), 1 if is_red(t) else 0)

    return sorted(tiles, key=rank)


# ── 牌山 ────────────────────────────────────────────────────────────────────
def build_wall(red_fives: bool = True, seed: int | None = None) -> list[str]:
    """洗好的一副牌（136 张）。seed 固定 → 结果可复现（复盘用）。"""
    tiles: list[str] = []
    for t in TILE_KINDS:
        tiles += [t] * 4
    if red_fives:
        for red, normal in RED_FIVES.items():
            tiles[tiles.index(normal)] = red
    random.Random(seed).shuffle(tiles)
    return tiles


def wall_counts(red_fives: bool = True) -> list[int]:
    """整副牌各有多少张（赤 5 算进普通 5 里，用于校验）。"""
    return counts_of(build_wall(red_fives, 0))


# ── 实体编号（牌显示架构重构：一张物理牌 = 一个全局唯一 Node2D 实体） ────────
def build_entities(red_fives: bool = True) -> list[str]:
    """生成 136 个实体 ID 的固定编号（洗牌前，顺序稳定）。

    命名规则：kind + 两位序号，例如四张 1 万 = 1m01..1m04。
    赤宝牌独立成 kind：5m/5p/5s 各留 3 张（序号 01..03），
    第 4 张变成 0m/0p/0s（赤，序号 01），这样客户端能按编号区分赤 5。
    字牌用 tiles 命名：dong/nan/xi/bei/bai/fa/zhong。
    """
    out: list[str] = []
    for t in TILE_KINDS:
        if red_fives and t in RED_FIVES.values():
            out.append(f"{t}01")
            out.append(f"{t}02")
            out.append(f"{t}03")
            # 第 4 张 = 赤宝牌，kind 换成 0x
            for red, normal in RED_FIVES.items():
                if normal == t:
                    out.append(f"{red}01")
        else:
            out += [f"{t}{i:02d}" for i in range(1, 5)]
    assert len(out) == 136, f"实体数不对: {len(out)}"
    return out


def build_entity_wall(red_fives: bool = True, seed: int | None = None) -> list[str]:
    """洗好的 136 个实体 ID 序列（牌山）。seed 固定 → 可复现（复盘）。"""
    entities = build_entities(red_fives=red_fives)
    random.Random(seed).shuffle(entities)
    return entities


def entity_kind(entity: str) -> str:
    """实体 ID → 牌种。'1m01'→'1m'，'0m01'→'0m'（赤，需再 kind_of 归到 5m）。"""
    # 字牌 kind 是 dong..zhong（多字母），数牌是数字+花色（如 0m / 1m）
    if entity[0] in "0123456789":
        return entity[:2]
    # 字牌：dong/nan/xi/bei/bai/fa/zhong 后接 01
    for h in HONORS:
        if entity.startswith(h):
            return h
    return entity


def entity_tile(entity: str) -> str:
    """实体 ID → 规则层牌名（赤 0m 保留，字牌 dong 等保留）。"""
    return entity_kind(entity)
