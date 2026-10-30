# -*- coding: utf-8 -*-
"""一定和牌这条链：副露后（吃碰后 11 张、没有刚摸的牌）也能宣言。

用户口径：「使用后可以触发一定和牌效果的技能改为在副露后也能发动，不只摸牌前」。
张数：1 副露吃碰后 11 张 → 切一张剩 10 = 3×3+1 → 本来就是听牌形。
"""
from __future__ import annotations

import io
import sys

sys.path.insert(0, r'N:\apps\tianma\server')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from game import Game  # noqa: E402
from tiles import parse_hand  # noqa: E402
import test_game as tg  # noqa: E402

OK = 0
BAD = 0


def check(name, got, want=True):
    global OK, BAD
    if got == want:
        OK += 1
        print("  [OK]  ", name)
    else:
        BAD += 1
        print("  [FAIL]", name, " got=", got, " want=", want)


# 副露之后手里 11 张 = 3 组面子 + 单张 4p + 待切的东
# 切掉东 → 10 张（123m 456p 789s 4p）+ 副露 3 张 = 13 → 单骑听 4p
# （先摆 14 张，让 db.meld 从手里扣掉南南南 3 张）
H11 = parse_hand("2z2z2z123m456p789s4p") + ["dong"]
OTHER = parse_hand("1m4m7m1p4p7p1s4s7s2z2z2z")
H_PAY = parse_hand("1m2m3m4p5p6p7s8s9s1p1p") + ["4p"]      # 手里有 4p（我的铳张）


def make(tag, seed, grants=None, meld=True):
    db = tg.fresh_db(tag)
    rid, _m, _u = tg.new_round(db, seed=seed)
    tg.set_hand(db, rid, 0, H11)                    # 没有 drawn = 吃碰后
    for s, h in ((1, H_PAY), (2, OTHER), (3, OTHER)):
        tg.set_hand(db, rid, s, h)
    if meld:
        with db.tx():
            db.meld(rid, 0, "open_set", parse_hand("2z2z2z"), called_tile="",
                    from_seat=-1, from_discard_seq=None, rot_index=-1)
    g = Game(db, rid)
    if grants:
        g.granted = {0: set(grants)}
    g.round_phase = "play"
    g.turn, g.phase = 0, "discard"
    g.save_flags()
    return db, rid


def main():
    print("① 1 副露、没有刚摸的牌 → 一定和牌可以宣言")
    db, rid = make("ya1", 951)
    g = Game(db, rid)
    g.granted = {0: {21}}
    g.yiding_grant(0, 21, 2)
    g = Game(db, rid)
    g.granted = {0: {21}}
    check("有权限", 0 in g.yiding, True)
    check("没有刚摸的牌", g.drawn_tile(0) is None, True)
    check("yiding_can 为真（副露后也算切牌时）", g.yiding_can(0), True)
    check("可切的牌里有东", "dong" in g.yiding_discards(0), True)
    # 11 张里切 4p 会变成「听东单骑」，所以 4p 也在列表里（这里只验证切得出去）
    check("4p 也在列表（切了听东单骑）", "4p" in g.yiding_discards(0), True)
    check("不构成面子的牌（1m）切了不听", "1m" in g.yiding_discards(0), False)
    check("legal 里有 yiding",
          any(a.get("action") == "yiding" for a in g.legal_actions(0)), True)

    print("\n② 国标（同样走一定和牌）在副露后也能发动")
    db2, rid2 = make("ya2", 952)
    g2 = Game(db2, rid2)
    g2.granted = {0: {1}}
    check("guobiao_can 为真", g2.guobiao_can(0), True)
    check("可切的牌里有东", "dong" in g2.guobiao_discards(0), True)

    print("\n③ 宣言后照常结算（下家手里有 4p → 他放铳）")
    db3, rid3 = make("ya3", 953)
    g3 = Game(db3, rid3)
    g3.granted = {0: {1}}
    ev = g3.guobiao_declare(0, "dong")
    res = g3.result or {}
    check("结算事件是 yiding", ev.get("event"), "yiding")
    check("出铳的是下家 1", ev.get("from"), 1)
    check("记成荣和", res.get("result"), "ron")
    check("赢家 0 号位", int(res.get("winner", -1)), 0)
    check("番数 > 0", int(res.get("han", 0)) > 0, True)

    print("\n④ 0 副露、没有刚摸的牌（13 张）→ 仍然不能宣言")
    db4, rid4 = make("ya4", 954, meld=False)
    tg.set_hand(db4, rid4, 0, parse_hand("123m456p789s4p55s"))
    g4 = Game(db4, rid4)
    g4.granted = {0: {21}}
    g4.yiding_grant(0, 21, 2)
    g4 = Game(db4, rid4)
    g4.granted = {0: {21}}
    check("13 张没摸牌：yiding_can 为假", g4.yiding_can(0), False)
    check("可切列表为空（13 张切一张不听）", g4.yiding_discards(0), [])

    print(f"\n通过 {OK} / 失败 {BAD}")
    return 1 if BAD else 0


if __name__ == "__main__":
    sys.exit(main())
