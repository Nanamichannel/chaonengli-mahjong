# -*- coding: utf-8 -*-
"""炸裂：点燃成功才换牌；点燃没成功 → 明确报错（不再「外层 ok 内层失败」）"""
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
HAND = ["1m", "2m", "3m", "4p", "5p", "6p", "7s", "8s", "9s", "1p", "1p", "1p", "5s"]


def check(cond, msg):
    global OK, BAD
    if cond:
        OK += 1
    else:
        BAD += 1
        print("  [FAIL]", msg)


def setup(tag, seed, ignite):
    path = os.path.join(r'N:\apps\tianma\server', 'data', f'_test_{tag}.db')
    db = tg.fresh_db(tag)
    rid, _m, _u = tg.new_round(db, seed=seed)
    tg.set_hand(db, rid, 0, HAND)
    with db.tx():
        db.conn.execute(
            "INSERT INTO round_discards(round_id, seq, seat, wall_seq, tile, called,"
            " is_riichi_tile, face_down) VALUES(?,?,?,?,?,0,0,0)",
            (rid, 500, 1, 9500, "7m"))
    g = Game(db, rid)
    g.granted = {0: {14}}
    g.ignite_ok = ignite
    g.ignite_done = True
    g.phase, g.turn = "draw", 0
    g.save_flags()
    return db, rid, path


def main():
    # ── ① 点燃成功 → 真的换牌 + 这一巡不能再炸
    db, rid, path = setup("zlf", 131, True)
    g = Game(db, rid)
    check(g.zhalie_can(0), "点燃成功 → 应该能炸")
    r = api_cli.handle({"op": "zhalie_swap", "seat": 0, "hand": "1m", "river": 500,
                        "round_id": rid}, path)
    check(bool(r.get("ok")), f"应该成功，实际 {r.get('error')}")
    check((r.get("zhalie") or {}).get("got") == "7m",
          f"应该换到 7m，实际 {r.get('zhalie')}")
    g = Game(db, rid)
    check("7m" in g.hand(0) and "1m" not in g.hand(0), f"手牌没变：{g.hand(0)}")
    check(not g.zhalie_can(0), "同一巡不能再炸")

    # ── ② 点燃没成功 → 明确报错（ok=False + 能看懂的 error）
    db2, rid2, path2 = setup("zlf2", 132, False)
    g = Game(db2, rid2)
    check(not g.zhalie_can(0), "点燃没成功 → 不该能炸")
    r = api_cli.handle({"op": "zhalie_swap", "seat": 0, "hand": "1m", "river": 500,
                        "round_id": rid2}, path2)
    check(not bool(r.get("ok")), f"应该失败，实际 {r.get('ok')}")
    check("点燃" in str(r.get("error", "")), f"报错要说清楚是点燃的问题：{r.get('error')}")
    g = Game(db2, rid2)
    check("1m" in g.hand(0), f"失败时不该换牌：{g.hand(0)}")

    print(f"\n通过 {OK} / 失败 {BAD}")
    return 1 if BAD else 0


if __name__ == "__main__":
    sys.exit(main())
