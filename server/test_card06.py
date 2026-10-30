# -*- coding: utf-8 -*-
"""Card06 Skill1「南风」自测
跑法： python test_card06.py
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


def new_round(db, seed: int, wind: str = "nan", owner=True) -> int:
    uids = [db.create_user(f"sw6{seed}_{i}") for i in range(4)]
    room = db.create_room(uids[0])
    for u in uids[1:]:
        db.join_room(room["room_code"], u)
    match = db.start_match(room["room_id"], seed=seed)
    rid = db.start_round(match, wind, 1, honba=0, dealer_seat=0, seed=seed)
    # 其他三家不要带 3/4/6/7（那几张有配牌技能，会把窗口撑出更多人）
    order = [1, 2, 6, 5, 9] if owner else [1, 2, 5, 9, 8]
    orders = [order, [1, 2, 5, 9, 8], [2, 5, 9, 8, 1], [1, 5, 9, 8, 2]]
    body = {"seats": [{"ready": False, "hand": [], "picks": [], "order": o} for o in orders],
            "phase": "playing"}
    with db.tx():
        db.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('lobby_state', ?)",
                        (json.dumps(body, ensure_ascii=False),))
    g = Game(db, rid)                 # 卡序先写好，配牌结束才会弹出窗口
    g.start()
    while not g.deal_done():
        g.deal_step()
    return rid


def set_table(db, rid):
    tg.set_hand(db, rid, 0, parse_hand("1m1m2m3m4m5m6m7m8m9m1p2p3p5z"), drawn="bai")
    tg.set_hand(db, rid, 1, parse_hand("1m9p2p3p4p5p6p7p8p1s2s3s5z"))
    tg.set_hand(db, rid, 2, parse_hand("4m5m6m1s2s3s7s8s9s5z6z7z2z"))
    tg.set_hand(db, rid, 3, parse_hand("9p4p5p6p1s2s3s7s8s9s5z6z7z"))


def rich_hand(g: Game, seat: int) -> list[str]:
    return g.hand(seat)


def main() -> int:
    print("=" * 70)
    print(" 天马麻将 · Card06 Skill1「南风」")
    print("=" * 70)

    print("\n① 技能登记")
    check("skills.has(6,1)", skills.has(6, 1))
    check("名字是「南风」", skills.info(6, 1).get("name"), "南风")
    check("时机是配牌", skills.timing(6, 1), "deal")

    # ── 2. 东场没有这个技能 ───────────────────────────────────
    print("\n② 东场：不出现")
    db0 = tg.fresh_db("sw6_east")
    rid0 = new_round(db0, seed=401, wind="dong")
    g0 = Game(db0, rid0)
    check("东场没有配牌窗口", g0.deal_wait, set())
    check("南风不在可选里",
          [(o["card"], o["skill"]) for o in g0._deal_skill_options(0) if o["card"] == 6], [])

    # ── 3. 南场：出现在配牌窗口 ───────────────────────────────
    print("\n③ 南场：配牌窗口里出现")
    db = tg.fresh_db("sw6_south")
    rid = new_round(db, seed=402, wind="nan")
    g = Game(db, rid)
    check("有配牌窗口", g.deal_wait, {0})
    opts = [(o["card"], o["skill"]) for o in g._deal_skill_options(0)]
    check("能看到南风", (6, 1) in opts, True)
    check("state 里也有", [(x["card"], x["skill"]) for x in
                           g.state_for(0)["deal_skill"]["mine"]], [(6, 1)])

    # ── 4. 选牌种 → 选手牌 → 交换 ─────────────────────────────
    print("\n④ 完整流程")
    r = g.deal_action(0, "use", 6, 1)
    check("发动成功", r.get("armed"), True)
    flow = r.get("flow") or {}
    check("流程 kind", flow.get("kind"), "south_wind")
    check("第一步选牌种", flow.get("stage"), "kinds")
    check("窗口还在等我", sorted(g.deal_wait), [0])

    r2 = g.south_wind_kinds(0, ["1m", "9p"])
    check("记录两种牌", r2.get("kinds"), ["1m", "9p"])
    check("下一步选手牌", (r2.get("flow") or {}).get("stage"), "hand")

    set_table(db, rid)
    g = Game(db, rid)
    mine_before = rich_hand(g, 0)
    r3 = g.south_wind_swap(0, ["2m", "3m"])
    swaps = r3.get("swaps") or []
    check("换了两张", len(swaps), 2)
    check("都是跟下家换的", [s["from"] for s in swaps], [1, 1])
    check("换进来的牌", sorted(s["got"] for s in swaps), ["1m", "9p"])
    check("换出去的牌", sorted(s["gave"] for s in swaps), ["2m", "3m"])
    check("技能结束、窗口关掉", g.phase, "discard")
    check("手牌还是 14 张", len(rich_hand(g, 0)), 14)
    check("手里有 1m 和 9p", all(t in rich_hand(g, 0) for t in ("1m", "9p")), True)
    check("下家手牌还是 13 张", len(rich_hand(g, 1)), 13)
    check("下家拿到了 2m/3m", all(t in rich_hand(g, 1) for t in ("2m", "3m")), True)
    check("没人碰过的对家/上家没变", len(rich_hand(g, 2)), 13)
    g2 = Game(db, rid)
    check("窗口已经关掉，不能再发动", g2.state_for(0)["deal_skill"]["mine"], [])

    # ── 5. 一家只有一张：继续找下一家 ─────────────────────────
    print("\n⑤ 下家只有一张 → 再跟对家换")
    db5 = tg.fresh_db("sw6_split")
    rid5 = new_round(db5, seed=403, wind="nan")
    g5 = Game(db5, rid5)
    g5.deal_action(0, "use", 6, 1)
    g5.south_wind_kinds(0, ["1m", "9p"])
    tg.set_hand(db5, rid5, 0, parse_hand("1m1m2m3m4m5m6m7m8m9m1p2p3p5z"), drawn="bai")
    tg.set_hand(db5, rid5, 1, parse_hand("1m2p3p4p5p6p7p8p1s2s3s5z6z"))
    tg.set_hand(db5, rid5, 2, parse_hand("9p4m5m6m1s2s3s7s8s9s6z7z2z"))
    tg.set_hand(db5, rid5, 3, parse_hand("4p5p6p1s2s3s7s8s9s5z6z7z2z"))
    g5 = Game(db5, rid5)
    r5 = g5.south_wind_swap(0, ["2m", "3m"])
    sw5 = r5.get("swaps") or []
    check("换了两次", len(sw5), 2)
    check("先下家再对家", [s["from"] for s in sw5], [1, 2])
    check("换到 1m 和 9p", sorted(s["got"] for s in sw5), ["1m", "9p"])

    # ── 6. 三家都没有 / 只有上家有 ────────────────────────────
    print("\n⑥ 三家都没有指定牌")
    db6 = tg.fresh_db("sw6_none")
    rid6 = new_round(db6, seed=404, wind="nan")
    g6 = Game(db6, rid6)
    g6.deal_action(0, "use", 6, 1)
    g6.south_wind_kinds(0, ["1m", "9p"])
    tg.set_hand(db6, rid6, 0, parse_hand("1m1m2m3m4m5m6m7m8m9m1p2p3p5z"), drawn="bai")
    for s in (1, 2, 3):
        tg.set_hand(db6, rid6, s, parse_hand("2p3p4p5p6p7p8p1s2s3s5z6z7z"))
    g6 = Game(db6, rid6)
    r6 = g6.south_wind_swap(0, ["2m", "3m"])
    check("一张都没换", r6.get("count"), 0)
    check("牌种还在手里", all(t in rich_hand(g6, 0) for t in ("2m", "3m")), True)
    check("技能结束", g6.phase, "discard")

    # ── 7. 参数校验 ───────────────────────────────────────────
    print("\n⑦ 参数校验")
    db7 = tg.fresh_db("sw6_bad")
    rid7 = new_round(db7, seed=405, wind="nan")
    g7 = Game(db7, rid7)
    g7.deal_action(0, "use", 6, 1)
    for name, kinds, want in [
        ("牌种必须两种", ["1m"], "两种"),
        ("牌种不能重复", ["1m", "1m"], "不同"),
        ("牌种要认识", ["1m", "zz"], "没有这种牌"),
    ]:
        try:
            g7.south_wind_kinds(0, kinds)
            check(name, False)
        except RuleError as e:
            check(name, want in str(e))
    g7.south_wind_kinds(0, ["1m", "9p"])
    tg.set_hand(db7, rid7, 0, parse_hand("1m2m3m4m5m6m7m8m9m1p2p3p5z"), drawn="bai")
    g7 = Game(db7, rid7)
    try:
        g7.south_wind_swap(0, ["2m"])
        check("手牌要两张", False)
    except RuleError as e:
        check("手牌要两张", "两张手牌" in str(e))
    try:
        g7.south_wind_swap(0, ["2m", "zhong"])
        check("手里没有的牌要拒绝", False)
    except RuleError as e:
        check("手里没有的牌要拒绝", "手里没有" in str(e))

    # ── 8. 东场不能发动 ───────────────────────────────────────
    print("\n⑧ 东场不能发动")
    db8 = tg.fresh_db("sw6_east2")
    rid8 = new_round(db8, seed=406, wind="dong")
    g8 = Game(db8, rid8)
    try:
        g8.south_wind_kinds(0, ["1m", "9p"])
        check("东场不能发动", False)
    except RuleError as e:
        check("东场不能发动", "南风" in str(e))

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
