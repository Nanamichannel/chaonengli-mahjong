# -*- coding: utf-8 -*-
"""立直之后的鸣牌限制（服务端规则）：
   ✗ 不能吃 / 碰 / 明杠        ✓ 可以荣和、可以暗杠
跑法： python test_riichi_rule.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from game import Game  # noqa: E402
import test_game as tg  # noqa: E402

PASS = FAIL = 0
_OPEN_DBS: list = []

# 13 张听牌手牌：123m 456m 789m + 22p 3p 4p → 听 2p/5p（手里有两张 2p，本来能碰）
HAND13 = "123m456m789m2234p"


def check(name, got, want):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  got {got!r} want {want!r}")


def claim_acts(g: Game, seat: int) -> set:
    p = g.pending
    if not p:
        return set()
    return {o["action"] for o in p["options"].get(seat, [])}


def at_discard(g: Game, seat: int) -> Game:
    """把局面摆成「seat 该出牌」（不摸牌，手牌保持刚设好的样子）"""
    g.turn = seat
    g.phase = "discard"
    g.save_flags()
    return g


def cleanup() -> None:
    """把测试用的临时库删掉，别留在 data 目录里（先关连接，不然 Windows 删不掉）"""
    for d in _OPEN_DBS:
        try:
            d.close()
        except Exception:
            pass
    data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    if os.path.isdir(data_dir):
        for f in os.listdir(data_dir):
            if f.startswith("_test_riichi"):
                try:
                    os.remove(os.path.join(data_dir, f))
                except OSError:
                    pass


def main() -> int:
    print("=" * 70)
    print(" 天马麻将 · 立直后的鸣牌限制")
    print("=" * 70)

    # ── 1. 立直之后：不能吃碰明杠，但能荣和 ────────────────────────────
    db = tg.fresh_db("riichi_rule")
    _OPEN_DBS.append(db)
    rid, _m, _ = tg.new_round(db, seed=13)
    tg.set_hand(db, rid, 0, tg.parse_hand(HAND13) + ["9s"], drawn="9s")
    g = at_discard(Game(db, rid), 0)
    check("手牌 14 张（13 + 摸到 9s）", len(g.hand(0)), 14)
    g.act(0, "riichi", tile="9s")
    check("立直已记录", g.is_riichi(0), True)

    # 上家（3 号位）打 2p：我手里有两张 2p，本来能碰
    g._open_claim_window(1, "2p", 3)
    acts_pon = claim_acts(g, 0)
    check("立直后不能碰", "pon" not in acts_pon, True)
    check("立直后不能明杠", "minkan" not in acts_pon, True)
    check("立直后不能吃", "chi" not in acts_pon, True)

    # 上家打 5p：那是我听的牌（一气通贯）
    g._open_claim_window(2, "5p", 3)
    acts_ron = claim_acts(g, 0)
    check("立直后仍然能荣和", "ron" in acts_ron, True)
    check("（能荣和时也看不到碰）", "pon" not in acts_ron, True)

    # ── 2. 对照组：没立直时，同一张 2p 能碰 ─────────────────────────
    db2 = tg.fresh_db("riichi_rule2")
    _OPEN_DBS.append(db2)
    rid2, _m2, _ = tg.new_round(db2, seed=13)
    tg.set_hand(db2, rid2, 0, tg.parse_hand(HAND13) + ["9s"], drawn="9s")
    g2 = at_discard(Game(db2, rid2), 0)
    g2._open_claim_window(1, "2p", 3)
    acts2 = claim_acts(g2, 0)
    check("没立直时能碰", "pon" in acts2, True)
    print("        （对照组的可选项：%s）" % sorted(acts2))

    # ── 3. 立直之后仍然可以暗杠 ─────────────────────────────────────
    db3 = tg.fresh_db("riichi_rule3")
    _OPEN_DBS.append(db3)
    rid3, _m3, _ = tg.new_round(db3, seed=13)
    tg.set_hand(db3, rid3, 0, tg.parse_hand(HAND13) + ["9s"], drawn="9s")
    g3 = at_discard(Game(db3, rid3), 0)
    g3.act(0, "riichi", tile="9s")
    # 立直后摸到第 4 张 1m，可以暗杠
    tg.set_hand(db3, rid3, 0, tg.parse_hand("1111m456m789m234p") + ["4p"], drawn="4p")
    g3b = at_discard(Game(db3, rid3), 0)
    acts3 = {a["action"] for a in g3b.legal_actions(0)}
    check("立直后仍然可以暗杠", "ankan" in acts3, True)
    print("        （立直后该我出牌时的可选项：%s）" % sorted(acts3))

    print()
    print(f"{PASS} 项通过 / {FAIL} 项失败")
    cleanup()
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
