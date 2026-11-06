# -*- coding: utf-8 -*-
"""Card10 Skill2「四喜」自测。

· 摸牌后发动一次：手里/副露要有 3 张东 + 3 张北，手里的那几张明置
· 第 5 张摸到的牌直接视为小四喜自摸（不用点按钮；可以被「禁止自摸」无效掉）
· 期间不能打出手里的东/北；就绪那巡不打就作废
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
    uids = [db.create_user(f"fj{seed}_{i}") for i in range(4)]
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


def add_meld(db, rid, seat: int, meld_id: int, kind: str, tiles: list[str]) -> None:
    with db.tx():
        db.conn.execute(
            "INSERT INTO round_melds(round_id, seat, meld_id, kind, called_tile, from_seat,"
            " tiles_json, rot_index, seqs_json) VALUES(?,?,?,?,?,?,?,?,?)",
            (rid, seat, meld_id, kind, tiles[0], 1, json.dumps(tiles), 0, "[]"))


ORD_10 = [[10, 1, 2, 3, 4], [1, 2, 3, 5, 6], [1, 2, 3, 5, 7], [1, 2, 3, 5, 8]]
# 手里 3 张东 + 2 张北，副露再来一组北刻子 = 3 东 + 3 北
H_ME = parse_hand("123m456p789s") + ["dong", "dong", "dong", "bei", "bei", "9s"]


def to_discard(g: Game, seat: int) -> Game:
    g.round_phase = "play"
    g.turn = seat
    g.phase = "discard"
    g.save_flags()
    return g


def main() -> int:
    print("=" * 70)
    print(" 天才麻将少女 · Card10 Skill2「四喜」")
    print("=" * 70)

    # ── ① 登记 ──────────────────────────────────────────────────
    print("\n① 技能登记")
    check("skills.has(10,2)", skills.has(10, 2))
    check("名字是「四喜」", skills.info(10, 2).get("name"), "四喜")
    check("时机是摸牌", skills.timing(10, 2), "draw")

    # ── ② 发动条件：3 东 + 3 北 ────────────────────────────────
    print("\n② 手里/副露要有 3 张东 + 3 张北")
    db = tg.fresh_db("fj_gate")
    rid = new_round(db, 961, ORD_10)
    tg.set_hand(db, rid, 0, H_ME, drawn="9s")
    g = to_discard(Game(db, rid), 0)
    check("手里 3 东 2 北 + 没副露 → 不能发动", g._c10s2_can(0), False)
    add_meld(db, rid, 0, 0, "pon", ["bei", "bei", "bei"])
    g = to_discard(Game(db, rid), 0)
    check("补一组北刻子 → 可以发动", g._c10s2_can(0), True)
    check("数得对（3 东 / 5 北：手里 2 + 副露 3）", g._c10s2_counts(0), (3, 5))
    check("state 里 card10s2_can=True", g.state_for(0)["card10s2_can"], True)
    check("1 号没有这张卡", g.owns_card10(1), False)

    # ── ③ 发动：明置手里的东/北 ────────────────────────────────
    print("\n③ 发动：明置手里的东/北")
    r = g.card10s2_activate(0)
    check("发动成功", r.get("seat"), 0)
    check("数到第 0 张", int(r.get("count", -1)), 0)
    check("只明置手里的 3 张东（北刻子本来就能看见）",
          sorted(r.get("reveal") or []), ["dong", "dong", "dong"])
    g2 = Game(db, rid)
    check("落库了", bool(g2.c10s2.get(0)), True)
    try:
        g2.card10s2_activate(0)
        check("再发动要拒绝", False)
    except RuleError as e:
        check("再发动要拒绝", "用过" in str(e))
    pub = g2.state_for(1).get("c10s2_reveal") or []
    check("别人也能看到明置的牌", bool(pub), True)
    check("别人看到 3 张东", len(pub[0]["tiles"]), 3)
    check("state 里明置的牌", sorted(g2.state_for(0)["card10s2_reveal"]),
          ["dong", "dong", "dong"])

    # ── ④ 期间不能打东/北 ─────────────────────────────────────
    print("\n④ 期间不能打出手里的东/北")
    try:
        g2.act(0, "discard", tile="dong")
        check("打东要拒绝", False)
    except RuleError as e:
        check("打东要拒绝", "东或北" in str(e))
    try:
        g2.act(0, "discard", tile="bei")
        check("打北要拒绝", False)
    except RuleError as e:
        check("打北要拒绝", "东或北" in str(e))

    # ── ⑤ 第 5 次摸牌 → 小四喜 ────────────────────────────────
    print("\n⑤ 第 5 次摸牌 → 就绪 + 直接结算")
    g3 = Game(db, rid)
    for i in range(4):
        g3._c10s2_on_draw(0)
    g3 = Game(db, rid)
    check("数到第 4 张还没就绪", g3._c10s2_ready(0), False)
    check("state 里 count=4", g3.state_for(0)["card10s2_count"], 4)
    g3._c10s2_on_draw(0)
    g3 = Game(db, rid)
    check("第 5 张就绪", g3._c10s2_ready(0), True)
    check("state 里 ready=True", g3.state_for(0)["card10s2_ready"], True)
    # 手牌根本不成和牌型，但就绪后自摸成立
    tg.set_hand(db, rid, 0, parse_hand("1m4m7m2p5p8p3s6s9s1z4z6z7z"), drawn="7z")
    g3 = to_discard(Game(db, rid), 0)
    check("乱牌也能自摸（就绪）", g3._win_ok(0, "7z", tsumo=True), True)
    res = g3._judge_win(0, "7z", tsumo=True)
    check("判成小四喜", [y["name"] for y in (res or {}).get("yaku", [])], ["四喜"])
    check("是役满", int((res or {}).get("yakuman", 0)), 1)
    check("点数按役满算", int(((res or {}).get("pays") or {}).get("total", 0)) > 0, True)

    # ── ⑤b 第 5 张摸牌 → 直接结算（2026-10-30 用户口径）────────
    print("\n⑤b 第 5 张摸牌直接结算（不用点按钮）")
    db6 = tg.fresh_db("fj_auto")
    rid6 = new_round(db6, 963, ORD_10)
    tg.set_hand(db6, rid6, 0, H_ME, drawn="9s")
    add_meld(db6, rid6, 0, 0, "pon", ["bei", "bei", "bei"])
    g6 = to_discard(Game(db6, rid6), 0)
    g6.card10s2_activate(0)
    for i in range(5):
        g6._c10s2_on_draw(0)
    g6 = to_discard(Game(db6, rid6), 0)
    check("第 5 张前：没就绪", g6._c10s2_ready(0), True)
    ev = g6._c10s2_auto_tsumo(0, "7z")
    check("第 5 张摸牌直接结算", (ev or {}).get("event"), "tsumo")
    check("结算成小四喜",
          "四喜" in [y["name"] for y in ((g6.result or {}).get("yaku") or [])],
          True)
    check("本局结束", (g6.result or {}).get("result"), "tsumo")
    g6b = Game(db6, rid6)
    check("状态清掉（不能再触发）", g6b._c10s2_ready(0), False)

    # ── ⑥ 能被「禁止自摸」无效掉 ───────────────────────────────
    print("\n⑥ 决斗里（非决斗家 + 立直）不能自摸 → 四喜白搭")
    g4 = to_discard(Game(db, rid), 0)
    g4.duel = {"by": 1, "target": 2}          # 0 号被限制
    g4.save_flags()
    with db.tx():
        db.conn.execute("INSERT OR REPLACE INTO round_riichi(round_id, seat, declared_seq)"
                        " VALUES(?,?,?)", (rid, 0, 1))
    g4 = to_discard(Game(db, rid), 0)
    check("还是就绪状态", g4._c10s2_ready(0), True)
    check("但被决斗封住自摸", g4._win_ok(0, "7z", tsumo=True), False)

    # ── ⑦ 就绪那巡不打 → 作废 ─────────────────────────────────
    print("\n⑦ 就绪了却没和：打牌就作废")
    db5 = tg.fresh_db("fj_waste")
    rid5 = new_round(db5, 962, ORD_10)
    tg.set_hand(db5, rid5, 0, H_ME, drawn="9s")
    add_meld(db5, rid5, 0, 0, "pon", ["bei", "bei", "bei"])
    g5 = to_discard(Game(db5, rid5), 0)
    g5.card10s2_activate(0)
    for i in range(5):
        g5._c10s2_on_draw(0)
    g5 = to_discard(Game(db5, rid5), 0)
    check("就绪", g5._c10s2_ready(0), True)
    tg.set_hand(db5, rid5, 0, parse_hand("123m456p789s123p5z"), drawn="bai")
    g5 = to_discard(Game(db5, rid5), 0)
    g5.act(0, "discard", tile="bai")         # 没和，正常打（白不是东/北）
    g5 = Game(db5, rid5)
    check("打完就作废", g5._c10s2_ready(0), False)
    check("四喜状态清空", g5.c10s2.get(0), None)

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
