# -*- coding: utf-8 -*-
"""配牌技能只看破一次：降神/炸裂/海神（放行后不再问；被看破则本局不可用）"""
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
HAND = ["1m", "2m", "3m", "4m", "5m", "6m", "7m", "8m", "9m", "1p", "2p", "3p", "4p"]


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


def setup(tag, seed, cards=(14,)):
    db = tg.fresh_db(tag)
    set_orders(db, [[14, 14, 14, 14, 3], [17, 17, 17, 17, 4],
                    [1, 2, 3, 4, 5], [6, 7, 8, 9, 10]])
    rid, _m, _u = tg.new_round(db, seed=seed)
    tg.set_hand(db, rid, 0, HAND)
    with db.tx():
        db.conn.execute(
            "INSERT INTO round_discards(round_id, seq, seat, wall_seq, tile, called,"
            " is_riichi_tile, face_down) VALUES(?,?,?,?,?,0,0,0)",
            (rid, 500, 1, 9500, "7m"))
    g = Game(db, rid)
    g.granted = {0: set(cards), 1: {17}}
    g.phase, g.turn = "deal_skill", 0
    g.deal_wait = {0}
    g.save_flags()
    return db, rid, g


def main():
    # ① 点燃（炸裂的配牌发动点）→ 问看破 → 放行 → 记进 kangpo_once
    db, rid, g = setup("konce", 161)
    r = call(dbpath("konce"), {"op": "ignite", "seat": 0, "round_id": rid})
    check(bool(r.get("need_kangpo")), f"配牌点燃应该先问看破，实际 {r}")
    call(dbpath("konce"), {"op": "kangpo_answer", "seat": 1, "use": False, "round_id": rid})
    _flush_asks(dbpath("konce"), rid)
    g = Game(db, rid)
    check(g.ignite_done is True, "放行后点燃应该真的摇了")
    check("0:14:2" in g.kangpo_once, f"炸裂的发动点要记下来，实际 {g.kangpo_once}")

    # ② 之后炸裂不再问看破
    g.ignite_ok = True
    g.phase, g.turn = "draw", 0
    g.deal_wait = set()
    g.save_flags()
    r = call(dbpath("konce"), {"op": "zhalie_swap", "seat": 0, "hand": "1m",
                               "river": 500, "round_id": rid})
    check(not bool(r.get("need_kangpo")), f"配牌问过 → 炸裂不该再问，实际 {r.get('need_kangpo')}")
    check((r.get("zhalie") or {}).get("got") == "7m", f"炸裂应该正常换牌，实际 {r.get('zhalie')}")

    # ③ 被看破 → 点燃不执行、本局炸裂不可用
    db2, rid2, g2 = setup("konce2", 162)
    r = call(dbpath("konce2"), {"op": "ignite", "seat": 0, "round_id": rid2})
    check(bool(r.get("need_kangpo")), "被看破那次也要先问")
    call(dbpath("konce2"), {"op": "kangpo_answer", "seat": 1, "use": True, "round_id": rid2})
    _flush_asks(dbpath("konce2"), rid2)
    g2 = Game(db2, rid2)
    check(g2.ignite_done is False, "被看破 → 点燃不该执行")
    check(g2.ignite_ok is False, "被看破 → 本局不能炸裂")
    g2.phase, g2.turn = "draw", 0
    g2.deal_wait = set()
    g2.save_flags()
    check(g2.zhalie_can(0) is False, "被看破 → 炸裂不可用")

    # ④ 海神：配牌开启时问看破，之后借牌不再问
    db3, rid3, g3 = setup("konce3", 163, cards=(12,))
    r = call(dbpath("konce3"), {"op": "haishin_start", "seat": 0, "round_id": rid3})
    check(bool(r.get("need_kangpo")), f"配牌开启海神应该先问看破，实际 {r}")
    call(dbpath("konce3"), {"op": "kangpo_answer", "seat": 1, "use": False, "round_id": rid3})
    _flush_asks(dbpath("konce3"), rid3)
    g3 = Game(db3, rid3)
    check(g3.haishin_on is True, "放行后海神应该开启")
    check("0:12:1" in g3.kangpo_once, f"海神要记进 kangpo_once，实际 {g3.kangpo_once}")

    # ── ⑤ 配牌重复点：第二次仍然「等看破」，不许绕过、不许执行 ──
    db5, rid5, g5 = setup("konce5", 165, cards=(12,))
    r1 = call(dbpath("konce5"), {"op": "haishin_start", "seat": 0, "round_id": rid5})
    check(bool(r1.get("need_kangpo")), "第一次应该拦下")
    r2 = call(dbpath("konce5"), {"op": "haishin_start", "seat": 0, "round_id": rid5})
    check(bool(r2.get("need_kangpo")), f"第二次仍应拦下（不能绕过看破），实际 {r2}")
    g5 = Game(db5, rid5)
    check(g5.haishin_on is False, "还没回答 → 海神不该开启")
    check(g5.phase == "deal_skill", "还没回答 → 应该还停在配牌阶段")
    r3 = call(dbpath("konce5"), {"op": "step", "seat": 0, "pre_ok": True, "round_id": rid5})
    check(bool(r3.get("waiting_kangpo")), "挂起期间 step 必须被拦")

    # ── ⑥ 被看破：只废这一个技能，配牌窗口继续等（用户口径 2026-10-23）──
    call(dbpath("konce5"), {"op": "kangpo_answer", "seat": 1, "use": True, "round_id": rid5})
    _flush_asks(dbpath("konce5"), rid5)
    g5 = Game(db5, rid5)
    check(g5.haishin_on is False, "被看破 → 海神不该开启")
    check("0:12:1" in g5.poked, f"这个技能要被剔除，实际 {g5.poked}")
    # 这家如果还有别的配牌技能 → 窗口留着让他改选；一个都没有 → 关窗
    left = g5._deal_skill_options(0)
    if left:
        check(0 in g5.deal_wait, f"还有别的配牌技能 → 窗口要留着，实际 {g5.deal_wait}")
        check(g5.phase, "deal_skill")
    else:
        check(0 not in g5.deal_wait, f"没有能用的了 → 关窗，实际 {g5.deal_wait}")
        check(g5.phase != "deal_skill", f"没有能用的了 → phase 要变，实际 {g5.phase}")

    # ── ⑦ 非看破场景下重复点配牌技能：返回 already，不重置流程 ──
    db7, rid7, g7 = setup("konce7", 167, cards=(7,))
    r1 = call(dbpath("konce7"), {"op": "deal_skill", "seat": 0, "action": "use", "card": 7, "skill": 1,
                                 "round_id": rid7})
    check(bool(r1.get("need_kangpo")), "降神配牌也要先问")
    call(dbpath("konce7"), {"op": "kangpo_answer", "seat": 1, "use": False, "round_id": rid7})
    _flush_asks(dbpath("konce7"), rid7)
    g7 = Game(db7, rid7)
    oracle1 = dict(g7.oracle.get(0, {}))
    r2 = call(dbpath("konce7"), {"op": "deal_skill", "seat": 0, "action": "use", "card": 7, "skill": 1,
                                 "round_id": rid7})
    ok2 = bool(r2.get("already")) or ("already" in str(r2.get("reason", ""))) \
        or (not bool(r2.get("armed", False)))
    check(ok2, "重复点不该再发动一次")
    g7 = Game(db7, rid7)
    check(dict(g7.oracle.get(0, {})) == oracle1, "重复点不该重新掷骰")

    # ── ⑧ 挂起超时：15 秒没人回答 → 自动放弃，不卡死 ──────────
    db8, rid8, g8 = setup("konce8", 168, cards=(12,))
    call(dbpath("konce8"), {"op": "haishin_start", "seat": 0, "round_id": rid8})
    g8 = Game(db8, rid8)
    check(g8.kangpo_pending is not None, "应该挂起")
    g8.kangpo_pending["ts"] = 1.0          # 假装 15 秒前
    g8.save_flags()
    r = call(dbpath("konce8"), {"op": "state", "seat": 0, "round_id": rid8})
    g8 = Game(db8, rid8)
    check(g8.kangpo_pending is None, "超时后挂起应该被清掉")
    r2 = call(dbpath("konce8"), {"op": "step", "seat": 0, "pre_ok": True, "round_id": rid8})
    check(not bool(r2.get("waiting_kangpo")), "超时后不该再被拦")

    print(f"\n通过 {OK} / 失败 {BAD}")
    return 1 if BAD else 0


if __name__ == "__main__":
    sys.exit(main())
