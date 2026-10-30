# -*- coding: utf-8 -*-
"""拦截树自测：并行多询问 / 嵌套反制 / 先答先落 / 免疫 / 超时。

跑法：cd N:\\apps\\tianma\\server; python test_act_tree.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from game import Game                              # noqa: E402
import api_cli                                     # noqa: E402
import test_card30 as t30                          # noqa: E402
import test_game as tg                             # noqa: E402
from tiles import parse_hand                       # noqa: E402

PASS = FAIL = 0
HANDS = ["123m456m789m234p5z3s", "123m456p789s1z2z3z4z",
         "123m456p789s5z5z1z2z", "123m456p789s6z6z3z4z"]


def check(name, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  got {got!r} want {want!r}")


def setup(tag, grants):
    db, rid = t30.setup(tag, card=40)
    for s in range(4):
        tg.set_hand(db, rid, s, parse_hand(HANDS[s]))
    with db.tx():
        for tb in ("round_dora", "round_discards", "round_melds", "round_riichi"):
            db.conn.execute("DELETE FROM %s WHERE round_id=?" % tb, (rid,))
    g = Game(db, rid)
    g.granted = grants
    g.round_phase = "play"
    g.phase = "discard"
    g.turn = 0
    g.deal_wait = set()
    g.deal_used = set()
    g.save_flags()
    return db, rid


def asks(db, rid, seat):
    return Game(db, rid).state_for(seat).get("asks") or []


def fire(db, rid, target=3):
    return api_cli.handle({"op": "c40s1_apply", "seat": 0, "target": target,
                           "round_id": rid}, db_path=db.path)


def main() -> int:
    print("=" * 78)
    print(" 拦截树（Activation）")
    print("=" * 78)

    print("\n① 一次发动 → 两个座位各一个窗口（并行询问）")
    db, rid = setup("at1", {0: {40}, 1: {17}, 2: {31}, 3: {}})
    out = fire(db, rid, 3)
    check("发动被挂起", bool(out.get("need_kangpo", False)), True)
    b = asks(db, rid, 1)
    c = asks(db, rid, 2)
    check("B 有 1 条", len(b), 1)
    check("C 有 1 条", len(c), 1)
    check("两条问的是同一笔（同一个 id）", (b[0]["id"], c[0]["id"]) if b and c else 0,
          (b[0]["id"], b[0]["id"]) if b else -1)
    check("B 只有看破", b[0]["kinds"] if b else [], ["sight"])
    check("C 有封堵/阻止", sorted(c[0]["kinds"]) if c else [], ["block", "stop"])
    check("技能还没执行", Game(db, rid).c40_show, {})

    print("\n② C 先落封堵 → 根节点等着（B 还能反制这一手封堵）")
    api_cli.handle({"op": "act_answer", "seat": 2, "aid": int(c[0]["id"]),
                    "kind": "block", "round_id": rid}, db_path=db.path)
    g2 = Game(db, rid)
    check("B 手上只剩一条询问", len(asks(db, rid, 1)), 1)
    b2 = asks(db, rid, 1)
    check("B 改成被问「C 的封堵」", [a["kind"] for a in b2], ["block"])
    check("封堵还没付钱（等反制结果）", g2.c31_block_used(2), 0)

    print("\n③ B 看破 C 的封堵 → C 失效、A 的透视恢复生效")
    api_cli.handle({"op": "act_answer", "seat": 1, "aid": int(b2[0]["id"]),
                    "kind": "sight", "round_id": rid}, db_path=db.path)
    g3 = Game(db, rid)
    check("透视生效了（看的是 3 号位）", 3 in (g3.c40_show.get(0) or set()), True)
    check("C 的封堵被剔除（poked 31）", "2:31" in g3.poked, True)
    check("C 本局不能和", 2 in g3.no_win, True)
    check("树清空", g3.acts, {})

    print("\n④ 反过来：没人反制 C 的封堵 → C 生效、A 作废")
    db2, rid2 = setup("at2", {0: {40}, 1: {17}, 2: {31}, 3: {}})
    fire(db2, rid2, 3)
    c2 = asks(db2, rid2, 2)
    api_cli.handle({"op": "act_answer", "seat": 2, "aid": int(c2[0]["id"]),
                    "kind": "block", "round_id": rid2}, db_path=db2.path)
    b2 = asks(db2, rid2, 1)
    api_cli.handle({"op": "act_answer", "seat": 1, "aid": int(b2[0]["id"]),
                    "kind": "pass", "round_id": rid2}, db_path=db2.path)
    g4 = Game(db2, rid2)
    check("A 的透视没生效", g4.c40_show, {})
    check("A 被剔除", "0:40" in g4.poked, True)
    check("C 付了封堵钱", g4.c31_block_used(2), 1)
    check("树清空", g4.acts, {})

    print("\n⑤ 先答先落：同一笔两个封堵者，先点的那个生效")
    db3, rid3 = setup("at3", {0: {40}, 1: {31}, 2: {31}, 3: {}})
    fire(db3, rid3, 3)
    a1 = asks(db3, rid3, 1)
    a2 = asks(db3, rid3, 2)
    api_cli.handle({"op": "act_answer", "seat": 2, "aid": int(a2[0]["id"]),
                    "kind": "block", "round_id": rid3}, db_path=db3.path)
    g5 = Game(db3, rid3)
    left = asks(db3, rid3, 1)
    check("2 号位先落 → 1 号位的窗口没了", left, [])
    check("只有 2 号位付钱", (g5.c31_block_used(2), g5.c31_block_used(1)), (1, 0))

    print("\n⑥ 免疫走同一棵树：目标里有免疫者 → 整次作废")
    db4, rid4 = setup("at4", {0: {40}, 1: {43}, 3: {}})
    fire(db4, rid4, 1)
    m = asks(db4, rid4, 1)
    check("我这条能用免疫", "imm" in (m[0]["kinds"] if m else []), True)
    api_cli.handle({"op": "act_answer", "seat": 1, "aid": int(m[0]["id"]),
                    "kind": "imm", "round_id": rid4}, db_path=db4.path)
    g6 = Game(db4, rid4)
    check("透视没生效", g6.c40_show, {})
    check("免疫记上了", g6.c43s2_immune(1, 40, 1), True)
    check("次数 2→1", g6.c43s2_left(1), 1)

    print("\n⑦ 超时 = 放行，不卡局")
    db5, rid5 = setup("at5", {0: {40}, 1: {17}, 3: {}})
    fire(db5, rid5, 3)
    g7 = Game(db5, rid5)
    for n in g7.acts.values():
        n["deadline"] = 1.0
    g7.save_flags()
    g7 = Game(db5, rid5)
    check("检测到超时", g7.act_timeout(), True)
    check("询问清空", g7.act_pending(), False)
    g7.act_take_ready()
    g8 = Game(db5, rid5)
    check("树也空了", g8.acts, {})

    print("\n⑧ A 发动 → B 封堵 → C 放行 B 的封堵 → C 仍能复制 A 的技能")
    db6, rid6 = setup("at6", {0: {40}, 1: {31}, 2: {17, 41}, 3: {}})
    fire(db6, rid6, 3)
    poolC = (Game(db6, rid6).state_for(2).get("c41") or {}).get("ask") or []
    check("C 第一个窗口就能复制 A 的技能",
          [int(x.get("card", 0)) for x in poolC], [40])
    b6 = asks(db6, rid6, 1)
    api_cli.handle({"op": "act_answer", "seat": 1, "aid": int(b6[0]["id"]),
                    "kind": "block", "round_id": rid6}, db_path=db6.path)
    c6 = asks(db6, rid6, 2)
    check("C 被问「要不要反制 B 的封堵」", [x["kind"] for x in c6], ["block"])
    api_cli.handle({"op": "act_answer", "seat": 2, "aid": int(c6[0]["id"]),
                    "kind": "pass", "round_id": rid6}, db_path=db6.path)
    g9 = Game(db6, rid6)
    check("A 的技能被堵住了", g9.c40_show, {})
    poolC2 = (g9.state_for(2).get("c41") or {}).get("ask") or []
    check("复制池还在（还能复制 A 的技能）",
          [int(x.get("card", 0)) for x in poolC2], [40])
    api_cli.handle({"op": "c41_copy", "seat": 2, "card": 40, "skill": 1,
                    "round_id": rid6}, db_path=db6.path)
    g10 = Game(db6, rid6)
    check("复制成功", (g10.c41_copies.get(2) or [{}])[0].get("card"), 40)

    print("\n⑨ 封堵拦【看破】：看破作废、A 的技能照常生效、封堵者付钱、看破者的卡不废")
    db7, rid7 = setup("at7", {0: {40}, 1: {17}, 2: {31}, 3: {}})
    fire(db7, rid7, 3)
    b7 = asks(db7, rid7, 1)
    api_cli.handle({"op": "act_answer", "seat": 1, "aid": int(b7[0]["id"]),
                    "kind": "sight", "round_id": rid7}, db_path=db7.path)
    c7 = Game(db7, rid7).act_ask_view(2)
    check("C 被问「B 的看破」", [x["kind"] for x in c7], ["sight"])
    check("这条能给封堵", "block" in (c7[0]["kinds"] if c7 else []), True)
    check("这条不给阻止", "stop" in (c7[0]["kinds"] if c7 else []), False)
    check("这条不给免疫", "imm" in (c7[0]["kinds"] if c7 else []), False)
    api_cli.handle({"op": "act_answer", "seat": 2, "aid": int(c7[0]["id"]),
                    "kind": "block", "round_id": rid7}, db_path=db7.path)
    g7 = Game(db7, rid7)
    check("A 的透视照常生效（看的是 3 号位）", 3 in (g7.c40_show.get(0) or set()), True)
    check("A 的卡没被剔除", "0:40" in g7.poked, False)
    check("C 付了封堵钱", g7.c31_block_used(2), 1)
    check("B 的看破卡没被废", "1:17" in g7.poked, False)
    check("B 没被禁和", 1 in g7.no_win, False)
    check("树清空", g7.acts, {})

    print("\n⑩ 反制只一层：C 封堵掉 B 的看破之后，不会再回头问 B")
    check("B 没有新窗口", Game(db7, rid7).act_ask_view(1), [])
    check("C 也没有新窗口", Game(db7, rid7).act_ask_view(2), [])
    check("没有挂起的节点", Game(db7, rid7).act_pending(), False)

    print("\n" + "=" * 78)
    print(f" 合计：{PASS + FAIL} 断言，{FAIL} 失败")
    print("=" * 78)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
