# -*- coding: utf-8 -*-
"""宝牌张数回归测试：同一手牌里有 2 张宝牌时，必须算 2 番（不是 1）"""
import io, os, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import importlib
tg = importlib.import_module("test_game")
from game import Game

FAIL = []


def check(name, got, want):
    ok = got == want
    print(("  \u2713 " if ok else "  \u2717 ") + name + (
        "" if ok else "  got=%r want=%r" % (got, want)))
    if not ok:
        FAIL.append(name)


def dora_han(res) -> int:
    for y in (res.get("yaku") or []):
        if str(y.get("name", "")).startswith("宝牌"):
            return int(y.get("han", 0))
    return 0


def no_tenhou(g):
    """第一巡和牌会判天和/地和（役满把番数清零），测试里假装已经打过牌。"""
    g._has_discarded = lambda s: True       # type: ignore
    g.all_closed = lambda: False            # type: ignore
    return g


def main():
    db = tg.fresh_db("dora")
    rid, match, uids = tg.new_round(db, seed=31)
    db.add_dora(rid, "dora", 0, "4m", "5m")

    # ① 自摸，手里两张 5m（指示牌 4m → 宝牌 5m）→ 宝牌 2 番
    tg.set_hand(db, rid, 0, ["3m", "4m", "5m", "5m", "6m", "7m",
                             "1p", "2p", "3p", "7s", "8s", "9s", "5p", "5p"])
    g = no_tenhou(Game(db, rid))
    res = g._judge_win(0, "5p", tsumo=True)
    print("  自摸 2 张 5m → han=%s yaku=%s" % (
        (res or {}).get("han"), [y.get("name") for y in (res or {}).get("yaku") or []]))
    check("同种 2 张宝牌 = 2 番", dora_han(res or {}), 2)

    # ② 荣和：手里 1 张 5m + 铳牌也是 5m → 2 张宝牌
    tg.set_hand(db, rid, 1, ["3m", "4m", "5m", "6m", "7m",
                             "1p", "2p", "3p", "7s", "8s", "9s", "5p", "5p"])
    g = no_tenhou(Game(db, rid))
    res2 = g._judge_win(1, "5m", tsumo=False)
    print("  荣和 5m（手里已有 1 张）→ han=%s yaku=%s" % (
        (res2 or {}).get("han"), [y.get("name") for y in (res2 or {}).get("yaku") or []]))
    check("铳牌算宝牌（手里1+铳1=2 番）", dora_han(res2 or {}), 2)

    # ③ 杠后翻出第二张指示牌，两张各命中 1 张 → 2 番
    db.add_dora(rid, "dora", 1, "4s", "5s")
    tg.set_hand(db, rid, 2, ["5m", "6m", "7m", "5s", "6s", "7s",
                             "1p", "2p", "3p", "7s", "8s", "9s", "5p", "5p"])
    g = no_tenhou(Game(db, rid))
    res3 = g._judge_win(2, "5p", tsumo=True)
    print("  两张指示牌(5m/5s) → han=%s yaku=%s" % (
        (res3 or {}).get("han"), [y.get("name") for y in (res3 or {}).get("yaku") or []]))
    check("两张指示牌各命中 1 张 = 2 番", dora_han(res3 or {}), 2)

    # ④ 手里 3 张同种宝牌 → 3 番
    tg.set_hand(db, rid, 3, ["5m", "5m", "5m", "6m", "7m", "8m",
                             "1p", "2p", "3p", "7s", "8s", "9s", "5p", "5p"])
    g = no_tenhou(Game(db, rid))
    res4 = g._judge_win(3, "5p", tsumo=True)
    print("  手里 3 张 5m → han=%s yaku=%s" % (
        (res4 or {}).get("han"), [y.get("name") for y in (res4 or {}).get("yaku") or []]))
    check("3 张宝牌 = 3 番", dora_han(res4 or {}), 3)

    print("\n%d 项通过 / %d 项失败" % (4 - len(FAIL), len(FAIL)))
    return 1 if FAIL else 0


sys.exit(main())
