# -*- coding: utf-8 -*-
"""一定和牌的新结算：先找「谁手里有我的铳牌」→ 他出铳；都没有 → 自摸。"""
from __future__ import annotations

import io
import sys

sys.path.insert(0, r'N:\apps\tianma\server')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from game import Game  # noqa: E402
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


def build(tag, others_tiles, seed):
    db = tg.fresh_db(tag)
    rid, _m, _u = tg.new_round(db, seed=seed)
    # 我：4 副露 + 单骑 9p（摸到 9p，切了就听 9p）
    tg.set_hand(db, rid, 0, parse_hand("123m456p789s111p99p"), drawn="9p")
    for seat, tiles in others_tiles.items():
        tg.set_hand(db, rid, seat, tiles)
    g = Game(db, rid)
    g.yiding = {0}
    g.phase, g.turn = "discard", 0
    g.save_flags()
    return db, rid


def main():
    # ① 下家（1 号位）手里有 9p → 他出铳
    db, rid = build("yd1", {
        1: parse_hand("9p") + ["1m", "2m", "3m", "4p", "5p", "6p", "7s", "8s", "9s",
                               "2p", "2p", "2p"],
        2: parse_hand("1m2m3m4p5p6p7s8s9s1p1p1p2s"),
        3: parse_hand("1m2m3m4p5p6p7s8s9s1p1p1p3s"),
    }, seed=51)
    g = Game(db, rid)
    ev = g.yiding_declare(0, "9p")     # 一定和牌：主动宣言
    row = db._row("SELECT result, winner_seat, loser_seat FROM rounds WHERE round_id=?",
                  (rid,)) or {}
    res = {"result": row.get("result"), "winner": row.get("winner_seat"),
           "loser": row.get("loser_seat")}
    print("① 结果：", res.get("result"), "winner", res.get("winner"), "loser", res.get("loser"))
    check(int(res.get("winner", -1)) == 0, f"赢的应该是我，实际 {res.get('winner')}")
    check(int(res.get("loser", -2)) == 1, f"出铳的应该是下家 1 号位，实际 {res.get('loser')}")
    check(str(res.get("result")) == "ron", f"应该按荣和结算，实际 {res.get('result')}")

    # ② 三家都没有我的铳牌 → 自摸
    db2, rid2 = build("yd2", {
        1: parse_hand("1m2m3m4p5p6p7s8s9s1p1p1p2s"),
        2: parse_hand("1m2m3m4p5p6p7s8s9s1p1p1p3s"),
        3: parse_hand("1m2m3m4p5p6p7s8s9s1p1p1p4s"),
    }, seed=52)
    g2 = Game(db2, rid2)
    ev2 = g2.yiding_declare(0, "9p")
    row2 = db2._row("SELECT result, winner_seat, loser_seat FROM rounds WHERE round_id=?",
                    (rid2,)) or {}
    res2 = {"result": row2.get("result"), "winner": row2.get("winner_seat"),
            "loser": row2.get("loser_seat")}
    print("② 结果：", res2.get("result"), "winner", res2.get("winner"), "loser", res2.get("loser"))
    check(int(res2.get("winner", -1)) == 0, f"赢的应该是我，实际 {res2.get('winner')}")
    check(res2.get("loser") is None or res2.get("loser") == -1,
          f"没人有铳牌 → 应该自摸（loser 为空），实际 {res2.get('loser')}")
    check(str(res2.get("result")) == "tsumo", f"应该按自摸结算，实际 {res2.get('result')}")

    print(f"\n通过 {OK} / 失败 {BAD}")
    return 1 if BAD else 0


if __name__ == "__main__":
    sys.exit(main())
