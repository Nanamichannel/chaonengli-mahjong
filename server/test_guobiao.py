# -*- coding: utf-8 -*-
"""【国标】(01-1) 一定和牌的听牌判定（用户口径 2026-11-07）：

  · 特殊番种 = 五门齐 / 花龙 / 三色三步高；
  · 番种没凑齐时：切一张后听的牌必须「和到能凑出番种」，否则不能一定和牌；
  · 宣言的那张也必须是「和到能凑出番种」的和张；
  · 已经凑齐（某番种换任何待牌都保住）→ 全部放开 = 任选胡张；
  · 摸牌前只换宣言的那一张，牌山里没有就什么都不换。

跑法：cd N:\\apps\\tianma\\server; python test_guobiao.py
"""
from __future__ import annotations

import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from game import Game                    # noqa: E402
from tiles import parse_hand             # noqa: E402
import test_game as tg                   # noqa: E402

OK = 0
BAD = 0
ORD = [[1, 1, 2, 3, 4], [2, 2, 3, 4, 5], [3, 3, 4, 5, 6], [4, 4, 5, 6, 7]]
OTHER = "1m2m3m4p5p6p7s8s9s1p1p1p2s"


def check(cond, msg, extra=""):
    global OK, BAD
    if cond:
        OK += 1
    else:
        BAD += 1
        print("  [FAIL]", msg, extra)


def build(tag, seed, hand14, drawn):
    db = tg.fresh_db(tag)
    rid, _m, _u = tg.new_round(db, seed=seed)
    with db.tx():
        db.conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES('lobby_state', ?)",
            (json.dumps({"seats": [{"ready": True, "hand": [], "picks": [], "order": list(o)}
                                   for o in ORD], "phase": "play"}, ensure_ascii=False),))
    tg.set_hand(db, rid, 0, parse_hand(hand14) + [drawn], drawn=drawn)
    for s in (1, 2, 3):
        tg.set_hand(db, rid, s, parse_hand(OTHER))
    g = Game(db, rid)
    g.round_phase = "play"
    g.phase, g.turn = "discard", 0
    g.save_flags()
    return db, rid


def at(db, rid):
    g = Game(db, rid)
    g.round_phase = "play"
    g.phase, g.turn = "discard", 0
    return g


def main() -> int:
    print("=" * 74)
    print(" Card01 S1【国标】：听牌张必须能和成特殊番种")
    print("=" * 74)

    # ── ① 番种没凑齐：只有能和成番种的那张能宣言 ─────────────────
    # 123m 234p 34s 678m 99p + 摸 9m → 切 9m 听 2s/5s
    #   和 5s → 123m 234p 345s = 三色三步高 ✔
    #   和 2s → 234s 凑不出（1,2,2）✘
    print("\n① 差一个番种：只有 5s 能宣言")
    db, rid = build("gb1", 61, "123m234p34s678m99p", "9m")
    g = at(db, rid)
    waits = g.yiding_waits(0)
    check("2s 是听牌张", "2s" in waits, "听牌张里应含 2s（实得 %s）" % sorted(waits))
    check("5s 是听牌张", "5s" in waits, "听牌张里应含 5s（实得 %s）" % sorted(waits))
    kinds = g.guobiao_kinds(0)
    check("5s 可以宣言（能和成三色三步高）", "5s" in kinds, "guobiao_kinds=%s" % kinds)
    check("2s 不在可宣言里（和到凑不出番种）", "2s" not in kinds,
          "guobiao_kinds=%s" % kinds)
    check("仍然能发动国标", g.guobiao_can(0), "guobiao_can 应该 True")
    try:
        g.guobiao_declare(0, "2s")
        check("宣言 2s 要被拒", False)
    except Exception as e:
        check("宣言 2s 要被拒", "特殊番种" in str(e) or "凑不出" in str(e))
    r = g.guobiao_declare(0, "5s")
    check("宣言 5s 成功", r.get("kind"), "5s")

    # 切牌校验：切 9m 还能听 5s 且保番种；切别的就不是听牌形了
    g2 = at(db, rid)
    check("切 9m 合法（仍听 5s）", g2._yiding_cut_ok(0, "9m"), "_yiding_cut_ok(9m)")
    check("切 1m 不合法（不听 5s 了）", not g2._yiding_cut_ok(0, "1m"), "_yiding_cut_ok(1m)")

    # 摸牌前：只换宣言的那张 5s
    g3 = at(db, rid)
    hit = g3.wall_find({"5s"})
    if hit:
        ok = g3._yiding_pre_swap(0)
        nxt = g3._draw_next_info(0) or {}
        check("牌山里有 5s → 换到下一张", bool(ok) and str(nxt.get("tile", "")) == "5s",
              "pre_swap=%s next=%s" % (ok, nxt.get("tile")))
    else:
        check("牌山里没有 5s → 什么都不换", g3._yiding_pre_swap(0), False)

    # ── ② 切出去听的牌全都凑不出番种 → 不能一定和牌 ───────────────
    print("\n② 听的牌都凑不出番种 → 国标不能发动")
    db2, rid2 = build("gb2", 62, "123m456m789m123p5p", "4p")
    g5 = at(db2, rid2)
    wk = g5.yiding_waits(0)
    check("确实听牌（5p）", "5p" in wk, "听牌张=%s" % sorted(wk))
    check("guobiao_discards 为空", g5.guobiao_discards(0), [])
    check("国标不能发动", g5.guobiao_can(0), False)
    try:
        g5.guobiao_declare(0, "5p")
        check("直接发也要拒", False)
    except Exception:
        check("直接发也要拒", True)

    # ── ③ 已经凑齐（花龙）→ 任选胡张 ─────────────────────────────
    # 123m 456p 789s 99p 78p + 摸 9m → 切 9m 听 6p/9p，两张都和成花龙
    print("\n③ 番种已经凑齐 → 任选胡张")
    db3, rid3 = build("gb3", 63, "123m456p789s99p78p", "9m")
    g6 = at(db3, rid3)
    k3 = set(g6.guobiao_kinds(0))
    check("6p 能宣言", "6p" in k3, "guobiao_kinds=%s" % sorted(k3))
    check("9p 也能宣言（任选）", "9p" in k3, "guobiao_kinds=%s" % sorted(k3))
    r3 = g6.guobiao_declare(0, "9p")
    check("宣言 9p 成功", r3.get("kind"), "9p")

    # ── ④ 普通「一定和牌」不受这套限制 ───────────────────────────
    print("\n④ 普通一定和牌：不要求番种（2s 也能宣言）")
    db4, rid4 = build("gb4", 64, "123m234p34s678m99p", "9m")
    g7 = at(db4, rid4)
    g7.yiding = {0}
    g7.save_flags()
    g7 = at(db4, rid4)
    check("一定和牌可用", g7.yiding_can(0), "yiding_can")
    r4 = g7.yiding_declare(0, "2s")
    check("宣言 2s 成功（不要求番种）", r4.get("kind"), "2s")

    # ── ⑤ state 下发可宣言牌种 ───────────────────────────────────
    print("\n⑤ state 里的 guobiao_kinds")
    db5, rid5 = build("gb5", 65, "123m234p34s678m99p", "9m")
    g8 = at(db5, rid5)
    st = g8.state_for(0)
    check("state 带 guobiao_kinds", isinstance(st.get("guobiao_kinds"), list),
          type(st.get("guobiao_kinds")))
    check("state 里 5s 可宣言", "5s" in (st.get("guobiao_kinds") or []),
          str(st.get("guobiao_kinds")))
    check("state 里 2s 不可宣言", "2s" not in (st.get("guobiao_kinds") or []),
          str(st.get("guobiao_kinds")))

    print("\n" + "=" * 74)
    print(f" 通过 {OK} / 失败 {BAD}")
    print("=" * 74)
    return 0 if BAD == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
