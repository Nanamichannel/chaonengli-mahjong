# -*- coding: utf-8 -*-
"""海神：配牌开启 → 整局强制换牌；不开启 → 整局无关"""
from __future__ import annotations

import io
import json
import os
import sys

sys.path.insert(0, r'N:\apps\tianma\server')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import api_cli  # noqa: E402
from game import Game, RuleError  # noqa: E402
import test_game as tg  # noqa: E402

OK = 0
BAD = 0
HAND = ["1m", "2m", "3m", "4m", "5m", "6m", "7m", "8m", "9m", "1p", "2p", "3p", "4p"]


def check(cond, msg):
    global OK, BAD
    if cond:
        OK += 1
    else:
        BAD += 1
        print("  [FAIL]", msg)


def dbpath(tag):
    return os.path.join(r'N:\apps\tianma\server', 'data', f'_test_{tag}.db')


def call(path, req):
    return api_cli.handle(req, path)


def set_orders(db, orders):
    body = {"seats": [{"ready": False, "hand": [], "picks": [], "order": list(o)}
                      for o in orders], "phase": "playing"}
    with db.tx():
        db.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('lobby_state', ?)",
                        (json.dumps(body, ensure_ascii=False),))


def setup(tag, seed):
    db = tg.fresh_db(tag)
    set_orders(db, [[12, 12, 12, 12, 3], [17, 17, 17, 17, 4],
                    [1, 2, 3, 4, 5], [6, 7, 8, 9, 10]])
    rid, _m, _u = tg.new_round(db, seed=seed)
    tg.set_hand(db, rid, 0, HAND)
    return db, rid


def main():
    # ── ① 配牌开启 ────────────────────────────────────────
    db, rid = setup("hsdeal", 171)
    g = Game(db, rid)
    g.granted = {0: {12}, 1: {17}}
    g.phase, g.turn = "deal_skill", 0
    g.deal_wait = {0}
    g.save_flags()
    r = call(dbpath("hsdeal"), {"op": "haishin_start", "seat": 0, "round_id": rid})
    check(bool(r.get("need_kangpo")), f"配牌开启海神要先问看破，实际 {r}")
    call(dbpath("hsdeal"), {"op": "kangpo_answer", "seat": 1, "use": False, "round_id": rid})
    g = Game(db, rid)
    check(g.haishin_on is True, "配牌开启后 haishin_on 应该 True")
    check(g.state_for(0).get("haishin_on") is True, "state 要下发 haishin_on")
    g.deal_wait = set()
    g.phase = "draw"
    g.save_flags()

    # ── ② 别人摸到万子 → 进 haishin 阶段、强制交换 ────────
    tg.set_next_draw(db, rid, "5m")
    g = Game(db, rid)
    g.turn = 1
    g.phase = "draw"
    g.save_flags()
    g = Game(db, rid)
    ev = g.advance()
    g = Game(db, rid)
    check(g.phase == "haishin", f"别人摸万子应该进借牌阶段，实际 {g.phase}")
    check(int((g.haishin_offer or {}).get("owner", -1)) == 0,
          f"应该问 0 号位，实际 {g.haishin_offer}")
    try:
        g.haishin_give(0, "")
        check("不能跳过", False)
    except RuleError as e:
        check("不能跳过", "必须选一张手牌" in str(e))
    r = g.haishin_give(0, "1p")
    check(r.get("got") == "5m", f"应该换到 5m，实际 {r}")
    g = Game(db, rid)
    check(g.phase in ("draw", "discard"), f"换完该正常继续，实际 {g.phase}")
    check("5m" in g.hand(0), f"手里应该有 5m，实际 {g.hand(0)}")

    # ── ③ 不开启 → 整局无关 ───────────────────────────────
    db2, rid2 = setup("hsdeal2", 172)
    g2 = Game(db2, rid2)
    g2.granted = {0: {12}, 1: {17}}
    g2.phase, g2.turn = "draw", 1        # 别人摸牌
    g2.haishin_on = False
    g2.save_flags()
    tg.set_next_draw(db2, rid2, "5m")
    g2 = Game(db2, rid2)
    g2.advance()
    g2 = Game(db2, rid2)
    check(g2.phase != "haishin", f"没开启就不该进借牌阶段，实际 {g2.phase}")
    check(g2.haishin_offer is None, "没开启不该有 offer")
    check(g2.haishin_can(0) is False, "没开启 → 整局用不了")

    # ── ④ 询问已经结束（offer 被清）→ 幂等返回，不抛错 ──────
    g = Game(db, rid)
    g.haishin_offer = None
    g.save_flags()
    g = Game(db, rid)
    r = g.haishin_give(0, "1m")
    check(bool(r.get("already")), f"offer 没了应该返回 already，实际 {r}")
    check(r.get("got") == "", "already 时不该报换到的牌")

    print(f"\n通过 {OK} / 失败 {BAD}")
    return 1 if BAD else 0


if __name__ == "__main__":
    sys.exit(main())
