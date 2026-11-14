# -*- coding: utf-8 -*-
"""「别人摸到的牌被抢」这批询问：换牌成功后必须把队列里的询问关掉。

跑法：cd server; python test_intercept_close.py

背景（2026-11-08 实机 round 6）：
  2 号位开着【深山】，1 号位摸到 3m → 挂出询问，2 号位换了牌。
  换牌本身生效了，但 `shenshan_resolve()` 的「换牌」分支**没关队列里那笔询问**：
    · `cur_ask` / `asks` 永久残留 → `prompt_state()` 一直返回
      {"kind": "shenshan", "waiting": [2]} → **全桌锁死**（摸牌的人不能切牌）；
    · 而 `shenshan_offer` 已经是 None → 2 号位客户端一个提示都没有
      → 玩家说「看不到别人刚摸的牌」，其实是被卡住了。
  【宝牌的集合】(25-2) 的 `c25s2_swap` 是同一个形状。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")

from game import Game          # noqa: E402
import test_card30 as t30      # noqa: E402
import test_game as tg         # noqa: E402

PASS = 0
FAIL = 0

H13 = ["1m", "2m", "3m", "4p", "5p", "6p", "7s", "8s", "dong", "nan", "xi", "5s", "6s"]


def check(name, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  got={got!r} want={want!r}")


def base(tag, seat2_hand, mains=None):
    """1 号位刚摸到 3m；2 号位等牌。返回 (db, rid)。"""
    db, rid = t30.setup(tag, card=8, mains=mains or [8, 8, 19, 8])
    tg.set_hand(db, rid, 1, H13[:-1] + ["3m"], drawn="3m")
    tg.set_hand(db, rid, 2, list(seat2_hand))
    with db.tx():
        db.conn.execute("DELETE FROM round_dora WHERE round_id=?", (rid,))
        db.conn.execute("DELETE FROM round_discards WHERE round_id=?", (rid,))
        db.conn.execute("DELETE FROM round_riichi WHERE round_id=?", (rid,))
    return db, rid


def main() -> int:
    print("=" * 74)
    print(" 摸到的牌被抢：换完牌必须关掉队列里的询问（否则全桌锁死）")
    print("=" * 74)

    print("\n① 【深山】(19-1)：换牌之后询问要收干净")
    db, rid = base("intc1", H13)
    g = Game(db, rid)
    g.round_phase = "play"
    g.phase = "discard"
    g.turn = 1
    g.shenshan = {2}
    g.save_flags()

    g = Game(db, rid)
    plan = g._intercept_plan(1, "3m")
    check("深山进了询问队列", [2, "shenshan"] in plan, True)
    g._open_intercept(1, "3m", plan)
    check("挂出了询问", g.cur_ask is not None, True)
    check("2 号位看到 offer", int((g.state_for(2).get("shenshan_offer") or {}).get("from", -1)), 1)
    check("offer 里带着摸到的牌", str((g.state_for(2).get("shenshan_offer") or {}).get("tile", "")), "3m")
    check("别人看不到这份 offer", g.state_for(0).get("shenshan_offer"), None)
    check("全桌在等他", g.prompt_state(), {"kind": "shenshan", "waiting": [2]})

    r = g.shenshan_resolve(2, "1m")          # 2 号位用 1m 换 3m
    check("换到了", str(r.get("got", "")), "3m")
    check("给出去的是 1m", str(r.get("gave", "")), "1m")

    g2 = Game(db, rid)
    check("询问已关闭（cur_ask）", g2.cur_ask, None)
    check("询问队列已清空", list(g2.asks or []), [])
    check("offer 槽位已清空", g2.shenshan_offer, None)
    check("没人被锁住", g2.prompt_state(), None)
    check("回到切牌阶段", g2.phase, "discard")
    check("2 号位手里有 3m", g2.hand(2).count("3m") >= 1, True)
    check("1 号位手里有 1m", g2.hand(1).count("1m") >= 1, True)
    check("摸牌标记跟着换过去", g2.drawn_tile(1) is not None, True)

    print("\n② 【深山】跳过那一路也要收干净（回归）")
    db2, rid2 = base("intc2", H13)
    g3 = Game(db2, rid2)
    g3.round_phase = "play"
    g3.phase = "discard"
    g3.turn = 1
    g3.shenshan = {2}
    g3.save_flags()
    g3 = Game(db2, rid2)
    g3._open_intercept(1, "3m", g3._intercept_plan(1, "3m"))
    check("挂出了询问", g3.cur_ask is not None, True)
    r2 = g3.shenshan_resolve(2, "")
    check("跳过了", bool(r2.get("skipped")), True)
    g4 = Game(db2, rid2)
    check("跳过也把询问关掉", g4.cur_ask, None)
    check("跳过也不锁桌", g4.prompt_state(), None)

    print("\n③ 【宝牌的集合】(25-2)：换完宝牌之后同样要收干净")
    db3, rid3 = base("intc3", ["1p"] + H13[1:], mains=[8, 8, 25, 8])
    with db3.tx():
        db3.conn.execute(
            "INSERT INTO round_dora(round_id, kind, idx, indicator, dora, revealed)"
            " VALUES(?, 'dora', 0, '5m', '6m', 1)", (rid3,))
    tg.set_hand(db3, rid3, 1, H13[:-1] + ["6m"], drawn="6m")
    g5 = Game(db3, rid3)
    g5.round_phase = "play"
    g5.phase = "discard"
    g5.turn = 1
    g5.c25s2_on = {2}
    g5.save_flags()
    g5 = Game(db3, rid3)
    check("6m 是宝牌", g5._is_dora("6m"), True)
    plan3 = g5._intercept_plan(1, "6m")
    check("宝牌的集合进了询问队列", [2, "c25s2"] in plan3, True)
    g5._open_intercept(1, "6m", plan3)
    check("挂出了询问", g5.cur_ask is not None, True)
    r3 = g5.c25s2_swap(2, "1p")
    check("换到了宝牌", str(r3.get("got", "")), "6m")
    g6 = Game(db3, rid3)
    check("询问已关闭（cur_ask）", g6.cur_ask, None)
    check("询问队列已清空", list(g6.asks or []), [])
    check("没人被锁住", g6.prompt_state(), None)

    print("\n" + "=" * 74)
    print(f" 合计：{PASS} 断言，{FAIL} 失败")
    print("=" * 74)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
