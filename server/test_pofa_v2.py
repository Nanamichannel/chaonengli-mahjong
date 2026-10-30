# -*- coding: utf-8 -*-
"""破发 v2（自动询问 / 2 张吃碰 / 3 张杠 / 副露后暗置打出）+ 先负最先立直"""
from __future__ import annotations

import io
import json
import os
import sys
import time

sys.path.insert(0, r'N:\apps\tianma\server')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from game import Game, RuleError  # noqa: E402
import test_game as tg  # noqa: E402

OK = 0
BAD = 0
H_ME = ["1m", "2m", "3m", "4m", "5m", "6m", "7m", "8m", "9m",
        "2p", "2p", "4s", "6s", "9p"]


def check(cond, msg):
    global OK, BAD
    if cond:
        OK += 1
    else:
        BAD += 1
        print("  [FAIL]", msg)


def set_orders(db, orders):
    body = {"seats": [{"ready": False, "hand": [], "picks": [], "order": list(o)}
                      for o in orders], "phase": "playing"}
    with db.tx():
        db.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('lobby_state', ?)",
                        (json.dumps(body, ensure_ascii=False),))


def add_discard(db, rid, seat, seq, tile, face_down=0):
    with db.tx():
        db.conn.execute(
            "INSERT INTO round_discards(round_id, seq, seat, wall_seq, tile, called,"
            " is_riichi_tile, face_down) VALUES(?,?,?,?,?,0,0,?)",
            (rid, seq, seat, 9000 + seq, tile, face_down))


def main():
    # ── ① 破发：立直窗口 → 自动询问（state.pofa_stage）────────────
    db = tg.fresh_db("po2")
    set_orders(db, [[13, 1, 2, 3, 4], [1, 2, 3, 5, 6], [1, 2, 3, 5, 7], [1, 2, 3, 5, 8]])
    rid, _m, _u = tg.new_round(db, seed=181)
    tg.set_hand(db, rid, 0, H_ME)
    add_discard(db, rid, 1, 101, "5s")
    add_discard(db, rid, 2, 102, "7p", face_down=1)
    g = Game(db, rid)
    g.granted = {0: {13}}
    g.pofa_window = {"declarer": 1, "seq": 101}
    g.pofa_ask = {"declarer": 1, "waiting": [0], "ts": time.time()}
    g.phase, g.turn = "discard", 1
    g.save_flags()
    g = Game(db, rid)
    st = g.state_for(0)
    check(st.get("pofa_stage") == "ask", f"别家立直后应该自动问破发，实际 {st.get('pofa_stage')}")
    check(st.get("pofa_can") is True, f"应该能破发，实际 {st.get('pofa_can')}")
    check(sorted(st.get("pofa_seqs", [])) == [101],
          f"只能选明牌，实际 {st.get('pofa_seqs')}")

    # 无效副露
    try:
        g.pofa_activate(0, 101, ["2p", "9p"])
        check("无效副露应该被拒", False)
    except RuleError as e:
        check("无效副露应该被拒", "无效副露" in str(e))

    # 2 张吃（5s + 4s6s）
    r = g.pofa_activate(0, 101, ["4s", "6s"])
    check(r.get("kind") == "chi", f"应该成顺子，实际 {r}")
    g2 = Game(db, rid)
    check(g2.turn == 0, f"副露后回合应该跳到我，实际 {g2.turn}")
    check(g2.state_for(0).get("pofa_stage") == "discard",
          f"接下来应该让我暗置打一张，实际 {g2.state_for(0).get('pofa_stage')}")
    check(len(g2.melds(0)) == 1, "副露应该挂上")

    # 暗置打出
    rd = g2.pofa_discard(0, "9p")
    check(rd.get("face_down") is True, "打出应该是暗置")
    g3 = Game(db, rid)
    check("9p" not in g3.discards_for_furiten(0), "暗置牌不该造成振听")
    check(g3.pofa_discard_pending is None, "打完之后应该清掉")
    check(g3.phase == "discard", f"打完该进入打牌阶段，实际 {g3.phase}")

    # ── ② 3 张杠 ─────────────────────────────────────────
    db2 = tg.fresh_db("po3")
    set_orders(db2, [[13, 1, 2, 3, 4], [1, 2, 3, 5, 6], [1, 2, 3, 5, 7], [1, 2, 3, 5, 8]])
    rid2, _m2, _u2 = tg.new_round(db2, seed=182)
    tg.set_hand(db2, rid2, 0, ["5s", "5s", "5s", "1m", "2m", "3m", "4m", "5m",
                               "6m", "7m", "8m", "9m", "2p", "9p"])
    add_discard(db2, rid2, 1, 201, "5s")
    g4 = Game(db2, rid2)
    g4.granted = {0: {13}}
    g4.pofa_window = {"declarer": 1, "seq": 201}
    g4.pofa_ask = {"declarer": 1, "waiting": [0], "ts": time.time()}
    g4.phase, g4.turn = "discard", 1
    g4.save_flags()
    g4 = Game(db2, rid2)
    r = g4.pofa_activate(0, 201, ["5s", "5s", "5s"])
    check(r.get("kind") == "minkan", f"3 张同牌应该成杠，实际 {r}")

    # ── ②b 窗口存活：别人摸牌不清，自己摸牌才过期 ──────────
    db2b = tg.fresh_db("po4")
    set_orders(db2b, [[13, 1, 2, 3, 4], [1, 2, 3, 5, 6], [1, 2, 3, 5, 7], [1, 2, 3, 5, 8]])
    rid2b, _a, _b = tg.new_round(db2b, seed=184)
    g7 = Game(db2b, rid2b)
    g7.phase, g7.turn = "draw", 2
    g7.pofa_window = {"declarer": 1, "seq": 3}
    g7.pofa_ask = {"declarer": 1, "waiting": [0], "ts": time.time()}
    g7.save_flags()
    g7 = Game(db2b, rid2b)
    check(g7.pofa_can(0) is True, "有窗口时应该能破发")
    g7.advance()                                   # 2 号位摸牌（别人）
    g7 = Game(db2b, rid2b)
    check(g7.pofa_window is not None, "别人摸牌不该清破发窗口")
    check(g7.pofa_can(0) is True, "别人摸牌后仍应该能破发")
    check(g7.state_for(0).get("pofa_stage") == "ask", "state 里应该还在问")
    g7.phase, g7.turn = "draw", 0
    g7.save_flags()
    g7 = Game(db2b, rid2b)
    g7.advance()                                   # 我自己摸牌
    g7 = Game(db2b, rid2b)
    check(g7.pofa_window is None, "自己摸牌后窗口应该过期")
    check(g7.pofa_can(0) is False, "自己摸牌后不能再破发")

    # ── ③ 先负：最先立直者 ─────────────────────────────────
    db3 = tg.fresh_db("xf1")
    rid3, _m3, _u3 = tg.new_round(db3, seed=183)
    with db3.tx():
        db3.conn.execute(
            "INSERT INTO round_riichi(round_id, seat, declared_seq, ippatsu) VALUES(?,?,?,1)",
            (rid3, 2, 30))
        db3.conn.execute(
            "INSERT INTO round_riichi(round_id, seat, declared_seq, ippatsu) VALUES(?,?,?,1)",
            (rid3, 1, 12))
    g5 = Game(db3, rid3)
    check(g5.first_riichi_seat(0) == 1,
          f"应该按宣言牌顺序取最先立直的（1 号位），实际 {g5.first_riichi_seat(0)}")

    # 先负结算中 → 破发不能改写
    g5.xianfu_pending = {"seat": 0, "declarer": 1}
    g5.pofa_window = {"declarer": 2, "seq": 1}
    check(g5.pofa_can(0) is False, "先负 pending 时破发必须被禁")

    print(f"\n通过 {OK} / 失败 {BAD}")
    return 1 if BAD else 0


if __name__ == "__main__":
    sys.exit(main())
