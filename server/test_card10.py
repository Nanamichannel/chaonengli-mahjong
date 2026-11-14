# -*- coding: utf-8 -*-
"""Card10 Skill1「鬼门」自测：手牌换弃牌的东/北、或副露换别家东/北，东和北各一次。"""
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
    uids = [db.create_user(f"c10{seed}_{i}") for i in range(4)]
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
            (rid, seq, seat, 6000 + seq, tile, 1 if down else 0, called))


def add_meld(db, rid, seat: int, meld_id: int, kind: str, tiles: list[str]) -> None:
    with db.tx():
        db.conn.execute(
            "INSERT INTO round_melds(round_id, seat, meld_id, kind, called_tile, from_seat,"
            " tiles_json, rot_index, seqs_json) VALUES(?,?,?,?,?,?,?,?,?)",
            (rid, seat, meld_id, kind, tiles[0], 1, json.dumps(tiles), 0, "[]"))


ORD_10 = [[10, 1, 2, 3, 4], [1, 2, 3, 5, 6], [1, 2, 3, 5, 7], [1, 2, 3, 5, 8]]
H_ME = parse_hand("123m456m789p12s1z") + ["9s"]        # 14 张（刚摸 9s）


def to_discard(g: Game, seat: int) -> Game:
    g.round_phase = "play"
    g.turn = seat
    g.phase = "discard"
    g.save_flags()
    return g


def main() -> int:
    print("=" * 70)
    print(" 天才麻将少女 · Card10 Skill1「鬼门」")
    print("=" * 70)

    # ── ① 登记 ──────────────────────────────────────────────────
    print("\n① 技能登记")
    check("skills.has(10,1)", skills.has(10, 1))
    check("名字是「鬼门」", skills.info(10, 1).get("name"), "鬼门")
    check("时机是摸牌", skills.timing(10, 1), "draw")

    # ── ② 发动条件 ──────────────────────────────────────────────
    print("\n② 发动条件：摸牌后、打牌前")
    db = tg.fresh_db("c10_gate")
    rid = new_round(db, 951, ORD_10)
    tg.set_hand(db, rid, 0, H_ME, drawn="9s")
    g = Game(db, rid)
    check("0 号持 10 号卡", g.owns_card10(0), True)
    check("1 号没有", g.owns_card10(1), False)
    g.round_phase = "play"
    g.turn = 0
    g.phase = "draw"
    g.save_flags()
    check("摸牌阶段还不能用", g.card10_can(0), False)
    g = to_discard(Game(db, rid), 0)
    check("摸完牌可以用", g.card10_can(0), True)
    check("state 里 card10_can=True", g.state_for(0)["card10_can"], True)

    # ── ③ 甲：手牌换弃牌的东 ────────────────────────────────────
    print("\n③ 甲：3 张手牌 ↔ 牌河 3 张东")
    add_river(db, rid, 1, 0, "dong")
    add_river(db, rid, 2, 2, "dong")
    add_river(db, rid, 3, 3, "dong")
    add_river(db, rid, 4, 1, "bei")             # 留着测北 / 混选
    add_river(db, rid, 5, 1, "5p")              # 不是风牌
    g = to_discard(Game(db, rid), 0)
    try:
        g.card10_swap_hand(0, "dong", ["1m", "2m", "3m"], [1, 2, 5])
        check("牌河不是东的要拒绝", False)
    except RuleError as e:
        check("牌河不是东的要拒绝", "3 张东" in str(e))
    g = to_discard(Game(db, rid), 0)
    r = g.card10_swap_hand(0, "dong", ["1m", "2m", "3m"], [1, 2, 3])
    check("换成功", r.get("mode"), "hand")
    check("换到 3 张东", sorted(r.get("got") or []), ["dong", "dong", "dong"])
    g = to_discard(Game(db, rid), 0)
    check("手里多了 3 张东", g.hand(0).count("dong"), 4)   # 原来 1 张 + 3 张
    check("手牌一张没少（3 换 3）", len(g.hand(0)), 13)
    check("手里的 1m 换出去了", g.hand(0).count("1m"), 0)
    row = g.db._row("SELECT tile, face_down FROM round_discards WHERE round_id=? AND seq=1",
                    (rid,))
    check("牌河那个位置变成我的手牌", row["tile"], "1m")
    check("换过去的是暗置", int(row["face_down"]), 1)
    check("state 里东已经用过", g.state_for(0)["card10_used"], ["dong"])

    # ── ④ 东不能再换，北还能换 ─────────────────────────────────
    print("\n④ 东、北各一次")
    try:
        g.card10_swap_hand(0, "dong", ["4m", "5m", "6m"], [1, 2, 3])
        check("东换第二次要拒绝", False)
    except RuleError as e:
        check("东换第二次要拒绝", "已经换过" in str(e))
    add_river(db, rid, 6, 0, "bei")
    add_river(db, rid, 7, 0, "bei")
    add_river(db, rid, 8, 0, "bei")
    r2 = g.card10_swap_hand(0, "bei", ["4m", "5m", "6m"], [6, 7, 8])
    check("北可以换", r2.get("kind"), "bei")
    check("东和北都用过了", sorted(g.state_for(0)["card10_used"]), ["bei", "dong"])

    # ── ⑤ 暗置牌不能换 ─────────────────────────────────────────
    print("\n⑤ 暗置牌不能换")
    add_river(db, rid, 9, 0, "dong", down=True)
    add_river(db, rid, 10, 0, "dong")
    add_river(db, rid, 11, 0, "dong")
    try:
        g.card10_swap_hand(0, "dong", ["7p", "8p", "9p"], [9, 10, 11])
        check("暗置牌要拒绝", False)
    except RuleError as e:
        check("暗置牌要拒绝（或东已经换过）", "暗置" in str(e) or "已经换过" in str(e))

    # ── ⑥ 乙：副露换别家东 ─────────────────────────────────────
    print("\n⑥ 乙：我的一组副露 ↔ 别家东的刻子")
    db2 = tg.fresh_db("c10_meld")
    rid2 = new_round(db2, 952, ORD_10)
    tg.set_hand(db2, rid2, 0, H_ME, drawn="9s")
    add_meld(db2, rid2, 0, 0, "pon", ["5p", "5p", "5p"])
    add_meld(db2, rid2, 1, 0, "pon", ["dong", "dong", "dong"])
    add_meld(db2, rid2, 1, 1, "chi", ["2m", "3m", "4m"])
    add_meld(db2, rid2, 2, 0, "pon", ["bei", "bei", "bei"])
    g2 = to_discard(Game(db2, rid2), 0)
    check("我有 1 组副露", len(g2.melds(0)), 1)
    check("1 号有 2 组", len(g2.melds(1)), 2)
    check("melds 里带 meld_id", g2.melds(0)[0].get("meld_id"), 0)
    r3 = g2.card10_swap_meld(0, "dong", 0, 1, 0)
    check("换成功", r3.get("mode"), "meld")
    g2 = to_discard(Game(db2, rid2), 0)
    my_tiles = [m["tiles"] for m in g2.melds(0)]
    check("我拿到了东的刻子", ["dong", "dong", "dong"] in my_tiles, True)
    their_tiles = [m["tiles"] for m in g2.melds(1)]
    check("1 号拿到了我的 5p 刻子", ["5p", "5p", "5p"] in their_tiles, True)
    check("1 号还剩吃的那组", len(g2.melds(1)), 2)
    check("东这一局用掉了", g2.state_for(0)["card10_used"], ["dong"])

    # ── ⑦ 副露换的拒绝条件 ────────────────────────────────────
    print("\n⑦ 副露换的拒绝条件")
    try:
        g2.card10_swap_meld(0, "dong", 0, 1, 1)
        check("东换第二次要拒绝", False)
    except RuleError as e:
        check("东换第二次要拒绝", "已经换过" in str(e))
    try:
        g2.card10_swap_meld(0, "bei", 1, 1, 1)     # 1 号 id=1 是吃的那组
        check("对方不是北的要拒绝", False)
    except RuleError as e:
        check("对方不是北的要拒绝", "不是北" in str(e) or "刻子" in str(e))
    try:
        g2.card10_swap_meld(0, "bei", 0, 0, 0)
        check("不能跟自己换", False)
    except RuleError as e:
        check("不能跟自己换", "别家" in str(e))

    # ── ⑦ 3 张同名手牌（重名牌）：要换满 3 张、手牌还是 13 张 ────
    print("\n⑦ 3 张同名手牌不能被当成同一张（2026-11-06 实机）")
    db3 = tg.fresh_db("c10_dup")
    rid3 = new_round(db3, 953, ORD_10)
    hdup = parse_hand("111m234p567p22s8s") + ["9s"]      # 12 张 + 摸 9s = 13
    tg.set_hand(db3, rid3, 0, hdup, drawn="9s")
    for i, sq in enumerate((21, 22, 23)):
        add_river(db3, rid3, sq, 1, "bei")
    g3 = to_discard(Game(db3, rid3), 0)
    check("手里 3 张 1m", g3.hand(0).count("1m"), 3)
    r3 = g3.card10_swap_hand(0, "bei", ["1m", "1m", "1m"], [21, 22, 23])
    check("换成功", r3.get("kind"), "bei")
    check("拿到 3 张北", r3.get("got"), ["bei", "bei", "bei"])
    g3 = to_discard(Game(db3, rid3), 0)
    check("3 张 1m 全换出去了", g3.hand(0).count("1m"), 0)
    check("手里确实多了 3 张北", g3.hand(0).count("bei"), 3)
    check("手牌张数没变（13）", len(g3.hand(0)), 13)
    down = [int(r["face_down"]) for r in g3.db._rows(
        "SELECT face_down FROM round_discards WHERE round_id=? AND seq IN (21,22,23)",
        (rid3,))]
    check("牌河三个位置都是暗置", down, [1, 1, 1])
    tiles_in = [str(r["tile"]) for r in g3.db._rows(
        "SELECT tile FROM round_discards WHERE round_id=? AND seq IN (21,22,23)", (rid3,))]
    check("牌河三个位置都是 1m", tiles_in, ["1m", "1m", "1m"])
    try:
        g3_2 = to_discard(Game(db3, rid3), 0)
        g3_2.card10_swap_hand(0, "dong", ["2s", "2s", "9s"], [21, 21, 22])
        check("牌河重复选要拒绝", False)
    except RuleError as e:
        check("牌河重复选要拒绝", "重复" in str(e) or "3 张" in str(e))

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
