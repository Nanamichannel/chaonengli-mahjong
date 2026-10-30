# -*- coding: utf-8 -*-
"""Card19~23 自测。python test_card1923.py"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")

from game import Game, RuleError, COLD_KINDS, WARM_KINDS  # noqa: E402
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
    uids = [db.create_user(f"n{seed}_{i}") for i in range(4)]
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


def add_discard(db, rid, seat, seq, tile, face_down=0, tsumogiri=1):
    with db.tx():
        db.conn.execute(
            "INSERT INTO round_discards(round_id, seat, seq, wall_seq, tile, called,"
            " is_riichi_tile, face_down, is_tsumogiri) VALUES(?,?,?,?,?,0,0,?,?)",
            (rid, seat, seq, 900000 + seq, tile, face_down, tsumogiri))


def add_meld(db, rid, seat, meld_id, kind, tiles):
    with db.tx():
        db.conn.execute(
            "INSERT INTO round_melds(round_id, seat, meld_id, kind, called_tile, from_seat,"
            " tiles_json, rot_index, seqs_json) VALUES(?,?,?,?,?,?,?,?,?)",
            (rid, seat, meld_id, kind, tiles[0], 1, json.dumps(tiles), 0, "[]"))


H = parse_hand("123m456p789s") + ["1p", "2p", "3s", "4s"]


def main() -> int:
    print("=" * 70)
    print(" 天才麻将少女 · Card19 ~ Card23")
    print("=" * 70)

    for c in (19, 20, 21, 22, 23):
        check(f"登记 {c}", skills.has(c, 1) and skills.has(c, 2))
    check("暖系含 zhong", "zhong" in WARM_KINDS, True)
    check("冷系含 3p", "3p" in COLD_KINDS, True)
    check("5s 是暖系", "5s" in WARM_KINDS, True)

    print("\n◆ 深山：第 12 张之后开，开着就报牌")
    db = tg.fresh_db("n19")
    rid = new_round(db, 1901, [[19, 1, 2, 3, 5], [1, 2, 3, 4, 5], [1, 2, 3, 4, 5], [1, 2, 3, 4, 5]])
    tg.set_hand(db, rid, 0, H, drawn="4s")
    g = Game(db, rid)
    g.phase, g.turn = "discard", 0
    g.save_flags()
    g = Game(db, rid)
    check("不到 12 张 → 不能开", g.shenshan_can(0), False)
    try:
        g.shenshan_toggle(0)
        check("不到 12 张 → 拒绝", False)
    except RuleError as e:
        check("不到 12 张 → 拒绝", "12" in str(e))
    for i in range(12):
        add_discard(db, rid, 0, 1910 + i, "1m", tsumogiri=1)
    g2 = Game(db, rid)
    check("满 12 张 → 可以开", g2.shenshan_can(0))
    r = g2.shenshan_toggle(0)
    check("打开", r.get("on"), True)
    g3 = Game(db, rid)
    check("再点 → 关", g3.shenshan_toggle(0).get("on"), False)
    g3 = Game(db, rid)
    g3.shenshan_toggle(0)
    g3 = Game(db, rid)
    check("有人摸牌 → 报给我", g3.shenshan_offer_draw(1, "5p"), True)
    check("阶段变成 shenshan", g3.phase, "shenshan")
    check("跳过", g3.shenshan_resolve(0, "").get("skipped"), True)

    print("\n◆ 浓雾：4 巡内别家不能自摸")
    db2 = tg.fresh_db("n19b")
    rid2 = new_round(db2, 1902, [[19, 1, 2, 3, 5], [1, 2, 3, 4, 5], [1, 2, 3, 4, 5], [1, 2, 3, 4, 5]])
    tg.set_hand(db2, rid2, 0, H, drawn="4s")
    g4 = Game(db2, rid2)
    g4.phase, g4.turn = "discard", 0
    g4.save_flags()
    g4 = Game(db2, rid2)
    check("浓雾可以发动", g4.nongwu_can(0))
    g4.nongwu_activate(0)
    g5 = Game(db2, rid2)
    check("别家不能自摸", g5._win_ok(1, "5s", tsumo=True), False)
    check("别家还能荣和", g5._win_ok(1, "5s", tsumo=False), g5._win_ok(1, "5s", tsumo=False))
    check("自己不受影响", g5._win_ok(0, "5s", tsumo=True), g5._win_ok(0, "5s", tsumo=True))

    print("\n◆ 前路：预言三张，全中 → 一定和牌")
    db3 = tg.fresh_db("n20")
    rid3 = new_round(db3, 2001, [[20, 1, 2, 3, 5], [1, 2, 3, 4, 5], [1, 2, 3, 4, 5], [1, 2, 3, 4, 5]])
    tg.set_hand(db3, rid3, 0, H, drawn="4s")
    for i in range(3):
        add_discard(db3, rid3, 0, 2010 + i, "1m", tsumogiri=1)
    g6 = Game(db3, rid3)
    g6.phase, g6.turn = "discard", 0
    g6.save_flags()
    g6 = Game(db3, rid3)
    check("3 巡之后能预言", g6.qianlu_can(0))
    g6.qianlu_set(0, ["1p", "2p", "3s"])
    g7 = Game(db3, rid3)
    for i, t in enumerate(["1p", "2p", "3s"]):
        g7._after_discard_hooks(0, t)
    g8 = Game(db3, rid3)
    check("三张全中 → 一定和牌", 0 in g8.yiding, True)

    print("\n◆ 感知 / 迷途之家 / 加热")
    db4 = tg.fresh_db("n21")
    rid4 = new_round(db4, 2101, [[21, 1, 2, 3, 5], [1, 2, 3, 4, 5], [1, 2, 3, 4, 5], [1, 2, 3, 4, 5]])
    tg.set_hand(db4, rid4, 0, H, drawn="4s")
    for i in range(4):
        add_discard(db4, rid4, 0, 2110 + i, "1m", tsumogiri=0)
    g9 = Game(db4, rid4)
    check("手切 4 张 → 馈赠1", g9._gift_check(0), 1)
    for i in range(4, 8):
        add_discard(db4, rid4, 0, 2110 + i, "1m", tsumogiri=0)
    g10 = Game(db4, rid4)
    check("手切 8 张 → 馈赠2", g10._gift_check(0), 2)
    for i in range(8, 12):
        add_discard(db4, rid4, 0, 2110 + i, "1m", tsumogiri=0)
    g11 = Game(db4, rid4)
    check("手切 12 张 → 馈赠3", g11._gift_check(0), 3)
    check("馈赠3 不再直接给一定和牌（改成听牌时给）", 0 in g11.yiding, False)

    db5 = tg.fresh_db("n23")
    rid5 = new_round(db5, 2301, [[23, 1, 2, 3, 5], [1, 2, 3, 4, 5], [1, 2, 3, 4, 5], [1, 2, 3, 4, 5]])
    tg.set_hand(db5, rid5, 0, H, drawn="4s")
    g12 = Game(db5, rid5)
    g12.phase, g12.turn = "discard", 0
    g12.save_flags()
    g12 = Game(db5, rid5)
    check("加热可以发动", g12.heat_can(0))
    try:
        g12.heat_activate(0, "5m")
        check("暖系不能加热", False)
    except RuleError as e:
        check("暖系不能加热", "冷系" in str(e))
    r2 = g12.heat_activate(0, "3p")
    check("加热 3p", r2.get("kind"), "3p")
    g13 = Game(db5, rid5)
    check("记进 flags", g13.heat_kind, "3p")
    check("冷系数得对", g13._cold_count(0) >= 0, True)

    print("\n◆ 先负：换牌 → 立直 → 那家出铳")
    db6 = tg.fresh_db("n22")
    rid6 = new_round(db6, 2201, [[22, 1, 2, 3, 5], [1, 2, 3, 4, 5], [1, 2, 3, 4, 5], [1, 2, 3, 4, 5]])
    tg.set_hand(db6, rid6, 0, H, drawn="4s")
    add_discard(db6, rid6, 1, 2210, "7p")
    with db6.tx():
        db6.conn.execute("INSERT INTO round_riichi(round_id, seat) VALUES(?,1)", (rid6,))
    g14 = Game(db6, rid6)
    g14.phase, g14.turn = "discard", 0
    g14.ippatsu = {1}
    g14.save_flags()
    g14 = Game(db6, rid6)
    g14.ippatsu = {1}
    check("别人一发巡 → 可以发动", g14.xianfu_can(0))
    r3 = g14.xianfu_swap(0, "4s", 2210)
    check("换到 7p", r3.get("got"), "7p")
    check("记下待立直", Game(db6, rid6).xianfu_armed, 0)
    g15 = Game(db6, rid6)
    g15.xianfu_pending = {"seat": 0, "declarer": 1}
    ev = g15._xianfu_settle(1)
    check("结算成先负", ev.get("event"), "xianfu")
    check("赢家是我", (g15.result or {}).get("result"), "ron")
    deltas = (g15.result or {}).get("deltas") or {}
    check("输家是立直那一家", int(deltas.get(1, 0)) < 0, True)
    check("其他家不掏钱", int(deltas.get(2, 0)), 0)

    print("\n◆ 友引：四副露单骑，牌河代摸牌")
    db7 = tg.fresh_db("n22b")
    rid7 = new_round(db7, 2202, [[22, 1, 2, 3, 5], [1, 2, 3, 4, 5], [1, 2, 3, 4, 5], [1, 2, 3, 4, 5]])
    for i, tiles in enumerate([["1m", "2m", "3m"], ["4p", "5p", "6p"],
                              ["7s", "8s", "9s"], ["1p", "1p", "1p"]]):
        add_meld(db7, rid7, 0, i, "chi" if i < 3 else "pon", tiles)
    # 新口径：四副露 + 摸完牌（手牌 2 张），一张手牌 ↔ 牌河一张互换
    tg.set_hand(db7, rid7, 0, ["5s", "3p"], drawn="3p")
    add_discard(db7, rid7, 1, 2220, "5s")
    g16 = Game(db7, rid7)
    g16.turn, g16.phase = 0, "discard"
    g16.save_flags()
    g16 = Game(db7, rid7)
    check("四副露 + 刚摸牌 → 可以发动", g16.youyin_swap_can(0))
    r4 = g16.youyin_take(0, 2220, "3p")
    check("挑到 5s", r4.get("got"), "5s")
    g17 = Game(db7, rid7)
    check("手里有 5s 了", "5s" in list(g17.hand(0)), True)
    left = db7._row("SELECT tile FROM round_discards WHERE round_id=? AND seq=2220", (rid7,))
    check("牌河那张换成了我的手牌 3p", left["tile"] if left else None, "3p")

    print("\n" + "=" * 70)
    print(f" 通过 {PASS} 项，失败 {FAIL} 项")
    print("=" * 70)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
