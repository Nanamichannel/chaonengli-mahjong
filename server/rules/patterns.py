# -*- coding: utf-8 -*-
"""角色卡技能用的「番种」判定（国标牌型）
=====================================================================
这三个不是日麻的役，只在 ctx["pattern_bonus"] 打开时才计番
（见 rules/yaku.py 的 _eval_one 末尾）。目前由 Card01 Skill1「国标」使用：

    五门齐      万、筒、索、风、箭 五门齐全
    花龙        三种花色的 123 / 456 / 789 各一个顺子
    三色三步高  三种花色各一个顺子，数字依次递增 1 或 2

判定输入和 rules/agari.py 一致：
    sets = [("run", i), ("triplet", i), ("kan", i), …]   ← 已经含副露
    pair = 雀头索引 0..33（七对子之类没有雀头时是 -1）
"""

from __future__ import annotations

SUIT_NAMES = ("万", "筒", "索")

# 花色分组：0/1/2 = 万/筒/索，3 = 风（东南西北），4 = 箭（白发中）
def _group(i: int) -> int:
    if 0 <= i < 9:
        return 0
    if 9 <= i < 18:
        return 1
    if 18 <= i < 27:
        return 2
    if 27 <= i < 31:
        return 3
    return 4


def _indices(s: tuple) -> list[int]:
    return [s[1], s[1] + 1, s[1] + 2] if s[0] == "run" else [s[1]]


def _all_indices(sets, pair) -> list[int]:
    out: list[int] = []
    for s in sets:
        out += _indices(s)
    if pair is not None and pair >= 0:
        out.append(pair)
    return out


def wumenqi(sets, pair) -> bool:
    """五门齐：万、筒、索、风、箭五门牌齐全。"""
    groups = set()
    for i in _all_indices(sets, pair):
        groups.add(_group(i))
    return len(groups) == 5


def _runs(sets) -> set[tuple[int, int]]:
    """顺子集合：(花色 0..2, 起点 0..6) —— 起点 0 = 123，起点 3 = 456，起点 6 = 789。"""
    out: set[tuple[int, int]] = set()
    for s in sets:
        if s[0] != "run":
            continue
        i = s[1]
        if 0 <= i < 27:
            out.add((i // 9, i % 9))
    return out


def hualong(sets) -> bool:
    """花龙：三种花色各一个 123 / 456 / 789。"""
    runs = _runs(sets)
    for a in range(3):                       # 123 的花色
        if (a, 0) not in runs:
            continue
        for b in range(3):                   # 456 的花色
            if b == a or (b, 3) not in runs:
                continue
            c = 3 - a - b                    # 剩下那种花色
            if (c, 6) in runs:
                return True
    return False


def sanse_step(sets) -> bool:
    """三色三步高：三种花色各一个顺子，数字依次递增一位或两位。"""
    runs = _runs(sets)
    starts = {suit: sorted({st for (s2, st) in runs if s2 == suit}) for suit in range(3)}
    for a in starts[0]:
        for b in starts[1]:
            for c in starts[2]:
                v = sorted((a, b, c))
                step = v[1] - v[0]
                if step in (1, 2) and v[2] - v[1] == step:
                    return True
    return False


def matched(sets, pair) -> list[str]:
    """这一手满足哪几个番种（按固定顺序，方便显示）。"""
    out: list[str] = []
    if wumenqi(sets, pair):
        out.append("五门齐")
    if hualong(sets):
        out.append("花龙")
    if sanse_step(sets):
        out.append("三色三步高")
    return out
