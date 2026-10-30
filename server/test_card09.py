# -*- coding: utf-8 -*-
"""Card09 S1 / S2 自测：摸牌前 手牌 ↔ 牌河明牌

跑法： python test_card09.py
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")

from game import Game, RuleError  # noqa: E402
from tiles import parse_hand  # noqa: E402
import skills  # noqa: E402
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


def new_round(db, seed: int, orders) -> int:
    uids = [db.create_user(f"c09{seed}_{i}") for i in range(4)]
    room = db.create_room(uids[0])
    for u in uids[1:]:
        db.join_room(room["room_code"], u)
    match = db.start_match(room["room_id"], seed=seed)
    rid = db.start_round(match, "dong", 1, honba=0, dealer_seat=0, seed=seed)
    body = {"seats": [{"ready": False, "hand": [], "picks": [], "order": list(o)}
                      for o in orders],
            "phase": "playing"}
    with db.tx():
        db.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('lobby_state', ?)",
                        (json.dumps(body, ensure_ascii=False),))
    return rid


def add_river(db, rid, seq: int, seat: int, tile: str, down=False, called=0) -> None:
    with db.tx():
        db.conn.execute(
            "INSERT INTO round_discards(round_id, seq, seat, wall_seq, tile,"
            " is_tsumogiri, is_riichi_tile, face_down, called) VALUES(?,?,?,?,?,0,0,?,?)",
            (rid, seq, seat, 5000 + seq, tile, 1 if down else 0, called))


ORD_9 = [[9, 1, 2, 3, 4], [1, 2, 3, 5, 6], [1, 2, 3, 5, 7], [1, 2, 3, 5, 8]]
H_ME = parse_hand("123m456m789p12s1z")     # 13 张


def to_draw(g: Game, seat: int) -> Game:
    g.round_phase = "play"
    g.turn = seat
    g.phase = "draw"
    g.save_flags()
    return g


def next_turn(g, keep_next: bool = True):
    """模拟「下一巡」：间合每回合只能用一次，旧用例要在两次发动之间清掉标记。"""
    g.c09_turn = ""
    if not keep_next:
        g.c09_next = {}
    g.save_flags()
    return to_draw(Game(g.db, g.round_id), 0)


def main() -> int:
    print("=" * 70)
    print(" 天马麻将 · Card09 S1 / S2（摸牌前换牌河）")
    print("=" * 70)

    # ── ① 登记 ──────────────────────────────────────────────────
    print("\n① 技能登记")
    check("skills.has(9,1)", skills.has(9, 1))
    check("skills.has(9,2)", skills.has(9, 2))
    check("S1 时机是摸牌", skills.timing(9, 1), "draw")
    check("S2 时机是摸牌", skills.timing(9, 2), "draw")

    # ── ② 能不能用 ──────────────────────────────────────────────
    print("\n② 发动条件：摸牌前、持 9 号卡")
    db = tg.fresh_db("c09_gate")
    rid = new_round(db, 941, ORD_9)
    tg.set_hand(db, rid, 0, H_ME)
    tg.set_hand(db, rid, 1, H_ME)
    g = Game(db, rid)
    check("0 号持 9 号卡", g.owns_card09(0), True)
    check("1 号没有", g.owns_card09(1), False)
    g.round_phase = "play"
    g.turn = 0
    g.phase = "discard"
    g.save_flags()
    check("打牌阶段不能用", g.card09_can(0), False)
    g = to_draw(Game(db, rid), 0)
    check("摸牌前可以用", g.card09_can(0), True)
    check("不是我的回合不能用", g.card09_can(1), False)
    check("state 里 card09_can=True", g.state_for(0)["card09_can"], True)

    # ── ③ S1：换自己牌河 ────────────────────────────────────────
    print("\n③ S1：换自己牌河里的明牌")
    add_river(db, rid, 1, 0, "3m")            # 自己牌河（明置）
    add_river(db, rid, 2, 1, "5p")            # 别家牌河
    g = to_draw(Game(db, rid), 0)
    r = g.card09_swap(0, 1, "dong", 1)
    check("换到的是牌河那张", r.get("got"), "3m")
    check("下一次只能用 Skill2", int(r.get("next", 0)), 2)
    g = to_draw(Game(db, rid), 0)
    check("王手里多了 3m", g.hand(0).count("3m"), 2)
    check("手里少了一张东", g.hand(0).count("dong"), 0)
    row = g.db._row("SELECT tile, face_down FROM round_discards WHERE round_id=? AND seq=?",
                    (rid, 1))
    check("牌河那个位置变成我的手牌", row["tile"], "dong")
    check("还是明置", int(row["face_down"]), 0)
    check("state 里 next=2", g.state_for(0)["card09_next"], 2)

    # ── ④ 轮换规则 ─────────────────────────────────────────────
    print("\n④ 用过 S1 → 下一次只能 S2")
    try:
        g.card09_swap(0, 1, "1m", 2)
        check("再用 S1 要拒绝", False)
    except RuleError as e:
        check("再用 S1 要拒绝", "只能" in str(e))
    add_river(db, rid, 3, 1, "7s")
    g.c09_turn = ""                          # 模拟「下一巡」：每回合只能用一次
    g.save_flags()
    g = to_draw(Game(db, rid), 0)
    r2 = g.card09_swap(0, 2, "1m", 3)
    check("S2 可以换别家的牌", r2.get("got"), "7s")
    check("换完下一次回到 Skill1", int(r2.get("next", 0)), 1)
    g = next_turn(g)
    try:
        g.card09_swap(0, 1, "2m", 2)          # 2 号 seq 是别家的河
        check("S1 不能换别家的河", False)
    except RuleError as e:
        check("S1 不能换别家的河", "只能换自己" in str(e))

    # ── ⑤ 暗置 / 被鸣走的牌不能换 ──────────────────────────────
    print("\n⑤ 暗置牌、被鸣走的牌不能换")
    add_river(db, rid, 4, 0, "9p", down=True)
    add_river(db, rid, 5, 0, "8p", called=1)
    g = next_turn(g)
    try:
        g.card09_swap(0, 1, "2m", 4)
        check("暗置牌要拒绝", False)
    except RuleError as e:
        check("暗置牌要拒绝", "暗置" in str(e))
    g = next_turn(g)
    try:
        g.card09_swap(0, 1, "2m", 5)
        check("被鸣走的要拒绝", False)
    except RuleError as e:
        check("被鸣走的要拒绝", "吃碰杠" in str(e))

    # ── ⑥ 每行只能换一张 ───────────────────────────────────────
    print("\n⑥ 每行（6 张）只能换一张")
    db2 = tg.fresh_db("c09_row")
    rid2 = new_round(db2, 942, ORD_9)
    tg.set_hand(db2, rid2, 0, parse_hand("123m456m789p123s"))
    tg.set_hand(db2, rid2, 1, parse_hand("123m456m789p123s"))
    for i in range(7):                         # 我的牌河 7 张（第 0 行 6 张 + 第 1 行）
        add_river(db2, rid2, 10 + i, 0, "1p")
    for i in range(7):                         # 1 号的牌河 7 张
        add_river(db2, rid2, 40 + i, 1, "2p")
    g2 = to_draw(Game(db2, rid2), 0)
    r3 = g2.card09_swap(0, 1, "1m", 10)        # S1：我的第 0 行
    check("我的第 0 行先换一张（成功）", r3.get("row"), 0)
    g2 = next_turn(g2)
    r4 = g2.card09_swap(0, 2, "2m", 40)        # S2：1 号的第 0 行
    check("别家第 0 行也能换", r4.get("row"), 0)
    g2 = next_turn(g2, keep_next=False)
    try:
        g2.card09_swap(0, 1, "3m", 11)         # S1：我的第 0 行，第二次
        check("同一行第二次要拒绝", False)
    except RuleError as e:
        check("同一行第二次要拒绝", "这一行" in str(e))
    g2 = next_turn(g2, keep_next=False)
    r5 = g2.card09_swap(0, 1, "4m", 16)        # S1：我的第 1 行（第 7 张）
    check("换到下一行可以", r5.get("row"), 1)

    # ── ⑦ 只能在摸牌前 ─────────────────────────────────────────
    print("\n⑦ 只能在摸牌前")
    g3 = Game(db2, rid2)
    g3.round_phase = "play"
    g3.turn = 0
    g3.phase = "discard"
    g3.save_flags()
    try:
        g3.card09_swap(0, 1, "1m", 10)
        check("打牌阶段要拒绝", False)
    except RuleError as e:
        check("打牌阶段要拒绝", "摸牌之前" in str(e))

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
