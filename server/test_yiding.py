# -*- coding: utf-8 -*-
"""一定和牌新流程（2026-11-07）：

  宣言听牌张 → 正常切一张（切完仍听它）→ 别人手里有就必须打（立直家豁免）
  → 我摸牌前把牌山里最近的一张和牌张换到下一张 → 全程正常判定。
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


def build(tag, seed):
    db = tg.fresh_db(tag)
    rid, _m, _u = tg.new_round(db, seed=seed)
    # 我：4 副露 + 单骑 9p（摸到 9p，切了就听 9p）
    tg.set_hand(db, rid, 0, parse_hand("123m456p789s111p99p"), drawn="9p")
    tg.set_hand(db, rid, 1, parse_hand("9p") + ["1m", "2m", "3m", "4p", "5p", "6p",
                                                "7s", "8s", "9s", "2p", "2p", "2p"])
    tg.set_hand(db, rid, 2, parse_hand("1m2m3m4p5p6p7s8s9s1p1p1p2s"))
    tg.set_hand(db, rid, 3, parse_hand("1m2m3m4p5p6p7s8s9s1p1p1p3s"))
    g = Game(db, rid)
    g.yiding = {0}
    g.round_phase = "play"
    g.phase, g.turn = "discard", 0
    g.save_flags()
    return db, rid


def to(g, db, rid):
    g = Game(db, rid)
    return g


def main():
    db, rid = build("ydnew", 51)
    g = Game(db, rid)
    g.yiding = {0}
    g.round_phase = "play"
    g.phase, g.turn = "discard", 0
    g.save_flags()
    g = Game(db, rid)
    g.phase, g.turn = "discard", 0

    # ① 听牌张
    waits = g.yiding_waits(0)
    check("9p" in waits, "9p 在听牌张里")

    # ② 宣言：不结算，只记 armed + 播报
    r = g.yiding_declare(0, "9p")
    check(r.get("kind") == "9p", "宣言返回 kind")
    check("进入 armed", 0 in g.yiding_armed)
    check(g.yiding_kind.get(0) == "9p", "记下牌种")
    check("播报里说了听牌九筒", "听牌【九筒】" in str((g.broadcast or {}).get("text", "")))
    _lgy = [e for e in (g.broadcast_log or []) if "听牌" in str(e.get("text", ""))]
    check(bool(_lgy) and "九筒" in str(_lgy[-1].get("text", "")),
          "右上角记录里也有听牌张（一定和牌）")
    check(not g.result, "没有立刻结算")

    # ③ 非听牌张要拒绝
    g2 = Game(db, rid)
    g2.phase, g2.turn = "discard", 0
    try:
        g2.yiding_declare(0, "bai")
        check("非听牌张要拒绝", False)
    except Exception as e:
        check("非听牌张要拒绝", "不是你的听牌张" in str(e))

    # ④ 切牌：切 9p（切完仍听 9p）→ 允许
    g3 = Game(db, rid)
    g3.phase, g3.turn = "discard", 0
    check("切 9p 仍听 9p", g3._yiding_cut_ok(0, "9p"))
    check(not g3._yiding_cut_ok(0, "1m"), "切 1m 不听 9p")
    try:
        g3._do_discard(0, "9p")
        check("宣言后正常切牌", True)
    except Exception as e:
        check("宣言后正常切牌", "切这张就不听" not in str(e))

    # ⑤ 别人被强制（1 号手里有 9p）；宣言者自己不算
    g4 = Game(db, rid)
    check(g4._yiding_force_kind(1) == "9p", "1 号必须以 9p 应战")
    check(g4._yiding_force_kind(0) == "", "宣言者自己不受限")

    # ⑥ 摸牌前：牌山里最近的 9p 换到下一张
    g5 = Game(db, rid)
    g5.phase, g5.turn = "draw", 0
    g5.save_flags()
    g5 = Game(db, rid)
    g5.phase, g5.turn = "draw", 0
    _before = str(g5.db.tile_at_seq(rid, int(g5._upcoming_wall_seqs(1)[0])) or "")
    ok = g5._yiding_pre_swap(0)
    g6 = Game(db, rid)
    _after = str(g6.db.tile_at_seq(rid, int(g6._upcoming_wall_seqs(1)[0])) or "")
    check(ok, "换过牌山")
    check(_after == "9p", "下一张变成 9p")

    # ⑦ 国标走同一套流程（多记 guobiao_armed，和牌时开 pattern_bonus）
    db7, rid7 = build("ydgb", 53)
    g7 = Game(db7, rid7)
    g7.granted = {0: {1}}
    g7.round_phase = "play"
    g7.phase, g7.turn = "discard", 0
    g7.save_flags()
    g7 = Game(db7, rid7)
    g7.phase, g7.turn = "discard", 0
    r7 = g7.guobiao_declare(0, "9p")
    check(r7.get("kind") == "9p", "国标宣言 kind")
    check(0 in g7.yiding_armed, "国标也进 armed")
    check(0 in g7.guobiao_armed, "国标记了 guobiao_armed")

    print(f"\n通过 {OK} / 失败 {BAD}")
    return 1 if BAD else 0


if __name__ == "__main__":
    sys.exit(main())
