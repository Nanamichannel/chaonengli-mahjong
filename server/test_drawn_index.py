# -*- coding: utf-8 -*-
"""state.drawn_index：按物理牌定位「刚摸到的那张」（换牌后牌面会重复，不能按牌面找）"""
from __future__ import annotations

import io
import os
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
    db = tg.fresh_db("didx")
    rid, _m, _u = tg.new_round(db, seed=251)
    hand = ["1m", "1m", "2m", "2m", "3m", "3m", "4p", "5p",
            "6p", "7s", "8s", "dong", "dong", "9m"]
    tg.set_hand(db, rid, 0, hand, drawn="9m")     # 最后一张标成「刚摸到」
    with db.tx():
        db.conn.execute(
            "INSERT INTO round_discards(round_id, seq, seat, wall_seq, tile, called,"
            " is_riichi_tile, face_down) VALUES(?,?,?,?,?,0,0,0)",
            (rid, 500, 1, 9500, "7m"))
    g = Game(db, rid)
    g.granted = {0: {9, 14}}
    g.ignite_ok = True
    g.phase, g.turn = "draw", 0
    g.save_flags()
    g = Game(db, rid)
    st = g.state_for(0)
    check(int(st.get("drawn_index", -9)) == 13,
          f"刚摸到的是第 14 张（下标 13），实际 {st.get('drawn_index')}")
    check(String_ok(st, "drawn") == "9m", f"drawn 应该是 9m，实际 {st.get('drawn')}")

    # 换掉「刚摸到的那张」→ drawn_index 仍然指向它（牌面变成牌河那张）
    r = g.zhalie_swap(0, "9m", 500)
    check(r.get("got") == "7m", f"应该换到 7m，实际 {r}")
    g = Game(db, rid)
    st2 = g.state_for(0)
    check(int(st2.get("drawn_index", -9)) == 13,
          f"换牌后 drawn_index 仍应指向那张物理牌，实际 {st2.get('drawn_index')}")
    check(String_ok(st2, "drawn") == "7m",
          f"换牌后 drawn 应该是换进来的 7m，实际 {st2.get('drawn')}")
    check(list(g.hand(0))[13] == "7m", f"hand[13] 应该是 7m，实际 {list(g.hand(0))[13]}")

    print(f"\n通过 {OK} / 失败 {BAD}")
    return 1 if BAD else 0


def String_ok(st, key):
    v = st.get(key)
    return "" if v is None else str(v)


if __name__ == "__main__":
    sys.exit(main())
