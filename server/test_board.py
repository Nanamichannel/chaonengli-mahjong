# -*- coding: utf-8 -*-
"""Card02 Skill1「画板」自测
跑法： python test_board.py

画板指定的是「牌种」（34 种里任选 3 种），不要求这些牌在自己手上。
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

PICKS = ["2s", "8p", "zhong"]          # 故意选不在手上的牌种


def check(name, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  got={got!r} want={want!r}")


def at_discard(g: Game, seat: int) -> Game:
    g.turn = seat
    g.phase = "discard"
    g.save_flags()
    return g


def at_draw(g: Game, seat: int) -> Game:
    g.turn = seat
    g.phase = "draw"
    g.save_flags()
    return g


def main() -> int:
    print("=" * 70)
    print(" 天马麻将 · Card02 Skill1「画板」")
    print("=" * 70)

    # ── 1. 指定三种牌（可以是手上没有的牌种）───────────────────────
    print("\n① 指定三种牌种（34 种里任选，不要求在手）")
    db = tg.fresh_db("board")
    rid, _m, _u = tg.new_round(db, seed=71)
    tg.set_hand(db, rid, 0, parse_hand("1p5s9m1234567m123z") + ["bai"], drawn="bai")
    g = at_discard(Game(db, rid), 0)
    hand0 = g.hand(0)
    check("选的三张都不在手上", [t for t in PICKS if t in hand0], [])
    r = g.choose_board(0, PICKS)
    check("记录三张", r["tiles"], PICKS)
    check("技能标记为已用", g.skill_used(0, 2, 1), True)
    check("get 视图", g.board_view(0)["tiles"], PICKS)
    try:
        g.choose_board(0, PICKS)
        check("同一小局不能再发动", False)
    except RuleError as e:
        check("同一小局不能再发动", "用过" in str(e))

    # 非法牌名要拒绝（另开一局测）
    db_bad = tg.fresh_db("board_bad")
    rid_bad, _m2, _u2 = tg.new_round(db_bad, seed=72)
    g_bad = at_discard(Game(db_bad, rid_bad), 0)
    try:
        g_bad.choose_board(0, ["2s", "8p", "abc"])
        check("不认识的牌名要拒绝", False)
    except RuleError as e:
        check("不认识的牌名要拒绝", "没有这种牌" in str(e))

    # ── 2. 别人摸到指定牌 → 交给我 + 他重摸 ────────────────────────
    print("\n② 1 号位摸到 2s：交给我，他重摸")
    tg.set_next_draw(db, rid, "2s")
    g2 = at_draw(Game(db, rid), 1)
    pre_n = len(g2.hand(1))
    ev = g2.advance()
    check("事件是摸牌", ev.get("event"), "draw")
    check("摸牌的是 1 号位", int(ev.get("seat", -1)), 1)
    # 重摸：张数不变、2s 张数不变（骰子真随机，牌山里有几张 2s 不固定）
    check("1 号位重摸后手牌 = 原张数 + 1", len(g2.hand(1)), pre_n + 1)
    check("转移的那张进了我卡下（不是他手里）", g2.board_view(0)["pending"], ["2s"])
    check("事件里报了「画板转移」", ev.get("board"), [{"owner": 0, "tile": "2s"}])
    bv = g2.board_view(0)
    check("明牌压在我卡下", bv["pending"], ["2s"])
    check("2s 已记为给过", bv["delivered"], ["2s"])

    # ── 3. 我下次摸牌直接拿那张明牌 ───────────────────────────────
    print("\n③ 我摸牌：拿卡下的明牌，不从牌山摸")
    g3 = at_draw(Game(db, rid), 0)
    before = len(g3.hand(0))
    ev3 = g3.advance()
    check("摸到 2s", ev3.get("tile"), "2s")
    check("手牌只多一张（是拿明牌不是摸山）", len(g3.hand(0)), before + 1)
    check("卡下明牌清空", g3.board_view(0)["pending"], [])

    # ── 4. 每种牌只给一次 ─────────────────────────────────────────
    print("\n④ 同一种牌只给一次")
    tg.set_next_draw(db, rid, "2s")
    g4 = at_draw(Game(db, rid), 2)
    ev4 = g4.advance()
    check("这次不再转移（2 号位自己拿着）", ev4.get("tile"), "2s")
    check("卡下没有新的明牌", g4.board_view(0)["pending"], [])

    # ── 5. 另外两种还会转移 ───────────────────────────────────────
    print("\n⑤ 另外两种还没给过 → 照样转移")
    tg.set_next_draw(db, rid, "8p")
    g5 = at_draw(Game(db, rid), 3)
    ev5 = g5.advance()
    check("3 号位摸到 8p 被转走", ev5.get("tile") != "8p")
    check("8p 压到我卡下", g5.board_view(0)["pending"], ["8p"])

    g5b = at_draw(Game(db, rid), 0)
    ev5b = g5b.advance()
    check("我先把 8p 明牌拿走", ev5b.get("tile"), "8p")
    check("卡下清空", g5b.board_view(0)["pending"], [])

    # ── 6. 自己摸到自己指定的牌不转移 ─────────────────────────────
    print("\n⑥ 自己摸到指定牌：自己拿着，不转移")
    tg.set_next_draw(db, rid, "zhong")
    g6 = at_draw(Game(db, rid), 0)
    ev6 = g6.advance()
    check("自己摸到 zhong", ev6.get("tile"), "zhong")
    check("没有多出明牌", g6.board_view(0)["pending"], [])

    for d in tg._OPEN_DBS:
        try:
            d.close()
        except Exception:
            pass

    print("\n" + "=" * 70)
    print(f" 通过 {PASS} 项，失败 {FAIL} 项")
    print("=" * 70)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
