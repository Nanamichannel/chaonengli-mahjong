# -*- coding: utf-8 -*-
"""立直后手牌锁定：会改手牌/牌河的技能 can 一律 False；降神不受影响"""
from __future__ import annotations

import io
import sys

sys.path.insert(0, r'N:\apps\tianma\server')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from game import Game  # noqa: E402
import test_game as tg  # noqa: E402

OK = 0
BAD = 0
CAN = ["card09_can", "zhalie_can", "haishin_can", "card11_can", "card11s2_can",
       "shenshan_can", "gift_can", "youyin_swap_can", "diaoyu_can", "pofa_can",
       "card10_can"]


def check(cond, msg):
    global OK, BAD
    if cond:
        OK += 1
    else:
        BAD += 1
        print("  [FAIL]", msg)


def make(tag, seed, riichi):
    db = tg.fresh_db(tag)
    rid, _m, _u = tg.new_round(db, seed=seed)
    tg.set_hand(db, rid, 0, ["1m", "2m", "3m", "4m", "5m", "6m", "7m", "8m",
                             "9m", "1p", "2p", "3p", "4p", "5p"])
    with db.tx():
        db.conn.execute(
            "INSERT INTO round_discards(round_id, seq, seat, wall_seq, tile, called,"
            " is_riichi_tile, face_down) VALUES(?,?,?,?,?,0,0,0)",
            (rid, 500, 1, 9500, "9p"))
        if riichi:
            db.conn.execute("INSERT OR REPLACE INTO round_riichi(round_id, seat) VALUES(?,?)",
                            (rid, 0))
    g = Game(db, rid)
    g.granted = {0: set(range(1, 24))}
    g.ignite_ok = True
    g.gift = {0: 5}
    g.phase, g.turn = "draw", 0
    g.save_flags()
    return db, rid, g


def main():
    # ── ① 立直后：全部 False
    db, rid, g = make("rlock", 151, True)
    for name in CAN:
        fn = getattr(g, name, None)
        if fn is None:
            check(False, f"{name} 不存在")
            continue
        try:
            val = fn(0)
        except TypeError:
            val = fn(0)          # 有些 can 可能带额外参数，这里统一 1 个
        check(val is False, f"立直后 {name} 应该 False，实际 {val}")

    # ── ② 未立直：间合/炸裂能发动（说明锁只因为立直）
    db2, rid2, g2 = make("rlock2", 152, False)
    check(g2.card09_can(0) is True, "未立直时间合应该能发动")
    check(g2.zhalie_can(0) is True, "未立直且点燃成功时炸裂应该能发动")

    # ── ③ 降神不受影响（只换牌山顺序，不改手牌）
    g3 = Game(db2, rid2)
    g3.oracle = {0: {"suit": "m", "on": True, "dice": 7}}
    with db2.tx():
        db2.conn.execute("INSERT OR REPLACE INTO round_riichi(round_id, seat) VALUES(?,?)",
                         (rid2, 0))
    g3.save_flags()
    g4 = Game(db2, rid2)
    r = g4.oracle_toggle(0)
    check(bool(r.get("on")) is False, f"立直后降神开关应该照常可用，实际 {r}")

    print(f"\n通过 {OK} / 失败 {BAD}")
    return 1 if BAD else 0


if __name__ == "__main__":
    sys.exit(main())
