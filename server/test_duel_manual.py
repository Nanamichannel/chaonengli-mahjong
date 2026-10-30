# -*- coding: utf-8 -*-
"""决斗改版：手动打牌 / 只能打刚摸到的 / 暗置牌只有压制能荣 / 技能照常"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")

from game import Game, RuleError  # noqa: E402
from tiles import parse_hand  # noqa: E402
import test_game as tg  # noqa: E402

PASS = 0
FAIL = 0


def check(name, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  got={got!r} want={want!r}")


def add_river(db, rid, seq, seat, tile, wseq):
    with db.tx():
        db.conn.execute(
            "INSERT OR REPLACE INTO round_discards(round_id, seq, seat, wall_seq, tile,"
            " is_tsumogiri, is_riichi_tile, face_down, called)"
            " VALUES(?,?,?,?,?,1,0,0,0)", (rid, seq, seat, wseq, tile))


def make(tag, seed, seat2_cards=(), seat3_cards=()):
    db = tg.fresh_db(tag)
    rid, _m, _u = tg.new_round(db, seed=seed)
    tg.set_hand(db, rid, 0, parse_hand("1m4m7m1p4p7p1s4s7s1z2z3z"))
    tg.set_hand(db, rid, 1, parse_hand("1m4m7m1p4p7p1s4s7s1z2z3z"))
    tg.set_hand(db, rid, 2, parse_hand("123m456p789s1z2z3z") + ["5m"], drawn="5m")
    tg.set_hand(db, rid, 3, parse_hand("123m456m789m111p") + ["5m"])   # 单骑 5m
    g = Game(db, rid)
    g.granted = {2: set(seat2_cards), 3: set(seat3_cards)}
    g.round_phase = "play"
    g.duel = {"by": 0, "target": 1}   # 决斗双方之外的两家受限
    g.turn, g.phase = 2, "discard"
    g.save_flags()
    return db, rid


def main() -> int:
    print("=" * 66)
    print(" 天马麻将 · 决斗：手动摸切 + 暗置牌只有压制能荣")
    print("=" * 66)

    # ① 只能打刚摸到的那张
    print("\n① 只能打刚摸到的那张（手动）")
    db, rid = make("dm1", 881)
    g = Game(db, rid)
    check("2 号位被限制", g.duel_restricted(2), True)
    st = g.state_for(2)
    disc = [a for a in st.get("legal", []) if a.get("action") == "discard"]
    check("legal 只给刚摸到的那张",
          bool(disc) and disc[0].get("tiles") == ["5m"], True)
    try:
        g.act(2, "discard", tile="1m")
        check("打别的牌要拒", False)
    except RuleError as e:
        check("打别的牌要拒", "只能摸切" in str(e))
    g = Game(db, rid)
    ev = g.act(2, "discard", tile="5m")
    check("打刚摸的那张可以", ev.get("event"), "discard")
    check("打出去的是暗置", ev.get("face_down"), True)
    row = db._row("SELECT face_down, tile FROM round_discards WHERE round_id=? "
                  "AND seat=2 ORDER BY seq DESC LIMIT 1", (rid,))
    check("牌河记录也是暗置", int(row["face_down"]), 1)

    # ② 没人持压制 → 不能荣这张暗牌，正常轮到下家
    print("\n② 没人持压制 → 谁都不能荣")
    g = Game(db, rid)
    check("没有人开鸣牌窗口", g.phase != "claim", True)
    check("轮到下家（3 号位）", g.turn, 3)

    # ③ 压制能荣这张暗牌
    print("\n③ 压制（Card03 S2）能荣暗牌")
    db2, rid2 = make("dm2", 882, seat3_cards=[3])
    g2 = Game(db2, rid2)
    g2.act(2, "discard", tile="5m")
    g2 = Game(db2, rid2)
    check("开出了鸣牌窗口", g2.phase, "claim")
    opts = (g2.pending or {}).get("options") or {}
    check("只有 3 号位有选项", list(opts.keys()), [3])
    check("选项是荣和", (opts.get(3) or [{}])[0].get("action"), "ron")

    # ④ 决斗家摸牌后能发动技能（钓鱼）
    print("\n④ 决斗家摸牌后能发动技能")
    db3, rid3 = make("dm3", 883, seat2_cards=[5])
    g3 = Game(db3, rid3)
    g3 = Game(db3, rid3)
    g3.card05_counter[2] = 1
    g3.save_flags()
    g3 = Game(db3, rid3)
    r = g3.card05_extra_activate(2)
    check("决斗家摸牌后能发动技能（策略段3）", bool(r.get("extra")), True)

    # ⑤ 转移机制：副露 / 立直 / 技能
    print("\n⑤ 决斗对象转移")
    db4, rid4 = make("dm4", 884)
    g4 = Game(db4, rid4)
    check("初始目标是 1", int((g4.duel or {}).get("target", -1)), 1)
    check("2 号位受限", g4.duel_restricted(2), True)
    g4.duel_retarget(2)
    g4 = Game(db4, rid4)
    check("2 号位发动技能/副露/立直 → 目标转到他",
          int((g4.duel or {}).get("target", -1)), 2)
    check("发起者 0 号位不变", int((g4.duel or {}).get("by", -1)), 0)
    check("转过之后 2 号位不再受限", g4.duel_restricted(2), False)
    check("3 号位仍然受限", g4.duel_restricted(3), True)

    print("\n" + "=" * 66)
    print(f" 通过 {PASS} / 失败 {FAIL}")
    print("=" * 66)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
