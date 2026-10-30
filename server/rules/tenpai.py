"""
听牌 / 有役听牌 / 振听判定（规则库里唯一的一份，客户端不再自己算）

术语
    听牌 tenpai       —— 差一张就能和牌
    有役听牌          —— 至少有一张能和出来的牌是「有役」的
                         （无役的那几张只能靠自摸/立直之类的役补上，荣和不能和）
    振听 furiten      —— 自己的牌河里有自己的待牌（永久）
                         或见逃过（同巡；立直后见逃则永久）

注意：荣和与自摸要分开算 —— 门清自摸和、岭上开花只存在于自摸，
所以一手牌完全可能「自摸有役、荣和无役」，这就是常说的无役听牌。
"""
from __future__ import annotations

from rules import agari, yaku
from tiles import counts_of, index_of, sort_tiles


# ────────────────────────── 听牌 ──────────────────────────

def waits(counts: list[int], melds=()) -> list[str]:
    """听哪些牌（能和的牌）。"""
    return sort_tiles(agari.winning_tiles(counts, melds))


def is_tenpai(counts: list[int], melds=()) -> bool:
    return agari.is_tenpai(counts, melds)


def _ctx(hand: list[str], melds, win_tile: str, tsumo: bool, base: dict | None = None) -> dict:
    """拼出 yaku.judge 需要的上下文；base 里带局面信息（亲家/自风/立直/宝牌…）。"""
    tiles = list(hand) + [win_tile]
    ctx = {
        "counts": counts_of(tiles),
        "tiles": tiles,
        "melds": list(melds or []),
        "win_index": index_of(win_tile),
        "is_dealer": False,
        "tsumo": tsumo,
        "seat_wind": "nan",
        "round_wind": "dong",
        "riichi": False,
        "ippatsu": False,
        "double_riichi": False,
        "last_tile": False,
        "rinshan": False,
        "chankan": False,
        "tenhou": None,
        "dora_indicators": [],
        "ura_indicators": [],
        "rules": {},
    }
    if base:
        for k, v in base.items():
            if v is not None:
                ctx[k] = v
    return ctx


def win_report(hand: list[str], melds, win_tile: str, tsumo: bool,
               base: dict | None = None) -> dict | None:
    """这张牌和下来是什么样；无役返回 None。"""
    if not win_tile:
        return None
    return yaku.judge(_ctx(hand, melds, win_tile, tsumo, base))


def win_summary(hand: list[str], melds, win_tile: str, tsumo: bool,
                base: dict | None = None) -> dict | None:
    """给客户端看的一小份结算摘要。"""
    r = win_report(hand, melds, win_tile, tsumo, base)
    if not r or not r.get("yaku"):        # 无役（judge 会返回一个空役种的结果）
        return None
    return {
        "tile": win_tile,
        "tsumo": tsumo,
        "yaku": [y["name"] for y in r["yaku"]],
        "han": r["han"],
        "fu": r["fu"],
        "yakuman": r.get("yakuman", 0),
        "pays": r.get("pays", {}),
        "fu_items": r.get("fu_items", []),
    }


def tenpai_report(hand: list[str], melds=(), base: dict | None = None) -> dict:
    """完整听牌报告：听什么、哪几张荣和/自摸有役、最高那手多少番多少点。

    hand 传 13 张（已经打出去之前的手牌，不含刚摸那张）。
    """
    counts = counts_of(hand)
    w = waits(counts, melds)
    detail: dict[str, dict] = {}
    yaku_ron: list[str] = []
    yaku_tsumo: list[str] = []
    best: dict | None = None
    for t in w:
        ron = win_summary(hand, melds, t, False, base)
        tsumo = win_summary(hand, melds, t, True, base)
        detail[t] = {"ron": ron, "tsumo": tsumo}
        if ron:
            yaku_ron.append(t)
        if tsumo:
            yaku_tsumo.append(t)
        for one in (ron, tsumo):
            if not one:
                continue
            # 用番/符粗排一下「最高的那手」（役满优先）
            rank = (one["yakuman"], one["han"], one["fu"])
            if best is None or rank > (best["yakuman"], best["han"], best["fu"]):
                best = one
    # 渣和（Card13 S2）：无役也能和（固定 1 番 30 符）→ 每张待牌都算「有役」。
    # 以前这条要在每个技能里自己补一遍（比如 Card27 伏兵的候选筛选），现在统一在这。
    if bool((base or {}).get("dawa")) and w:
        for t in w:
            if t not in yaku_ron:
                yaku_ron.append(t)
            if t not in yaku_tsumo:
                yaku_tsumo.append(t)
        if best is None:
            best = {"tile": w[0], "tsumo": False,
                    "yaku": ["渣和（无役和牌）"], "han": 1, "fu": 30,
                    "yakuman": 0, "pays": {}, "fu_items": []}
    return {
        "tenpai": bool(w),
        "waits": w,
        "yaku_ron": yaku_ron,                       # 荣和就有役的牌（有役听牌）
        "noyaku_ron": [t for t in w if t not in yaku_ron],
        "yaku_tsumo": yaku_tsumo,
        "noyaku_tsumo": [t for t in w if t not in yaku_tsumo],
        "has_yaku_ron": bool(yaku_ron),             # 有役听牌（能荣和）
        "has_yaku_tsumo": bool(yaku_tsumo),
        "noyaku_ron": bool(w) and not yaku_ron,     # 无役听牌：能听，但荣和没役
        "noyaku_all": bool(w) and not yaku_ron and not yaku_tsumo,   # 荣和、自摸都没役
        "best": best,
        "detail": detail,
    }


def is_tenpai_with_yaku(hand: list[str], melds=(), base: dict | None = None,
                        tsumo_ok: bool = False) -> bool:
    """有役听牌：至少一张待牌荣和有役（tsumo_ok=True 时自摸有役也算）。"""
    r = tenpai_report(hand, melds, base)
    return bool(r["yaku_ron"]) or (tsumo_ok and bool(r["yaku_tsumo"]))


# ────────────────────────── 振听 ──────────────────────────

def furiten_info(counts: list[int], melds, own_discards: list[str],
                 temp: bool = False, riichi: bool = False) -> dict:
    """振听状态。

    temp    —— 同巡振听（这一巡见逃过，自己下次摸牌就解除）
    riichi  —— 立直后见逃（永久）
    """
    w = waits(counts, melds)
    hit = sorted(set(w) & set(own_discards))
    permanent = bool(hit)                 # 自己的牌河里有待牌 → 永久振听
    return {
        "furiten": bool(permanent or temp or riichi),
        "permanent": permanent,
        "temporary": bool(temp),
        "riichi": bool(riichi),
        "hit": hit,
        "waits": w,
        "reason": ("自己的牌河里已经有待牌 " + "、".join(hit)) if permanent else
                  ("立直后见逃（永久振听）" if riichi else
                   ("这一巡见逃过（同巡振听）" if temp else "")),
    }


def ron_availability(hand13: list[str], win_tile: str, melds, own_discards: list[str],
                     temp: bool = False, riichi: bool = False,
                     base: dict | None = None) -> dict:
    """能不能荣和这张，以及为什么不能。

    返回 {"ok": bool, "reason": str, "win": 摘要 | None}
    """
    if not win_tile:
        return {"ok": False, "reason": "没有牌", "win": None}
    counts = list(counts_of(hand13))
    counts[index_of(win_tile)] += 1
    if not agari.is_winning(counts, melds):
        return {"ok": False, "reason": "这张和不了（牌型不成）", "win": None}
    f = furiten_info(counts_of(hand13), melds, own_discards, temp, riichi)
    if f["furiten"]:
        return {"ok": False, "reason": "振听：" + (f["reason"] or "见逃"), "win": None, "furiten": f}
    one = win_summary(hand13, melds, win_tile, False, base)
    if not one:
        return {"ok": False, "reason": "无役（荣和不能和，只能自摸）", "win": None}
    return {"ok": True, "reason": "", "win": one}


def _one_hot(tile: str) -> list[int]:
    c = [0] * 34
    c[index_of(tile)] += 1
    return c
