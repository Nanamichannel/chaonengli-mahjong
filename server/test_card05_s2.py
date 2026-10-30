# -*- coding: utf-8 -*-
"""Card05 Skill2「拔北」自测
跑法： python test_card05_s2.py
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")

from game import Game, RuleError  # noqa: E402
import skills  # noqa: E402
from rules import score
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
    uids = [db.create_user(f"nuki{seed}_{i}") for i in range(4)]
    room = db.create_room(uids[0])
    for u in uids[1:]:
        db.join_room(room["room_code"], u)
    match = db.start_match(room["room_id"], seed=seed)
    rid = db.start_round(match, "dong", 1, honba=0, dealer_seat=0, seed=seed)
    g = Game(db, rid)
    g.start()
    while not g.deal_done():
        g.deal_step()
    order = [5, 1, 2, 3, 4] if owner else [1, 2, 3, 4, 6]
    orders = [order, [1, 2, 3, 4, 6], [2, 3, 4, 6, 7], [1, 3, 4, 6, 7]]
    body = {"seats": [{"ready": False, "hand": [], "picks": [], "order": o} for o in orders],
            "phase": "playing"}
    with db.tx():
        db.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('lobby_state', ?)",
                        (json.dumps(body, ensure_ascii=False),))
    return rid


def at_discard(g: Game) -> Game:
    g.round_phase = "play"
    g.turn, g.phase = 0, "discard"
    g.save_flags()
    return g


def main() -> int:
    print("=" * 70)
    print(" 天才麻将少女 · Card05 Skill2「拔北」")
    print("=" * 70)

    print("\n① 技能登记")
    check("skills.has(5,2)", skills.has(5, 2))
    check("名字是「拔北」", skills.info(5, 2).get("name"), "拔北")
    check("时机是摸牌", skills.timing(5, 2), "draw")

    # ── 2. 拔北 ─────────────────────────────────────────────────
    print("\n② 拔北：北放出去，从正常牌山补一张")
    db = tg.fresh_db("nuki_one")
    rid = new_round(db, seed=301)
    tg.set_hand(db, rid, 0, parse_hand("123m456m789m123p4z4z"), drawn="bei")
    g = at_discard(Game(db, rid))
    n0 = len(g.hand(0))
    r = g.card05_nuki(0)
    check("拔北次数 1", r.get("nuki"), 1)
    check("补了一张", r.get("drawn") not in (None, ""), True)
    g = Game(db, rid)
    check("手里少了一张北", len([t for t in g.hand(0) if t == "bei"]), 1)
    check("手牌张数不变", len(g.hand(0)), n0)
    check("还是我的回合", g.turn, 0)
    check("还能继续打牌", "discard" in {a["action"] for a in g.legal_actions(0)}, True)
    row = db._row("SELECT tile, is_nuki, face_down FROM round_discards WHERE round_id=? AND seat=0", (rid,))
    check("牌河多了一张北", (row["tile"], row["is_nuki"]), ("bei", 1))
    check("拔北不算振听", "bei" in g.discards_for_furiten(0), False)

    # ── 3. 可以连着拔 ──────────────────────────────────────────
    print("\n③ 手里还有北：可以连着拔")
    r2 = g.card05_nuki(0)
    check("第二次拔北", r2.get("nuki"), 2)
    g2 = Game(db, rid)
    check("手里没有北了", [t for t in g2.hand(0) if t == "bei"], [])
    try:
        g2.card05_nuki(0)
        check("没有北不能拔", False)
    except RuleError as e:
        check("没有北不能拔", "没有北" in str(e))

    # ── 4. 和牌 + 拔北番 ───────────────────────────────────────
    print("\n④ 和牌：拔北 +1 番")
    # 对照：同样牌型，不拔北（先塞一条以前的弃牌，避免天和）
    dbc2 = tg.fresh_db("nuki_ctrl2")
    ridc2 = new_round(dbc2, seed=303)
    tg.set_hand(dbc2, ridc2, 0, parse_hand("123m456m789m123p55z"), drawn="bai")
    with dbc2.tx():
        dbc2.conn.execute(
            "INSERT INTO round_discards(round_id, seq, seat, wall_seq, tile, is_tsumogiri,"
            " is_riichi_tile, face_down, called, is_nuki) VALUES(?,1,0,999,'1m',1,0,0,0,0)",
            (ridc2,))
    gc2 = at_discard(Game(dbc2, ridc2))
    gc2.act(0, "tsumo")
    resc = gc2.result or {}
    base_han = int(resc.get("han", 0))
    base_pts = int((resc.get("pays") or {}).get("total", 0))
    check("对照和牌", resc.get("result"), "tsumo")

    db4 = tg.fresh_db("nuki_win")
    rid4 = new_round(db4, seed=304)
    tg.set_hand(db4, rid4, 0, parse_hand("123m456m789m123p55z"), drawn="bai")
    with db4.tx():
        db4.conn.execute(
            "INSERT INTO round_discards(round_id, seq, seat, wall_seq, tile, is_tsumogiri,"
            " is_riichi_tile, face_down, called, is_nuki) VALUES(?,1,0,999,'1m',1,0,0,0,0)",
            (rid4,))
    g4 = at_discard(Game(db4, rid4))
    g4.nuki_count = {0: 1}
    g4.save_flags()
    g4 = Game(db4, rid4)
    g4.round_phase, g4.turn, g4.phase = "play", 0, "discard"
    g4.act(0, "tsumo")
    res4 = g4.result or {}
    check("多了「拔北」1 番",
          [y["han"] for y in res4.get("yaku", []) if y["name"] == "拔北"], [1])
    yaku_han = sum(int(y.get("han", 0)) for y in res4.get("yaku", []))
    check("总番数 = 各役相加（含拔北）", int(res4.get("han", 0)), yaku_han)
    want4 = score.payments(int(res4.get("han", 0)), int(res4.get("fu", 0)),
                           is_dealer=(res4.get("winner") == 0), tsumo=True,
                           kiriage_mangan=False).get("total")
    check("点数按加番后重算", int((res4.get("pays") or {}).get("total", 0)), want4)

    # ── 5. 不是这张卡 / 不是自己回合 ───────────────────────────
    print("\n⑤ 条件校验")
    db5 = tg.fresh_db("nuki_noown")
    rid5 = new_round(db5, seed=305, owner=False)
    tg.set_hand(db5, rid5, 0, parse_hand("123m456m789m123p4z4z"), drawn="bei")
    g5 = at_discard(Game(db5, rid5))
    try:
        g5.card05_nuki(0)
        check("没这张卡不能拔北", False)
    except RuleError as e:
        check("没这张卡不能拔北", "人物卡" in str(e))

    db6 = tg.fresh_db("nuki_turn")
    rid6 = new_round(db6, seed=306)
    tg.set_hand(db6, rid6, 0, parse_hand("123m456m789m123p4z4z"), drawn="bei")
    g6 = at_discard(Game(db6, rid6))
    g6.turn = 1
    try:
        g6.card05_nuki(0)
        check("不是自己回合不能拔", False)
    except RuleError as e:
        check("不是自己回合不能拔", "出牌回合" in str(e))

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
