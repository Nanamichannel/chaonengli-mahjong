# -*- coding: utf-8 -*-
"""Card44 S2【电报】自测。

跑法：cd N:\\apps\\tianma\\server; python test_card44s2.py
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
H0 = "123m456m789m234p5s5s"                        # 14 张（刚摸 5s）→ 自摸
HQ = "123m456m789m234m55m"                         # 清一色（够满贯）


def check(name, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  got {got!r} want {want!r}")


def setup(tag, hand=H0, drawn="5s", holders=(0,), c28=False, nongwu=False,
          card=44):
    db, rid = t30.setup(tag, card=int(card))
    tg.set_hand(db, rid, 0, parse_hand(hand), drawn=drawn)
    with db.tx():
        db.conn.execute("DELETE FROM round_dora WHERE round_id=?", (rid,))
        db.conn.execute("DELETE FROM round_discards WHERE round_id=?", (rid,))
        db.conn.execute("DELETE FROM round_melds WHERE round_id=?", (rid,))
        db.conn.execute("DELETE FROM round_riichi WHERE round_id=?", (rid,))
        # 上家先碰过 → all_closed() 为假，避免第一巡被判成「天和」役满
        db.conn.execute(
            "INSERT INTO round_melds(round_id,meld_id,seat,kind,called_tile,from_seat,"
            "tiles_json,rot_index,seqs_json) VALUES(?,0,3,'pon','1z',0,?,0,'[]')",
            (rid, '["1z","1z","1z"]'))
    g = Game(db, rid)
    g.granted = {int(s): {44, 23} for s in holders}
    g.round_phase = "play"
    g.phase = "discard"
    g.turn = 0
    g.deal_wait = set()
    g.deal_used = set()
    if c28:
        g.c28s1_on = {1}
    if nongwu:
        g.nongwu = {"by": 1, "left": 4}
    g.save_flags()
    return db, rid


def main() -> int:
    print("=" * 78)
    print(" Card44 S2【电报】")
    print("=" * 78)

    print("\n① 注册 / 时机")
    check("名字", skills.info(44, 2).get("name"), "电报")
    check("时机 = 摸牌", skills.timing(44, 2), "draw")

    print("\n② 摸牌后才能发动 / 本局一次")
    db0, rid0 = setup("c44s2z", holders=(), card=6)
    g0 = Game(db0, rid0)
    check("不持有 44 → 不能发动", g0.c44s2_can(0), False)

    db, rid = setup("c44s2a")
    g = Game(db, rid)
    check("摸牌后可以发动", g.c44s2_can(0), True)
    check("不是自己的回合 → 不能", g.c44s2_can(1), False)
    r = g.c44s2_arm(0)
    check("arm 返回开启", bool(r.get("on", False)), True)

    g2 = Game(db, rid)
    check("落库：本局常开", 0 in g2.c44s2_on, True)
    check("一次（不能重复发动）", g2.c44s2_can(0), False)

    print("\n③ 明牌：只有别人看得到，走 reveal_hands 那条链")
    st1 = g2.state_for(1)
    rev = [int(x.get("seat", -1)) for x in (st1.get("reveal_hands") or [])]
    check("1 号位看得到我的手牌", 0 in rev, True)
    tiles = []
    for x in (st1.get("reveal_hands") or []):
        if int(x.get("seat", -1)) == 0:
            tiles = [str(t) for t in (x.get("tiles") or [])]
    check("给的是我全部手牌（14 张）", len(tiles), 14)
    check("牌面就是我的手牌", sorted(tiles), sorted([str(t) for t in g2.hand(0)]))
    st0 = g2.state_for(0)
    check("自己这边不用重复翻",
          [int(x.get("seat", -1)) for x in (st0.get("reveal_hands") or [])], [])
    check("state 里标记本家已开启", bool(st0.get("c44s2_on", False)), True)

    print("\n④ 和牌 → 番数链按 30 符 1 番（对照组先看不发动时是多少）")
    dbC, ridC = setup("c44s2c")
    gC = Game(dbC, ridC)
    gC.act(0, "tsumo")
    resC = (Game(dbC, ridC).result or {})
    han_c, fu_c = int(resC.get("han", 0)), int(resC.get("fu", 0))
    check("对照组不是 1 番（证明电报确实压低了番数）", han_c > 1, True)
    print(f"         （对照组 {han_c} 番 {fu_c} 符 / {resC.get('points')} 点）")

    g3 = Game(db, rid)
    g3.act(0, "tsumo")
    res = (Game(db, rid).result or {})
    check("电报：1 番", int(res.get("han", 0)), 1)
    check("电报：30 符", int(res.get("fu", 0)), 30)
    check("明细里记了电报", bool(res.get("c44s2")), True)
    check("和牌结果有役名", any("电报" in str(y.get("name", ""))
                            for y in (res.get("yaku") or [])), True)
    check("结果里记了压之前的番数",
          int((res.get("c44s2") or {}).get("old_han", 0)), han_c)

    print("\n④b 番数钩子本身：把大牌压成 30 符 1 番（基本点 240）")
    dbU, ridU = setup("c44s2u")
    gU = Game(dbU, ridU)
    gU.c44s2_on = {0}                     # 当作已经发过电报
    resU = {"han": 6, "fu": 40, "yaku": [{"name": "清一色", "han": 6}],
            "fu_items": [("符", 40)]}
    envU = {"winner": 0, "loser": None, "result": "tsumo", "tsumo": True,
            "is_dealer": True}
    gU._settle_c44s2(resU, envU)
    check("番 = 1", int(resU.get("han", 0)), 1)
    check("符 = 30", int(resU.get("fu", 0)), 30)
    check("基本点 = 240", int((resU.get("pays") or {}).get("basic", 0)), 240)
    check("役种被换成电报一条",
          [y.get("name") for y in (resU.get("yaku") or [])],
          ["电报"])
    check("记号看破了原来的番数", int((resU.get("c44s2") or {}).get("old_han", 0)), 6)

    dbV, ridV = setup("c44s2v")
    gV = Game(dbV, ridV)
    resV = {"han": 6, "fu": 40, "yaku": []}
    gV._settle_c44s2(dict(resV), envU)          # 没发电报的那一家
    check("没发电报 → 钩子不动", int(resV.get("han", 0)), 6)

    print("\n⑤【自信】照样加成（番数双倍 = 2 番 30 符）")
    db5, rid5 = setup("c44s2d")
    g5 = Game(db5, rid5)
    g5.confident = {0}
    g5.c44s2_on = {0}
    g5.save_flags()
    g6 = Game(db5, rid5)
    g6.act(0, "tsumo")
    res5 = (Game(db5, rid5).result or {})
    check("自信：2 番", int(res5.get("han", 0)), 2)
    check("自信：仍是 30 符", int(res5.get("fu", 0)), 30)
    check("自信把番数抬到 2（明细在役种里）",
          any("自信" in str(y.get("name", ""))
              for y in (res5.get("yaku") or [])), True)

    print("\n⑥【暖气】照样乘在电报之后的得点上（零寒 → ×3）")
    res6 = dict(res)
    res6["pays"] = dict(res6.get("pays") or {})
    base_total = int(res6["pays"].get("total", 0))
    g7 = Game(db, rid)
    g7._cold_count = lambda s: 0            # 零寒 → 倍率 3
    env7 = {"winner": 0, "loser": None, "result": "tsumo", "tsumo": True,
            "is_dealer": True}
    g7._settle_heat(res6, env7)
    check("暖气倍率 3", int(res6.get("nuanqi", 0)), 3)
    check("得点 ×3", int(res6["pays"].get("total", 0)), base_total * 3)

    print("\n⑦【满贯】照样拦（30 符 1 番 的段位不够满贯）")
    dbA, ridA = setup("c44s2e", hand=HQ, drawn="5m", c28=True)
    gA = Game(dbA, ridA)
    check("对照组（没电报）满贯放行", gA._c28s1_allows(0, "5m", True), True)

    dbB, ridB = setup("c44s2f", hand=HQ, drawn="5m", c28=True)
    gB = Game(dbB, ridB)
    gB.c44s2_arm(0)
    gB2 = Game(dbB, ridB)
    check("电报之后满贯拦下", gB2._c28s1_allows(0, "5m", True), False)

    print("\n⑧【浓雾】照样拦（发电报不豁免）")
    dbN, ridN = setup("c44s2g", nongwu=True)
    gN = Game(dbN, ridN)
    gN.c44s2_arm(0)
    gN2 = Game(dbN, ridN)
    check("浓雾：自摸闸门不通", gN2._win_gate(0, None, True), False)
    check("浓雾：按钮也出不来", gN2._win_ok(0, "5s", True), False)

    print("\n⑨ 役满也压成 30 符 1 番（用户口径 2026-10-28）")
    gY = Game(db, rid)
    resY = {"han": 13, "fu": 30, "yakuman": 1, "yaku": []}
    envY = {"winner": 0, "loser": None, "result": "tsumo", "tsumo": True,
            "is_dealer": True}
    gY._settle_c44s2(resY, envY)
    check("番数压成 1", int(resY.get("han", 0)), 1)
    check("符压成 30", int(resY.get("fu", 0)), 30)
    check("役满被清掉", int(resY.get("yakuman", 0)), 0)
    check("记下原来的役满数", int((resY.get("c44s2") or {}).get("yakuman", 0)), 1)

    print("\n⑩ op 层登记（要走看破闸门，不能进免看破白名单）")
    check("OPS 里有 c44s2_arm", "c44s2_arm" in api_cli.OPS, True)
    check("卡号/技能号登记", api_cli._SKILL_OP_PAIRS.get("c44s2_arm"), (44, 2))
    check("要问看破", "c44s2_arm" in api_cli._NO_GATE_OPS, False)

    print("\n⑪ 电报生效 → 播报面板补「得点 X → Y（电报）」")
    db9, rid9 = t30.setup("c44s2bc", card=44)
    tg.set_hand(db9, rid9, 0, parse_hand("123m456m789m234p5s"))
    with db9.tx():
        db9.conn.execute("DELETE FROM round_dora WHERE round_id=?", (rid9,))
        db9.conn.execute("DELETE FROM round_discards WHERE round_id=?", (rid9,))
        db9.conn.execute("DELETE FROM round_melds WHERE round_id=?", (rid9,))
    g9 = Game(db9, rid9)
    g9.granted = {0: {44}}
    g9.round_phase = "play"
    g9.phase = "discard"
    g9.turn = 0
    g9.deal_wait = set()
    g9.deal_used = set()
    g9.c44s2_on.add(0)                      # 已经宣言明牌
    g9.save_flags()
    g9 = Game(db9, rid9)
    _res = g9._judge_win(0, "5s", tsumo=False)
    g9._finish(0, 1, "ron", _res)
    g10 = Game(db9, rid9)
    _r = g10.result or {}
    _b2 = g10.broadcast or {}
    check("电报生效（有得点）", int(_r.get("points", 0)) > 0, True)
    check("明细记了压番前得点", int(((_r.get("c44s2") or {}).get("old_total", 0))), 3900)
    check("播报写的是电报", "电报" in str(_b2.get("text", "")), True)
    check("播报里有得点变化箭头", "→" in str(_b2.get("text", "")), True)

    print("\n" + "=" * 78)
    print(f" 合计：{PASS + FAIL} 断言，{FAIL} 失败")
    print("=" * 78)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
