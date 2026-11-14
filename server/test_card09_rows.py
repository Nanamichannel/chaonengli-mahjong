# -*- coding: utf-8 -*-
"""P9：(b) 口径 —— 【间合】的「一行牌河只能换一次」改成**按发动者各算各的**。

规则（用户口径 2026-11-09）：
  · 座位0 用【间合攻】换了座位3 牌河第 0 行 → 只有**座位0**不能再换那一行
  · 座位3 自己想用【间合守】换自己那一行 → **允许**（以前被全局占用挡住）
  · 同一个人对同一行第二次 → 仍然拒绝

跑法：cd N:\\apps\\tianma\\server; python test_card09_rows.py
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from game import Game, RuleError         # noqa: E402
from tiles import parse_hand             # noqa: E402
import test_game as tg                   # noqa: E402

PASS = FAIL = 0
HAND = parse_hand("123m456m789p12s5z")    # 13 张，含「白」
HT = str(HAND[0])                          # 拿一张真实牌 id 当「换出去的手牌」
ORD_9 = [[9, 1, 2, 3, 4], [1, 2, 3, 5, 6], [1, 2, 3, 5, 7], [9, 1, 2, 5, 8]]


def check(name, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  got={got!r} want={want!r}")


def new_round(db, seed: int, orders) -> int:
    uids = [db.create_user(f"c09r{seed}_{i}") for i in range(4)]
    room = db.create_room(uids[0])
    for u in uids[1:]:
        db.join_room(room["room_code"], u)
    match = db.start_match(room["room_id"], seed=seed)
    rid = db.start_round(match, "dong", 1, honba=0, dealer_seat=0, seed=seed)
    body = {"seats": [{"ready": False, "hand": [], "picks": [], "order": list(o)}
                      for o in orders],
            "phase": "playing"}
    with db.tx():
        db.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('lobby_state', ?)",
                        (json.dumps(body, ensure_ascii=False),))
    return rid


def add_river(db, rid, seq: int, seat: int, tile: str) -> None:
    with db.tx():
        db.conn.execute(
            "INSERT INTO round_discards(round_id, seq, seat, wall_seq, tile,"
            " is_tsumogiri, is_riichi_tile, face_down, called) VALUES(?,?,?,?,?,0,0,0,0)",
            (rid, seq, seat, 5000 + seq, tile))


def err(g, *args, **kw):
    try:
        g.card09_swap(*args, **kw)
        return ""
    except RuleError as e:
        return str(e)


def at_draw(db, rid, seat: int) -> Game:
    g = Game(db, rid)
    g.round_phase = "play"
    g.turn, g.phase = int(seat), "draw"
    g.c09_turn = ""
    g.c09_next = {}                      # 本测只验「行占用」，把 S1/S2 交替清掉
    g.save_flags()
    return Game(db, rid)


def main() -> int:
    print("=" * 72)
    print(" Card09【间合】：行占用按「发动者」各算各的")
    print("=" * 72)

    db = tg.fresh_db("c09rows")
    rid = new_round(db, 61, ORD_9)
    tg.set_hand(db, rid, 0, HAND)
    tg.set_hand(db, rid, 3, HAND)
    for i in range(7):                       # 座位3 牌河：第 0 行 6 张 + 第 1 行 1 张
        add_river(db, rid, 100 + i, 3, ["1m", "2m", "3m", "4m", "5m", "6m", "7m"][i])

    g = Game(db, rid)
    g.granted = {0: {9}, 3: {9}}             # 两家都持 09 号卡
    g.round_phase = "play"
    g.turn, g.phase = 0, "draw"
    g.save_flags()

    print("\n① 座位0 用【间合攻】换座位3 牌河第 0 行")
    g = at_draw(db, rid, 0)
    r = g.card09_swap(0, 2, HT, 100)
    check("换成功", str(r.get("got", "")), "1m")
    g = Game(db, rid)
    check("占用记成「发动者:河主:行」", sorted(g.c09_rows), ["0:3:0"])

    print("\n② 座位0 再换同一行 → 仍然拒绝")
    g = at_draw(db, rid, 0)
    e = err(g, 0, 2, HT, 101)
    check("同一个人同一行第二次被拒", "换过" in e, True)

    print("\n③ 座位3 用【间合守】换**自己**同一行 → 现在允许（b 口径）")
    g = at_draw(db, rid, 3)
    e2 = err(g, 3, 1, HT, 101)
    check("别人换过不影响我换", e2, "")

    print("\n④ 座位3 再换自己同一行 → 拒绝（自己也不能重复）")
    g = at_draw(db, rid, 3)
    e3 = err(g, 3, 1, str(HAND[2]), 102)
    check("自己同一行第二次被拒", "换过" in e3, True)

    print("\n" + "=" * 72)
    print(" 合计：%d 断言，%d 失败" % (PASS, FAIL))
    print("=" * 72)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
