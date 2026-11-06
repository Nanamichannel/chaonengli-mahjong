# -*- coding: utf-8 -*-
"""配牌技能「多个几乎同时发动」的时序回归（用户口径 2026-11-06）：

   · 三家同时点发动 → 只有第一个开流程，后两个按**点击先后**排队
   · 前一个结算完 → 队列队头自动出列，不会跳过中间那个
   · 全部结算/取消完 → 阶段才关（phase=discard，轮到庄家）
   · 排队中可以撤销，撤销后队列照常往下走
   · 同一个技能重复点不会再排一次

★ 三家都用【南风】（6-1）当测试样本：它一定停在「等玩家选牌种 / 选牌」，
  不像【宝牌运】会「三家都没宝牌 → 当场收尾」，测出来是随机的。

用法：cd server; python test_deal_queue3.py
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


def setup(tag, granted):
    db = tg.fresh_db(tag)
    rid, _m, _u = tg.new_round(db, seed=9)
    with db.tx():                      # 南场：南风只在南场能发
        db.conn.execute("UPDATE rounds SET wind='nan' WHERE round_id=?", (rid,))
    tg.set_hand(db, rid, 0, parse_hand("123m456p789s") + ["dong", "nan", "bai", "1p"])
    tg.set_hand(db, rid, 1, parse_hand("234m567p678s") + ["nan", "2p", "9m"])
    tg.set_hand(db, rid, 2, parse_hand("2m5m8m2p5p8p2s5s8s") + ["dong", "xi", "bei"])
    tg.set_hand(db, rid, 3, parse_hand("3m6m9m3p6p9p3s6s9s") + ["1p", "2p", "3p"])
    g = Game(db, rid)
    g.round_phase = "play"
    g.phase = "deal_skill"
    g.deal_wait = set(granted.keys())
    g.granted = granted
    g.deal_pending = []
    g.deal_flow = None
    g.save_flags()
    return db, rid, g


def finish_south(g, seat):
    """把某家的南风流程走完（选牌种 → 选两张手牌换）。"""
    g.south_wind_kinds(seat, ["dong", "nan"])
    h = g.hand(seat)
    picks = [t for t in ("1m", "2m") if t in h]
    if len(picks) < 2:
        picks = list(dict.fromkeys(h))[:2]
    g.south_wind_swap(seat, picks)


print("① 三家同时发动：先点的先结算，后面的按顺序排队")
db, rid, g = setup("dq3", {0: {6}, 1: {6}, 2: {6}})
g.deal_action(0, "use", 6, 1)
check("第一个直接开流程", str((g.deal_flow or {}).get("kind")), "south_wind")
check("先开流程的是 0 号位", int((g.deal_flow or {}).get("seat", -1)), 0)
r1 = g.deal_action(1, "use", 6, 1)
r2 = g.deal_action(2, "use", 6, 1)
check("1 号位 queued", bool(r1.get("queued")), True)
check("2 号位 queued", bool(r2.get("queued")), True)
check("队列按点击先后排", [x.get("seat") for x in g.deal_pending], [1, 2])
check("排队的都不再挂等待列表", sorted(g.deal_wait), [0])
check("第一个的流程没被顶掉", int((g.deal_flow or {}).get("seat", -1)), 0)

print("\n② 0 号位结算完 → 队头（1 号位）出列，队尾不动")
finish_south(g, 0)
g2 = Game(db, rid)                                  # 重新载入，确认落库
check("出列的是 1 号位", int((g2.deal_flow or {}).get("seat", -1)), 1)
check("2 号位还在队列里", [x.get("seat") for x in g2.deal_pending], [2])
check("阶段还开着（不能提前进打牌）", str(g2.phase), "deal_skill")

print("\n③ 1 号位结算完 → 2 号位出列；它收尾后阶段才关")
finish_south(g2, 1)
g3 = Game(db, rid)
check("出列的是 2 号位", int((g3.deal_flow or {}).get("seat", -1)), 2)
check("队列空了", g3.deal_pending, [])
check("阶段还开着", str(g3.phase), "deal_skill")
finish_south(g3, 2)
g4 = Game(db, rid)
check("没有流程了", g4.deal_flow, None)
check("等待列表清空", sorted(g4.deal_wait), [])
check("进入打牌阶段", str(g4.phase), "discard")
check("轮到庄家", int(g4.turn) if g4.turn is not None else -1, int(g4.dealer))

print("\n④ 排队者撤销后，后面那个补上（不留空档）")
db5, rid5, g5 = setup("dq3b", {0: {6}, 1: {6}, 2: {6}})
g5.deal_action(0, "use", 6, 1)
g5.deal_action(1, "use", 6, 1)
g5.deal_action(2, "use", 6, 1)
r = g5.deal_action(1, "skip")                       # 撤销排队
check("撤销成功", bool(r.get("unqueued")), True)
check("队列只剩 2 号位", [x.get("seat") for x in g5.deal_pending], [2])
finish_south(g5, 0)
g6 = Game(db5, rid5)
check("撤销的那个没有顶掉后面的", int((g6.deal_flow or {}).get("seat", -1)), 2)

print("\n⑤ 同一个技能重复点：不会再排一次")
db7, rid7, g7 = setup("dq3c", {0: {6}, 1: {6}})
g7.deal_action(0, "use", 6, 1)
g7.deal_action(1, "use", 6, 1)
r7 = g7.deal_action(1, "use", 6, 1)                 # 客户端没收到状态又点了一次
check("第二次不再入队", len(g7.deal_pending), 1)
check("返回 done（不报错）", bool(r7.get("done")), True)

print("\n" + "=" * 70)
print(" 通过 %d 项，失败 %d 项" % (PASS, FAIL))
print("=" * 70)
sys.exit(1 if FAIL else 0)
