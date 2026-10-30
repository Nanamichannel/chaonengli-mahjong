# -*- coding: utf-8 -*-
"""看破时机 + 立直后技能限制 自测

1. 降神(7-1) 是「多步」技能：op=skill 那一步不被看破拦（只是开面板）；
   真正的结算 op=oracle_pick 才问看破。
2. 被挡下的那次请求（op + tile）要记下来，放行后按原样重放。
3. 立直之后，会改动自己手牌的技能 op 一律拒绝；降神这类不动手牌的照旧可用。
"""
from __future__ import annotations

import io
import os
import sys

sys.path.insert(0, r'N:\apps\tianma\server')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import api_cli  # noqa: E402
from game import Game  # noqa: E402
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


def dbpath(tag):
    return os.path.join(r'N:\apps\tianma\server', 'data', f'_test_{tag}.db')


def call(path, req):
    return api_cli.handle(req, path)


def main():
    # ── ① 降神的发动点 = 配牌（op=skill 7-1）→ 那一步就问看破 ─────────
    check(api_cli._GATE_AT_CONFIRM == set(), "没有「只开面板」的技能了")

    db = tg.fresh_db("kp1")
    rid, _m, _u = tg.new_round(db, seed=31)
    g = Game(db, rid)
    g.granted = {0: {7}, 1: {17}}
    g.phase, g.turn = "discard", 0
    g.save_flags()

    r = call(dbpath("kp1"), {"op": "deal_skill", "seat": 0,
                    "action": "use", "card": 7, "skill": 1,
                             "round_id": rid})
    check(bool(r.get("need_kangpo")), f"降神应该在配牌那一步问看破，实际 {r}")
    st_owner = (call(dbpath("kp1"), {"op": "state", "seat": 1,
                                     "round_id": rid}).get("state") or {})
    ask = st_owner.get("kangpo_ask") or {}
    check(int(ask.get("owner", -1)) == 1, f"应该问 1 号位（持有看破），实际 {ask}")
    check((int(ask.get("card", 0)), int(ask.get("skill", 0))) == (7, 1),
          f"要问的是 7-1，实际 {ask}")

    # ── ② 放行后：配牌技能记进 kangpo_once，之后 oracle_pick 不再问 ────
    call(dbpath("kp1"), {"op": "kangpo_answer", "seat": 1, "use": False, "round_id": rid})
    g = Game(db, rid)
    check("0:7:1" in g.kangpo_once, f"配牌问过要记下来，实际 {g.kangpo_once}")
    check("0:14:2" not in g.kangpo_once, "别的技能不该被记")
    g.oracle = {0: {"suit": "m", "on": True, "dice": 7}}
    tg.set_hand(db, rid, 1, ["1m", "2m", "3m", "4p", "5p", "6p", "7s", "8s",
                             "9s", "1p", "1p", "1p", "5s"])
    g.phase, g.turn = "draw", 0
    g.save_flags()
    r = call(dbpath("kp1"), {"op": "oracle_pick", "seat": 0, "tile": "1m",
                             "round_id": rid})
    check(not bool(r.get("need_kangpo")),
          f"配牌已经问过 → oracle_pick 不该再问，实际 {r.get('need_kangpo')}")

    # ── ③ 放行后：询问清掉、降神真的执行 ─────────────────────────────
    g = Game(db, rid)
    check(g.kangpo_ask is None and g.kangpo_pending is None, "放行后询问应该清掉")
    check(str(g.oracle.get(0, {}).get("suit", "")) == "m",
          f"放行后降神应该真的掷了花色，实际 {g.oracle}")

    # ── ④ 立直之后：改手牌的技能被拒；降神仍可用 ──────────────────────
    db2 = tg.fresh_db("kp2")
    rid2, _m2, _u2 = tg.new_round(db2, seed=32)
    g = Game(db2, rid2)
    g.granted = {0: set(range(1, 24))}
    g.yiding = set()
    with db2.tx():
        db2.conn.execute("INSERT OR REPLACE INTO round_riichi(round_id, seat) VALUES(?,?)",
                         (rid2, 0))
    g.oracle = {0: {"suit": "m", "on": True, "dice": 7}}
    g.phase, g.turn = "discard", 0
    g.save_flags()
    for op, extra in (("zhalie_swap", {"hand_tile": "1m", "river_seq": -1}),
                      ("haishin_give", {"hand_tile": ""}),
                      ("card11_swap", {"hand_tile": "1m", "idx": 0})):
        r = call(dbpath("kp2"), dict({"op": op, "seat": 0, "round_id": rid2}, **extra))
        check(not bool(r.get("ok")) and "立直" in str(r.get("error", "")),
              f"立直后 {op} 应该被拒，实际 {r.get('ok')} / {r.get('error')}")
    r = call(dbpath("kp2"), {"op": "oracle_toggle", "seat": 0, "round_id": rid2})
    check(bool(r.get("ok")), f"立直后降神开关不该被这条规则拦，实际 {r.get('error')}")

    print(f"\n通过 {OK} / 失败 {BAD}")
    return 1 if BAD else 0


if __name__ == "__main__":
    sys.exit(main())
