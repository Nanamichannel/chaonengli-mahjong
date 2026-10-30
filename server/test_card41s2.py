# -*- coding: utf-8 -*-
"""Card41 S2【局终】自测。

跑法：cd N:\\apps\\tianma\\server; python test_card41s2.py
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
HW = "123m456m789m234p5s5s"                          # 和牌形（自摸 5s）


def check(name, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  got {got!r} want {want!r}")


def setup(tag):
    db, rid = t30.setup(tag, card=41, mains=[41, 6, 7, 8])
    tg.set_hand(db, rid, 0, parse_hand(H0), drawn="3s")
    with db.tx():
        db.conn.execute("DELETE FROM round_dora WHERE round_id=?", (rid,))
        db.conn.execute("DELETE FROM round_discards WHERE round_id=?", (rid,))
        db.conn.execute("DELETE FROM round_melds WHERE round_id=?", (rid,))
        db.conn.execute("DELETE FROM round_riichi WHERE round_id=?", (rid,))
    g = Game(db, rid)
    g.granted = {0: {41}}
    g.round_phase = "play"
    g.phase = "discard"
    g.turn = 0
    g.deal_wait = set()
    g.deal_used = set()
    g.save_flags()
    return db, rid


def give_copies(db, rid, items):
    """直接写 c41_copies（模拟已经复制过）。"""
    with db.tx():
        pass
    g = Game(db, rid)
    g.c41_copies[0] = [dict(x) for x in items]
    g.save_flags()


def deltas_of(db, rid):
    d = (Game(db, rid).result or {}).get("deltas") or {}
    return {int(k): int(v) for k, v in d.items()}


def main() -> int:
    print("=" * 78)
    print(" Card41 S2【局终】")
    print("=" * 78)

    print("\n① 注册 / 时机")
    check("名字", skills.info(41, 2).get("name"), "局终")
    check("时机 = 结算", skills.timing(41, 2), "settle")

    print("\n② 别人和牌 + 我复制过 1 个 → 我付他 1000")
    db, rid = setup("c41s2a")
    give_copies(db, rid, [{"card": 33, "skill": 1, "from": 1}])
    tg.set_hand(db, rid, 1, parse_hand(HW), drawn="5s")
    g = Game(db, rid)
    g.turn = 1
    g.phase = "discard"
    g.save_flags()
    g = Game(db, rid)
    base = g.scores().get(0, 0)
    g.act(1, "tsumo")
    g2 = Game(db, rid)
    check("结算存了 c41s2", isinstance((g2.result or {}).get("c41s2"), dict), True)
    dd = deltas_of(db, rid)
    pay = ((g2.result or {}).get("c41s2") or {}).get("0") or \
          ((g2.result or {}).get("c41s2") or {}).get(0) or []
    check("明细：付给 1 号 1000", [int(x.get("points", 0)) for x in pay], [1000])
    # seat0 除正常失点外还要多付 1000
    check("c41s2 明细指向 1 号", int((pay[0] if pay else {}).get("to", -1)), 1)

    print("\n③ 复制两个不同来源 → 分别各付 1000")
    db2, rid2 = setup("c41s2b")
    give_copies(db2, rid2, [{"card": 33, "skill": 1, "from": 1},
                            {"card": 6, "skill": 2, "from": 2}])
    tg.set_hand(db2, rid2, 3, parse_hand(HW), drawn="5s")
    g3 = Game(db2, rid2)
    g3.turn = 3
    g3.phase = "discard"
    g3.save_flags()
    g3 = Game(db2, rid2)
    g3.act(3, "tsumo")
    g4 = Game(db2, rid2)
    p2 = (g4.result or {}).get("c41s2") or {}
    lst = p2.get("0") or p2.get(0) or []
    got = sorted([(int(x.get("to", -1)), int(x.get("points", 0))) for x in lst])
    check("两家各 1000", got, [(1, 1000), (2, 1000)])

    print("\n④ 我自己和牌 → 不付")
    db3, rid3 = setup("c41s2c")
    give_copies(db3, rid3, [{"card": 33, "skill": 1, "from": 1}])
    tg.set_hand(db3, rid3, 0, parse_hand(HW), drawn="5s")
    g5 = Game(db3, rid3)
    g5.act(0, "tsumo")
    g6 = Game(db3, rid3)
    check("没有 c41s2 明细", not bool((g6.result or {}).get("c41s2")), True)

    print("\n⑤ 流局也算「没和牌」→ 照付")
    db4, rid4 = setup("c41s2d")
    give_copies(db4, rid4, [{"card": 33, "skill": 1, "from": 2}])
    g7 = Game(db4, rid4)
    g7._ryuukyoku("exhaustive")
    g8 = Game(db4, rid4)
    p4 = (g8.result or {}).get("c41s2") or {}
    lst4 = p4.get("0") or p4.get(0) or []
    check("流局也付 1000", [int(x.get("points", 0)) for x in lst4], [1000])
    check("付给 2 号", int((lst4[0] if lst4 else {}).get("to", -1)), 2)

    print("\n⑥ 没复制过 → 不付")
    db5, rid5 = setup("c41s2e")
    tg.set_hand(db5, rid5, 1, parse_hand(HW), drawn="5s")
    g9 = Game(db5, rid5)
    g9.turn = 1
    g9.phase = "discard"
    g9.save_flags()
    g9 = Game(db5, rid5)
    g9.act(1, "tsumo")
    g10 = Game(db5, rid5)
    check("没有明细", not bool((g10.result or {}).get("c41s2")), True)

    print("\n" + "=" * 78)
    print(f" 通过 {PASS} / 失败 {FAIL}")
    print("=" * 78)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
