# -*- coding: utf-8 -*-
"""Card15 S1「钓鱼」可以多次发动：不能因为用了一次就把图标永久置灰。

用户现场：吃到上家的牌之后明明解锁了，图标还是锁着点不动。
根因：diaoyu_force 走 note_skill → note_use → used_skills 里写 `15-1-座位`
→ 客户端 _apply_used_skills 把它当一次性技能置灰。
"""
from __future__ import annotations

import io
import json
import sys

sys.path.insert(0, r'N:\apps\tianma\server')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from game import Game  # noqa: E402
from tiles import parse_hand  # noqa: E402
import test_game as tg  # noqa: E402

OK = 0
BAD = 0
ORD_15 = [[15, 15, 15, 15, 4], [1, 2, 3, 4, 5], [1, 2, 3, 4, 6], [1, 2, 3, 4, 7]]
HAND = parse_hand("123m456p789s") + ["5s", "5s", "3p", "6p", "9p"]
OTHER = parse_hand("123m456p789s") + ["5s", "2m", "9p", "9p"]


def check(cond, msg):
    global OK, BAD
    if cond:
        OK += 1
    else:
        BAD += 1
        print("  [FAIL]", msg)


def new_round(db, seed):
    body = {"seats": [{"ready": False, "hand": [], "picks": [], "order": list(o)}
                      for o in ORD_15], "phase": "playing"}
    with db.tx():
        db.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('lobby_state', ?)",
                        (json.dumps(body, ensure_ascii=False),))
    rid, _m, _u = tg.new_round(db, seed=seed)
    tg.set_hand(db, rid, 0, HAND, drawn="9p")
    for t in range(1, 4):
        tg.set_hand(db, rid, t, OTHER, drawn="9p")
    g = Game(db, rid)
    g.phase, g.turn = "discard", 0
    g.save_flags()
    return rid


def main():
    db = tg.fresh_db("dyrepeat")
    rid = new_round(db, 1501)
    g = Game(db, rid)
    check(g.diaoyu_can(0), "摸牌后可以钓鱼")
    check(not g.skill_used(0, 15, 1), "还没发动 → 不该记一次性")

    g.diaoyu_force(0, 3, "5s")
    g2 = Game(db, rid)
    check(not g2.skill_used(0, 15, 1),
          "发动后也不能进 used_skills（否则图标永久灰）")

    # 卡面还是要翻明 + 还是要播报
    st = {c["seat"]: c for c in g2._char_states()}
    check(bool((st[0].get("main") or {}).get("open")) is True, "15 号卡应该翻明")
    check(bool(g2.broadcast), "应该有播报")

    # 发动后本小局锁住（等吃到/碰上家的牌才解锁）
    check(g2.diaoyu_locked, "发动后先锁住")
    check(not g2.diaoyu_can(0), "锁住时不能发动")

    # 吃到上家的牌 → 解锁
    g2.diaoyu_locked = False
    g2.save_flags()
    g3 = Game(db, rid)
    check(not g3.diaoyu_locked, "解锁落库")
    # 下一次摸牌之后又能发动（钓鱼会把刚摸的那张交给对方，且把 turn 交给对方）
    tg.set_hand(db, rid, 0, HAND, drawn="9p")
    g4 = Game(db, rid)
    g4.phase, g4.turn = "discard", 0
    g4.save_flags()
    g4 = Game(db, rid)
    check(g4.diaoyu_can(0), "解锁 + 下次摸牌后又能用")

    print(f"\n通过 {OK} / 失败 {BAD}")
    return 1 if BAD else 0


if __name__ == "__main__":
    sys.exit(main())
