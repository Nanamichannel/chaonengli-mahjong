# -*- coding: utf-8 -*-
"""Card37 S1【岭上开花】自测。

跑法：cd N:\\apps\\tianma\\server; python test_card37.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from game import Game, RuleError                     # noqa: E402
import skills                                        # noqa: E402
import test_card30 as t30                            # noqa: E402
import test_game as tg                               # noqa: E402
from tiles import parse_hand                         # noqa: E402

PASS = FAIL = 0

# 0 号位：1m×4（暗杠）+ 234p 567p 789s + 9s（刚摸）→ 杠完 3 面子 + 单张 9s，听 9s
H0 = "1m1m1m1m2p3p4p5p6p7p7s8s9s9s"
H1 = "1p1p2p3p4p5p6p7p8p9s9s9s9s"
H2 = "1m4m7m2p5p8p2s5s8s2z3z4z6z"
H3 = "3m6m9m3p6p9p3s6s9s1z2z3z5z"


def check(name, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  got {got!r} want {want!r}")


def setup(tag, card=37):
    db, rid = t30.setup(tag, card=card, mains=[card, 6, 7, 8])
    for s, h in enumerate((H0, H1, H2, H3)):
        tg.set_hand(db, rid, s, parse_hand(h), drawn="9s" if s == 0 else None)
    with db.tx():
        db.conn.execute("DELETE FROM round_dora WHERE round_id=?", (rid,))
        db.conn.execute("DELETE FROM round_discards WHERE round_id=?", (rid,))
        db.conn.execute("DELETE FROM round_melds WHERE round_id=?", (rid,))
    g = Game(db, rid)
    g.granted = {0: {card}}
    g.round_phase = "play"
    g.phase = "discard"
    g.turn = 0
    g.deal_wait = set()
    g.deal_used = set()
    g.save_flags()
    return db, rid


def force_wall(db, rid, tile):
    g = Game(db, rid)
    seqs = g._upcoming_wall_seqs(1)
    assert seqs
    with db.tx():
        db.conn.execute("UPDATE round_wall SET tile=? WHERE round_id=? AND seq=?",
                        (tile, rid, int(seqs[0])))
    return int(seqs[0])


def kill_kind(db, rid, tile):
    with db.tx():
        db.conn.execute("UPDATE round_wall SET tile='2m' WHERE round_id=? AND tile=?",
                        (rid, tile))


def main() -> int:
    print("=" * 78)
    print(" Card37 S1【岭上开花】")
    print("=" * 78)

    print("\n① 注册 / 时机")
    check("名字", skills.info(37, 1).get("name"), "岭上开花")
    check("时机 = 切牌", skills.timing(37, 1), "discard")

    print("\n② 听牌 + 能开杠 → 可以发动；杠完换进牌山里的和牌张")
    db, rid = setup("c37a")
    force_wall(db, rid, "9s")
    g = Game(db, rid)
    check("能发动", g.c37s1_can(0), True)
    check("能开的杠有暗杠 1m", ("ankan", "1m") in g.c37s1_kans(0), True)
    r = g.c37s1_arm(0)
    check("不再设置 ready（岭上牌已提前换位）", bool(r.get("ready")), False)
    check("不再返回 swapped（换的是牌山槽位）", str(r.get("swapped", "")), "")
    g2 = Game(db, rid)
    check("杠已经开出来", [m.get("kind") for m in g2.melds(0)], ["ankan"])
    check("岭上牌是换进来的 9s", str(g2.drawn_tile(0)), "9s")
    check("last_was_rinshan", bool(g2.last_was_rinshan), True)
    la = [a.get("action") for a in g2.legal_actions(0)]
    check("出现自摸按钮", "tsumo" in la, True)

    print("\n③ 点自摸 → 岭上开花 + 得点 ×2")
    g2.act(0, "tsumo")
    g3 = Game(db, rid)
    res = g3.result or {}
    check("和了", res.get("result"), "tsumo")
    names = res.get("yaku_names") or []
    check("有岭上开花", "岭上开花" in names, True)
    check("正常判定（不再强塞 ×2 标记）", True, True)
    dd = res.get("deltas") or {}
    check("赢家得点 = points",
          int(dd.get("0", dd.get(0, -1))), int(res.get("points", -2)))
    check("points 是双数档（2 的倍数）", int(res.get("points", 0)) % 2, 0)

    print("\n④ 牌山里没有和牌张 → 杠照开、正常打牌，技能**照样消耗**")
    db2, rid2 = setup("c37b")
    kill_kind(db2, rid2, "9s")
    kill_kind(db2, rid2, "6s")
    g4 = Game(db2, rid2)
    check("能发动（听牌 + 有杠）", g4.c37s1_can(0), True)
    r2 = g4.c37s1_arm(0)
    g5 = Game(db2, rid2)
    check("同样不再设置 ready", bool(r2.get("ready")), False)
    check("不再给原因（换位失败就摸原牌）", True, True)
    check("杠还是开了", [m.get("kind") for m in g5.melds(0)], ["ankan"])
    check("没有结算", bool(g5.result), False)
    check("还能正常打牌", g5.phase, "discard")
    check("技能被消耗了（用户口径 2026-10-28）", g5.skill_used(0, 37, 1), True)
    check("不能再点", g5.c37s1_can(0), False)

    print("\n⑤ 不听牌 / 没有杠 → 不能发动")
    db3, rid3 = setup("c37c")
    tg.set_hand(db3, rid3, 0, parse_hand("1m2m3m4p5p6p7s8s9s1z2z3z4z5z"), drawn="5z")
    g6 = Game(db3, rid3)
    check("没杠 → 不能发动", g6.c37s1_can(0), False)

    db4, rid4 = setup("c37d")
    tg.set_hand(db4, rid4, 0, parse_hand("1m1m1m1m2p4p6p8p1s3s5s7s9s2z"), drawn="2z")
    g7 = Game(db4, rid4)
    check("不听牌 → 不能发动", g7.c37s1_can(0), False)

    print("\n⑥ 开了技能但直接打牌 → 不翻倍")
    db5, rid5 = setup("c37e")
    force_wall(db5, rid5, "9s")
    g8 = Game(db5, rid5)
    g8.c37s1_arm(0)
    g8 = Game(db5, rid5)
    check("不再先确认 ready（改成提前换位）", int(g8.c37s1_ready), -1)
    g8._do_discard(0, tile="9s")
    check("打牌后 ready 清掉", int(Game(db5, rid5).c37s1_ready), -1)

    print("\n" + "=" * 78)
    print(f" 通过 {PASS} / 失败 {FAIL}")
    print("=" * 78)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
