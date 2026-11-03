# -*- coding: utf-8 -*-
"""Card24 S1「一发」自测

用户口径：
  · 摸牌后、处于「可立直」状态 → 点技能图标发动
  · 用默认方式面板选一张「打出去能立直」的手牌 → 横置打出、进入立直状态
  · 服务端读牌山 + 王牌：自己的胡张在里面 → 【一发】开启
  · 之后「立直 + 一发巡 + 轮到自己摸牌」→ 出现自摸按钮，
    按下按「一发自摸」结算（其他役种照常）；多种胡张取打点最高的

跑法：cd N:\apps\tianma\server; python test_card24s1.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from game import Game, RuleError        # noqa: E402
import test_game as tg                  # noqa: E402
from tiles import parse_hand            # noqa: E402

PASS = FAIL = 0


def check(name, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  got {got!r} want {want!r}")


def wall_live_seq(db, rid, nth=0):
    rows = db._rows("SELECT seq FROM round_wall WHERE round_id=? AND zone='live' "
                    "AND dealt_to IS NULL ORDER BY seq", (rid,))
    return int(rows[nth]["seq"])


def set_wall_kind(db, rid, seq, kind):
    with db.tx():
        db.conn.execute("UPDATE round_wall SET tile=? WHERE round_id=? AND seq=?",
                        (kind, rid, seq))


def wipe_wall_kind(db, rid, kinds, to="1z"):
    """把牌山/王牌里还没被拿走的这些牌种都改成别的（造「牌山里没有我的胡张」）"""
    q = ",".join("?" * len(kinds))
    with db.tx():
        db.conn.execute(
            "UPDATE round_wall SET tile=? WHERE round_id=? AND dealt_to IS NULL "
            "AND tile IN (%s)" % q, (to, rid, *kinds))


def setup(tag, hand13, drawn):
    """手牌 123m456m789m5p5p6s7s + 摸到 9s → 切 6s 听 8s；切 9s 听 5s/8s

    注意 tg.set_hand 只把「列表最后一张 == drawn」标成刚摸的，所以要把摸的牌接在末尾。
    """
    db = tg.fresh_db(tag)
    rid, _m, _u = tg.new_round(db, seed=71)
    tg.set_hand(db, rid, 0, list(hand13) + [drawn], drawn=drawn)
    tg.set_hand(db, rid, 1, parse_hand("1m4m7m1p4p7p1s4s7s1z2z3z"))
    tg.set_hand(db, rid, 2, parse_hand("2m5m8m2p5p8p2s5s8s2z3z4z"))
    tg.set_hand(db, rid, 3, parse_hand("3m6m9m3p6p9p3s6s9s1z2z3z"))
    g = Game(db, rid)
    g.granted = {0: {24}}
    g.round_phase = "play"
    g.turn, g.phase = 0, "discard"
    g.save_flags()
    return db, rid, Game(db, rid)


HAND = parse_hand("123m456m789m5p5p6s7s")


def main() -> int:
    print("=" * 76)
    print(" Card24 S1「一发」：立直判断 → 选牌 → 横置立直 → 牌山有胡张 → 一发自摸")
    print("=" * 76)

    # ══ ① 能不能点 ══════════════════════════════════════════════════════
    print("\n① 发动条件（摸牌后 + 可立直 + 持 24 号卡）")
    db, rid, g = setup("c24_can", HAND, "9s")
    check("能点（立直判断机通过）", g.c24_can(0))
    check("state 里 c24_can = true", g.state_for(0).get("c24_can"), True)
    check("state 里带可选牌（= 立直宣言牌）",
          sorted(g.state_for(0).get("c24_tiles") or []), ["6s", "9s"])

    g2 = Game(db, rid)
    g2.phase = "draw"                       # 还没摸牌
    check("没摸牌不能点", g2.c24_can(0), False)

    db3, rid3, g3 = setup("c24_nocard", HAND, "9s")
    g3.granted = {}
    g3.save_flags()                        # 要让「没有这张卡」落库，重新读才算数
    g3 = Game(db3, rid3)
    check("没这张卡不能点", g3.c24_can(0), False)

    # ══ ② 选错牌 ════════════════════════════════════════════════════════
    print("\n② 选一张「打出去就不听」的牌 → 拒绝")
    db4, rid4, g4 = setup("c24_bad", HAND, "9s")
    db4b = g4.db
    seq = wall_live_seq(db4b, rid4, 0)
    set_wall_kind(db4b, rid4, seq, "8s")     # 牌山里放一张 8s（我的胡张）
    try:
        g4.c24_declare(0, "1m")
        check("应该被拒", "没拒", "拒了")
    except RuleError as e:
        check("应该被拒", "拒了", "拒了")
        print("       错误信息:", e)

    # ══ ③ 正常发动：横置立直 + 一发开启 ═════════════════════════════════
    print("\n③ 切 6s 立直（听 8s），牌山里有 8s → 一发开启")
    r = g4.c24_declare(0, "6s")
    print("   返回:", {k: r.get(k) for k in ("seat", "tile", "riichi", "ippatsu_on", "wins")})
    check("记成立直", r.get("riichi"), True)
    check("牌山里有胡张 → 一发开启", r.get("ippatsu_on"), True)
    check("胡张是 8s", r.get("wins"), ["8s"])

    g5 = Game(db4b, rid4)
    check("真的进了立直状态", g5.is_riichi(0))
    d = g5.db._row("SELECT tile, is_riichi_tile FROM round_discards WHERE round_id=? "
                   "AND seat=0 ORDER BY seq DESC LIMIT 1", (rid4,))
    check("宣言牌是 6s", d["tile"], "6s")
    check("宣言牌横置（is_riichi_tile=1）", int(d["is_riichi_tile"]), 1)
    check("flags 里 c24_armed = 0", g5.c24_armed, 0)
    check("state 里 c24_armed = true", g5.state_for(0).get("c24_armed"), True)
    check("技能记账（翻卡面）", g5.skill_used(0, 24, 1))

    # ══ ④ 一发巡摸牌 → 出现自摸按钮 → 一发自摸结算 ═══════════════════════
    print("\n④ 下一巡摸牌（摸到一张无关的牌）→ 自摸按钮 → 一发自摸")
    dseq = wall_live_seq(db4b, rid4, 0)
    set_wall_kind(db4b, rid4, dseq, "dong")          # 摸到的这张：东风（和不了）
    g6 = Game(db4b, rid4)
    g6.db.draw_seq(rid4, 0, dseq, "dong", drawn=True)
    g6.turn, g6.phase = 0, "discard"
    g6.save_flags()
    g6 = Game(db4b, rid4)
    check("摸到的是一张和不了的牌", g6.drawn_tile(0), "dong")
    check("一发不再提供「直接和」窗口（改成提前换位）", g6.c24_win_can(0), False)
    acts = [a.get("action") for a in g6.legal_actions(0)]
    check("不再强塞自摸按钮", "tsumo" in acts, False)
    check("一发巡还在（没被误清）", 0 in g6.ippatsu)

    # 2026-11-03 规则：一发不再「改写摸到的牌 + 绕过判定」。
    # 发动时已经把和的牌换到「一发巡要摸的那张」位置，摸到走正常自摸判定。
    g7 = Game(db4b, rid4)
    check("本局没有因为一发被强行结算", bool(g7.result), False)

    # ══ ⑤ 牌山里没有胡张 → 立直了，但没有一发 ═══════════════════════════
    print("\n⑤ 牌山/王牌里没有 8s → 一发不开启（只是普通立直）")
    db8, rid8, g8 = setup("c24_nowin", HAND, "9s")
    wipe_wall_kind(g8.db, rid8, ["8s", "5s", "0s"])
    g8 = Game(db8, rid8)
    r8 = g8.c24_declare(0, "6s")
    check("仍然立直", r8.get("riichi"), True)
    check("一发没开启", r8.get("ippatsu_on"), False)
    check("胡张列表为空", r8.get("wins"), [])
    g9 = Game(db8, rid8)
    check("flags c24_armed = -1", g9.c24_armed, -1)
    check("c24_win_can = false", g9.c24_win_can(0), False)

    print("\n" + "=" * 76)
    print(f" 结果：{PASS} 项通过，{FAIL} 项失败")
    print("=" * 76)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
