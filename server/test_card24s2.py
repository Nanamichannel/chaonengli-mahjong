# -*- coding: utf-8 -*-
"""Card24 S2「未来」自测

用户口径：即将摸牌前发动 → 看牌山里接下来 5 张 → 重新排序 → 确认后牌山顺序改成
玩家排的顺序 → 然后摸牌（摸第一张）。本小局一次。

跑法：cd N:\apps\tianma\server; python test_card24s2.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from game import Game, RuleError          # noqa: E402
import test_game as tg                    # noqa: E402
from tiles import parse_hand              # noqa: E402

PASS = FAIL = 0


def check(name, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  got {got!r} want {want!r}")


def setup(tag, owns=True):
    db = tg.fresh_db(tag)
    rid, _m, _u = tg.new_round(db, seed=83)
    tg.set_hand(db, rid, 0, parse_hand("123m456m789m5p5p6s7s"))
    tg.set_hand(db, rid, 1, parse_hand("1m4m7m1p4p7p1s4s7s1z2z3z"))
    tg.set_hand(db, rid, 2, parse_hand("2m5m8m2p5p8p2s5s8s2z3z4z"))
    tg.set_hand(db, rid, 3, parse_hand("3m6m9m3p6p9p3s6s9s1z2z3z"))
    g = Game(db, rid)
    g.granted = {0: {24}} if owns else {}
    g.round_phase = "play"
    g.turn, g.phase = 0, "draw"           # 即将摸牌
    g.save_flags()
    return db, rid


def main() -> int:
    print("=" * 76)
    print(" Card24 S2「未来」：摸牌前把接下来 5 张牌山重新排序")
    print("=" * 76)

    db, rid = setup("fut")
    g = Game(db, rid)

    # ── ① 能不能发动 ───────────────────────────────────────────────────
    print("\n① 发动条件")
    check("轮到我摸牌之前 → 能发动", g.future_can(0))
    check("state 里 future_can = true", g.state_for(0).get("future_can"), True)
    check("★ 询问阶段不亮牌（要先点技能）", g.future_view(0), [])
    check("state 里 future_tiles 也是空的", g.state_for(0).get("future_tiles"), [])
    r0 = g.future_arm(0)                       # 点技能图标 = 直接发动
    check("发动成功", r0.get("armed"), True)
    check("发动后立刻记「本小局用过」", g.skill_used(0, 24, 2))
    check("发动后 future_can = false", g.future_can(0), False)
    check("state 里 future_armed = true", g.state_for(0).get("future_armed"), True)
    view = g.future_view(0)
    print("   接下来 5 张:", view)
    check("发动后才给 5 张", len(view), 5)
    check("别人看不到", g.future_view(1), [])
    check("发动后仍然会停住等我排序", g.pre_draw_pending(0))

    g_nodraw = Game(db, rid)
    g_nodraw.phase = "discard"
    check("不是摸牌阶段 → 不能发动", g_nodraw.future_can(0), False)

    g_nocard = Game(db, rid)
    g_nocard.granted = {}
    g_nocard.save_flags()
    g_nocard = Game(db, rid)
    check("没这张卡 → 不能发动", g_nocard.future_can(0), False)

    check("摸牌前服务端会停下来等我（pre_draw_pending）", g.pre_draw_pending(0))

    # ── ② 排序不合规要被拒 ─────────────────────────────────────────────
    print("\n② 排序不合规")
    for bad in ([0, 1, 2, 3], [0, 0, 1, 2, 3], [0, 1, 2, 3, 5]):
        try:
            g.future_set(0, bad)
            check(f"{bad} 应该被拒", "没拒", "拒了")
        except RuleError as e:
            check(f"{bad} 应该被拒", "拒了", "拒了")
    check("被拒之后还能再来（排序还没生效）", g.future_armed, 0)

    # ── ③ 正常排序：倒过来 ─────────────────────────────────────────────
    print("\n③ 把 5 张倒过来排")
    order = [4, 3, 2, 1, 0]
    r = g.future_set(0, order)
    print("   返回的新顺序:", r.get("tiles"))
    check("返回的就是倒过来的 5 张", r.get("tiles"), list(reversed(view)))

    g2 = Game(db, rid)
    check("牌山确实变了（再看一遍 = 倒序）", g2.future_view(0), [])
    # 已经用过了 → 不再给看（future_can 为假）
    check("用过之后 future_can = false", g2.future_can(0), False)
    check("记成「本小局用过了」", g2.skill_used(0, 24, 2))

    # ── ④ 摸到的是新顺序的第一张 ────────────────────────────────────────
    print("\n④ 接着摸牌：摸到的应该是新顺序的第 1 张")
    g3 = Game(db, rid)
    ev = g3.advance()
    g4 = Game(db, rid)
    got = g4.drawn_tile(0)
    print(f"   摸到 {got}（期望 {list(reversed(view))[0]}）")
    check("摸到新顺序的第一张", got, list(reversed(view))[0])
    check("摸完进入打牌", g4.phase, "discard")

    # ── ⑤ 只能用一次 ───────────────────────────────────────────────────
    print("\n⑤ 本小局只能用一次")
    g5 = Game(db, rid)
    g5.phase, g5.turn = "draw", 0          # 假装又轮到我摸
    g5.save_flags()
    g5 = Game(db, rid)
    check("再来一次不能发动", g5.future_can(0), False)
    try:
        g5.future_arm(0)
        check("强行发动被拒", "没拒", "拒了")
    except RuleError:
        check("强行发动被拒", "拒了", "拒了")

    # ── ⑦ 没发动就排序 / 发动后超时 ────────────────────────────────────
    print("\n⑦ 必须先发动；发动了不排序就超时放弃")
    db7, rid7 = setup("fut_arm")
    g7 = Game(db7, rid7)
    try:
        g7.future_set(0, [0, 1, 2, 3, 4])
        check("没发动就排序 → 拒", "没拒", "拒了")
    except RuleError as e:
        check("没发动就排序 → 拒", "先点技能图标发动" in str(e))
    g7 = Game(db7, rid7)
    g7.future_arm(0)
    g7 = Game(db7, rid7)
    check("超时前不算超时", g7.future_timeout(), False)
    g7.future_deadline = 1.0                        # 假装早就过了
    g7.save_flags()
    g8 = Game(db7, rid7)
    check("过点了 → 超时", g8.future_timeout(), True)
    g8.future_abort()
    g8 = Game(db7, rid7)
    check("兜底后放开：不再等我排序", g8.future_armed, -1)
    check("兜底后 pre_draw_pending 不再拦", g8.pre_draw_pending(0), False)

    # ── ⑥ 牌山不够 5 张就不能发动 ─────────────────────────────────────
    print("\n⑥ 牌山剩不到 5 张")
    db6, rid6 = setup("fut_short")
    g6 = Game(db6, rid6)
    with g6.db.tx():                       # 把活牌山几乎清空
        rows = g6.db._rows("SELECT seq FROM round_wall WHERE round_id=? AND zone='live' "
                           "AND dealt_to IS NULL ORDER BY seq", (rid6,))
        for r0 in rows[3:]:
            g6.db.conn.execute(
                "UPDATE round_wall SET dealt_to=0 WHERE round_id=? AND seq=?",
                (rid6, int(r0["seq"])))
        # live_left() 读的是 rounds.live_left（服务端自己维护的计数），一起改成 3
        g6.db.conn.execute("UPDATE rounds SET live_left=3 WHERE round_id=?", (rid6,))
    g6 = Game(db6, rid6)
    check("活牌只剩 3 张 → 不能发动", g6.future_can(0), False)

    print("\n" + "=" * 76)
    print(f" 结果：{PASS} 项通过，{FAIL} 项失败")
    print("=" * 76)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
