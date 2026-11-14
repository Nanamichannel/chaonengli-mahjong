# -*- coding: utf-8 -*-
"""Card02 S1「画板」/ S2「换牌」：改成**摸牌前**询问 / 发动

用户口径 2026-11-07：
  · S1 画板：摸牌前询问，当场决定发不发动
  · S2 换牌：**只在第十三巡摸牌前**那一次询问
  · 两个都能问时，先问 S2（换牌）、再问 S1（画板），别冲突

跑法：cd server; python test_card02_predraw.py
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


H13 = parse_hand("123m456p789s") + ["1p", "1p", "5m", "5m"]      # 13 张（摸牌前）


def put_river(db, rid, rows):
    """测试用：直接往牌河里放牌（seat, tile[, wall_seq]）"""
    with db.tx():
        for i, item in enumerate(rows):
            seat, tile = item[0], item[1]
            wseq = item[2] if len(item) > 2 else 9000 + i
            db.conn.execute(
                "INSERT INTO round_discards(round_id, seq, seat, wall_seq, tile, is_tsumogiri,"
                " is_riichi_tile, face_down, called) VALUES(?,?,?,?,?,0,0,0,0)",
                (rid, i + 1, seat, wseq, tile))


def setup(tag, seed, discs=12, grant=None):
    """建一局：0 号位持 Card02，已经打完 discs 巡，轮到他**摸牌前**"""
    db = tg.fresh_db(tag)
    rid, _m, _u = tg.new_round(db, seed=seed)
    tg.set_hand(db, rid, 0, H13)
    for s in (1, 2, 3):
        tg.set_hand(db, rid, s, H13)
    with db.tx():
        for i in range(int(discs)):
            db.conn.execute(
                "INSERT INTO round_actions(round_id, seq, seat, action, payload) "
                "VALUES(?, ?, 0, 'discard', '{}')", (rid, 500 + i))
    g = Game(db, rid)
    g.round_phase = "play"
    g.granted = grant if grant is not None else {0: {2}}
    tg.to_draw(g, 0)
    return db, rid, g


def main() -> int:
    print("=" * 70)
    print(" 天才麻将少女 · Card02 S1/S2（摸牌前询问）")
    print("=" * 70)

    # ── ① 第十三巡摸牌前：先问换牌(S2)，跳过之后才问画板(S1) ────────
    print("\n① 第十三巡摸牌前：S2 先问、S1 后问")
    db, rid, g = setup("c02p1", 701)
    put_river(db, rid, [(1, "3p"), (2, "7m"), (3, "nan")])
    check("轮到我摸牌（还没摸）", g.drawn_tile(0), None)
    check("画板 摸牌前可发动", g.board_can(0), True)
    check("换牌 第十三巡摸牌前可发动", g.swap3_can(0), True)
    check("摸牌前有询问要问", g.pre_draw_pending(0), True)
    check("能挂出询问", g.open_pre_draw_ask(0), True)
    check("第一笔是换牌（S2）", str((g.cur_ask or {}).get("kind", "")), "c02s2")
    check("跳过换牌", (g.pre_draw_skip(0) or {}).get("kind"), "c02s2")
    check("接着挂画板（S1）", g.open_pre_draw_ask(0), True)
    check("第二笔是画板（S1）", str((g.cur_ask or {}).get("kind", "")), "c02s1")
    check("跳过画板", (g.pre_draw_skip(0) or {}).get("kind"), "c02s1")
    check("都问完了 → 不再欠询问", g.pre_draw_pending(0), False)
    check("也挂不出新询问", g.open_pre_draw_ask(0), False)

    # ── ② 还没到第十三巡：不问换牌，只问画板 ──────────────────────
    print("\n② 第五巡摸牌前：只问画板，不问换牌")
    db2, rid2, g2 = setup("c02p2", 702, discs=5)
    put_river(db2, rid2, [(1, "3p")])
    check("换牌不可问", g2.swap3_can(0), False)
    check("画板可问", g2.board_can(0), True)
    check("挂出询问", g2.open_pre_draw_ask(0), True)
    check("先问的是画板", str((g2.cur_ask or {}).get("kind", "")), "c02s1")
    g2.pre_draw_skip(0)
    check("没有第二笔", g2.open_pre_draw_ask(0), False)

    # ── ③ 过了第十三巡：两个都不问 ───────────────────────────────
    print("\n③ 第十四巡摸牌前：换牌不再问")
    db3, rid3, g3 = setup("c02p3", 703, discs=13)
    put_river(db3, rid3, [(1, "3p")])
    check("换牌不可用", g3.swap3_can(0), False)
    try:
        g3.swap_river(0, ["1p", "1p", "5m"], [1])
        check("强行换牌被拒绝", False)
    except RuleError as e:
        check("强行换牌被拒绝", "第十三巡" in str(e))

    # ── ④ 画板：摸牌前指定三种牌 → 照常摸牌 ────────────────────────
    print("\n④ 画板摸牌前发动")
    db4, rid4, g4 = setup("c02p4", 704)
    r = g4.choose_board(0, ["1p", "9p", "dong"])
    check("指定成功", r.get("tiles"), ["1p", "9p", "dong"])
    check("本小局标记已用", g4.skill_used(0, 2, 1), True)
    check("画板不能再问", g4.board_can(0), False)
    n0 = len(g4.hand(0))
    g4.advance()
    check("照常摸到一张（13 → 14）", len(g4.hand(0)), n0 + 1)
    check("摸到牌了", g4.drawn_tile(0) is not None, True)

    # ── ⑤ 换牌：摸牌前 3 换 3 → 再摸牌，之后只能摸切 ────────────────
    print("\n⑤ 换牌摸牌前发动（第十三巡）")
    db5, rid5, g5 = setup("c02p5", 705)
    put_river(db5, rid5, [(1, "3p"), (2, "7m"), (3, "nan")])
    before = sorted(g5.hand(0))
    r5 = g5.swap_river(0, ["1p", "1p", "5m"], [1, 2, 3])
    check("换进 3p/7m/nan", r5.get("got"), ["3p", "7m", "nan"])
    check("手牌张数不变（还是 13）", len(g5.hand(0)), len(before))
    check("摸牌前不伪造「刚摸到的」", g5.drawn_tile(0), None)
    check("记了只能摸切", g5.state_for(0).get("must_tsumogiri"), True)
    check("换牌不能再问", g5.swap3_can(0), False)
    g5.advance()
    drawn = g5.drawn_tile(0)
    other = [t for t in g5.hand(0) if t != drawn][0]
    try:
        g5.act(0, "discard", tile=other)
        check("手切被拒绝", False)
    except RuleError as e:
        check("手切被拒绝", "摸切" in str(e))
    check("摸切可以打出去", bool(g5.act(0, "discard", tile=drawn).get("ok", True)), True)

    print("\n" + "=" * 70)
    print(f" 通过 {PASS} 项，失败 {FAIL} 项")
    print("=" * 70)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
