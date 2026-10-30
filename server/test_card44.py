# -*- coding: utf-8 -*-
"""Card44 S1【弃子】自测。

跑法：cd N:\\apps\\tianma\\server; python test_card44.py
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
H0 = "123m456m789m234p5z3s"
HW = "123m456m789m234p5s5s"


def check(name, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  got {got!r} want {want!r}")


def setup(tag, holders=(0,)):
    db, rid = t30.setup(tag, card=44, mains=[44, 6, 7, 8])
    tg.set_hand(db, rid, 0, parse_hand(H0), drawn="3s")
    with db.tx():
        db.conn.execute("DELETE FROM round_dora WHERE round_id=?", (rid,))
        db.conn.execute("DELETE FROM round_discards WHERE round_id=?", (rid,))
        db.conn.execute("DELETE FROM round_melds WHERE round_id=?", (rid,))
        db.conn.execute("DELETE FROM round_riichi WHERE round_id=?", (rid,))
    g = Game(db, rid)
    g.granted = {int(s): {44} for s in holders}
    g.round_phase = "play"
    g.phase = "discard"
    g.turn = 0
    g.deal_wait = set()
    g.deal_used = set()
    g.save_flags()
    return db, rid


def deltas_of(db, rid):
    d = (Game(db, rid).result or {}).get("deltas") or {}
    return {int(k): int(v) for k, v in d.items()}


def main() -> int:
    print("=" * 78)
    print(" Card44 S1【弃子】")
    print("=" * 78)

    print("\n① 注册 / 时机")
    check("名字", skills.info(44, 1).get("name"), "弃子")
    check("时机 = 结算", skills.timing(44, 1), "settle")

    print("\n② 亲家役满自摸（每家 16000）→ 持有者不付")
    db, rid = setup("c44a", holders=(1,))
    tg.set_hand(db, rid, 0, parse_hand("123m456m789m234p5s5s"), drawn="5s")
    g = Game(db, rid)
    g.act(0, "tsumo")
    g2 = Game(db, rid)
    res = g2.result or {}
    check("基础得点是 48000（每家 16000）", int(res.get("points", 0)) >= 48000, True)
    dd = deltas_of(db, rid)
    check("1 号位不付", dd.get(1, -999), 0)
    check("赢家少收那 16000", int(dd.get(0, 0)), int(res.get("points", 0)) - 16000)
    w = (res.get("c44s1") or [])
    check("明细里记了 1 号位", [int(x.get("seat", -1)) for x in w], [1])

    print("\n③ 正好 16000 也触发（「以上」含等于）")
    check("saved = 16000", int((w[0] if w else {}).get("saved", 0)), 16000)

    print("\n④ 失点小于 16000 且不超过自己点数 → 照付")
    db2, rid2 = setup("c44b", holders=(1,))
    tg.set_hand(db2, rid2, 0, parse_hand("123m456m789m234p5z3s"), drawn="3s")
    tg.set_hand(db2, rid2, 0, parse_hand("123m456m789m234p5s5s"), drawn="5s")
    g3 = Game(db2, rid2)
    # 造一个「1 番 30 符」级别的小和牌：用碰牌 + 副露减少得点太麻烦，
    # 这里直接验证 helper：deltas 里 1 号位只有 -8000 → 不该免
    deltas = {0: 8000, 1: -8000, 2: -4000, 3: -4000}
    got = g3._c44s1_waive(0, deltas, "tsumo")
    check("8000 不失点豁免", got, [])
    check("deltas 不变", [deltas[0], deltas[1]], [8000, -8000])

    print("\n⑤ 失点超过自己点数 → 不付")
    db3, rid3 = setup("c44c", holders=(1,))
    g4 = Game(db3, rid3)
    with db3.tx():
        db3._score(rid3, 1, -30000, "test")     # 1 号位只剩 5000
    g4 = Game(db3, rid3)
    check("1 号位点数 5000", int(g4.scores().get(1, 0)), 5000)
    deltas2 = {0: 8000, 1: -8000, 2: -4000, 3: -4000}
    got2 = g4._c44s1_waive(0, deltas2, "tsumo")
    check("8000 > 5000 → 免掉", [int(x.get("saved", 0)) for x in got2], [8000])
    check("1 号位归 0", deltas2[1], 0)
    check("赢家少收", deltas2[0], 0)

    print("\n⑥ 不持有 44 → 照付")
    db4, rid4 = setup("c44d", holders=())
    g5 = Game(db4, rid4)
    deltas3 = {0: 16000, 1: -16000, 2: -16000, 3: -16000}
    got3 = g5._c44s1_waive(0, deltas3, "tsumo")
    check("没有豁免", got3, [])
    check("deltas 不变", deltas3[1], -16000)

    print("\n⑦ 赢家自己不会被豁免（只处理失点）")
    db5, rid5 = setup("c44e", holders=(0,))
    g6 = Game(db5, rid5)
    deltas4 = {0: 48000, 1: -16000, 2: -16000, 3: -16000}
    got4 = g6._c44s1_waive(0, deltas4, "tsumo")
    check("赢家不减", deltas4[0], 48000)
    check("其他三家都不持有 → 没豁免", got4, [])

    print("\n⑧ 弃子生效 → 播报面板补「失点 X → 0（弃子）」")
    db6, rid6 = setup("c44f", holders=(1,))
    tg.set_hand(db6, rid6, 0, parse_hand("123m456m789m234p5s5s"), drawn="5s")
    g7 = Game(db6, rid6)
    g7.act(0, "tsumo")                     # 天和 48000 → 每家 16000 → 1 号位弃子
    g8 = Game(db6, rid6)
    check("1 号位真没付", int((g8.result or {}).get("deltas", {}).get("1", -1)), 0)
    _b = g8.broadcast or {}
    check("播报有一句", bool(str(_b.get("text", ""))), True)
    check("播报写的是弃子", "弃子" in str(_b.get("text", "")), True)
    check("播报里有「→ 0」", "→ 0" in str(_b.get("text", "")), True)

    print("\n" + "=" * 78)
    print(f" 通过 {PASS} / 失败 {FAIL}")
    print("=" * 78)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
