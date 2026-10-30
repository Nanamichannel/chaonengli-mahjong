# -*- coding: utf-8 -*-
"""先负：换牌之后，**每一张**「可立直切牌」都必须真的能切出去立直。
（前端能点到的每一张都要过服务端这一关，不能出现「列表里有、点了没反应」。）
"""
from __future__ import annotations

import io
import sys

sys.path.insert(0, r'N:\apps\tianma\server')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from game import Game  # noqa: E402
from tiles import parse_hand  # noqa: E402
import test_game as tg  # noqa: E402

OK = 0
BAD = 0


def check(cond, msg):
    global OK, BAD
    if cond:
        OK += 1
    else:
        BAD += 1
        print("  [FAIL]", msg)


def build(tag):
    db = tg.fresh_db(tag)
    rid, _m, _u = tg.new_round(db, seed=41)
    tg.set_hand(db, rid, 0, parse_hand("123m456p789s111p99p"), drawn="9p")
    with db.tx():
        db.conn.execute("INSERT OR REPLACE INTO round_riichi(round_id, seat) VALUES(?,?)",
                        (rid, 1))
        db.conn.execute(
            "INSERT OR REPLACE INTO round_discards(round_id, seat, seq, wall_seq, tile,"
            " called, is_riichi_tile, face_down, is_tsumogiri)"
            " VALUES(?,?,?,?,?,0,0,0,1)", (rid, 1, 1401, 940001, "7p"))
    g = Game(db, rid)
    g.granted = {0: {22}}
    g.ippatsu.add(1)
    g.gift = {0: 0}
    g.phase, g.turn = "discard", 0
    g.save_flags()
    return db, rid


def main():
    db, rid = build("xfr")
    g = Game(db, rid)
    check(g.xianfu_can(0), "先负应该可以发动")
    g.xianfu_swap(0, "9p", 1401)

    g = Game(db, rid)
    disc = list(g.riichi_discards(0))
    print("换牌后可立直切牌 =", disc)
    check(bool(disc), f"应该有可切牌，实际 {disc}")

    import itertools
    _n = itertools.count(1)
    for t in disc:
        db2, rid2 = build("xfr%d" % next(_n))
        g2 = Game(db2, rid2)
        g2.xianfu_swap(0, "9p", 1401)
        g3 = Game(db2, rid2)
        cand = list(g3.riichi_discards(0))
        if t not in cand:
            check(False, f"{t} 第二次建局面时不在可切列表 {cand}")
            continue
        try:
            ev = g3.act(0, "riichi", tile=str(t))
            check(True, f"切 {t} 立直成功")
        except Exception as e:
            check(False, f"切 {t} 立直失败：{type(e).__name__}: {e}")

    # 顺手确认：立直之后 legal 只给「刚摸的那张」
    g4 = Game(db2, rid2)
    if g4.is_riichi(0):
        acts = [a for a in g4.legal_actions(0) if a["action"] == "discard"]
        if acts:
            check(len(acts[0]["tiles"]) == 1, f"立直后只应允许摸切，实际 {acts[0]['tiles']}")

    print(f"\n通过 {OK} / 失败 {BAD}")
    return 1 if BAD else 0


if __name__ == "__main__":
    sys.exit(main())
