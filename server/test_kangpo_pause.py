# -*- coding: utf-8 -*-
"""看破挂起时，step/advance/act 都不许推进对局（draw 那个 op 已经删掉了）。"""
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


def call(path, req):
    return api_cli.handle(req, path)


def main():
    db = tg.fresh_db("kp_pause")
    rid, _m, _u = tg.new_round(db, seed=61)
    path = os.path.join(r'N:\apps\tianma\server', 'data', '_test_kp_pause.db')

    # 造一个「看破正挂着」的状态：0 号位要发动降神，1 号位持有看破
    g = Game(db, rid)
    g.granted = {0: {7}, 1: {17}}
    g.oracle = {0: {"suit": "m", "on": True, "dice": 7}}
    g.phase, g.turn = "draw", 0
    g.save_flags()
    g = Game(db, rid)
    g.kangpo_gate(0, 7, 1, op="oracle_pick", payload={"tile": "1m"})
    g = Game(db, rid)
    check(g.kangpo_pending is not None, "夹具：看破应该处于挂起状态")

    before = (str(g.phase), int(g.turn if g.turn is not None else -1),
              len(g.hand(0)), len(g.hand(1)))

    for op in ("step", "advance", "act"):
        extra = {"action": "discard", "tile": "1m"} if op == "act" else {}
        r = call(path, {"op": op, "seat": 1, "round_id": rid, **extra})
        g2 = Game(db, rid)
        after = (str(g2.phase), int(g2.turn if g2.turn is not None else -1),
                 len(g2.hand(0)), len(g2.hand(1)))
        check(after == before, f"{op} 不该推进对局，{before} → {after}")
        check(bool(r.get("waiting_kangpo")), f"{op} 应该回 waiting_kangpo，实际 {r.get('waiting_kangpo')}")

    r = call(path, {"op": "act", "seat": 0, "action": "discard", "tile": "1m",
                    "round_id": rid})
    g3 = Game(db, rid)
    check(len(g3.discards(0)) == 0, "看破挂起时不该能打牌")
    check(bool(r.get("waiting_kangpo")), "act 也应该回 waiting_kangpo")

    # 看破回答（放行）之后就恢复：降神的结算照原样重放
    r2 = call(path, {"op": "kangpo_answer", "seat": 1, "use": False, "round_id": rid})
    check(bool(r2.get("ok")), f"看破放行应该成功，实际 {r2.get('error')}")
    g4 = Game(db, rid)
    check(g4.kangpo_pending is None, "放行之后挂起状态应该清掉")
    r3 = call(path, {"op": "step", "seat": 0, "round_id": rid})
    check(not bool(r3.get("waiting_kangpo")), "放行之后 step 应该恢复正常")

    print(f"\n通过 {OK} / 失败 {BAD}")
    return 1 if BAD else 0


if __name__ == "__main__":
    sys.exit(main())
