# -*- coding: utf-8 -*-
"""摸牌前询问队列（P3）：降神 / 间合 / 海神挪宝 / 炸裂 / 未来 / 天梯 / 神境。

只验证「队列层面的行为」：
  · 按卡序（主战 → 协战）挂询问
  · 跳过一笔 → 挂下一笔；都跳完 → pre_draw_pending 变 False（不会无限等）
  · 技能真的用掉 → close_pre_draw_ask 关掉询问
  · 换一巡（活牌山变了）→ 重新可以问

用法：cd server; python test_pre_draw_ask.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")

from game import Game  # noqa: E402
from tiles import parse_hand  # noqa: E402
import test_game as tg  # noqa: E402

PASS = FAIL = 0


def check(name, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  got={got!r} want={want!r}")


H0 = parse_hand("123m456p789s") + ["1p", "1p", "5m", "5m"]
H1 = parse_hand("234m567p678s") + ["2p", "2p", "9m"]
H2 = parse_hand("2m5m8m2p5p8p2s5s8s") + ["2z", "3z", "4z", "5m"]
H3 = parse_hand("3m6m9m3p6p9p3s6s9s") + ["1z", "2z", "3z", "5z"]


def setup(tag, seed, grant, oracle_on=True, haishin_on=True):
    db = tg.fresh_db(tag)
    rid, _m, _u = tg.new_round(db, seed=seed)
    tg.set_hand(db, rid, 0, H0)
    tg.set_hand(db, rid, 1, H1)
    tg.set_hand(db, rid, 2, H2)
    tg.set_hand(db, rid, 3, H3)
    g = Game(db, rid)
    g.round_phase = "play"
    g.granted = grant
    g.haishin_on = bool(haishin_on)
    if oracle_on:
        g.oracle = {0: {"on": True, "suit": "m"}}
    g.phase, g.turn = "draw", 0
    g.save_flags()
    return db, rid


def main() -> int:
    print("=" * 70)
    print(" 天才麻将少女 · 摸牌前询问队列（P3）")
    print("=" * 70)

    print("\n① 按卡序挂：降神(7) 先于 海神挪宝(12)")
    db, rid = setup("pda1", 601, {0: {7, 12}, 1: {1}})
    g = Game(db, rid)
    check("能挂出询问", g.open_pre_draw_ask(0), True)
    check("第一笔是降神", str((g.cur_ask or {}).get("kind", "")), "oracle")
    check("state 里能看到", len(g.state_for(0).get("pending_asks") or []), 1)
    check("别家看不到", len(g.state_for(1).get("pending_asks") or []), 0)
    r1 = g.pre_draw_skip(0)
    check("跳过降神", str(r1.get("kind", "")), "oracle")

    g = Game(db, rid)
    check("接着挂海神挪宝", g.open_pre_draw_ask(0), True)
    check("第二笔是挪宝", str((g.cur_ask or {}).get("kind", "")), "haishin_swap")
    g.pre_draw_skip(0)

    g = Game(db, rid)
    check("都问完了 → pending False", g.pre_draw_pending(0), False)
    check("也挂不出新询问", g.open_pre_draw_ask(0), False)
    ev = g.advance()
    check("能正常摸牌", ev.get("event") == "draw", True)
    g = Game(db, rid)
    check("摸到牌了", g.drawn_tile(0) is not None, True)

    print("\n② 换一巡 → 可以重新问（降神一直开着）")
    g.phase, g.turn = "draw", 0
    g.save_flags()
    g = Game(db, rid)
    check("新一巡重新挂降神", g.open_pre_draw_ask(0), True)
    check("种类还是降神", str((g.cur_ask or {}).get("kind", "")), "oracle")

    print("\n③ 技能用掉 → 询问自动关掉")
    db, rid = setup("pda2", 602, {0: {7}, 1: {1}}, haishin_on=False)
    g = Game(db, rid)
    g.open_pre_draw_ask(0)
    check("挂着降神", str((g.cur_ask or {}).get("kind", "")), "oracle")
    check("close_pre_draw_ask 关得掉", g.close_pre_draw_ask(0), True)
    check("关掉后队列空", g.asks, [])
    check("关掉后不再挡摸牌", g.prompt_state(), None)
    check("关掉别人不生效", g.close_pre_draw_ask(1), False)

    print("\n④ include_haishin=False：只算「其它技能」")
    db, rid = setup("pda3", 603, {0: {12}, 1: {1}})
    g = Game(db, rid)
    check("算上海神 → 待问", g.pre_draw_pending(0), True)
    check("不算海神 → 不问", g.pre_draw_pending(0, include_haishin=False), False)

    print("\n⑤ 立直后手牌锁定：不再问会改手牌的技能")
    db, rid = setup("pda4", 604, {0: {12}, 1: {1}})
    with db.tx():
        db.conn.execute("INSERT INTO round_riichi(round_id, seat) VALUES(?,0)", (rid,))
    g = Game(db, rid)
    check("海神挪宝不问（立直锁手牌）", g.pre_draw_pending(0), False)

    print("\n" + "=" * 70)
    print(f" 通过 {PASS} 项，失败 {FAIL} 项")
    print("=" * 70)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
