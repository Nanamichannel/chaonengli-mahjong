# -*- coding: utf-8 -*-
"""风盘：state 要下发「本半庄的开局风场」（半庄不一定从东场开始）。

客户端按它决定显示哪张「东南X」图：
  开局东场 → 东:一 南:四 西:三 北:二
  开局南场 → 南:二 西:一 北:四 东:三
  开局西场 → 西:三 北:二 东:一 南:四
  开局北场 → 北:四 东:三 南:二 西:一
"""
from __future__ import annotations

import io
import sys

sys.path.insert(0, r'N:\apps\tianma\server')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

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


def main():
    print("① 东场开局")
    db = tg.fresh_db("wind1")
    rid, mid, _u = tg.new_round(db, seed=31)          # 东一
    g = Game(db, rid)
    check(g.start_wind() == "dong", f"应该 dong，实际 {g.start_wind()}")
    check(Game(db, rid).state_for(0).get("start_wind") == "dong", "state 里要带 start_wind")

    print("\n② 换到南一：开局风场还是 dong（不是当前风场）")
    rid2 = db.start_round(mid, "nan", 1, honba=0, dealer_seat=0, seed=32)
    g2 = Game(db, rid2)
    check(g2.start_wind() == "dong", f"应该 dong，实际 {g2.start_wind()}")
    check(g2.state_for(0).get("wind") == "nan", "当前风场应该是 nan")

    print("\n③ 半庄从南场开始")
    db2 = tg.fresh_db("wind2")
    uids = [db2.create_user(f"w2_{i}") for i in range(4)]
    room = db2.create_room(uids[0])
    for u in uids[1:]:
        db2.join_room(room["room_code"], u)
    mid2 = db2.start_match(room["room_id"], seed=33)
    rid3 = db2.start_round(mid2, "nan", 1, honba=0, dealer_seat=0, seed=33)
    g3 = Game(db2, rid3)
    check(g3.start_wind() == "nan", f"开局南场 → 应该 nan，实际 {g3.start_wind()}")
    check(g3.state_for(0).get("start_wind") == "nan", "state 里 start_wind = nan")

    print("\n④ 同一个半庄里前面有本场（honba）也不影响")
    rid4 = db2.start_round(mid2, "nan", 1, honba=3, dealer_seat=0, seed=34)
    g4 = Game(db2, rid4)
    check(g4.start_wind() == "nan", f"本场 3 时仍是 nan，实际 {g4.start_wind()}")

    print(f"\n通过 {OK} / 失败 {BAD}")
    return 1 if BAD else 0


if __name__ == "__main__":
    sys.exit(main())
