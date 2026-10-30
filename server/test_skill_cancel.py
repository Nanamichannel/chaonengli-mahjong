# -*- coding: utf-8 -*-
"""「技能还在选牌时，再点一次图标 = 取消这次发动」自测（服务端状态回退）

覆盖：风神（没换过 / 换过之后）、南风（选牌种 / 选完牌种）、自风、
      策略换牌机会、策略盖牌、没有可取消时的报错。
跑法： python test_skill_cancel.py
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")

from game import Game, RuleError  # noqa: E402
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
    uids = [db.create_user(f"cxl{seed}_{i}") for i in range(4)]
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


H_DEALER = ("123m456m789m123p5s5z", "bai")
H_2WIND = ("123m456p789s1z2z5p6p", None)
H_NOWIND = ("123m456m789m123p5s", None)
H_1WIND = ("123m456m789m12p4z5z", None)


def main() -> int:
    print("=" * 70)
    print(" 天才麻将少女 · 技能取消（再点一次图标）")
    print("=" * 70)

    # ── ① 风神：一张都没换就取消 → 当没发动，窗口还在等我 ────────────
    print("\n① 风神 stage=0 取消")
    db = tg.fresh_db("cxl_a")
    rid = new_round(db, 701,
                    [[4, 1, 2, 3, 41], [5, 1, 2, 3, 8],
                     [1, 2, 3, 6, 9], [1, 2, 3, 6, 10]],
                    [(0, *H_DEALER), (1, *H_2WIND), (2, *H_NOWIND), (3, *H_1WIND)])
    g = Game(db, rid)
    before = g.hand(0)
    r = g.deal_action(0, "use", 4, 1)
    check("风神发动起来了", bool((r.get("flow") or {})), True)
    c = g.skill_cancel(0, "fengshen")
    check("取消了", c.get("cancelled"), True)
    check("种类是风神", c.get("kind"), "fengshen")
    check("算没发动过", c.get("used"), False)
    check("流程清空", g.deal_flow, None)
    check("还留在配牌窗口等我", 0 in sorted(g.deal_wait), True)
    check("阶段还是 deal_skill", g.phase, "deal_skill")
    check("手牌没动", g.hand(0), before)
    check("窗口里还能看到风神",
          [(x["card"], x["skill"]) for x in g.state_for(0)["deal_skill"]["mine"]], [(4, 1)])
    check("图标没变灰", 0 in g.deal_used, False)
    r2 = g.deal_action(0, "use", 4, 1)
    check("取消后能重新发动", bool((r2.get("flow") or {})), True)

    # ── ② 风神：已经换了一家再取消 → 算用掉，窗口关掉 ────────────────
    print("\n② 风神 stage=1 之后取消")
    g.deal_swap(0, 0, ["1m", "2m"])
    check("已经换了一家（对家没风牌自动跳过）", int(g.deal_flow.get("stage")) >= 1, True)
    c = g.skill_cancel(0, "fengshen")
    check("取消了", c.get("cancelled"), True)
    check("算用掉了", c.get("used"), True)
    check("流程清空", g.deal_flow, None)
    check("窗口里没有我了", sorted(g.deal_wait), [])
    check("阶段变成切牌", g.phase, "discard")
    check("图标要变灰", 0 in g.deal_used, True)

    # ── ③ 南风：选牌种 / 选完牌种 两种阶段取消都不算用掉 ─────────────
    print("\n③ 南风取消（南一局）")
    db = tg.fresh_db("cxl_b")
    rid = new_round(db, 702,
                    [[1, 3, 6, 2, 11], [1, 3, 5, 2, 12],
                     [1, 3, 5, 2, 13], [1, 3, 5, 2, 14]],
                    [(0, *H_DEALER), (1, *H_2WIND), (2, *H_NOWIND), (3, *H_1WIND)],
                    wind="nan")
    g = Game(db, rid)
    r = g.deal_action(0, "use", 6, 1)
    check("南风开了选牌种", (r.get("flow") or {}).get("stage"), "kinds")
    c = g.skill_cancel(0)
    check("取消（选牌种阶段）", c.get("cancelled"), True)
    check("算没发动过", c.get("used"), False)
    check("还留在窗口里", 0 in sorted(g.deal_wait), True)
    g.deal_action(0, "use", 6, 1)
    g.south_wind_kinds(0, ["1m", "2m"])
    check("现在是选两张手牌", g.deal_flow.get("stage"), "hand")
    c = g.skill_cancel(0)
    check("取消（选手牌阶段）", c.get("used"), False)
    check("手牌没被换走", len(g.hand(1)), 13)

    # ── ④ 自风：取消 = 不换，回合还给摸牌的人 ───────────────────────
    print("\n④ 自风取消")
    db = tg.fresh_db("cxl_c")
    rid = new_round(db, 703,
                    [[4, 1, 2, 3, 41], [5, 1, 2, 3, 8],
                     [1, 2, 3, 6, 9], [1, 2, 3, 6, 10]],
                    [(0, *H_DEALER),
                     (1, "123m456p789s1z5p5p6p", "1z"),
                     (2, *H_NOWIND), (3, *H_1WIND)])
    g = Game(db, rid)
    g.self_wind.add(0)
    g.wind_swap = {"owner": 0, "from": 1, "tile": "dong"}
    g.phase = "wind_swap"
    g.save_flags()
    mine_before = g.hand(0)
    c = g.skill_cancel(0, "self_wind")
    check("取消了", c.get("cancelled"), True)
    check("种类是自风", c.get("kind"), "self_wind")
    check("自风交换清空", g.wind_swap, None)
    check("回合还给摸牌的人", (g.phase, g.turn), ("discard", 1))
    check("自己的手牌没变", g.hand(0), mine_before)
    check("对方还留着那张东", g.hand(1).count("dong"), 1)

    # ── ⑤ 策略：换牌机会 / 盖牌 取消 ────────────────────────────────
    print("\n⑤ 策略：换牌机会 / 盖牌 取消")
    db = tg.fresh_db("cxl_d")
    rid = new_round(db, 704,
                    [[1, 2, 3, 6, 5], [1, 2, 3, 6, 8],
                     [1, 2, 3, 6, 9], [1, 2, 3, 6, 10]],
                    [(0, *H_DEALER), (1, *H_2WIND), (2, *H_NOWIND), (3, *H_1WIND)])
    g = Game(db, rid)
    check("0 号持策略（协战位）", g.owns_card05(0), True)
    g.card05_offer[0] = {"by": 1, "reason": "风神"}
    c = g.skill_cancel(0, "card05_offer")
    check("换牌机会取消了", c.get("kind"), "card05_offer")
    check("机会没了", g.card05_offer.get(0), None)
    g.card05_pending_hide[0] = 2
    c = g.skill_cancel(0, "card05_hide")
    check("盖牌取消了", c.get("kind"), "card05_hide")
    check("盖牌请求没了", g.card05_pending_hide.get(0), None)
    try:
        g.skill_cancel(0)
        check("没有可取消的要报错", False)
    except RuleError as e:
        check("没有可取消的要报错", "没有可以取消" in str(e))

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
