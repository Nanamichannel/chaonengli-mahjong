# -*- coding: utf-8 -*-
"""Card36 S2【故意】自测。

跑法：cd N:\\apps\\tianma\\server; python test_card36s2.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from game import C26_N0, Game, RuleError             # noqa: E402
import skills                                        # noqa: E402
import test_card30 as t30                            # noqa: E402
import test_game as tg                               # noqa: E402
from tiles import parse_hand                         # noqa: E402

PASS = FAIL = 0

# seat0 手里 14 张（刚摸 5s）；打 5s 之后 seat1 的手牌正好成和牌型
H0 = "123m456m789m234p55s5s"
H1 = "123m456m789m234p5s"
H2 = "1m4m7m2p5p8p2s5s8s2z3z4z6z"
H3 = "3m6m9m3p6p9p3s6s9s1z2z3z5z"


def check(name, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  got {got!r} want {want!r}")


def setup(tag, mains=None):
    db, rid = t30.setup(tag, card=36, mains=mains or [36, 6, 7, 8])
    for s, h in enumerate((H0, H1, H2, H3)):
        tg.set_hand(db, rid, s, parse_hand(h), drawn="5s" if s == 0 else None)
    with db.tx():
        db.conn.execute("DELETE FROM round_dora WHERE round_id=?", (rid,))
        db.conn.execute("DELETE FROM round_discards WHERE round_id=?", (rid,))
        db.conn.execute("DELETE FROM round_melds WHERE round_id=?", (rid,))
    g = Game(db, rid)
    g.granted = {0: {36}}
    g.round_phase = "play"
    g.phase = "discard"
    g.turn = 0
    g.deal_wait = set()
    g.deal_used = set()
    g.save_flags()
    return db, rid


def main() -> int:
    print("=" * 78)
    print(" Card36 S2【故意】")
    print("=" * 78)

    print("\n① 注册 / 时机")
    check("名字", skills.info(36, 2).get("name"), "故意")
    check("时机 = 切牌", skills.timing(36, 2), "discard")

    print("\n② 切牌前能发动；本小局一次")
    db, rid = setup("c36s2a")
    g = Game(db, rid)
    check("能发动", g.c36s2_can(0), True)
    r = g.c36s2_arm(0)
    check("开启", int(r.get("on", -1)), 0)
    g2 = Game(db, rid)
    check("开着", int(g2.c36s2_on), 0)
    check("state.c36.s2", bool((g2.state_for(0).get("c36") or {}).get("s2")), True)
    check("记了一次性", g2.skill_used(0, 36, 2), True)
    check("不能再发动", g2.c36s2_can(0), False)

    print("\n③ 打出的牌让别人成和牌型 → 立刻结算，我付 1000")
    g2._do_discard(0, tile="5s")
    g3 = Game(db, rid)
    res = g3.result or {}
    check("本局结束", res.get("result"), "ron")
    check("赢家是下家", int(res.get("winner", -1)), 1)
    check("放铳的是我", int(res.get("loser", -1)), 0)
    check("1000 点", int(res.get("points", 0)), 1000)
    # 从库里读回来的 deltas 键是字符串
    dd = res.get("deltas") or {}
    check("收付 ±1000", [int(dd.get("0", dd.get(0, 0))),
                        int(dd.get("1", dd.get(1, 0)))], [-1000, 1000])
    check("明细写「故意」", (res.get("yaku_names") or [""])[0], "故意")
    check("状态清掉", int(Game(db, rid).c36s2_on), -1)

    print("\n④ 多家都能成 → 下家优先")
    db2, rid2 = setup("c36s2b")
    tg.set_hand(db2, rid2, 2, parse_hand("123m456m789m234p5s"))    # 对家也能和 5s
    g4 = Game(db2, rid2)
    g4.c36s2_arm(0)
    g4._do_discard(0, tile="5s")
    check("取下家", int((Game(db2, rid2).result or {}).get("winner", -1)), 1)

    print("\n⑤ 只看「4 面子 + 1 雀头」：七对子不算")
    db3, rid3 = setup("c36s2c")
    tg.set_hand(db3, rid3, 1, parse_hand("1m1m2p2p3p3p4s4s5s5s6s6s7z"))
    g5 = Game(db3, rid3)
    g5.c36s2_arm(0)
    g5._do_discard(0, tile="5s")
    g6 = Game(db3, rid3)
    check("七对子不结算", bool(g6.result), False)
    check("状态照样清掉", int(g6.c36s2_on), -1)

    print("\n⑥ 不判役 / 不振听：无役也照付")
    db4, rid4 = setup("c36s2d")
    tg.set_hand(db4, rid4, 1, parse_hand("123m456m789m234p5s"))
    g7 = Game(db4, rid4)
    g7.c36s2_arm(0)
    g7.armed_skill = None
    g7._do_discard(0, tile="5s")
    check("照样结算", int((Game(db4, rid4).result or {}).get("winner", -1)), 1)

    print("\n⑦ 天梯特判：没记录过 → 1000 记成第一次")
    db5, rid5 = setup("c36s2e", mains=[36, 26, 7, 8])   # seat1 拿 26 号卡
    g8 = Game(db5, rid5)
    g8.c26s2_on.add(1)
    g8.c26_n[1] = C26_N0                  # 天梯初始 n
    g8.c26_last[1] = -1                   # 还没记录过点数
    g8.save_flags()
    g8 = Game(db5, rid5)
    g8.c36s2_arm(0)
    g8._do_discard(0, tile="5s")
    g9 = Game(db5, rid5)
    check("记成 1000", int(g9.c26_last.get(1, -999)), 1000)
    check("天梯次数 +1（和正常和牌一样）", int(g9.c26_n.get(1, -1)), C26_N0 + 1)
    check("没有触发天梯罚（不是流局）",
          (g9.result or {}).get("result"), "ron")

    print("\n⑧ 天梯特判：已经记过 → 打断，天梯从 0 开始")
    db6, rid6 = setup("c36s2f", mains=[36, 26, 7, 8])
    g10 = Game(db6, rid6)
    g10.c26s2_on.add(1)
    g10.c26_n[1] = 3
    g10.c26_last[1] = 8000
    g10.save_flags()
    g10 = Game(db6, rid6)
    g10.c36s2_arm(0)
    g10._do_discard(0, tile="5s")
    g11 = Game(db6, rid6)
    check("天梯回到初始值", int(g11.c26_n.get(1, -1)), C26_N0)
    check("成绩清空", int(g11.c26_last.get(1, -999)), -1)
    check("照样正常结算", (g11.result or {}).get("result"), "ron")

    print("\n" + "=" * 78)
    print(f" 通过 {PASS} / 失败 {FAIL}")
    print("=" * 78)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
