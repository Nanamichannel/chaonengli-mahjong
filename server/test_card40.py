# -*- coding: utf-8 -*-
"""Card40 S1【透视】自测。

跑法：cd N:\\apps\\tianma\\server; python test_card40.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from game import Game, RuleError                     # noqa: E402
import skills                                        # noqa: E402
import test_card30 as t30                            # noqa: E402
import test_game as tg                               # noqa: E402
from tiles import parse_hand                         # noqa: E402

PASS = FAIL = 0
H0 = "123m456m789m234p5z3s"


def check(name, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  got {got!r} want {want!r}")


def setup(tag, card=40):
    db, rid = t30.setup(tag, card=card, mains=[card, 6, 7, 8])
    tg.set_hand(db, rid, 0, parse_hand(H0), drawn="3s")
    with db.tx():
        db.conn.execute("DELETE FROM round_dora WHERE round_id=?", (rid,))
        db.conn.execute("DELETE FROM round_discards WHERE round_id=?", (rid,))
        db.conn.execute("DELETE FROM round_melds WHERE round_id=?", (rid,))
        db.conn.execute("DELETE FROM round_riichi WHERE round_id=?", (rid,))
    g = Game(db, rid)
    g.granted = {0: {card}}
    g.round_phase = "play"
    g.phase = "discard"
    g.turn = 0
    g.deal_wait = set()
    g.deal_used = set()
    g.save_flags()
    return db, rid


def reveal_seats(db, rid, seat=0):
    return [int(x.get("seat", -1)) for x in (Game(db, rid).state_for(seat).get("reveal_hands") or [])]


def main() -> int:
    print("=" * 78)
    print(" Card40 S1【透视】")
    print("=" * 78)

    print("\n① 注册 / 时机")
    check("名字", skills.info(40, 1).get("name"), "透视")
    check("时机 = 切牌", skills.timing(40, 1), "discard")

    print("\n② 三家各一个计数器，初始 1")
    db, rid = setup("c40a")
    g = Game(db, rid)
    check("对下家还剩 1", g.c40s1_left(0, 1), 1)
    check("对家还剩 1", g.c40s1_left(0, 2), 1)
    check("上家还剩 1", g.c40s1_left(0, 3), 1)
    st = g.state_for(0)
    check("state 里三家的余量", (st.get("c40") or {}).get("counts"),
          {"1": 1, "2": 1, "3": 1})

    print("\n③ 非立直 + 计数 1 → 看得到，计数归 0")
    r = g.c40s1_apply(0, 1)
    check("看得到", bool(r.get("shown")), True)
    check("不是免费", bool(r.get("free")), False)
    g2 = Game(db, rid)
    check("计数归 0", g2.c40s1_left(0, 1), 0)
    check("reveal 里有他", reveal_seats(db, rid), [1])
    check("state.c40.shown", (g2.state_for(0).get("c40") or {}).get("shown"), [1])

    print("\n④ 同一家计数 0 → 不给看")
    g3 = Game(db, rid)
    r2 = g3.c40s1_apply(0, 1)
    check("不给看", bool(r2.get("shown")), False)
    check("给了原因", str(r2.get("why", "")) != "", True)

    print("\n⑤ 立直中 → 免费看，计数不变")
    with db.tx():
        db.conn.execute("INSERT INTO round_riichi(round_id, seat, declared_seq, ippatsu) "
                        "VALUES(?,2,-1,0)", (rid,))
    g4 = Game(db, rid)
    r3 = g4.c40s1_apply(0, 2)
    check("看得到", bool(r3.get("shown")), True)
    check("免费", bool(r3.get("free")), True)
    g5 = Game(db, rid)
    check("计数还是 1", g5.c40s1_left(0, 2), 1)
    check("再免费看一次也行", bool(g5.c40s1_apply(0, 2).get("shown")), True)
    check("计数仍 1", Game(db, rid).c40s1_left(0, 2), 1)

    print("\n⑥ 多看一眼不重叠：看过的人会一直显示（直到我打牌）")
    g6 = Game(db, rid)
    g6.c40s1_apply(0, 3)
    check("三家都在（③ 看过 1、⑤ 看过 2、这里看过 3）",
          sorted(reveal_seats(db, rid)), [1, 2, 3])

    print("\n⑦ 打出一张牌 → 看到的复位（计数不回补）")
    g7 = Game(db, rid)
    g7._do_discard(0, tile="3s")
    g8 = Game(db, rid)
    check("reveal 清空", (g8.state_for(0).get("reveal_hands")), [])
    check("计数不回补", g8.c40s1_left(0, 3), 0)
    check("立直那家的计数还是 1", g8.c40s1_left(0, 2), 1)

    print("\n⑧ 不是我的回合 → 不能发动")
    g9 = Game(db, rid)
    g9.turn = 1
    g9.save_flags()
    try:
        Game(db, rid).c40s1_apply(0, 2)
        check("被拒", False, True)
    except RuleError:
        check("被拒", True, True)

    print("\n" + "=" * 78)
    print(f" 通过 {PASS} / 失败 {FAIL}")
    print("=" * 78)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
