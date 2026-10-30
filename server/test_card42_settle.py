# -*- coding: utf-8 -*-
"""Card42 S2【夺目】：结算前必须问我（用户 2026-10-28 报的 bug）。

修前：只能自己在切牌前点图标指定庄家 → 一不留神错过时机，结算照真庄家算。
修后：`_finish()` 进来先挂起 → `state.c42.ask` → 客户端弹面板 →
      `op=c42s2_answer{target}` 选人（或 -1 跳过）→ 才真正结算；15 秒不答按真庄家。

跑法：cd N:\\apps\\tianma\\server; python test_card42_settle.py
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
import api_cli                                      # noqa: E402
import test_card30 as t30                           # noqa: E402
import test_game as tg                              # noqa: E402
from tiles import parse_hand                        # noqa: E402

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


def setup_play(tag, card=42):
    db, rid = t30.setup(tag, card=int(card))
    tg.set_hand(db, rid, 0, parse_hand(H14), drawn="5s")
    with db.tx():
        for tb in ("round_dora", "round_discards", "round_melds", "round_riichi"):
            db.conn.execute("DELETE FROM %s WHERE round_id=?" % tb, (rid,))
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
    g.save_flags()
    return db, rid


def main() -> int:
    print("=" * 78)
    print(" Card42 S2【夺目】· 结算前询问")
    print("=" * 78)

    print("\n① 对照组：没有 42 号卡 → 和牌直接结算，不问")
    db0, rid0 = setup_play("c42st_a", card=6)
    Game(db0, rid0).act(0, "tsumo")
    r0 = Game(db0, rid0).result or {}
    pts0 = int(r0.get("points", 0))
    check("对照组已结算", bool(r0), True)
    check("没人被问", Game(db0, rid0).c42s2_settle, None)

    print("\n② 持 42：点自摸 → **先挂起**、state 里出现询问")
    db, rid = setup_play("c42st_b")
    g = Game(db, rid)
    ev = g.act(0, "tsumo")
    g2 = Game(db, rid)
    check("还没结算", g2.result, None)
    check("挂着询问", bool(g2.c42s2_settle), True)
    check("询问的赢家是 0", int((g2.c42s2_settle or {}).get("winner", -1)), 0)
    ask = g2.state_for(0).get("c42", {}).get("ask") or {}
    check("state 里给了 ask", bool(ask), True)
    check("ask.dealer 是真庄家 0", int(ask.get("dealer", -1)), 0)
    check("别人看不到这一问", Game(db, rid).state_for(1).get("c42", {}).get("ask"), None)
    check("这一问算「有人在等回答」",
          (Game(db, rid).prompt_state() or {}).get("kind"), "c42s2")
    check("挂起时 phase = c42s2_ask（AI 不会替赢家再打一张）",
          str(Game(db, rid).phase), "c42s2_ask")
    check("挂起时不能打牌", Game(db, rid).legal_actions(0), [])
    check("自摸事件先回来了（客户端据此播效果）", str((ev or {}).get("event", "")), "tsumo")
    check("技能还没消耗", Game(db, rid).skill_used(0, 42, 2), False)

    print("\n③ 回答「把 1 号位当庄家」→ 才真正结算，点数按闲家算")
    out = api_cli.handle({"op": "c42s2_answer", "seat": 0, "target": 1,
                          "round_id": rid}, db_path=db.path)
    check("回包 ok", bool(out.get("ok", False)), True)
    g3 = Game(db, rid)
    check("结算了", bool(g3.result), True)
    check("指定落库", int(g3.c42s2_target), 1)
    check("真庄家没变", int(g3.dealer), 0)
    check("赢得比对照组少（按闲家算）", int((g3.result or {}).get("points", 0)) < pts0, True)
    check("技能消耗了", g3.skill_used(0, 42, 2), True)
    check("询问清掉", g3.c42s2_settle, None)

    print("\n④ 选择「跳过」→ 按真庄家结算，而且不会再问")
    db2, rid2 = setup_play("c42st_c")
    Game(db2, rid2).act(0, "tsumo")
    check("先挂起", bool(Game(db2, rid2).c42s2_settle), True)
    api_cli.handle({"op": "c42s2_answer", "seat": 0, "target": -1, "round_id": rid2},
                   db_path=db2.path)
    g4 = Game(db2, rid2)
    check("已结算", bool(g4.result), True)
    check("没指定（真庄家）", int(g4.c42s2_target), -1)
    check("和对照组一样", int((g4.result or {}).get("points", 0)), pts0)
    check("记了「问过」", 0 in g4.c42s2_asked, True)
    check("算点数用真庄家", int(g4.c42s2_dealer()), 0)

    print("\n⑤ 切牌前自己点图标指定过 → 结算时不再问（不重复打扰）")
    db3, rid3 = setup_play("c42st_d")
    g5 = Game(db3, rid3)
    g5.c42s2_arm(0, 1)
    Game(db3, rid3).act(0, "tsumo")
    g6 = Game(db3, rid3)
    check("没挂询问", g6.c42s2_settle, None)
    check("直接结算", bool(g6.result), True)
    check("按 1 号位当庄家", int(g6.c42s2_dealer()), 1)

    print("\n⑥ 一直不答**不会**自动结算（用户口径：面板上有「跳过」，不替玩家做决定）")
    db4, rid4 = setup_play("c42st_e")
    Game(db4, rid4).act(0, "tsumo")
    g7 = Game(db4, rid4)
    pend = dict(g7.c42s2_settle or {})
    pend["ts"] = 1.0                       # 假装已经过去很久
    g7.c42s2_settle = pend
    g7.save_flags()
    check("超时不自动结算", Game(db4, rid4).c42s2_timeout(), False)
    g8 = Game(db4, rid4)
    check("还挂着询问", bool(g8.c42s2_settle), True)
    check("还没结算", g8.result, None)
    # 玩家点「跳过」= op target=-1
    api_cli.handle({"op": "c42s2_answer", "seat": 0, "target": -1, "round_id": rid4},
                   db_path=db4.path)
    g9 = Game(db4, rid4)
    check("点跳过之后才结算", bool(g9.result), True)
    check("按真庄家", int(g9.c42s2_target), -1)

    print("\n⑦ op 登记")
    check("OPS 里有 c42s2_answer", "c42s2_answer" in api_cli.OPS, True)

    print("\n" + "=" * 78)
    print(f" 通过 {PASS} / 失败 {FAIL}")
    print("=" * 78)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
