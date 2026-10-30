# -*- coding: utf-8 -*-
"""Card42 S1【理论战】+ S2【夺目】自测。

跑法：cd N:\\apps\\tianma\\server; python test_card42.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from game import Game, RuleError                  # noqa: E402
import api_cli                                     # noqa: E402
import skills                                      # noqa: E402
import test_card30 as t30                          # noqa: E402
import test_game as tg                             # noqa: E402
from tiles import parse_hand                       # noqa: E402

PASS = FAIL = 0
H14 = "123m456m789m234p5s5s"


def check(name, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  got {got!r} want {want!r}")


def setup_deal(tag, card=42):
    """配牌阶段（t30.setup 的默认形态）。"""
    db, rid = t30.setup(tag, card=int(card))
    tg.set_hand(db, rid, 0, parse_hand("123m456m789m234p5z3s"), drawn="3s")
    g = Game(db, rid)
    g.granted = {0: {int(card)}}
    g.save_flags()
    return db, rid


def setup_play(tag, card=42, confident=False):
    db, rid = t30.setup(tag, card=int(card))
    tg.set_hand(db, rid, 0, parse_hand(H14), drawn="5s")
    with db.tx():
        db.conn.execute("DELETE FROM round_dora WHERE round_id=?", (rid,))
        db.conn.execute("DELETE FROM round_discards WHERE round_id=?", (rid,))
        db.conn.execute("DELETE FROM round_melds WHERE round_id=?", (rid,))
        db.conn.execute("DELETE FROM round_riichi WHERE round_id=?", (rid,))
        db.conn.execute(
            "INSERT INTO round_melds(round_id,meld_id,seat,kind,called_tile,from_seat,"
            "tiles_json,rot_index,seqs_json) VALUES(?,0,3,'pon','1z',0,?,0,'[]')",
            (rid, '["1z","1z","1z"]'))
    g = Game(db, rid)
    g.granted = {0: {int(card)}}
    g.round_phase = "play"
    g.phase = "discard"
    g.turn = 0
    g.deal_wait = set()
    g.deal_used = set()
    if confident:
        g.confident = {1}
    g.save_flags()
    return db, rid


def main() -> int:
    print("=" * 78)
    print(" Card42 S1【理论战】+ S2【夺目】")
    print("=" * 78)

    print("\n① 注册 / 时机")
    check("S1 名字", skills.info(42, 1).get("name"), "理论战")
    check("S2 名字", skills.info(42, 2).get("name"), "夺目")
    check("S1 时机 = 配牌", skills.timing(42, 1), "deal")
    check("S2 时机 = 切牌", skills.timing(42, 2), "discard")

    print("\n② 理论战：庄家配牌时能发动，已发动的配牌技能作废")
    db, rid = setup_deal("c42a")
    g = Game(db, rid)
    check("庄家是我", int(g.dealer), 0)
    check("能发动", g.c42s1_can(0), True)
    g.confident = {1}
    g.c28s1_on = {2}
    g.save_flags()
    g = Game(db, rid)
    r = g.c42s1_apply(0)
    check("开启", bool(r.get("on")), True)
    g2 = Game(db, rid)
    check("落库", g2.c42s1_on, True)
    check("自信被作废", g2.confident, set())
    check("满贯被作废", g2.c28s1_on, set())
    check("配牌窗口收干净", g2.phase != "deal_skill", True)

    print("\n③ 理论战之后：谁都不能发动技能（连看破都不问）")
    check("看破闸门直接关", g2.kangpo_gate(1, 37, 2, op="c37s2_apply", payload={}), False)
    out = api_cli.handle({"op": "c39s1_apply", "seat": 1, "round_id": rid},
                         db_path=db.path)
    check("op 被拒", bool(out.get("ok", True)), False)
    check("错误说明是理论战", "理论战" in str(out.get("error", "")), True)
    check("非技能 op 照常", bool(api_cli.handle(
        {"op": "state", "seat": 0, "round_id": rid}, db_path=db.path).get("ok")), True)

    print("\n③b 理论战：其他家还在想配牌技能时也不能卡死")
    db2, rid2 = setup_deal("c42lock")
    gb = Game(db2, rid2)
    gb.phase = "deal_skill"
    gb.round_phase = "play"
    gb.turn = 0
    gb.deal_wait = {0, 1, 2, 3}          # 其他三家也还挂着「发动 / 跳过」
    gb.deal_used = set()
    gb.c25s2_pending = 2
    gb.save_flags()
    gb = Game(db2, rid2)
    rb = gb.c42s1_apply(0)
    check("其他三家被一起作废", rb.get("voided"), [1, 2, 3])
    gb2 = Game(db2, rid2)
    check("deal_wait 清空（不清就是永远等）", gb2.deal_wait, set())
    check("离开配牌阶段 → 庄家切牌", gb2.phase, "discard")
    check("轮到自己", (-1 if gb2.turn is None else int(gb2.turn)), 0)
    check("「宝牌的集合」二段询问也清掉", int(gb2.c25s2_pending), -1)
    check("state 里不再挂着配牌技能",
          (gb2.state_for(1).get("deal_skill") or {}).get("pending"), [])

    print("\n④ 夺目：指定结算用的庄家（只影响点数）")
    db2, rid2 = setup_play("c42b", card=6)          # 对照组：没这张卡
    Game(db2, rid2).act(0, "tsumo")
    res0 = (Game(db2, rid2).result or {})
    pts0 = int(res0.get("points", 0))
    check("对照组赢家是亲家（真庄家）", int(res0.get("winner")), 0)

    db3, rid3 = setup_play("c42c")
    g3 = Game(db3, rid3)
    check("能发动夺目", g3.c42s2_can(0), True)
    g3.c42s2_arm(0, 1)                              # 指定 1 号位当庄家
    g4 = Game(db3, rid3)
    check("落库", int(g4.c42s2_target), 1)
    check("真庄家没变", int(g4.dealer), 0)
    check("算点数用的庄家是 1", int(g4.c42s2_dealer()), 1)
    g4.act(0, "tsumo")
    res3 = (Game(db3, rid3).result or {})
    check("赢得比对照组少（按闲家算）", int(res3.get("points", 0)) < pts0, True)
    check("结算完真庄家还是 0", int(Game(db3, rid3).dealer), 0)

    print("\n⑤ 指定自己为庄家 → 按亲家算")
    db4, rid4 = setup_play("c42d")
    g5 = Game(db4, rid4)
    g5.c42s2_arm(0, 0)
    g5 = Game(db4, rid4)
    g5.act(0, "tsumo")
    res5 = (Game(db4, rid4).result or {})
    check("和对照组一样（本来就是亲家）", int(res5.get("points", 0)), pts0)

    print("\n⑥ op 层登记")
    check("OPS 里有 c42s1_apply", "c42s1_apply" in api_cli.OPS, True)
    check("OPS 里有 c42s2_arm", "c42s2_arm" in api_cli.OPS, True)
    check("登记 (42,1)", api_cli._SKILL_OP_PAIRS.get("c42s1_apply"), (42, 1))
    check("登记 (42,2)", api_cli._SKILL_OP_PAIRS.get("c42s2_arm"), (42, 2))

    print("\n" + "=" * 78)
    print(f" 合计：{PASS + FAIL} 断言，{FAIL} 失败")
    print("=" * 78)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
