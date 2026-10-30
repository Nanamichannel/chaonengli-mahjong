# -*- coding: utf-8 -*-
"""Card22 S1「先负」自测：别家立直的一发巡 → 换牌 → 正常立直 → 结算他出铳

用户口径：
  · 别家立直的一发巡（一发已经被破了就不行），我摸牌后可以发动
  · 默认方式选一张手牌、黄框选一张牌河的牌，按「开始」交换
  · 换完之后必须还能正常立直（弹出立直按钮 → 点 → 进入正常立直流程）
"""
from __future__ import annotations

import io
import sys

sys.path.insert(0, r'N:\apps\tianma\server')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

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


def setup():
    db = tg.fresh_db("xf")
    rid, _m, _u = tg.new_round(db, seed=41)
    # 我：123m 456p 789s 111p + 99p（摸到 9p，打掉就单骑听 9p）
    tg.set_hand(db, rid, 0, parse_hand("123m456p789s111p99p"), drawn="9p")
    # 1 号位：已经立直 + 一发巡，牌河里有一张明置的 7p
    with db.tx():
        db.conn.execute("INSERT OR REPLACE INTO round_riichi(round_id, seat) VALUES(?,?)",
                        (rid, 1))
        db.conn.execute(
            "INSERT OR REPLACE INTO round_discards(round_id, seat, seq, wall_seq, tile,"
            " called, is_riichi_tile, face_down, is_tsumogiri)"
            " VALUES(?,?,?,?,?,0,0,0,1)", (rid, 1, 1401, 940001, "7p"))
    g = Game(db, rid)
    g.granted = {0: {22}}
    g.ippatsu.add(1)
    g.phase, g.turn = "discard", 0
    g.save_flags()
    return db, rid


def main():
    db, rid = setup()
    g = Game(db, rid)
    check(g.xianfu_can(0), "一发巡 + 别人立直 → 先负应该可以发动")
    check(g.can_riichi(0), "换牌之前本来就听牌，应该能立直")
    seqs = g.gift_targets(0)
    check(1401 in seqs, f"牌河那张 7p 应该可换，实际 {seqs}")

    r = g.xianfu_swap(0, "9p", 1401)
    check(r.get("got") == "7p", f"应该换到 7p，实际 {r}")

    g = Game(db, rid)
    check(int(g.xianfu_armed) == 0, "换完牌要记下「等我去立直」")
    check(g.can_riichi(0), "换完牌之后必须还能立直（用户口径）")
    disc = g.riichi_discards(0)
    check(bool(disc), f"换完牌之后要有可立直切牌，实际 {disc}")

    # 正常立直
    ev = g.act(0, "riichi", tile=str(disc[0]))
    check(ev.get("event") in ("discard", "riichi"), f"立直应该成功，实际 {ev}")
    g = Game(db, rid)
    check(g.is_riichi(0), "立直之后应该在立直状态")
    check(g.phase == "ended" or int((g.xianfu_pending or {}).get("declarer", -1)) == 1,
          f"先负要么已经结算、要么记着谁立直引出来的，实际 phase={g.phase} / {g.xianfu_pending}")

    # 立直牌打出去、没人荣和 → 直接按先负结算（他出铳）
    for _ in range(6):
        g = Game(db, rid)
        if g.phase == "ended":
            break
        if g.phase == "claim":
            for s in list(g.pending.get("options", {})):
                if s not in g.pending["answers"]:
                    g.act(s, "pass")
            g = Game(db, rid)
            if g.phase == "claim":
                g.advance()
            continue
        if g.phase == "discard" and g.turn is not None:
            tiles = [a["tiles"] for a in g.legal_actions(int(g.turn))
                     if a["action"] == "discard"]
            if tiles:
                g.act(int(g.turn), "discard", tile=str(tiles[0][0]))
                continue
        g.advance()
    g = Game(db, rid)
    check(g.phase == "ended", f"先负应该直接结算出结果，实际 phase={g.phase}")

    print(f"\n通过 {OK} / 失败 {BAD}")
    return 1 if BAD else 0


if __name__ == "__main__":
    sys.exit(main())
