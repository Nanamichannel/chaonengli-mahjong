# -*- coding: utf-8 -*-
"""看破闸门：重复请求不许绕过 + AI 持有看破时直接放行

复现过的现场（修之前）：
  ① 间合攻 → need_kangpo（拦下，没换牌）
  ② 客户端又发一次同样的请求 → kangpo_gate 看到「已有挂起」就 return False
     = 不问直接执行 → 换牌真的发生了、看破被绕过
  ③ 客户端把 ① 的返回当成功（card09 是空字典）→ toast「换牌：用 X 换到 （空）」

修之后要保证：
  · 同一笔重复点：还是拦着（return True），手牌一动不动
  · 换一笔别的技能：直接 RuleError「稍等」，不许执行
  · 看破持有者是 AI（没有 lease）：不问，技能直接生效
  · 间合真的发动了 → 9 号卡翻明 + c09_next 轮换
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


def set_lease(db, seat):
    val = api_cli._lease_value(os.getpid())
    with db.tx():
        db.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES(?,?)",
                        (api_cli.LEASE_KEY % seat, val))


def clear_lease(db, seat):
    with db.tx():
        db.conn.execute("DELETE FROM meta WHERE key=?", (api_cli.LEASE_KEY % seat,))


def setup(tag, seed):
    db = tg.fresh_db(tag)
    # 0 号位主战卡 9（间合），1 号位主战卡 17（看破）
    set_orders(db, [[9, 9, 9, 9, 3], [17, 17, 17, 17, 4],
                    [1, 2, 3, 4, 5], [6, 7, 8, 9, 10]])
    rid, _m, _u = tg.new_round(db, seed=seed)
    tg.set_hand(db, rid, 0, HAND)
    with db.tx():
        db.conn.execute(
            "INSERT INTO round_discards(round_id, seq, seat, wall_seq, tile, called,"
            " is_riichi_tile, face_down) VALUES(?,?,?,?,?,0,0,0)",
            (rid, 500, 1, 9500, "3p"))
    g = Game(db, rid)
    g.granted = {0: {9}, 1: {17}}
    g.phase, g.turn = "draw", 0
    g.save_flags()
    return db, rid


def req09(rid, skill=2, hand="5m"):
    return {"op": "card09_swap", "seat": 0, "skill": skill, "hand": hand,
            "river": 500, "round_id": rid}


def main():
    # ── ① 两个座位都是人：第一次拦住 ─────────────────────────
    db, rid = setup("kpdup", 81)
    set_lease(db, 0)
    set_lease(db, 1)
    r = call(dbpath("kpdup"), req09(rid))
    check(bool(r.get("need_kangpo")), f"第一次应该先问看破，实际 {r.get('need_kangpo')}")
    check(not r.get("card09"), f"拦住的时候不该有 card09 结果，实际 {r.get('card09')}")
    g = Game(db, rid)
    check("5m" in g.hand(0) and "3p" not in g.hand(0), f"拦住时不该换牌，实际 {g.hand(0)}")
    check(g.c09_next == {}, f"拦住时不该写 c09_next，实际 {g.c09_next}")

    # ── ② 同一笔再点一次：还是拦着，绝不执行 ─────────────────
    r = call(dbpath("kpdup"), req09(rid))
    check(bool(r.get("need_kangpo")), f"重复点还是应该拦着，实际 {r}")
    check(not r.get("card09"), f"重复点绝不能执行，实际 {r.get('card09')}")
    g = Game(db, rid)
    check("5m" in g.hand(0) and "3p" not in g.hand(0), f"重复点之后不该换牌，实际 {g.hand(0)}")
    check(bool(g.kangpo_pending), "应该还在等看破")

    # ── ③ 换一笔别的技能：直接拒绝 ──────────────────────────
    r = call(dbpath("kpdup"), req09(rid, skill=1))
    check(not bool(r.get("ok")), f"挂起期间发别的技能应该被拒，实际 {r.get('ok')}")
    check("看破" in str(r.get("error", "")), f"报错要提到看破，实际 {r.get('error')}")

    # ── ④ 放行 → 照原样执行（真的换牌 + 记账）───────────────
    r = call(dbpath("kpdup"), {"op": "kangpo_answer", "seat": 1, "use": False,
                               "round_id": rid})
    check(bool(r.get("ok")), f"放行应该成功，实际 {r.get('error')}")
    g = Game(db, rid)
    hand = list(g.hand(0))
    check("3p" in hand and "5m" not in hand, f"放行后应该换牌，实际 {hand}")
    check(g.c09_next == {0: 1}, f"换完之后下一次只能用 Skill1，实际 {g.c09_next}")
    check(g.kangpo_pending is None, "放行后不该再有挂起")
    st = {c["seat"]: c for c in g._char_states()}
    check(bool((st[0].get("main") or {}).get("open")) is True,
          f"间合发动了 → 9 号卡应该翻明，实际 {st[0].get('main')}")

    # ── ⑤ 看破在 AI 手里（没有 lease）：不问，直接生效 ───────
    db2, rid2 = setup("kpdup2", 82)
    set_lease(db2, 0)                       # 只有 0 号位有人在操作
    clear_lease(db2, 1)                     # 1 号位是 AI
    r = call(dbpath("kpdup2"), req09(rid2))
    check(not bool(r.get("need_kangpo")), f"AI 持有看破时不该问，实际 {r}")
    check(bool(r.get("card09")), f"应该直接执行，实际 {r.get('card09')}")
    g = Game(db2, rid2)
    check(g.kangpo_pending is None, "AI 那边不该留下挂起")
    check("3p" in g.hand(0), f"应该换到 3p，实际 {g.hand(0)}")

    # ── ⑥ 被看破 → 不换牌、不禁发动者以外的人 ───────────────
    db3, rid3 = setup("kpdup3", 83)
    set_lease(db3, 0)
    set_lease(db3, 1)
    call(dbpath("kpdup3"), req09(rid3))
    r = call(dbpath("kpdup3"), {"op": "kangpo_answer", "seat": 1, "use": True,
                                "round_id": rid3})
    check(bool(r.get("ok")), f"看破应该成功，实际 {r.get('error')}")
    g = Game(db3, rid3)
    check("5m" in g.hand(0) and "3p" not in g.hand(0), f"被看破 → 不该换牌，实际 {g.hand(0)}")
    check(g.c09_next == {}, f"被看破 → 不该消耗这一次，实际 {g.c09_next}")
    check(0 in g.no_win, "被看破的那家本局不能和牌")
    check(1 not in g.no_win, "看破的人自己不该被禁和")

    # ── ⑦ 结构：会「发动技能」的 op 都必须挂在看破闸门上 ──────
    need = {"board": (2, 1), "swap": (2, 2), "press": (3, 2), "duel_start": (8, 1),
            "card09_swap": (9, 1), "pofa_activate": (13, 1), "chuancheng": (16, 1),
            "wind_swap": (4, 2), "skill2": (1, 2),
            "card10_hand": (10, 1), "card10_meld": (10, 1)}
    for op, pair in need.items():
        check(api_cli._GATE_SKILL_OPS.get(op) == pair,
              f"{op} 应该挂在看破闸门上（{pair}），实际 {api_cli._GATE_SKILL_OPS.get(op)}")

    print(f"\n通过 {OK} / 失败 {BAD}")
    return 1 if BAD else 0


if __name__ == "__main__":
    sys.exit(main())
