# -*- coding: utf-8 -*-
"""批次 2 回归：A2 前路时机校验 / A3 结算技能翻明（只翻不明置灰）。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")

from game import Game, RuleError  # noqa: E402
from tiles import parse_hand  # noqa: E402
import skills  # noqa: E402
import test_game as tg  # noqa: E402

PASS = FAIL = 0


def check(name, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  got={got!r} want={want!r}")


def setup(tag):
    db = tg.fresh_db(tag)
    rid, _m, _u = tg.new_round(db, seed=13)
    tg.set_hand(db, rid, 0, parse_hand("123m456p789s") + ["dong", "nan", "xi", "bei"])
    tg.set_hand(db, rid, 1, parse_hand("234m567p678s") + ["2p", "2p", "9m"])
    tg.set_hand(db, rid, 2, parse_hand("2m5m8m2p5p8p2s5s8s") + ["dong", "nan", "xi"])
    tg.set_hand(db, rid, 3, parse_hand("3m6m9m3p6p9p3s6s9s") + ["bei", "bai", "fa"])
    with db.tx():                    # 给 seat2 造 3 张牌河（前路要求 3 巡之后）
        for i in range(3):
            db.conn.execute(
                "INSERT INTO round_discards(round_id, seq, seat, tile, wall_seq, is_tsumogiri) "
                "VALUES(?,?,?,?,?,1)", (rid, 900 + i, 2, "1p", 990 + i))
    g = Game(db, rid)
    g.round_phase = "play"
    g.phase, g.turn = "discard", 0
    g.granted = {2: {20}}
    g.save_flags()
    return db, rid, g


print("① 前路：别人回合不能发动")
db, rid, g = setup("b2a2")
try:
    g.qianlu_set(2, ["1m", "2m", "3m"])
    check("别人回合被拒", False, True)
except RuleError as e:
    check("别人回合被拒（%s）" % str(e)[:16], True, True)
check("没有脏状态", g.qianlu, None)

print("\n② 前路：自己的回合可以发动")
g.turn = 2
g.save_flags()
r = g.qianlu_set(2, ["1m", "2m", "3m"])
check("自己的回合能发", str((r or {}).get("seat", "")), "2")

print("\n③ 结算类技能也要翻明（但不进 used_skills）")
db3, rid3, g3 = setup("b2a3")
check("结算前没翻明", "2:32" in (skills._char_use(db3) or {}), False)
g3._settle_fx(2, 32)
cu = skills._char_use(db3) or {}
check("结算后翻明了", "2:32" in cu, True)
check("没有把图标置灰", "32-2-2" in g3.used_skills, False)

print("\n" + "=" * 70)
print(" 通过 %d 项，失败 %d 项" % (PASS, FAIL))
print("=" * 70)
sys.exit(1 if FAIL else 0)
