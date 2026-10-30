# -*- coding: utf-8 -*-
"""Card38 S1【重整】自测。

跑法：cd N:\\apps\\tianma\\server; python test_card38.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from game import Game, RuleError                     # noqa: E402
import skills                                        # noqa: E402
import test_card30 as t30                            # noqa: E402
import test_game as tg                               # noqa: E402
from tiles import parse_hand                         # noqa: E402

PASS = FAIL = 0
H0 = "1m2m3m4p5p6p7s8s9s1z3z5z7z9m"                 # 14 张（刚摸 9m）


def check(name, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  got {got!r} want {want!r}")


def setup(tag):
    db, rid = t30.setup(tag, card=38, mains=[38, 6, 7, 8])
    tg.set_hand(db, rid, 0, parse_hand(H0), drawn="9m")
    with db.tx():
        db.conn.execute("DELETE FROM round_dora WHERE round_id=?", (rid,))
        db.conn.execute("DELETE FROM round_discards WHERE round_id=?", (rid,))
        db.conn.execute("DELETE FROM round_melds WHERE round_id=?", (rid,))
        db.conn.execute("UPDATE rounds SET live_left=50 WHERE round_id=?", (rid,))
    g = Game(db, rid)
    g.granted = {0: {38}}
    g.dora_revealed = 1                 # 第 1 张已翻 → 接下来是第 2/3/4 张
    g.round_phase = "play"
    g.phase = "discard"
    g.turn = 0
    g.deal_wait = set()
    g.deal_used = set()
    g.save_flags()
    return db, rid


def faces(db, rid, seqs):
    return [str(db.tile_at_seq(rid, s) or "") for s in seqs]


def hand_map(db, rid, seat=0):
    return {int(r["wall_seq"]): str(r["tile"]) for r in db.my_hand(rid, seat)}


def main() -> int:
    print("=" * 78)
    print(" Card38 S1【重整】")
    print("=" * 78)

    print("\n① 注册 / 时机")
    check("名字", skills.info(38, 1).get("name"), "重整")
    check("时机 = 切牌", skills.timing(38, 1), "discard")

    print("\n② 切牌前能发动；能看到接下来 3 张指示牌")
    db, rid = setup("c38a")
    g = Game(db, rid)
    check("能发动", g.c38s1_can(0), True)
    slots = g.c38s1_slots()
    check("3 个槽", len(slots), 3)
    v = g.c38s1_view(0)
    check("view 给 3 张指示牌", len(v.get("dora") or []), 3)
    check("view 给整手牌", len(v.get("hand") or []), 14)
    check("指示牌牌面跟库一致",
          [x["tile"] for x in (v.get("dora") or [])], faces(db, rid, slots))

    print("\n③ 三张都选自手牌：指示牌按顺序换掉，手牌换回原来那三张")
    before = faces(db, rid, slots)
    hm = hand_map(db, rid, 0)
    hs = sorted(hm)[:3]
    picks = [{"kind": "hand", "seq": int(h)} for h in hs]
    want = [hm[int(h)] for h in hs]
    r = g.c38s1_apply(0, picks)
    after = faces(db, rid, slots)
    check("指示牌 = 选中的三张（按顺序）", after, want)
    hm2 = hand_map(db, rid, 0)
    check("手牌张数不变", len(hm2), 14)
    check("手牌那三张换成原指示牌",
          [hm2[int(h)] for h in hs], before)
    check("记了一次性", Game(db, rid).skill_used(0, 38, 1), True)
    check("返回新指示牌", r.get("dora"), want)

    print("\n④ 混合选：指示牌 + 2 张手牌")
    db2, rid2 = setup("c38b")
    g2 = Game(db2, rid2)
    slots2 = g2.c38s1_slots()
    cur = faces(db2, rid2, slots2)
    hm = hand_map(db2, rid2, 0)
    hs = sorted(hm)[:2]
    picks = [{"kind": "dora", "i": 1},
             {"kind": "hand", "seq": int(hs[0])},
             {"kind": "hand", "seq": int(hs[1])}]
    g2.c38s1_apply(0, picks)
    got = faces(db2, rid2, slots2)
    check("第 1 位 = 原来第 2 张", got[0], cur[1])
    check("第 2 位 = 手牌 a", got[1], hm[int(hs[0])])
    check("第 3 位 = 手牌 b", got[2], hm[int(hs[1])])
    hm2 = hand_map(db2, rid2, 0)
    check("被顶下来的两张回手牌", [hm2[int(hs[0])], hm2[int(hs[1])]],
          [cur[0], cur[2]])

    print("\n⑤ 选重复 / 张数不对 → 报错")
    db3, rid3 = setup("c38c")
    g3 = Game(db3, rid3)
    hs = sorted(hand_map(db3, rid3, 0))[:2]
    try:
        g3.c38s1_apply(0, [{"kind": "hand", "seq": int(hs[0])},
                           {"kind": "hand", "seq": int(hs[0])},
                           {"kind": "hand", "seq": int(hs[1])}])
        check("重复选被拒", False, True)
    except RuleError:
        check("重复选被拒", True, True)
    try:
        g3.c38s1_apply(0, [{"kind": "hand", "seq": int(hs[0])}])
        check("张数不对被拒", False, True)
    except RuleError:
        check("张数不对被拒", True, True)
    check("失败不消耗", Game(db3, rid3).skill_used(0, 38, 1), False)

    print("\n⑥ 不是我的回合 / 已经翻满 4 张 → 不能发动")
    g4 = Game(db3, rid3)
    g4.turn = 1
    g4.save_flags()
    check("不是我的回合", Game(db3, rid3).c38s1_can(0), False)
    g5 = Game(db3, rid3)
    g5.turn = 0
    g5.dora_revealed = 2                # 只剩 2 张可翻
    g5.save_flags()
    check("不够 3 张可翻", Game(db3, rid3).c38s1_can(0), False)

    print("\n" + "=" * 78)
    print(f" 通过 {PASS} / 失败 {FAIL}")
    print("=" * 78)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
