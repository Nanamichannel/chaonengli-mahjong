# -*- coding: utf-8 -*-
"""Card05 Skill1「策略」自测
跑法： python test_card05.py
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")

from game import Game, RuleError  # noqa: E402
from rules import wallmodel  # noqa: E402
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


def new_round(db, seed: int, owner=True) -> int:
    uids = [db.create_user(f"c05{seed}_{i}") for i in range(4)]
    room = db.create_room(uids[0])
    for u in uids[1:]:
        db.join_room(room["room_code"], u)
    match = db.start_match(room["room_id"], seed=seed)
    rid = db.start_round(match, "dong", 1, honba=0, dealer_seat=0, seed=seed)
    g = Game(db, rid)
    g.start()
    while not g.deal_done():
        g.deal_step()
    orders = [[5, 1, 2, 3, 4], [2, 1, 3, 4, 6], [2, 3, 4, 6, 7], [1, 3, 4, 6, 7]]
    if not owner:
        orders[0] = [1, 2, 3, 4, 6]
    body = {"seats": [{"ready": False, "hand": [], "picks": [], "order": o} for o in orders],
            "phase": "playing"}
    with db.tx():
        db.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('lobby_state', ?)",
                        (json.dumps(body, ensure_ascii=False),))
    return rid


def safe_hands(db, rid):
    """其他三家给一手没法鸣牌的牌，方便测试「没人鸣 → 额外摸切」。"""
    hand = parse_hand("1m4m7m1p4p7p1s4s7s1z2z3z5z")
    for s in (1, 2, 3):
        tg.set_hand(db, rid, s, hand)


def add_river(db, rid, seq, seat, tile, wseq, down=False, called=0, riichi=0):
    with db.tx():
        db.conn.execute(
            "INSERT INTO round_discards(round_id, seq, seat, wall_seq, tile,"
            " is_tsumogiri, is_riichi_tile, face_down, called) VALUES(?,?,?,?,?,1,?,?,?)",
            (rid, seq, seat, wseq, tile, riichi, 1 if down else 0, called))


def main() -> int:
    print("=" * 70)
    print(" 天马麻将 · Card05 Skill1「策略」")
    print("=" * 70)

    # ── 1. 登记 ──────────────────────────────────────────────────
    print("\n① 技能登记")
    check("skills.has(5,1)", skills.has(5, 1))
    check("名字是「策略」", skills.info(5, 1).get("name"), "策略")
    check("时机是摸牌", skills.timing(5, 1), "draw")

    # ── 2. 计数：别人画板害我重摸 ──────────────────────────────
    print("\n② 计数：别人的技能害我重摸")
    db = tg.fresh_db("c05_count")
    rid = new_round(db, seed=201)
    tg.set_hand(db, rid, 0, parse_hand("123m456p789s1z2z3z5z"))
    safe_hands(db, rid)
    g = Game(db, rid)
    check("0 号位持有策略", g.owns_card05(0))
    g.boards[1] = {"tiles": ["dong"], "delivered": [], "pending": []}
    g.save_flags()
    tg.set_next_draw(db, rid, "dong")
    g = Game(db, rid)
    g.turn, g.phase = 0, "draw"
    g.save_flags()
    g.advance()
    check("计数 +1", g.card05_counter.get(0), 1)
    check("给了一次换牌机会", 0 in g.card05_offer)
    check("state 里报出来", g.state_for(0)["card05"]["counter"], 1)
    check("别人（没卡）没有计数", g.state_for(1)["card05"]["counter"], 0)

    # ── 2b. 计数器上限 1（用户口径）────────────────────────────
    print("\n②b 计数器上限 1")
    g = Game(db, rid)
    g.card05_counter[0] = 0
    g.save_flags()
    g.card05_interfere(0, 1, "害一次")
    check("害一次 → 1 点", g.card05_counter.get(0), 1)
    g.card05_interfere(0, 2, "再害一次")
    check("再害一次 → 还是 1 点（不叠加）", g.card05_counter.get(0), 1)
    check("换牌机会照给", 0 in g.card05_offer)
    g2 = Game(db, rid)
    check("落库后也是 1", g2.card05_counter.get(0), 1)

    # ── 3. 额外摸切 ─────────────────────────────────────────────
    print("\n③ 花 1 点：切牌后再摸一张再切")
    g = Game(db, rid)
    r = g.card05_extra_activate(0)
    check("发动成功", r.get("extra"), True)
    check("计数变成 0", g.card05_counter.get(0), 0)
    g.card05_interfere(0, 1, "花完又被害")
    check("花完还能再攒 1 点", g.card05_counter.get(0), 1)
    g.card05_counter[0] = 0
    g.save_flags()
    check("挂上额外摸切", 0 in g.card05_extra)
    try:
        g.card05_extra_activate(0)
        check("同一回合不能重复发动", False)
    except RuleError as e:
        check("同一回合不能重复发动", "已经发动" in str(e))

    g = Game(db, rid)
    g.round_phase = "play"
    g.turn, g.phase = 0, "discard"
    n0 = len(g.hand(0))
    g.act(0, "discard", tile="1m")
    check("切牌后立刻又摸了一张", g.phase, "discard")
    check("还是轮到我", g.turn, 0)
    check("手牌回到 14 张（摸切完 14）", len(g.hand(0)), n0)
    check("额外摸切用掉了", 0 in g.card05_extra, False)
    g.act(0, "discard", tile=g.drawn_tile(0) or "1p")
    check("第二次切完轮到下家", g.turn, 1)

    # ── 4. 计数为 0 不能发动 ───────────────────────────────────
    print("\n④ 计数为 0")
    db4 = tg.fresh_db("c05_zero")
    rid4 = new_round(db4, seed=202)
    tg.set_hand(db4, rid4, 0, parse_hand("123m456p789s1z2z3z5z5z"), drawn="bai")
    g4 = Game(db4, rid4)
    g4.turn, g4.phase, g4.round_phase = 0, "discard", "play"
    g4.save_flags()
    try:
        g4.card05_extra_activate(0)
        check("计数为 0 拒绝", False)
    except RuleError as e:
        check("计数为 0 拒绝", "计数器" in str(e))

    # ── 5. 和弃牌交换 ─────────────────────────────────────────
    print("\n⑤ 和弃牌交换（明置 / 暗置）")
    db5 = tg.fresh_db("c05_river")
    rid5 = new_round(db5, seed=203)
    tg.set_hand(db5, rid5, 0, parse_hand("123m456p789s1z2z3z5z"))
    g5 = Game(db5, rid5)
    g5.turn, g5.phase, g5.round_phase = 0, "discard", "play"
    g5.card05_counter[0] = 1
    g5.card05_offer[0] = {"by": 1, "reason": "test"}
    g5.save_flags()
    add_river(db5, rid5, 1, 2, "9p", 700)
    add_river(db5, rid5, 2, 3, "nan", 701, down=True)
    g5 = Game(db5, rid5)
    r5 = g5.card05_swap(0, "1m", "river", river_seq=1)
    check("换到 9p", r5.get("got"), "9p")
    check("是明置位置", r5.get("face_down"), False)
    g5 = Game(db5, rid5)
    check("手里多了 9p", "9p" in g5.hand(0), True)
    check("1m 去了牌河", db5._one(
        "SELECT tile FROM round_discards WHERE round_id=? AND seq=1", (rid5,)), "1m")
    check("牌河这张还是明置", db5._one(
        "SELECT face_down FROM round_discards WHERE round_id=? AND seq=1", (rid5,)), 0)
    check("换完机会用掉了", 0 in g5.card05_offer, False)

    # 机会发在「别人的回合」里也要能换（画板转移就是那一刻发的）
    g5.card05_offer[0] = {"by": 1, "reason": "test"}
    g5.turn, g5.phase = 2, "discard"
    g5.save_flags()
    add_river(db5, rid5, 5, 2, "4s", 705)
    r5c = g5.card05_swap(0, "bai", "river", river_seq=5)
    check("不是我的回合也能换（offer 在就行）", r5c.get("got"), "4s")
    g5.turn, g5.phase = 0, "discard"
    g5.save_flags()

    g5.card05_offer[0] = {"by": 1, "reason": "test"}
    g5.save_flags()
    r5b = g5.card05_swap(0, "2m", "river", river_seq=2)
    check("换到暗置牌的牌", r5b.get("got"), "nan")
    check("是暗置位置", r5b.get("face_down"), True)
    check("1m? 换进去的 2m 仍暗置", db5._one(
        "SELECT face_down FROM round_discards WHERE round_id=? AND seq=2", (rid5,)), 1)

    # 不能换被鸣走 / 立直宣言牌
    add_river(db5, rid5, 3, 2, "7s", 702, called=1)
    add_river(db5, rid5, 4, 2, "8s", 703, riichi=1)
    g5.card05_offer[0] = {"by": 1, "reason": "test"}
    g5.save_flags()
    for name, seq, want in [("被鸣走的不给换", 3, "吃碰杠"), ("立直宣言牌不给换", 4, "立直")]:
        g5 = Game(db5, rid5)
        g5.card05_offer[0] = {"by": 1, "reason": "test"}
        try:
            g5.card05_swap(0, "3m", "river", river_seq=seq)
            check(name, False)
        except RuleError as e:
            check(name, want in str(e))

    # ── 6. 和王牌交换 ─────────────────────────────────────────
    print("\n⑥ 和王牌交换")
    db6 = tg.fresh_db("c05_dead")
    rid6 = new_round(db6, seed=204)
    tg.set_hand(db6, rid6, 0, parse_hand("123m456p789s1z2z3z5z"))
    g6 = Game(db6, rid6)
    g6.turn, g6.phase, g6.round_phase = 0, "discard", "play"
    g6.card05_offer[0] = {"by": 1, "reason": "test"}
    g6.save_flags()
    n = g6.wall_first_stack()
    k = wallmodel.wrap_stack(n - 1)
    a, b = wallmodel.tile_nos_of_stack(k)
    sa, sb = wallmodel.seq_of_tile(a), wallmodel.seq_of_tile(b)
    ta = db6._one("SELECT tile FROM round_wall WHERE round_id=? AND seq=?", (rid6, sa))
    tb = db6._one("SELECT tile FROM round_wall WHERE round_id=? AND seq=?", (rid6, sb))
    r6 = g6.card05_swap(0, "1m", "dead", stack=k, half="top")
    check("换到王牌上面那张", r6.get("got"), ta)
    check("是暗置位置", r6.get("face_down"), True)
    check("王牌那墩上面变成 1m", db6._one(
        "SELECT tile FROM round_wall WHERE round_id=? AND seq=?", (rid6, sa)), "1m")
    check("下面那张没动", db6._one(
        "SELECT tile FROM round_wall WHERE round_id=? AND seq=?", (rid6, sb)), tb)
    check("王牌还在墙上（没被拿走）", db6._one(
        "SELECT dealt_to FROM round_wall WHERE round_id=? AND seq=?", (rid6, sa)), None)
    g6 = Game(db6, rid6)
    check("手里拿到王牌那张", ta in g6.hand(0), True)
    check("手里没有 1m 了", "1m" in g6.hand(0), False)

    # 不是王牌的墩要拒绝
    g6.card05_offer[0] = {"by": 1, "reason": "test"}
    try:
        g6.card05_swap(0, "2m", "dead", stack=wallmodel.wrap_stack(n + 5), half="top")
        check("普通牌墩不给换", False)
    except RuleError as e:
        check("普通牌墩不给换", "王牌" in str(e))

    # 取消
    g6.card05_offer[0] = {"by": 1, "reason": "test"}
    g6.card05_cancel(0)
    check("可以取消换牌机会", 0 in g6.card05_offer, False)

    # ── 7. 被看手牌：盖三张 ───────────────────────────────────
    print("\n⑦ 被看手牌：盖住三张")
    db7 = tg.fresh_db("c05_view")
    rid7 = new_round(db7, seed=205)
    tg.set_hand(db7, rid7, 0, parse_hand("123m456p789s1z2z3z5z"))
    g7 = Game(db7, rid7)
    v = g7.card05_view_hand(1, 0)
    check("第一次看被挡住", v.get("blocked"), True)
    check("0 号位收到盖牌请求", g7.state_for(0)["card05"]["hide_request"], True)
    h = g7.card05_hide(0, ["1m", "2m", "3m"])
    check("盖了三张", h.get("hidden"), 3)
    v2 = g7.card05_view_hand(1, 0)
    check("第二次能看了", v2.get("blocked"), False)
    hand = v2.get("hand") or []
    check("盖住的三张看不到", [t for t in hand if t in ("1m", "2m", "3m")], [])
    check("其他牌还能看到", "bai" in hand, True)
    check("看别人的手牌不受影响", g7.card05_view_hand(1, 2).get("blocked"), False)

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
