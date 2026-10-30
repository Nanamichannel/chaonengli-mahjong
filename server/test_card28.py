# -*- coding: utf-8 -*-
"""Card28 S1【满贯】+ S2【蜕变】自测

用户口径（2026-10-27）：
· 结算分两条链：【番数链】按卡序（主战→协战），【得点链】固定顺序（自信→多面→暖气），
  番数链整体先于得点链。
· 【蜕变】：>30符2番 且 <满贯 → 满贯；满贯→跳满；跳满→倍满；倍满→三倍满；
  三倍满→役满；役满不升。升上去按该档位**最小番**计入。
· 【满贯】：本局任何人和牌，番数结算不到满贯 → 不结算（按钮直接不出现）。
  渣和对它特化（无视）。

跑法：cd N:\apps\tianma\server; python test_card28.py
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from game import Game                        # noqa: E402
import skills                                # noqa: E402
from rules import score                      # noqa: E402
import test_game as tg                       # noqa: E402
from tiles import parse_hand                 # noqa: E402

PASS = FAIL = 0

# 0 号位：14 张，刚摸 8s → 123m456m789m 5p5p 678s（一气+平和 = 3 番，20 符）
WIN_HAND = "123m456m789m5p5p6s7s8s"
WIN_TILE = "8s"
# 0 号位（副露版）：碰 1p + 234m 567m 234s 99s → 无役（门清都没有）
DAWA_HAND = "234m567m234s99s"
DAWA_TILE = "9s"
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


def setup(tag, mains=(28, 3, 6, 7), sups=(1, 1, 1, 1),
          hand=None, drawn=None, pon_1p=False):
    """四家卡序：seat0 的主战/协战由参数给（用来测卡序）。"""
    db = tg.fresh_db(tag)
    rid, _m, _u = tg.new_round(db, seed=113)
    for s, h in enumerate(((hand or WIN_HAND), H1, H2, H3)):
        tg.set_hand(db, rid, s, parse_hand(h), drawn=(drawn if s == 0 else None))
    orders = [[mains[s], 1, 2, 3, sups[s]] for s in range(4)]
    with db.tx():
        db.conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES('lobby_state', ?)",
            (json.dumps({"seats": [{"order": o} for o in orders]},
                        ensure_ascii=False),))
    # 宝牌指示牌清空：牌山按 tag 不同，手上可能白捡宝牌 → 番数不固定。
    with db.tx():
        db.conn.execute("DELETE FROM round_dora WHERE round_id=?", (rid,))
    # 先给 0 号位塞一张「已经打过的牌」：否则他满足「天和」条件（役满），
    # 会把要测的番数全顶掉。
    with db.tx():
        db.conn.execute(
            "INSERT INTO round_discards(round_id, seq, seat, wall_seq, tile,"
            " is_tsumogiri, is_riichi_tile, face_down, called)"
            " VALUES(?,900,0,901,'1z',1,0,0,0)", (rid,))
    if pon_1p:
        with db.tx():
            db.conn.execute(
                "INSERT INTO round_melds(round_id,meld_id,seat,kind,called_tile,from_seat,"
                "tiles_json,rot_index) VALUES(?,0,0,'pon','1p',3,"
                "'[\"1p\",\"1p\",\"1p\"]',0)", (rid,))
    g = Game(db, rid)
    g.granted = {s: {mains[s], sups[s]} for s in range(4)}
    g.round_phase = "play"
    g.turn, g.phase = 0, "discard"
    g.save_flags()
    return db, rid


def settle(g, seat, tile, tsumo=True):
    """跑一遍完整结算链（不落账）"""
    res = g._judge_win(seat, tile, tsumo=tsumo)
    if res is None:
        return None
    return g.settle_preview(seat, None, "tsumo" if tsumo else "ron",
                            res, dry_run=True)


def main() -> int:
    print("=" * 78)
    print(" Card28 S1【满贯】+ S2【蜕变】")
    print("=" * 78)

    # ── ① 注册 ────────────────────────────────────────────────────
    print("\n① 注册")
    check("S1 名字", skills.info(28, 1).get("name"), "满贯")
    check("S2 名字", skills.info(28, 2).get("name"), "蜕变")
    check("S1 时机 = 配牌", skills.timing(28, 1), "deal")
    check("S2 时机 = 结算", skills.timing(28, 2), "settle")
    check("蜕变不在配牌窗口", (28, 2) in skills.deal_skills(), False)
    check("满贯在配牌窗口", (28, 1) in skills.deal_skills(), True)

    # ── ② 档位表 ──────────────────────────────────────────────────
    print("\n② score.next_tier（升档 + 最小番）")
    check("3番30符 → 满贯(5)", score.next_tier(3, 30), (5, 2000, "满贯"))
    check("满贯 → 跳满(6)", score.next_tier(5, 30), (6, 3000, "跳满"))
    check("跳满 → 倍满(8)", score.next_tier(6, 30), (8, 4000, "倍满"))
    check("倍满 → 三倍满(11)", score.next_tier(8, 30), (11, 6000, "三倍满"))
    check("三倍满 → 役满", score.next_tier(11, 30), (13, 8000, "役满"))
    check("4番40符（点数满贯）→ 跳满", score.next_tier(4, 40), (6, 3000, "跳满"))
    check("2番30符（等于阈值）不升", score.next_tier(2, 30), None)
    check("1番30符 不升", score.next_tier(1, 30), None)
    check("役满不升", score.next_tier(14, 30), None)

    # ── ③ 例子 1：蜕变 主战 + 自信 协战 ───────────────────────────
    print("\n③ 主战【蜕变】+ 协战【自信】：3番 → 满贯(5) → ×2 = 10 番（倍满）")
    db, rid = setup("c28a", mains=(28, 6, 6, 7), sups=(3, 1, 1, 1),
                    hand=WIN_HAND, drawn=WIN_TILE)
    g = Game(db, rid)
    g.confident = {0}
    g.save_flags()
    g = Game(db, rid)
    check("卡序 = 主战 28 → 协战 3", skills.cards_in_order(db, g, 0), [28, 3])
    base = g._judge_win(0, WIN_TILE, tsumo=True)
    # 门清自摸和 1 + 平和 1 + 一气通贯 2 = 4 番 20 符
    check("判番 = 4 番 20 符", (int(base["han"]), int(base["fu"])), (4, 20))
    res = settle(g, 0, WIN_TILE)
    check("蜕变 → 满贯 5 番，自信 ×2 → 10 番", int(res["han"]) if res else None, 10)
    if res:
        check("基本点 = 4000（倍满）", int(res["pays"]["basic"]), 4000)
        check("役种里有蜕变", any("蜕变" in y["name"] for y in res["yaku"]), True)

    # 对照：主战/协战对调 —— 蜕变仍在番数链、自信在得点链，结果一样
    db1b, rid1b = setup("c28a2", mains=(3, 6, 6, 7), sups=(28, 1, 1, 1),
                        hand=WIN_HAND, drawn=WIN_TILE)
    g1b = Game(db1b, rid1b)
    g1b.confident = {0}
    g1b.save_flags()
    g1b = Game(db1b, rid1b)
    check("对调后卡序", skills.cards_in_order(db1b, g1b, 0), [3, 28])
    res1b = settle(g1b, 0, WIN_TILE)
    check("（番数链先于得点链）结果仍是 10 番",
          int(res1b["han"]) if res1b else None, 10)

    # ── ④ 渣和 × 自信（A 方案：自信在得点链，永远看得到 1 番）──────
    print("\n④ 副露无役 + 【渣和】+【自信】：1 番 30 符 → 2 番 30 符")
    db2, rid2 = setup("c28b", mains=(13, 6, 6, 7), sups=(3, 1, 1, 1),
                      hand=DAWA_HAND, drawn=DAWA_TILE, pon_1p=True)
    g2 = Game(db2, rid2)
    g2.confident = {0}
    g2.save_flags()
    g2 = Game(db2, rid2)
    r2 = settle(g2, 0, DAWA_TILE)
    check("渣和 + 自信 → 2 番", int(r2["han"]) if r2 else None, 2)
    check("30 符", int(r2["fu"]) if r2 else None, 30)
    check("标了 dawa", bool(r2.get("dawa")) if r2 else None, True)

    # ── ⑤ 满贯拦截：番数不到满贯 → 按钮不出现 ────────────────────
    print("\n⑤ 【满贯】：番数不到满贯 → 自摸按钮不出现")
    db3, rid3 = setup("c28c", mains=(6, 6, 6, 7), hand=WIN_HAND, drawn=WIN_TILE)
    g3 = Game(db3, rid3)
    acts0 = [a["action"] for a in g3.legal_actions(0)]
    check("（没开满贯）4 番 → 有自摸", "tsumo" in acts0, True)
    g3.c28s1_on = {1}                       # 别家发动了满贯
    g3.save_flags()
    g3 = Game(db3, rid3)
    check("满贯开着 + 4 番20符（不到满贯）→ 没有自摸", "tsumo" in
          [a["action"] for a in g3.legal_actions(0)], False)
    check("_c28s1_blocks(4番20符)", g3._c28s1_blocks(settle(g3, 0, WIN_TILE)), True)

    # 但【蜕变】能把 3 番抬到满贯 → 按钮又出来了（预测跑了完整链）
    db4, rid4 = setup("c28d", mains=(28, 6, 6, 7), hand=WIN_HAND, drawn=WIN_TILE)
    g4 = Game(db4, rid4)
    g4.c28s1_on = {1}
    g4.save_flags()
    g4 = Game(db4, rid4)
    check("蜕变把 4 番抬成满贯 → 满贯拦截放行",
          "tsumo" in [a["action"] for a in g4.legal_actions(0)], True)

    # 段位判定：点数满贯也算
    check("4番40符 算满贯 → 放行", g4._c28s1_blocks({"han": 4, "fu": 40}), False)
    check("3番70符 算满贯 → 放行", g4._c28s1_blocks({"han": 3, "fu": 70}), False)
    check("3番30符 → 拦", g4._c28s1_blocks({"han": 3, "fu": 30}), True)
    check("6番 → 放行", g4._c28s1_blocks({"han": 6, "fu": 30}), False)
    check("役满 → 放行", g4._c28s1_blocks({"han": 13, "fu": 30, "yakuman": 1}), False)
    check("渣和特化：1番30符 也放行",
          g4._c28s1_blocks({"han": 1, "fu": 30, "dawa": True}), False)
    check("多面/暖气的放大救不了 3 番",
          g4._c28s1_blocks({"han": 3, "fu": 30, "pays": {"basic": 2880}}), True)

    # ── ⑥ 配牌发动 ────────────────────────────────────────────────
    print("\n⑥ 配牌点【满贯】")
    db5, rid5 = setup("c28e", mains=(28, 6, 6, 7))
    g5 = Game(db5, rid5)
    g5.phase = "deal_skill"
    g5.deal_wait = {0}
    g5.deal_used = set()
    g5.save_flags()
    g5 = Game(db5, rid5)
    g5.phase = "deal_skill"
    g5.deal_wait = {0}
    opts5 = [(o["card"], o["skill"]) for o in g5._deal_skill_options(0)]
    check("配牌窗口里有 (28,1)", (28, 1) in opts5, True)
    r5 = g5.deal_action(0, "use", 28, 1)
    check("发动成功", bool(r5.get("armed")), True)
    g5b = Game(db5, rid5)
    check("本局开着（落库了）", 0 in g5b.c28s1_on, True)
    check("state 里有 c28s1_on", bool(g5b.state_for(0).get("c28s1_on")), True)
    check("全桌都知道满贯开着", bool(g5b.state_for(2).get("c28s1_any")), True)
    check("本小局不能用第二次", g5b.skill_used(0, 28, 1), True)

    print("\n" + "=" * 78)
    print(f" 通过 {PASS} / 失败 {FAIL}")
    print("=" * 78)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
