# -*- coding: utf-8 -*-
"""Card01 S1「国标」= 一定和牌（宣言式）：选一张听牌的牌打出 → 按顺位找铳张结算

规则：下家 → 对家 → 上家，找手里有我的铳牌的人；一个人有多张 → 取点数最高的那张；
都没有 → 自摸。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")

from game import Game  # noqa: E402
from tiles import parse_hand  # noqa: E402
import test_game as tg  # noqa: E402

PASS = 0
FAIL = 0


def check(name, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  got={got!r} want={want!r}")


# 14 张：123m456m789m22p34s9s → 打 9s 听 2s/5s
H14 = parse_hand("123m456m789m22p34s") + ["9s"]
H_NONE = parse_hand("1m4m7m1p4p7p1s4s7s1z2z3z")


def make(tag, seed, others):
    db = tg.fresh_db(tag)
    rid, _m, _u = tg.new_round(db, seed=seed)
    tg.set_hand(db, rid, 0, H14, drawn="9s")
    for i, h in enumerate(others, start=1):
        tg.set_hand(db, rid, i, h)
    g = Game(db, rid)
    g.granted = {0: {1}}
    g.round_phase = "play"
    g.turn, g.phase = 0, "discard"
    g.save_flags()
    return db, rid


def main() -> int:
    print("=" * 66)
    print(" 天才麻将少女 · Card01 S1「国标」= 一定和牌")
    print("=" * 66)

    # ① 没满足条件不能发动
    print("\n① 条件")
    db, rid = make("gb1", 911, [H_NONE, H_NONE, H_NONE])
    g = Game(db, rid)
    check("刚摸牌 + 切了听牌 → 可以发动", g.guobiao_can(0), True)
    check("可切的牌里有 9s", "9s" in g.guobiao_discards(0), True)
    check("2p 切了不听，不在列表", "2p" in g.guobiao_discards(0), False)
    check("legal 里有 guobiao",
          any(a.get("action") == "guobiao" for a in g.legal_actions(0)), True)

    # ② 下家有铳张 → 下家出铳（先问下家）
    print("\n② 下家有铳张 → 下家放铳")
    below = parse_hand("1m2m3m4p5p6p7s8s9s1p1p1p") + ["2s"]     # 有 2s
    db2, rid2 = make("gb2", 912, [below, H_NONE, H_NONE])
    g2 = Game(db2, rid2)
    ev = g2.guobiao_declare(0, "9s")
    check("事件类型", ev.get("event"), "yiding")
    check("出铳的是下家 1", ev.get("from"), 1)
    row = db2._row("SELECT result, winner_seat, loser_seat FROM rounds WHERE round_id=?",
                   (rid2,))
    check("记成荣和", row["result"], "ron")
    check("放铳者 1", int(row["loser_seat"]), 1)
    check("国标用掉了（一局一次）", Game(db2, rid2).guobiao_can(0), False)

    # ③ 下家没有、对家有 → 对家出铳
    print("\n③ 下家没有、对家有 → 对家放铳")
    across = parse_hand("1m2m3m4p5p6p7s8s9s1p1p1p") + ["5s"]    # 有 5s
    db3, rid3 = make("gb3", 913, [H_NONE, across, H_NONE])
    g3 = Game(db3, rid3)
    ev3 = g3.guobiao_declare(0, "9s")
    check("出铳的是对家 2", ev3.get("from"), 2)
    row3 = db3._row("SELECT loser_seat FROM rounds WHERE round_id=?", (rid3,))
    check("放铳者 2", int(row3["loser_seat"]), 2)

    # ④ 只有上家有 → 上家出铳
    print("\n④ 只有上家有 → 上家放铳")
    above = parse_hand("1m2m3m4p5p6p7s8s9s1p1p1p") + ["5s"]
    db4, rid4 = make("gb4", 914, [H_NONE, H_NONE, above])
    g4 = Game(db4, rid4)
    ev4 = g4.guobiao_declare(0, "9s")
    check("出铳的是上家 3", ev4.get("from"), 3)

    # ⑤ 都没铳张 → 自摸
    print("\n⑤ 都没铳张 → 自摸")
    db5, rid5 = make("gb5", 915, [H_NONE, H_NONE, H_NONE])
    g5 = Game(db5, rid5)
    ev5 = g5.guobiao_declare(0, "9s")
    check("自摸（from=-1）", ev5.get("from"), -1)
    row5 = db5._row("SELECT result FROM rounds WHERE round_id=?", (rid5,))
    check("记成自摸", row5["result"], "tsumo")

    # ⑥ 一个人有多个铳张 → 取最高点数
    print("\n⑥ 同一人有多个铳张 → 取最高点数")
    # 让上家同时有 2s 和 5s（我打 9s 后听 2s/5s）
    both = parse_hand("1m2m3m4p5p6p7s8s9s1p1p") + ["2s", "5s"]
    db6, rid6 = make("gb6", 916, [H_NONE, H_NONE, both])
    g6 = Game(db6, rid6)
    pair = g6._yiding_payer(0)
    check("找到上家出铳", pair[0], 3)
    check("拿到的是某一张铳张", pair[1] in ("2s", "5s"), True)
    # 点数都算出来挑最大的
    base = parse_hand("123m456m789m22p34s")
    best = -1
    for t in ("2s", "5s"):
        res = g6._judge_win(0, t, tsumo=False, quiet=True) or {}
        best = max(best, int((res.get("pays") or {}).get("total", 0)))
    res_pick = g6._judge_win(0, pair[1], tsumo=False, quiet=True) or {}
    check("取的就是点数最高的那张",
          int((res_pick.get("pays") or {}).get("total", 0)), best)

    # ⑦ 切了不听牌的牌要拒
    print("\n⑦ 切了不听牌 → 拒绝")
    db7, rid7 = make("gb7", 917, [H_NONE, H_NONE, H_NONE])
    g7 = Game(db7, rid7)
    try:
        g7.guobiao_declare(0, "2p")
        check("要拒绝", False)
    except Exception as e:
        check("要拒绝", "不听牌" in str(e))
    check("拒绝后还能再发动", Game(db7, rid7).guobiao_can(0), True)

    print("\n" + "=" * 66)
    print(f" 通过 {PASS} / 失败 {FAIL}")
    print("=" * 66)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
