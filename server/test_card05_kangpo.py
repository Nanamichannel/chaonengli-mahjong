# -*- coding: utf-8 -*-
"""Card05 三段 · 看破时机

段1 压牌：永不可看破
段2 换牌：选完牌点「确认」那一下问；被看破 = 换牌不发生、机会不吞
段3 额外摸切：摸牌后点技能那一下问；被看破 = 不扣点、不挂标记
"""
from __future__ import annotations

import io
import json
import os
import sys

sys.path.insert(0, r'N:\apps\tianma\server')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import api_cli  # noqa: E402
from game import Game  # noqa: E402
from tiles import parse_hand  # noqa: E402
import test_game as tg  # noqa: E402


def _flush_asks(dbp, rid):
    """并行询问：答完自己那条，把其余「没人在操作」的座位放行（测试里全是 AI）。"""
    try:
        from db import DB as _DB
        for _ in range(12):
            g = Game(_DB(dbp), int(rid))
            pend = [n for n in g.acts.values() if n.get("state") == "asking"]
            if not pend:
                return
            n = pend[0]
            seat = -1
            for a in (n.get("asks") or []):
                if not a.get("answer"):
                    seat = int(a.get("seat", -1))
                    break
            if seat < 0:
                break
            api_cli.handle({"op": "kangpo_answer", "seat": seat, "use": False,
                            "round_id": int(rid)}, dbp)
    except Exception:
        return


OK = 0
BAD = 0


def check(cond, msg):
    global OK, BAD
    if cond:
        OK += 1
    else:
        BAD += 1
        print("  [FAIL]", msg)


def dbpath(tag):
    return os.path.join(r'N:\apps\tianma\server', 'data', f'_test_{tag}.db')


def call(path, req):
    return api_cli.handle(req, path)


def set_orders(db, orders):
    body = {"seats": [{"ready": False, "hand": [], "picks": [], "order": list(o)}
                      for o in orders], "phase": "playing"}
    with db.tx():
        db.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('lobby_state', ?)",
                        (json.dumps(body),))


def add_river(db, rid, seq, seat, tile, wseq):
    with db.tx():
        db.conn.execute(
            "INSERT INTO round_discards(round_id, seq, seat, wall_seq, tile,"
            " is_tsumogiri, is_riichi_tile, face_down, called)"
            " VALUES(?,?,?,?,?,1,0,0,0)", (rid, seq, seat, wseq, tile))


def setup(tag, seed):
    """0 号位持策略（有 1 点 + 一次换牌机会），1 号位持看破。"""
    db = tg.fresh_db(tag)
    set_orders(db, [[5, 1, 1, 1, 1], [17, 17, 17, 17, 17],
                    [1, 2, 3, 4, 5], [6, 7, 8, 9, 10]])
    rid, _m, _u = tg.new_round(db, seed=seed)
    tg.set_hand(db, rid, 0, parse_hand("123m456p789s1z2z3z") + ["5m"], drawn="5m")
    tg.set_hand(db, rid, 1, parse_hand("1m4m7m1p4p7p1s4s7s1z2z3z"))
    tg.set_hand(db, rid, 2, parse_hand("2m5m8m2p5p8p2s5s8s2z3z4z"))
    tg.set_hand(db, rid, 3, parse_hand("3m6m9m3p6p9p3s6s9s1z2z3z"))
    add_river(db, rid, 500, 2, "9p", 9500)
    g = Game(db, rid)
    g.granted = {0: {5}, 1: {17}}
    g.round_phase = "play"
    g.turn, g.phase = 0, "discard"
    g.card05_counter[0] = 1
    g.card05_offer[0] = {"by": 2, "reason": "test"}
    g.save_flags()
    return db, rid


def main():
    # ① 结构：三段各归各位
    print("① 闸门归属")
    check(api_cli._gate_pair("card05_swap", {}) == (5, 1), "段2 在闸门里 (5,1)")
    check(api_cli._gate_pair("card05_extra", {}) == (5, 1), "段3 在闸门里 (5,1)")
    check(api_cli._gate_pair("card05_nuki", {}) == (5, 2), "拔北在闸门里 (5,2)")
    check(api_cli._gate_pair("card05_hide", {}) is None, "段1 永不可看破")
    check(api_cli._gate_pair("card05_cancel", {}) is None, "取消不问")

    # ② 段2：确认 → 先问看破 → 被看破 → 不换牌、机会还在
    print("\n② 段2 换牌被看破")
    db, rid = setup("c05g2", 401)
    before = list(Game(db, rid).hand(0))
    r = call(dbpath("c05g2"), {"op": "card05_swap", "seat": 0, "hand": "1m",
                               "kind": "river", "river": 500, "stack": 0,
                               "half": "top", "round_id": rid})
    check(bool(r.get("need_kangpo")), f"换牌前要先问看破，实际 {r}")
    g = Game(db, rid)
    check(list(g.hand(0)) == before, "被拦下时不能真的换牌")
    check(0 in g.card05_offer, "被拦下时机会还在")
    call(dbpath("c05g2"), {"op": "kangpo_answer", "seat": 1, "use": True, "round_id": rid})
    _flush_asks(dbpath("c05g2"), rid)
    g2 = Game(db, rid)
    check(list(g2.hand(0)) == before, "被看破 → 换牌不发生")
    check(0 in g2.card05_offer, f"被看破 → 换牌机会不吞，实际 {g2.card05_offer}")
    check(g2.card05_counter.get(0) == 1, "换牌被看破不动点数")
    check(0 in g2.no_win, "被看破的那家本局不能和")

    # ③ 段2 放行 → 真的换
    print("\n③ 段2 放行后真的换")
    db, rid = setup("c05g2b", 402)
    r = call(dbpath("c05g2b"), {"op": "card05_swap", "seat": 0, "hand": "1m",
                                "kind": "river", "river": 500, "stack": 0,
                                "half": "top", "round_id": rid})
    check(bool(r.get("need_kangpo")), "先问看破")
    out = call(dbpath("c05g2b"), {"op": "kangpo_answer", "seat": 1, "use": False,
                                  "round_id": rid})
    _flush_asks(dbpath("c05g2b"), rid)
    g = Game(db, rid)
    check((out.get("card05_swap") or {}).get("got") == "9p",
          f"放行后要真的换到 9p，实际 {out.get('card05_swap')}")
    check("9p" in g.hand(0), "手里要有 9p")
    check(0 not in g.card05_offer, "换完机会用掉")

    # ④ 段3：点技能 → 先问看破 → 被看破 → 不扣点、不挂标记
    print("\n④ 段3 额外摸切被看破")
    db, rid = setup("c05g3", 403)
    r = call(dbpath("c05g3"), {"op": "card05_extra", "seat": 0, "round_id": rid})
    check(bool(r.get("need_kangpo")), f"额外摸切要先问看破，实际 {r}")
    g = Game(db, rid)
    check(g.card05_counter.get(0) == 1, "被拦下时点数不动")
    check(0 not in g.card05_extra, "被拦下时不能挂标记")
    call(dbpath("c05g3"), {"op": "kangpo_answer", "seat": 1, "use": True, "round_id": rid})
    _flush_asks(dbpath("c05g3"), rid)
    g2 = Game(db, rid)
    check(g2.card05_counter.get(0) == 1, "被看破 → 不扣点")
    check(0 not in g2.card05_extra, "被看破 → 不挂标记")
    check(g2.phase, "discard")

    # ⑤ 段3 放行 → 扣点 + 挂标记
    print("\n⑤ 段3 放行后真的挂上")
    db, rid = setup("c05g3b", 404)
    call(dbpath("c05g3b"), {"op": "card05_extra", "seat": 0, "round_id": rid})
    call(dbpath("c05g3b"), {"op": "kangpo_answer", "seat": 1, "use": False, "round_id": rid})
    _flush_asks(dbpath("c05g3b"), rid)
    g = Game(db, rid)
    check(g.card05_counter.get(0) == 0, "放行后扣掉 1 点")
    check(0 in g.card05_extra, "放行后要挂上额外摸切")

    print("\n" + "=" * 60)
    print("通过 %d / 失败 %d" % (OK, BAD))
    print("=" * 60)
    return 0 if BAD == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
