# -*- coding: utf-8 -*-
"""Card04 Skill2「自风」自测
跑法： python test_card04_s2.py
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")

from game import Game, RuleError  # noqa: E402
import skills  # noqa: E402
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


def new_round(db, seed: int, dealer: int = 0) -> int:
    uids = [db.create_user(f"sw{seed}_{i}") for i in range(4)]
    room = db.create_room(uids[0])
    for u in uids[1:]:
        db.join_room(room["room_code"], u)
    match = db.start_match(room["room_id"], seed=seed)
    rid = db.start_round(match, "dong", 1, honba=0, dealer_seat=dealer, seed=seed)
    g = Game(db, rid)
    g.start()
    while not g.deal_done():
        g.deal_step()
    return rid


def setup(db, rid, owner=0):
    tg.set_hand(db, rid, 0, parse_hand("5m6m7m1p2p3p1s2s3s5z5z1z2z"))
    tg.set_hand(db, rid, 1, parse_hand("1m2m3m4p5p6p7s8s9s2z2z3z4z"))
    g = Game(db, rid)
    g.round_phase = "play"
    g.self_wind.add(owner)
    g.save_flags()
    return g


def main() -> int:
    print("=" * 70)
    print(" 天马麻将 · Card04 Skill2「自风」")
    print("=" * 70)

    # ── 1. 登记 ──────────────────────────────────────────────────
    print("\n① 技能登记")
    check("skills.has(4,2)", skills.has(4, 2))
    check("名字是「自风」", skills.info(4, 2).get("name"), "自风")
    check("时机是摸牌（别人摸到自风时）", skills.timing(4, 2), "draw")

    # ── 2. 风神发动 → 自风自动生效 ─────────────────────────────
    print("\n② 风神发动后自动生效")
    db0 = tg.fresh_db("sw_link")
    rid0 = new_round(db0, seed=151)
    g0 = Game(db0, rid0)
    g0.deal_flow = None
    g0._start_deal_swap(0, 4, 1)
    check("自风自动记上", 0 in g0.self_wind)
    check("state 里 self_wind=True", g0.state_for(0).get("self_wind"), True)
    check("别人那边是 False", g0.state_for(1).get("self_wind"), False)
    g0b = Game(db0, rid0)
    check("落库后还在", 0 in g0b.self_wind)

    # ── 3. 别人摸到我的自风 → 卡住换牌 ────────────────────────
    print("\n③ 下家摸到我的自风（东）")
    db = tg.fresh_db("sw_trigger")
    rid = new_round(db, seed=152, dealer=0)
    g = setup(db, rid, owner=0)
    check("0 号位自风是东", g.seat_wind(0), "dong")
    tg.set_next_draw(db, rid, "dong")
    g = Game(db, rid)
    g.turn = 1
    g.phase = "draw"
    g.save_flags()
    ev = g.advance()
    check("进入 wind_swap 阶段", g.phase, "wind_swap")
    view = g.state_for(0).get("wind_swap") or {}
    check("要我（0 号位）来换", view.get("owner"), 0)
    check("是 1 号位摸到的", view.get("from"), 1)
    check("摸到的是东", view.get("tile"), "dong")
    check("摸牌的人不能打牌", g.legal_actions(1), [])
    check("事件里报了触发", ev.get("event"), "draw")

    # 别人不能替他换
    try:
        g.wind_swap_apply(1, "1m")
        check("不是自己的自风不能换", False)
    except RuleError as e:
        check("不是自己的自风不能换", "不是你的" in str(e))
    try:
        g.wind_swap_apply(0, "zhong")
        check("手里没有的牌不能换", False)
    except RuleError as e:
        check("手里没有的牌不能换", "手里没有" in str(e))

    # ── 4. 换牌 ─────────────────────────────────────────────────
    print("\n④ 换牌：我的 5m ↔ 他摸到的东")
    r = g.wind_swap_apply(0, "5m")
    check("换到东", r.get("got"), "dong")
    check("换出去 5m", r.get("tile"), "5m")
    check("换完进入打牌阶段", g.phase, "discard")
    check("轮到摸牌的人", g.turn, 1)
    g = Game(db, rid)
    check("东到我手里了", "dong" in g.hand(0), True)
    check("我手牌还是 13 张", len(g.hand(0)), 13)
    check("他拿到了 5m 并且算刚摸到", g.drawn_tile(1), "5m")
    check("他手牌还是 14 张", len(g.hand(1)), 14)
    check("他可以正常打牌了", "discard" in {a["action"] for a in g.legal_actions(1)}, True)

    # ── 5. 不该触发的情况 ──────────────────────────────────────
    print("\n⑤ 不该触发的情况")
    # 摸到的不是我的自风
    db5 = tg.fresh_db("sw_nowind")
    rid5 = new_round(db5, seed=153, dealer=0)
    setup(db5, rid5)
    tg.set_next_draw(db5, rid5, "nan")
    g5 = Game(db5, rid5)
    g5.turn, g5.phase = 1, "draw"
    g5.save_flags()
    g5.advance()
    check("摸到南不触发（我的自风是东）", g5.phase, "discard")

    # 自己摸到自己的自风
    db6 = tg.fresh_db("sw_self")
    rid6 = new_round(db6, seed=154, dealer=0)
    setup(db6, rid6)
    tg.set_next_draw(db6, rid6, "dong")
    g6 = Game(db6, rid6)
    g6.turn, g6.phase = 0, "draw"
    g6.save_flags()
    g6.advance()
    check("自己摸自己的自风不触发", g6.phase, "discard")

    # 立直后失效
    db7 = tg.fresh_db("sw_riichi")
    rid7 = new_round(db7, seed=155, dealer=0)
    setup(db7, rid7)
    with db7.tx():
        db7.conn.execute("INSERT INTO round_riichi(round_id, seat) VALUES(?,?)", (rid7, 0))
    tg.set_next_draw(db7, rid7, "dong")
    g7 = Game(db7, rid7)
    g7.turn, g7.phase = 1, "draw"
    g7.save_flags()
    g7.advance()
    check("立直后失效", g7.phase, "discard")

    # ── 6. 兜底跳过 ─────────────────────────────────────────────
    print("\n⑥ 没人在操作时兜底跳过")
    db8 = tg.fresh_db("sw_pass")
    rid8 = new_round(db8, seed=156, dealer=0)
    setup(db8, rid8)
    tg.set_next_draw(db8, rid8, "dong")
    g8 = Game(db8, rid8)
    g8.turn, g8.phase = 1, "draw"
    g8.save_flags()
    g8.advance()
    check("先触发", g8.phase, "wind_swap")
    g8.wind_swap_pass()
    check("跳过后继续打牌", g8.phase, "discard")
    check("轮到摸牌的人", g8.turn, 1)
    check("东还留在他手里", "dong" in g8.hand(1), True)

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
