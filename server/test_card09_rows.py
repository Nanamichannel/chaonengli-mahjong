# -*- coding: utf-8 -*-
"""间合：点选阶段就要把「换过的行 / 被鸣走 / 暗置 / 立直牌」排掉（服务端下发列表）"""
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
    db = tg.fresh_db("c09rows")
    rid, _m, _u = tg.new_round(db, seed=121)
    tg.set_hand(db, rid, 0, ["1m", "2m", "3m", "4m", "5m", "6m", "7m", "8m",
                             "1s", "2s", "3s", "4s", "5s"])
    with db.tx():
        # 1 号位牌河 8 张：500..505 = 第 0 行，506..507 = 第 1 行
        tiles = ["9m", "9m", "9p", "9p", "1z", "1z", "8s", "8s"]
        for i, t in enumerate(tiles):
            db.conn.execute(
                "INSERT INTO round_discards(round_id, seq, seat, wall_seq, tile, called,"
                " is_riichi_tile, face_down) VALUES(?,?,?,?,?,0,0,0)",
                (rid, 500 + i, 1, 9500 + i, t))
        # 2 号位：一张暗置、一张立直宣言牌（都不该出现在可换列表里）
        db.conn.execute(
            "INSERT INTO round_discards(round_id, seq, seat, wall_seq, tile, called,"
            " is_riichi_tile, face_down) VALUES(?,?,?,?,?,0,0,1)", (rid, 600, 2, 9600, "9s"))
        db.conn.execute(
            "INSERT INTO round_discards(round_id, seq, seat, wall_seq, tile, called,"
            " is_riichi_tile, face_down) VALUES(?,?,?,?,?,0,1,0)", (rid, 601, 2, 9601, "9s"))
        # 3 号位：被鸣走的一张
        db.conn.execute(
            "INSERT INTO round_discards(round_id, seq, seat, wall_seq, tile, called,"
            " is_riichi_tile, face_down) VALUES(?,?,?,?,?,1,0,0)", (rid, 700, 3, 9700, "9m"))
    g = Game(db, rid)
    g.granted = {0: {9}}
    g.phase, g.turn = "draw", 0
    g.save_flags()

    # ── ① 初始：别家可换 = 1 号位 8 张（0 行 + 1 行）；暗置/立直/被鸣走都没有
    oth = g.card09_targets(0, 2)
    check(oth == [500, 501, 502, 503, 504, 505, 506, 507],
          f"别家可换应该只有 1 号位那 8 张，实际 {oth}")
    own = g.card09_targets(0, 1)
    check(own == [], f"自己牌河是空的，实际 {own}")

    # ── ② 换掉第 0 行的一张 → 整行都不能再换
    tg.set_hand(db, rid, 1, ["1p", "2p", "3p", "4p", "5p", "6p", "7p", "8p",
                             "1z", "1z", "1z", "2z", "2z"])
    g = Game(db, rid)
    g.granted = {0: {9}}
    g.phase, g.turn = "draw", 0
    g.save_flags()
    r = g.card09_swap(0, 2, "1m", 500)
    check(r.get("got") == "9m", f"应该换到 9m，实际 {r}")
    g = Game(db, rid)
    # 换完这一巡就用掉了 —— 下一巡（我这个回合打完牌之后）面板再开时才看行锁
    g.c09_turn = ""
    g.save_flags()
    g = Game(db, rid)
    oth = g.card09_targets(0, 2)
    check(oth == [506, 507],
          f"第 0 行换过之后，整行（500-505）都不该再出现，实际 {oth}")

    # ── ③ state_for 里也下发同样的列表
    st = g.state_for(0)
    check(sorted(int(x) for x in st.get("card09_other_seqs", [])) == [506, 507],
          f"state.card09_other_seqs 不对：{st.get('card09_other_seqs')}")
    check(st.get("card09_own_seqs") == [],
          f"state.card09_own_seqs 不对：{st.get('card09_own_seqs')}")

    # ── ④ 这一巡用过了 → 列表空
    check(g.card09_targets(0, 2) == [506, 507], "下一巡时剩下那一行还是能换")
    g.c09_turn = g._c09_turn_key(0)
    g.save_flags()
    check(g.card09_targets(0, 2) == [], "这一巡用过了 → 不该再给可换列表")

    print(f"\n通过 {OK} / 失败 {BAD}")
    return 1 if BAD else 0


if __name__ == "__main__":
    sys.exit(main())
