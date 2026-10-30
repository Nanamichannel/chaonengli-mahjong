# -*- coding: utf-8 -*-
"""Card34 S1【厄运】自测。

跑法：cd N:\\apps\\tianma\\server; python test_card34.py
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

# 0 号位：普通手牌（能正常切）
H0 = "1m2m3m4p5p6p7s8s9s5z5z1m6m3s"
# 1 号位：有一对 1p（本来能碰）+ 4 张 9s（本来能暗杠）
H1 = "4p4p2p3p5p6p7p8p1p9s9s9s9s"
# 2 / 3 号位：杂牌
H2 = "1m4m7m2p5p8p2s5s8s2z3z4z6z"
H3 = "3m6m9m3p6p9p3s6s9s1z2z3z5z"


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


def setup(tag, card=34):
    db, rid = t30.setup(tag, card=card)
    for s, h in enumerate((H0, H1, H2, H3)):
        tg.set_hand(db, rid, s, parse_hand(h), drawn=("3s" if s == 0 else "9s" if s == 1 else None))
    with db.tx():
        db.conn.execute("DELETE FROM round_dora WHERE round_id=?", (rid,))
        db.conn.execute("DELETE FROM round_discards WHERE round_id=?", (rid,))
    g = Game(db, rid)
    g.round_phase = "play"
    g.phase = "discard"
    g.turn = 0
    g.deal_wait = set()
    g.deal_used = set()
    g.save_flags()
    return db, rid


def main() -> int:
    print("=" * 78)
    print(" Card34 S1【厄运】")
    print("=" * 78)

    print("\n① 注册 / 时机")
    check("名字", skills.info(34, 1).get("name"), "厄运")
    check("时机 = 切牌", skills.timing(34, 1), "discard")
    check("不是配牌技能", (34, 1) in skills.deal_skills(), False)

    print("\n② 发动 + 静默判定")
    db, rid = setup("c34a")
    g = Game(db, rid)
    check("切牌前 can", g.c34s1_can(0), True)
    check("别人回合不能发", g.c34s1_can(1), False)
    r = g.c34s1_arm(0)
    check("发动返回 turns=3", int(r.get("turns", 0)), 3)
    check("还剩 3 巡", int(r.get("left", 0)), 3)
    g2 = Game(db, rid)
    check("1 号位静默", g2.c34_muted(1), True)
    check("2 号位静默", g2.c34_muted(2), True)
    check("3 号位静默", g2.c34_muted(3), True)
    check("发动者不受影响", g2.c34_muted(0), False)
    msg = err_of(lambda: Game(db, rid).c34s1_arm(0))
    check("本小局一次（次数用完）", "没有可发动次数" in msg, True)

    print("\n③ 只能摸切（legal_actions + 硬校验）")
    g3 = Game(db, rid)
    g3.turn = 1
    g3.phase = "discard"
    la = g3.legal_actions(1)
    check("legal 只有 discard", [a["action"] for a in la], ["discard"])
    check("只能打刚摸的那张", la[0].get("tiles"), ["9s"])
    msg = err_of(lambda: g3._do_discard(1, "4p"))
    check("手切被拒", "只能摸切" in msg, True)

    print("\n④ 不能和")
    db4, rid4 = setup("c34b")
    tg.set_hand(db4, rid4, 1, parse_hand("123m456m789m234p5z"))
    g4 = Game(db4, rid4)
    g4.phase = "discard"
    g4.turn = 0
    g4.c34_by = 0
    g4.c34_left = 3
    g4.save_flags()
    check("静默期 _win_ok = False", g4._win_ok(1, "bai", tsumo=False), False)
    g4.c34_by = -1
    g4.c34_left = {}
    check("不静默时能和", g4._win_ok(1, "bai", tsumo=False), True)

    print("\n⑤ 不能副露")
    db5, rid5 = setup("c34c")
    g5 = Game(db5, rid5)
    g5.c34_by = 0
    g5.c34_left = 3
    g5.save_flags()
    g5._do_discard(0, "4p")
    opts = (g5.pending or {}).get("options") or {}
    check("1 号位没有碰/吃选项", 1 in opts, False)
    check("确实开了鸣牌窗口（别家也没牌）", g5.pending, None)

    print("\n⑥ 不能杠（含暗杠）")
    dg = Game(db5, rid5)
    check("暗杠被拒", "不能杠" in err_of(lambda: dg._kan(1, "ankan", "9s")), True)
    check("加杠被拒", "不能杠" in err_of(lambda: dg._kan(1, "kakan", "9s")), True)

    print("\n⑦ 技能 op 被拒 / 询问不问他")
    import api_cli
    rr = api_cli.handle({"op": "c33s1_swap", "seat": 1, "hand_tiles": ["1p", "1p", "2p"],
                         "river": [1, 2, 3], "round_id": rid5}, db5.path)
    check("静默期技能 op 被拒", "厄运" in str(rr.get("error", "")), True)
    rr2 = api_cli.handle({"op": "state", "seat": 1, "round_id": rid5}, db5.path)
    check("state 照常能看", bool(rr2.get("ok")), True)
    st1 = (rr2.get("state") or {}).get("c34") or {}
    check("state.c34.muted", bool(st1.get("muted")), True)
    check("pre_draw_pending 静默期 False", Game(db5, rid5).pre_draw_pending(1), False)
    check("看破/封堵不问静默座位", 1 in Game(db5, rid5)._kangpo_askers(0), False)

    print("\n⑧ 三巡计数：每家摸 3 次各自解除")
    db8, rid8 = setup("c34d")
    g8 = Game(db8, rid8)
    g8.c34s1_arm(0)
    g8._c34_tick(1)                      # 别人摸牌不减（口径：算发动者自己的摸牌）
    check("别人摸牌不减巡数", int(g8.c34_left), 3)
    check("1 号位仍静默", g8.c34_muted(1), True)
    for _ in range(3):
        g8._c34_tick(0)                  # 发动者自己摸 3 次
    check("发动者摸 3 次 → 窗口关闭", int(g8.c34_by), -1)
    check("谁都正常了", g8.c34_muted(1), False)

    print("\n⑨ 三巡结束：决斗重新生效，对象转移给厄运发动者")
    db9, rid9 = setup("c34e")
    g9 = Game(db9, rid9)
    g9.duel = {"by": 2, "target": 3}
    g9.c34s1_arm(0)
    check("静默期决斗不限制人", g9.duel_restricted(1), False)
    for _ in range(3):
        g9._c34_tick(0)
    check("三巡后决斗恢复", g9.duel_restricted(1), True)
    check("决斗对象变成 34 发动者", int((g9.duel or {}).get("target", -1)), 0)

    print("\n⑩ 延迟生效：命中计数不累计 / 四喜直接作废")
    db10, rid10 = setup("c34f")
    g10 = Game(db10, rid10)
    g10.c34s1_arm(0)
    g10.c27_s2 = {1}
    g10.c27_mark = {1: 2}
    g10.c27_cnt = {1: 2}
    hit = g10._c27_tick(2, False)
    check("命中不累计（到 3 也不引爆）", hit, [])
    check("计数没动", int(g10.c27_cnt.get(1, 0)), 2)

    print("\n⑪ 策略（Card05 S1）第三段计数器 +1")
    db11, rid11 = t30.setup("c34g", card=34)
    for s, h in enumerate((H0, H1, H2, H3)):
        tg.set_hand(db11, rid11, s, parse_hand(h), drawn="3s" if s == 0 else None)
    gw = Game(db11, rid11)
    gw.granted.setdefault(1, set()).add(5)      # 1 号位持【策略】
    gw.round_phase = "play"
    gw.phase = "discard"
    gw.turn = 0
    gw.save_flags()
    gw = Game(db11, rid11)
    check("1 号位确实有策略", gw.owns_card05(1), True)
    gw.c34s1_arm(0)
    check("计数器 +1", int(gw.card05_counter.get(1, 0)), 1)
    check("没持策略的人不加", int(gw.card05_counter.get(2, 0)), 0)

    print("\n⑫ API 入口")
    db12, rid12 = setup("c34h")
    rr3 = api_cli.handle({"op": "c34s1_arm", "seat": 0, "round_id": rid12}, db12.path)
    check("API ok", bool(rr3.get("ok")), True)
    check("API left = 3", int((rr3.get("c34") or {}).get("left", 0)), 3)
    st = ((rr3.get("state") or {}).get("c34") or {})
    check("发动者 state.muted = False", bool(st.get("muted")), False)
    check("state.by = 0", int(st.get("by", -1)), 0)

    print("\n" + "=" * 78)
    print(f" 通过 {PASS} / 失败 {FAIL}")
    print("=" * 78)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
