# -*- coding: utf-8 -*-
"""振听也能立直（振聴立直）—— can_riichi 和 riichi_discards 口径一致

现场 bug：1 号位听 6s/9s，9s 就在自己牌河里 → `can_riichi` 判「永久振听」不许立直
→ 立直按钮永远不出现（打完一张振听牌之后按钮直接消失，而且这一局再也回不来）。
同时先负换完牌如果是「单骑待自己切的牌」，换完就立不了直 → 先负白用。

标准日麻：**振聴でも立直は可能**（只是不能荣和）。所以：
  · `can_riichi()` 不再看振听（只看门清 / 听牌 / 分数 / 巡目）
  · `riichi_discards()` 只看形状（切完还听不听）
  · 振听仍然拦「荣和」（`calls.can_ron` 不受影响）

跑法：cd N:\apps\tianma\server; python test_riichi_furiten.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from game import Game, RuleError         # noqa: E402
import test_game as tg                   # noqa: E402
from tiles import parse_hand, counts_of  # noqa: E402
from rules import calls                  # noqa: E402

PASS = FAIL = 0


def check(name, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  got {got!r} want {want!r}")


def add_discard(db, rid, seat, seq, tile, face_down=0):
    with db.tx():
        db.conn.execute(
            "INSERT OR REPLACE INTO round_discards(round_id, seq, seat, wall_seq, tile,"
            " is_tsumogiri, is_riichi_tile, face_down, called)"
            " VALUES(?,?,?,?,?,1,0,?,0)", (rid, seq, seat, 9000 + seq, tile, face_down))


def setup(tag, own_discards, drawn="9s"):
    """手牌 123m456m789m5p5p6s7s + 摸到 9s → 切 9s 听 5s/8s，切 6s 听 8s"""
    hand = parse_hand("123m456m789m5p5p6s7s") + [drawn]
    db = tg.fresh_db(tag)
    rid, _m, _u = tg.new_round(db, seed=53)
    tg.set_hand(db, rid, 0, hand, drawn=drawn)
    tg.set_hand(db, rid, 1, parse_hand("1m4m7m1p4p7p1s4s7s1z2z3z"))
    tg.set_hand(db, rid, 2, parse_hand("2m5m8m2p5p8p2s5s8s2z3z4z"))
    tg.set_hand(db, rid, 3, parse_hand("3m6m9m3p6p9p3s6s9s1z2z3z"))
    g = Game(db, rid)
    g.round_phase = "play"
    g.turn, g.phase = 0, "discard"
    g.save_flags()
    seq = 100
    for t in own_discards:
        add_discard(db, rid, 0, seq, t)
        seq += 1
    return Game(db, rid)


def main() -> int:
    print("=" * 74)
    print(" 振听也能立直（can_riichi / riichi_discards 口径一致）")
    print("=" * 74)

    # ── ① 干净手牌 ───────────────────────────────────────────────────
    print("\n① 牌河里没有自己的待牌")
    g = setup("riichi_clean", ["dong"])
    check("可以立直", g.can_riichi(0))
    check("宣言牌 = 6s / 9s", sorted(g.riichi_discards(0)), ["6s", "9s"])

    # ── ② 待牌在自己牌河（永久振听）→ 仍然能立直 ────────────────────────
    print("\n② 待牌 5s 在自己牌河里 → 振听，但依然可以立直")
    g2 = setup("riichi_furiten5s", ["5s", "dong"])
    check("仍然可以立直（振聴立直）", g2.can_riichi(0))
    check("宣言牌只看形状，还是 6s / 9s", sorted(g2.riichi_discards(0)), ["6s", "9s"])
    hand13 = g2.hand13(0)
    check("振听依然拦荣和（5s 不能荣和）",
          calls.can_ron(counts_of(hand13), g2.melds(0),
                        g2.discards_for_furiten(0), "5s"), False)

    # ── ③ 真的发一次立直：能立，但荣和不行 ───────────────────────────────
    print("\n③ 振听状态下真的发 op=riichi")
    r = g2.act(0, "riichi", tile="9s")
    check("立直成功", str(r.get("event", "")), "discard")
    g2b = Game(g2.db, g2.round_id)
    check("进了立直状态", g2b.is_riichi(0))
    check("立直宣言牌记的是 9s",
          [d for d in g2b.db._rows("SELECT tile FROM round_discards WHERE round_id=? "
                                   "AND seat=0 AND is_riichi_tile=1", (g2b.round_id,))],
          [{"tile": "9s"}])
    check("5s 依然不能荣和",
          calls.can_ron(counts_of(g2b.hand13(0)), g2b.melds(0),
                        g2b.discards_for_furiten(0), "5s"), False)

    # ── ④ 待牌 8s 同理 ────────────────────────────────────────────────
    print("\n④ 待牌 8s 在自己牌河里")
    g4 = setup("riichi_furiten8s", ["8s"])
    check("仍然可以立直", g4.can_riichi(0))

    # ── ⑤ 暗置牌（换牌技能塞进来的）不算自己打的 ─────────────────────────
    print("\n⑤ 暗置牌不造成振听")
    g5 = setup("riichi_facedown", [])
    add_discard(g5.db, g5.round_id, 0, 200, "5s", face_down=1)
    g5 = Game(g5.db, g5.round_id)
    check("可以立直", g5.can_riichi(0))
    check("5s 仍然可以荣和（暗置牌不算）",
          calls.can_ron(counts_of(g5.hand13(0)), g5.melds(0),
                        g5.discards_for_furiten(0), "5s"), True)

    # ── ⑥ 口径一致性：有宣言牌 ⟺ 能立直 ──────────────────────────────────
    print("\n⑥ can_riichi 与 riichi_discards 一致")
    for tag, disc in (("riichi_clean", ["dong"]), ("riichi_furiten5s", ["5s"]),
                      ("riichi_furiten8s", ["8s"])):
        gg = setup("consist_" + tag, disc)
        check(f"{tag}: 有宣言牌 = 能立直",
              bool(gg.riichi_discards(0)) == gg.can_riichi(0))

    print("\n" + "=" * 74)
    print(f" 结果：{PASS} 项通过，{FAIL} 项失败")
    print("=" * 74)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
