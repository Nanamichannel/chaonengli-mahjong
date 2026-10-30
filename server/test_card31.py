# -*- coding: utf-8 -*-
"""Card31 S1【封堵】+ S2【阻止】自测。

跑法：cd N:\\apps\\tianma\\server; python test_card31.py
"""
from __future__ import annotations

import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from game import Game, RuleError  # noqa: E402
import skills  # noqa: E402
import test_card30 as t30  # noqa: E402

PASS = FAIL = 0


def check(name, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  got {got!r} want {want!r}")


def sticks(db, rid) -> int:
    return int(db._one("SELECT IFNULL(riichi_sticks,0) FROM rounds WHERE round_id=?",
                       (rid,)) or 0)


def mk(tag):
    db, rid = t30.setup(tag, card=31, mains=[31, 5, 7, 8])
    g = Game(db, rid)
    g.human_seats = {0, 1, 2, 3}
    return db, rid, g


def main() -> int:
    print("=" * 78)
    print(" Card31 S1【封堵】+ S2【阻止】")
    print("=" * 78)

    print("\n① 注册")
    check("S1 名字", skills.info(31, 1).get("name"), "封堵")
    check("S2 名字", skills.info(31, 2).get("name"), "阻止")

    print("\n② 封堵：与看破同时机，效果=作废，价格 2000 起每次翻倍")
    db, rid, g = mk("c31a")
    check("挂起了询问", g.kangpo_gate(1, 27, 1, op="c27s1_swap", payload={}), True)
    ask = g.kangpo_ask or {}
    check("问到 0 号位", int(ask.get("owner", -1)), 0)
    kinds0 = [o["kinds"] for o in (ask.get("options") or []) if int(o["seat"]) == 0][0]
    check("能出 封堵", "block" in kinds0, True)
    check("能出 阻止（调包是 draw 时机）", "stop" in kinds0, True)
    check("这次价格 2000", g.c31_block_price(0), 2000)
    s0 = int(g.scores()[0])
    st0 = sticks(db, rid)
    res = g.kangpo_answer(0, True, "block")
    check("封堵作废了那次发动", bool(res.get("used", False)), True)
    check("价格记在返回里", int(res.get("price", 0)), 2000)
    g2 = Game(db, rid)
    check("扣掉了 2000 点", int(g2.scores()[0]), s0 - 2000)
    check("场供 +2 根", sticks(db, rid), st0 + 2)
    check("对方被标成作废", "1:27:1" in g2.poked, True)

    g3 = Game(db, rid)
    g3.human_seats = {0, 1, 2, 3}
    check("下一次价格翻倍 4000", g3.c31_block_price(0), 4000)
    check("换个技能再问", g3.kangpo_gate(1, 29, 1, op="c29s1_chi", payload={}), True)
    s1 = int(g3.scores()[0])
    st1 = sticks(db, rid)
    r2 = g3.kangpo_answer(0, True, "block")
    check("第二次收 4000", int(r2.get("price", 0)), 4000)
    g4 = Game(db, rid)
    check("再扣 4000", int(g4.scores()[0]), s1 - 4000)
    check("场供再 +4 根", sticks(db, rid), st1 + 4)
    check("第三次会要 8000", g4.c31_block_price(0), 8000)

    print("\n③ 阻止：只挡主动技能，不算他的一次性次数")
    db2, rid2, h = mk("c31b")
    check("挂起了询问", h.kangpo_gate(1, 27, 1, op="c27s1_swap", payload={}), True)
    res3 = h.kangpo_answer(0, True, "stop")
    check("用了阻止", String_kind(res3), "stop")
    check("没收钱", int(res3.get("price", 0)), 0)
    h2 = Game(db2, rid2)
    check("对方没有被标 poked", "1:27:1" in h2.poked, False)
    check("对方没被禁和", 1 in h2.no_win, False)
    check("记账：对 1 号位用过了", 1 in (h2.c31s2_used.get(0) or set()), True)
    check("对同一个玩家第二次不给阻止", "stop" in h2.kangpo_kinds(0, 1, 29, 1), False)
    check("对别的玩家还能阻止", "stop" in h2.kangpo_kinds(0, 2, 29, 1), True)
    check("结算型技能不给阻止", "stop" in h2.kangpo_kinds(0, 2, 28, 2), False)
    check("结算型技能照样能给封堵", "block" in h2.kangpo_kinds(0, 2, 28, 2), True)

    print("\n④ 放行：什么都不改")
    db3, rid3, k = mk("c31c")
    check("挂起", k.kangpo_gate(1, 27, 1, op="c27s1_swap", payload={}), True)
    k.kangpo_answer(0, False)
    k2 = Game(db3, rid3)
    check("放行不算用掉", 0 in (k2.c31s2_used or {}), False)
    check("没作废对方", "1:27:1" in k2.poked, False)
    check("没花钱", int(k2.scores()[0]), 35000)

    print("\n⑤ 防作弊：这次用不了的招不能硬发")
    db4, rid4, m = mk("c31d")
    check("结算型技能也能挂起", m.kangpo_gate(1, 28, 2, op="x", payload={}), True)
    err = ""
    try:
        m.kangpo_answer(0, True, "stop")     # 28-2 是结算技能，阻止用不了
    except RuleError as e:
        err = str(e)
    check("阻止用在结算技能上被拒", err != "", True)
    check("拒绝之后桌子不会卡住", (Game(db4, rid4).kangpo_pending is None), True)

    print("\n⑥ 拦截之后【魔术】/【快手】还能不能用（用户报的那个坑）")
    import json  # noqa: E402
    from tiles import parse_hand  # noqa: E402
    import test_game as tg  # noqa: E402

    db6 = tg.fresh_db("c31e")
    rid6, _m, _u = tg.new_round(db6, seed=71)
    with db6.tx():
        db6.conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES('lobby_state', ?)",
            (json.dumps({"seats": [{"order": [11, 1, 2, 3, 4]},
                                   {"order": [31, 2, 3, 4, 5]},
                                   {"order": [6, 2, 3, 4, 5]},
                                   {"order": [7, 2, 3, 4, 5]}]},
                        ensure_ascii=False),))
    tg.set_hand(db6, rid6, 0, parse_hand("123m456p789s11z22z"), drawn="nan")
    h6 = Game(db6, rid6)
    h6.human_seats = {0, 1, 2, 3}
    h6.phase, h6.turn = "discard", 0
    h6.dora_revealed = 1
    h6.save_flags()
    check("魔术本来能用", Game(db6, rid6).card11_can(0), True)

    # 阻止：作废这一次，但**什么都不写** → 他还挂得上、还能再发动
    check("挂起询问", h6.kangpo_gate(0, 11, 1, op="card11_swap",
                                   payload={"hand": "1m", "idx": 0}), True)
    h6.kangpo_answer(1, True, "stop")
    h7 = Game(db6, rid6)
    h7.human_seats = {0, 1, 2, 3}
    check("阻止之后魔术还能用", h7.card11_can(0), True)
    check("阻止没有剔除这张卡", 11 in (h7.state_for(0).get("poked_cards") or []), False)
    check("阻止没写 poked", "0:11" in h7.poked, False)
    check("阻止没消耗他的次数", h7.skill_used(0, 11, 1), False)

    # 封堵：等于看破（整张卡本小局剔除）
    check("再挂一次询问", h7.kangpo_gate(0, 11, 2, op="card11s2_swap",
                                     payload={"river": -1}), True)
    h7.kangpo_answer(1, True, "block")
    h8 = Game(db6, rid6)
    check("封堵之后魔术不能用了（整张卡被剔除）", h8.card11_can(0), False)
    check("state 里能看出「被剔除」", 11 in (h8.state_for(0).get("poked_cards") or []), True)
    check("封堵仍然没消耗他的次数", h8.skill_used(0, 11, 1), False)

    print("\n" + "=" * 78)
    print(f" 通过 {PASS} / 失败 {FAIL}")
    print("=" * 78)
    return 0 if FAIL == 0 else 1


def String_kind(res) -> str:
    return str(res.get("kind", ""))


if __name__ == "__main__":
    sys.exit(main())
