# -*- coding: utf-8 -*-
"""Card21 S2 段2：手切第 8 张后，每巡摸牌前自动问「换牌」；跳过下次再问；发动一次为止"""
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


def add_river(db, rid, seq, seat, tile, wseq):
    with db.tx():
        db.conn.execute(
            "INSERT INTO round_discards(round_id, seq, seat, wall_seq, tile,"
            " is_tsumogiri, is_riichi_tile, face_down, called)"
            " VALUES(?,?,?,?,?,1,0,0,0)", (rid, seq, seat, wseq, tile))


def make(tag, seed, gift_lv=2):
    db = tg.fresh_db(tag)
    rid, _m, _u = tg.new_round(db, seed=seed)
    tg.set_hand(db, rid, 0, parse_hand("123m456p789s1z2z3z") + ["5m"], drawn="5m")
    for s in (1, 2, 3):
        tg.set_hand(db, rid, s, parse_hand("1m4m7m1p4p7p1s4s7s1z2z3z"))
    add_river(db, rid, 500, 1, "9p", 9500)
    g = Game(db, rid)
    g.granted = {0: {21}}
    g.round_phase = "play"
    g.gift[0] = int(gift_lv)
    g.turn, g.phase = 0, "draw"
    g.save_flags()
    return db, rid


def main() -> int:
    print("=" * 66)
    print(" 天马麻将 · Card21 S2 段2（馈赠换牌 · 每巡摸牌前询问）")
    print("=" * 66)

    # ① 摸牌前自动问
    print("\n① 摸牌前自动弹询问")
    db, rid = make("g1", 801)
    g = Game(db, rid)
    check("有换牌资格", g.gift_can(0), True)
    ev = g.advance()
    check("事件是 gift", ev.get("event"), "gift")
    check("phase 变成 gift", g.phase, "gift")
    check("state 下发了 offer",
          typeof_ok(g.state_for(0).get("gift_offer")), True)
    pr = g.prompt_state() or {}
    check("统一询问锁是 gift", pr.get("kind"), "gift")
    check("等的是 0 号位", pr.get("waiting"), [0])

    # ② 跳过 → 下次继续问
    print("\n② 跳过 → 下次继续问")
    g = Game(db, rid)
    r = g.gift_skip(0)
    check("跳过成功", r.get("skipped"), True)
    check("回到摸牌", g.phase, "draw")
    check("没记「用过了」", 0 in g.gift_used, False)
    # 「下一次」= 下一巡：这里把巡数推进一格（打出一张牌）再摸牌
    with db.tx():
        db.conn.execute(
            "INSERT INTO round_actions(round_id, seq, seat, action, payload)"
            " VALUES(?,?,?,?, '{}')", (rid, 9001, 0, "discard"))
    g = Game(db, rid)
    ev2 = g.advance()
    check("下一巡又问一次", ev2.get("event"), "gift")
    # 同一巡重复 advance 不会再问
    g2 = Game(db, rid)
    g2.gift_skip(0)
    check("同一巡不再问", Game(db, rid).gift_offer_open(0), False)

    # ③ 换牌 → 发动一次为止
    print("\n③ 换牌成功后不再问")
    db2, rid2 = make("g2", 802)
    g2 = Game(db2, rid2)
    g2.advance()
    r2 = g2.gift_swap(0, "1m", 500)
    check("换到 9p", r2.get("got"), "9p")
    check("记成用过了", 0 in g2.gift_used, True)
    check("牌真的换了", "9p" in Game(db2, rid2).hand(0), True)
    g2 = Game(db2, rid2)
    check("之后不能再发动", g2.gift_can(0), False)
    ev3 = g2.advance()
    check("之后不再弹窗", ev3.get("event") != "gift", True)

    # ④ 立直后不问（手牌锁定）
    print("\n④ 立直后不问")
    db3, rid3 = make("g3", 803)
    with db3.tx():
        db3.conn.execute(
            "INSERT OR REPLACE INTO round_riichi(round_id, seat, declared_seq, ippatsu)"
            " VALUES(?,?,?,1)", (rid3, 0, 1))
    g3 = Game(db3, rid3)
    check("立直后不能换", g3.gift_can(0), False)
    check("立直后不弹窗", g3.gift_offer_open(0), False)

    # ⑤ 手切不足 8 张不给
    print("\n⑤ 手切不足 8 张不给")
    db4, rid4 = make("g4", 804, gift_lv=1)
    g4 = Game(db4, rid4)
    check("馈赠1 不能换", g4.gift_can(0), False)
    check("不弹窗", g4.gift_offer_open(0), False)

    print("\n" + "=" * 66)
    print(f" 通过 {PASS} / 失败 {FAIL}")
    print("=" * 66)
    return 0 if FAIL == 0 else 1


def typeof_ok(v):
    return isinstance(v, dict) and int(v.get("seat", -1)) == 0


if __name__ == "__main__":
    raise SystemExit(main())
