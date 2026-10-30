# -*- coding: utf-8 -*-
"""Card04 Skill1「风神」自测
跑法： python test_card04.py
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


def new_round(db, seed: int, orders) -> int:
    uids = [db.create_user(f"c04{seed}_{i}") for i in range(4)]
    room = db.create_room(uids[0])
    for u in uids[1:]:
        db.join_room(room["room_code"], u)
    match = db.start_match(room["room_id"], seed=seed)
    rid = db.start_round(match, "dong", 1, honba=0, dealer_seat=0, seed=seed)
    seats = [{"ready": False, "hand": [], "picks": [], "order": [41 if int(v) == 7 else int(v) for v in o]} for o in orders]
    body = {"seats": seats, "phase": "playing"}
    with db.tx():
        db.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('lobby_state', ?)",
                        (json.dumps(body, ensure_ascii=False),))
    return rid


def deal_all(g: Game) -> None:
    g.start()
    while not g.deal_done():
        g.deal_step()


def hand_of(g: Game, seat: int) -> list[str]:
    return g.hand(seat)


def main() -> int:
    print("=" * 70)
    print(" 天才麻将少女 · Card04 Skill1「风神」")
    print("=" * 70)

    # ── 1. 登记 / 时机 ──────────────────────────────────────────
    print("\n① 技能登记")
    check("skills.has(4,1)", skills.has(4, 1))
    check("名字是「风神」", skills.info(4, 1).get("name"), "风神")
    check("时机是配牌", skills.timing(4, 1), "deal")
    check("配牌技能里多了 4-1", (4, 1) in skills.deal_skills())

    # ── 2. 配牌窗口里能发动 ────────────────────────────────────
    print("\n② 配牌窗口")
    db = tg.fresh_db("c04_deal")
    rid = new_round(db, seed=111, orders=[[4, 1, 2, 3, 5], [1, 2, 3, 5, 6],
                                          [2, 3, 5, 6, 7], [1, 3, 5, 6, 7]])
    g = Game(db, rid)
    deal_all(g)
    check("阶段是 deal_skill", g.phase, "deal_skill")
    st = g.state_for(0)
    check("窗口里能看到风神",
          [(x["card"], x["skill"]) for x in st["deal_skill"]["mine"]], [(4, 1)])

    # 手上：庄家 14 张；下家 3 张风牌；对家没有；上家 1 张风牌
    tg.set_hand(db, rid, 0, parse_hand("123m456m789m123p5s5z"), drawn="bai")
    tg.set_hand(db, rid, 1, parse_hand("123m456p789s1z2z3z5p"))
    tg.set_hand(db, rid, 2, parse_hand("123m456m789m123p5s"))
    tg.set_hand(db, rid, 3, parse_hand("123m456m789m12p5z4z"))
    g = Game(db, rid)
    check("庄家 14 张", len(hand_of(g, 0)), 14)
    check("下家风牌 3 张", [r["tile"] for r in g._winds_of(1)], ["dong", "nan", "xi"])
    check("对家风牌 0 张", g._winds_of(2), [])
    check("上家风牌 1 张", [r["tile"] for r in g._winds_of(3)], ["bei"])

    # ── 3. 发动：先跟下家换 3 张 ───────────────────────────────
    print("\n③ 发动：先换下家")
    r = g.deal_action(0, "use", 4, 1)
    check("发动成功", r.get("armed"), True)
    check("kind=deal_swap", r.get("kind"), "deal_swap")
    flow = r.get("flow") or {}
    check("第一步是下家（1 号位）", flow.get("target"), 1)
    check("要选 3 张", flow.get("n"), 3)
    check("窗口还在等我（没做完）", sorted(g.deal_wait), [0])
    check("流程中不再给「开始」", g.state_for(0)["deal_skill"]["mine"], [])
    check("state 里有流程", g.state_for(0)["deal_flow"].get("n"), 3)
    check("别人看不到我的流程", g.state_for(1).get("deal_flow"), None)

    # 张数不对要拒绝
    try:
        g.deal_swap(0, 0, ["1m"])
        check("张数不对要拒绝", False)
    except RuleError as e:
        check("张数不对要拒绝", "要选 3 张" in str(e))
    try:
        g.deal_swap(0, 0, ["9p", "9p", "9p"])
        check("手里没有的牌要拒绝", False)
    except RuleError as e:
        check("手里没有的牌要拒绝", "手里没有" in str(e))

    # 正常换：1m 2m 5s（5s 是刚摸的那张）
    r1 = g.deal_swap(0, 0, ["1m", "2m", "bai"])
    check("换到 3 张风牌", sorted(r1.get("got") or []), ["dong", "nan", "xi"])
    g = Game(db, rid)
    mine = hand_of(g, 0)
    check("手牌还是 14 张", len(mine), 14)
    check("风牌都到我手上了",
          [t for t in mine if t in ("dong", "nan", "xi", "bei")],
          ["dong", "nan", "xi"])
    check("换出去的手牌去了下家", sorted(hand_of(g, 1)),
          sorted(parse_hand("123m456p789s5p1m2m") + ["bai"]))
    check("下家手牌还是 13 张", len(hand_of(g, 1)), 13)
    check("刚摸的牌被换走 → 换进来的风牌顶上", g.drawn_tile(0) in ("dong", "nan", "xi"))

    # ── 4. 自动跳到上家（对家没有风牌）─────────────────────────
    print("\n④ 对家没风牌 → 直接跳到上家")
    nxt = r1.get("next") or {}
    check("下一步是上家（3 号位）", nxt.get("target"), 3)
    check("上家要换 1 张", nxt.get("n"), 1)

    r2 = g.deal_swap(0, 2, ["3m"])
    check("换到上家的风牌", r2.get("got"), ["bei"])
    check("流程结束", r2.get("next"), None)
    check("窗口关掉、进入切牌", g.phase, "discard")
    check("可以正常切牌了", "discard" in {a["action"] for a in g.legal_actions(0)}, True)
    g = Game(db, rid)
    mine = hand_of(g, 0)
    check("四张风牌都在手上",
          sorted([t for t in mine if t in ("dong", "nan", "xi", "bei")]),
          ["bei", "dong", "nan", "xi"])
    check("上家手牌还是 13 张", len(hand_of(g, 3)), 13)
    check("上家拿到了我的 3m", "3m" in hand_of(g, 3))

    # ── 5. 三家都没风牌 → 发动后立刻结束 ──────────────────────
    print("\n⑤ 三家都没有风牌：发动即结束")
    db5 = tg.fresh_db("c04_none")
    rid5 = new_round(db5, seed=112, orders=[[4, 1, 2, 3, 5], [1, 2, 3, 5, 6],
                                            [2, 3, 5, 6, 7], [1, 3, 5, 6, 7]])
    g5 = Game(db5, rid5)
    deal_all(g5)
    tg.set_hand(db5, rid5, 1, parse_hand("123m456m789m123p5s"))
    tg.set_hand(db5, rid5, 2, parse_hand("123m456m789m123p5s"))
    tg.set_hand(db5, rid5, 3, parse_hand("123m456m789m123p5s"))
    g5 = Game(db5, rid5)
    r5 = g5.deal_action(0, "use", 4, 1)
    check("发动成功", r5.get("armed"), True)
    check("没有下一步", r5.get("flow"), None)
    check("直接进入切牌", g5.phase, "discard")
    check("窗口清空", g5.deal_wait, set())

    # ── 6. 流程中不能改主意 / 不能跳 ──────────────────────────
    print("\n⑥ 流程中不能再做别的决定")
    db6 = tg.fresh_db("c04_busy")
    rid6 = new_round(db6, seed=113, orders=[[4, 1, 2, 3, 5], [1, 2, 3, 5, 6],
                                            [2, 3, 5, 6, 7], [1, 3, 5, 6, 7]])
    g6 = Game(db6, rid6)
    deal_all(g6)
    tg.set_hand(db6, rid6, 1, parse_hand("123m456p789s1z2z3z5p"))
    g6 = Game(db6, rid6)
    g6.deal_action(0, "use", 4, 1)
    busy = g6.deal_action(0, "skip")
    check("流程中跳过被忽略", busy.get("busy"), True)
    check("还在流程里", (g6.deal_flow or {}).get("stage"), 0)
    try:
        g6.deal_swap(0, 1, ["1m", "2m", "3m"])
        check("阶段不对要拒绝", False)
    except RuleError as e:
        check("阶段不对要拒绝", "阶段" in str(e))

    # ── 7. 没这张卡就不弹窗口 ─────────────────────────────────
    print("\n⑦ 没这张卡：不弹窗口")
    db7 = tg.fresh_db("c04_noown")
    rid7 = new_round(db7, seed=114, orders=[[1, 2, 3, 5, 6], [2, 3, 5, 6, 7],
                                            [1, 3, 5, 6, 7], [1, 2, 5, 6, 7]])
    g7 = Game(db7, rid7)
    deal_all(g7)
    check("直接切牌", g7.phase, "discard")
    check("没有配牌窗口", g7.deal_wait, set())

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
