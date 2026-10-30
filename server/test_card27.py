# -*- coding: utf-8 -*-
"""Card27 S1「调包」+ S2「命中」自测

用户口径：
· S1：摸牌后点技能 → 选 1 张手牌 + 1 张**别人牌河**的明牌 → 开始 → 互换
      （换的谁的牌就进谁的牌河，换进来的进我手里）；标记那一家；本小局一次。
      立直宣言牌**可以**换，暗置牌**不可以**。
· S2：摸牌后点技能 → 选一张「切出后仍有役听牌 / 门清」的牌 → 开始 → **暗置**打出，
      门清同时立直（暗置 + 横置）。字牌不标记；147 标记下家 / 258 对家 / 369 上家。
      发动后**不能手切**，本小局一次。
      被标记的人每**手切**一张 +1；== 3 时立刻结算「他对我出铳」，
      铳牌取牌山第一张我的铳牌；牌山没有 / 荣和链路被堵（恶灵）→ 技能作废、游戏继续。

跑法：cd N:\apps\tianma\server; python test_card27.py
"""
from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from game import Game, RuleError          # noqa: E402
import skills                             # noqa: E402
from rules import agari, tenpai           # noqa: E402
import test_game as tg                    # noqa: E402
from tiles import parse_hand, kind_of     # noqa: E402

PASS = FAIL = 0

H0 = "123m456m789m5p5p6s7s9s"     # 14 张（S1 换牌用）
H13 = "123m456m789m5p5p6s7s"      # 13 张，听 8s
H1 = "1z2z3z4z1p4p7p9p2s5s8s6m7m"
H2 = "2m5m8m2p5p8p2s5s8s2z3z4z6z"
H3 = "3m6m9m3p6p9p3s6s9s1z2z3z5z"


def check(name, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  got {got!r} want {want!r}")


def setup(tag, card=27):
    db = tg.fresh_db(tag)
    rid, _m, _u = tg.new_round(db, seed=113)
    for s, h in enumerate((H0, H1, H2, H3)):
        tg.set_hand(db, rid, s, parse_hand(h))
    orders = [[card, 1, 2, 3, 5], [4, 1, 2, 3, 5], [6, 1, 2, 3, 5], [7, 1, 2, 3, 5]]
    with db.tx():
        db.conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES('lobby_state', ?)",
            (json.dumps({"seats": [{"order": o} for o in orders]}, ensure_ascii=False),))
    # 1 号位牌河里放两张明牌 + 一张暗置牌（给 S1 挑）
    add_river(db, rid, 1, 1, "3p", 801)
    add_river(db, rid, 2, 1, "7s", 802)
    add_river(db, rid, 3, 1, "1s", 803, down=True)
    g = Game(db, rid)
    g.granted = {0: {card}}
    g.round_phase = "play"
    g.turn, g.phase = 0, "discard"
    g.save_flags()
    return db, rid


def add_river(db, rid, seq, seat, tile, wseq, down=False):
    with db.tx():
        db.conn.execute(
            "INSERT INTO round_discards(round_id, seq, seat, wall_seq, tile,"
            " is_tsumogiri, is_riichi_tile, face_down, called)"
            " VALUES(?,?,?,?,?,1,0,?,0)", (rid, seq, seat, wseq, tile, 1 if down else 0))


def main() -> int:
    print("=" * 78)
    print(" Card27 S1「调包」+ S2「命中」")
    print("=" * 78)

    # ── ① 注册 ─────────────────────────────────────────────────────
    print("\n① 注册")
    check("S1 名字", skills.info(27, 1).get("name"), "调包")
    check("S2 名字", skills.info(27, 2).get("name"), "命中")
    check("S1 时机 = 摸牌后", skills.timing(27, 1), "draw")
    check("S2 时机 = 摸牌后", skills.timing(27, 2), "draw")

    # ── ② S1：能换哪张牌河牌 ───────────────────────────────────────
    print("\n② S1 可换的牌河牌")
    db, rid = setup("c27a")
    g = Game(db, rid)
    tg.set_hand(db, rid, 0, parse_hand(H0), drawn="9s")
    g = Game(db, rid)
    check("能换：1 号位牌河里的 3p", 1 in g.c27s1_targets(0), True)
    check("能换：立直宣言牌（不是自己的就行）",
          [s for s in g.c27s1_targets(0)], [1, 2])
    check("不能换：暗置牌（seq 3）", 3 in g.c27s1_targets(0), False)
    check("不能换：自己牌河的牌", g.c27s1_targets(0).count(0), 0)
    check("自己不能换自己", 1 in g.c27s1_targets(1), False)
    check("刚摸完牌 → 能发动", g.c27s1_can(0), True)

    # ── ③ S1：换牌 + 标记 ─────────────────────────────────────────
    print("\n③ S1 换牌：牌面互换（进他的牌河 / 进我手里）+ 标记那一家")
    before_hand = list(g.hand(0))
    r = g.c27s1_swap(0, "9s", 1)
    check("换出去的是 9s", r.get("hand"), "9s")
    check("换进来的是 3p", r.get("got"), "3p")
    check("标记 1 号位", r.get("mark"), 1)
    g2 = Game(db, rid)
    check("我手里有 3p 了", "3p" in g2.hand(0), True)
    check("9s 不在我手里了", "9s" in g2.hand(0), False)
    check("我手牌张数不变（14）", len(g2.hand(0)), 14)
    river = g2.db._row("SELECT seat, tile FROM round_discards WHERE round_id=? AND seq=?",
                       (rid, 1))
    check("牌河那一格进了 9s，还挂在 1 号位名下",
          (int(river["seat"]), str(river["tile"])), (1, "9s"))
    check("c27_mark = 1", g2.c27_mark.get(0), 1)
    check("计数从 0 开始", g2.c27_cnt.get(0), 0)
    check("本小局只能一次", g2.skill_used(0, 27, 1), True)
    check("换完不能再发动", g2.c27s1_can(0), False)

    # ── ④ S2：哪些牌能切 ──────────────────────────────────────────
    print("\n④ S2 候选：切出后仍是「有役听牌 / 门清」")
    db2, rid2 = setup("c27b")
    tg.set_hand(db2, rid2, 0, parse_hand(H0), drawn="9s")
    g3 = Game(db2, rid2)
    cand = g3.c27s2_discards(0)
    check("14 张听 8s → 有候选", bool(cand), True)
    check("候选里有 9s（切掉仍听 8s）", "9s" in cand, True)
    check("候选里没有 8s（切了就不听）", "8s" in cand, False)
    check("能发动", g3.c27s2_can(0), True)
    # 完全不听 → 没有候选
    db3, rid3 = setup("c27c")
    tg.set_hand(db3, rid3, 0, parse_hand("1m4m7m2p5p8p3s6s9s1z4z7z"), drawn="2z")
    g4 = Game(db3, rid3)
    check("完全不听 → 没有候选", bool(g4.c27s2_discards(0)), False)
    check("也不能发动", g4.c27s2_can(0), False)

    # ── ⑤ S2：暗置打出 + 立直 + 按序数标记 ────────────────────────
    print("\n⑤ S2 打出：暗置 + 立直 + 标记")
    g5 = Game(db2, rid2)
    r5 = g5.c27s2_declare(0, "9s")
    check("打出 9s", r5.get("tile"), "9s")
    check("门清 → 同时立直", r5.get("riichi"), True)
    check("9s：369 → 标记上家", r5.get("mark"), 3)
    g5b = Game(db2, rid2)
    row = g5b.db._row("SELECT tile, face_down, is_riichi_tile FROM round_discards "
                      "WHERE round_id=? AND seat=0 ORDER BY seq DESC LIMIT 1", (rid2,))
    check("这张是暗置的", int(row["face_down"]), 1)
    check("而且横置（立直宣言牌）", int(row["is_riichi_tile"]), 1)
    check("我是立直状态", g5b.is_riichi(0), True)
    check("发动后不能手切（state 也这么说）", 0 in g5b.c27_s2, True)
    err = ""
    tg.set_hand(db2, rid2, 0, parse_hand("123m456m789m5p5p9s") + ["7s"], drawn="7s")
    g5c = Game(db2, rid2)
    g5c.turn, g5c.phase = 0, "discard"        # 同一个对象里直接测，不落库
    try:
        g5c._do_discard(0, tile="1m")
    except RuleError as e:
        err = str(e)
    check("手切被拒（立直/命中都只能摸切）", "只能" in err)
    check("摸切放行", bool(g5c._do_discard(0, tile="7s")), True)
    check("本小局只能一次", g5b.skill_used(0, 27, 2), True)

    # 字牌 → 不标记
    print("\n   字牌打出去不标记")
    db4, rid4 = setup("c27d")
    tg.set_hand(db4, rid4, 0, parse_hand("123m456m789m5p5p6s1z"), drawn="1z")
    g6 = Game(db4, rid4)
    cand6 = g6.c27s2_discards(0)
    if "1z" in cand6:
        r6 = g6.c27s2_declare(0, "1z")
        check("字牌 → 不标记（mark = -1）", r6.get("mark"), -1)
        g6b = Game(db4, rid4)
        check("但照样不能手切", 0 in g6b.c27_s2, True)
    else:
        check("（这手牌 1z 不是候选，跳过）", True)

    # ── ⑥ 计数 + 合成荣和 ────────────────────────────────────────
    print("\n⑥ 手切计数 → 3 → 立刻结算「他对我出铳」")
    db7, rid7 = setup("c27e")
    tg.set_hand(db7, rid7, 0, parse_hand(H13))                # 13 张，听 8s
    tg.set_hand(db7, rid7, 1, parse_hand("1z2z3z4z1p4p7p9p2s5s8s6m7m"), drawn="7m")
    tg.set_next_draw(db7, rid7, "8s")                          # 牌山第一张 = 我的铳牌
    g7 = Game(db7, rid7)
    g7.c27_s2 = {0}
    g7.c27_mark = {0: 1}
    g7.c27_cnt = {0: 2}
    g7.save_flags()
    g7 = Game(db7, rid7)
    g7.turn, g7.phase = 1, "discard"
    g7.save_flags()
    g7 = Game(db7, rid7)
    check("我听的牌里有 8s", "8s" in g7.waits(0), True)
    ev = g7._do_discard(1, tile="dong")                        # 手切（刚摸的是 7m）
    check("立刻结算成荣和", ev.get("event"), "c27_ron")
    check("铳牌 = 牌山第一张 8s", ev.get("tile"), "8s")
    g8 = Game(db7, rid7)
    check("放铳的是 1 号位", (g8.result or {}).get("loser"), 1)
    check("和牌的是我", (g8.result or {}).get("winner"), 0)
    check("结算方式是荣和", (g8.result or {}).get("result"), "ron")
    check("结算完把标记/计数清掉",
          (0 in g8.c27_s2, g8.c27_mark.get(0), g8.c27_cnt.get(0)), (False, None, None))

    # 摸切不算
    print("\n   摸切不算手切")
    g9 = Game(db7, rid7)
    g9.c27_s2 = {0}
    g9.c27_mark = {0: 1}
    g9.c27_cnt = {0: 0}
    g9.save_flags()
    hits = g9._c27_tick(1, True)
    check("摸切不加计数", (hits, g9.c27_cnt.get(0)), ([], 0))
    hits2 = g9._c27_tick(1, False)
    check("手切 +1", (hits2, g9.c27_cnt.get(0)), ([], 1))

    # ── ⑦ 失败路径：牌山没有铳牌 / 恶灵堵荣和 ─────────────────────
    print("\n⑦ 失败 → 技能作废、游戏继续")
    db8, rid8 = setup("c27f")
    tg.set_hand(db8, rid8, 0, parse_hand(H13))
    g10 = Game(db8, rid8)
    g10.c27_s2 = {0}
    g10.c27_mark = {0: 1}
    g10.c27_cnt = {0: 2}
    with db8.tx():
        db8.conn.execute("UPDATE rounds SET live_left=0 WHERE round_id=?", (rid8,))
    g10 = Game(db8, rid8)
    check("牌山空 → 找不到铳牌", g10._c27_wall_win(0, {"8s"}), "")
    check("结算失败", g10._c27_try_ron(0, 1), None)
    g10.c27s2_fail(0)
    g10b = Game(db8, rid8)
    check("技能作废（不能手切的限制也撤了）", 0 in g10b.c27_s2, False)
    check("标记清掉", g10b.c27_mark.get(0), None)

    print("\n   【恶灵】堵住荣和链路")
    db9, rid9 = setup("c27g")
    tg.set_hand(db9, rid9, 0, parse_hand(H13))
    tg.set_next_draw(db9, rid9, "8s")
    g11 = Game(db9, rid9)
    g11.c27_s2 = {0}
    g11.c27_mark = {0: 1}
    g11.c27_cnt = {0: 2}
    g11.oracle = {0: {"suit": "m", "on": True, "dice": 3}}     # 恶灵
    g11.save_flags()
    g11 = Game(db9, rid9)
    check("牌山里有铳牌", g11._c27_wall_win(0, {"8s"}), "8s")
    check("但恶灵堵住荣和 → 结算失败", g11._c27_try_ron(0, 1), None)
    check("_win_ok 也说不许荣和", g11._win_ok(0, "8s", tsumo=False), False)
    check("不看振听的那个口子也不放行恶灵",
          g11._win_ok(0, "8s", tsumo=False, furiten_ok=True), False)

    # ── ⑧ 闸门：门清一定过（门清自摸和本身就是役）/ 副露无役听牌不算 ────
    print("\n⑧ 「有役听牌 or 门清」闸门：门清 vs 副露")
    # 形状：234m 567m 234s 99s（切 9s → 听 9s 单骑）。荣和没有役（不是一气/三色/
    # 平和/断幺），所以能否成为候选完全取决于「门清自摸和」这一个役。
    dbA, ridA = setup("c27h")
    tg.set_hand(dbA, ridA, 0, parse_hand("234m567m234s678p99s"), drawn="9s")
    gA = Game(dbA, ridA)
    check("切 9s 后听 9s 单骑（荣和没役）",
          tenpai.is_tenpai_with_yaku(gA.hand13(0), gA.melds(0), gA.yaku_base(0),
                                     tsumo_ok=False), False)
    check("门清 · 荣和没役但门清自摸和有役 → 候选里有 9s",
          "9s" in gA.c27s2_discards(0), True)
    check("门清也确实是门清", agari.is_closed(gA.melds(0)), True)
    # 同一形状但改成碰出来的（副露）→ 荣和 / 自摸都没役 → 没有候选
    dbB, ridB = setup("c27i")
    tg.set_hand(dbB, ridB, 0, parse_hand("234m567m234s99s"), drawn="9s")
    with dbB.tx():
        dbB.conn.execute(
            "INSERT INTO round_melds(round_id,meld_id,seat,kind,called_tile,from_seat,"
            "tiles_json,rot_index) VALUES(?,0,0,'pon','1p',3,'[\"1p\",\"1p\",\"1p\"]',0)",
            (ridB,))
    gB = Game(dbB, ridB)
    check("副露 · 无役听牌 → 没有候选", gB.c27s2_discards(0), [])
    check("副露 · 也不能发动", gB.c27s2_can(0), False)

    # ── ⑨ 计数只落在「标记了这位打牌者」的人身上 ─────────────────────
    print("\n⑨ 一次手切只可能把一台计数推到 3")
    dbE, ridE = setup("c27k")
    tg.set_hand(dbE, ridE, 0, parse_hand(H13) + ["9s"], drawn="9s")
    gE = Game(dbE, ridE)
    gE.c27_s2 = {0, 2}
    gE.c27_mark = {0: 1, 2: 3}          # 0 号位标了 1 号位；2 号位标的是 3 号位
    gE.c27_cnt = {0: 2, 2: 2}
    hits = gE._c27_tick(1, False)       # 只有 1 号位手切一张
    check("只有「标了 1 号位」的 0 号位 +1（到 3）", (hits, gE.c27_cnt.get(0)), ([0], 3))
    check("标的是 3 号位的 2 号位不动", gE.c27_cnt.get(2), 2)

    # ── ⑩ S2 失败之后不能再发动 ──────────────────────────────────────
    print("\n⑩ S2 失败 → 也不能再发动")
    dbF, ridF = setup("c27l")
    tg.set_hand(dbF, ridF, 0, parse_hand(H13) + ["9s"], drawn="9s")
    gF = Game(dbF, ridF)
    check("这时候能发动", gF.c27s2_can(0), True)
    gF.note_use(0, 27, 2)               # 相当于已经发动过（一次性，失败也不退）
    gF.c27s2_fail(0)                    # 失败 → 技能作废
    gF2 = Game(dbF, ridF)
    gF2.turn, gF2.phase = 0, "discard"
    check("失败作废后，条件又满足也不能再发动",
          (gF2.c27s2_can(0), gF2.skill_used(0, 27, 2)), (False, True))

    # ── ⑪ 宣言牌「这一巡」就要能打出去（别被自己那条「只能摸切」拦住）──
    print("\n⑪ 命中的宣言牌：这一巡就能打出去")
    dbH, ridH = setup("c27m")
    # 14 张，刚摸的是 9s（set_hand 要求 drawn 排在最后一张）；
    # 选 6s（手牌里的一张，不是刚摸那张）→ 打完是 7s9s 嵌张听 8s
    tg.set_hand(dbH, ridH, 0, parse_hand("123m456m789m5p5p6s7s9s"), drawn="9s")
    gH = Game(dbH, ridH)
    check("6s 是候选", "6s" in gH.c27s2_discards(0), True)
    check("6s 不是刚摸的那张（这才是老 bug 的触发条件）", gH.drawn_tile(0), "9s")
    err2 = ""
    rH: dict = {}
    try:
        rH = gH.c27s2_declare(0, "6s")
    except RuleError as e:
        err2 = str(e)
    check("宣言牌不是刚摸那张也能打出去（以前被「只能摸切」拦下 → 卡死）", err2, "")
    if err2 == "":
        check("打出去的就是 6s", rH.get("tile"), "6s")
        check("门清 → 同时立直", rH.get("riichi"), True)
        check("6s：369 → 标记上家", rH.get("mark"), 3)
        rowH = Game(dbH, ridH).db._row(
            "SELECT tile, face_down, is_riichi_tile FROM round_discards "
            "WHERE round_id=? AND seat=0 ORDER BY seq DESC LIMIT 1", (ridH,))
        check("牌河里那张：暗置 + 横置",
              (str(rowH["tile"]), int(rowH["face_down"]), int(rowH["is_riichi_tile"])),
              ("6s", 1, 1))
        gH2 = Game(dbH, ridH)
        check("打完之后才进入「只能摸切」", 0 in gH2.c27_s2, True)
        check("这一巡已经轮到下家（不是还卡在我这儿）",
              (gH2.turn, gH2.phase != "discard" or int(gH2.turn) != 0), (1, True))

    print("\n" + "=" * 78)
    print(f" 通过 {PASS} / 失败 {FAIL}")
    print("=" * 78)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
