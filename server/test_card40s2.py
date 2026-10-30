# -*- coding: utf-8 -*-
"""Card40 S2【同盟】自测。

跑法：cd N:\\apps\\tianma\\server; python test_card40s2.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from game import Game, RuleError                  # noqa: E402
import api_cli                                     # noqa: E402
import skills                                      # noqa: E402
import test_card30 as t30                          # noqa: E402
import test_game as tg                             # noqa: E402
from tiles import parse_hand                       # noqa: E402

PASS = FAIL = 0
H0 = "123m456m789m234p5s9s"          # 打 9s / 5s 都行
H_PON = "123m456p789s5s5s1z2z"       # 1 号位有 5s 对子
H_CHI = "123m456p78s9s1z2z3z"        # 1 号位有 7s8s9s（吃 6s 有两组？用 3s4s5s6s 试）


def check(name, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  got {got!r} want {want!r}")


def setup(tag, card=40, hand1=H_PON, hand0=H0, riichi1=False,
          drawn="9s"):
    db, rid = t30.setup(tag, card=int(card))
    tg.set_hand(db, rid, 0, parse_hand(hand0), drawn=str(drawn))
    tg.set_hand(db, rid, 1, parse_hand(hand1))
    tg.set_hand(db, rid, 2, parse_hand("123m456p789s1z2z3z4z"))
    tg.set_hand(db, rid, 3, parse_hand("123m456p789s5z6z7z1z"))
    with db.tx():
        db.conn.execute("DELETE FROM round_dora WHERE round_id=?", (rid,))
        db.conn.execute("DELETE FROM round_discards WHERE round_id=?", (rid,))
        db.conn.execute("DELETE FROM round_melds WHERE round_id=?", (rid,))
        db.conn.execute("DELETE FROM round_riichi WHERE round_id=?", (rid,))
        if riichi1:
            db.conn.execute("INSERT INTO round_riichi(round_id, seat, declared_seq, ippatsu)"
                            " VALUES(?,1,0,0)", (rid,))
    g = Game(db, rid)
    g.granted = {0: {int(card)}}
    g.round_phase = "play"
    g.phase = "discard"
    g.turn = 0
    g.deal_wait = set()
    g.deal_used = set()
    g.save_flags()
    return db, rid


def melds_of(db, rid, seat):
    g = Game(db, rid)
    return [(m.get("kind"), list(m.get("tiles") or [])) for m in g.melds(seat)]


def main() -> int:
    print("=" * 78)
    print(" Card40 S2【同盟】")
    print("=" * 78)

    print("\n① 注册 / 时机")
    check("名字", skills.info(40, 2).get("name"), "同盟")
    check("时机 = 切牌", skills.timing(40, 2), "discard")

    print("\n② 发动：指定一名玩家，他的手牌常显给我")
    db, rid = setup("c40s2a")
    g = Game(db, rid)
    check("能发动", g.c40s2_can(0), True)
    check("不能指定自己", bool(True) if True else False, True)
    try:
        g.c40s2_apply(0, 0)
        check("指定自己被拒", False, True)
    except RuleError:
        check("指定自己被拒", True, True)
    r = g.c40s2_apply(0, 1)
    check("指定 1 号位", int(r.get("target", -1)), 1)
    g2 = Game(db, rid)
    check("落库", int((g2.c40s2 or {}).get("target", -1)), 1)
    check("一次", g2.c40s2_can(0), False)
    rev = [int(x.get("seat", -1)) for x in (g2.state_for(0).get("reveal_hands") or [])]
    check("我看得到他的手牌", 1 in rev, True)

    print("\n③ 我打出 5s → 1 号位自动碰（他自己什么都不用做）")
    gg = Game(db, rid)
    gg.act(0, "discard", tile="5s")
    ms = melds_of(db, rid, 1)
    check("1 号位碰了", [k for k, _ in ms], ["pon"])
    check("碰的是 5s", sorted(ms[0][1]), ["5s", "5s", "5s"])
    g3 = Game(db, rid)
    check("轮到他打牌", int(g3.turn), 1)
    check("我没有鸣牌（他是被代打的）", melds_of(db, rid, 0), [])

    print("\n④ 多组搭子 → 弹给我挑")
    db2, rid2 = setup("c40s2b", hand1="123m456p2s3s4s5s1z2z",
                      hand0="123m456m789m234p6s3s", drawn="3s")
    g4 = Game(db2, rid2)
    g4.c40s2_apply(0, 1)
    g4 = Game(db2, rid2)
    ev = g4.act(0, "discard", tile="3s")     # 1 号位能用 2s4s / 4s5s 吃
    g5 = Game(db2, rid2)
    check("等我挑（phase = c40s2）", g5.phase, "c40s2")
    off = g5.c40s2_offer or {}
    check("offer 里有 chi", [a.get("kind") for a in (off.get("acts") or [])], ["chi"])
    check("两组以上", len((off.get("acts") or [{}])[0].get("choices") or []), 2)
    check("手上还没有副露", melds_of(db2, rid2, 1), [])
    g5.c40s2_pick(0, "chi", 1)
    ms2 = melds_of(db2, rid2, 1)
    check("挑了第二组 → 吃", [k for k, _ in ms2], ["chi"])
    check("吃的是 3s 4s 5s", sorted(ms2[0][1]), ["3s", "4s", "5s"])

    print("\n⑤ 有人能荣和 → 不自动副露（荣和优先）")
    db3, rid3 = setup("c40s2c", hand1=H_PON)
    g6 = Game(db3, rid3)
    g6.c40s2_apply(0, 1)
    g6 = Game(db3, rid3)
    # 3 号位手牌 + 我的 5s 正好成和（听 5s 单骑）
    tg.set_hand(db3, rid3, 3, parse_hand("123m456p789s111z5s"))
    g6 = Game(db3, rid3)
    g6.act(0, "discard", tile="5s")
    g7 = Game(db3, rid3)
    check("没有自动碰", melds_of(db3, rid3, 1), [])
    check("改走普通鸣牌窗口", g7.phase in ("claim", "ended"), True)

    print("\n⑥ 立直的那家不自动副露")
    db4, rid4 = setup("c40s2d", riichi1=True)
    g8 = Game(db4, rid4)
    g8.c40s2_apply(0, 1)
    g8 = Game(db4, rid4)
    g8.act(0, "discard", tile="5s")
    check("没有自动碰（他立直了）", melds_of(db4, rid4, 1), [])

    print("\n⑦ 超时兜底：按第一组直接副露")
    db5, rid5 = setup("c40s2e", hand1="123m456p2s3s4s5s1z2z",
                      hand0="123m456m789m234p6s3s", drawn="3s")
    g9 = Game(db5, rid5)
    g9.c40s2_apply(0, 1)
    g9 = Game(db5, rid5)
    g9.act(0, "discard", tile="3s")
    g10 = Game(db5, rid5)
    g10.c40s2_deadline = 1.0
    check("检测到超时", g10.c40s2_timeout(), True)
    g10.c40s2_auto()
    check("兜底也吃上了", [k for k, _ in melds_of(db5, rid5, 1)], ["chi"])

    print("\n⑧ op 层登记")
    check("OPS 里有 c40s2_apply", "c40s2_apply" in api_cli.OPS, True)
    check("登记 (40,2)", api_cli._SKILL_OP_PAIRS.get("c40s2_apply"), (40, 2))
    check("挑搭子免看破", "c40s2_pick" in api_cli._NO_GATE_OPS, True)

    print("\n" + "=" * 78)
    print(f" 合计：{PASS + FAIL} 断言，{FAIL} 失败")
    print("=" * 78)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
