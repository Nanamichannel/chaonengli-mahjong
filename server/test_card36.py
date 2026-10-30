# -*- coding: utf-8 -*-
"""Card36 S1【思路】自测。

跑法：cd N:\\apps\\tianma\\server; python test_card36.py
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


def check(name, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  got {got!r} want {want!r}")


def setup(tag):
    """seat1 拿 36 号卡，其余座位拿 6/7/8。"""
    db, rid = t30.setup(tag, card=36, mains=[6, 36, 7, 8])
    g = Game(db, rid)
    g.granted = {1: {36}}          # t30.setup 默认给 seat0 发了「传承」→ 这里改成 seat1
    g.round_phase = "play"
    g.phase = "discard"
    g.turn = 0
    g.deal_wait = set()
    g.deal_used = set()
    g.save_flags()
    return db, rid


def on_of(seat, db, rid):
    return (Game(db, rid).state_for(seat).get("c36") or {}).get("on", [])


def main() -> int:
    print("=" * 78)
    print(" Card36 S1【思路】")
    print("=" * 78)

    print("\n① 注册 / 时机")
    check("名字", skills.info(36, 1).get("name"), "思路")
    check("时机 = 任意（跟着别人的发动走）", skills.timing(36, 1), "any")
    check("不在配牌技能清单里", (36, 1) in skills.deal_skills(), False)

    print("\n② 别人宣告技能 → 我看到他的手牌")
    db, rid = setup("c36a")
    g = Game(db, rid)
    check("seat1 持有这张卡", g.c36s1_owns(1), True)
    check("seat0 没有这张卡", g.c36s1_owns(0), False)
    g.c36s1_touch(0)                       # seat0 宣告技能
    st = Game(db, rid).state_for(1)
    rh = st.get("reveal_hands") or []
    check("看到了 seat0", [int(x.get("seat", -1)) for x in rh], [0])
    check("给的是整手牌", len((rh[0].get("tiles") or [])), 13)
    check("state.c36.on", (st.get("c36") or {}).get("on"), [0])
    check("别人看不到我这份", (Game(db, rid).state_for(2).get("reveal_hands")), [])

    print("\n③ 看破 / 封堵的询问节点也会触发（kangpo_gate）")
    g2 = Game(db, rid)
    g2.kangpo_gate(2, 7, 1)                # seat2 宣告降神
    check("多了一家", on_of(1, db, rid), [0, 2])

    print("\n④ 多家同时宣告 → 两家都看得到（互不覆盖）")
    st3 = Game(db, rid).state_for(1)
    seats = [int(x.get("seat", -1)) for x in (st3.get("reveal_hands") or [])]
    check("两家都在", seats, [0, 2])
    check("各自都有牌",
          all(len(x.get("tiles") or []) >= 10 for x in (st3.get("reveal_hands") or [])), True)

    print("\n⑤ 我打出一张牌 → 全部失效")
    tg.set_hand(db, rid, 1, parse_hand("123m456m789m234p5z3s"), drawn="3s")
    g4 = Game(db, rid)
    g4.turn = 1
    g4.phase = "discard"
    g4.save_flags()
    g4 = Game(db, rid)
    g4._do_discard(1, tile="3s")
    check("打牌后清空", on_of(1, db, rid), [])
    check("reveal_hands 也空了", (Game(db, rid).state_for(1).get("reveal_hands")), [])

    print("\n⑥ 不限次数：再宣告一次又能看到")
    g5 = Game(db, rid)
    g5.c36s1_touch(3)
    check("再次生效", on_of(1, db, rid), [3])

    print("\n⑦ 厄运静默期内无效")
    g6 = Game(db, rid)
    g6.c36s1_clear(1)
    g6.c34_by = 2
    g6.c34_left = 3                        # seat1 在静默期
    g6.save_flags()
    g6 = Game(db, rid)
    g6.c36s1_touch(0)
    check("静默期看不到", on_of(1, db, rid), [])

    print("\n⑧ 宣告者自己的牌不会露给自己那一家")
    g7 = Game(db, rid)
    g7.c36s1_touch(1)                      # seat1 自己宣告
    check("自己不看自己", on_of(1, db, rid), [])

    print("\n" + "=" * 78)
    print(f" 通过 {PASS} / 失败 {FAIL}")
    print("=" * 78)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
