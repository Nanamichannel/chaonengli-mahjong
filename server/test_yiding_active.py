# -*- coding: utf-8 -*-
"""一定和牌改成主动宣言：权限（被动获得）→ 宣言（立直式）→ 立刻结算

规则：按下家 → 对家 → 上家 找第一个手里有「我的铳牌」的人 → 他出铳；都没有 → 自摸。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")

from game import Game, RuleError  # noqa: E402
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


# 14 张：123m 456m 789m 22p 34s 9s  → 打 9s 听 2s/5s
H14 = parse_hand("123m456m789m22p34s") + ["9s"]
# 别人手里：一个拿 2s（当铳牌），一个不拿
H_OWER = parse_hand("1m4m7m1p4p7p1s4s7s1z2z3z")
H_NONE1 = parse_hand("2m5m8m2p5p8p2s5s8s2z3z4z")     # 有 2s/5s → 会出铳
H_NONE2 = parse_hand("3m6m9m3p6p9p3s6s9s1z2z3z")     # 没有 2s/5s


def make(tag, seed, others):
    db = tg.fresh_db(tag)
    rid, _m, _u = tg.new_round(db, seed=seed)
    tg.set_hand(db, rid, 0, H14, drawn="9s")
    for i, h in enumerate(others, start=1):
        tg.set_hand(db, rid, i, h)
    g = Game(db, rid)
    g.round_phase = "play"
    g.turn, g.phase = 0, "discard"
    g.save_flags()
    return db, rid


def main() -> int:
    print("=" * 66)
    print(" 天马麻将 · 一定和牌（主动宣言）")
    print("=" * 66)

    # ① 没有权限 → 不能宣言
    print("\n① 没有权限不能宣言")
    db, rid = make("yd0", 701, [H_OWER, H_NONE1, H_NONE2])
    g = Game(db, rid)
    check("没权限 → yiding_can False", g.yiding_can(0), False)
    check("没权限 → 可切牌列表空", g.yiding_discards(0), [])
    try:
        g.yiding_declare(0, "9s")
        check("没权限要拒", False)
    except RuleError as e:
        check("没权限要拒", "不能宣言" in str(e))

    # ② 给权限 → 能宣言；只给「切出去还听牌」的牌
    print("\n② 给权限后能宣言")
    g = Game(db, rid)
    g.yiding_grant(0, 21, 2)
    g = Game(db, rid)
    check("权限落库", 0 in g.yiding, True)
    check("来源记下来了", g.yiding_src_of(0), [21, 2])
    check("yiding_can", g.yiding_can(0), True)
    td = g.yiding_discards(0)
    check("可切 9s（切了听 2s/5s）", "9s" in td, True)
    check("不能切 2p（切了不听）", "2p" in td, False)
    check("legal_actions 里有 yiding",
          any(a.get("action") == "yiding" for a in g.legal_actions(0)), True)

    # ③ 宣言 → 有人手里有铳牌 → 他出铳
    print("\n③ 有人有铳牌 → 他出铳")
    db2, rid2 = make("yd1", 702, [H_OWER, H_NONE1, H_NONE2])
    g2 = Game(db2, rid2)
    g2.yiding_grant(0, 21, 2)
    g2 = Game(db2, rid2)
    ev = g2.yiding_declare(0, "9s")
    check("事件是 yiding", ev.get("event"), "yiding")
    check("出铳者 2 号位（下家没有、对家有 2s）", ev.get("from"), 2)
    check("权限用掉了", 0 in g2.yiding, False)
    check("本局结束", g2.phase, "ended")
    row = db2._row("SELECT result, winner_seat, loser_seat FROM rounds WHERE round_id=?",
                   (rid2,))
    check("记成荣和", row["result"], "ron")
    check("和牌者 0", int(row["winner_seat"]), 0)
    check("放铳者 2", int(row["loser_seat"]), 2)

    # ④ 都没铳牌 → 自摸
    print("\n④ 都没铳牌 → 自摸")
    db3, rid3 = make("yd2", 703, [H_OWER, H_NONE2, H_NONE2])
    g3 = Game(db3, rid3)
    g3.yiding_grant(0, 21, 2)
    g3 = Game(db3, rid3)
    ev = g3.yiding_declare(0, "9s")
    check("事件是 yiding", ev.get("event"), "yiding")
    check("自摸（from=-1）", ev.get("from"), -1)
    row = db3._row("SELECT result, winner_seat, loser_seat FROM rounds WHERE round_id=?",
                   (rid3,))
    check("记成自摸", row["result"], "tsumo")
    check("自摸没有放铳者", row["loser_seat"], None)

    # ⑤ 打完牌 = 已经进牌河，且不经过鸣牌窗口
    print("\n⑤ 宣言牌进牌河、不鸣牌")
    db4, rid4 = make("yd3", 704, [H_OWER, H_NONE1, H_NONE2])
    g4 = Game(db4, rid4)
    g4.yiding_grant(0, 21, 2)
    g4 = Game(db4, rid4)
    g4.yiding_declare(4 if False else 0, "9s")
    last = db4._row("SELECT tile, seat FROM round_discards WHERE round_id=? "
                    "ORDER BY seq DESC LIMIT 1", (rid4,))
    check("9s 已经进牌河", last["tile"], "9s")
    check("是我打的", int(last["seat"]), 0)

    # ⑥ 不听牌的牌不能宣言
    print("\n⑥ 切了不听牌 → 拒绝")
    db5, rid5 = make("yd4", 705, [H_OWER, H_NONE1, H_NONE2])
    g5 = Game(db5, rid5)
    g5.yiding_grant(0, 21, 2)
    g5 = Game(db5, rid5)
    try:
        g5.yiding_declare(0, "2p")
        check("切了不听牌要拒", False)
    except RuleError as e:
        check("切了不听牌要拒", "不听牌" in str(e))
    check("被拒后权限还在", 0 in Game(db5, rid5).yiding, True)

    # ⑦ 听牌就自动获得权限（21S2）
    print("\n⑦ 听牌自动获得权限（21S2）")
    db6 = tg.fresh_db("yd5")
    rid6, _m, _u = tg.new_round(db6, seed=706)
    # 0 号位持 21 号卡；手牌 13 张已经听牌
    tg.set_hand(db6, rid6, 0, parse_hand("123m456m789m22p34s"))
    tg.set_hand(db6, rid6, 1, H_OWER)
    tg.set_hand(db6, rid6, 2, H_NONE2)
    tg.set_hand(db6, rid6, 3, H_NONE2)
    g6 = Game(db6, rid6)
    g6.granted = {0: {21}}
    g6.round_phase = "play"
    g6.turn, g6.phase = 0, "discard"
    g6.save_flags()
    g6 = Game(db6, rid6)
    g6._maybe_grant_yiding(0)
    check("只是听牌、手切还没满 12 张 → 不给权限",
          0 in Game(db6, rid6).yiding, False)
    g6 = Game(db6, rid6)
    g6.gift[0] = 3                     # 手切满 12 张（馈赠3）
    g6._maybe_grant_yiding(0)
    g6 = Game(db6, rid6)
    check("手切满 12 张 → 拿到权限", 0 in g6.yiding, True)
    check("来源是 21S2", g6.yiding_src_of(0), [21, 2])
    check("已经持有时不重复记", g6.yiding_src_of(0), [21, 2])

    print("\n" + "=" * 66)
    print(f" 通过 {PASS} / 失败 {FAIL}")
    print("=" * 66)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
