# -*- coding: utf-8 -*-
"""Card46 S2【赤里】自测。

跑法：cd N:\\apps\\tianma\\server; python test_card46s2.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from game import Game                              # noqa: E402
import skills                                      # noqa: E402
import test_card30 as t30                          # noqa: E402
import test_game as tg                             # noqa: E402
from tiles import parse_hand                       # noqa: E402

PASS = FAIL = 0
H14 = "123m456m789m234p5s5s"        # 14 张（刚摸 5s）→ 自摸
H13 = "123m456m789m234p5s"          # 13 张，荣和 5s


def check(name, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  got {got!r} want {want!r}")


def ura_of(res):
    for y in (res.get("yaku") or []):
        if str(y.get("name", "")) == "宝牌":
            return int(((y.get("detail") or {}).get("里宝牌")) or 0)
    return 0


def yaku_han(res, name):
    for y in (res.get("yaku") or []):
        if str(y.get("name", "")) == name:
            return int(y.get("han", 0))
    return -1


def setup(tag, holders=(0,), hand=H14, drawn="5s", riichi=True, ura="4s",
          card=46):
    db, rid = t30.setup(tag, card=int(card))
    tg.set_hand(db, rid, 0, parse_hand(hand), drawn=drawn if drawn else None)
    with db.tx():
        db.conn.execute("DELETE FROM round_dora WHERE round_id=?", (rid,))
        db.conn.execute("DELETE FROM round_discards WHERE round_id=?", (rid,))
        db.conn.execute("DELETE FROM round_melds WHERE round_id=?", (rid,))
        db.conn.execute("DELETE FROM round_riichi WHERE round_id=?", (rid,))
        if ura:
            db.conn.execute(
                "INSERT INTO round_dora(round_id, idx, kind, indicator, dora, revealed)"
                " VALUES(?,0,'ura',?,?,1)", (rid, str(ura), "5s"))
        # 上家先碰过 → all_closed() 为假，避免第一巡被判成「天和」役满
        db.conn.execute(
            "INSERT INTO round_melds(round_id,meld_id,seat,kind,called_tile,from_seat,"
            "tiles_json,rot_index,seqs_json) VALUES(?,0,3,'pon','1z',0,?,0,'[]')",
            (rid, '["1z","1z","1z"]'))
        if riichi:
            db.conn.execute(
                "INSERT INTO round_riichi(round_id, seat, declared_seq, ippatsu)"
                " VALUES(?,0,0,0)", (rid,))
    g = Game(db, rid)
    g.granted = {int(x): {46} for x in holders}
    g.round_phase = "play"
    g.phase = "discard"
    g.turn = 0
    g.deal_wait = set()
    g.deal_used = set()
    g.save_flags()
    return db, rid


def main() -> int:
    print("=" * 78)
    print(" Card46 S2【赤里】")
    print("=" * 78)

    print("\n① 注册 / 时机")
    check("名字", skills.info(46, 2).get("name"), "赤里")
    check("时机 = 结算", skills.timing(46, 2), "settle")

    print("\n② 对照组：立直和牌（没带 46 卡）→ 里宝牌照常算")
    db0, rid0 = setup("c46s2z", holders=(), card=6)   # 对照组不带 46 卡
    Game(db0, rid0).act(0, "tsumo")
    res0 = (Game(db0, rid0).result or {})
    check("里宝牌 = 2（指示牌 4s → 5s，手里两张）", ura_of(res0), 2)
    check("没有赤里", yaku_han(res0, "赤里（和到的「5s」算里宝）"), -1)
    han0 = int(res0.get("han", 0))

    print("\n③ 带 46 卡：原里宝无效，和到的 5s 算里宝 2 张 + 5 再多 1 番")
    db, rid = setup("c46s2a")
    Game(db, rid).act(0, "tsumo")
    res = (Game(db, rid).result or {})
    check("原里宝无效（里宝牌 = 0）", ura_of(res), 0)
    check("赤里（和到的「5s」算里宝）2 番",
          yaku_han(res, "赤里（和到的「5s」算里宝）"), 2)
    check("赤里 1 番（和到 5s）", yaku_han(res, "赤里"), 1)
    check("番数比对照组多 1（2 张里宝 + 1 赤里 - 原里宝 2）", int(res.get("han", 0)), han0 + 1)
    check("钩子记了总数", int(res.get("c46s2", 0)), 3)

    print("\n④ 没立直 → 赤里不生效")
    db2, rid2 = setup("c46s2b", riichi=False)
    Game(db2, rid2).act(0, "tsumo")
    res2 = (Game(db2, rid2).result or {})
    check("没有赤里", yaku_han(res2, "赤里（和到的「5s」算里宝）"), -1)
    check("也没有赤里 1 番", yaku_han(res2, "赤里"), -1)

    print("\n⑤ 和到的不是 5 → 只有里宝那一条（没有「赤里 1 番」）")
    # 手牌 123m456m789m234p 9s9s，摸 9s？改：13 张 123m456m789m234p 9s + 摸 9s
    db3, rid3 = setup("c46s2c", hand="123m456m789m234p9s9s", drawn="9s", ura="8s")
    Game(db3, rid3).act(0, "tsumo")
    res3 = (Game(db3, rid3).result or {})
    check("原里宝无效", ura_of(res3), 0)
    check("和到的 9s 算里宝 2 张",
          yaku_han(res3, "赤里（和到的「9s」算里宝）"), 2)
    check("不是 5 → 没有单独的赤里 1 番", yaku_han(res3, "赤里"), -1)

    print("\n⑥ 荣和：铳张也算进「和到的那张」的张数")
    db4, rid4 = setup("c46s2d", hand=H13, drawn=None)
    tg.set_hand(db4, rid4, 1, parse_hand("5s123m456p789s5z5z1z"), drawn=None)
    g4 = Game(db4, rid4)
    g4.phase = "discard"
    g4.turn = 0
    g4.save_flags()
    Game(db4, rid4).act(0, "ron", tile="5s") if False else None
    # 直接走判番：荣和 5s
    res4 = Game(db4, rid4)._judge_win(0, "5s", tsumo=False)
    check("判出来了", bool(res4), True)
    env4 = {"winner": 0, "loser": 1, "result": "ron", "tsumo": False,
            "is_dealer": True}
    g5 = Game(db4, rid4)
    g5.settle_preview(0, 1, "ron", res4)
    check("里宝无效", ura_of(res4), 0)
    check("铳张 5s + 手里 5s = 2 张里宝",
          yaku_han(res4, "赤里（和到的「5s」算里宝）"), 2)
    check("5s 再多 1 番", yaku_han(res4, "赤里"), 1)

    print("\n" + "=" * 78)
    print(f" 合计：{PASS + FAIL} 断言，{FAIL} 失败")
    print("=" * 78)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
