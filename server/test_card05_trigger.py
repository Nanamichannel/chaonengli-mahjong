# -*- coding: utf-8 -*-
"""Card05 Skill1「策略」：被别的玩家技能换手牌时的触发自测

技能原文（Cailiao/skill/ui/skills.json）：
    「……因其他玩家技能导致手牌变动时，可以从王牌、弃牌中选择一张与手牌交换……」

所以「风神」（Card04 S1）、「南风」（Card06 S1）、「自风」（Card04 S2）
换走我的牌时必须给持有策略的人：计数器 +1 + 一次换牌机会；
自己用自己的技能不算；手牌没被换到的人（南风经常有人没指定牌）也不能算。

跑法： python test_card05_trigger.py
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")

from game import Game, RuleError  # noqa: E402
from rules import wallmodel  # noqa: E402
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


def new_round(db, seed: int, orders, hands, wind="dong", number=1) -> int:
    """开局 + 把四家各持哪 5 张人物卡写进 lobby_state（owns_card 要读它）+ 摆好手牌。

    注意顺序：先配牌（deal_step），再改手牌，否则配牌会把改过的手牌盖掉。
    """
    uids = [db.create_user(f"c05t{seed}_{i}") for i in range(4)]
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
    g = Game(db, rid)
    g.start()
    while not g.deal_done():
        g.deal_step()
    for seat, text, drawn in hands:
        tg.set_hand(db, rid, seat, parse_hand(text), drawn=drawn)
    return rid


def counter(g: Game, seat: int) -> int:
    return int(g.card05_counter.get(int(seat), 0))


# 各家手牌（东一：庄家 14 张，闲家 13 张）
H_DEALER = ("123m456m789m123p5s5z", "bai")
H_2WIND = ("123m456p789s1z2z5p6p", None)
H_1WIND = ("123m456m789m12p4z5z", None)
H_NOWIND = ("123m456m789m123p5s", None)


def main() -> int:
    print("=" * 70)
    print(" 天才麻将少女 · Card05 Skill1「策略」× 别人的换牌技能")
    print("=" * 70)

    # ── ① 风神：下家被换牌 → 计数 +1 + 换牌机会 ────────────────────
    print("\n① 风神（Card04 S1）换走对手的手牌")
    db = tg.fresh_db("c05_trigger_a")
    rid = new_round(db, 601,
                    [[4, 1, 2, 3, 7],       # 0 号：风神，没有策略
                     [5, 1, 2, 3, 8],       # 1 号：策略
                     [1, 2, 3, 6, 9],       # 2 号：没策略
                     [1, 2, 3, 6, 10]],     # 3 号：没策略
                    [(0, *H_DEALER), (1, *H_2WIND), (2, *H_NOWIND), (3, *H_1WIND)])
    g = Game(db, rid)
    check("开局阶段是 deal_skill", g.phase, "deal_skill")
    check("1 号持有策略", g.owns_card05(1), True)
    check("0 号没有策略", g.owns_card05(0), False)
    check("下家手牌 13 张", len(g.hand(1)), 13)
    check("下家 2 张风牌", [r["tile"] for r in g._winds_of(1)], ["dong", "nan"])

    r = g.deal_action(0, "use", 4, 1)
    flow = r.get("flow") or {}
    check("风神先跟下家换", flow.get("target"), 1)
    check("下家有 2 张风牌", flow.get("n"), 2)

    g.deal_swap(0, 0, ["1m", "2m"])
    check("下家（持策略）计数 +1", counter(g, 1), 1)
    offer = g.card05_offer.get(1) or {}
    check("下家拿到了换牌机会", bool(offer), True)
    check("机会来由是风神", offer.get("reason"), "风神")
    check("机会是谁给的", offer.get("by"), 0)
    check("发动者自己不加计数", counter(g, 0), 0)
    check("对家（没被换牌）不加计数", counter(g, 2), 0)
    st = g.state_for(1)
    check("state 里能看到计数", int(st["card05"]["counter"]), 1)
    check("state 里能看到换牌机会", bool(st["card05"]["offer"]), True)
    check("别人看不到我的换牌机会", g.state_for(0)["card05"]["offer"], None)

    # 配牌阶段就把这次机会用掉（换王牌），换完机会消失
    dstack = wallmodel.dead_stack_nos(g.wall_first_stack())[0]
    before = g.hand(1)
    sw = g.card05_swap(1, str(before[0]), "dead", stack=dstack, half="top")
    check("配牌阶段能换王牌", str(sw.get("got", "")) != "", True)
    check("换完机会就没了", g.card05_offer.get(1), None)
    check("手牌张数不变", len(g.hand(1)), len(before))

    # ── ② 自己用自己的技能不算 ────────────────────────────────────
    print("\n② 发动者自己也持有策略 → 自己不算「被别人动」")
    db = tg.fresh_db("c05_trigger_b")
    rid = new_round(db, 602,
                    [[5, 1, 2, 3, 4],       # 0 号：策略（主战）+ 风神（协战）
                     [5, 1, 2, 3, 8],
                     [1, 2, 3, 6, 9],
                     [1, 2, 3, 6, 10]],
                    [(0, *H_DEALER), (1, *H_2WIND), (2, *H_NOWIND), (3, *H_1WIND)])
    g = Game(db, rid)
    check("0 号同时持有策略", g.owns_card05(0), True)
    g.deal_action(0, "use", 4, 1)
    g.deal_swap(0, 0, ["1m", "2m"])
    check("自己的技能不动自己的计数", counter(g, 0), 0)
    check("对手照样 +1", counter(g, 1), 1)

    # ── ③ 南风：只算真的被换到牌的人 ──────────────────────────────
    print("\n③ 南风（Card06 S1）三家都持策略，但只有被换到的算")
    db = tg.fresh_db("c05_trigger_c")
    # 南风只有南场才有 → 南一局，主战卡用 order[2]（东一东二→0，东三东四→1，南一南二→2）
    rid = new_round(db, 603,
                    [[1, 3, 6, 2, 11],      # 0 号：南风
                     [1, 3, 5, 2, 12],      # 1 号：策略，手里有 1m
                     [1, 3, 5, 2, 13],      # 2 号：策略，手里有 2m
                     [1, 3, 5, 2, 14]],     # 3 号：策略，手里有 1m（轮不到）
                    [(0, *H_DEALER),
                     (1, "345m678p123s5s1m5p6p", None),   # 只有 1m
                     (2, "345m678p123s5s2m5p6p", None),   # 只有 2m
                     (3, "345m678p123s5s1m5p6p", None)],  # 只有 1m（我牌已换完，轮不到）
                    wind="nan")
    g = Game(db, rid)
    check("开局是南一", g.round_wind, "nan")
    check("三家都持有策略", [g.owns_card05(s) for s in (1, 2, 3)], [True, True, True])
    r = g.deal_action(0, "use", 6, 1)
    check("南风开窗口", (r.get("flow") or {}).get("stage"), "kinds")
    g.south_wind_kinds(0, ["1m", "2m"])
    sw = g.south_wind_swap(0, ["3m", "4m"])
    check("换了两家（我只有两张手牌）", sw.get("count"), 2)
    got = [str(x["got"]) for x in sw.get("swaps") or []]
    check("换回来的牌", sorted(got), ["1m", "2m"])
    check("被换到的下家 +1", counter(g, 1), 1)
    check("被换到的对家 +1", counter(g, 2), 1)
    check("没被换到的上家不算（虽然持策略）", counter(g, 3), 0)
    check("换牌机会来由是南风", (g.card05_offer.get(1) or {}).get("reason"), "南风")
    check("上家没有换牌机会", g.card05_offer.get(3), None)

    # ── ④ 自风：摸牌的人手牌被换 → 算 ────────────────────────────
    print("\n④ 自风（Card04 S2）换走摸牌人的风牌")
    db = tg.fresh_db("c05_trigger_d")
    rid = new_round(db, 604,
                    [[4, 1, 2, 3, 7],
                     [5, 1, 2, 3, 8],
                     [1, 2, 3, 6, 9],
                     [1, 2, 3, 6, 10]],
                    [(0, *H_DEALER),
                     (1, "123m456p789s1z5p5p6p", "1z"),
                     (2, *H_NOWIND), (3, *H_1WIND)])
    g = Game(db, rid)
    check("1 号持有策略", g.owns_card05(1), True)
    check("1 号手里有刚摸到的东", g.hand(1).count("dong"), 1)
    g.self_wind.add(0)                         # 0 号发动了「自风」
    g.wind_swap = {"owner": 0, "from": 1, "tile": "dong"}
    g.phase = "wind_swap"
    g.save_flags()
    r = g.wind_swap_apply(0, "9m")
    check("自风换牌成功", r.get("got"), "dong")
    check("摸牌的人（持策略）计数 +1", counter(g, 1), 1)
    check("机会来由是自风", (g.card05_offer.get(1) or {}).get("reason"), "自风")
    check("自风发动者自己不加计数", counter(g, 0), 0)

    # ── ⑤ 没持卡的人一律不触发 ────────────────────────────────────
    print("\n⑤ 没有策略的人不会被记计数")
    db = tg.fresh_db("c05_trigger_e")
    rid = new_round(db, 605,
                    [[4, 1, 2, 3, 7],
                     [1, 2, 3, 6, 8],
                     [1, 2, 3, 6, 9],
                     [1, 2, 3, 6, 10]],
                    [(0, *H_DEALER), (1, *H_2WIND), (2, *H_NOWIND), (3, *H_1WIND)])
    g = Game(db, rid)
    check("1 号没有策略", g.owns_card05(1), False)
    g.deal_action(0, "use", 4, 1)
    g.deal_swap(0, 0, ["1m", "2m"])
    check("没持卡 → 不计数", counter(g, 1), 0)
    check("没持卡 → 没有换牌机会", g.card05_offer.get(1), None)

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
