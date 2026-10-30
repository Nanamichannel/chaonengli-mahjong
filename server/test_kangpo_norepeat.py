# -*- coding: utf-8 -*-
"""看破：放行后不许「再问一遍」自测

问题现场：技能结算 op 先被闸门拦下（need_kangpo）→ 看破持有者点「开始」（放行）
→ op_kangpo_answer 重放该 op → op 内 note_use() 又调 _maybe_ask_kangpo()
→ 客户端又弹一次遮罩，而且点下去报「现在没有要你看破的技能」。

修法：放行时把 (座位:卡:技能) 记进 kangpo_pass，note_use 那边消费掉就跳过。
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
import test_game as tg  # noqa: E402

OK = 0
BAD = 0
HAND = ["1m", "2m", "3m", "4m", "5m", "7m", "8m", "9m", "1s", "2s", "3s", "4s", "6s"]


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
                        (json.dumps(body, ensure_ascii=False),))


def setup(tag, seed):
    db = tg.fresh_db(tag)
    set_orders(db, [[21, 21, 21, 21, 3], [17, 17, 17, 17, 4],
                    [1, 2, 3, 4, 5], [6, 7, 8, 9, 10]])
    rid, _m, _u = tg.new_round(db, seed=seed)
    tg.set_hand(db, rid, 0, HAND)
    with db.tx():
        db.conn.execute(
            "INSERT INTO round_discards(round_id, seq, seat, wall_seq, tile, called,"
            " is_riichi_tile, face_down) VALUES(?,?,?,?,?,0,0,0)",
            (rid, 500, 1, 9500, "3p"))
    g = Game(db, rid)
    g.granted = {0: {21}, 1: {17}}
    g.gift = {0: 2}                      # 已经打过两张 → 馈赠2 可用
    g.phase, g.turn = "draw", 0          # 摸牌前
    g.save_flags()
    return db, rid


def main():
    # ① 放行 → 重放成功，且不再问一遍
    db, rid = setup("kpnr", 61)
    r = call(dbpath("kpnr"), {"op": "gift_swap", "seat": 0, "hand": "5m",
                              "river": 500, "round_id": rid})
    check(bool(r.get("need_kangpo")), f"馈赠应该先问看破，实际 {r}")
    g = Game(db, rid)
    check(g.kangpo_pass == set(), "还没回答，不该有「已放行」标记")
    check(int((g.kangpo_ask or {}).get("owner", -1)) == 1, "应该问 1 号位")

    r2 = call(dbpath("kpnr"), {"op": "kangpo_answer", "seat": 1, "use": False,
                               "round_id": rid})
    check(bool(r2.get("ok")), f"放行应该成功，实际 {r2.get('error')}")
    g = Game(db, rid)
    check(g.kangpo_ask is None, f"放行后不该再留询问，实际 {g.kangpo_ask}")
    check(g.kangpo_pending is None, f"放行后不该再有挂起的发动，实际 {g.kangpo_pending}")
    check(g.kangpo_pass == set(), f"放行标记应该被消费掉，实际 {g.kangpo_pass}")

    hand = [str(x) for x in g.hand(0)]
    check("3p" in hand, f"换进来的 3p 应该在手里，实际 {hand}")
    check("5m" not in hand, f"换出去的 5m 不该还在手里，实际 {hand}")
    st = {c["seat"]: c for c in g._char_states()}
    check(bool((st[0].get("main") or {}).get("open")) is True,
          f"发动过技能 → 21 号卡应该翻明，实际 {st[0].get('main')}")

    # ② 被看破 → op 不执行、卡也不翻明
    db2, rid2 = setup("kpnr2", 62)
    r = call(dbpath("kpnr2"), {"op": "gift_swap", "seat": 0, "hand": "5m",
                               "river": 500, "round_id": rid2})
    check(bool(r.get("need_kangpo")), "被看破那次也要先问")
    call(dbpath("kpnr2"), {"op": "kangpo_answer", "seat": 1, "use": True, "round_id": rid2})
    g = Game(db2, rid2)
    hand = [str(x) for x in g.hand(0)]
    check("5m" in hand and "3p" not in hand, f"被看破 → 换牌不该执行，实际 {hand}")
    check(g.kangpo_ask is None and g.kangpo_pending is None, "被看破后不该留询问")
    check(0 in g.no_win, "被看破的家本局不能和牌")
    st = {c["seat"]: c for c in g._char_states()}
    check(bool((st[0].get("main") or {}).get("open")) is False,
          f"被看破 → 卡不该翻明，实际 {st[0].get('main')}")

    print(f"\n通过 {OK} / 失败 {BAD}")
    return 1 if BAD else 0


if __name__ == "__main__":
    sys.exit(main())
