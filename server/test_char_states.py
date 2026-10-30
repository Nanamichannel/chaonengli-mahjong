# -*- coding: utf-8 -*-
"""遮罩状态（A 案：按「卡」算）自测

  · 用主战卡的技能 → main.open=True，support 不受影响
  · 用协战卡的技能 → support.open=True，main 不受影响
  · 「这一风场 + 下一风场」之后 expired（永久遮住）
  · 新半庄 → 全部恢复未发动
"""
from __future__ import annotations

import io
import json
import sys

sys.path.insert(0, r'N:\apps\tianma\server')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from db import DB  # noqa: E402
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


def set_orders(db, orders):
    body = {"seats": [{"ready": False, "hand": [], "picks": [], "order": list(o)}
                      for o in orders], "phase": "playing"}
    with db.tx():
        db.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('lobby_state', ?)",
                        (json.dumps(body, ensure_ascii=False),))


def states(g):
    return {c["seat"]: c for c in g._char_states()}


def main():
    db = tg.fresh_db("mask")
    # 0 号位：order = [11, 1, 2, 3, 12] → 东一主战 11、协战 12
    set_orders(db, [[11, 11, 11, 11, 12], [1, 2, 3, 4, 5], [1, 2, 3, 4, 6], [1, 2, 3, 4, 7]])
    rid, _m, _u = tg.new_round(db, seed=111)
    g = Game(db, rid)
    st = states(g)[0]
    check(st["main"]["card"] == 11 and st["support"]["card"] == 12,
          f"0 号位主战/协战摆错：{st}")
    check(st["main"]["open"] is False and st["support"]["open"] is False,
          "新半庄应该都还没翻明")

    # ① 用主战卡的技能
    g = Game(db, rid)
    g.mark_skill_used(0, 11, 1)
    g = Game(db, rid)
    st = states(g)[0]
    check(st["main"]["open"] is True, "用主战卡技能 → 主战卡应该翻明")
    check(st["support"]["open"] is False, "主战卡发动不该连带翻明协战卡")

    # ② 用协战卡的技能
    g = Game(db, rid)
    g.mark_skill_used(0, 12, 1)
    g = Game(db, rid)
    st = states(g)[0]
    check(st["support"]["open"] is True, "用协战卡技能 → 协战卡应该翻明")

    # ③ 寿命：东一用过的卡存活「两个风场」= 东一 + 东二，东三起过期
    for wind, num, want_expired in (("dong", 2, False), ("dong", 3, True),
                                    ("nan", 1, True)):
        rid2 = db.start_round(db._one("SELECT match_id FROM rounds WHERE round_id=?", (rid,)),
                              wind, num, honba=0, dealer_seat=0, seed=112)
        g2 = Game(db, rid2)
        st2 = states(g2)[0]
        check(bool(st2["main"]["expired"]) == want_expired,
              f"{wind}{num}：主战卡 expired 应该 {want_expired}，实际 {st2['main']}")

    print(f"\n通过 {OK} / 失败 {BAD}")
    return 1 if BAD else 0


if __name__ == "__main__":
    sys.exit(main())
