# -*- coding: utf-8 -*-
"""Card18 S1【枷锁】：① 点图标 = 发动 ② 发动后看得到里宝指示牌
③ 立直和牌时为了凑上枷锁，自动删「里宝 / 一发」（删掉的不播报）

跑法：cd server; python test_card18.py
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")

from game import Game, RuleError      # noqa: E402
import test_card30 as t30             # noqa: E402
import test_game as tg                # noqa: E402
from tiles import parse_hand          # noqa: E402

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


def setup(tag, ura="4s"):
    """0 号位持 18 号卡、配牌技能窗口阶段；里宝指示牌 = ura（**还没翻开**）"""
    db, rid = t30.setup(tag, card=18)
    tg.set_hand(db, rid, 0, parse_hand("123m456p789s") + ["1p", "2p", "3s", "4s"],
                drawn="4s")
    with db.tx():
        db.conn.execute("DELETE FROM round_dora WHERE round_id=?", (rid,))
        db.conn.execute(
            "INSERT INTO round_dora(round_id, idx, kind, indicator, dora, revealed)"
            " VALUES(?,?, 'ura', ?, ?, 0)", (rid, 0, ura, "5s"))
    g = Game(db, rid)
    g.granted = {0: {18}}
    g.round_phase = "deal"
    g.phase = "deal_skill"
    g.turn = 0
    g.deal_wait = {0}
    g.deal_used = set()
    g.save_flags()
    return db, rid


def badge(yakus):
    return [(str(y.get("name")), int(y.get("han", 0))) for y in yakus]


def solo_deal(db, rid):
    """把这个座位的卡序改成「配牌技能只有枷锁」（协战 8 号卡不是配牌技能）"""
    with db.tx():
        db.conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES('lobby_state', ?)",
            (json.dumps({"phase": "playing",
                         "seats": [{"order": [18, 5, 6, 7, 8]},
                                   {"order": [1, 2, 3, 4, 5]},
                                   {"order": [1, 2, 3, 4, 5]},
                                   {"order": [1, 2, 3, 4, 5]}]},
                        ensure_ascii=False),))


def _has_bc(g, name):
    for it in (g.broadcast_log or []):
        if isinstance(it, dict) and str(it.get("name", "")) == name:
            return True
    return False


def main() -> int:
    print("=" * 76)
    print(" Card18 S1【枷锁】：点图标发动 / 看里宝 / 自动减里宝·一发")
    print("=" * 76)

    # ── ① 点图标 = 发动；发动后才看得到里宝指示牌 ────────────────────
    print("\n① 发动（配牌窗口点技能图标）")
    db, rid = setup("c18a")
    g = Game(db, rid)
    check("能发动", g.jiasuo_can(0), True)
    check("发动前看不到里宝", g.state_for(0).get("ura_peek"), [])
    r = g.jiasuo_apply(0)
    check("发动成功", bool(r.get("on")), True)
    g2 = Game(db, rid)
    check("落库：已经发动", 0 in g2.jiasuo_on, True)
    check("等定番数", g2.jiasuo_pending(0), True)
    check("state：ura_peek 有里宝指示牌", g2.state_for(0).get("ura_peek"), ["4s"])
    check("state：别人看不到", g2.state_for(1).get("ura_peek"), [])
    check("不能重复发动", g2.jiasuo_can(0), False)
    check("点图标那一步还不算结完（不置灰）", g2.skill_used(0, 18, 1), False)

    # ── ② 再定番数（第二步）──────────────────────────────────────────
    print("\n② 定番数")
    db2, rid2 = setup("c18b")
    g3 = Game(db2, rid2)
    try:
        g3.jiasuo_set(0, 3)
        check("没发动就定番数要拒", False)
    except RuleError as e:
        check("没发动就定番数要拒", "先点技能图标发动" in str(e))
    g3.jiasuo_apply(0)
    r3 = g3.jiasuo_set(0, 3)
    check("定了 3 番", r3.get("han"), 3)
    g4 = Game(db2, rid2)
    check("落库", g4.jiasuo.get(0), 3)
    check("定完就不等了", g4.jiasuo_pending(0), False)
    check("state：jiasuo_mine", g4.state_for(0).get("jiasuo_mine"), 3)
    try:
        g4.jiasuo_set(0, 5)
        check("一局只能定一次", False)
    except RuleError as e:
        check("一局只能定一次", "一次" in str(e))

    # ── ③ 配牌窗口 deal_action 走 use 也要能发动 ─────────────────────
    print("\n③ 配牌窗口 op=deal_skill use")
    db5, rid5 = setup("c18c")
    g5 = Game(db5, rid5)
    r5 = g5.deal_action(0, "use", 18, 1)
    check("armed", bool(r5.get("armed")), True)
    check("还有风神没发 → 配牌窗口继续等他", 0 in g5.deal_wait, True)
    g6 = Game(db5, rid5)
    check("落库：已发动", 0 in g6.jiasuo_on, True)
    check("等定番数", g6.jiasuo_pending(0), True)
    g5.deal_action(0, "skip")               # 剩下的风神也不发 → 窗口收掉
    g6b = Game(db5, rid5)
    check("都发完了就不再等他", 0 in g6b.deal_wait, False)

    # ── ④ 自动减番：里宝 / 一发 / 两个都减 ───────────────────────────
    print("\n④ 凑枷锁：自动删里宝 / 一发")
    db7, rid7 = setup("c18d")
    g7 = Game(db7, rid7)

    def mk(han, yakus):
        return {"han": han, "fu": 30, "yaku": [dict(y) for y in yakus]}

    Y_RIICHI = {"name": "立直", "han": 1}
    Y_IP = {"name": "一发", "han": 1}
    Y_DORA = {"name": "宝牌", "han": 2, "detail": {"宝牌": 1, "里宝牌": 1}}

    res = mk(4, [Y_RIICHI, Y_IP, Y_DORA])
    got = g7._c18_try_trim(res, 3)
    check("删里宝 1 番", got, ["里宝"])
    check("删完 = 3 番", res["han"], 3)
    check("狱宝牌条目剩 1 番", badge(res["yaku"]), [("立直", 1), ("一发", 1), ("宝牌", 1)])
    check("里宝牌清 0", res["yaku"][2]["detail"].get("里宝牌"), 0)

    res2 = mk(3, [Y_RIICHI, Y_IP, {"name": "宝牌", "han": 1,
                                   "detail": {"宝牌": 1, "里宝牌": 0}}])
    got2 = g7._c18_try_trim(res2, 2)
    check("删一发", got2, ["一发"])
    check("删完 = 2 番", res2["han"], 2)
    check("一发没了", badge(res2["yaku"]), [("立直", 1), ("宝牌", 1)])

    res3 = mk(4, [Y_RIICHI, Y_IP, {"name": "宝牌", "han": 1,
                                   "detail": {"宝牌": 0, "里宝牌": 1}}])
    got3 = g7._c18_try_trim(res3, 2)
    check("两个都删", sorted(got3), ["一发", "里宝"])
    check("删完 = 2 番", res3["han"], 2)
    check("宝牌整条删掉（只剩里宝那张）", badge(res3["yaku"]), [("立直", 1)])

    res4 = mk(5, [Y_RIICHI, Y_IP, Y_DORA])
    got4 = g7._c18_try_trim(res4, 2)
    check("差太多就不动", got4, [])
    check("番数没变", res4["han"], 5)

    # ── ⑤ 枷锁真的起效：删完 → 番数翻倍 ──────────────────────────────
    print("\n⑤ 删完凑上 → 枷锁翻倍")
    db8, rid8 = setup("c18e")
    g8 = Game(db8, rid8)
    g8.jiasuo_apply(0)
    g8.jiasuo_set(0, 3)
    env = {"winner": 0, "is_dealer": True, "tsumo": True, "result": "tsumo"}
    res5 = mk(4, [Y_RIICHI, Y_IP, Y_DORA])
    g8._settle_jiasuo(res5, env)
    check("删了里宝", res5.get("jiasuo_trim"), ["里宝"])
    check("3 番 ×2 = 6 番", res5["han"], 6)
    check("有枷锁这条", "枷锁" in [y["name"] for y in res5["yaku"]], True)
    _jy = [y for y in res5["yaku"] if y["name"] == "枷锁"][0]
    check("枷锁那行带 skill 标记（播报排最左）", bool(_jy.get("skill")), True)
    check("枷锁写 *2番", _jy.get("han_text"), "*2番")
    check("枷锁那行 han = 翻倍前（各家加起来 = 总番）", _jy.get("han"), 3)
    check("役种番数加起来正好是总番",
          sum(int(y.get("han", 0)) for y in res5["yaku"]), res5["han"])
    check("结算里有得点", bool(res5.get("pays")), True)

    # 差得太多凑不上就什么都不做（6 番，删里宝+一发只能到 4 番 ≠ 3）
    res6 = mk(6, [Y_RIICHI, Y_IP, Y_DORA])
    g8._settle_jiasuo(res6, env)
    check("凑不上就不翻倍", res6["han"], 6)
    check("也没有trim标记", res6.get("jiasuo_trim", []), [])

    # ── ⑥ 役满不掺 ───────────────────────────────────────────────────
    print("\n⑥ 役满不掺和")
    res7 = mk(13, [{"name": "四暗刻", "han": 13}])
    res7["yakuman"] = 1
    g8._settle_jiasuo(res7, env)
    check("役满原样", res7["han"], 13)
    check("没 trim", res7.get("jiasuo_trim", []), [])

    # ── ⑦ 选完番数才算这一家结完（别跳过配牌阶段）─────────────────────
    print("\n⑦ 选完番数才算结完")
    db9, rid9 = setup("c18f")
    solo_deal(db9, rid9)
    g9 = Game(db9, rid9)
    check("配牌技能只剩枷锁", [o["card"] for o in g9._deal_skill_options(0)], [18])
    g9.jiasuo_apply(0)
    g9b = Game(db9, rid9)
    check("发动后还在等他定番数", 0 in g9b.deal_wait, True)
    check("发动那一步不记一次性", g9b.skill_used(0, 18, 1), False)
    check("发动那一步不播报", _has_bc(g9b, "枷锁"), False)
    g9b.jiasuo_set(0, 4)
    g9c = Game(db9, rid9)
    check("定完番数才收窗口", 0 in g9c.deal_wait, False)
    check("定完才记一次性（特效就这一次）", g9c.skill_used(0, 18, 1), True)
    check("定完才播报「发动了【枷锁】」", _has_bc(g9c, "枷锁"), True)
    check("番数记下了", g9c.jiasuo.get(0), 4)

    db10, rid10 = setup("c18g")
    solo_deal(db10, rid10)
    g10 = Game(db10, rid10)
    g10.jiasuo_apply(0)
    g10.jiasuo_set(0, 0)                    # 放弃（不定番数）
    g10b = Game(db10, rid10)
    check("放弃也能收窗口", 0 in g10b.deal_wait, False)
    check("放弃 = 0 番", g10b.jiasuo.get(0), 0)
    check("放弃也算用过（不重复问）", g10b.skill_used(0, 18, 1), True)

    print("\n" + "=" * 76)
    print(f" 合计：{PASS} 断言，{FAIL} 失败")
    print("=" * 76)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
