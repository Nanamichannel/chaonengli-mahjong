# -*- coding: utf-8 -*-
"""Card43 S1【NO MISS】自测。

跑法：cd N:\\apps\\tianma\\server; python test_card43.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from game import Game, RuleError, is_taatsu          # noqa: E402
import skills                                        # noqa: E402
import test_card30 as t30                            # noqa: E402
import test_game as tg                               # noqa: E402
from tiles import parse_hand                         # noqa: E402

PASS = FAIL = 0
# 3 面子 + 23p + 55s + 9s；把 23p 换成牌河的 7s8s → 123m456m789m 789s 55s
H0 = "123m456m789m2p3p5s5s9s"


def check(name, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  got {got!r} want {want!r}")


def setup(tag, river=("7s", "8s"), face_down=False):
    db, rid = t30.setup(tag, card=43, mains=[43, 6, 7, 8])
    tg.set_hand(db, rid, 0, parse_hand(H0), drawn="9s")
    with db.tx():
        db.conn.execute("DELETE FROM round_dora WHERE round_id=?", (rid,))
        db.conn.execute("DELETE FROM round_discards WHERE round_id=?", (rid,))
        db.conn.execute("DELETE FROM round_melds WHERE round_id=?", (rid,))
        for i, t in enumerate(river):
            db.conn.execute(
                "INSERT INTO round_discards(round_id, seq, seat, wall_seq, tile, "
                "is_tsumogiri, is_riichi_tile, face_down, is_nuki) "
                "VALUES(?,?,?,?,?,0,0,?,0)",
                (rid, i, 1 + i % 3, 9000 + i, t, 1 if face_down else 0))
    g = Game(db, rid)
    g.granted = {0: {43}}
    g.round_phase = "play"
    g.phase = "discard"
    g.turn = 0
    g.deal_wait = set()
    g.deal_used = set()
    g.save_flags()
    return db, rid


def river_seqs(db, rid):
    return [int(r["seq"]) for r in db._rows(
        "SELECT seq FROM round_discards WHERE round_id=? ORDER BY seq", (rid,))]


def main() -> int:
    print("=" * 78)
    print(" Card43 S1【NO MISS】")
    print("=" * 78)

    print("\n① 搭子判断函数")
    check("两面 1m2m", is_taatsu(["1m", "2m"]), True)
    check("嵌张 1m3m", is_taatsu(["1m", "3m"]), True)
    check("边张 1m2m（同上）", is_taatsu(["1m", "2m"]), True)
    check("对子 5s5s", is_taatsu(["5s", "5s"]), True)
    check("字牌成对", is_taatsu(["bai", "bai"]), True)
    check("字牌不同", is_taatsu(["bai", "fa"]), False)
    check("差 3 张不算", is_taatsu(["1m", "4m"]), False)
    check("不同花色不算", is_taatsu(["1m", "2p"]), False)
    check("三张不算", is_taatsu(["1m", "2m", "3m"]), False)
    check("9m1m 不算", is_taatsu(["9m", "1m"]), False)

    print("\n② 注册 / 时机")
    check("名字", skills.info(43, 1).get("name"), "NO MISS")
    check("时机 = 切牌", skills.timing(43, 1), "discard")

    print("\n③ 能发动：手牌有搭子 + 牌河有搭子")
    db, rid = setup("c43a")
    g = Game(db, rid)
    check("能发动", g.c43s1_can(0), True)
    check("手牌搭子能找到", ["2p", "3p"] in g._c43_hand_pairs(0), True)
    check("牌河候选 2 张", len(g.c43s1_river_seqs(0)), 2)
    st = g.state_for(0)
    check("state.c43.can", bool((st.get("c43") or {}).get("can")), True)

    print("\n④ 非搭子 → 拒绝确认")
    rs = river_seqs(db, rid)
    try:
        g.c43s1_apply(0, ["2p", "5s"], rs)          # 2p5s 不是搭子
        check("手牌非搭子被拒", False, True)
    except RuleError as e:
        check("手牌非搭子被拒", "不是搭子" in str(e), True)

    print("\n⑤ 换完成和 → 不自动自摸，弹按钮点了才结算")
    g2 = Game(db, rid)
    r = g2.c43s1_apply(0, ["2p", "3p"], rs)
    check("判定为和牌形", bool(r.get("win")), True)
    check("挂上「等自摸」待办", bool(r.get("pending")), True)
    g3 = Game(db, rid)
    check("还没结算（不自动自摸）", bool(g3.result), False)
    check("只给「自摸」按钮", [a.get("action") for a in g3.legal_actions(0)], ["tsumo"])
    check("别家没得点", int(g3.scores().get(1, 0)), 35000)
    g3.act(0, "tsumo")                     # ← 玩家点「自摸」
    g3 = Game(db, rid)
    res = g3.result or {}
    check("点了才结算成自摸", res.get("result"), "tsumo")
    names = res.get("yaku_names") or []
    # seat0 是第一巡和牌 → 会判成「天和」（役满），此时不再叠门前清自摸和
    check("按自摸判番（天和 / 门前清自摸和 其一）",
          ("天和" in names) or ("门前清自摸和" in names), True)
    check("手里拿到了 7s8s", sorted(t for t in g3.hand(0) if t in ("7s", "8s")),
          ["7s", "8s"])
    check("牌河那两张变成 2p3p",
          sorted(str(rr["tile"]) for rr in db._rows(
              "SELECT tile FROM round_discards WHERE round_id=? ORDER BY seq", (rid,))),
          ["2p", "3p"])

    print("\n⑤c 再点一次技能图标 = 取消（不结算，换过的牌保留）")
    db7, rid7 = setup("c43d")
    g7 = Game(db7, rid7)
    rs7 = river_seqs(db7, rid7)
    r7 = g7.c43s1_apply(0, ["2p", "3p"], rs7)
    check("先挂上「等自摸」", bool(r7.get("pending")), True)
    g7b = Game(db7, rid7)
    check("state 里有 win_pending", (g7b.state_for(0).get("win_pending") or {}).get("card"), 43)
    check("别人看不到", g7b.state_for(1).get("win_pending"), None)
    c7 = g7b.skill_cancel(0, "c43s1")
    check("取消成功", bool(c7.get("cancelled")), True)
    g7c = Game(db7, rid7)
    check("待办清掉", g7c.win_pending, None)
    check("没有结算", bool(g7c.result), False)
    check("回到正常打牌", [a.get("action") for a in g7c.legal_actions(0)][:1], ["discard"])
    check("换过的牌保留（手里有 7s/8s）",
          sorted(t for t in g7c.hand(0) if t in ("7s", "8s")), ["7s", "8s"])
    check("技能算用掉了", g7c.skill_used(0, 43, 1), True)

    print("\n⑤b 判番上下文：不计边坎吊的 2 符")
    dbx, ridx = setup("c43x")
    gx = Game(dbx, ridx)
    tiles = parse_hand("123m456m789m123p5s5s")
    ctx0 = gx.win_ctx(0, tiles, "2p", tsumo=True, as_tsumo=True)
    check("平时 no_edge_fu", bool(ctx0.get("no_edge_fu")), False)
    check("平时 no_wait_fu", bool(ctx0.get("no_wait_fu")), False)
    gx.c43s1_win.add(0)
    ctx1 = gx.win_ctx(0, tiles, "2p", tsumo=True, as_tsumo=True)
    check("NO MISS 时 no_edge_fu", bool(ctx1.get("no_edge_fu")), True)
    check("NO MISS 时 no_wait_fu", bool(ctx1.get("no_wait_fu")), True)
    gx.c43s1_win.discard(0)

    print("\n⑥ 不能选暗置牌")
    db2, rid2 = setup("c43b", face_down=True)
    g4 = Game(db2, rid2)
    rs2 = river_seqs(db2, rid2)
    try:
        g4.c43s1_apply(0, ["2p", "3p"], rs2)
        check("暗置牌被拒", False, True)
    except RuleError:
        # 暗置牌不进候选 → 直接判「不能发动」；总之选不中
        check("暗置牌被拒", True, True)
    check("暗置牌不在候选里", g4.c43s1_river_seqs(0), [])

    print("\n⑦ 换完不能和 → 正常继续（技能照用掉）")
    db3, rid3 = setup("c43c", river=("dong", "dong"))  # 换进一对客风，和不了
    g5 = Game(db3, rid3)
    rs3 = river_seqs(db3, rid3)
    r3 = g5.c43s1_apply(0, ["2p", "3p"], rs3)
    g6 = Game(db3, rid3)
    check("没和牌", bool(r3.get("win")), False)
    check("没有结算", bool(g6.result), False)
    check("记了一次性", g6.skill_used(0, 43, 1), True)
    check("手牌拿到一对东", [t for t in g6.hand(0) if t == "dong"], ["dong", "dong"])

    print("\n" + "=" * 78)
    print(f" 通过 {PASS} / 失败 {FAIL}")
    print("=" * 78)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
