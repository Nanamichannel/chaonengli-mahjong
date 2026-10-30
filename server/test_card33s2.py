# -*- coding: utf-8 -*-
"""Card33 S2【记忆】自测。

跑法：cd N:\\apps\\tianma\\server; python test_card33s2.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from game import Game, RuleError                     # noqa: E402
import skills                                        # noqa: E402
import test_card30 as t30                            # noqa: E402
import test_game as tg                               # noqa: E402
from tiles import parse_hand                          # noqa: E402

PASS = FAIL = 0
H = "1m2m3m4p5p6p7s8s9s5z5z1m3s"


def check(name, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  got {got!r} want {want!r}")


def err_of(fn):
    try:
        fn()
    except RuleError as e:
        return str(e)
    return ""


def playable(db, rid, seat=0, drawn="3s"):
    """把一局摆成「seat 的切牌状态 + 有摸牌」。"""
    tg.set_hand(db, rid, seat, parse_hand(H), drawn=drawn)
    g = Game(db, rid)
    g.round_phase = "play"
    g.phase = "discard"
    g.turn = seat
    g.deal_wait = set()
    g.deal_used = set()
    g.save_flags()
    return g


def main() -> int:
    print("=" * 78)
    print(" Card33 S2【记忆】")
    print("=" * 78)

    print("\n① 注册 / 时机")
    check("名字", skills.info(33, 2).get("name"), "记忆")
    check("时机 = 切牌", skills.timing(33, 2), "discard")
    check("不是配牌技能", (33, 2) in skills.deal_skills(), False)

    print("\n② 东一第一局：没有上一局 → 任何数字都能发")
    db, rid = t30.setup("c33s2a", card=33)
    g = playable(db, rid)
    check("last_points = None", g.c33s2_last_points(0), None)
    check("切牌状态可以发", g.c33s2_can(0), True)
    check("不是自己回合不能发", g.c33s2_can(1), False)
    r = g.c33s2_try(0, 12345)
    check("随便输个数就发动", bool(r.get("armed")), True)
    check("armed = 0", int(g.c33s2_armed), 0)
    check("本小局记成已用", g.skill_used(0, 33, 2), True)

    print("\n③ 发动后：下一张打出暗置，然后 armed 清掉")
    g2 = Game(db, rid)
    check("重开实例 armed 还在（落库）", int(g2.c33s2_armed), 0)
    out = g2._do_discard(0, "1m")
    d = g2.db._row("SELECT tile, face_down FROM round_discards WHERE round_id=? "
                   "ORDER BY seq DESC LIMIT 1", (rid,))
    check("打出的那张进牌河", d["tile"], "1m")
    check("是暗置", int(d["face_down"]), 1)
    check("armed 已清", int(g2.c33s2_armed), -1)
    check("暗置牌不产生鸣牌/荣和窗口", g2.pending, None)
    g2.turn = 1
    g2.phase = "discard"
    g2._do_discard(1, "1p")
    d2 = g2.db._row("SELECT tile, face_down FROM round_discards WHERE round_id=? "
                    "ORDER BY seq DESC LIMIT 1", (rid,))
    check("下一张恢复正常明置", int(d2["face_down"]), 0)

    print("\n④ 本小局只能用一次")
    g3 = playable(db, rid, seat=0)
    msg = err_of(lambda: g3.c33s2_try(0, 8000))
    check("再用 → 拒", "已经用过" in msg, True)
    st = Game(db, rid).state_for(0).get("c33s2") or {}
    check("state.c33s2.used", bool(st.get("used")), True)
    check("state.c33s2.can", bool(st.get("can")), False)

    print("\n④b 下一小局可以再用（不是整场）")
    m0 = int(db._one("SELECT match_id FROM rounds WHERE round_id=?", (rid,)))
    db.finish_round(rid, "ryuukyoku", deltas={})
    rid_n = db.start_round(m0, "dong", 2, honba=0, dealer_seat=1, seed=88)
    gn = playable(db, rid_n, seat=0)
    check("新的一局 can 又变 true", gn.c33s2_can(0), True)
    check("新的一局 used=false", bool((gn.state_for(0).get("c33s2") or {}).get("used")), False)
    check("上一局流局 → 答案 3000", gn.c33s2_last_points(0), 3000)
    rn = gn.c33s2_try(0, 3000)
    check("新的一局可以再发", bool(rn.get("armed")), True)

    print("\n⑤ 有上一局：数字要对上（净得失点数）")
    db2, rid0 = t30.setup("c33s2b", card=33)
    match = int(db2._one("SELECT match_id FROM rounds WHERE round_id=?", (rid0,)))
    # 第一局结算：0 号位 +1000，1 号位 -1000
    db2.finish_round(rid0, "ron", winner_seat=1, loser_seat=0, han=1, fu=30,
                     points=1000, deltas={1: 1000, 0: -1000})
    rid1 = db2.start_round(match, "dong", 2, honba=0, dealer_seat=1, seed=77)
    g4 = playable(db2, rid1, seat=0)
    check("上一局我（放铳）-1000", g4.c33s2_last_points(0), -1000)
    check("上一局对家 +1000", g4.c33s2_last_points(1), 1000)
    check("上一局没参与的人 = 0", g4.c33s2_last_points(2), 0)
    msg = err_of(lambda: g4.c33s2_try(0, 999))
    check("输错 → 拒", "数字不对" in msg, True)
    check("输错不发动", int(Game(db2, rid1).c33s2_armed), -1)
    r4 = g4.c33s2_try(0, 1000)
    check("输对（负数取绝对值）→ 发动", bool(r4.get("armed")), True)

    print("\n⑥ API 入口")
    import api_cli
    db3, rid3 = t30.setup("c33s2c", card=33)
    g6 = playable(db3, rid3)
    rr = api_cli.handle({"op": "c33s2_try", "seat": 0, "number": 1234,
                         "round_id": rid3}, db3.path)
    check("API ok", bool(rr.get("ok")), True)
    check("API armed", bool((rr.get("c33s2") or {}).get("armed")), True)
    st3 = ((rr.get("state") or {}).get("c33s2") or {})
    check("API state.armed", bool(st3.get("armed")), True)
    check("state.last = None（东一第一局）", st3.get("last", "x"), None)

    print("\n⑦ state 里带上一局点数")
    db4, rid4 = t30.setup("c33s2d", card=33)
    m4 = int(db4._one("SELECT match_id FROM rounds WHERE round_id=?", (rid4,)))
    db4.finish_round(rid4, "tsumo", winner_seat=0, han=2, fu=30, points=2000,
                     deltas={0: 2000, 1: -700, 2: -700, 3: -600})
    rid5 = db4.start_round(m4, "dong", 2, honba=0, dealer_seat=1, seed=79)
    g7 = playable(db4, rid5, seat=0)
    st5 = g7.state_for(0).get("c33s2") or {}
    check("state.last = 2000", int(st5.get("last", 0)), 2000)

    print("\n⑦ 流局：答案固定 3000（所有人都一样）")
    db8, rid8 = t30.setup("c33s2e", card=33)
    m8 = int(db8._one("SELECT match_id FROM rounds WHERE round_id=?", (rid8,)))
    db8.finish_round(rid8, "ryuukyoku", deltas={0: 3000, 1: -1000, 2: -1000, 3: -1000})
    rid9 = db8.start_round(m8, "dong", 2, honba=0, dealer_seat=1, seed=90)
    g9 = playable(db8, rid9, seat=0)
    check("流局 → 我听牌者也是 3000", g9.c33s2_last_points(0), 3000)
    check("流局 → 未听牌的人也是 3000", g9.c33s2_last_points(1), 3000)
    msg = err_of(lambda: g9.c33s2_try(0, 1000))
    check("流局输 1000 → 拒", "数字不对" in msg, True)
    r9 = g9.c33s2_try(0, 3000)
    check("流局输 3000 → 发动", bool(r9.get("armed")), True)

    print("\n" + "=" * 78)
    print(f" 通过 {PASS} / 失败 {FAIL}")
    print("=" * 78)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
