# -*- coding: utf-8 -*-
"""Card43 S2【免疫】自测（拦截树版）。

跑法：cd N:\\apps\\tianma\\server; python test_card43s2.py
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
import skills                                      # noqa: E402
import test_card30 as t30                          # noqa: E402
import test_game as tg                             # noqa: E402
from tiles import parse_hand                       # noqa: E402

PASS = FAIL = 0


def check(name, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  got {got!r} want {want!r}")


def setup(tag, granted=None):
    """0 号位持 40（透视，指向性技能），1 号位持 43（免疫）。"""
    db, rid = t30.setup(tag, card=40)
    tg.set_hand(db, rid, 0, parse_hand("123m456m789m234p5z3s"), drawn="3s")
    tg.set_hand(db, rid, 1, parse_hand("123m456p789s5z5z1z2z"), drawn=None)
    with db.tx():
        for tb in ("round_dora", "round_discards", "round_melds", "round_riichi"):
            db.conn.execute("DELETE FROM %s WHERE round_id=?" % tb, (rid,))
    g = Game(db, rid)
    g.granted = granted if granted is not None else {0: {40}, 1: {43}}
    g.round_phase = "play"
    g.phase = "discard"
    g.turn = 0
    g.deal_wait = set()
    g.deal_used = set()
    g.save_flags()
    return db, rid


def asks(db, rid, seat):
    return Game(db, rid).state_for(seat).get("asks") or []


def main() -> int:
    print("=" * 78)
    print(" Card43 S2【免疫】（拦截树版）")
    print("=" * 78)

    print("\n① 注册 / 可用次数")
    check("名字", skills.info(43, 2).get("name"), "免疫")
    db0, rid0 = setup("c43s2z")
    check("默认 2 次", Game(db0, rid0).c43s2_left(1), 2)

    print("\n② 别人发动指向我的技能 → 我的询问里有 imm")
    db, rid = setup("c43s2a")
    out = api_cli.handle({"op": "c40s1_apply", "seat": 0, "target": 1,
                          "round_id": rid}, db_path=db.path)
    check("被拦下（need_kangpo）", bool(out.get("need_kangpo", False)), True)
    mine = asks(db, rid, 1)
    check("我有一条询问", len(mine), 1)
    check("能用免疫", "imm" in (mine[0].get("kinds") or []), True) if mine else None
    g = Game(db, rid)
    check("技能还没生效", g.c40_show, {})
    check("0 号位看不到我的询问", asks(db, rid, 0), [])

    print("\n③ 发动免疫 → 这次作废 + 以后免疫")
    aid = int(mine[0]["id"]) if mine else -1
    out2 = api_cli.handle({"op": "act_answer", "seat": 1, "aid": aid, "kind": "imm",
                           "round_id": rid}, db_path=db.path)
    check("回答成功", bool(out2.get("ok", False)), True)
    g2 = Game(db, rid)
    check("记下免疫", g2.c43s2_immune(1, 40, 1), True)
    check("次数 2→1", g2.c43s2_left(1), 1)
    check("透视没生效", g2.c40_show, {})

    print("\n④ 再发一次 → 直接作废（不用再问）")
    out3 = api_cli.handle({"op": "c40s1_apply", "seat": 0, "target": 1,
                           "round_id": rid}, db_path=db.path)
    check("被拒", bool(out3.get("ok", True)), False)
    check("说明是免疫", "免疫" in str(out3.get("error", "")), True)
    check("没有再挂询问", asks(db, rid, 1), [])

    print("\n⑤ 跳过 = 照常发动，次数不减")
    db2, rid2 = setup("c43s2b")
    api_cli.handle({"op": "c40s1_apply", "seat": 0, "target": 1, "round_id": rid2},
                   db_path=db2.path)
    m2 = asks(db2, rid2, 1)
    out4 = api_cli.handle({"op": "act_answer", "seat": 1, "aid": int(m2[0]["id"]),
                           "kind": "pass", "round_id": rid2}, db_path=db2.path)
    check("放行成功", bool(out4.get("ok", False)), True)
    g3 = Game(db2, rid2)
    check("透视生效了", 1 in (g3.c40_show.get(0) or set()), True)
    check("次数没减", g3.c43s2_left(1), 2)
    check("没记免疫", g3.c43s2_immune(1, 40, 1), False)

    print("\n⑥ 不指向我的技能不问")
    db3, rid3 = setup("c43s2c")
    out5 = api_cli.handle({"op": "c40s1_apply", "seat": 0, "target": 2,
                           "round_id": rid3}, db_path=db3.path)
    check("没挂询问", asks(db3, rid3, 1), [])
    check("直接生效", bool(out5.get("ok", False)), True)

    print("\n⑦ 不持 43 卡 → 不问")
    db4, rid4 = setup("c43s2d", granted={0: {40}})
    api_cli.handle({"op": "c40s1_apply", "seat": 0, "target": 1, "round_id": rid4},
                   db_path=db4.path)
    check("没挂询问", asks(db4, rid4, 1), [])

    print("\n⑧ 同时持 31+43：同一个面板里三种招")
    db5, rid5 = setup("c43s2e", granted={0: {40}, 1: {31, 43}})
    api_cli.handle({"op": "c40s1_apply", "seat": 0, "target": 1, "round_id": rid5},
                   db_path=db5.path)
    m5 = asks(db5, rid5, 1)
    check("kinds = 封堵/阻止/免疫", sorted(m5[0].get("kinds") or []),
          ["block", "imm", "stop"]) if m5 else None

    print("\n⑨ 目标解析（牌河 seq / 手牌实体 / 兜底表）")
    db6, rid6 = setup("c43s2f", granted={0: {27}, 2: {43}})
    with db6.tx():
        db6.conn.execute(
            "INSERT INTO round_discards(round_id, seq, seat, wall_seq, tile,"
            " is_tsumogiri, is_riichi_tile, face_down, called)"
            " VALUES(?,501,2,901,'5p',1,0,0,0)", (rid6,))
    g6 = Game(db6, rid6)
    check("牌河 seq 501 → 2 号位", g6.c43s2_targets("c27s1_swap", {"seq": 501}), {2})
    check("river 列表", g6.c43s2_targets("c33s1_swap", {"river": [501]}), {2})
    check("算不准的按其他三家", g6.c43s2_targets("swap", {}), {0, 1, 2, 3})
    check("没有目标就不问", g6.c43s2_targets("c46s1_apply", {"tile": "1m"}), set())

    print("\n" + "=" * 78)
    print(f" 合计：{PASS + FAIL} 断言，{FAIL} 失败")
    print("=" * 78)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
