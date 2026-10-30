# -*- coding: utf-8 -*-
"""Card06 Skill2「坚韧」自测

技能原文（Cailiao/skill/ui/skills.json）：
    「当东场摸到此卡时，你的失点减半(向上取整)。南场无该技能。」
被动：不发动。放铳 / 被别人自摸时，**自己**付的那一份减半（向上取整到 100），
和牌的人得点不变（少付的那份不回补给赢家）。

跑法： python test_tenacity.py
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")

from game import Game  # noqa: E402
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


def half_up100(x: int) -> int:
    """失点的一半，向上取整到 100。"""
    return ((int(x) + 199) // 200) * 100


def new_round(db, seed: int, orders, wind="dong", number=1) -> int:
    uids = [db.create_user(f"ten{seed}_{i}") for i in range(4)]
    room = db.create_room(uids[0])
    for u in uids[1:]:
        db.join_room(room["room_code"], u)
    match = db.start_match(room["room_id"], seed=seed)
    rid = db.start_round(match, wind, number, honba=0, dealer_seat=0, seed=seed)
    body = {"seats": [{"ready": False, "hand": [], "picks": [], "order": list(o)}
                      for o in orders],
            "phase": "playing"}
    with db.tx():
        db.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('lobby_state', ?)",
                        (json.dumps(body, ensure_ascii=False),))
    return rid


def mark_discarded(db, rid: int, seat: int) -> None:
    """假装这个座位已经打过一张牌（不然第一次自摸会判天和/地和 → 役满）。"""
    with db.tx():
        db.conn.execute(
            "INSERT INTO round_discards(round_id, seq, seat, wall_seq, tile,"
            " is_tsumogiri, is_riichi_tile, face_down, called)"
            " VALUES(?,?,?,?,?,1,0,0,0)", (rid, 500 + seat, seat, 700 + seat, "1m"))


def to_discard(g: Game, seat: int) -> Game:
    g.round_phase = "play"
    g.turn = seat
    g.phase = "discard"
    g.save_flags()
    return g


# 东一：主战卡 = order[0]；南一：主战卡 = order[2]
ORD_DONG_6 = [[6, 1, 2, 3, 7], [1, 2, 3, 5, 8], [1, 2, 3, 5, 9], [1, 2, 3, 5, 10]]
ORD_DONG_NO6 = [[1, 2, 3, 5, 7], [1, 2, 3, 5, 8], [1, 2, 3, 5, 9], [1, 2, 3, 5, 10]]
ORD_NAN_6 = [[1, 3, 6, 2, 11], [1, 2, 3, 5, 12], [1, 2, 3, 5, 13], [1, 2, 3, 5, 14]]

H_RON_DEALER = parse_hand("123m456m789m123p55z") + ["3p"]   # 打 3p 放铳
H_RON_WINNER = parse_hand("123m456m789m12p55z")             # 荣和 3p
H_TSUMO = parse_hand("123m456m789m123p55z")                 # 自摸（摸白）


def main() -> int:
    print("=" * 70)
    print(" 天马麻将 · Card06 Skill2「坚韧」")
    print("=" * 70)

    # ── ① 登记 ──────────────────────────────────────────────────
    print("\n① 技能登记")
    check("skills.has(6,2)", skills.has(6, 2))
    check("名字是「坚韧」", skills.info(6, 2).get("name"), "坚韧")
    check("时机是结算", skills.timing(6, 2), "settle")
    check("不是配牌技能", (6, 2) in skills.deal_skills(), False)

    # ── ② 东场 · 放铳：我付一半，赢家照拿全额 ───────────────────
    print("\n② 东场放铳")
    dbc = tg.fresh_db("ten_ron_ctrl")
    ridc = new_round(dbc, 901, ORD_DONG_NO6)
    tg.set_hand(dbc, ridc, 0, H_RON_DEALER, drawn="3p")
    tg.set_hand(dbc, ridc, 1, H_RON_WINNER)
    gc = to_discard(Game(dbc, ridc), 0)
    check("没卡的对照：也持不持坚韧", gc.owns_tenacity(0), False)
    gc.act(0, "discard", tile="3p")
    gc.act(1, "ron")
    rc = gc.result or {}
    base_total = int((rc.get("pays") or {}).get("total", 0))
    base_deltas = rc.get("deltas") or {}
    check("对照：正常荣和", rc.get("winner"), 1)
    check("对照：放铳者全额", base_deltas.get(0), -base_total)
    check("对照：收付合计为 0", sum(base_deltas.values()), 0)

    db2 = tg.fresh_db("ten_ron")
    rid2 = new_round(db2, 902, ORD_DONG_6)
    tg.set_hand(db2, rid2, 0, H_RON_DEALER, drawn="3p")
    tg.set_hand(db2, rid2, 1, H_RON_WINNER)
    g2 = Game(db2, rid2)
    check("东场持坚韧", g2.owns_tenacity(0), True)
    check("state 里 tenacity=True", g2.state_for(0).get("tenacity"), True)
    check("别人看不到我的", g2.state_for(1).get("tenacity"), False)
    to_discard(g2, 0)
    g2.act(0, "discard", tile="3p")
    g2.act(1, "ron")
    r2 = g2.result or {}
    d2 = r2.get("deltas") or {}
    want2 = -half_up100(base_total)
    check("我付一半（向上取整到百位）", d2.get(0), want2)
    check("赢家还是拿全额", d2.get(1), base_total)
    check("少付的那份没补给赢家", sum(d2.values()), base_total - (-want2))
    check("役种里有「坚韧（失点减半）」",
          "坚韧（失点减半）" in [y["name"] for y in (r2.get("yaku") or [])], True)
    check("番数没被动过", int(r2.get("han", 0)), int(rc.get("han", 0)))
    check("点数显示还是赢家的得点", int((r2.get("pays") or {}).get("total", 0)), base_total)

    # ── ③ 东场 · 别人自摸：只有我这一份减半 ─────────────────────
    print("\n③ 东场被别人自摸")
    dbc3 = tg.fresh_db("ten_tsumo_ctrl")
    ridc3 = new_round(dbc3, 903, ORD_DONG_NO6)
    tg.set_hand(dbc3, ridc3, 1, H_TSUMO, drawn="bai")
    mark_discarded(dbc3, ridc3, 1)
    gc3 = to_discard(Game(dbc3, ridc3), 1)
    gc3.act(1, "tsumo")
    rc3 = gc3.result or {}
    pays_c = rc3.get("pays") or {}
    check("对照：自摸", rc3.get("result"), "tsumo")
    check("对照：亲家付 from_dealer", (rc3.get("deltas") or {}).get(0), -int(pays_c["from_dealer"]))

    db4 = tg.fresh_db("ten_tsumo")
    rid4 = new_round(db4, 904, ORD_DONG_6)
    tg.set_hand(db4, rid4, 1, H_TSUMO, drawn="bai")
    mark_discarded(db4, rid4, 1)
    g4 = to_discard(Game(db4, rid4), 1)
    g4.act(1, "tsumo")
    r4 = g4.result or {}
    d4 = r4.get("deltas") or {}
    p4 = r4.get("pays") or {}
    check("我是亲家，付一半", d4.get(0), -half_up100(int(p4["from_dealer"])))
    check("子家照付全额（2 号位）", d4.get(2), -int(p4["from_other"]))
    check("子家照付全额（3 号位）", d4.get(3), -int(p4["from_other"]))
    check("自摸的人得点不变", d4.get(1), int(p4["total"]))

    # ── ④ 南场：没有这个技能 ────────────────────────────────────
    print("\n④ 南场无效")
    db5 = tg.fresh_db("ten_nan")
    rid5 = new_round(db5, 905, ORD_NAN_6, wind="nan")
    tg.set_hand(db5, rid5, 0, H_RON_DEALER, drawn="3p")
    tg.set_hand(db5, rid5, 1, H_RON_WINNER)
    g5 = Game(db5, rid5)
    check("南一场", g5.round_wind, "nan")
    check("南场持不生效", g5.owns_tenacity(0), False)
    check("state 里 tenacity=False", g5.state_for(0).get("tenacity"), False)
    to_discard(g5, 0)
    g5.act(0, "discard", tile="3p")
    g5.act(1, "ron")
    r5 = g5.result or {}
    check("南场照常全额放铳", (r5.get("deltas") or {}).get(0),
          -int((r5.get("pays") or {}).get("total", 0)))
    check("南场役种里没有「坚韧」",
          "坚韧（失点减半）" in [y["name"] for y in (r5.get("yaku") or [])], False)

    # ── ⑤ 自己赢了不受影响 ──────────────────────────────────────
    print("\n⑤ 坚韧持有者和牌时不减别人")
    db6 = tg.fresh_db("ten_win")
    rid6 = new_round(db6, 906, ORD_DONG_6)
    tg.set_hand(db6, rid6, 0, H_TSUMO, drawn="bai")
    mark_discarded(db6, rid6, 0)
    g6 = to_discard(Game(db6, rid6), 0)
    g6.act(0, "tsumo")
    r6 = g6.result or {}
    d6 = r6.get("deltas") or {}
    p6 = r6.get("pays") or {}
    check("我自摸和牌", r6.get("result"), "tsumo")
    check("赢家拿全额", d6.get(0), int(p6["total"]))
    check("别人照常付（合计为 0）", sum(d6.values()), 0)

    # ── ⑥ 没这张卡的人不受影响 ──────────────────────────────────
    print("\n⑥ 别人放铳，我没有这张卡就不减")
    db7 = tg.fresh_db("ten_other")
    rid7 = new_round(db7, 907, ORD_DONG_6)     # 只有 0 号持卡 6
    tg.set_hand(db7, rid7, 1, H_RON_DEALER, drawn="3p")
    tg.set_hand(db7, rid7, 2, H_RON_WINNER)
    g7 = to_discard(Game(db7, rid7), 1)
    g7.act(1, "discard", tile="3p")
    g7.act(2, "ron")
    r7 = g7.result or {}
    d7 = r7.get("deltas") or {}
    check("1 号放铳全额", d7.get(1), -int((r7.get("pays") or {}).get("total", 0)))
    check("没触发坚韧", "tenacity_payers" in r7, False)

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
