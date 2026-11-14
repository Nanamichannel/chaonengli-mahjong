# -*- coding: utf-8 -*-
"""E2：【满贯】(28-1) 抬门槛拦下的和牌张 = 见逃 → 同巡振听；立直中 → 本局永久振听

跑法：cd server; python test_card28_furiten.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")

from game import Game          # noqa: E402
import test_card30 as t30      # noqa: E402
import test_game as tg        # noqa: E402
from tiles import parse_hand   # noqa: E402

PASS = 0
FAIL = 0

# 13 张，单骑等 5s：和到是「一气通贯」2 番（够不到满贯）
WAIT_YAKU = "123m456m789m234p5s"
# 13 张，单骑等 5p：**无役**（两刻两顺，不是三暗刻 / 有幺九不断幺 / 单骑没平和）
WAIT_NONE = "111m999p234s567s5p"


def check(name, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  got={got!r} want={want!r}")


def setup(tag, banchong=True, riichi=True, hand=WAIT_YAKU):
    """1 号位：等一张牌；banchong=True → 3 号位开了【满贯】"""
    db, rid = t30.setup(tag, card=8)
    for s in range(4):
        tg.set_hand(db, rid, s, parse_hand(hand))
    with db.tx():
        db.conn.execute("DELETE FROM round_dora WHERE round_id=?", (rid,))
        db.conn.execute("DELETE FROM round_discards WHERE round_id=?", (rid,))
        db.conn.execute("DELETE FROM round_riichi WHERE round_id=?", (rid,))
        if riichi:
            db.conn.execute(
                "INSERT INTO round_riichi(round_id, seat, declared_seq, ippatsu)"
                " VALUES(?,1,0,0)", (rid,))
    g = Game(db, rid)
    g.round_phase = "play"
    g.phase = "discard"
    g.turn = 0                                # 0 号位打牌
    g.c28s1_on = {3} if banchong else set()
    g.temp_furiten = set()
    g.riichi_furiten = set()
    g.save_flags()
    return db, rid


def opts_of(g, tile, from_seat):
    g._open_claim_window(900, tile, from_seat)
    p = g.pending or {}
    return {int(s): [str(a.get("action")) for a in acts]
            for s, acts in (p.get("options") or {}).items()}


def main() -> int:
    print("=" * 74)
    print(" Card28 S1【满贯】拦下的和牌张 = 见逃（振听）")
    print("=" * 74)

    print("\n① 对照组：没开满贯 → 1 号位（立直）能荣 5s，不振听")
    db, rid = setup("c28f0", banchong=False)
    g = Game(db, rid)
    check("有荣和按钮", opts_of(g, "5s", 0).get(1), ["ron"])
    g2 = Game(db, rid)
    check("不记同巡振听", 1 in g2.temp_furiten, False)
    check("不记立直后见逃", 1 in g2.riichi_furiten, False)

    print("\n② 开了满贯：立直 + 一气 2 番够不到 → 见逃 → 永久振听")
    db2, rid2 = setup("c28f1", banchong=True)
    g3 = Game(db2, rid2)
    check("没有荣和按钮", opts_of(g3, "5s", 0).get(1), None)
    g4 = Game(db2, rid2)
    check("记了同巡振听", 1 in g4.temp_furiten, True)
    check("立直中 → 记立直后见逃（本局永久）", 1 in g4.riichi_furiten, True)
    check("落库", 1 in Game(db2, rid2).riichi_furiten, True)
    check("之后同一张也荣不了", g4._win_ok(1, "5s", tsumo=False), False)

    print("\n③ 满贯 + 没立直（有役但不到满贯）→ 见逃，只记同巡振听")
    db3, rid3 = setup("c28f2", banchong=True, riichi=False)
    g5 = Game(db3, rid3)
    check("没有荣和按钮", opts_of(g5, "5s", 0).get(1), None)
    g6 = Game(db3, rid3)
    check("记了同巡振听", 1 in g6.temp_furiten, True)
    check("没立直 → 不记永久振听", 1 in g6.riichi_furiten, False)

    print("\n④ 满贯 + 无役手牌 → 本来就没资格和 → 不算见逃、不振听")
    db4, rid4 = setup("c28f3", banchong=True, riichi=False, hand=WAIT_NONE)
    g7 = Game(db4, rid4)
    check("没有荣和按钮", opts_of(g7, "5p", 0).get(1), None)
    g8 = Game(db4, rid4)
    check("不记同巡振听（无役 ≠ 见逃）", 1 in g8.temp_furiten, False)
    check("不记永久振听", 1 in g8.riichi_furiten, False)

    print("\n" + "=" * 74)
    print(f" 合计：{PASS} 断言，{FAIL} 失败")
    print("=" * 74)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
