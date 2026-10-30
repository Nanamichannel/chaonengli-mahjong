# -*- coding: utf-8 -*-
"""立直后手牌锁定：任何技能都不能改立直家的手牌

覆盖：钓鱼 / 自风 / 画板 / 海神 / do_swap 全家桶 / 拔北 / 破发 / 压制 / 画板3⇄3
反向：立直家自己摸牌、打牌、暗杠、荣和照常
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")

from game import Game, RuleError  # noqa: E402
from tiles import parse_hand  # noqa: E402
import test_game as tg  # noqa: E402

PASS = 0
FAIL = 0


def check(name, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  got={got!r} want={want!r}")


def add_river(db, rid, seq, seat, tile, wseq, down=False):
    with db.tx():
        db.conn.execute(
            "INSERT INTO round_discards(round_id, seq, seat, wall_seq, tile,"
            " is_tsumogiri, is_riichi_tile, face_down, called)"
            " VALUES(?,?,?,?,?,1,0,?,0)", (rid, seq, seat, wseq, tile, 1 if down else 0))


def make(tag, seed, seat0_riichi=True, hand0=None, drawn0="1p"):
    """0 号位立直（默认），1 号位持钓鱼/自风/海神等。</summary>"""
    db = tg.fresh_db(tag)
    rid, _m, _u = tg.new_round(db, seed=seed)
    h0 = hand0 or (parse_hand("123m456p789s1z2z3z") + [drawn0])
    tg.set_hand(db, rid, 0, h0, drawn=drawn0)
    tg.set_hand(db, rid, 1, parse_hand("1m4m7m1p4p7p1s4s7s1z2z3z"))
    tg.set_hand(db, rid, 2, parse_hand("2m5m8m2p5p8p2s5s8s2z3z4z"))
    tg.set_hand(db, rid, 3, parse_hand("3m6m9m3p6p9p3s6s9s1z2z3z"))
    g = Game(db, rid)
    g.round_phase = "play"
    g.turn, g.phase = 0, "discard"
    g.save_flags()
    if seat0_riichi:
        with db.tx():
            db.conn.execute(
                "INSERT OR REPLACE INTO round_riichi(round_id, seat, declared_seq, ippatsu)"
                " VALUES(?,?,?,1)", (rid, 0, 1))
    return db, rid


def hand_of(db, rid, seat):
    return sorted(g.hand(seat) for g in [Game(db, rid)])[0] if False else sorted(
        Game(db, rid).hand(seat))


def main() -> int:
    print("=" * 66)
    print(" 天马麻将 · 立直后手牌锁定")
    print("=" * 66)

    # ① 钓鱼
    print("\n① 钓鱼不能钓立直家")
    db, rid = make("rl_dy", 501)
    add_river(db, rid, 500, 0, "5s", 9500)
    g = Game(db, rid)
    g.granted = {1: {15}}
    g.save_flags()
    before = hand_of(db, rid, 0)
    g = Game(db, rid)
    g.granted = {1: {15}}
    check("立直家不在可钓名单里", g.diaoyu_options(1, 0), [])
    try:
        g.diaoyu_force(1, 0, "5s")
        check("钓鱼立直家要被拒", False)
    except RuleError as e:
        check("钓鱼立直家要被拒", "立直" in str(e))
    check("手牌一张没变", hand_of(db, rid, 0), before)
    check("失败即锁本小局", Game(db, rid).diaoyu_locked, True)

    # ② 自风
    print("\n② 自风不能拿走立直家的摸牌")
    db, rid = make("rl_wind", 502)
    g = Game(db, rid)
    g.self_wind = {1}
    g.save_flags()
    g = Game(db, rid)
    check("立直家摸到自风也不弹窗", g._self_wind_owner(0, "dong"), None)
    g.wind_swap = {"owner": 1, "from": 0, "tile": "dong"}
    g.phase = "wind_swap"
    g.save_flags()
    before = hand_of(db, rid, 0)
    g = Game(db, rid)
    g.wind_swap = {"owner": 1, "from": 0, "tile": "dong"}
    g.phase = "wind_swap"
    try:
        g.wind_swap_apply(1, "1m")
        check("自风换立直家要被拒", False)
    except RuleError as e:
        check("自风换立直家要被拒", "立直" in str(e))
    check("手牌一张没变", hand_of(db, rid, 0), before)

    # ③ 海神
    print("\n③ 海神不能借立直家的摸牌")
    db, rid = make("rl_hs", 503)
    g = Game(db, rid)
    g.granted = {0: {5}, 1: {12}}
    g.haishin_on = True
    g.save_flags()
    g = Game(db, rid)
    g.granted = {0: {5}, 1: {12}}
    g.haishin_on = True
    check("立直家摸万子不触发海神", g._haishin_owner(0, "9m"), None)

    # ④ 画板：立直家摸到的牌不被抢走
    print("\n④ 画板不能抽走立直家的摸牌")
    db, rid = make("rl_board", 504)
    g = Game(db, rid)
    g.boards[1] = {"tiles": ["9p"], "delivered": [], "pending": []}
    g.save_flags()
    g = Game(db, rid)
    check("不转给画板持有者", g._board_transfer(0, {"tile": "9p", "seq": 1}), None)
    check("画板没记这笔", (g.boards.get(1) or {}).get("delivered"), [])

    # ⑤ do_swap 全家桶
    print("\n⑤ do_swap 挡住所有换牌")
    db, rid = make("rl_swap", 505)
    h0 = hand_of(db, rid, 0)
    g = Game(db, rid)
    rows0 = g.db._rows("SELECT wall_seq, tile FROM round_hands WHERE round_id=? AND seat=0",
                       (rid,))
    rows1 = g.db._rows("SELECT wall_seq, tile FROM round_hands WHERE round_id=? AND seat=1",
                       (rid,))
    add_river(db, rid, 600, 2, "9p", 9600)
    cases = [
        ("hand_hand（海神借牌/迷途之家）",
         lambda gg: gg.do_swap("hand_hand", 1, "测试", seat_a=0, hand_seq_a=int(rows0[0]["wall_seq"]),
                               seat_b=1, hand_seq_b=int(rows1[0]["wall_seq"]))),
        ("hand_river（策略段2/间合）",
         lambda gg: gg.do_swap("hand_river", 0, "测试", hand_seq=int(rows0[0]["wall_seq"]),
                               river_seq=600, face_down=False)),
        ("hand_wall（魔术/海神换宝）",
         lambda gg: gg.do_swap("hand_wall", 0, "测试", hand_seq=int(rows0[0]["wall_seq"]),
                               wall_seq=0)),
        ("river_hand（友引）",
         lambda gg: gg.do_swap("river_hand", 0, "测试", river_seq=600, seat=0)),
    ]
    for name, fn in cases:
        g = Game(db, rid)
        try:
            fn(g)
            check(name + " 要被拒", False)
        except RuleError as e:
            check(name + " 要被拒", "立直" in str(e))
        check(name + " 手牌没变", hand_of(db, rid, 0), h0)
    check("wall_wall 不受影响（不动手牌）", isinstance(
        Game(db, rid).do_swap("wall_wall", 1, "测试", seq_a=0, seq_b=1), dict), True)

    # ⑥ 其它自己动手的技能
    print("\n⑥ 拔北 / 破发 / 压制 / 画板3⇄3 都拒绝")
    db, rid = make("rl_self", 506)
    g = Game(db, rid)
    g.granted = {0: {5, 13, 3, 2}}
    g.pofa_ask = {"declarer": 1, "waiting": [0], "ts": 1.0}
    g.save_flags()
    add_river(db, rid, 700, 1, "4s", 9700)
    for name, fn in (("拔北", lambda gg: gg.card05_nuki(0)),
                     ("破发", lambda gg: gg.pofa_activate(0, 700, ["5p", "6p"])),
                     ("压制", lambda gg: gg.suppress_swap(0, "1p", 700)),
                     ("画板3⇄3", lambda gg: gg.swap_river(0, ["1m", "2m", "3m"], [700, 701, 702]))):
        gg = Game(db, rid)
        try:
            fn(gg)
            check(name + " 要拒绝立直家", False)
        except RuleError as e:
            check(name + " 要拒绝立直家", "立直" in str(e))

    # ⑦ 反向：立直家自己摸牌 / 打牌照常
    print("\n⑦ 立直家自己摸打照常")
    db, rid = make("rl_ok", 507, seat0_riichi=False)
    with db.tx():
        db.conn.execute(
            "INSERT OR REPLACE INTO round_riichi(round_id, seat, declared_seq, ippatsu)"
            " VALUES(?,?,?,1)", (rid, 0, 1))
    g = Game(db, rid)
    n0 = len(g.hand(0))
    ev = g.act(0, "discard", tile="1p")
    check("立直家能打牌", ev.get("event"), "discard")
    check("打完少一张", len(g.hand(0)), n0 - 1)
    g = tg.to_draw(Game(db, rid), 0)
    g.advance()
    check("立直家能摸牌", len(g.hand(0)), n0)

    print("\n" + "=" * 66)
    print(f" 通过 {PASS} / 失败 {FAIL}")
    print("=" * 66)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
