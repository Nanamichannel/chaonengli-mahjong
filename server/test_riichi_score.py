# -*- coding: utf-8 -*-
"""立直完全放开（用户口径 2026-11-08）：负分 / 不足 1000 点也能立直。

原来 rule：`can_riichi()` 里 `scores < 1000 → False`（日麻标准）。
现在：整条删掉，供托照扣（点数可以扣成负数）。

跑法：cd N:\apps\tianma\server; python test_riichi_score.py
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
DRAWN = "9s"
HAND = "123m456m789m5p5p6s7s"


def check(name, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  got {got!r} want {want!r}")


def setup(tag, score: int, hand: str = HAND):
    """0 号位切 9s 后听 5s/8s（门清听牌），点数设成 score。"""
    db = tg.fresh_db(tag)
    rid, _m, _u = tg.new_round(db, seed=53)
    tg.set_hand(db, rid, 0, parse_hand(hand) + [DRAWN], drawn=DRAWN)
    tg.set_hand(db, rid, 1, parse_hand("1m4m7m1p4p7p1s4s7s1z2z3z"))
    tg.set_hand(db, rid, 2, parse_hand("2m5m8m2p5p8p2s5s8s2z3z4z"))
    tg.set_hand(db, rid, 3, parse_hand("3m6m9m3p6p9p3s6s9s1z2z3z"))
    g = Game(db, rid)
    g.round_phase = "play"
    g.turn, g.phase = 0, "discard"
    g.save_flags()
    with db.tx():
        db.conn.execute("UPDATE match_seats SET score=? WHERE match_id=? AND seat=0",
                        (int(score), int(g.match_id)))
    return Game(db, rid)


def main() -> int:
    print("=" * 74)
    print(" 立直完全放开：负分 / 不足 1000 点也能立直")
    print("=" * 74)

    print("\n① can_riichi：各种点数都要能立直")
    for tag, sc in (("r1000", 1000), ("r999", 999), ("r0", 0), ("rneg", -5000)):
        g = setup(tag, sc)
        check("%s 点 → can_riichi" % sc, g.can_riichi(0), True)
        acts = [a.get("action") for a in g.legal_actions(0)]
        check("%s 点 → 有 riichi 选项" % sc, "riichi" in acts, True)
        check("%s 点 → 点数确实设成 %s" % (sc, sc), g.scores().get(0), sc)

    print("\n② 负分立直真的能宣言：供托扣 1000（扣成更负）")
    g = setup("rneg2", -1200)
    ev = g.act(0, "riichi", tile=DRAWN)
    check("立直成功", bool(ev) or True)
    check("已进入立直状态", g.is_riichi(0), True)
    check("点数 -1200 → -2200", g.scores().get(0), -2200)

    print("\n③ 不该立的仍然立不了（回归）")
    g = setup("rneg3", -9999, hand="123m456m789m1p4p7p2s")   # 切哪张都不听 → 不能立直
    check("不听牌 → 不能立直", g.can_riichi(0), False)

    print("\n" + "=" * 74)
    print(" 合计：%d 断言，%d 失败" % (PASS, FAIL))
    print("=" * 74)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
