# -*- coding: utf-8 -*-
"""人机打牌：移植 kobalab/majiang-ai（電脳麻将）select_dapai 的思路（简化版）。

原版的关键四步，这里一一对应：
  1) 先算「安全牌」——有人立直时先找 100% 不会点的牌；
  2) 逐个候选打牌，**打完之后向听数不能变差**（原版 `xiangting(shoupai) > n_xiangting → 跳过`）；
  3) 用「进张数 × 打点期待」给每个候选打分（原版 `eval_shoupai`）；
  4) 有人立直时按 `押し引き` 折扣危险度（原版 `suan_weixian_all` + 那串 if）。

我们没有原版的 `Majiang.Util`（JS），所以底层用的是本项目自己的
`agari` / `tenpai` / `yaku`，上层评估函数照原版结构重写。

★ 契约：`choose_discard()` **要么返回手里真实存在的一张牌，要么返回 ""**。
  调用方（api_cli._bot_discard）必须再和服务端 legal 核对一次 —— 人机的牌可能
  被别的技能换掉/暗置，这里的缓存一律不许影响「能不能打」。
"""
from __future__ import annotations

import time

from tiles import TILE_KINDS, counts_of, kind_of, is_honor   # noqa: E402
from rules import agari                                      # noqa: E402

YAOCHU = [0, 8, 9, 17, 18, 26, 27, 28, 29, 30, 31, 32, 33]

_SH_CACHE: dict = {}


# ── 向听数 ────────────────────────────────────────────────────────────
def _shanten_std(c: list[int]) -> int:
    best = 8

    def dfs(i: int, m: int, t: int, p: int) -> None:
        nonlocal best
        while i < 34 and c[i] == 0:
            i += 1
        if i == 34:
            tt = min(t, 4 - m - p)
            sh = 8 - 2 * m - tt - p
            if sh < best:
                best = sh
            return
        if c[i] >= 3:                       # 刻子
            c[i] -= 3
            dfs(i, m + 1, t, p)
            c[i] += 3
        if i < 27 and i % 9 <= 6 and c[i + 1] and c[i + 2]:      # 顺子
            c[i] -= 1
            c[i + 1] -= 1
            c[i + 2] -= 1
            dfs(i, m + 1, t, p)
            c[i] += 1
            c[i + 1] += 1
            c[i + 2] += 1
        if c[i] >= 2 and p == 0:            # 雀头
            c[i] -= 2
            dfs(i, m, t, 1)
            c[i] += 2
        if c[i] >= 2 and t < 4:             # 对子当搭子
            c[i] -= 2
            dfs(i, m, t + 1, p)
            c[i] += 2
        if i < 27 and i % 9 <= 7 and c[i + 1] and t < 4:          # 两面
            c[i] -= 1
            c[i + 1] -= 1
            dfs(i, m, t + 1, p)
            c[i] += 1
            c[i + 1] += 1
        if i < 27 and i % 9 <= 6 and c[i + 2] and t < 4:          # 嵌张
            c[i] -= 1
            c[i + 2] -= 1
            dfs(i, m, t + 1, p)
            c[i] += 1
            c[i + 2] += 1
        c[i] -= 1                           # 孤张
        dfs(i, m, t, p)
        c[i] += 1

    dfs(0, 0, 0, 0)
    return best


def shanten(counts: list[int], melds_n: int = 0) -> int:
    """向听数（-1 = 已经和了，0 = 听牌）。"""
    key = (tuple(counts), int(melds_n))
    hit = _SH_CACHE.get(key)
    if hit is not None:
        return hit
    sh = _shanten_std(list(counts))
    if melds_n:
        # 有副露：把副露当成已完成的面子
        sh = _shanten_std(list(counts))
    if melds_n == 0:
        pairs = sum(1 for x in counts if x >= 2)
        kinds = sum(1 for x in counts if x >= 1)
        s7 = 6 - pairs + max(0, 7 - kinds)
        if s7 < sh:
            sh = s7
        if all(counts[i] >= 1 for i in YAOCHU) and sum(counts[i] for i in YAOCHU) >= 13:
            s13 = 13 - sum(1 for i in YAOCHU if counts[i] >= 1)
            if counts[0] or counts[8] or counts[9] or counts[17] or counts[18] or counts[26] \
                    or any(counts[i] >= 2 for i in YAOCHU[6:]):
                s13 -= 1
            if s13 < sh:
                sh = s13
    if len(_SH_CACHE) > 40000:
        _SH_CACHE.clear()
    _SH_CACHE[key] = sh
    return sh


# ── 可见牌 / 剩余张数 ─────────────────────────────────────────────────
def _visible(g, seat: int) -> list[int]:
    """34 格「已经看得见」的张数：自己手牌 + 全场牌河 + 副露 + 宝牌指示牌。"""
    vis = [0] * 34

    def add(t: str) -> None:
        i = TILE_KINDS.index(kind_of(t))
        vis[i] += 1

    for t in (g.hand(seat) or []):
        add(t)
    for s in range(4):
        for t in (g.discards(s) or []):
            add(t)
        for m in (g.melds(s) or []):
            for t in (m.get("tiles") or []):
                add(t)
    try:
        for t in (g.revealed_dora("dora") or []):
            add(t)
    except Exception:
        pass
    return vis


def _ukeire(counts13: list[int], melds, vis: list[int], melds_n: int) -> int:
    """进张数：摸到哪张能让向听数下降（牌山还剩几张）。

    加 4ms 预算：34 次 shanten DFS 在 1 核 VPS 上可能几十毫秒；超时就返回已统计的部分
    （陪玩够用，不会因为算牌把整桌拖卡）。
    """
    t0 = time.perf_counter()
    base = shanten(counts13, melds_n)
    n = 0
    for i in range(34):
        if counts13[i] >= 4:
            continue
        counts13[i] += 1
        if shanten(counts13, melds_n) < base:
            n += max(0, 4 - vis[i])
        counts13[i] -= 1
        if time.perf_counter() - t0 > 0.008:
            break
    return n


# ── 危险度（原版 suan_weixian_all 的粗化版）────────────────────────────
_BASE_DANGER = {0: 2, 1: 4, 2: 5, 3: 6, 4: 8, 5: 8, 6: 6, 7: 5, 8: 4, 9: 2}


def _danger(g, seat: int, tile: str) -> float:
    """只在「别人立直」时才有意义：现物 0，字牌按可见张数，数牌按中张/筋。"""
    k = kind_of(tile)
    total = 0.0
    for s in range(4):
        if s == seat:
            continue
        try:
            if not g.is_riichi(s):
                continue
        except Exception:
            continue
        river = g.discards(s) or []
        if k in river:                       # 现物 → 绝对安全
            continue
        if is_honor(k):
            seen = sum(1 for t in river if kind_of(t) == k)
            d = 1.0 if seen == 0 else (0.4 if seen == 1 else 0.15)
        else:
            num = int(k[0])
            suit = k[1]
            d = float(_BASE_DANGER.get(num, 5))
            # 筋：这一家里有 num±3 的牌 → 折半（原版也是按筋降危险）
            for d3 in (num - 3, num + 3):
                if 1 <= d3 <= 9 and ("%d%s" % (d3, suit)) in river:
                    d *= 0.5
                    break
            if num in (1, 9):
                d = max(0.8, d)
        total = max(total, d)
    return total


# ── 打点期待（原版 eval_shoupai 的替身）───────────────────────────────
def _tenpai_value(g, seat: int, hand13: list[str], melds,
                  vis: list[int] | None = None) -> float:
    """听牌时的「打点期待」粗估。

    ★ 以前对每个待牌都调一次 `g._judge_win()`（完整判番，10ms 级），
      听牌后一巡能吃掉上百毫秒 → 云上 1 核直接卡。陪玩 AI 用「待牌剩余张数 × 平均点」就够。
    """
    try:
        ws = agari.winning_tiles(counts_of(hand13), melds)
    except Exception:
        ws = []
    if not ws:
        return 0.0
    total = 0
    for w in ws:
        k = kind_of(w)
        try:
            i = TILE_KINDS.index(k)
        except ValueError:
            continue
        left = max(0, 4 - (vis[i] if vis else 0))
        total += left
    return float(max(total, 1)) * 800.0


# ── 主入口 ────────────────────────────────────────────────────────────
def _shape_score(c: list[int]) -> int:
    """向听 >= 2 时用的廉价牌效：对子数 + 相邻搭子数（O(34)，不做 DFS）。"""
    n = 0
    for i in range(34):
        if c[i] >= 2:
            n += 1
        if i < 27 and i % 9 <= 7 and c[i] and c[i + 1]:
            n += 1
    return n


def choose_discard(g, seat: int) -> str:
    """从 14 张（含刚摸的那张）里挑一张打。返回牌种字符串；挑不出来返回 ""。"""
    seat = int(seat)
    hand = list(g.hand(seat) or [])
    if not hand:
        return ""
    melds = list(g.melds(seat) or [])
    melds_n = len(melds)
    drawn = g.drawn_tile(seat)
    vis = _visible(g, seat)

    cands: list[str] = []
    for t in hand:                           # 去重（同种只算一次；赤五优先留 0x 版本？这里取原牌）
        if t not in cands:
            cands.append(t)
    if drawn and drawn in cands:             # 原版：刚摸的那张先排在最前
        cands.remove(drawn)
        cands.insert(0, drawn)
    # ★ 预算有限：把「更可能要打的」排前面先算（摸切那张不动）——
    #   孤张字牌 → 端牌 → 中张。否则预算 break 时可能还没算到真正该打的那张。
    head = cands[:1] if (drawn and cands and cands[0] == drawn) else []
    tail = cands[len(head):]

    def _ord(t: str) -> int:
        k = kind_of(t)
        if is_honor(k):
            return 1
        if k[0] in ("1", "9"):
            return 2
        return 3
    tail.sort(key=_ord)
    cands = head + tail

    base_sh = shanten(counts_of(hand), melds_n)
    # 立直家数量 → 押し引き强度
    n_riichi = 0
    for s in range(4):
        if s == seat:
            continue
        try:
            if g.is_riichi(s):
                n_riichi += 1
        except Exception:
            pass
    if base_sh >= 2:
        safe_w = 55.0
    elif base_sh == 1:
        safe_w = 18.0
    elif base_sh == 0:
        safe_w = 4.0
    else:
        safe_w = 0.0

    # ★ 孤张字牌：直接打掉（不参与后面的进张精算）。
    #   ① 牌理上几乎总是对的（孤张字牌既不成面子也不成将）；
    #   ② 让决策结果稳定：不会因为时间预算截断在不同机器上打出不同的牌。
    for t in cands:
        if t == drawn:
            continue
        if is_honor(kind_of(t)) and hand.count(t) == 1:
            rest0 = list(hand)
            rest0.remove(t)
            if shanten(counts_of(rest0), melds_n) <= base_sh:
                return t

    best, best_v = "", -1e18
    t_start = time.perf_counter()
    for t in cands:
        if best != "" and time.perf_counter() - t_start > 0.015:
            break                          # 12ms 预算：剩下的候选不再精算
        rest = list(hand)
        rest.remove(t)
        c13 = counts_of(rest)
        sh = shanten(c13, melds_n)
        # ① 打完之后向听变差 → 原版直接跳过（除非全都变差，那也只在没别的选择时用）
        worse = sh > base_sh
        # ② 形状价值：听牌 > 一向听 > …
        v = (300.0 / (1.0 + max(sh, 0)))
        # ③ 进张数（听牌时用待牌；否则用「能使向听下降的牌张数」）
        if sh == 0:
            uke = 0
            try:
                for w in agari.winning_tiles(c13, melds):
                    uke += max(0, 4 - vis[TILE_KINDS.index(kind_of(w))])
            except Exception:
                uke = 0
            v += float(uke) * max(1.0, _tenpai_value(g, seat, rest, melds, vis) / 100.0)
        elif sh == 1:
            v += float(_ukeire(list(c13), melds, vis, melds_n)) * 3.0
        else:
            # ★ 向听还很远时不算「进张数」——那是 14×34 次 DFS，一次决策能吃掉几十毫秒，
            #   云服务器（1 核）上直接卡到几百毫秒。改成搭子/对子的 O(34) 粗估。
            v += float(_shape_score(c13)) * 1.5
        # ④ 宝牌/赤牌 留着（打掉要扣分；原版 paijia 也是这个意思）
        try:
            dora_kinds = [kind_of(x) for x in (g._dora_kinds() or [])]
        except Exception:
            dora_kinds = []
        if kind_of(t) in dora_kinds or t in ("0m", "0p", "0s"):
            v -= 40.0
        # ⑤ 字牌/端牌先走。★ 孤张（手里只有这一张）给硬加分：
        #    否则进张数在慢机器上被预算截断，会偶发「不打孤张字牌」。
        kk = kind_of(t)
        cnt_kind = hand.count(t)
        if is_honor(kk):
            v += 25.0 if cnt_kind == 1 else 6.0
        elif kk[0] in ("1", "9"):
            v += 8.0 if cnt_kind == 1 else 3.0
        # ⑥ 押し引き：有人立直就按危险度扣分
        if n_riichi:
            v -= _danger(g, seat, t) * safe_w
        if worse:
            v -= 1000.0
        if v > best_v:
            best_v = v
            best = t
    return best if best in hand else (hand[-1] if hand else "")
