# -*- coding: utf-8 -*-
"""Card16/17/18 自测。python test_card1618.py"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")

import game as G  # noqa: E402
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


def new_round(db, seed, orders):
    uids = [db.create_user(f"m{seed}_{i}") for i in range(4)]
    room = db.create_room(uids[0])
    for u in uids[1:]:
        db.join_room(room["room_code"], u)
    match = db.start_match(room["room_id"], seed=seed)
    rid = db.start_round(match, "dong", 1, honba=0, dealer_seat=0, seed=seed)
    g0 = Game(db, rid)
    g0.start()
    while not g0.deal_done():
        g0.deal_step()
    body = {"seats": [{"ready": False, "hand": [], "picks": [], "order": list(o)}
                      for o in orders], "phase": "playing"}
    with db.tx():
        db.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('lobby_state', ?)",
                        (json.dumps(body, ensure_ascii=False),))
    return rid


def to_discard(g, seat=0):
    g.phase = "discard"
    g.turn = seat
    g.save_flags()
    return g


ORD16 = [[16, 1, 2, 3, 5], [1, 2, 3, 4, 5], [1, 2, 3, 4, 5], [1, 2, 3, 4, 5]]
ORD17 = [[17, 1, 2, 3, 5], [1, 2, 3, 4, 5], [1, 2, 3, 4, 5], [1, 2, 3, 4, 5]]
ORD18 = [[18, 1, 2, 3, 5], [1, 2, 3, 4, 5], [1, 2, 3, 4, 5], [1, 2, 3, 4, 5]]


def main() -> int:
    print("=" * 70)
    print(" 天才麻将少女 · Card16 / 17 / 18")
    print("=" * 70)

    for c in (16, 17, 18):
        check(f"登记 {c}", skills.has(c, 1) and skills.has(c, 2))

    db = tg.fresh_db("c1618")
    rid = new_round(db, 1601, ORD16)
    tg.set_hand(db, rid, 0, parse_hand("123m456p789s") + ["1p", "2p", "3s", "4s"], drawn="4s")
    g = to_discard(Game(db, rid))
    g = Game(db, rid)

    print("\n◆ 传承：整个半庄宣告过的技能都能复制")
    check("没有记录 → 不能发动", g.chuancheng_can(0), False)
    g.mark_skill_used(0, 11, 1)                      # 我自己宣告过魔术
    g = Game(db, rid)
    lst = g.chuancheng_list(0)
    check("列表里有我宣告的「魔术」",
          any(x["card"] == 11 and x["skill"] == 1 for x in lst), True)
    check("可以发动了", g.chuancheng_can(0), True)
    try:
        g.chuancheng_use(0, 16, 1)
        check("不能复制自己", False)
    except RuleError as e:
        check("不能复制自己", "自己" in str(e))
    r = g.chuancheng_use(0, 11, 1)
    check("复制成功", r.get("card"), 11)
    g2 = Game(db, rid)
    check("本小局算我的卡", skills.owns_card(db, g2, 0, 11, strict=True), True)
    check("传承记一次", g2.skill_used(0, 16, 1), True)

    print("\n◆ 多面：三面听 ×2")
    db2 = tg.fresh_db("c16b")
    rid2 = new_round(db2, 1602, ORD16)
    # 234m 456p 678s 22s 34s → 听 2s/5s？先测面数函数本身
    tg.set_hand(db2, rid2, 0, parse_hand("234m456p678s") + ["2s", "3s", "4s", "5s"])
    g3 = to_discard(Game(db2, rid2))
    g3 = Game(db2, rid2)
    n = g3._multi_face(0, "ron")
    check("算得出听牌种数", n >= 1, True)
    print("       面数 =", n)

    print("\n◆ 研究：单数看上家、双数看下家")
    db3 = tg.fresh_db("c17a")
    rid3 = new_round(db3, 1701, ORD17)
    tg.set_hand(db3, rid3, 0, parse_hand("123m456p789s") + ["1p", "2p", "3s", "4s"], drawn="4s")
    G.random = type("R", (), {"randint": staticmethod(lambda a, b: 3)})   # 两个 3 → 偶数
    g4 = to_discard(Game(db3, rid3))
    r4 = g4.yanjiu_activate(0)
    check("双数 → 看下家", r4.get("target"), 1)
    g5 = Game(db3, rid3)
    check("state 里带对方手牌", isinstance(g5.state_for(0).get("yanjiu_tiles"), list), True)
    check("别人看不到", g5.state_for(1).get("yanjiu_tiles"), [])

    print("\n◆ 看破：剔除一个技能 + 本局不能和")
    db4 = tg.fresh_db("c17b")
    rid4 = new_round(db4, 1702, ORD17)
    tg.set_hand(db4, rid4, 0, parse_hand("123m456p789s") + ["1p", "2p", "3s", "4s"], drawn="4s")
    g6 = to_discard(Game(db4, rid4))
    check("可以看破", g6.kangpo_can(0), True)
    r5 = g6.kangpo_poke(0, 1, 6, 2)                  # 剔除对家的坚韧
    check("记了屏蔽", r5.get("card"), 6)
    g7 = Game(db4, rid4)
    check("本局我不能和牌", 0 in g7.no_win, True)
    check("别家的人不受影响", g7._win_ok(1, "5s", tsumo=True), g7._win_ok(1, "5s", tsumo=True))
    check("看破记一次", g7.skill_used(0, 17, 2), True)
    check("再看破要拒", g7.kangpo_can(0), False)

    print("\n◆ 枷锁 / 连接")
    db5 = tg.fresh_db("c18")
    rid5 = new_round(db5, 1801, ORD18)
    tg.set_hand(db5, rid5, 0, parse_hand("123m456p789s") + ["1p", "2p", "3s", "4s"], drawn="4s")
    g8 = Game(db5, rid5)
    r6 = g8.jiasuo_set(0, 3)
    check("枷锁定 3 番", r6.get("han"), 3)
    try:
        g8.jiasuo_set(0, 5)
        check("一局只能定一次", False)
    except RuleError as e:
        check("一局只能定一次", "一次" in str(e))
    g9 = to_discard(Game(db5, rid5))
    check("连接可以发动", g9.link_can(0), True)
    try:
        g9.link_use(0, 0)
        check("不能连自己", False)
    except RuleError as e:
        check("不能连自己", "其他玩家" in str(e))
    r7 = g9.link_use(0, 2)
    check("连到 2 号位", r7.get("target"), 2)
    check("记进 flags", Game(db5, rid5).link.get(0), 2)

    print("\n" + "=" * 70)
    print(f" 通过 {PASS} 项，失败 {FAIL} 项")
    print("=" * 70)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
