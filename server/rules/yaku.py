# -*- coding: utf-8 -*-
"""
役种判定
=====================================================================
入口：judge(ctx) → 番数、符数、役种清单、点数

ctx 需要的字段：
    counts          暗牌 34 格张数（已经含和牌那张）
    melds           副露列表
    win_index       和牌那张的 0..33
    is_dealer       是不是亲家
    tsumo           自摸 True / 荣和 False
    riichi / double_riichi / ippatsu
    seat_wind / round_wind     "dong"/"nan"/"xi"/"bei"
    last_tile       海底摸月 / 河底捞鱼
    rinshan         岭上开花（杠后摸的岭上牌和的）
    chankan         抢杠
    tenhou          天和 / 地和（第一巡自摸）
    dora_indicators / ura_indicators   宝牌指示牌列表
    rules           {"kuitan": True, "kiriage_mangan": False, "double_yakuman": True}

没实现/需要以后补的：流局听牌罚符、形式听牌、四杠散了、三家和了、切上满贯默认关。
"""

from __future__ import annotations

from tiles import (HONORS, HONOR_CN, TILE_KINDS, dora_from_indicator, index_of, is_honor,
                   kind_of, tile_number, tile_suit)
from rules import patterns as _patterns
from rules import score as _score
from rules.agari import (all_sets, decompositions, is_chiitoitsu, is_closed, is_kokushi,
                         meld_to_set)

HONOR_BASE = 27
DRAGONS = ("bai", "fa", "zhong")


# ── 小工具 ──────────────────────────────────────────────────────────────────
def _indices(s: tuple) -> list[int]:
    return [s[1], s[1] + 1, s[1] + 2] if s[0] == "run" else [s[1]]


def _is_honor_i(i: int) -> bool:
    return i >= HONOR_BASE


def _is_terminal_i(i: int) -> bool:
    return i < 27 and i % 9 in (0, 8)


def _is_orphan_i(i: int) -> bool:
    return _is_honor_i(i) or _is_terminal_i(i)


def _set_has_orphan(s: tuple) -> bool:
    return any(_is_orphan_i(i) for i in _indices(s))


def _set_is_honor(s: tuple) -> bool:
    return all(_is_honor_i(i) for i in _indices(s))


def _set_is_terminal(s: tuple) -> bool:
    return all(_is_terminal_i(i) for i in _indices(s))


def _hole(i: int) -> str:
    """0..33 → 花色（'m'/'p'/'s'/''=字）。"""
    return "" if i >= 27 else "mps"[i // 9]


def _num(i: int) -> int:
    return 0 if i >= 27 else i % 9 + 1


# ── 宝牌 ────────────────────────────────────────────────────────────────────
def count_dora(all_tiles: list[str], indicators: list[str]) -> int:
    want = [dora_from_indicator(x) for x in indicators]
    return sum(1 for t in all_tiles if kind_of(t) in want)


def count_aka(all_tiles: list[str]) -> int:
    return sum(1 for t in all_tiles if t in ("0m", "0p", "0s"))


# ── 拆解里的一些事实 ────────────────────────────────────────────────────────
def _concealed_flags(hand_sets, melds, win_index: int, tsumo: bool) -> list[bool]:
    flags = [True] * len(hand_sets)
    for m in melds:
        flags.append(m.get("kind") == "ankan")
    if not tsumo:
        # 荣和补上的那个刻子算明刻；但如果同一张牌还能组成顺子，就认为顺子是补上的
        in_run = any(s[0] == "run" and s[1] <= win_index <= s[1] + 2 for s in hand_sets)
        if not in_run:
            for k, s in enumerate(hand_sets):
                if s[0] in ("triplet", "kan") and s[1] == win_index:
                    flags[k] = False
                    break
    return flags


def _wait_type(hand_sets, pair: int, win_index: int, counts13: list[int]) -> str:
    if pair == win_index and counts13[win_index] == 1:
        return "tanki"
    for s in hand_sets:
        if s[0] == "run" and s[1] <= win_index <= s[1] + 2:
            if win_index == s[1] + 1:
                return "kanchan"
            if (s[1] % 9 == 0 and win_index == s[1] + 2) or (s[1] % 9 == 6 and win_index == s[1]):
                return "penchan"
            return "ryanmen"
        if s[0] in ("triplet", "kan") and s[1] == win_index:
            return "shanpon"
    return "none"


# ── 主流程 ──────────────────────────────────────────────────────────────────
def judge(ctx: dict) -> dict:
    counts = list(ctx["counts"])
    melds = list(ctx.get("melds") or [])
    win_index = ctx["win_index"]
    tsumo = bool(ctx.get("tsumo"))
    rules = ctx.get("rules") or {}
    closed_hand = is_closed(melds)
    all_tiles = []
    for i, n in enumerate(counts):
        all_tiles += [TILE_KINDS[i]] * n
    for m in melds:
        all_tiles += list(m.get("tiles") or [])

    # 宝牌的集合：杠翻出来的表宝牌无效 → 只算开局那 1 张指示牌
    _di = list(ctx.get("dora_indicators") or [])
    if ctx.get("dora_void_kan"):
        _di = _di[:1]
    dora_n = count_dora(all_tiles, _di)
    # 赤宝牌必须看「真实的牌 id」——34 格张数表里 0s 和 5s 是同一格，分不出来
    real_tiles = list(ctx.get("tiles") or ()) or all_tiles
    aka_n = count_aka(real_tiles)
    ura_n = count_dora(all_tiles, list(ctx.get("ura_indicators") or [])) if ctx.get("riichi") else 0

    # ── 役满：先看 ──
    ym = _yakuman(ctx, counts, melds, all_tiles, win_index, closed_hand, tsumo, rules)
    if ym:
        return {"yaku": ym, "han": 0, "fu": 0, "yakuman": len(ym),
                "pays": _score.payments(0, 0, is_dealer=bool(ctx["is_dealer"]), tsumo=tsumo,
                                        yakuman=len(ym), kiriage_mangan=bool(rules.get("kiriage_mangan")))}

    # ── 普通牌型：每种拆法都算一遍，取点数最高的 ──
    best = None
    cands = []
    if not melds and is_chiitoitsu(counts):
        cands.append(((), -1))
    else:
        cands = decompositions(counts, melds)

    for hand_sets, pair in cands:
        got = _eval_one(ctx, counts, melds, hand_sets, pair, all_tiles,
                        dora_n, aka_n, ura_n, closed_hand, tsumo, win_index, rules)
        if got is None:
            continue
        if best is None or (got["pays"]["total"], got["han"]) > (best["pays"]["total"], best["han"]):
            best = got
    if best is None:
        return {"yaku": [], "han": 0, "fu": 0, "yakuman": 0, "pays": {}, "error": "不是和牌型"}
    return best


def _eval_one(ctx, counts, melds, hand_sets, pair, all_tiles, dora_n, aka_n, ura_n,
              closed_hand, tsumo, win_index, rules) -> dict | None:
    sets = list(hand_sets) + [meld_to_set(m) for m in melds]
    yaku: list[tuple[str, int]] = []
    counts13 = list(counts)
    counts13[win_index] -= 1
    wait = "none" if pair == -1 else _wait_type(hand_sets, pair, win_index, counts13)
    # 压制：换牌直接自摸的那一手，不算边张 / 嵌张符
    if ctx.get("no_wait_fu"):
        if wait in ("kanchan", "penchan", "tanki"):
            wait = "none"                        # 魔术：换来的牌没有待ち，两符全免
    elif ctx.get("no_edge_fu") and wait in ("kanchan", "penchan"):
        wait = "none"

    # —— 门前清 / 状况系 ——
    if ctx.get("double_riichi"):
        yaku.append(("双立直", 2))
    elif ctx.get("riichi"):
        yaku.append(("立直", 1))
    if ctx.get("ippatsu"):
        yaku.append(("一发", 1))
    if tsumo and closed_hand:
        yaku.append(("门前清自摸和", 1))
    if ctx.get("rinshan") and tsumo:                     # 岭上开花是自摸役：荣和不成立
        yaku.append(("岭上开花", 1))
    if ctx.get("chankan"):
        yaku.append(("抢杠", 1))
    if ctx.get("last_tile"):
        yaku.append(("海底摸月" if tsumo else "河底捞鱼", 1))

    # —— 断幺九 ——
    if all(not _is_orphan_i(index_of(t)) for t in all_tiles):
        if closed_hand or rules.get("kuitan", True):
            yaku.append(("断幺九", 1))

    # —— 平和 ——
    if (closed_hand and wait == "ryanmen" and all(s[0] == "run" for s in sets)
            and not _pair_is_yakuhai(pair, ctx)):
        yaku.append(("平和", 1))

    # —— 役牌 ——
    for s in sets:
        if s[0] in ("triplet", "kan") and _is_honor_i(s[1]):
            name = HONORS[s[1] - HONOR_BASE]
            cn = HONOR_CN.get(name, name)
            if name in DRAGONS:
                yaku.append((f"役牌 {cn}", 1))
            else:
                if name == ctx.get("round_wind"):
                    yaku.append((f"场风 {cn}", 1))
                if name == ctx.get("seat_wind"):
                    yaku.append((f"自风 {cn}", 1))

    # —— 一杯口 / 二杯口 ——
    if closed_hand:
        runs = [s for s in sets if s[0] == "run"]
        paircnt = sum(1 for r in runs if runs.count(r) >= 2) // 2
        if paircnt >= 2:
            yaku.append(("二杯口", 3))
        elif paircnt == 1:
            yaku.append(("一杯口", 1))

    # —— 三色同顺 / 一气通贯 ——
    runs = [s for s in sets if s[0] == "run"]
    for n in range(1, 10):
        if all(any(s[1] == i * 9 + n - 1 for s in runs) for i in range(3)):
            yaku.append(("三色同顺", 2 if closed_hand else 1))
            break
    for i in (0, 9, 18):
        if all(any(s[1] == i + k for s in runs) for k in (0, 3, 6)):
            yaku.append(("一气通贯", 2 if closed_hand else 1))
            break

    # —— 三色同刻 ——
    for n in range(1, 10):
        if all(any(s[0] in ("triplet", "kan") and s[1] == i * 9 + n - 1 for s in sets)
               for i in range(3)):
            yaku.append(("三色同刻", 2))
            break

    # —— 对对和 / 三暗刻 / 三杠子 ——
    flags = _concealed_flags(hand_sets, melds, win_index, tsumo)
    trips = [s for s in sets if s[0] in ("triplet", "kan")]
    concealed_trips = sum(1 for s, c in zip(sets, flags) if s[0] in ("triplet", "kan") and c)
    kans = sum(1 for s in sets if s[0] == "kan")
    if len(trips) == 4:
        yaku.append(("对对和", 2))
    if concealed_trips >= 3:
        yaku.append(("三暗刻", 2))
    if kans >= 3:
        yaku.append(("三杠子", 2))

    # —— 小三元 ——
    dragon_trips = sum(1 for s in trips if _is_honor_i(s[1]) and HONORS[s[1] - HONOR_BASE] in DRAGONS)
    if dragon_trips == 2 and _is_honor_i(pair) and HONORS[pair - HONOR_BASE] in DRAGONS:
        yaku.append(("小三元", 2))

    # —— 混老头 ——
    if all(_is_orphan_i(i) for i in range(34) for _ in range(counts[i])) and pair != -1:
        if all(_is_orphan_i(i) for s in sets for i in _indices(s)) and _is_orphan_i(pair):
            yaku.append(("混老头", 2))

    # —— 混一色 / 清一色 ——
    suits = {_hole(i) for s in sets for i in _indices(s)} | ({_hole(pair)} if pair >= 0 else set())
    used_suits = {x for x in suits if x}
    has_honor = any(_is_honor_i(i) for s in sets for i in _indices(s)) or _is_honor_i(pair)
    if len(used_suits) == 1 and has_honor:
        yaku.append(("混一色", 3 if closed_hand else 2))
    elif len(used_suits) == 1 and not has_honor:
        yaku.append(("清一色", 6 if closed_hand else 5))

    # —— 混全带幺九 / 纯全带幺九（和混老头冲突时不算）——
    if not any(y[0] == "混老头" for y in yaku) and pair >= 0:
        if all(_set_has_orphan(s) for s in sets) and _is_orphan_i(pair):
            pure = all(_is_terminal_i(i) for s in sets for i in _indices(s)) and _is_terminal_i(pair)
            if pure:
                yaku.append(("纯全带幺九", 3 if closed_hand else 2))
            else:
                yaku.append(("混全带幺九", 2 if closed_hand else 1))

    # —— 七对子 ——
    if not melds and is_chiitoitsu(counts):
        yaku.append(("七对子", 2))

    # —— 角色卡技能的「国标」番种：五门齐 / 花龙 / 三色三步高 ——
    # 只有 ctx["pattern_bonus"] 打开时才认（普通对局里它们不是役）。
    # 番数固定：门清 +2 / 副露 +1，复合时也只算这一份（几番就是奖励番的番数）。
    pats: list[str] = []
    if ctx.get("pattern_bonus"):
        pats = _patterns.matched(sets, pair)
        if pats:
            yaku.append(("、".join(pats), 2 if closed_hand else 1))

    if not yaku:
        return None                             # 没有役，不能和牌
    han = sum(h for _, h in yaku)
    # 宝牌的集合：每开一次杠 +4 番，**算进宝牌里**（不单独成役）
    bonus = int(ctx.get("dora_bonus_han") or 0)
    dora_total = dora_n + aka_n + ura_n + bonus
    if yaku:
        han += dora_total

    fu = 0
    fu_detail: list = []
    if yaku:
        fu_args = dict(sets=sets, pair_index=max(pair, 0), concealed_flags=flags,
                       closed_hand=closed_hand, tsumo=tsumo, wait=wait,
                       is_pinfu=any(y[0] == "平和" for y in yaku),
                       is_chiitoitsu=(not melds and is_chiitoitsu(counts)),
                       round_wind=ctx.get("round_wind", "dong"),
                       seat_wind=ctx.get("seat_wind", "dong"))
        fu_detail = _score.fu_items(**fu_args)
        fu = _score.calc_fu(**fu_args)
    pays = _score.payments(han, fu, is_dealer=bool(ctx["is_dealer"]), tsumo=tsumo,
                           kiriage_mangan=bool(rules.get("kiriage_mangan"))) if yaku else {}
    out_yaku = [{"name": n, "han": h} for n, h in yaku]
    if dora_total:
        detail = {"宝牌": dora_n, "赤宝牌": aka_n, "里宝牌": ura_n}
        if bonus:
            detail["宝牌的集合"] = bonus
        out_yaku.append({"name": "宝牌", "han": dora_total, "detail": detail})
    return {"yaku": out_yaku, "han": han, "fu": fu, "yakuman": 0, "pays": pays,
            "sets": sets, "pair": pair, "wait": wait, "flags": flags, "fu_items": fu_detail,
            "patterns": pats}


def _pair_is_yakuhai(pair: int, ctx) -> bool:
    if pair < 0 or not _is_honor_i(pair):
        return False
    name = HONORS[pair - HONOR_BASE]
    return name in DRAGONS or name in (ctx.get("round_wind"), ctx.get("seat_wind"))


# ── 役满 ────────────────────────────────────────────────────────────────────
def _yakuman(ctx, counts, melds, all_tiles, win_index, closed_hand, tsumo, rules) -> list:
    out = []
    double = rules.get("double_yakuman", True)
    if not melds and is_kokushi(counts):
        waits = sum(1 for i in range(34) if counts[i] >= 2)
        out.append({"name": "国士无双十三面" if waits >= 13 else "国士无双",
                    "han": 13 if (waits >= 13 and double) else 13})
        return out
    if all(_is_honor_i(index_of(t)) for t in all_tiles):
        out.append({"name": "字一色", "han": 13})
    terminals = [t for t in all_tiles if not _is_honor_i(index_of(t))]
    if terminals and all(_is_terminal_i(index_of(t)) for t in terminals) and not any(
            _is_honor_i(index_of(t)) for t in all_tiles):
        out.append({"name": "清老头", "han": 13})
    green = {"2s", "3s", "4s", "6s", "8s", "fa"}
    if all(kind_of(t) in green for t in all_tiles):
        out.append({"name": "绿一色", "han": 13})
    # —— 九莲宝灯（门清、清一色、1112345678999 + 任意一张）——
    if not melds:
        suited = {tile_suit(t) for t in all_tiles}
        if len(suited) == 1 and "" not in suited:
            nums = sorted(tile_number(t) for t in all_tiles)
            base = [1, 1, 1, 2, 3, 4, 5, 6, 7, 8, 9, 9, 9]
            if len(nums) == 14 and all(nums.count(n) >= base.count(n) for n in range(1, 10)):
                for k in range(14):
                    if nums[:k] + nums[k + 1:] == base:
                        out.append({"name": "九莲宝灯", "han": 13})
                        break
    # 大三元 / 小四喜 / 大四喜 / 四暗刻 / 四杠子
    for hand_sets, pair in decompositions(counts, melds):
        sets = list(hand_sets) + [meld_to_set(m) for m in melds]
        flags = _concealed_flags(hand_sets, melds, win_index, tsumo)
        trips = [s for s in sets if s[0] in ("triplet", "kan")]
        dragons = [s for s in trips if _is_honor_i(s[1]) and HONORS[s[1] - HONOR_BASE] in DRAGONS]
        winds = [s for s in trips if _is_honor_i(s[1]) and HONORS[s[1] - HONOR_BASE] in HONORS[:4]]
        if len(dragons) == 3 and not any(y["name"] == "大三元" for y in out):
            out.append({"name": "大三元", "han": 13})
        if len(winds) == 4 and not any(y["name"] == "大四喜" for y in out):
            out.append({"name": "大四喜", "han": 13})
        elif len(winds) == 3 and _is_honor_i(pair) and HONORS[pair - HONOR_BASE] in HONORS[:4] \
                and not any(y["name"] == "小四喜" for y in out):
            out.append({"name": "小四喜", "han": 13})
        concealed_trips = sum(1 for s, c in zip(sets, flags) if s[0] in ("triplet", "kan") and c)
        if concealed_trips == 4 and not ctx.get("no_suuankou"):
            tanki = (pair == win_index and counts[win_index] == 1)
            name = "四暗刻单骑" if (tanki and double) else "四暗刻"
            if not any(y["name"].startswith("四暗刻") for y in out):
                out.append({"name": name, "han": 13})
        if sum(1 for s in sets if s[0] == "kan") == 4 and not any(y["name"] == "四杠子" for y in out):
            out.append({"name": "四杠子", "han": 13})
    if ctx.get("tenhou"):
        out.append({"name": "天和" if ctx["tenhou"] == "tenhou" else "地和", "han": 13})
    return out
