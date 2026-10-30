"""
牌山编号系统（服务端唯一的一份，客户端不再自己算）

一墩 = 两张牌。
编号 1..136：从骰子指到的那一面、最右边那墩开始，沿牌山绕一圈编号，
一张牌的「编号 no」↔ 牌山序列 seq = no - 1（seq 0..135）。
同一墩的两张：上面那张 = 奇数号，下面那张 = 偶数号。

拿牌：从第 n 墩开始（n = 骰子点数 + 1）。
王牌（就在起点前面那 6 墩）：
    第 n-1、n-2 墩  = 岭上 4 张（摸的顺序：编号最大的叫「岭上第一张」，先摸它）
    第 n-3 ~ n-6 墩 = 宝牌指示牌：一墩两张，上面那张是表宝牌指示牌、下面那张是里宝牌指示牌
普通摸牌会跳过这 6 墩；开杠时从岭上按顺序补牌，并翻下一张宝牌指示牌。

绕圈方向（按主视角）：下排(东) 右→左、左列(西) 下→上、上排(北) 左→右、右列(南) 上→下。
"""
from __future__ import annotations

import random

TOTAL_STACKS = 68                 # 一局 68 墩
TILES_PER_STACK = 2
TOTAL_TILES = TOTAL_STACKS * TILES_PER_STACK      # 136

SIDE_ORDER = ["东", "南", "西", "北"]              # 骰子点数 → 从哪一面开始编号
RINSHAN_STACKS = 2                # 岭上 2 墩 = 4 张
DORA_STACKS = 4                   # 宝牌指示牌 4 墩（表 4 张 + 里 4 张）
SPARE_STACKS = 1                  # 王牌里不翻的保障墩（2 张）
# 王牌 = 7 墩 = 14 张（用户口径 2026-10-28）：岭上 4 + 宝牌/里宝 8 + 保障 2
DEAD_STACKS = RINSHAN_STACKS + DORA_STACKS + SPARE_STACKS
DEAD_TILES = DEAD_STACKS * TILES_PER_STACK


# ────────────────────────── 骰子 / 起点 ──────────────────────────

def roll(rng: random.Random | None = None) -> tuple[int, int]:
    r = rng or random
    return r.randint(1, 6), r.randint(1, 6)


def start_side(dice: tuple[int, int]) -> str:
    """骰子点数指向哪一面的牌山。"""
    return SIDE_ORDER[(sum(dice) - 2) % len(SIDE_ORDER)]


def first_stack_no(dice: tuple[int, int]) -> int:
    """从第几墩开始拿 = 点数 + 1（4+5=9 → 第 10 墩；2+1=3 → 第 4 墩）。"""
    return sum(dice) + 1


# ────────────────────────── 编号 ↔ 墩 / seq ──────────────────────────

def stack_of_tile(no: int) -> int:
    """这张牌（编号）属于第几墩。上面那张（奇数）= 这墩；下面那张（偶数）= 同一墩。"""
    return (no + 1) // 2


def tile_nos_of_stack(k: int) -> tuple[int, int]:
    """第 k 墩的两张牌编号：[上面那张, 下面那张]。"""
    return k * 2 - 1, k * 2


def seq_of_tile(no: int) -> int:
    """编号 → 牌山序列 seq（0..135）。"""
    return no - 1


def tile_of_seq(seq: int) -> int:
    """牌山序列 seq → 编号。"""
    return seq + 1


def wrap_stack(k: int) -> int:
    """墩号循环到 1..68。"""
    return ((k - 1) % TOTAL_STACKS + TOTAL_STACKS) % TOTAL_STACKS + 1


def wrap_tile(no: int) -> int:
    """编号循环到 1..136。"""
    return ((no - 1) % TOTAL_TILES + TOTAL_TILES) % TOTAL_TILES + 1


# ────────────────────────── 王牌 ──────────────────────────

def dead_stack_nos(n: int) -> list[int]:
    """王牌那 **7 墩**（14 张）：[n-1 … n-7]（含绕圈）。

    n-1/n-2 = 岭上，n-3..n-6 = 宝牌/里宝指示，n-7 = 不翻的保障墩。
    """
    return [wrap_stack(n - i) for i in range(1, DEAD_STACKS + 1)]


def is_dead_stack(k: int, n: int) -> bool:
    return wrap_stack(k) in dead_stack_nos(n)


def is_dead_tile(no: int, n: int) -> bool:
    return is_dead_stack(stack_of_tile(no), n)


def rinshan_tile_nos(n: int) -> list[int]:
    """岭上 4 张，按「摸的顺序」排：先岭上第一张（编号最大的那张），最后第四张。"""
    nos: list[int] = []
    for k in (n - 1, n - 2):
        a, b = tile_nos_of_stack(wrap_stack(k))
        nos += [a, b]
    nos.sort(reverse=True)
    return nos


def dora_stack_no(n: int, idx: int) -> int:
    """第 idx 张宝牌指示牌在第几墩（idx 从 0 起：n-3、n-4、n-5、n-6）。"""
    return wrap_stack(n - 3 - idx)


def dora_tile_nos(n: int, idx: int) -> tuple[int, int]:
    """第 idx 张宝牌指示牌：(表宝牌指示牌的编号, 里宝牌指示牌的编号)。"""
    k = dora_stack_no(n, idx)
    return tile_nos_of_stack(k)


# ────────────────────────── 配牌计划 ──────────────────────────

def deal_plan(n: int, dealer: int = 0) -> dict:
    """整段配牌计划（服务端算，客户端照着摆）。

    3 圈：每圈每人 4 张；
    第 4 圈：每人 1 张，庄家这一下同时「跳牌」——把第 14 张也一起拿走（隔 4 张）。
    返回 {"steps": [...], "next_no": 配牌结束后牌山前面的编号, "jump_no": 跳牌那张}
    """
    steps: list[dict] = []
    no = n * 2 - 1                                   # 起点：第 n 墩的上面那张
    d = int(dealer) % 4
    for rnd in range(3):
        for k in range(4):
            seat = (d + k) % 4                       # 从庄家开始按座次发
            tiles = [no + i for i in range(4)]
            steps.append({"round": rnd, "seat": seat, "tiles": tiles, "drawn": False})
            no += 4
    # 第 4 圈：庄家（0 号位）1 张 + 跳牌第 14 张
    jump_no = no + 4
    for k in range(4):
        seat = (d + k) % 4
        step = {"round": 3, "seat": seat, "tiles": [no + k], "drawn": False}
        if k == 0:
            step["jump"] = jump_no
        steps.append(step)
    return {"steps": steps, "jump_no": jump_no, "next_no": jump_no + 1}


# ────────────────────────── 普通摸牌 ──────────────────────────

def next_live_no(no: int, n: int) -> int | None:
    """从 no 开始往后找第一张不是王牌的牌；找不到（绕完一整圈）返回 None。"""
    cur = wrap_tile(no)
    for _ in range(TOTAL_TILES):
        if not is_dead_tile(cur, n):
            return cur
        cur = wrap_tile(cur + 1)
    return None


def skip_to_next_stack(no: int) -> int:
    """这一墩不能摸 → 跳到下一墩的上面那张。"""
    return wrap_tile(stack_of_tile(no) * 2 + 1)
