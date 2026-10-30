# -*- coding: utf-8 -*-
"""间合攻/守：每个自己的回合只能用一次。"""
from __future__ import annotations

import io
import sys

sys.path.insert(0, r'N:\apps\tianma\server')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from game import Game, RuleError  # noqa: E402
from tiles import parse_hand  # noqa: E402
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
    db = tg.fresh_db("c09once")
    rid, _m, _u = tg.new_round(db, seed=91)
    tg.set_hand(db, rid, 0, parse_hand("123m456p789s1234s"), drawn="4s")
    wall = db._rows("SELECT seq FROM round_wall WHERE round_id=? ORDER BY seq LIMIT 4", (rid,))
    with db.tx():
        # 自己的河 + 别家的河 各一张
        db.conn.execute(
            "INSERT OR REPLACE INTO round_discards(round_id, seat, seq, wall_seq, tile,"
            " called, is_riichi_tile, face_down, is_tsumogiri) VALUES(?,?,?,?,?,0,0,0,1)",
            (rid, 0, 500, int(wall[0]["seq"]), "5p"))
        db.conn.execute(
            "INSERT OR REPLACE INTO round_discards(round_id, seat, seq, wall_seq, tile,"
            " called, is_riichi_tile, face_down, is_tsumogiri) VALUES(?,?,?,?,?,0,0,0,1)",
            (rid, 1, 501, int(wall[1]["seq"]), "6p"))
        db.conn.execute("UPDATE round_wall SET tile='5p' WHERE round_id=? AND seq=?",
                        (rid, int(wall[0]["seq"])))
        db.conn.execute("UPDATE round_wall SET tile='6p' WHERE round_id=? AND seq=?",
                        (rid, int(wall[1]["seq"])))

    g = Game(db, rid)
    g.granted = {0: {9}}
    g.phase, g.turn = "draw", 0
    g.save_flags()
    g = Game(db, rid)
    check(g.card09_can(0), "摸牌前应该能发动间合")

    hand = g.hand(0)[0]
    g.card09_swap(0, 1, hand, 500)                  # 用自己的河
    g = Game(db, rid)
    check(not g.card09_can(0), "同一回合用掉一次之后，不能再发动（用户口径）")

    # 硬来也要被拒
    try:
        Game(db, rid).card09_swap(0, 2, Game(db, rid).hand(0)[0], 501)
        check(False, "同一回合第二次应该被拒")
    except RuleError as e:
        check("一次" in str(e) or "回合" in str(e), f"拒绝理由要说清楚，实际：{e}")

    # 下一巡（我打出一张之后）恢复
    g = Game(db, rid)
    g.phase, g.turn = "discard", 0
    g.save_flags()
    g = Game(db, rid)
    g.act(0, "discard", tile=str(g.hand(0)[0]))
    g = Game(db, rid)
    g.phase, g.turn = "draw", 0
    g.save_flags()
    g = Game(db, rid)
    check(g.card09_can(0), "到了下一巡应该又能发动")

    print(f"\n通过 {OK} / 失败 {BAD}")
    return 1 if BAD else 0


if __name__ == "__main__":
    sys.exit(main())
