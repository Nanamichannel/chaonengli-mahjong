# -*- coding: utf-8 -*-
"""Card46 S1【恶听】自测。

跑法：cd N:\\apps\\tianma\\server; python test_card46.py

口径（2026-10-28 用户）：
  切牌前，若能打出一张牌后听牌、且待牌在「他家未副露手牌 / 牌河暗置牌 / 没摸的牌山（含王牌）」
  里**一共只剩 1 张**，就能发动；那张就是铳张，结算点数按它算。
  切哪张牌仍然**自己手动选**（客户端弹面板）。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from game import Game, RuleError                  # noqa: E402
import api_cli                                     # noqa: E402
import skills                                      # noqa: E402
import test_card30 as t30                          # noqa: E402
import test_game as tg                             # noqa: E402
from tiles import parse_hand                       # noqa: E402

PASS = FAIL = 0
# 14 张：手里 123m456m789m234p5s + 刚摸 9s → 打 9s 听 5s（单骑）；打 5s 听 9s
H14 = "123m456m789m234p5s9s"
H1 = "123m456p123s5s5z5z1z"       # 下家手里有 1 张 5s（注意别混进 9s）
H1_NO5 = "123m456p123s2z5z5z1z"   # 下家手里没有 5s
H2 = "123m456p123s6z6z1z2z"
H3 = "123m456p123s7z7z3z4z"


def check(name, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  got {got!r} want {want!r}")


def err_of(fn, *a, **kw):
    try:
        fn(*a, **kw)
        return ""
    except RuleError as e:
        return str(e)


def clean_wall(db, rid, kinds=("5s", "0s", "9s")):
    """把牌山里这些牌种换成 7z —— 好精确控制「隐藏区还剩几张」。"""
    with db.tx():
        for t in kinds:
            db.conn.execute("UPDATE round_wall SET tile='7z' WHERE round_id=? AND tile=?",
                            (rid, t))


def put_wall(db, rid, tile, dead=False):
    """往牌山塞一张指定牌；dead=True → 变成王牌（zone='dead', draw_no=NULL）。"""
    seq = db._one("SELECT MIN(seq) FROM round_wall WHERE round_id=? AND zone='live' "
                  "AND dealt_to IS NULL", (rid,))
    with db.tx():
        if dead:
            db.conn.execute(
                "UPDATE round_wall SET tile=?, zone='dead', draw_no=NULL "
                "WHERE round_id=? AND seq=?", (tile, rid, int(seq)))
        else:
            db.conn.execute("UPDATE round_wall SET tile=? WHERE round_id=? AND seq=?",
                            (tile, rid, int(seq)))
    return int(seq)


def setup(tag, holders=(0,), h1=H1):
    db, rid = t30.setup(tag, card=46)
    tg.set_hand(db, rid, 0, parse_hand(H14), drawn="9s")
    tg.set_hand(db, rid, 1, parse_hand(h1))
    tg.set_hand(db, rid, 2, parse_hand(H2))
    tg.set_hand(db, rid, 3, parse_hand(H3))
    with db.tx():
        db.conn.execute("DELETE FROM round_dora WHERE round_id=?", (rid,))
        db.conn.execute("DELETE FROM round_discards WHERE round_id=?", (rid,))
        db.conn.execute("DELETE FROM round_melds WHERE round_id=?", (rid,))
        db.conn.execute("DELETE FROM round_riichi WHERE round_id=?", (rid,))
    clean_wall(db, rid)                    # 牌山里不留 5s / 9s
    g = Game(db, rid)
    g.granted = {int(x): {46} for x in holders}
    g.round_phase = "play"
    g.phase = "discard"
    g.turn = 0
    g.deal_wait = set()
    g.deal_used = set()
    g.save_flags()
    return db, rid


def main() -> int:
    print("=" * 78)
    print(" Card46 S1【恶听】")
    print("=" * 78)

    print("\n① 注册 / 时机")
    check("名字", skills.info(46, 1).get("name"), "恶听")
    check("时机 = 切牌", skills.timing(46, 1), "discard")

    print("\n② 条件：待牌在隐藏区「正好 1 张」")
    db, rid = setup("c46a")
    g = Game(db, rid)
    check("隐藏区 5s 只有 1 张（下家手里）", g._c46_hidden_counts(0).get("5s", 0), 1)
    check("隐藏区 9s = 0 张", g._c46_hidden_counts(0).get("9s", 0), 0)
    check("能发动", g.c46s1_can(0), True)
    check("候选只有 9s（打 5s 听 9s，但 9s 已没了）", g.c46s1_tiles(0), ["9s"])
    check("打 9s 之后听 5s", g.c46s1_waits(0, "9s"), ["5s"])
    check("铳张 = 5s", g.c46s1_only(0, "9s"), "5s")
    check("打 5s 不算（9s 剩 0 张）", g.c46s1_only(0, "5s"), "")
    st = g.state_for(0)
    check("state.c46.tiles", (st.get("c46") or {}).get("tiles"), ["9s"])

    print("\n③ 剩 2 张 → 不能发动")
    db2, rid2 = setup("c46b")
    put_wall(db2, rid2, "5s")              # 牌山里再多一张 5s → 共 2 张
    g2 = Game(db2, rid2)
    check("隐藏区 5s = 2 张", g2._c46_hidden_counts(0).get("5s", 0), 2)
    check("候选为空", g2.c46s1_tiles(0), [])
    check("不能发动", g2.c46s1_can(0), False)

    print("\n④ 王牌也算：铳张在王牌里 → 还能发动（按自摸结算）")
    db3, rid3 = setup("c46c", h1=H1_NO5)
    put_wall(db3, rid3, "5s", dead=True)
    g3 = Game(db3, rid3)
    check("隐藏区 5s = 1 张（在王牌）", g3._c46_hidden_counts(0).get("5s", 0), 1)
    check("能发动", g3.c46s1_can(0), True)
    out3 = g3.c46s1_apply(0, "9s")
    check("事件 = 等自摸", str(out3.get("event", "")), "c46_pending")
    check("铳张是 5s", str(out3.get("tile", "")), "5s")
    g3b = Game(db3, rid3)
    check("不自动自摸", bool(g3b.result), False)
    check("只给「自摸」按钮", [a.get("action") for a in g3b.legal_actions(0)], ["tsumo"])
    g3b.act(0, "tsumo")                    # ← 玩家点「自摸」
    g3c = Game(db3, rid3)
    check("点了才结算成自摸", (g3c.result or {}).get("result"), "tsumo")
    check("有得点", int((g3c.result or {}).get("points", 0)) > 0, True)

    print("\n⑤ 牌河暗置牌也算")
    db4, rid4 = setup("c46d", h1=H1_NO5)
    with db4.tx():
        db4.conn.execute(
            "INSERT INTO round_discards(round_id, seq, seat, wall_seq, tile, is_tsumogiri, "
            "is_riichi_tile, face_down) VALUES(?,900,2,999,'5s',0,0,1)", (rid4,))
    g4 = Game(db4, rid4)
    check("隐藏区 5s = 1 张（暗置牌）", g4._c46_hidden_counts(0).get("5s", 0), 1)
    check("能发动", g4.c46s1_can(0), True)
    check("铳张 = 5s", g4.c46s1_only(0, "9s"), "5s")

    print("\n⑥ 一定和牌（荣和）：下家有铳张 → 点自摸才结算，点数按这张算")
    out = g.c46s1_apply(0, "9s")
    check("事件 = 等自摸", str(out.get("event", "")), "c46_pending")
    check("铳张就是那张 5s", str(out.get("tile", "")), "5s")
    g5 = Game(db, rid)
    check("不自动结算", bool(g5.result), False)
    check("只给「自摸」按钮", [a.get("action") for a in g5.legal_actions(0)], ["tsumo"])
    g5.act(0, "tsumo")                     # ← 玩家点「自摸」
    g5 = Game(db, rid)
    res = g5.result or {}
    check("放铳的是下家", res.get("loser"), 1)
    check("结算类型 = 荣和", res.get("result"), "ron")
    check("赢家是我", int(res.get("winner", -1)), 0)
    check("放铳的是下家", res.get("loser"), 1)
    check("有役", bool(res.get("yaku")), True)
    row = db._row("SELECT tile FROM round_discards WHERE round_id=? AND seat=0", (rid,))
    check("打出的就是我选的那张", str((row or {}).get("tile", "")), "9s")
    check("技能用掉了", g5.skill_used(0, 46, 1), True)

    print("\n⑥b 再点一次技能图标 = 取消（这次不和，轮到下家）")
    db7, rid7 = setup("c46g")
    g7 = Game(db7, rid7)
    out7 = g7.c46s1_apply(0, "9s")
    check("先挂上待办", str(out7.get("event", "")), "c46_pending")
    g7b = Game(db7, rid7)
    check("state 里有 win_pending", (g7b.state_for(0).get("win_pending") or {}).get("card"), 46)
    c7 = g7b.skill_cancel(0, "c46s1")
    check("取消成功", bool(c7.get("cancelled")), True)
    g7c = Game(db7, rid7)
    check("待办清掉", g7c.win_pending, None)
    check("没有结算", bool(g7c.result), False)
    check("轮到下家", (-1 if g7c.turn is None else int(g7c.turn)), 1)
    row7 = db7._row("SELECT tile FROM round_discards WHERE round_id=? AND seat=0", (rid7,))
    check("切出去的牌留在牌河", str((row7 or {}).get("tile", "")), "9s")

    print("\n⑦ 不能重复发动 / 立直后不能发动")
    check("一次", g5.c46s1_can(0), False)
    db6, rid6 = setup("c46e")
    with db6.tx():
        db6.conn.execute("INSERT INTO round_riichi(round_id, seat, declared_seq, ippatsu)"
                         " VALUES(?,0,0,0)", (rid6,))
    check("立直后不能发动", Game(db6, rid6).c46s1_can(0), False)

    print("\n⑧ 选错的牌被拒")
    check("不是候选的牌", err_of(g5.c46s1_apply, 0, "1m") != "", True)

    print("\n⑨ op 层登记")
    check("OPS 里有 c46s1_apply", "c46s1_apply" in api_cli.OPS, True)
    check("卡号/技能号登记", api_cli._SKILL_OP_PAIRS.get("c46s1_apply"), (46, 1))
    check("要问看破", "c46s1_apply" in api_cli._NO_GATE_OPS, False)

    print("\n" + "=" * 78)
    print(f" 合计：{PASS + FAIL} 断言，{FAIL} 失败")
    print("=" * 78)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
