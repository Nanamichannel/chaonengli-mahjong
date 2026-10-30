# -*- coding: utf-8 -*-
"""回归：持有「一定和牌」权限 ≠ 任何牌都能和"""
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


def make(tag, seed, hand, drawn):
    db = tg.fresh_db(tag)
    rid, _m, _u = tg.new_round(db, seed=seed)
    tg.set_hand(db, rid, 0, hand + [drawn], drawn=drawn)
    for s in (1, 2, 3):
        tg.set_hand(db, rid, s, parse_hand("1m4m7m1p4p7p1s4s7s1z2z3z"))
    g = Game(db, rid)
    g.granted = {0: {21}}
    g.round_phase = "play"
    g.turn, g.phase = 0, "discard"
    g.yiding_grant(0, 21, 2)          # 直接给「一定和牌」权限
    g.save_flags()
    return db, rid


def main() -> int:
    print("=" * 60)
    print(" 一定和牌权限 ≠ 任何牌都能和")
    print("=" * 60)

    # ① 没听的牌：摸一张完全没用的牌，不能出现「和」
    print("\n① 没成形的手牌")
    db, rid = make("ydw1", 771, parse_hand("123m456p789s1z2z3z"), "7p")
    g = Game(db, rid)
    check("手上有一定和牌权限", 0 in g.yiding, True)
    acts = [a.get("action") for a in g.legal_actions(0)]
    check("没有 tsumo 按钮", "tsumo" in acts, False)
    check("_win_ok 也是 False", g._win_ok(0, "7p", True), False)
    check("_judge_win 不兜底", g._judge_win(0, "7p", tsumo=True), None)

    # ② 成形的手牌：正常能和
    print("\n② 真听牌了")
    db2, rid2 = make("ydw2", 772, parse_hand("123m456m789m22p34s"), "2s")
    g2 = Game(db2, rid2)
    check("_win_ok 为 True", g2._win_ok(0, "2s", True), True)
    acts2 = [a.get("action") for a in g2.legal_actions(0)]
    check("有 tsumo 按钮", "tsumo" in acts2, True)

    # ③ 宣言永远能结算（权限本身还有效）
    print("\n③ 宣言照常能结算")
    db3, rid3 = make("ydw3", 773, parse_hand("123m456m789m22p34s"), "9s")
    g3 = Game(db3, rid3)
    check("可以宣言（切 9s 听 2s/5s）", g3.yiding_can(0), True)
    ev = g3.yiding_declare(0, "9s")
    check("结算事件是 yiding", ev.get("event"), "yiding")
    check("本局结束", g3.phase, "ended")

    print("\n" + "=" * 60)
    print(f" 通过 {PASS} / 失败 {FAIL}")
    print("=" * 60)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
