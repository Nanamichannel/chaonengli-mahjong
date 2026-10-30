# -*- coding: utf-8 -*-
"""配牌技能阶段：**不限时**（用户口径 2026-10-27）。

历史：以前等 20 秒没人点「发动 / 开始」就由服务端自己跳过（怕整局卡在 deal_skill）。
现在改成一律等玩家自己决定：
  · `_open_deal_window()` 不记截止时间（deal_deadline 恒 0.0）
  · `deal_skill_timeout()` 恒 False（哪怕 deal_deadline 是过去的时间）
  · `api_cli` 的任何请求都不会替「还在想的人」跳过配牌
  · `deal_skip_all()` 作为**手动**兜底仍然保留（显式调用时才收尾）
"""
from __future__ import annotations

import io
import json
import sys
import time

sys.path.insert(0, r"N:\apps\tianma\server")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from game import Game  # noqa: E402
import api_cli  # noqa: E402
import test_game as tg  # noqa: E402

OK = 0
BAD = 0


def check(cond, msg):
    global OK, BAD
    if cond:
        OK += 1
        print("  [OK]  ", msg)
    else:
        BAD += 1
        print("  [FAIL]", msg)


def set_orders(db, orders):
    body = {"seats": [{"ready": False, "hand": [], "picks": [], "order": list(o)}
                      for o in orders], "phase": "playing"}
    with db.tx():
        db.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('lobby_state', ?)",
                        (json.dumps(body, ensure_ascii=False),))


def main():
    print("=" * 70)
    print(" 配牌技能阶段：不限时")
    print("=" * 70)

    print("\n① _open_deal_window 不再记截止时间")
    db = tg.fresh_db("dto1")
    set_orders(db, [[3, 3, 3, 3, 4], [1, 2, 4, 5, 6], [1, 2, 4, 5, 7], [1, 2, 4, 5, 8]])
    rid, _m, _u = tg.new_round(db, seed=41)
    g = Game(db, rid)
    g.deal_used = set()
    g.deal_wait = set()
    g._open_deal_window()
    check(g.phase == "deal_skill", f"应该进入配牌技能阶段，实际 {g.phase}")
    check(g.deal_deadline == 0.0, f"截止时间恒 0（不限时），实际 {g.deal_deadline}")
    check(0 in g.deal_wait, f"0 号位有卡，应该在等待列表，实际 {g.deal_wait}")

    print("\n② 没有超时 → 不放行")
    g2 = Game(db, rid)
    check(not g2.deal_skill_timeout(), "没超时当然不放行")

    print("\n③ 就算截止时间早就过了，也不算超时")
    g3 = Game(db, rid)
    g3.deal_wait = {0, 2}
    g3.deal_deadline = time.time() - 999.0
    g3.save_flags()
    g4 = Game(db, rid)
    check(not g4.deal_skill_timeout(), "过去的截止时间也不放行（不限时）")

    print("\n④ api_cli 的 state 请求不会替「还在想的人」跳过配牌")
    db2 = tg.fresh_db("dto2")
    set_orders(db2, [[3, 3, 3, 3, 4], [1, 2, 4, 5, 6], [1, 2, 4, 5, 7], [1, 2, 4, 5, 8]])
    rid2, _m2, _u2 = tg.new_round(db2, seed=42)
    g6 = Game(db2, rid2)
    g6.deal_wait = {0}
    g6.phase = "deal_skill"
    g6.deal_deadline = time.time() - 999.0
    g6.save_flags()
    api_cli.handle({"op": "state", "seat": 0, "round_id": rid2}, db2.path)
    g7 = Game(db2, rid2)
    check(g7.phase == "deal_skill", f"还是配牌阶段，实际 {g7.phase}")
    check(sorted(g7.deal_wait) == [0], f"还在等 0 号位，实际 {sorted(g7.deal_wait)}")

    print("\n⑤ 手动 deal_skip_all()：仍然能把换牌流程和等待一并收掉")
    db3 = tg.fresh_db("dto3")
    set_orders(db3, [[3, 3, 3, 3, 4], [1, 2, 4, 5, 6], [1, 2, 4, 5, 7], [1, 2, 4, 5, 8]])
    rid3, _m3, _u3 = tg.new_round(db3, seed=43)
    g8 = Game(db3, rid3)
    g8.phase = "deal_skill"
    g8.deal_wait = {0}
    g8.deal_flow = {"kind": "xiangting", "seat": 0, "stage": 0, "targets": [1, 2],
                    "sub": "give", "target": 1, "picked": []}
    g8.save_flags()
    g9 = Game(db3, rid3)
    g9.deal_skip_all()
    g10 = Game(db3, rid3)
    check(g10.deal_flow is None, "没做完的换牌流程应该被清掉")
    check(g10.phase == "discard", f"应该放行到打牌，实际 {g10.phase}")
    check(not g10.deal_wait, f"等待列表应该清空，实际 {g10.deal_wait}")

    print("\n⑥ 向听被卡住时：任何请求都替「没人的座位」交牌（step / state 都一样）")
    db4 = tg.fresh_db("dto4")
    set_orders(db4, [[30, 1, 2, 3, 4], [1, 2, 4, 5, 6], [1, 2, 4, 5, 7], [1, 2, 4, 5, 8]])
    rid4, _m4, _u4 = tg.new_round(db4, seed=44)
    # 只有 0 号位「有人在操作」，1/2/3 号位算 AI
    with db4.tx():
        for s in (1, 2, 3):
            db4.conn.execute("DELETE FROM meta WHERE key=?", (api_cli.LEASE_KEY % s,))
    g11 = Game(db4, rid4)
    g11.phase = "deal_skill"
    g11.deal_wait = {0}
    g11.deal_flow = {"kind": "xiangting", "seat": 0, "card": 30, "skill": 1,
                     "targets": [1, 3], "stage": 0, "sub": "give",
                     "target": 1, "picked": []}
    g11.save_flags()
    api_cli.handle({"op": "state", "seat": 0, "round_id": rid4}, db4.path)
    g12 = Game(db4, rid4)
    flow = g12.deal_flow or {}
    check(str(flow.get("sub")) == "swap", f"1 号位（AI）应该已经被代交，实际 sub={flow.get('sub')}")
    check(flow.get("picked") == ["dong", "nan"] or len(flow.get("picked") or []) == 2,
          f"交了两张，实际 {flow.get('picked')}")

    print("\n" + "=" * 70)
    print(f" 通过 {OK} / 失败 {BAD}")
    print("=" * 70)
    return 1 if BAD else 0


if __name__ == "__main__":
    sys.exit(main())
