# -*- coding: utf-8 -*-
"""state 字段与客户端对齐：客户端读的字段服务端必须真的给（防回退）"""
from __future__ import annotations

import io
import sys

sys.path.insert(0, r'N:\apps\tianma\server')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

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


def main():
    db = tg.fresh_db("statef")
    rid, _m, _u = tg.new_round(db, seed=141)
    g = Game(db, rid)
    g.granted = {0: {9, 14, 15, 16, 19, 21, 22}}
    g.phase, g.turn = "draw", 0
    g.gift = {0: 2}
    g.ignite_ok = True
    g.ignite_done = True
    g.save_flags()
    with db.tx():
        db.conn.execute(
            "INSERT INTO round_discards(round_id, seq, seat, wall_seq, tile, called,"
            " is_riichi_tile, face_down) VALUES(?,?,?,?,?,0,0,0)",
            (rid, 500, 1, 9500, "3p"))
    st = Game(db, rid).state_for(0)

    # 客户端 main.gd 读、以前服务端没给的三项
    for k in ("gift_can", "ignite_done", "drawn_count",
              "card09_own_seqs", "card09_other_seqs", "kangpo_wait"):
        check(k in st, f"state 少了 {k}（客户端会读到一个默认值 → 功能静默失效）")

    check(st.get("gift_can") is True, f"打过两张、摸牌前 → 馈赠应该可用，实际 {st.get('gift_can')}")
    check(st.get("ignite_done") is True, f"ignite_done 应该是 True，实际 {st.get('ignite_done')}")
    check(int(st.get("drawn_count", 0)) == len(g.hand(0)),
          f"drawn_count 应该等于手牌张数，实际 {st.get('drawn_count')}")

    # 服务端不再给的旧字段（客户端不该再依赖）
    check("claim" not in st, "state 里没有 claim：鸣牌选项走 legal（客户端已核对）")

    print(f"\n通过 {OK} / 失败 {BAD}")
    return 1 if BAD else 0


if __name__ == "__main__":
    sys.exit(main())
