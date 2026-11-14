# -*- coding: utf-8 -*-
"""【连接】(18-2) 结算：被连接者自摸时，点数必须**和连接者对半分**，且整桌守恒。

历史 bug（2026-11-09 实机两次丢分）：`deltas` 先只放了赢家，连接分账写在
「放铳者付点 / 三家付点」**之前**，而后者用 `=` 赋值 →
自摸时连接者的 +半被覆盖（整桌少一半）；荣和时读 `deltas.get(loser)` 恒为 0。
现在分账挪到付点之后，这个测试守着它。

做法：同手牌跑两遍（有连接 / 没连接），用差值断言——
  · 有连接时赢家 = 没连接时的一半
  · 有连接时连接者 = 自己应付的点 + 那一半
  · 两种情况整桌都守恒

跑法：cd N:\\apps\\tianma\\server; python test_card18_link.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from game import Game                    # noqa: E402
import test_game as tg                   # noqa: E402
from tiles import parse_hand             # noqa: E402

PASS = FAIL = 0
WIN13 = "123m456m789m123p5s"
DRAWN = "5s"


def check(name, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  got {got!r} want {want!r}")


def setup(tag):
    db = tg.fresh_db(tag)
    rid, _m, _u = tg.new_round(db, seed=53)
    tg.set_hand(db, rid, 0, parse_hand(WIN13) + [DRAWN], drawn=DRAWN)
    tg.set_hand(db, rid, 1, parse_hand("1m4m7m1p4p7p1s4s7s1z2z3z"))
    tg.set_hand(db, rid, 2, parse_hand("2m5m8m2p5p8p2s5s8s2z3z4z"))
    tg.set_hand(db, rid, 3, parse_hand("3m6m9m3p6p9p3s6s9s1z2z3z"))
    g = Game(db, rid)
    g.round_phase = "play"
    g.turn, g.phase = 0, "discard"
    g.save_flags()
    return db, rid


def deltas_of(db, rid):
    return {int(r["seat"]): int(r["delta"]) for r in
            db._rows("SELECT seat, delta FROM score_events WHERE round_id=?", (rid,))}


def run(tag, link):
    db, rid = setup(tag)
    if link:
        g0 = Game(db, rid)
        g0.link = dict(link)
        g0.save_flags()
    g = Game(db, rid)
    g.act(0, "tsumo")
    return deltas_of(db, rid)


def main() -> int:
    print("=" * 74)
    print(" Card18 S2【连接】：自摸时和连接者各拿一半，且整桌守恒")
    print("=" * 74)

    print("\n① 座位1 连接座位0（座位0 自摸）")
    d = run("c18a", {1: 0})
    print("     有连接 deltas =", d)
    check("整桌守恒（和 = 0）", sum(d.values()), 0)

    print("\n② 对照：不发动连接")
    d0 = run("c18b", None)
    print("     无连接 deltas =", d0)
    check("整桌守恒（和 = 0）", sum(d0.values()), 0)

    print("\n③ 两者对比（差分断言）")
    half = d0.get(0, 0) // 2
    check("赢家只拿一半", d.get(0, 0), half)
    check("连接者 = 本来要付的 + 那一半", d.get(1, 0), d0.get(1, 0) + half)
    check("另外两家付点不变", (d.get(2), d.get(3)), (d0.get(2), d0.get(3)))

    print("\n" + "=" * 74)
    print(" 合计：%d 断言，%d 失败" % (PASS, FAIL))
    print("=" * 74)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
