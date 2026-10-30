# -*- coding: utf-8 -*-
"""点燃新规则的专项测试。"""
from __future__ import annotations

import io
import json
import sys

sys.path.insert(0, r'N:\apps\tianma\server')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from game import Game, RuleError  # noqa: E402
import test_game as tg  # noqa: E402

OK = 0
BAD = 0


def check(cond, msg):
    global OK, BAD
    if cond:
        OK += 1
    else:
        BAD += 1
        print("  [FAIL]", msg)


def main():
    db = tg.fresh_db("ignite")
    rid, _m, _u = tg.new_round(db, seed=101)

    # ① 摸牌后不能点燃
    g = Game(db, rid)
    g.granted = {0: {14}}
    g.phase, g.turn = "discard", 0
    g.save_flags()
    g = Game(db, rid)
    check(not g.ignite_can(0), "摸牌后不该能点燃（ignite_can）")
    try:
        g.ignite_activate(0)
        check(False, "摸牌后调用 ignite_activate 应该报错")
    except RuleError as e:
        check("配牌" in str(e), f"报错要说清「只能在配牌阶段」，实际 {e}")

    # ② 配牌阶段摇一次：失败就不能再摇，本小局炸裂不可用
    g = Game(db, rid)
    g.deal_wait = {0}
    g.phase = "deal_skill"
    g.save_flags()
    g = Game(db, rid)
    check(g.ignite_can(0), "配牌阶段应该能点燃")
    G_random = __import__("game").random
    _seq = iter([3, 5])
    G_random.randint = lambda a, b: next(_seq)            # 3/5 → 必失败
    r = g._start_ignite(0, 14, 1)
    check(r["success"] is False, "3/5 应该判失败")
    g = Game(db, rid)
    check(g.ignite_done, "摇过之后 ignite_done 应为 True")
    check(not g.ignite_ok, "失败 → 本小局炸裂不可用")
    check(g.po10_next == 1, f"失败攒 1 点给下一小局，实际 {g.po10_next}")
    check(g.po10_pts == 0, f"本小局不该有点数可用，实际 {g.po10_pts}")
    check(not g.ignite_can(0), "摇过之后不能再摇")
    try:
        g2 = Game(db, rid)
        g2._start_ignite(0, 14, 1)
        check(False, "第二次点燃应该报错")
    except RuleError as e:
        check("摇过" in str(e), f"第二次点燃的报错不对：{e}")

    # ③ 下一小局：攒的点变成可用
    rid2 = db.start_round(db._one("SELECT match_id FROM rounds WHERE round_id=?", (rid,)),
                          "dong", 2, honba=0, dealer_seat=1, seed=102)
    g3 = Game(db, rid2)
    g3.granted = {0: {14}}
    g3.save_flags()
    g4 = Game(db, rid2)
    check(g4.po10_pts == 1 and g4.po10_next == 0,
          f"下一小局应该拿到 1 点、攒的清零，实际 pts={g4.po10_pts} next={g4.po10_next}")

    print(f"\n通过 {OK} / 失败 {BAD}")
    return 1 if BAD else 0


if __name__ == "__main__":
    sys.exit(main())
