# -*- coding: utf-8 -*-
"""摸牌前技能必须先问 + 看破拦在技能结算前 + 研究明牌全场可见。"""
from __future__ import annotations

import io
import os
import sys

sys.path.insert(0, r'N:\apps\tianma\server')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import api_cli  # noqa: E402
from game import Game  # noqa: E402
from tiles import parse_hand  # noqa: E402
import test_game as tg  # noqa: E402

OK = 0
BAD = 0


def check(cond, msg):
    global OK, BAD
    if cond:
        OK += 1
    else:
        BAD += 1
        print("  [FAIL]", msg)


def call(path, req):
    return api_cli.handle(req, path)


def main():
    # ── ① 摸牌前有技能 → op=step 不许替玩家摸牌 ──────────────────────
    db = tg.fresh_db("pre1")
    rid, _m, _u = tg.new_round(db, seed=81)
    path = os.path.join(r'N:\apps\tianma\server', 'data', '_test_pre1.db')
    g = Game(db, rid)
    g.granted = {0: {14}}
    g.ignite_ok = True
    g.phase, g.turn = "draw", 0
    g.save_flags()
    # 造一张可炸的牌河
    wall = db._rows("SELECT seq FROM round_wall WHERE round_id=? ORDER BY seq LIMIT 2", (rid,))
    with db.tx():
        db.conn.execute(
            "INSERT OR REPLACE INTO round_discards(round_id, seat, seq, wall_seq, tile,"
            " called, is_riichi_tile, face_down, is_tsumogiri) VALUES(?,?,?,?,?,0,0,0,1)",
            (rid, 1, 300, int(wall[0]["seq"]), "6m"))
    g = Game(db, rid)
    check(g.pre_draw_pending(0), "有炸裂可用 → pre_draw_pending 应为 True")

    before = len(g.hand(0))
    r = call(path, {"op": "step", "seat": 0, "round_id": rid})       # 没带 pre_ok
    g2 = Game(db, rid)
    evs = r.get("events") or []
    names = [str(e.get("event", "")) for e in evs if isinstance(e, dict)]
    check("wait_pre" in names, f"应该回 wait_pre，实际 {names}")
    check(len(g2.hand(0)) == before, f"不该先摸牌：{before} → {len(g2.hand(0))}")
    check(str(g2.phase) == "draw", f"应该还停在摸牌前，实际 {g2.phase}")

    # 带 pre_ok 才摸
    r2 = call(path, {"op": "step", "seat": 0, "round_id": rid, "pre_ok": True})
    g3 = Game(db, rid)
    check(len(g3.hand(0)) == before + 1, f"pre_ok 之后应该摸到牌：{before} → {len(g3.hand(0))}")

    # ── ② 看破：拦在技能结算前，且询问期间对局不动 ────────────────────
    db2 = tg.fresh_db("pre2")
    rid2, _m2, _u2 = tg.new_round(db2, seed=82)
    path2 = os.path.join(r'N:\apps\tianma\server', 'data', '_test_pre2.db')
    wall2 = db2._rows("SELECT seq FROM round_wall WHERE round_id=? ORDER BY seq LIMIT 4", (rid2,))
    with db2.tx():
        db2.conn.execute(
            "INSERT OR REPLACE INTO round_discards(round_id, seat, seq, wall_seq, tile,"
            " called, is_riichi_tile, face_down, is_tsumogiri) VALUES(?,?,?,?,?,0,0,0,1)",
            (rid2, 1, 400, int(wall2[0]["seq"]), "7p"))
    g = Game(db2, rid2)
    g.granted = {0: {9}, 1: {17}}           # 0 号位间合、1 号位看破
    g.phase, g.turn = "draw", 0
    g.save_flags()
    hand0 = list(Game(db2, rid2).hand(0))
    river0 = len(Game(db2, rid2).discards(0))
    r = call(path2, {"op": "card09_swap", "seat": 0, "skill": 2, "hand": hand0[-1],
                     "river": 400, "round_id": rid2})
    check(bool(r.get("need_kangpo")), f"间合结算前必须先问看破，实际 {r.get('need_kangpo')}")
    g = Game(db2, rid2)
    check(g.kangpo_pending is not None, "应该记下被挡下的那次发动")
    check(list(g.hand(0)) == hand0, "被挡下时不该真的换牌")

    # 询问期间：不能打牌、不能推进
    r2 = call(path2, {"op": "act", "seat": 0, "action": "discard", "tile": hand0[-1],
                      "round_id": rid2})
    g = Game(db2, rid2)
    check(bool(r2.get("waiting_kangpo")), f"看破期间 act 应该被拦，实际 {r2.get('waiting_kangpo')}")
    check(len(g.discards(0)) == river0, "看破期间不该能切牌")

    # 放行 → 按原样重放（牌真的换了）
    r3 = call(path2, {"op": "kangpo_answer", "seat": 1, "use": False, "round_id": rid2})
    check(bool(r3.get("ok")), f"放行应该成功，实际 {r3.get('error')}")
    g = Game(db2, rid2)
    check(g.kangpo_pending is None, "放行后挂起状态应清掉")
    check(list(g.hand(0)) != hand0, "放行后间合应该真的执行")

    # ── ③ 研究：明牌三家都能看到（走 op=state 验证） ──────────────────
    db3 = tg.fresh_db("pre3")
    rid3, _m3, _u3 = tg.new_round(db3, seed=83)
    path3 = os.path.join(r'N:\apps\tianma\server', 'data', '_test_pre3.db')
    g = Game(db3, rid3)
    g.granted = {0: {17}}
    g.phase, g.turn = "discard", 0
    g.save_flags()
    r = call(path3, {"op": "yanjiu", "seat": 0, "round_id": rid3})
    target = int((r.get("yanjiu") or {}).get("target", -1))
    check(target >= 0, f"研究应该定了目标，实际 {r.get('yanjiu')}")
    seen = []
    for s in range(4):
        st = call(path3, {"op": "state", "seat": s, "round_id": rid3})
        rh = (st.get("state") or {}).get("reveal_hands") or []
        if any(int(x.get("seat", -1)) == target for x in rh):
            seen.append(s)
    check(seen == [0], f"研究只有发动者（0 号位）能看，实际看到的是 {seen}")

    print(f"\n通过 {OK} / 失败 {BAD}")
    return 1 if BAD else 0


if __name__ == "__main__":
    sys.exit(main())
