# -*- coding: utf-8 -*-
"""策略·额外摸切 必须走「普通摸牌」那一套钩子（以前自己摸一张就完事）

覆盖：海神（摸到万子要强制借牌）、深山（摸到指定牌要弹窗）。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")

from game import Game  # noqa: E402
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


def setup(tag, seed, drawn="bai"):
    db = tg.fresh_db(tag)
    rid, _m, _u = tg.new_round(db, seed=seed)
    # 0 号位手持「策略」+ 1 点计数，已经摸完牌该打了（drawn 必须是最后一张）
    tg.set_hand(db, rid, 0, parse_hand("123m456p789s1z2z3z") + ["5m", drawn], drawn=drawn)
    tg.set_hand(db, rid, 1, parse_hand("1m4m7m1p4p7p1s4s7s1z2z3z5z"))
    tg.set_hand(db, rid, 2, parse_hand("2m5m8m2p5p8p2s5s8s2z3z4z5z"))
    tg.set_hand(db, rid, 3, parse_hand("3m6m9m3p6p9p3s6s9s1z2z3z5z"))
    g = Game(db, rid)
    g.round_phase = "play"
    g.turn, g.phase = 0, "discard"
    g.card05_counter[0] = 1
    g.granted = {0: {5}}
    g.save_flags()
    return db, rid


def main() -> int:
    print("=" * 66)
    print(" 天才麻将少女 · 策略「额外摸切」要走公共摸牌钩子")
    print("=" * 66)

    # ① 海神：额外摸到万子 → 必须弹借牌窗（以前不会）
    print("\n① 额外摸切摸到万子 → 海神要弹窗")
    db, rid = setup("c05x_hs", 301)
    g = Game(db, rid)
    g.granted = {0: {5}, 1: {12}}          # 1 号位持海神
    g.haishin_on = True
    g.save_flags()
    tg.set_next_draw(db, rid, "9m")        # 额外摸切摸到的那张
    g = Game(db, rid)
    g.turn, g.phase = 0, "discard"
    r = g.card05_extra_activate(0)
    check("挂上额外摸切", r.get("extra"), True)
    g.act(0, "discard", tile="bai")         # 切牌 → 没人鸣 → 额外摸
    tg.clear_claims(g)
    g = Game(db, rid)
    check("额外摸切已经用掉", 0 in g.card05_extra, False)
    check("海神被触发（phase=haishin）", g.phase, "haishin")
    check("借牌窗指向 1 号位", (g.haishin_offer or {}).get("owner"), 1)
    check("借的是刚摸的 9m", (g.haishin_offer or {}).get("tile"), "9m")
    r2 = g.haishin_give(1, "1m")
    check("换完回到打牌", g.phase, "discard")
    check("牌真的换了", r2.get("got"), "9m")

    # ② 没开海神 → 额外摸切照旧直接进打牌
    print("\n② 海神没开 → 不影响")
    db2, rid2 = setup("c05x_no", 302)
    g2 = Game(db2, rid2)
    g2.granted = {0: {5}, 1: {12}}
    g2.haishin_on = False
    g2.save_flags()
    tg.set_next_draw(db2, rid2, "9m")
    g2 = Game(db2, rid2)
    g2.turn, g2.phase = 0, "discard"
    g2.card05_extra_activate(0)
    g2.act(0, "discard", tile="bai")
    tg.clear_claims(g2)
    g2 = Game(db2, rid2)
    check("没开海神 → 直接进打牌", g2.phase, "discard")
    check("还是轮到我", g2.turn, 0)
    check("手牌 14 张", len(g2.hand(0)), 14)

    # ③ 额外摸切也要吃到「牌桌压牌」（画板）
    print("\n③ 额外摸切也要认画板压的牌")
    db3, rid3 = setup("c05x_board", 303)
    g3 = Game(db3, rid3)
    g3.granted = {0: {5}}
    g3.boards[1] = {"tiles": ["dong"], "delivered": [], "pending": []}
    g3.save_flags()
    tg.set_next_draw(db3, rid3, "dong")          # 额外摸到的第一张正好是画板要的
    g3 = Game(db3, rid3)
    g3.turn, g3.phase = 0, "discard"
    g3.card05_extra_activate(0)
    g3.act(0, "discard", tile="bai")
    tg.clear_claims(g3)
    g3 = Game(db3, rid3)
    check("多摸完仍是 14 张", len(g3.hand(0)), 14)
    check("画板那边收到了东", len((g3.boards.get(1) or {}).get("delivered") or []), 1)

    print("\n" + "=" * 66)
    print(f" 通过 {PASS} / 失败 {FAIL}")
    print("=" * 66)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
