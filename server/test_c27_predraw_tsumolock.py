# -*- coding: utf-8 -*-
"""2026-11-14 用户口径两条：

① 瞄准 27-1 改成**摸牌前**发动：先换牌（不标 is_drawn）→ 再正常走摸牌山
② 先负 22-1 / 破发 13-1：刚换完牌（副露完）这一巡**不许自摸**，荣和不受影响
"""
from __future__ import annotations

import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding="utf-8")

from game import Game                    # noqa: E402
from tiles import parse_hand             # noqa: E402
import test_game as tg                   # noqa: E402
import test_chuancheng_copy as tc        # noqa: E402

CLIENT = os.path.join(os.path.dirname(HERE), "main.gd")
SERVER = os.path.join(HERE, "game.py")

PASS = 0
FAIL = 0


def check(name, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print("  [OK]   %s" % name)
    else:
        FAIL += 1
        print("  [FAIL] %s  got=%r want=%r" % (name, got, want))


def make27(tag, seed):
    """座位 0 持 27，轮到 0 摸牌（还没摸）。别家牌河里有一张明牌。"""
    db = tg.fresh_db(tag)
    tc.set_orders(db, [[27, 27, 27, 27, 27], [1, 2, 3, 4, 5],
                       [1, 2, 3, 4, 6], [1, 2, 3, 4, 7]])
    rid, _m, _u = tg.new_round(db, seed=seed)
    tg.set_hand(db, rid, 0, parse_hand("123m456p789s1z2z3z"))
    for s, hand in ((1, "1m4m7m1p4p7p1s4s7s1z2z3z"),
                    (2, "2m5m8m2p5p8p2s5s8s2z3z4z"),
                    (3, "3m6m9m3p6p9p3s6s9s1z1z2z")):
        tg.set_hand(db, rid, s, parse_hand(hand))
    # 别家牌河一张明牌（1 号位打出 5z）
    with db.tx():
        db.conn.execute(
            "INSERT INTO round_discards(round_id, seq, seat, wall_seq, tile, called,"
            " is_tsumogiri, is_riichi_tile, face_down, is_nuki)"
            " VALUES(?,?,?,?,?,0,1,0,0,0)", (rid, 0, 1, 9001, "5z"))
    g = Game(db, rid)
    g.granted = {0: {27}}
    g.round_phase = "play"
    g.turn, g.phase = 0, "draw"
    g.save_flags()
    return db, rid


def main() -> int:
    print("=" * 70)
    print(" 天才麻将少女 · 瞄准改摸牌前 / 先负·破发这一巡不许自摸")
    print("=" * 70)

    print("\n① 瞄准：摸牌前就能发动，换完是普通手牌（不造第二张「刚摸到」）")
    db, rid = make27("c27pre", 2027)
    g = Game(db, rid)
    check("c27s1_can（还没摸牌）=True", g.c27s1_can(0), True)
    check("摸牌前询问表里有 c27s1", "c27s1" in g._pre_draw_kinds(0), True)
    check("_pre_draw_kind_ok(c27s1)=True", g._pre_draw_kind_ok(0, "c27s1"), True)
    check("state.c27s1_can=True", bool(g.state_for(0).get("c27s1_can")), True)

    hand_before = len(g.hand(0))
    ht = str(g.hand(0)[0])
    r = g.c27s1_swap(0, ht, 0)            # 手牌一张 ⇄ 牌河 5z
    check("换到的是牌河那张 5z", str(r.get("got")), "5z")
    check("标记了 1 号位", int(r.get("mark", -1)), 1)
    check("换完手里还是 13 张", len(g.hand(0)), hand_before)
    check("换完**没有**「刚摸到」的牌（摸牌前不该有）", g.drawn_tile(0), None)
    check("本小局用掉了", g.skill_used(0, 27, 1), True)
    check("用完 can=False（询问不会再挂）", g.c27s1_can(0), False)
    check("is_drawn=1 的行数 = 0", int(g.db._one(
        "SELECT COUNT(*) FROM round_hands WHERE round_id=? AND seat=? AND is_drawn=1",
        (rid, 0)) or 0), 0)

    g2 = Game(db, rid)
    check("换牌落盘（重开实例看得到标记）", int(g2.c27_mark.get(0, -1)), 1)

    print("\n② 先负/破发：这一巡锁自摸，但**荣和不锁**")
    db2 = tg.fresh_db("tsulock")
    tc.set_orders(db2, [[22, 22, 22, 22, 22], [1, 2, 3, 4, 5],
                        [1, 2, 3, 4, 6], [1, 2, 3, 4, 7]])
    rid2, _m2, _u2 = tg.new_round(db2, seed=2222)
    tg.set_hand(db2, rid2, 0, parse_hand("123m456p789s1z2z3z"))
    g3 = Game(db2, rid2)
    g3.granted = {0: {22}}
    g3.round_phase = "play"
    g3.turn, g3.phase = 0, "discard"
    g3.tsumo_lock_seat = 0
    check("锁定中：自摸被拒", g3._win_gate(0, "1z", True), False)
    check("锁定中：荣和不受影响", g3._win_gate(0, "1z", False), True)
    check("别的座位不受影响", g3._win_gate(1, "1z", True), True)
    g3._after_discard_hooks(0, "1z")      # 打出一张 = 这一巡结束
    check("打出后解锁", g3.tsumo_lock_seat, -1)
    check("解锁后自摸恢复", g3._win_gate(0, "1z", True), True)
    check("锁定标记落盘", "tsumo_lock_seat" in io.open(SERVER, encoding="utf-8").read())

    print("\n③ 静态：两个技能都挂上锁 + 客户端接进摸牌前询问")
    gsrc = io.open(SERVER, encoding="utf-8").read()
    check("先负换完牌上锁", "self.tsumo_lock_seat = s          # 刚换完牌" in gsrc)
    check("破发副露完上锁", "self.tsumo_lock_seat = s          # 破发副露完" in gsrc)
    check("瞄准改动吃进摸牌前询问", 'if kind == "c27s1":' in gsrc)
    check("瞄准不再标 is_drawn", "换进来的是**普通手牌**，不标 is_drawn" in gsrc)

    csrc = io.open(CLIENT, encoding="utf-8").read()
    check("客户端摸牌前询问表有 27", '27: "c27s1",' in csrc)
    check("客户端闸门表有 c27s1", '"c27s1": "_c27s1_gate_before_draw",' in csrc)
    check("闸门函数存在", "func _c27s1_gate_before_draw() -> bool:" in csrc)
    check("关面板会通知服务端放开摸牌", '_pda_skip_once("c27s1")' in csrc)

    print("\n" + "=" * 70)
    print(" 断言 %d 条 / 失败 %d 条" % (PASS, FAIL))
    print("=" * 70)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
