# -*- coding: utf-8 -*-
"""
和牌 / 听牌 / 牌型拆解
=====================================================================
所有函数都按「暗牌 34 格张数表 + 副露列表」来算，副露每 1 组算 1 个面子。

面子写法： ("run", i)     顺子 i, i+1, i+2
          ("triplet", i)  刻子（三张一样）
          ("kan", i)      杠（四张一样；判定牌型时和刻子等价，但三杠子/符数要用到）
副露写法： {"kind": "chi"/"pon"/"minkan"/"ankan"/"kakan", "tiles": [...]}
"""

from __future__ import annotations

from tiles import ORPHAN_KINDS, TILE_KINDS, index_of

Meld = dict


# ── 副露 → 面子 ─────────────────────────────────────────────────────────────
def meld_to_set(meld: Meld) -> tuple:
    kind = meld.get("kind", "pon")
    tiles = meld.get("tiles") or []
    idxs = [index_of(t) for t in tiles]
    if kind == "chi":
        return ("run", min(idxs))
    if kind in ("minkan", "ankan", "kakan"):
        return ("kan", idxs[0])
    return ("triplet", idxs[0])


def sets_needed(melds) -> int:
    return 4 - len(list(melds or ()))


# ── 基础判定 ────────────────────────────────────────────────────────────────
def _can_form_sets(counts: list[int]) -> bool:
    """剩下的牌能不能刚好拆成若干面子（刻子 / 顺子）。"""
    i = 0
    while i < 34 and counts[i] == 0:
        i += 1
    if i == 34:
        return True
    if counts[i] >= 3:                                  # 刻子
        counts[i] -= 3
        ok = _can_form_sets(counts)
        counts[i] += 3
        if ok:
            return True
    if i < 27 and i % 9 <= 6 and counts[i + 1] and counts[i + 2]:   # 顺子
        counts[i] -= 1
        counts[i + 1] -= 1
        counts[i + 2] -= 1
        ok = _can_form_sets(counts)
        counts[i] += 1
        counts[i + 1] += 1
        counts[i + 2] += 1
        if ok:
            return True
    return False


def is_chiitoitsu(counts: list[int]) -> bool:
    """七对子：7 个不同的对子（四张一样的算两对，不算）。"""
    return sum(counts) == 14 and all(c in (0, 2) for c in counts)


def is_kokushi(counts: list[int]) -> bool:
    """国士无双：13 种幺九牌各一张 + 其中一种再来一张。"""
    pairs = 0
    for i in range(34):
        if i in ORPHAN_KINDS:
            if counts[i] == 0 or counts[i] > 2:
                return False
            if counts[i] == 2:
                pairs += 1
        elif counts[i] > 0:
            return False
    return pairs == 1


def is_winning(counts: list[int], melds=()) -> bool:
    """是不是和牌型（暗牌 + 副露）。"""
    melds = list(melds or ())
    if sum(counts) + 3 * len(melds) != 14:
        return False
    if not melds:                                       # 七对子 / 国士必须是门清
        if is_kokushi(counts) or is_chiitoitsu(counts):
            return True
    c = list(counts)
    for p in range(34):                                 # 依次假设雀头
        if c[p] >= 2:
            c[p] -= 2
            ok = _can_form_sets(c)
            c[p] += 2
            if ok:
                return True
    return False


def winning_indices(counts: list[int], melds=()) -> list[int]:
    """听哪些牌（返回 0..33 的索引表）。"""
    out = []
    c = list(counts)
    for i in range(34):
        if c[i] >= 4:                                   # 4 张都在自己手里，不可能再来
            continue
        c[i] += 1
        if is_winning(c, melds):
            out.append(i)
        c[i] -= 1
    return out


def winning_tiles(counts: list[int], melds=()) -> list[str]:
    return [TILE_KINDS[i] for i in winning_indices(counts, melds)]


def is_tenpai(counts: list[int], melds=()) -> bool:
    """听牌 = 摸进任意一张能和（这里就是「存在听牌张」）。"""
    return bool(winning_indices(counts, melds))


def losing_tiles(counts: list[int], melds=()) -> list[str]:
    """打出去之后仍然听牌的那几张（立直宣言牌的选择用）。"""
    out = []
    for i in range(34):
        if counts[i] == 0:
            continue
        counts[i] -= 1
        if is_tenpai(counts, melds):
            out.append(TILE_KINDS[i])
        counts[i] += 1
    return out


# ── 牌型拆解（役种、符数要用） ──────────────────────────────────────────────
def _enum_sets(counts: list[int], i: int, acc: list, out: list) -> None:
    while i < 34 and counts[i] == 0:
        i += 1
    if i == 34:
        out.append(tuple(sorted(acc)))
        return
    if counts[i] >= 3:
        counts[i] -= 3
        acc.append(("triplet", i))
        _enum_sets(counts, i, acc, out)
        acc.pop()
        counts[i] += 3
    if i < 27 and i % 9 <= 6 and counts[i + 1] and counts[i + 2]:
        counts[i] -= 1
        counts[i + 1] -= 1
        counts[i + 2] -= 1
        acc.append(("run", i))
        _enum_sets(counts, i, acc, out)
        acc.pop()
        counts[i] += 1
        counts[i + 1] += 1
        counts[i + 2] += 1


def decompositions(counts: list[int], melds=()) -> list[tuple[tuple, int]]:
    """
    列出所有拆法：[ (面子元组, 雀头索引), … ]
    役种判定要「每种拆法都试一遍，取番数最高的」。
    """
    melds = list(melds or ())
    if sum(counts) + 3 * len(melds) != 14:
        return []
    if not melds and (is_kokushi(counts) or is_chiitoitsu(counts)):
        return [((), -1)]                                # 特殊牌型单独处理
    c = list(counts)
    out = []
    for p in range(34):
        if c[p] >= 2:
            c[p] -= 2
            subs: list = []
            _enum_sets(c, 0, [], subs)
            c[p] += 2
            for s in subs:
                out.append((s, p))
    return out or [((), -1)]


def all_sets(sets: tuple, melds) -> list[tuple]:
    """暗牌拆出来的面子 + 副露，凑成完整的一手（4 面子）。"""
    return list(sets) + [meld_to_set(m) for m in (melds or ())]


def is_closed(melds) -> bool:
    """门清（暗杠不算破门清）。"""
    return all(m.get("kind") == "ankan" for m in (melds or ()))
