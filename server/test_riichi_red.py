# -*- coding: utf-8 -*-
"""立直可切牌：红 5（0s）和普通 5s 一视同仁，按日麻标准来。

手牌 14 张 = 123m 456p 789s 111p + 0s + 8s
  · 切 0s → 剩 123m456p789s111p + 8s，单骑 8s，仍听牌 → 应该允许
  · 切 8s → 剩 123m456p789s111p + 0s，单骑 5s，仍听牌 → 应该允许
老 bug：riichi_discards 返回牌种 "5s"，按字面比对找不到手上的 "0s" → 只让切 8s。
"""
from __future__ import annotations

import io
import json
import os
import sys

sys.path.insert(0, r'N:\apps\tianma\server')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from db import DB  # noqa: E402
from game import Game  # noqa: E402

OK = 0
BAD = 0


def check(cond, msg):
    global OK, BAD
    if cond:
        OK += 1
    else:
        BAD += 1
        print("  [FAIL]", msg)


def fresh():
    path = r'N:\apps\tianma\server\data\_t_red.db'
    for suf in ("", "-wal", "-shm"):
        try:
            os.remove(path + suf)
        except OSError:
            pass
    db = DB(path)
    db.init_schema()
    uids = [db.create_user(f"red{i}") for i in range(4)]
    room = db.create_room(uids[0])
    for u in uids[1:]:
        db.join_room(room["room_code"], u)
    match = db.start_match(room["room_id"], seed=7)
    body = {"seats": [{"ready": True, "hand": [], "picks": [], "order": [1, 2, 3, 4, 5]}
                      for _ in range(4)], "phase": "playing"}
    with db.tx():
        db.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('lobby_state', ?)",
                        (json.dumps(body, ensure_ascii=False),))
    rid = db.start_round(match, "dong", 1, honba=0, dealer_seat=0, seed=7)
    g = Game(db, rid)
    g.start()
    n = 0
    while not g.deal_done():
        g.deal_step()
        n += 1
        if n > 40:
            break
    return db, rid


def set_hand(db, rid, seat, tiles, drawn=None):
    with db.tx():
        db.conn.execute("DELETE FROM round_hands WHERE round_id=? AND seat=?", (rid, seat))
        for i, t in enumerate(tiles):
            db.conn.execute(
                "INSERT INTO round_hands(round_id, seat, wall_seq, tile, slot, is_drawn)"
                " VALUES(?,?,?,?,?,?)",
                (rid, seat, 900000 + seat * 100 + i, t, i,
                 1 if (drawn and t == drawn and i == len(tiles) - 1) else 0))


def main():
    db, rid = fresh()
    hand = ["1m", "2m", "3m", "4p", "5p", "6p", "7s", "8s", "9s",
            "1p", "1p", "1p", "0s", "8s"]
    set_hand(db, rid, 0, hand, drawn="8s")
    g = Game(db, rid)
    g.phase, g.turn = "discard", 0
    g.save_flags()
    g = Game(db, rid)
    disc = g.riichi_discards(0)
    print("可立直切牌 =", disc)
    check("0s" in disc, f"红 5（0s）应该可以立直切出，实际 {disc}")
    check("8s" in disc, f"8s 应该可以立直切出，实际 {disc}")
    check(len(disc) >= 2, f"至少两张（0s/8s 都要在），实际 {disc}")
    check(len(set(disc)) == len(disc) or disc.count("8s") == 2, "可切牌列表不应出现重复的同一张实体")
    # 真打一次：切 0s 立直必须成功
    g = Game(db, rid)
    ev = g.act(0, "riichi", tile="0s")
    check(bool(ev), "切 0s 立直应该成功")
    g = Game(db, rid)
    check(g.is_riichi(0), "切 0s 后应该在立直状态")
    row = db._row("SELECT tile FROM round_discards WHERE round_id=? ORDER BY seq DESC LIMIT 1",
                  (rid,))
    check(str(row["tile"]) == "0s", f"牌河最后一张应是 0s，实际 {row['tile']}")

    # 立直之后只允许摸切
    acts = g.legal_actions(0) if g.phase == "discard" and g.turn == 0 else []
    print("立直后 legal =", acts)

    print(f"\n通过 {OK} / 失败 {BAD}")
    return 1 if BAD else 0


if __name__ == "__main__":
    sys.exit(main())
