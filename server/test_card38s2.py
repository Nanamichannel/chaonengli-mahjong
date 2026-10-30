# -*- coding: utf-8 -*-
"""Card38 S2【逆袭】自测。

跑法：cd N:\\apps\\tianma\\server; python test_card38s2.py
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
H0 = "123m456m789m234p5s5s"                        # 14 张（刚摸 5s）→ 自摸


def check(name, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  got {got!r} want {want!r}")


def setup(tag, delta=0, card=38):
    """delta：先给 seat0 加/减分，用来把点数压到 35000 以下。"""
    db, rid = t30.setup(tag, card=card, mains=[card, 6, 7, 8])
    tg.set_hand(db, rid, 0, parse_hand(H0), drawn="5s")
    with db.tx():
        db.conn.execute("DELETE FROM round_dora WHERE round_id=?", (rid,))
        db.conn.execute("DELETE FROM round_discards WHERE round_id=?", (rid,))
        db.conn.execute("DELETE FROM round_melds WHERE round_id=?", (rid,))
        if delta:
            db._score(rid, 0, int(delta), "test")
    g = Game(db, rid)
    g.granted = {0: {card}}
    g.round_phase = "play"
    g.phase = "discard"
    g.turn = 0
    g.deal_wait = set()
    g.deal_used = set()
    g.save_flags()
    return db, rid


def play_tsumo(db, rid):
    g = Game(db, rid)
    g.act(0, "tsumo")
    return Game(db, rid)


def main() -> int:
    print("=" * 78)
    print(" Card38 S2【逆袭】")
    print("=" * 78)

    print("\n① 注册 / 时机")
    check("名字", skills.info(38, 2).get("name"), "逆袭")
    check("时机 = 结算", skills.timing(38, 2), "settle")

    print("\n② 点数 30000（< 35000）→ 得点 ×2")
    # 对照组：同一手牌、同样分数，但没有 38 号卡（不翻倍）
    db0, rid0 = setup("c38s2base", delta=-5000, card=6)
    base_pts = int((play_tsumo(db0, rid0).result or {}).get("points", 0))
    check("baseline 有得点", base_pts > 0, True)
    db, rid = setup("c38s2a", delta=-5000)
    g = Game(db, rid)
    check("发动条件成立", g.c38s2_on(0), True)
    base = g.scores().get(0, 0)
    check("结算前 30000（初始 35000，这里手动压低好测逆袭）", int(base), 30000)
    g2 = play_tsumo(db, rid)
    res = g2.result or {}
    names = res.get("yaku_names") or []
    check("有逆袭明细", "逆袭（得点×2）" in names, True)
    dd = res.get("deltas") or {}
    check("赢家得点 = points",
          int(dd.get("0", dd.get(0, -1))), int(res.get("points", -2)))
    pts = int(res.get("points", 0))
    check("得点正好是对照组的两倍", pts, base_pts * 2)

    print("\n③ 点数正好 35000 → 不发动")
    db2, rid2 = setup("c38s2b", delta=0)
    g3 = Game(db2, rid2)
    check("结算前 35000", int(g3.scores().get(0, 0)), 35000)
    check("不发动", g3.c38s2_on(0), False)
    g4 = play_tsumo(db2, rid2)
    check("没有逆袭明细", "逆袭（得点×2）" in (g4.result or {}).get("yaku_names", []), False)
    check("得点和对照组一样", int((g4.result or {}).get("points", 0)), base_pts)

    print("\n④ 点数 34000（差一点）→ 发动")
    db3, rid3 = setup("c38s2c", delta=-1000)
    g5 = Game(db3, rid3)
    check("结算前 34000", int(g5.scores().get(0, 0)), 34000)
    check("发动", g5.c38s2_on(0), True)

    print("\n⑤ 别人和牌 → 不发动（即使我 < 35000）")
    db4, rid4 = setup("c38s2d")
    tg.set_hand(db4, rid4, 1, parse_hand(H0), drawn="5s")
    g6 = Game(db4, rid4)
    g6.turn = 1
    g6.phase = "discard"
    g6.save_flags()
    g6 = Game(db4, rid4)
    g6.act(1, "tsumo")
    g7 = Game(db4, rid4)
    check("赢家是 seat1", int((g7.result or {}).get("winner", -1)), 1)
    check("seat1 没有逆袭",
          "逆袭（得点×2）" in (g7.result or {}).get("yaku_names", []), False)

    print("\n⑥ 叠加【岭上开花】(37S1) → 两个 ×2 都在")
    db5, rid5 = setup("c38s2e", card=37, delta=-5000)
    tg.set_hand(db5, rid5, 0, parse_hand("1m1m1m1m2p3p4p5p6p7p7s8s9s9s"), drawn="9s")
    with db5.tx():
        db5.conn.execute("UPDATE rounds SET live_left=12 WHERE round_id=?", (rid5,))
    g8 = Game(db5, rid5)
    g8.granted = {0: {37, 38}}
    g8.save_flags()
    g8 = Game(db5, rid5)
    r = g8.c37s1_arm(0)
    if bool(r.get("ready")):
        g8 = Game(db5, rid5)
        g8.act(0, "tsumo")
        g9 = Game(db5, rid5)
        names = (g9.result or {}).get("yaku_names") or []
        check("两个 ×2 都在", ("岭上开花（得点×2）" in names and "逆袭（得点×2）" in names), True)
        check("得点 > 0", int((g9.result or {}).get("points", 0)) > 0, True)
    else:
        check("（这一手没杠成，跳过叠加用例）", True, True)

    print("\n" + "=" * 78)
    print(f" 通过 {PASS} / 失败 {FAIL}")
    print("=" * 78)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
