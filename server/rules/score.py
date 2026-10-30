# -*- coding: utf-8 -*-
"""
符数计算 + 翻数→点数
=====================================================================
符数：底 20 符 + 门清荣和 10 + 自摸 2 + 雀头（役牌 2／连风 4）
       + 面子（明刻 2·4 / 暗刻 4·8 / 明杠 8·16 / 暗杠 16·32）
       + 听牌形（嵌张/边张/单骑 2）→ 进位到 10
       特例：七对子 25 符；平和自摸 20 符；平和荣和 30 符；食い平和 30 符。

点数：基本点 = 符 × 2^(2+翻)，再按亲家/子家、荣和/自摸分配，各自进位到百位。
       满贯以上按段位表。
"""

from __future__ import annotations

import math

HONOR_BASE = 27                     # 0..33 里 27 起是字牌


def _is_honor_index(i: int) -> bool:
    return i >= HONOR_BASE


def _is_terminal(i: int) -> bool:
    return i < 27 and i % 9 in (0, 8)


def _is_orphan(i: int) -> bool:
    return _is_honor_index(i) or _is_terminal(i)


def _set_indices(s: tuple) -> list[int]:
    kind, i = s[0], s[1]
    if kind == "run":
        return [i, i + 1, i + 2]
    return [i] * (4 if kind == "kan" else 3)


def _round100(x: float) -> int:
    return int(math.ceil(x / 100.0) * 100)


def fu_items(*, sets, pair_index: int, concealed_flags: list[bool], closed_hand: bool,
             tsumo: bool, wait: str, is_pinfu: bool, is_chiitoitsu: bool,
             round_wind: str, seat_wind: str) -> list[tuple[str, int]]:
    """符数明细：[(名字, 符), …]（测试界面要显示每一项）"""
    if is_chiitoitsu:
        return [("七对子（固定）", 25)]
    if is_pinfu and tsumo:
        return [("平和自摸（固定）", 20)]
    items: list[tuple[str, int]] = [("底符", 20)]
    if closed_hand and not tsumo:
        items.append(("门清荣和", 10))
    if tsumo:
        items.append(("自摸", 2))

    from tiles import HONORS, HONOR_CN, TILE_KINDS
    if _is_honor_index(pair_index):
        h = HONORS[pair_index - HONOR_BASE]
        cn = HONOR_CN.get(h, h)
        if h in ("bai", "fa", "zhong"):
            items.append((f"雀头（役牌 {cn}）", 2))
        elif h == round_wind and h == seat_wind:
            items.append((f"雀头（连风 {cn}）", 4))
        elif h in (round_wind, seat_wind):
            items.append((f"雀头（风 {cn}）", 2))

    for s, concealed in zip(sets, concealed_flags):
        if s[0] == "run":
            continue
        i, kind = s[1], s[0]
        base = 2 if (not _is_orphan(i) and not _is_honor_index(i)) else 4
        label = f"{'暗' if concealed else '明'}{'杠' if kind == 'kan' else '刻'}"
        if kind == "kan":
            items.append((f"{label} {TILE_KINDS[i]}", base * (8 if concealed else 4)))
        else:
            items.append((f"{label} {TILE_KINDS[i]}", base * (2 if concealed else 1)))

    if wait in ("kanchan", "penchan", "tanki"):
        name = {"kanchan": "嵌张", "penchan": "边张", "tanki": "单骑"}[wait]
        items.append((f"听牌形（{name}）", 2))

    total = sum(v for _, v in items)
    if is_pinfu and not tsumo:
        return items                                   # 平和荣和 = 20 + 10 = 30，正好
    if not closed_hand and total < 30:
        items.append(("食い平和（副露最低 30）", 30 - total))
    return items


def calc_fu(**kw) -> int:
    """算符。wait ∈ {'ryanmen','kanchan','penchan','tanki','shanpon','none'}"""
    items = fu_items(**kw)
    if items and items[0][0].startswith("七对子"):
        return 25
    total = sum(v for _, v in items)
    return int(math.ceil(total / 10.0) * 10)


# ── 翻数 → 点数 ─────────────────────────────────────────────────────────────
LIMITS = [
    (13, 8000, "役满"),
    (11, 6000, "三倍满"),
    (8, 4000, "倍满"),
    (6, 3000, "跳满"),
    (5, 2000, "满贯"),
]


def base_points(han: int, fu: int, *, yakuman: int = 0, kiriage_mangan: bool = False) -> tuple[int, str]:
    """返回 (基本点, 段位名)。"""
    if yakuman > 0:
        return 8000 * yakuman, "役满" + (f"×{yakuman}" if yakuman > 1 else "")
    for need_han, basic, name in LIMITS:
        if han >= need_han:
            return basic, name
    if han == 4 and fu >= 40:
        return 2000, "满贯"
    if han == 3 and fu >= 70:
        return 2000, "满贯"
    if kiriage_mangan and ((han == 4 and fu == 30) or (han == 3 and fu == 60)):
        return 2000, "满贯（切上）"
    return fu * (2 ** (2 + han)), ""


# 档位 → 该档位的**最小番**（28S2【蜕变】升档后按最小番计入）
TIER_MIN_HAN = {"满贯": 5, "跳满": 6, "倍满": 8, "三倍满": 11}


def tier(han: int, fu: int, *, yakuman: int = 0,
         kiriage_mangan: bool = False) -> tuple[str, int]:
    """(档位名, 基本点)。没有段位时名字是 ""。

    「切上」后缀会去掉，役满统一叫「役满」（倍数看 basic）。
    """
    basic, name = base_points(han, fu, yakuman=yakuman,
                              kiriage_mangan=kiriage_mangan)
    if name.endswith("（切上）"):
        name = name[:-4]
    if name.startswith("役满"):
        name = "役满"
    return name, basic


def next_tier(han: int, fu: int, *, yakuman: int = 0,
              kiriage_mangan: bool = False) -> tuple[int, int, str] | None:
    """28S2【蜕变】：返回 (新手番, 新基本点, 新档名)；不在升级范围 → None。

    用户口径（2026-10-27）：
      · 打点必须**严格大于** 30 符 2 番（基本点 480），且不满贯时才升级
      · <满贯 → 满贯 / 满贯 → 跳满 / 跳满 → 倍满 / 倍满 → 三倍满 / 三倍满 → 役满
      · 役满不升；升上去按**该档位的最小番**计入（满贯 5 / 跳满 6 / 倍满 8 / 三倍满 11）
    """
    if yakuman > 0:
        return None
    name, basic = tier(han, fu, kiriage_mangan=kiriage_mangan)
    if basic <= base_points(2, 30, kiriage_mangan=kiriage_mangan)[0]:
        return None                        # 不超过 30 符 2 番 → 不升级
    if name == "":
        return (5, 2000, "满贯")
    nxt = {"满贯": ("跳满", 6, 3000), "跳满": ("倍满", 8, 4000),
           "倍满": ("三倍满", 11, 6000), "三倍满": ("役满", 13, 8000)}
    if name in nxt:
        nm, h, b = nxt[name]
        return (h, b, nm)
    return None


def payments(han: int, fu: int, *, is_dealer: bool, tsumo: bool,
             yakuman: int = 0, kiriage_mangan: bool = False) -> dict:
    """
    返回这一手该收多少：
        ron  → {"total": 点数, "pay": {放铳的人:-total}}, 由调用方填具体是谁
        tsumo → {"total": 总数, "from_dealer": x, "from_other": y}
    """
    basic, limit_name = base_points(han, fu, yakuman=yakuman, kiriage_mangan=kiriage_mangan)
    out = {"han": han, "fu": fu, "basic": basic, "limit": limit_name, "yakuman": yakuman}
    if tsumo:
        if is_dealer:
            each = _round100(basic * 2)
            out.update({"total": each * 3, "each": each, "from_dealer": each, "from_other": each})
        else:
            a = _round100(basic)            # 子家付
            b = _round100(basic * 2)        # 亲家付
            out.update({"total": a * 2 + b, "from_dealer": b, "from_other": a})
    else:
        pay = _round100(basic * (6 if is_dealer else 4))
        out.update({"total": pay, "each": pay})
    return out
