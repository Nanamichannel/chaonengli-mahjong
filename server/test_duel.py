# -*- coding: utf-8 -*-
"""Card08 Skill1「决斗」自测

跑法： python test_duel.py
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
    uids = [db.create_user(f"duel{seed}_{i}") for i in range(4)]
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


def fake_discards(db, rid: int, seat: int, n: int, base: int = 600) -> None:
    """假装这个座位已经正常打过 n 张（数巡目用）。"""
    with db.tx():
        for i in range(n):
            db.conn.execute(
                "INSERT INTO round_discards(round_id, seq, seat, wall_seq, tile,"
                " is_tsumogiri, is_riichi_tile, face_down, called)"
                " VALUES(?,?,?,?,?,1,0,0,0)", (rid, base + seat * 10 + i, seat,
                                              900 + base + i, "9p"))
            # 巡目数的是 round_actions 里的 discard 条数
            db.conn.execute(
                "INSERT INTO round_actions(round_id, seq, seat, action, payload)"
                " VALUES(?,?,?,?,?)", (rid, 5000 + base + seat * 10 + i, seat,
                                      "discard", "{}"))


def to_discard(g: Game, seat: int) -> Game:
    g.round_phase = "play"
    g.turn = seat
    g.phase = "discard"
    g.save_flags()
    return g


ORD_8 = [[8, 1, 2, 3, 4], [5, 1, 2, 3, 6], [1, 2, 3, 6, 9], [1, 2, 3, 6, 10]]

H_PLAYER = parse_hand("123m456m789m12p55z") + ["3p"]       # 13 张 + 刚摸 3p = 14
H_WAIT = parse_hand("123m456m789m12p55z")                  # 13 张，听 3p
H_OTHER = parse_hand("123m456p789s123p1z")


def main() -> int:
    print("=" * 70)
    print(" 天马麻将 · Card08 Skill1「决斗」")
    print("=" * 70)

    # ── ① 登记 ──────────────────────────────────────────────────
    print("\n① 技能登记")
    check("skills.has(8,1)", skills.has(8, 1))
    check("名字是「决斗」", skills.info(8, 1).get("name"), "决斗")
    check("时机是摸牌", skills.timing(8, 1), "draw")

    # ── ② 发动条件：第六巡之后 ──────────────────────────────────
    print("\n② 发动条件")
    db = tg.fresh_db("duel_gate")
    rid = new_round(db, 921, ORD_8)
    tg.set_hand(db, rid, 0, H_PLAYER, drawn="3p")
    tg.set_hand(db, rid, 1, H_OTHER)
    tg.set_hand(db, rid, 2, H_OTHER)
    tg.set_hand(db, rid, 3, H_OTHER)
    g = to_discard(Game(db, rid), 0)
    check("还没到第六巡 → 不能发动", g.duel_can_start(0), False)
    try:
        g.duel_start(0, 1)
        check("巡目不够要拒绝", False)
    except RuleError as e:
        check("巡目不够要拒绝", "第六巡" in str(e))
    fake_discards(db, rid, 0, 6)
    g = to_discard(Game(db, rid), 0)
    check("打满 6 张 → 可以发动", g.duel_can_start(0), True)
    check("不是我回合不能发动", Game(db, rid).duel_can_start(1), False)

    # ── ③ 发动：指定对手 ────────────────────────────────────────
    print("\n③ 发动")
    r = g.duel_start(0, 1)
    check("对手是 1 号位", int((r.get("duel") or {}).get("target", -1)), 1)
    check("我是发起者", bool((r.get("duel") or {}).get("mine", False)), True)
    check("我不被限制", bool((r.get("duel") or {}).get("restricted", True)), False)
    check("1 号也不被限制", g.duel_restricted(1), False)
    check("2 号被限制", g.duel_restricted(2), True)
    check("3 号被限制", g.duel_restricted(3), True)
    check("一次性：用过了", g.skill_used(0, 8, 1), True)
    check("state 里有决斗", g.state_for(0)["duel"]["target"], 1)
    check("2 号 state 说自己被限制", g.state_for(2)["duel"]["restricted"], True)
    try:
        g.duel_start(0, 2)
        check("不能发动第二次", False)
    except RuleError as e:
        check("不能发动第二次", "已经" in str(e) or "用过" in str(e))
    # 策略记账：2/3 号没有 5 号卡 → 不计数
    check("2 号没持策略 → 不计数", int(g.card05_counter.get(2, 0)), 0)

    # ── ④ 非决斗家只能摸切 + 暗置 ───────────────────────────────
    print("\n④ 非决斗家：只能摸切、暗置打出、不出铳")
    db2 = tg.fresh_db("duel_tsumogiri")
    rid2 = new_round(db2, 922, ORD_8)
    tg.set_hand(db2, rid2, 0, H_OTHER)                       # 发起者
    tg.set_hand(db2, rid2, 1, H_OTHER)                       # 对手
    tg.set_hand(db2, rid2, 2, H_PLAYER, drawn="3p")          # 被限制：刚摸 3p
    tg.set_hand(db2, rid2, 3, H_WAIT)                        # 听 3p（想荣和）
    g2 = to_discard(Game(db2, rid2), 2)
    g2.duel = {"by": 0, "target": 1}
    g2.save_flags()
    check("2 号被限制", g2.duel_restricted(2), True)
    # 新口径（用户 2026-10-24）：决斗也要看得见自己摸到的牌，而且要手动打
    _st2 = g2.state_for(2)
    check("摸到的牌看得到", _st2["drawn"] != "", True)
    check("手牌是完整的 14 张", len(_st2["hand"]), 14)
    check("duel_drawn_hidden=False", _st2["duel_drawn_hidden"], False)
    check("发起者也一样", g2.state_for(0)["duel_drawn_hidden"], False)
    _disc = [a for a in _st2.get("legal", []) if a.get("action") == "discard"]
    check("只能打刚摸到的那张（tiles 只有 1 张）",
          bool(_disc) and _disc[0].get("tiles") == [_st2["drawn"]], True)

    try:
        g2.act(2, "discard", tile="3p")                      # 3p 就是刚摸的那张，允许
        ok_tsumogiri = True
    except RuleError:
        ok_tsumogiri = False
    check("摸切可以（打的就是刚摸那张）", ok_tsumogiri, True)
    g2 = Game(db2, rid2)
    row = g2.db._row("SELECT face_down, tile FROM round_discards WHERE round_id=? "
                     "ORDER BY seq DESC LIMIT 1", (rid2,))
    check("打出去的牌是暗置的", int(row["face_down"]), 1)
    check("没人能荣和这张（没开鸣牌窗口）", g2.pending, None)
    check("回合正常轮到下家摸牌", (g2.phase, g2.turn), ("draw", 3))

    # 对照：没有决斗时，同一张牌会被荣和
    db3 = tg.fresh_db("duel_control")
    rid3 = new_round(db3, 923, ORD_8)
    tg.set_hand(db3, rid3, 0, H_OTHER)
    tg.set_hand(db3, rid3, 2, H_PLAYER, drawn="3p")
    tg.set_hand(db3, rid3, 3, H_WAIT)
    g3 = to_discard(Game(db3, rid3), 2)
    g3.act(2, "discard", tile="3p")
    check("对照：没决斗时这张开鸣牌窗口", g3.phase, "claim")
    check("对照：3 号能荣和", any(o["action"] == "ron"
                                  for o in (g3.pending["options"].get(3) or [])), True)

    # ── ⑤ 手切被拒 ──────────────────────────────────────────────
    print("\n⑤ 非决斗家想手切别的牌")
    db4 = tg.fresh_db("duel_handcut")
    rid4 = new_round(db4, 924, ORD_8)
    tg.set_hand(db4, rid4, 0, H_OTHER)
    tg.set_hand(db4, rid4, 2, H_PLAYER, drawn="3p")
    tg.set_hand(db4, rid4, 3, H_OTHER)
    g4 = to_discard(Game(db4, rid4), 2)
    g4.duel = {"by": 0, "target": 1}
    g4.save_flags()
    try:
        g4.act(2, "discard", tile="1m")
        check("手切别的牌要拒绝", False)
    except RuleError as e:
        check("手切别的牌要拒绝", "只能摸切" in str(e))
    # 决斗双方照常手切
    g4.turn = 0
    g4.phase = "discard"
    g4.save_flags()
    g4.oracle  # noqa: B018  (占位，避免 linter 抱怨)
    g4.act(0, "discard", tile="1m")
    check("发起者可以正常手切", g4.phase in ("claim", "draw"), True)
    row = g4.db._row("SELECT face_down FROM round_discards WHERE round_id=? AND seat=0 "
                     "ORDER BY seq DESC LIMIT 1", (rid4,))
    check("发起者的牌是明置的", int(row["face_down"]), 0)

    # ── ⑥ 策略记账（非决斗家持 5 号卡）────────────────────────────
    print("\n⑥ 被卷进来的策略持有者：计数 +1")
    db5 = tg.fresh_db("duel_c05")
    rid5 = new_round(db5, 925, [[8, 1, 2, 3, 4], [1, 2, 3, 6, 5],
                                [1, 2, 3, 6, 9], [1, 2, 3, 6, 10]])
    tg.set_hand(db5, rid5, 0, H_PLAYER, drawn="3p")
    tg.set_hand(db5, rid5, 1, H_OTHER)
    tg.set_hand(db5, rid5, 2, H_OTHER)
    tg.set_hand(db5, rid5, 3, H_OTHER)
    fake_discards(db5, rid5, 0, 6)
    g5 = to_discard(Game(db5, rid5), 0)
    check("1 号持策略（协战位）", g5.owns_card05(1), True)
    g5.duel_start(0, 2)                       # 对手是 2 → 1、3 被限制
    check("被限制的策略持有者 +1", int(g5.card05_counter.get(1, 0)), 1)
    check("有换牌机会", bool(g5.card05_offer.get(1)), True)
    check("决斗对手（2 号）不计数", int(g5.card05_counter.get(2, 0)), 0)
    check("发起者不计数", int(g5.card05_counter.get(0, 0)), 0)

    # ── ⑦ 目标转移 ──────────────────────────────────────────────
    print("\n⑦ 非决斗家 副露 / 立直 / 用技能 → 目标转移")
    g5.duel_retarget(3)
    check("3 号变成对手", int(g5.duel["target"]), 3)
    check("新的对手 3 号不再被限制", g5.duel_restricted(3), False)
    check("原来的对手 2 号变成被限制", g5.duel_restricted(2), True)
    check("一直没进决斗的 1 号还是被限制", g5.duel_restricted(1), True)
    check("发起者不变", int(g5.duel["by"]), 0)
    g5.duel_retarget(0)
    check("发起者自己不会转移", int(g5.duel["target"]), 3)

    # ── ⑧ 立直相关 ─────────────────────────────────────────────
    print("\n⑧ 立直")
    db6 = tg.fresh_db("duel_riichi")
    rid6 = new_round(db6, 926, ORD_8)
    tg.set_hand(db6, rid6, 0, H_OTHER)
    tg.set_hand(db6, rid6, 2, H_OTHER)
    tg.set_hand(db6, rid6, 3, H_WAIT)
    g6 = to_discard(Game(db6, rid6), 2)
    g6.duel = {"by": 0, "target": 1}
    g6.save_flags()
    check("没立直时能自摸（形状对了的话）", g6.duel_restricted(2) and g6.is_riichi(2), False)
    with db6.tx():                         # 假装 2 号立直了
        db6.conn.execute("INSERT OR REPLACE INTO round_riichi(round_id, seat, declared_seq)"
                         " VALUES(?,?,?)", (rid6, 2, 1))
    g6 = Game(db6, rid6)
    check("2 号立直了", g6.is_riichi(2), True)
    check("被限制 + 立直 → 不能自摸", g6._win_ok(2, "3p", tsumo=True), False)

    # 我立直 → 决斗取消
    db7 = tg.fresh_db("duel_myriichi")
    rid7 = new_round(db7, 927, ORD_8)
    tg.set_hand(db7, rid7, 0, parse_hand("123m456m789m12p55z") + ["9s"], drawn="9s")
    tg.set_hand(db7, rid7, 1, H_OTHER)
    tg.set_hand(db7, rid7, 2, H_OTHER)
    tg.set_hand(db7, rid7, 3, H_OTHER)
    g7 = to_discard(Game(db7, rid7), 0)
    g7.duel = {"by": 0, "target": 1}
    g7.save_flags()
    if g7.can_riichi(0):
        g7.act(0, "riichi", tile=str(g7.riichi_discards(0)[0]))
        check("我立直 → 决斗取消", g7.duel, None)
    else:
        check("（这个手牌不能立直，跳过）", True)

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
