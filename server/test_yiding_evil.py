# -*- coding: utf-8 -*-
"""一定和牌 × 【恶灵】/【浓雾】 自测（2026-10-26）

用户口径：
· 带【恶灵】→ 荣和链路被堵 → 三次询问（下家/对家/上家）到荣和那步全失败 → 算自摸。
· 同时还有【浓雾】→ 【一定和牌】作废、游戏继续进行。
· 没有恶灵 → 谁的牌能荣和就荣和（无役也能靠 1 番 30 符兜底）。

跑法：cd N:\apps\tianma\server; python test_yiding_evil.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from game import Game                       # noqa: E402
import test_game as tg                      # noqa: E402
from tiles import parse_hand                # noqa: E402

PASS = FAIL = 0

# 0 号位：14 张，切 9s 之后听 8s（123m456m789m 是一气通贯，所以荣和有役）
H_ME = "123m456m789m5p5p6s7s9s"
H1 = "1z2z3z4z1p4p7p9p2s5s8s6m7m"          # 1 号位手里有我听的 8s
H2 = "2m5m8m2p5p8p2s5s8s2z3z4z6z"
H3 = "3m6m9m3p6p9p3s6s9s1z2z3z5z"
# 没人有 8s 的一组
H1N = "1z2z3z4z1p4p7p9p2s6s1m6m7m"
H2N = "2m5m8m2p5p8p2s9s1s2z3z4z6z"
H3N = "3m6m9m3p6p9p3s6s1s1z2z3z4z"


def check(name, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  got {got!r} want {want!r}")


def setup(tag, with_eight="yes"):
    db = tg.fresh_db(tag)
    rid, _m, _u = tg.new_round(db, seed=113)
    tg.set_hand(db, rid, 0, parse_hand(H_ME), drawn="9s")
    if with_eight == "yes":
        hands = (H1, H2, H3)
    else:
        hands = (H1N, H2N, H3N)
    for s, h in ((1, hands[0]), (2, hands[1]), (3, hands[2])):
        tg.set_hand(db, rid, s, parse_hand(h))
    g = Game(db, rid)
    g.yiding = {0}
    g.yiding_src = {0: [21, 2]}
    g.turn, g.phase = 0, "discard"
    g.save_flags()
    return db, rid


def main() -> int:
    print("=" * 78)
    print(" 一定和牌 × 恶灵 / 浓雾")
    print("=" * 78)

    # ── ① 没有恶灵：有人手里有我的铳牌 → 荣和 ────────────────────────
    print("\n① 没有恶灵 → 照常荣和")
    db1, rid1 = setup("yd1")
    g1 = Game(db1, rid1)
    check("找得到放铳者（1 号位；5s / 8s 都是我的待牌）",
          g1._yiding_payer(0) in ((1, "5s"), (1, "8s")), True)
    ev1 = g1.yiding_declare(0, "9s")
    check("事件是一点和牌", ev1.get("event"), "yiding")
    check("结算成荣和", (ev1.get("from"), g1.result.get("result")), (1, "ron"))
    check("和牌的是我", g1.result.get("winner"), 0)

    # ── ② 带【恶灵】：荣和全被堵 → 算自摸 ────────────────────────────
    print("\n② 恶灵堵荣和 → 三次询问全失败 → 自摸")
    db2, rid2 = setup("yd2")
    g2 = Game(db2, rid2)
    g2.oracle = {0: {"suit": "m", "on": True, "dice": 3}}      # 我掷过骰子 = 恶灵
    g2.save_flags()
    g2 = Game(db2, rid2)
    check("一个放铳者都找不到", g2._yiding_payer(0), (-1, ""))
    check("_win_gate 也说荣和不行", g2._win_gate(0, "8s", tsumo=False), False)
    ev2 = g2.yiding_declare(0, "9s")
    check("结算成自摸", (ev2.get("from"), g2.result.get("result")), (-1, "tsumo"))
    check("和牌的是我", g2.result.get("winner"), 0)
    check("没有作废", ev2.get("event"), "yiding")

    # ── ③ 恶灵 + 浓雾：一定和牌作废、游戏继续 ────────────────────────
    print("\n③ 恶灵 + 浓雾 → 一定和牌作废、游戏继续")
    db3, rid3 = setup("yd3")
    g3 = Game(db3, rid3)
    g3.oracle = {0: {"suit": "m", "on": True, "dice": 3}}
    g3.nongwu = {"by": 1, "left": 3}            # 1 号位开着浓雾（4 巡）
    g3.save_flags()
    g3 = Game(db3, rid3)
    check("两条路都堵死", g3._yiding_void(0), True)
    ev3 = g3.yiding_declare(0, "9s")
    check("事件 = 作废", ev3.get("event"), "yiding_void")
    check("没人和牌（这局还在继续）", g3.result, None)
    g3b = Game(db3, rid3)
    check("轮到 1 号位摸牌", (g3b.turn, g3b.phase), (1, "draw"))
    check("我这局不再是「一定和牌」状态", 0 in g3b.yiding, False)
    check("打出去的那张 9s 在牌河里（不是白打一张又摸回来）",
          g3b.db._one("SELECT COUNT(*) FROM round_discards WHERE round_id=? AND seat=0",
                      (rid3,)), 1)

    # ── ④ 只有【浓雾】：没人有我的铳牌 → 自摸被堵 → 作废 ────────────
    print("\n④ 只有浓雾：三家都没有我的铳牌 → 自摸被堵 → 技能作废")
    db4, rid4 = setup("yd4", with_eight="no")
    g4 = Game(db4, rid4)
    g4.nongwu = {"by": 1, "left": 3}            # 1 号位开着浓雾（4 巡）
    g4.save_flags()
    g4 = Game(db4, rid4)
    check("没人有我的铳牌", g4._yiding_payer(0), (-1, ""))
    check("自摸链路被浓雾堵住 → 作废", g4._yiding_void(0), True)
    ev4 = g4.yiding_declare(0, "9s")
    check("事件 = 作废", ev4.get("event"), "yiding_void")
    check("没人和牌（这局还在继续）", g4.result, None)
    g4b = Game(db4, rid4)
    check("轮到 1 号位摸牌", (g4b.turn, g4b.phase), (1, "draw"))
    check("打出去的那张 9s 留在牌河",
          g4b.db._one("SELECT COUNT(*) FROM round_discards WHERE round_id=? AND seat=0",
                      (rid4,)), 1)

    # ── ⑤ 浓雾只封自摸：有人手里有我的铳牌 → 照样荣和 ────────────────
    print("\n⑤ 浓雾不影响荣和")
    db5b, rid5b = setup("yd7")
    g5b = Game(db5b, rid5b)
    g5b.nongwu = {"by": 1, "left": 3}
    g5b.save_flags()
    g5b = Game(db5b, rid5b)
    check("找得到放铳者（浓雾不管荣和）", g5b._yiding_payer(0)[0], 1)
    ev5 = g5b.yiding_declare(0, "9s")
    check("照样走荣和", (ev5.get("from"), g5b.result.get("result")), (1, "ron"))
    check("没作废", ev5.get("event"), "yiding")

    # ── ⑤ 判番上下文统一：tenpai_base 带着技能开关 ───────────────────
    print("\n⑥ tenpai_base = yaku_base + 技能开关")
    db5, rid5 = setup("yd5")
    g5 = Game(db5, rid5)
    check("没技能时不含 dora_bonus_han", "dora_bonus_han" in g5.tenpai_base(0), False)
    g5.c25s2_on = {0}
    check("宝牌的集合开着 → base 里有 dora_void_kan", g5.tenpai_base(0).get("dora_void_kan"), True)
    check("普通的 yaku_base 里没有（开关只走 tenpai_base / win_ctx）",
          "dora_void_kan" in g5.yaku_base(0), False)
    ctx = g5.win_ctx(0, list(g5.hand(0)), "9s", False)
    check("win_ctx 也带着同一个开关", ctx.get("dora_void_kan"), True)

    # ── ⑦ 什么自摸形式都不能豁免浓雾 ──────────────────────────────────
    print("\n⑦ 浓雾不豁免任何自摸形式")
    # 对照组：14 张听 8s、刚摸的就是 8s（门清自摸和 + 一气通贯）→ 有自摸按钮
    db7, rid7 = setup("yd8")
    tg.set_hand(db7, rid7, 0, parse_hand("123m456m789m5p5p6s7s8s"), drawn="8s")
    g7 = Game(db7, rid7)
    acts0 = [a["action"] for a in g7.legal_actions(0)]
    check("（对照）没有浓雾 → 有自摸", "tsumo" in acts0, True)
    # 处理组：同一手牌 + 浓雾（1 号位开的，4 巡）
    db8, rid8 = setup("yd9")
    tg.set_hand(db8, rid8, 0, parse_hand("123m456m789m5p5p6s7s8s"), drawn="8s")
    g8 = Game(db8, rid8)
    g8.nongwu = {"by": 1, "left": 3}
    g8.yiding = {0}                       # 手上还握着「一定和牌」的权限
    g8.save_flags()
    g8 = Game(db8, rid8)
    check("握着一定和牌权限也不再豁免浓雾", g8._win_gate(0, "8s", tsumo=True), False)
    check("自摸闸门 = False", g8._tsumo_gate_ok(0), False)
    acts1 = [a["action"] for a in g8.legal_actions(0)]
    check("浓雾里不给自摸按钮", "tsumo" in acts1, False)
    check("（荣和不受影响）浓雾不碰 _win_gate 的荣和",
          g8._win_gate(0, "8s", tsumo=False), True)
    # 海神 gate 也是「不许和」：两条路一起拦
    g8.haishin_gate = 0
    check("海神 gate 也拦自摸", g8._tsumo_gate_ok(0), False)
    check("海神 gate 也拦荣和", g8._win_gate(0, "8s", tsumo=False), False)

    print("\n" + "=" * 78)
    print(f" 通过 {PASS} / 失败 {FAIL}")
    print("=" * 78)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
