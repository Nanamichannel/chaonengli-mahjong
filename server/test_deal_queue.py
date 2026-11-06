# -*- coding: utf-8 -*-
"""配牌技能排队（用户口径 2026-11-06）：
  南风先发动 → 风神进等待队列 → 南风结算完 → 风神自动出列结算。

用法：cd server; python test_deal_queue.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")

from game import Game  # noqa: E402
from tiles import parse_hand  # noqa: E402
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
    rid, _m, _u = tg.new_round(db, seed=9)
    # 南场：南风（Card6 S1）只有南场能发
    with db.tx():
        db.conn.execute("UPDATE rounds SET wind='nan' WHERE round_id=?", (rid,))
    tg.set_hand(db, rid, 0, parse_hand("123m456p789s") + ["dong", "nan", "bai", "1p"])
    tg.set_hand(db, rid, 1, parse_hand("234m567p678s") + ["nan", "2p", "9m"])
    tg.set_hand(db, rid, 2, parse_hand("2m5m8m2p5p8p2s5s8s") + ["dong", "xi", "bei"])
    tg.set_hand(db, rid, 3, parse_hand("3m6m9m3p6p9p3s6s9s") + ["1p", "2p", "3p"])
    g = Game(db, rid)
    g.round_phase = "play"
    g.phase = "deal_skill"
    g.deal_wait = {0, 1}
    g.granted = {0: {6}, 1: {4}}
    g.deal_pending = []
    g.deal_flow = None
    g.save_flags()
    return db, rid, g


print("① 南风先发动 → 风神不报错，进队列")
db, rid, g = setup("dq1")
r1 = g.deal_action(0, "use", 6, 1)
check("南风开流程", str((g.deal_flow or {}).get("kind")), "south_wind")
check("南风期间两家都还在列表（发起人收尾才走、排队者写了才走）", sorted(g.deal_wait), [0, 1])
r2 = g.deal_action(1, "use", 4, 1)
check("风神返回 queued", bool(r2.get("queued", False)), True)
check("风神进了排队", [(x.get("seat"), x.get("card")) for x in g.deal_pending], [(1, 4)])
check("风神不再挂在等待列表", sorted(g.deal_wait), [0])
check("南风流程还在跑（没被顶掉）", str((g.deal_flow or {}).get("kind")), "south_wind")

print("\n② 南风走完 → 风神自动出列")
g.south_wind_kinds(0, ["dong", "nan"])
h = g.hand(0)
picks = [t for t in ("1m", "2m") if t in h]
check("手里有能换的两张", len(picks), 2)
g.south_wind_swap(0, picks)
g2 = Game(db, rid)                        # 重新从 flags 载入，确认落库了
check("南风流程结束", g2.deal_flow is not None, True)
check("出列的是风神", str((g2.deal_flow or {}).get("kind")), "fengshen")
check("风神的主人正确", int((g2.deal_flow or {}).get("seat", -1)), 1)
check("排队队列清空", g2.deal_pending, [])

print("\n③ 取消风神 → 配牌阶段结束，进入打牌")
g2.skill_cancel(1)
g3 = Game(db, rid)
check("没有流程了", g3.deal_flow, None)
check("进入打牌阶段", str(g3.phase), "discard")

print("\n④ 排队中的技能可以撤销")
db4, rid4, g4 = setup("dq4")
g4.deal_action(0, "use", 6, 1)
g4.deal_action(1, "use", 4, 1)
r = g4.deal_action(1, "skip")
check("撤销排队成功", bool(r.get("unqueued", False)), True)
check("队列空了", g4.deal_pending, [])

print("\n" + "=" * 70)
print(" 通过 %d 项，失败 %d 项" % (PASS, FAIL))
print("=" * 70)
sys.exit(1 if FAIL else 0)
