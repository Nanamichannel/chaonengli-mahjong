# -*- coding: utf-8 -*-
"""Card39 S1【隐形】+ S2【无视】自测。

跑法：cd N:\\apps\\tianma\\server; python test_card39.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from game import Game, RuleError                  # noqa: E402
import api_cli                                     # noqa: E402
import skills                                      # noqa: E402
import test_card30 as t30                          # noqa: E402
import test_game as tg                             # noqa: E402
from tiles import parse_hand                       # noqa: E402

PASS = FAIL = 0
H14 = "123m456m789m234p5s5s"


def check(name, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  got {got!r} want {want!r}")


def add_river(db, rid, seq, seat, tile, wseq, down=False):
    with db.tx():
        db.conn.execute(
            "INSERT INTO round_discards(round_id, seq, seat, wall_seq, tile,"
            " is_tsumogiri, is_riichi_tile, face_down, called)"
            " VALUES(?,?,?,?,?,1,0,?,0)", (rid, seq, seat, wseq, tile, 1 if down else 0))


def setup(tag, holes=8, card=39, hand=None, drawn="5s", ura=None):
    db, rid = t30.setup(tag, card=int(card))
    tg.set_hand(db, rid, 0, parse_hand(hand or H14), drawn=drawn)
    with db.tx():
        db.conn.execute("DELETE FROM round_dora WHERE round_id=?", (rid,))
        db.conn.execute("DELETE FROM round_discards WHERE room_id=?", (rid,)) \
            if False else None
        db.conn.execute("DELETE FROM round_discards WHERE round_id=?", (rid,))
        db.conn.execute("DELETE FROM round_melds WHERE round_id=?", (rid,))
        db.conn.execute("DELETE FROM round_riichi WHERE round_id=?", (rid,))
        # 上家先碰过 → 避免第一巡被判天和
        db.conn.execute(
            "INSERT INTO round_melds(round_id,meld_id,seat,kind,called_tile,from_seat,"
            "tiles_json,rot_index,seqs_json) VALUES(?,0,3,'pon','1z',0,?,0,'[]')",
            (rid, '["1z","1z","1z"]'))
        if ura:
            db.conn.execute(
                "INSERT INTO round_dora(round_id, idx, kind, indicator, dora, revealed)"
                " VALUES(?,0,'ura',?,?,1)", (rid, str(ura), "5s"))
    for i in range(int(holes)):
        add_river(db, rid, 500 + i, 0, ["1m", "2m", "3m", "4m", "6p", "7p", "8p", "9p",
                                        "1s", "2s"][i % 10], 800 + i)
    g = Game(db, rid)
    g.granted = {0: {int(card)}}
    g.round_phase = "play"
    g.phase = "discard"
    g.turn = 0
    g.deal_wait = set()
    g.deal_used = set()
    g.save_flags()
    return db, rid


def yaku_han(res, name):
    for y in (res.get("yaku") or []):
        if str(y.get("name", "")) == name:
            return int(y.get("han", 0))
    return -1


def main() -> int:
    print("=" * 78)
    print(" Card39 S1【隐形】+ S2【无视】")
    print("=" * 78)

    print("\n① 注册 / 时机")
    check("S1 名字", skills.info(39, 1).get("name"), "隐形")
    check("S2 名字", skills.info(39, 2).get("name"), "无视")
    check("S1 时机 = 切牌", skills.timing(39, 1), "discard")

    print("\n② 隐形：发动条件（摸牌后 + 自己牌河满 7 张）")
    dbA, ridA = setup("c39a", holes=6)
    check("6 张 → 不能发动", Game(dbA, ridA).c39s1_can(0), False)
    dbA2, ridA2 = setup("c39a2", holes=7)
    check("7 张（摸牌后）→ 能发动", Game(dbA2, ridA2).c39s1_can(0), True)
    dbA3, ridA3 = setup("c39a3", holes=8, drawn=None)
    check("牌河够但没摸牌 → 不能发动", Game(dbA3, ridA3).c39s1_can(0), False)
    db, rid = setup("c39b", holes=8)
    g = Game(db, rid)
    check("8 张 → 能发动", g.c39s1_can(0), True)
    r = g.c39s1_apply(0)
    check("开启", bool(r.get("on")), True)
    g2 = Game(db, rid)
    check("落库", g2.c39s1_on, True)
    check("一次", g2.c39s1_can(0), False)

    print("\n③ 隐形之后：不能鸣 / 不能被荣 / 不造成振听")
    g3 = Game(db, rid)
    g3.phase = "discard"
    g3.turn = 3
    check("加速闸门关掉", g3._c29s1_gate(900, "5s", 3), False)
    check("暗置牌也不能荣", g3._open_facedown_claim(901, "5s", 3), False)
    g4 = Game(db, rid)
    g4.phase = "discard"
    g4.turn = 3
    g4._open_claim_window(902, "5s", 3)      # 本来 0 号位能碰/荣
    check("鸣牌窗口一个选项都没有", g4.pending, None)
    check("振听表为空", g4.discards_for_furiten(1), [])

    print("\n④ 无视：门前清 + 持卡 → 当作立直（不动 is_riichi / 不锁手牌）")
    db2, rid2 = setup("c39c")
    g5 = Game(db2, rid2)
    check("c39s2_fake = True", g5.c39s2_fake(0), True)
    check("但真立直还是 False", g5.is_riichi(0), False)
    check("手牌没锁（能正常手切）", g5.hand_locked(0), False)
    check("不是 must_tsumogiri", 0 in g5.must_tsumogiri, False)
    tiles = []
    for a in g5.legal_actions(0):
        if a.get("action") == "discard":
            tiles = list(a.get("tiles") or [])
    check("可以打任意手牌（不是只摸切）", len(tiles) > 1, True)

    print("\n⑤ 无视：和牌按立直结算（立直 1 番 + 里宝）")
    db3, rid3 = setup("c39d", ura="4s")      # 里宝指示牌 4s → 里宝 5s，手里两张
    Game(db3, rid3).act(0, "tsumo")
    res3 = (Game(db3, rid3).result or {})
    check("有立直", yaku_han(res3, "立直"), 1)
    ura = 0
    for y in (res3.get("yaku") or []):
        if str(y.get("name", "")) == "宝牌":
            ura = int(((y.get("detail") or {}).get("里宝牌")) or 0)
    check("里宝 2 张也算上了", ura, 2)

    db4, rid4 = setup("c39e", ura="4s", card=6)  # 对照组：没这张卡
    Game(db4, rid4).act(0, "tsumo")
    res4 = (Game(db4, rid4).result or {})
    check("对照组没有立直", yaku_han(res4, "立直"), -1)
    check("番数比对照组多（立直+里宝）",
          int(res3.get("han", 0)) > int(res4.get("han", 0)), True)

    print("\n⑥ 有副露 → 无视不生效")
    db5, rid5 = setup("c39f")
    with db5.tx():
        db5.conn.execute(
            "INSERT INTO round_melds(round_id,meld_id,seat,kind,called_tile,from_seat,"
            "tiles_json,rot_index,seqs_json) VALUES(?,1,0,'pon','9s',1,?,0,'[]')",
            (rid5, '["9s","9s","9s"]'))
    check("有副露 → False", Game(db5, rid5).c39s2_fake(0), False)

    print("\n⑦ op 层登记")
    check("OPS 里有 c39s1_apply", "c39s1_apply" in api_cli.OPS, True)
    check("卡号/技能号登记", api_cli._SKILL_OP_PAIRS.get("c39s1_apply"), (39, 1))

    print("\n" + "=" * 78)
    print(f" 合计：{PASS + FAIL} 断言，{FAIL} 失败")
    print("=" * 78)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
