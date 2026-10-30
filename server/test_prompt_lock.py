# -*- coding: utf-8 -*-
"""统一询问锁：有人等回答时谁都不能推进；破发逐个问；看破不被覆盖"""
from __future__ import annotations

import io
import os
import sys
import time

sys.path.insert(0, r'N:\apps\tianma\server')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import api_cli  # noqa: E402
from game import Game  # noqa: E402
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


def dbpath(tag):
    return os.path.join(r'N:\apps\tianma\server', 'data', f'_test_{tag}.db')


def call(path, req):
    return api_cli.handle(req, path)


def main():
    # ── ① 破发询问：step/act 一律停 ────────────────────────
    db = tg.fresh_db("plock")
    rid, _m, _u = tg.new_round(db, seed=221)
    g = Game(db, rid)
    g.phase, g.turn = "discard", 2
    g.save_flags()
    g = Game(db, rid)
    g.pofa_ask = {"declarer": 1, "waiting": [0, 3], "ts": time.time()}
    g.pofa_window = {"declarer": 1}
    g.save_flags()
    check((Game(db, rid).prompt_state() or {}).get("kind") == "pofa",
          "破发询问应该出现在 prompt_state 里")

    for op in ("step", "advance", "act"):
        extra = {"action": "discard", "tile": "1m"} if op == "act" else {}
        r = call(dbpath("plock"), {"op": op, "seat": 2, "pre_ok": True,
                                   "round_id": rid, **extra})
        check(str(r.get("waiting_prompt", "")) == "pofa",
              f"{op} 应该被破发询问拦住，实际 {r.get('waiting_prompt')}")

    # 只轮到 waiting[0]=0
    g = Game(db, rid)
    check(g.pofa_can(0) is True, "0 号位应该被问")
    check(g.pofa_can(3) is False, "3 号位要等 0 号位先回答")

    # 0 号位跳过 → 轮到 3
    r = call(dbpath("plock"), {"op": "pofa_pass", "seat": 0, "round_id": rid})
    check(bool(r.get("ok")), f"pofa_pass 应该成功，实际 {r.get('error')}")
    g = Game(db, rid)
    check(g.pofa_can(3) is True, "0 跳过之后应该轮到 3")
    check((g.prompt_state() or {}).get("kind") == "pofa", "还有人没答 → 仍然锁")
    r = call(dbpath("plock"), {"op": "step", "seat": 2, "pre_ok": True, "round_id": rid})
    check(str(r.get("waiting_prompt", "")) == "pofa", "还有人在等 → step 仍要被拦")

    # 3 也跳过 → 解锁
    call(dbpath("plock"), {"op": "pofa_pass", "seat": 3, "round_id": rid})
    g = Game(db, rid)
    check(g.prompt_state() is None, "都答完 → 不再锁")
    r = call(dbpath("plock"), {"op": "state", "seat": 2, "round_id": rid})
    check(not bool(r.get("waiting_prompt")), "state 不该带 waiting_prompt")

    # ── ② 海神 / 深山 / 友引 也锁 ──────────────────────────
    cases = [
        ("haishin", {"owner": 0, "from": 1, "tile": "5m"}, "haishin_offer"),
        ("shenshan", {"seat": 0, "from": 1, "tile": "5m"}, "shenshan_offer"),
        ("youyin", {"seat": 0}, "youyin_offer"),
    ]
    for kind, val, attr in cases:
        db2 = tg.fresh_db(f"plock_{kind}")
        rid2, _a, _b = tg.new_round(db2, seed=hash(kind) % 1000 + 230)
        g2 = Game(db2, rid2)
        g2.phase, g2.turn = "discard", 2
        setattr(g2, attr, dict(val))
        g2.save_flags()
        p = dbpath(f"plock_{kind}")
        r = call(p, {"op": "step", "seat": 2, "pre_ok": True, "round_id": rid2})
        check(str(r.get("waiting_prompt", "")) == kind,
              f"{kind} 询问期间 step 应该被拦，实际 {r.get('waiting_prompt')}")

    # ── ③ 看破正在等时，别的技能不能把 ask 顶掉 ────────────
    db3 = tg.fresh_db("plock_kp")
    rid3, _c, _d = tg.new_round(db3, seed=241)
    p3 = dbpath("plock_kp")
    g3 = Game(db3, rid3)
    g3.granted = {0: {7}, 1: {17}, 2: {14}}
    g3.phase, g3.turn = "discard", 0
    g3.save_flags()
    # 0 号位发动降神 → 挂起（看破在 1 号位）
    r = call(p3, {"op": "deal_skill", "seat": 0, "action": "use", "card": 7, "skill": 1, "round_id": rid3})
    check(bool(r.get("need_kangpo")), "降神应该先问看破")
    g3 = Game(db3, rid3)
    ask1 = dict(g3.kangpo_ask or {})
    # 2 号位这时发动别的技能（点燃）→ 不能覆盖
    call(p3, {"op": "skill", "seat": 2, "card": 14, "skill": 1, "round_id": rid3})
    g3 = Game(db3, rid3)
    check(dict(g3.kangpo_ask or {}) == ask1,
          f"看破窗口被顶掉了：{ask1} → {g3.kangpo_ask}")

    print(f"\n通过 {OK} / 失败 {BAD}")
    return 1 if BAD else 0


if __name__ == "__main__":
    sys.exit(main())
