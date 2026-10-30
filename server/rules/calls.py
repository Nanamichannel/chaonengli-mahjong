# -*- coding: utf-8 -*-
"""
鸣牌（吃 / 碰 / 杠）合法性、振听、食い替え
=====================================================================
这里的 hand 都是「具体的牌 id 列表」（不是张数表），因为赤宝牌要和普通 5 分开算：
    手里有 0s(赤5) 和 5s 时，吃/碰能用的组合是分开的，和客户端显示的分组一致。
"""

from __future__ import annotations

from tiles import (HONORS, ORPHAN_KINDS, index_of, is_honor, kind_of, tile_number, tile_suit)
from rules.agari import is_tenpai, winning_indices


# ── 吃 ──────────────────────────────────────────────────────────────────────
def chi_options(hand: list[str], tile: str) -> list[list[str]]:
    """
    上家打出 tile，手里能用来吃的两张（每组两张，按牌 id 去重）。
    0s 和 5s 是不同 id → 会分成两组（和客户端一致）。
    """
    suit = tile_suit(tile)
    if suit == "":
        return []
    n = tile_number(tile)
    out: list[list[str]] = []
    for a, b in ((n - 2, n - 1), (n - 1, n + 1), (n + 1, n + 2)):
        if a < 1 or b > 9:
            continue
        ia = [i for i, x in enumerate(hand) if tile_suit(x) == suit and tile_number(x) == a]
        ib = [i for i, x in enumerate(hand) if tile_suit(x) == suit and tile_number(x) == b]
        for x in ia:
            for y in ib:
                if x == y:
                    continue
                pair = sorted([hand[x], hand[y]])
                if pair not in out:
                    out.append(pair)
    return out


# ── 碰 ──────────────────────────────────────────────────────────────────────
def pon_options(hand: list[str], tile: str) -> list[list[str]]:
    """
    能碰的两种取法。[0] 优先是「两张完全一样的」（刻子三张相同、摆放好看），
    只有 0s/5s 这种凑不出两张一样的才会给出混搭。
    """
    k = kind_of(tile)
    idxs = [i for i, x in enumerate(hand) if kind_of(x) == k]
    if len(idxs) < 2:
        return []
    same: dict[str, list[int]] = {}
    for i in idxs:
        same.setdefault(hand[i], []).append(i)
    out: list[list[str]] = []
    for tid, ii in same.items():
        if len(ii) >= 2:
            out.append([hand[ii[0]], hand[ii[1]]])
    if not out:                                    # 没有两张一样的（比如 0s + 5s）
        out.append([hand[idxs[0]], hand[idxs[1]]])
    else:                                          # 也允许「赤 + 普通」的取法
        mix = [hand[i] for i in idxs]
        for a in range(len(mix)):
            for b in range(a + 1, len(mix)):
                pair = sorted([mix[a], mix[b]])
                if pair not in out and pair[0] != pair[1]:
                    out.append(pair)
    return out


def can_pon(hand: list[str], tile: str) -> bool:
    return len(pon_options(hand, tile)) > 0


# ── 杠 ──────────────────────────────────────────────────────────────────────
def minkan_options(hand: list[str], tile: str) -> list[list[str]]:
    """明杠：手里有 3 张和打出的一样。"""
    k = kind_of(tile)
    idxs = [i for i, x in enumerate(hand) if kind_of(x) == k]
    if len(idxs) < 3:
        return []
    return [[hand[i] for i in idxs[:3]]]


def ankan_options(hand: list[str]) -> list[str]:
    """暗杠：手里有 4 张一样的（返回牌种）。"""
    cnt: dict[str, int] = {}
    for t in hand:
        cnt[kind_of(t)] = cnt.get(kind_of(t), 0) + 1
    return [k for k, c in cnt.items() if c == 4]


def kakan_options(hand: list[str], melds) -> list[str]:
    """加杠：碰过的那张，自己又摸到第 4 张。"""
    out = []
    for m in melds or []:
        if m.get("kind") != "pon":
            continue
        k = kind_of((m.get("tiles") or [""])[0])
        if any(kind_of(t) == k for t in hand):
            out.append(k)
    return out


# ── 振听 ────────────────────────────────────────────────────────────────────
def is_permanent_furiten(hand_counts: list[int], melds, own_discards: list[str]) -> bool:
    """
    永久振听：自己牌河里出现过自己的听牌张 → 这一局不能荣和。
    （hand_counts 是当前 13 张的暗牌。）
    """
    waits = set(winning_indices(hand_counts, melds))
    return any(index_of(t) in waits for t in own_discards)


def can_ron(hand_counts: list[int], melds, own_discards: list[str],
            tile: str, temp_furiten: bool = False) -> bool:
    """能不能荣和这张。temp_furiten = 同巡振听（错过了上一次荣和）。"""
    from rules.agari import is_winning
    c = list(hand_counts)
    c[index_of(tile)] += 1
    if not is_winning(c, melds):
        return False
    if temp_furiten:
        return False
    return not is_permanent_furiten(hand_counts, melds, own_discards)


# ── 食い替え（鸣牌之后不能打什么） ─────────────────────────────────────────
def is_meld_of_three(ids: list[str]) -> bool:
    """三张是不是一个面子（刻子 / 顺子）——和客户端 main.gd 一条规则。"""
    if len(ids) != 3:
        return False
    if kind_of(ids[0]) == kind_of(ids[1]) == kind_of(ids[2]):
        return True
    suit = tile_suit(ids[0])
    if suit == "":
        return False
    nums = []
    for t in ids:
        if tile_suit(t) != suit:
            return False
        nums.append(tile_number(t))
    nums.sort()
    return nums[1] == nums[0] + 1 and nums[2] == nums[1] + 1


def can_discard_after_call(tile: str, kind: str, called_tile: str,
                           used_tiles: list[str]) -> bool:
    """
    吃完不能打出「和吃用的两张凑成面子」的牌；碰完不能打和碰来那张一样的牌。
    （和客户端现在的限制完全一致。）
    """
    if kind == "chi" and len(used_tiles) >= 2:
        return not is_meld_of_three([used_tiles[0], used_tiles[1], tile])
    if kind in ("pon", "minkan", "kakan"):
        return tile != called_tile
    return True


# ── 特殊流局 ────────────────────────────────────────────────────────────────
def can_kyuushu_kyuuhai(hand_counts: list[int], melds) -> bool:
    """九种九牌：起手第一巡，幺九牌种类 ≥ 9 种（且没鸣过牌）。"""
    if melds:
        return False
    kinds = sum(1 for i in ORPHAN_KINDS if hand_counts[i] > 0)
    return kinds >= 9


def is_daburu_riichi(first_turn: bool) -> bool:
    """双立直：第一巡就立直。"""
    return bool(first_turn)
