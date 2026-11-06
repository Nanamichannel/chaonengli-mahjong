# -*- coding: utf-8 -*-
"""Card08 Skill2「决斗标记」自测

· 指定对手 / 转移一次 → 参与决斗的人各拿一个标记（标记不会清除）
· 别人胡牌 → 我计数器 += 场上标记人数
· 我胡牌 → 额外 +计数器 番
· 标记和计数器只活一个「角色」（两局：东一东二 / 东三东四 / 南一南二 / 南三南四），
  角色下场（进入下一个两局）就清空

跑法： python test_duel_mark.py
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")

from game import Game  # noqa: E402
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


def new_match(db, seed: int, orders):
    """开一个新半庄，返回 (match_id, rid 东一)。"""
    uids = [db.create_user(f"dm{seed}_{i}") for i in range(4)]
    room = db.create_room(uids[0])
    for u in uids[1:]:
        db.join_room(room["room_code"], u)
    match = db.start_match(room["room_id"], seed=seed)
    body = {"seats": [{"ready": False, "hand": [], "picks": [], "order": list(o)}
                      for o in orders],
            "phase": "playing"}
    with db.tx():
        db.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('lobby_state', ?)",
                        (json.dumps(body, ensure_ascii=False),))
    rid = db.start_round(match, "dong", 1, honba=0, dealer_seat=0, seed=seed)
    return match, rid


def next_round(db, match, wind: str, number: int, seed: int) -> int:
    return db.start_round(match, wind, number, honba=0, dealer_seat=0, seed=seed)


def mark_discarded(db, rid: int, seat: int) -> None:
    """假装这家已经打过一张（不然第一次自摸会判天和/地和）。"""
    with db.tx():
        db.conn.execute(
            "INSERT INTO round_discards(round_id, seq, seat, wall_seq, tile,"
            " is_tsumogiri, is_riichi_tile, face_down, called)"
            " VALUES(?,?,?,?,?,1,0,0,0)", (rid, 500 + seat, seat, 700 + seat, "9p"))


def win_tsumo(db, rid: int, seat: int) -> dict:
    """让这家自摸和牌，返回结算结果。"""
    tg.set_hand(db, rid, seat, parse_hand("123m456m789m123p55z"), drawn="bai")
    mark_discarded(db, rid, seat)
    g = Game(db, rid)
    g.round_phase = "play"
    g.turn = seat
    g.phase = "discard"
    g.save_flags()
    g.act(seat, "tsumo")
    return g.result or {}


ORD_8 = [[8, 1, 2, 3, 4], [1, 2, 3, 6, 5], [1, 2, 3, 6, 9], [1, 2, 3, 6, 10]]


def main() -> int:
    print("=" * 70)
    print(" 天才麻将少女 · Card08 Skill2「决斗标记」")
    print("=" * 70)

    # ── ① 登记 ──────────────────────────────────────────────────
    print("\n① 技能登记")
    check("skills.has(8,2)", skills.has(8, 2))
    check("名字是「决斗标记」", skills.info(8, 2).get("name"), "决斗标记")
    check("不是配牌技能", (8, 2) in skills.deal_skills(), False)

    db = tg.fresh_db("dm_main")
    match, rid = new_match(db, 931, ORD_8)
    tg.set_hand(db, rid, 0, parse_hand("123m456m789m12p55z") + ["3p"], drawn="3p")

    # ── ② 开决斗 → 两家拿标记 ──────────────────────────────────
    print("\n② 开决斗 → 参与的两家各拿一个标记")
    g = Game(db, rid)
    check("0 号持 8 号卡（S2 自动生效）", g.owns_duel_s2(0), True)
    check("开局没有标记", len(g.duel_marks), 0)
    g.round_phase = "play"
    g.turn = 0
    g.phase = "discard"
    g.save_flags()
    # 凑够六巡
    with db.tx():
        for i in range(6):
            db.conn.execute("INSERT INTO round_actions(round_id, seq, seat, action, payload)"
                            " VALUES(?,?,?,?,?)", (rid, 8000 + i, 0, "discard", "{}"))
    g = Game(db, rid)
    g.round_phase = "play"
    g.turn = 0
    g.phase = "discard"
    g.save_flags()
    check("可以发动决斗", g.duel_can_start(0), True)
    g.duel_start(0, 1)
    check("发起者拿到标记", 0 in g.duel_marks, True)
    check("对手拿到标记", 1 in g.duel_marks, True)
    check("标记总数 2", len(g.duel_marks), 2)
    check("state 里 duel_marks=2", g.state_for(0)["duel_marks"], 2)
    check("发起者 duel_marked=True", g.state_for(0)["duel_marked"], True)
    check("别人 duel_marked=False", g.state_for(2)["duel_marked"], False)
    check("计数器还是 0", int(g.state_for(0)["duel_counter"]), 0)

    # ── ③ 转移一次 → 新对手也拿标记（旧的不清） ────────────────
    print("\n③ 转移一次决斗对象")
    g.duel_retarget(2)
    check("新的对手 2 号拿到标记", 2 in g.duel_marks, True)
    check("原来的对手 1 号标记还在（不会清除）", 1 in g.duel_marks, True)
    check("现在场上有 3 个标记", len(g.duel_marks), 3)
    check("再转移给 3 号 → 4 个", (g.duel_retarget(3) or len(g.duel_marks)), 4)

    # ── ④ 别人胡牌 → 我计数器 +标记数 ──────────────────────────
    print("\n④ 别人胡牌：计数器 +场上标记人数")
    res1 = win_tsumo(db, rid, 1)
    check("1 号自摸和牌", res1.get("result"), "tsumo")
    g = Game(db, rid)
    check("标记还是 4 个", len(g.duel_marks), 4)
    check("0 号计数器 +4", int(g.duel_counter.get(0, 0)), 4)
    check("没有 8 号卡的 2 号不计数", int(g.duel_counter.get(2, 0)), 0)
    check("state 里能看到计数器", int(g.state_for(0)["duel_counter"]), 4)

    # ── ⑤ 标记/计数器跨「同一角色的第二局」保留 ────────────────
    print("\n⑤ 东二（同一个角色）→ 标记和计数器还在")
    rid2 = next_round(db, match, "dong", 2, seed=932)
    g2 = Game(db, rid2)
    check("东二角色序号还是 0", g2._char_index(), 0)
    check("标记还在（4 个）", len(g2.duel_marks), 4)
    check("计数器还在（4）", int(g2.duel_counter.get(0, 0)), 4)

    # ── ⑥ 我胡牌 → 额外 +计数器 番 ────────────────────────────
    print("\n⑥ 我胡牌：额外 +计数器 番")
    res2 = win_tsumo(db, rid2, 0)
    check("0 号自摸和牌", res2.get("result"), "tsumo")
    check("额外番数 = 4", int(res2.get("duel_bonus", 0)), 4)
    names = [y.get("name") for y in (res2.get("yaku") or [])]
    check("役种里有「决斗标记（+4 番）」", "决斗标记" in names, True)
    bonus_han = sum(int(y.get("han", 0)) for y in (res2.get("yaku") or [])
                    if str(y.get("name", "")).startswith("决斗标记"))
    check("番数里确实算进去了", bonus_han, 4)
    # 别人再胡不会因为我胡过就变
    g2 = Game(db, rid2)
    check("我胡牌不给自己加计数", int(g2.duel_counter.get(0, 0)), 4)

    # ── ⑦ 角色下场（进东三）→ 标记和计数器清空 ────────────────
    print("\n⑦ 东三（换角色）→ 标记清空")
    rid3 = next_round(db, match, "dong", 3, seed=933)
    g3 = Game(db, rid3)
    check("东三角色序号是 1", g3._char_index(), 1)
    check("标记清空", len(g3.duel_marks), 0)
    check("计数器清空", int(g3.duel_counter.get(0, 0)), 0)
    check("state 里也是 0", int(g3.state_for(0)["duel_marks"]), 0)

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
