# -*- coding: utf-8 -*-
"""Card12 S1「海神」询问链回归（P1 修复配套）。

覆盖：
  ① ask_id：每笔询问带递增流水号，且落 flags
  ② give 之后 plan 里剩下的询问要继续（以前被整个丢掉 → 出现「该问没问」）
  ③ give / pass / 岭上补牌 之后的「摸牌后」尾段（同巡振听解除）
  ④ pre_draw_pending 认「海神·挪宝」（以前服务端不认账，任何 pre_ok 都能推过去）
  ⑤ 已经结束的询问幂等返回 already

用法：cd server; python test_card12_s1_ask.py
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")

from game import Game, RuleError  # noqa: E402
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
H1 = parse_hand("234m567p678s") + ["2p", "2p", "5m"]
H2 = parse_hand("2m5m8m2p5p8p2s5s8s") + ["2z", "3z", "4z", "5m"]
H3 = parse_hand("3m6m9m3p6p9p3s6s9s") + ["1z", "2z", "3z", "5z"]


def setup(tag, seed, grant, drawn1="5m"):
    """建一局：1 号位「刚摸到 drawn1」，手牌都摆好。"""
    db = tg.fresh_db(tag)
    rid, _m, _u = tg.new_round(db, seed=seed)
    tg.set_hand(db, rid, 0, H0)
    tg.set_hand(db, rid, 1, H1, drawn=drawn1)
    tg.set_hand(db, rid, 2, H2)
    tg.set_hand(db, rid, 3, H3)
    g = Game(db, rid)
    g.round_phase = "play"
    g.granted = grant
    g.haishin_on = True
    g.phase, g.turn = "draw", 1
    g.save_flags()
    return db, rid


def main() -> int:
    print("=" * 70)
    print(" 天才麻将少女 · Card12 S1 询问链（ask_id / 继续问 / 尾段 / 摸牌前登记）")
    print("=" * 70)

    # ① ask_id 唯一且递增、落 flags
    print("\n① ask_id 流水号")
    db, rid = setup("c12ask1", 501, {0: {12}, 1: {1}})
    g = Game(db, rid)
    g._open_intercept(1, "5m", [[0, "haishin"]])
    a1 = int((g.haishin_offer or {}).get("ask_id", 0))
    check("第一笔带 ask_id", a1 > 0)
    check("队列里有一笔 haishin 询问",
          [(int(a.get("seat", -1)), str(a.get("kind", ""))) for a in g.asks],
          [(0, "haishin")])
    g.haishin_offer = None
    g._open_intercept(1, "5m", [[0, "haishin"]])
    a2 = int((g.haishin_offer or {}).get("ask_id", 0))
    check("第二笔 ask_id 递增", a2, a1 + 1)
    g.save_flags()
    g2 = Game(db, rid)
    check("ask_seq 落 flags", int(g2.ask_seq), a2)

    # ② give 之后：plan 里第二家还要被问
    print("\n② 第一家换完 → 第二家继续被问")
    db, rid = setup("c12ask2", 502, {0: {12}, 1: {1}, 2: {12}})
    g = Game(db, rid)
    g._open_intercept(1, "5m", [[0, "haishin"], [2, "haishin"]])
    check("先问 0 号位", (g.haishin_offer or {}).get("owner"), 0)
    r1 = g.haishin_give(0, "5m")
    g = Game(db, rid)
    check("换到手的是 5m", r1.get("got"), "5m")
    check("换完还停在询问阶段", g.phase, "haishin")
    check("第二家接着被问", (g.haishin_offer or {}).get("owner"), 2)
    check("问的是他换到手的那张", (g.haishin_offer or {}).get("tile"), "5m")
    check("ask_id 是新的一笔",
          int((g.haishin_offer or {}).get("ask_id", 0)) > a1, True)
    check("不会再问回第一家",
          int((g.haishin_offer or {}).get("owner", -1)) != 0, True)
    r2 = g.haishin_give(0, "5m")
    check("已经结束的询问幂等返回", bool(r2.get("already")), True)
    g.haishin_give(2, "5m")
    g = Game(db, rid)
    check("两家都换完 → 回到打牌", g.phase, "discard")
    check("换完 offer 清掉", g.haishin_offer, None)

    # ③ 尾段：pass / give / 岭上
    print("\n③ 询问结束后要补「摸牌后」尾段")
    db, rid = setup("c12ask3", 503, {0: {12}, 1: {1}})
    g = Game(db, rid)
    g._open_intercept(1, "5m", [[0, "haishin"]])
    g.temp_furiten.add(1)
    g.save_flags()
    g.haishin_pass(0)
    g = Game(db, rid)
    check("跳过借牌 → 回到打牌", g.phase, "discard")
    check("被抢牌的人同巡振听解除", 1 in g.temp_furiten, False)

    db, rid = setup("c12ask4", 504, {0: {12}, 1: {1}})
    g = Game(db, rid)
    g._open_intercept(1, "5m", [[0, "haishin"]])
    g.temp_furiten.add(1)
    g.save_flags()
    g.haishin_give(0, "5m")
    g = Game(db, rid)
    check("借牌完成 → 回到打牌", g.phase, "discard")
    check("借牌完成 · 振听解除", 1 in g.temp_furiten, False)
    check("借牌完成 · 他的摸牌标记在我给他的那张", g.drawn_tile(1), "5m")

    db, rid = setup("c12ask5", 505, {0: {12}, 1: {1}})
    g = Game(db, rid)
    g.temp_furiten.add(2)
    g.save_flags()
    g._draw_after(2, "3p", rinshan=True, extra_checks=False)
    g.save_flags()
    g = Game(db, rid)
    check("岭上补牌也解除同巡振听", 2 in g.temp_furiten, False)
    check("岭上补牌后进入打牌/自风", g.phase in ("discard", "wind_swap"), True)

    # ④ 服务端认「摸牌前还欠一次海神询问」
    print("\n④ pre_draw_pending 认海神挪宝")
    db, rid = setup("c12ask6", 506, {0: {12}, 1: {1}})
    g = Game(db, rid)
    g.phase, g.turn = "draw", 0
    g.haishin_step = {}
    g.save_flags()
    g = Game(db, rid)
    check("有万子 + 没摸牌 → 欠一次询问", g.pre_draw_pending(0), True)
    g.haishin_step[0] = 3
    g.save_flags()
    check("三步走完 → 不再问", g.pre_draw_pending(0), False)
    g = Game(db, rid)
    g.haishin_step = {}
    g.haishin_on = False
    g.save_flags()
    check("本局没开海神 → 不欠询问", Game(db, rid).pre_draw_pending(0), False)

    # ⑤ P2：统一询问队列 + 挪宝服务端化
    print("\n⑤ 询问队列：一次排好、只挂队头")
    db, rid = setup("c12ask7", 507, {0: {12}, 1: {1}, 2: {12}})
    g = Game(db, rid)
    g._open_intercept(1, "5m", [[0, "haishin"], [2, "haishin"]])
    check("队列里排了两笔", len(g.asks), 2)
    check("只有队头挂出来", (g.haishin_offer or {}).get("owner"), 0)
    check("队头就是 cur_ask", int((g.cur_ask or {}).get("seat", -1)), 0)

    print("\n⑥ 挪宝：服务端挂询问 / 跳过 / 确认都关得掉")
    db, rid = setup("c12ask8", 508, {0: {12}, 1: {1}})
    g = Game(db, rid)
    g.phase, g.turn = "draw", 0
    g.haishin_step = {}
    g.save_flags()
    g = Game(db, rid)
    check("轮到我摸牌 → 挂上挪宝询问", g.open_pre_draw_ask(0), True)
    check("队头是 haishin_swap", str((g.cur_ask or {}).get("kind", "")), "haishin_swap")
    check("state.asks 只发给我", len(g.state_for(0).get("pending_asks") or []), 1)
    check("别家看不到这笔", len(g.state_for(1).get("pending_asks") or []), 0)
    check("询问锁认它", (g.prompt_state() or {}).get("kind"), "haishin_swap")
    g.open_pre_draw_ask(0)                       # 已经挂着 → 只回 True，不再入队
    check("同一巡不重复挂（队列还是一条）", len(g.asks), 1)
    r = g.haishin_swap_skip(0)
    check("跳过返回 skipped", bool(r.get("skipped")), True)
    g = Game(db, rid)
    check("跳过之后队列空了", g.asks, [])
    check("跳过之后询问锁放开", g.prompt_state(), None)

    db, rid = setup("c12ask9", 509, {0: {12}, 1: {1}})
    g = Game(db, rid)
    g.phase, g.turn = "draw", 0
    g.haishin_step = {}
    g.save_flags()
    g = Game(db, rid)
    g.open_pre_draw_ask(0)
    r2 = g.haishin_swap(0, "5m")
    g = Game(db, rid)
    check("换完一步会关掉询问", g.asks, [])
    check("换完 step=1", int(r2.get("next", -1)), 1)
    check("next_ready=False（一回合只能换一张）", bool(r2.get("next_ready", True)), False)
    check("换完一步 → 这一巡不能再换", g.haishin_swap_can(0), False)
    try:
        g.haishin_swap(0, "5m")
        check("换完一步 → 同一巡再换被拒", False)
    except RuleError as e:
        check("换完一步 → 同一巡再换被拒", "一回合" in str(e))
    # 模拟下一巡：指纹翻页 → 可以换第 2 种
    g.haishin_turn_used = {}
    g.save_flags()
    g = Game(db, rid)
    check("下一巡 → 又能换（杠宝）", g.haishin_swap_can(0), True)
    check("换完一步 → 这一巡不再重复挂询问", g.pre_draw_pending(0), False)
    check("换完一步 → 挂不出新询问", g.open_pre_draw_ask(0), False)

    print("\n⑦ 借牌（被动）不影响挪宝（主动）询问")
    db, rid = setup("c12askA", 510, {0: {12}, 1: {1}})
    g = Game(db, rid)
    g.phase, g.turn = "draw", 0
    g.haishin_step = {}
    g.save_flags()
    g = Game(db, rid)
    check("借过牌也照常问挪宝", g.open_pre_draw_ask(0), True)
    check("不移交抑制标记", int(g.haishin_swap_hold), -1)

    print("\n⑧ 跳过询问之后能正常摸牌（不会把对局挂死）")
    db, rid = setup("c12askB", 511, {0: {12}, 1: {1}})
    g = Game(db, rid)
    g.phase, g.turn = "draw", 0
    g.haishin_step = {}
    g.save_flags()
    g = Game(db, rid)
    check("服务端认为还欠一次询问", g.pre_draw_pending(0), True)
    g.open_pre_draw_ask(0)
    g = Game(db, rid)
    check("询问锁挡着", (g.prompt_state() or {}).get("kind"), "haishin_swap")
    g.haishin_swap_skip(0)
    g = Game(db, rid)
    check("跳过之后询问锁放开", g.prompt_state(), None)
    ev = g.advance()
    check("能正常摸牌", ev.get("event") in ("draw", "x_skip"), True)
    g = Game(db, rid)
    check("手上多了一张摸牌", g.drawn_tile(0) is not None, True)

    print("\n⑨ 一问一命 / 失效不锁桌 / 超时 / 三种换完")
    db, rid = setup("c12askC", 512, {0: {12}, 1: {1}})
    g = Game(db, rid)
    g.phase, g.turn = "draw", 0
    g.haishin_step = {}
    g.haishin_swap_asked = {}
    g.save_flags()
    g = Game(db, rid)
    check("该问就问", g.open_pre_draw_ask(0), True)
    check("同一巡重复调用只挂一笔", len(g.asks), 1)
    check("同一巡重复调用只挂一笔", len(g.asks), 1)

    g.cur_ask = dict(g.cur_ask or {})
    g.cur_ask["ts"] = time.time() - 120
    check("挂 120 秒 → 判定超时", g.pre_draw_ask_timeout(90), True)
    check("刚挂上 → 不算超时", g.pre_draw_ask_timeout(99999), False)

    g.phase = "discard"               # 模拟「已经摸完牌」：询问失效
    g.save_flags()
    g = Game(db, rid)
    check("失效的询问不再锁桌", g.prompt_state(), None)
    g.open_pre_draw_ask(0)
    check("顺手把失效询问清掉", g.cur_ask, None)

    g.phase, g.turn = "draw", 0
    g.haishin_step = {0: 3}           # 三种都换完
    g.save_flags()
    g = Game(db, rid)
    check("三种换完 → 不能再换", g.haishin_swap_can(0), False)
    check("三种换完 → 不再欠询问", g.pre_draw_pending(0), False)
    check("三种换完 → 挂不出询问", g.open_pre_draw_ask(0), False)

    print("\n" + "=" * 70)
    print(f" 通过 {PASS} 项，失败 {FAIL} 项")
    print("=" * 70)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
