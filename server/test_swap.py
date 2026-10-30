# -*- coding: utf-8 -*-
"""Card02 Skill2「换牌」自测
跑法： python test_swap.py
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


def at_discard(g: Game, seat: int) -> Game:
    g.turn = seat
    g.phase = "discard"
    g.save_flags()
    return g


def put_river(db, rid, rows):
    """测试用：直接往牌河里放牌（seat, tile, wall_seq, called, riichi）"""
    with db.tx():
        for i, item in enumerate(rows):
            seat, tile = item[0], item[1]
            wseq = item[2] if len(item) > 2 else 9000 + i
            called = item[3] if len(item) > 3 else 0
            riichi = item[4] if len(item) > 4 else 0
            db.conn.execute(
                "INSERT INTO round_discards(round_id, seq, seat, wall_seq, tile, is_tsumogiri,"
                " is_riichi_tile, face_down, called) VALUES(?,?,?,?,?,0,?,0,?)",
                (rid, i + 1, seat, wseq, tile, riichi, called))


def main() -> int:
    print("=" * 70)
    print(" 天马麻将 · Card02 Skill2「换牌」")
    print("=" * 70)

    # ── 1. 正常换牌 ───────────────────────────────────────────────
    print("\n① 三张手牌 ↔ 三张牌河牌")
    db = tg.fresh_db("swap")
    rid, _m, _u = tg.new_round(db, seed=81)
    tg.set_hand(db, rid, 0, parse_hand("1p5s9m1234567m123z") + ["bai"], drawn="bai")
    put_river(db, rid, [(1, "3p"), (2, "7m"), (3, "nan")])
    g = at_discard(Game(db, rid), 0)
    before = sorted(g.hand(0))
    r = g.swap_river(0, ["1p", "5s", "9m"], [1, 2, 3])
    check("返回换进来的三张", r["got"], ["3p", "7m", "nan"])
    after = sorted(g.hand(0))
    check("手牌张数不变", len(after), len(before))
    check("拿出了 1p/5s/9m", [t for t in ("1p", "5s", "9m") if t in after], [])
    check("换进了 3p/7m/nan", [t for t in ("3p", "7m", "nan") if t in after],
          ["3p", "7m", "nan"])
    check("技能标记为已用", g.skill_used(0, 2, 2), True)
    check("换进来的牌里有一张算「刚摸到的」", g.drawn_tile(0) is not None, True)
    check("换牌后只能摸切（state）", g.state_for(0).get("must_tsumogiri"), True)

    rows = db._rows("SELECT seq, tile, face_down FROM round_discards "
                    "WHERE round_id=? ORDER BY seq", (rid,))
    check("牌河那三张变成我打出的暗牌",
          [(int(x["tile"] == "1p"), int(x["tile"] == "5s"), int(x["tile"] == "9m"))
           for x in rows if int(x["face_down"]) == 1],
          [(1, 0, 0), (0, 1, 0), (0, 0, 1)])
    check("三张都标了 face_down", sum(int(x["face_down"]) for x in rows), 3)

    # ── 2. 暗置的牌不进入振听判定 ─────────────────────────────────
    print("\n② 暗置牌不算别人「打出去的牌」")
    check("正常牌河（含暗牌）能看到 1p", "1p" in g.discards(1), True)
    check("振听用的牌河不含 1p", "1p" in g.discards_for_furiten(1), False)

    # ── 3. 一次性 ────────────────────────────────────────────────
    print("\n③ 本小局只能一次")
    try:
        g.swap_river(0, ["2m", "3m", "4m"], [1, 2, 3])
        check("再次发动被拒绝", False)
    except RuleError as e:
        check("再次发动被拒绝", "用过" in str(e))

    # ── 4. 第十三巡前（摸牌次数 <= 12）────────────────────────────
    print("\n④ 第十三巡之后不能发动")
    db2 = tg.fresh_db("swap_late")
    rid2, _m2, _u2 = tg.new_round(db2, seed=82)
    tg.set_hand(db2, rid2, 0, parse_hand("1p5s9m1234567m123z") + ["bai"], drawn="bai")
    put_river(db2, rid2, [(1, "3p"), (2, "7m"), (3, "nan")])
    with db2.tx():
        for _ in range(12):                       # 已经打完 12 巡
            db2.conn.execute(
                "INSERT INTO round_actions(round_id, seq, seat, action, payload) "
                "VALUES(?, ?, 0, 'discard', '{}')", (rid2, 200 + _))
    g2 = at_discard(Game(db2, rid2), 0)
    check("已经打完 12 巡", g2.turn_count(0), 12)
    try:
        g2.swap_river(0, ["1p", "5s", "9m"], [1, 2, 3])
        check("第十三巡后拒绝", False)
    except RuleError as e:
        check("第十三巡后拒绝", "第十三巡" in str(e))

    # 12 次以内可以
    db3 = tg.fresh_db("swap_early")
    rid3, _m3, _u3 = tg.new_round(db3, seed=83)
    tg.set_hand(db3, rid3, 0, parse_hand("1p5s9m1234567m123z") + ["bai"], drawn="bai")
    put_river(db3, rid3, [(1, "3p"), (2, "7m"), (3, "nan")])
    with db3.tx():
        for k in range(11):
            db3.conn.execute(
                "INSERT INTO round_actions(round_id, seq, seat, action, payload) "
                "VALUES(?, ?, 0, 'discard', '{}')", (rid3, 100 + k))
    g3 = at_discard(Game(db3, rid3), 0)
    check("第 12 巡仍可发动", g3.swap_river(0, ["1p", "5s", "9m"], [1, 2, 3])["got"],
          ["3p", "7m", "nan"])

    # ── 5. 不能换的牌 ────────────────────────────────────────────
    print("\n⑤ 被鸣走 / 立直宣言牌不能换")
    db4 = tg.fresh_db("swap_bad")
    rid4, _m4, _u4 = tg.new_round(db4, seed=84)
    tg.set_hand(db4, rid4, 0, parse_hand("1p5s9m1234567m123z") + ["bai"], drawn="bai")
    put_river(db4, rid4, [(1, "3p", 9001, 1, 0),      # 被碰走了
                          (2, "7m", 9002, 0, 1),      # 立直宣言牌
                          (3, "nan", 9003, 0, 0)])
    g4 = at_discard(Game(db4, rid4), 0)
    try:
        g4.swap_river(0, ["1p", "5s", "9m"], [1, 2, 3])
        check("被鸣走的牌要拒绝", False)
    except RuleError as e:
        check("被鸣走的牌要拒绝", "吃碰杠" in str(e))
    try:
        g4.swap_river(0, ["1p", "5s", "9m"], [2, 3, 1])
        check("立直宣言牌要拒绝", False)
    except RuleError as e:
        check("立直宣言牌要拒绝", "立直" in str(e))

    # ── 6. 参数校验：1~3 张、两边张数相等、牌河不重复、手牌必须在手上 ──
    print("\n⑥ 参数校验")
    try:
        g4.swap_river(0, ["1p", "5s", "9m"], [3, 3, 3])
        check("牌河不能重复", False)
    except RuleError as e:
        check("牌河不能重复", "不能重复" in str(e))
    try:
        g4.swap_river(0, ["1p", "5s", "9m"], [1, 2])
        check("两边张数不等要拒绝", False)
    except RuleError as e:
        check("两边张数不等要拒绝", "同样张数" in str(e))
    try:
        g4.swap_river(0, ["1p", "1p", "9m"], [1, 2, 3])
        check("手牌张数不够要拒绝", False)
    except RuleError as e:
        check("手牌张数不够要拒绝", "手里没有" in str(e))
    try:
        g4.swap_river(0, [], [])
        check("不能一张都不选", False)
    except RuleError as e:
        check("不能一张都不选", "1~3 张" in str(e))

    # ── 6b. 只换 2 张也行 ─────────────────────────────────────────
    print("\n⑥b 2 张也能换")
    db4b = tg.fresh_db("swap_two")
    rid4b, _m4b, _u4b = tg.new_round(db4b, seed=86)
    tg.set_hand(db4b, rid4b, 0, parse_hand("1p5s9m1234567m123z") + ["bai"], drawn="bai")
    put_river(db4b, rid4b, [(1, "3p"), (2, "7m"), (3, "nan")])
    g4b = at_discard(Game(db4b, rid4b), 0)
    r4b = g4b.swap_river(0, ["1p", "5s"], [1, 2])
    check("2 张换成功", r4b.get("got"), ["3p", "7m"])
    g4b2 = Game(db4b, rid4b)
    h4b = sorted(g4b2.hand(0))
    check("拿到了 3p/7m", [t for t in ("3p", "7m") if t in h4b], ["3p", "7m"])
    check("换出去 1p/5s", [t for t in ("1p", "5s") if t in h4b], [])
    check("只用了 2 个牌河位置",
          sum(int(x["face_down"]) for x in db4b._rows(
              "SELECT face_down FROM round_discards WHERE round_id=?", (rid4b,))), 2)

    # ── 7. 重发同一个请求（客户端没收到回应）→ 直接返回上次结果 ────────
    print("\n◎ 重发请求（幂等）")
    db5 = tg.fresh_db("swap_idem")
    rid5, _m5, _u5 = tg.new_round(db5, seed=85)
    tg.set_hand(db5, rid5, 0, parse_hand("1p5s9m1234567m123z") + ["bai"], drawn="bai")
    put_river(db5, rid5, [(1, "3p", 9001), (2, "7m", 9002), (3, "nan", 9003)])
    g5 = at_discard(Game(db5, rid5), 0)
    first = g5.swap_river(0, ["1p", "5s", "9m"], [1, 2, 3])
    try:
        again = g5.swap_river(0, ["1p", "5s", "9m"], [1, 2, 3])
        check("同参数重发不报错", True)
        check("同参数重发返回同样的三张", again.get("got"), first.get("got"))
    except RuleError as e:
        check("同参数重发不报错", False)
    try:
        g5.swap_river(0, ["1p", "5s", "9m"], [3, 2, 1])
        check("换一组参数仍然拒绝", False)
    except RuleError as e:
        check("换一组参数仍然拒绝", "已经用过" in str(e))

    # ── 8. 换完之后只能摸切（bug3）────────────────────────────────
    print("\n◎ 换完之后只能摸切")
    check("state 里标记了只能摸切", g5.state_for(0).get("must_tsumogiri"), True)
    check("别人没有这个标记", g5.state_for(1).get("must_tsumogiri"), False)
    drawn5 = g5.drawn_tile(0)
    other5 = next(t for t in g5.hand(0) if t != drawn5)
    try:
        g5.act(0, "discard", tile=other5)
        check("手切被拒绝", False)
    except RuleError as e:
        check("手切被拒绝", "只能摸切" in str(e))
    ev5 = g5.act(0, "discard", tile=drawn5)
    check("摸切可以打出去", ev5.get("event"), "discard")
    check("打出去的是刚摸那张", (ev5.get("tile") if ev5.get("event") == "discard" else ""), drawn5)

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
