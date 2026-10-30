# -*- coding: utf-8 -*-
"""Card25 S2「宝牌的集合」自测

口径（用户已确认）：
  · 配牌紧随【宝牌运】自动发动，S1 结算完之前不离开配牌阶段；看破 S2 紧接着 S1 问；
  · 开启后：别人摸到宝牌 → 我拿一张非宝牌换过来，**不可跳过**、**不可拿宝牌换**；整局每次；
  · 杠翻出来的**表宝牌全场无效**，里宝牌不受影响；我胡牌时**每杠 +4 番**（算进宝牌，不算役）；
  · 「摸到的牌被抢」统一按 下家 → 对家 → 上家 的座位顺序（深山/海神/宝牌的集合/画板）；
  · 钓鱼强制打出宝牌不触发【宝牌运】的罚点；钓鱼不能点名「只能摸切」的人。

跑法：cd N:\apps\tianma\server; python test_card25s2.py
"""
from __future__ import annotations

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
import test_game as tg                    # noqa: E402
from tiles import parse_hand              # noqa: E402

PASS = FAIL = 0

H0 = "1m3m4m5m6m7m8m9m5p5p6s7s9s"     # 没有 2m / 赤 5
H1 = "2m2m1p4p7p1s4s7s1z2z3z"
H2 = "3m6m9m3p6p9p3s6s9s4z5z6z7z"
H3 = "0m2m3m6m9m3p6p9p3s6s9s1z2z"


def check(name, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  got {got!r} want {want!r}")


def setup(tag, hands=(H0, H1, H2, H3), granted=(25,)):
    db = tg.fresh_db(tag)
    rid, _m, _u = tg.new_round(db, seed=83)
    for s, h in enumerate(hands):
        tg.set_hand(db, rid, s, parse_hand(h))
    db.add_dora(rid, "dora", 0, "1m", "2m")          # 宝牌 = 2m
    g = Game(db, rid)
    g.granted = {0: set(granted)}
    g.round_phase = "play"
    g.phase = "deal_skill"
    g.deal_wait = {0}
    g.deal_deadline = time.time() + 20.0
    g.save_flags()
    return db, rid


def main() -> int:
    print("=" * 78)
    print(" Card25 S2「宝牌的集合」：配牌紧随宝牌运 + 抢宝牌 + 杠宝无效/每杠+4番")
    print("=" * 78)

    # ── ① 注册 / 时机 / 不在配牌窗口里 ──────────────────────────────
    print("\n① 技能注册与发动时机")
    check("名字", skills.info(25, 2).get("name"), "宝牌的集合")
    check("时机 = 配牌", skills.timing(25, 2), "deal")
    db, rid = setup("c25s2a")
    g = Game(db, rid)
    opts = [(o["card"], o["skill"]) for o in g._deal_skill_options(0)]
    check("列了宝牌运", (25, 1) in opts)
    check("不列宝牌的集合（它是自动挂出来的）", (25, 2) in opts, False)

    # ── ② 宝牌运结算完 → 留在配牌阶段等宝牌的集合 ────────────────────
    print("\n② 宝牌运结算完 → 先不离开配牌阶段")
    g.deal_action(0, "use", 25, 1)
    check("换牌流程已开始", g.deal_flow is not None)
    g.deal_swap(0, 0, ["1m", "3m"])                  # 下家 2 张宝牌
    if g.deal_flow is not None:
        g.deal_swap(0, 2, ["5p", "6s"])              # 上家 2 张宝牌（对家没宝牌被跳过）
    check("流程收尾", g.deal_flow, None)
    check("宝牌运开启", 0 in g.c25_on)
    check("还留在配牌阶段", g.phase, "deal_skill")
    check("这一家还在等决定", 0 in g.deal_wait)
    check("下发 c25s2_can", bool(g.state_for(0).get("c25s2_can")), True)
    check("还没开启宝牌的集合", 0 in g.c25s2_on, False)
    r = g.c25s2_arm(0)
    check("发动成功", r.get("c25s2_on"), True)
    check("宝牌的集合开启", 0 in g.c25s2_on)
    check("配牌阶段结束", g.phase, "discard")
    check("本局不会再挂第二次", g.c25s2_pending, -1)
    g2 = Game(db, rid)
    check("落库了（另一个进程能看到）", 0 in g2.c25s2_on)
    check("重复发动被拒", isinstance(g2.c25s2_pending, int) and g2.c25s2_pending == -1)

    # ── ③ 宝牌运跳过 / 已经用过 → 不挂 ───────────────────────────────
    print("\n③ 宝牌运被跳过 → 宝牌的集合不挂出")
    db2, rid2 = setup("c25s2b")
    g3 = Game(db2, rid2)
    g3.deal_action(0, "skip")
    check("没有挂着等", g3.c25s2_pending, -1)
    check("直接进切牌", g3.phase, "discard")
    check("宝牌的集合没开", 0 in g3.c25s2_on, False)

    # ── ④ 抢牌顺序：下家 → 对家 → 上家 ───────────────────────────────
    print("\n④ 「摸到的牌被抢」统一按座位顺序")
    db3, rid3 = setup("c25s2c")
    g4 = Game(db3, rid3)
    g4.c25s2_on = {1, 2, 3}
    g4.haishin_on = False
    # 1 号位（下家）先能拿
    check("三家都开着 → 下家先", g4._tile_interceptor(0, "2m"), (1, "c25s2"))
    g4.c25s2_on = {2, 3}
    check("下家没开 → 对家", g4._tile_interceptor(0, "2m"), (2, "c25s2"))
    g4.c25s2_on = {3}
    check("只剩上家", g4._tile_interceptor(0, "2m"), (3, "c25s2"))
    check("不是宝牌 → 谁也不抢", g4._tile_interceptor(0, "5p"), None)
    g4.c25s2_on = {1}
    check("自己摸到 → 不抢自己", g4._tile_interceptor(1, "2m"), None)
    # 同一家：画板优先于换牌类
    g4.boards = {1: {"tiles": ["2m"], "delivered": [], "pending": []}}
    check("同一家 画板 优先", g4._tile_interceptor(0, "2m"), (1, "board"))
    g4.boards = {}
    # 海神也在同一家 → 海神（画板没有时）
    g4.granted = {1: {12}}
    g4.haishin_on = True
    g4.c25s2_on = {1}
    g4._owns_cache = {}
    check("海神 优先于 宝牌的集合（同一家）", g4._tile_interceptor(0, "2m"), (1, "haishin"))

    # ── ⑤ 别人摸到宝牌 → 挂 offer，只有我看到 ────────────────────────
    print("\n⑤ 别人摸到宝牌 → 要我用非宝牌换（不可跳过）")
    db4, rid4 = setup("c25s2d")
    # 我手里有两张 2m（宝牌）+ 一张 1m；1 号位「刚摸到」2m
    tg.set_hand(db4, rid4, 0, parse_hand("1m2m2m4m5m6m7m8m9m5p5p6s9s"))
    tg.set_hand(db4, rid4, 1, parse_hand("1p4p7p1s4s7s1z2z3z2m"), drawn="2m")
    g5 = Game(db4, rid4)
    g5.c25s2_on = {0}
    g5.phase = "c25s2"
    g5.c25s2_offer = {"owner": 0, "from": 1, "tile": "2m"}
    g5.save_flags()
    g6 = Game(db4, rid4)
    check("state 给 owner 看到 offer",
          isinstance(g6.state_for(0).get("c25s2_offer"), dict), True)
    check("别家看不到", g6.state_for(1).get("c25s2_offer"), None)
    check("统一询问锁把桌子停住", (g6.prompt_state() or {}).get("kind"), "c25s2")
    err = ""
    try:
        g6.c25s2_swap(0, "")
    except RuleError as e:
        err = str(e)
    check("不能跳过", "不能跳过" in err)
    err = ""
    try:
        g6.c25s2_swap(0, "2m")                       # 我手里也有 2m（宝牌）
    except RuleError as e:
        err = str(e)
    check("不能拿宝牌去换", "不能拿宝牌" in err)
    r6 = g6.c25s2_swap(0, "1m")
    check("换到了宝牌", r6.get("got"), "2m")
    check("我出的是 1m", r6.get("gave"), "1m")
    g7 = Game(db4, rid4)
    check("换完回到打牌阶段", g7.phase, "discard")
    check("我手里多了那张 2m", g7.hand(0).count("2m"), 3)
    check("对方拿到我的 1m", g7.hand(1).count("1m"), 1)

    # ── ⑥ 自己摸到 / 没开 → 不触发 ──────────────────────────────────
    print("\n⑥ 触发条件")
    db5, rid5 = setup("c25s2e")
    g8 = Game(db5, rid5)
    check("没开 → 不抢", g8._tile_interceptor(1, "2m"), None)
    g8.c25s2_on = {0}
    check("自己摸到宝牌 → 不给自己", g8._tile_interceptor(0, "2m"), None)
    check("别人摸到 → 抢", g8._tile_interceptor(1, "2m"), (0, "c25s2"))
    with db5.tx():
        db5.conn.execute("INSERT INTO round_riichi(round_id, seat) VALUES(?,?)", (rid5, 0))
    g8b = Game(db5, rid5)
    check("我立直了 → 不抢（手牌锁定）", g8b._tile_interceptor(1, "2m"), None)

    # ── ⑦ 判番：杠翻的表宝牌无效 / 每杠 +4 番（算进宝牌） ──────────────
    print("\n⑦ 杠翻出来的表宝牌无效 + 每杠 +4 番")
    WIN14 = "123m456m789m4p4p6s7s8s"      # 自摸 8s 就和（14 张）
    db6, rid6 = tg.fresh_db("c25s2f"), None
    rid6, _m6, _u6 = tg.new_round(db6, seed=91)
    tg.set_hand(db6, rid6, 0, parse_hand(WIN14), drawn="8s")
    tg.set_hand(db6, rid6, 1, parse_hand("1m4m7m1p4p7p1s4s7s1z2z3z"))
    tg.set_hand(db6, rid6, 2, parse_hand("2m5m8m2p5p8p2s5s8s2z3z4z"))
    tg.set_hand(db6, rid6, 3, parse_hand("3p3p3p3p6p9p3s6s9s1z2z3z"))
    db6.add_dora(rid6, "dora", 0, "1m", "2m")        # 开局宝牌 = 2m（手里 1 张）
    g9 = Game(db6, rid6)
    g9.round_phase = "play"
    g9.turn, g9.phase = 0, "discard"
    g9.save_flags()
    plain = g9._judge_win(0, "8s", tsumo=True)
    check("开局就天和（哨兵：这手牌本身是和的）",
          [y["name"] for y in plain["yaku"]], ["天和"])
    # 开一个杠 + 翻第 2 张表宝牌（指示牌 3p → 宝牌 4p，我手里有 2 张）
    db6.meld(rid6, 3, "ankan", ["3p", "3p", "3p", "3p"], called_tile="3p",
             from_seat=3, rot_index=-1)
    db6.add_dora(rid6, "dora", 1, "3p", "4p")
    g10 = Game(db6, rid6)
    g10.round_phase = "play"
    g10.turn, g10.phase = 0, "discard"
    g10.save_flags()
    check("杠数 = 1", g10.kan_count(), 1)
    check("宝牌指示牌 2 张", len(g10.revealed_dora("dora")), 2)
    plain_kan = g10.settle_preview(0, None, "tsumo",
                                   g10._judge_win(0, "8s", tsumo=True), dry_run=True)
    check("没开宝牌的集合：杠宝牌照算（宝牌 3 张）", int(plain_kan["han"]), 7)
    check("宝牌明细 3 张", [y for y in plain_kan["yaku"]
                            if y["name"] == "宝牌"][0]["han"], 3)
    g11 = Game(db6, rid6)
    g11.round_phase = "play"
    g11.turn, g11.phase = 0, "discard"
    g11.c25s2_on = {0}
    g11.save_flags()
    res = g11.settle_preview(0, None, "tsumo",
                             g11._judge_win(0, "8s", tsumo=True), dry_run=True)
    check("开着：杠翻的表宝牌不算（-2 番）+ 每杠 4 番 → 7-2+4 = 9", int(res["han"]), 9)
    dora = [y for y in res["yaku"] if y.get("name") == "宝牌"]
    check("宝牌条目只有一条", len(dora), 1)
    check("宝牌里的明细写了「宝牌的集合」", int((dora[0].get("detail") or {}).get("宝牌的集合", 0)), 4)
    check("不再单独占一个役种", any(y.get("name") == "宝牌的集合" for y in res["yaku"]), False)
    # 对手：表宝牌同样无效，但没有 +4
    ctx_o = {"seat": 1}
    g11._c25s2_judge_ctx(1, ctx_o)
    check("对手也吃「表宝牌无效」", bool(ctx_o.get("dora_void_kan")), True)
    check("对手没有 +4 番", "dora_bonus_han" in ctx_o, False)

    # ── ⑧ 钓鱼：强制切宝牌不触发罚点 ─────────────────────────────────
    print("\n⑧ 钓鱼强制打出宝牌 → 不触发【宝牌运】")
    db7, rid7 = tg.fresh_db("c25s2g"), None
    rid7, _m7, _u7 = tg.new_round(db7, seed=77)
    tg.set_hand(db7, rid7, 0, parse_hand("2m2m4m5m6m7m8m9m1p2p3p4s5s"), drawn="5s")
    tg.set_hand(db7, rid7, 1, parse_hand("1m4m7m1p4p7p1s4s7s1z2z3z"))
    tg.set_hand(db7, rid7, 2, parse_hand("2m5m8m2p5p8p2s5s8s2z3z4z"))
    tg.set_hand(db7, rid7, 3, parse_hand("3m6m9m3p6p9p3s6s9s1z2z3z"))
    db7.add_dora(rid7, "dora", 0, "1m", "2m")
    g12 = Game(db7, rid7)
    g12.granted = {0: {15}}
    g12.round_phase = "play"
    g12.turn, g12.phase = 0, "discard"
    g12.c25_on = {2}                                 # 2 号位开着【宝牌运】
    g12.save_flags()
    g12 = Game(db7, rid7)
    check("能钓 2 号位的 2m", "2m" in g12.diaoyu_options(0, 2), True)
    before = g12.scores()
    r12 = g12.diaoyu_force(0, 2, "2m")
    check("强制打出去了", r12.get("ok", True), True)
    g13 = Game(db7, rid7)
    check("不罚：本局还能和牌", 2 in g13.no_win, False)
    check("不罚：分数没动", g13.scores(), before)
    check("不罚：宝牌运还开着", 2 in g13.c25_on)

    # ── ⑨ 钓鱼不能点名「只能摸切」的人 ───────────────────────────────
    print("\n⑨ 钓鱼不能要求「只能摸切」的人手切")
    g12b = Game(db7, rid7)
    g12b.must_tsumogiri = {2}
    check("换牌技能后用过的（只能摸切）→ 不列", g12b.diaoyu_options(0, 2), [])
    g12b.must_tsumogiri = set()
    g12b.duel = {"by": 0, "target": 1}
    check("被决斗限制的（只能摸切）→ 不列", g12b.diaoyu_options(0, 2), [])
    g12b.duel = None
    check("正常情况照常列", "2m" in g12b.diaoyu_options(0, 2), True)
    g12b.c10s2 = {2: 1}
    check("四喜期间不能让他打东/北", [k for k in g12b.diaoyu_options(0, 2)
                                     if k in ("dong", "bei")], [])

    # ── ⑩ 同一家：主战卡先于协战卡（两次询问）────────────────────────
    print("\n⑩ 主战卡先于协战卡：同一家要问两次")
    import json as _json
    db8, rid8 = setup("c25s2h")
    g14 = Game(db8, rid8)
    # 0 号位：主战 = 深山(19)，协战 = 宝牌的集合(25)
    order_main19 = [19, 2, 25, 12, 25]
    order_main25 = [25, 2, 19, 12, 19]
    with db8.tx():
        db8.conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES('lobby_state', ?)",
            (_json.dumps({"seats": [{"order": order_main19}, {"order": order_main19},
                                    {"order": order_main19}, {"order": order_main19}]}),))
    g14.granted = {}                    # 不走「传承当主战」那条，纯粹看大厅的卡序
    check("主战卡 rank=0", skills.card_slot(db8, g14, 0, 19), 0)
    check("协战卡 rank=1", skills.card_slot(db8, g14, 0, 25), 1)
    g14.shenshan = {0}
    g14.c25s2_on = {0}
    g14._role_cache = {}
    g14._owns_cache = {}
    check("主战（深山）先问", g14._intercept_kinds(0, 1, "2m"), ["shenshan", "c25s2"])
    check("plan 里两条都在（同一家两次）",
          g14._intercept_plan(1, "2m"), [[0, "shenshan"], [0, "c25s2"]])

    # 主战 / 协战互换 → 顺序跟着换
    with db8.tx():
        db8.conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES('lobby_state', ?)",
            (_json.dumps({"seats": [{"order": order_main25}, {"order": order_main25},
                                    {"order": order_main25}, {"order": order_main25}]}),))
    g15 = Game(db8, rid8)
    g15.shenshan = {0}
    g15.c25s2_on = {0}
    check("主战换成宝牌的集合 → 它先问",
          g15._intercept_kinds(0, 1, "2m"), ["c25s2", "shenshan"])

    # 深山「不要」→ 继续问协战卡（第二次询问）
    g16 = Game(db8, rid8)
    g16.c25s2_on = {0}
    g16.shenshan_offer = {"seat": 0, "from": 1, "tile": "2m",
                          "plan": [[0, "c25s2"]]}
    g16.phase = "shenshan"
    g16.save_flags()
    r16 = g16.shenshan_resolve(0, "")
    check("深山跳过 → 接着问协战卡", (r16.get("next") or {}).get("skill"), "c25s2")
    check("轮到协战卡的询问", g16.phase, "c25s2")
    check("还是同一张牌", (g16.c25s2_offer or {}).get("tile"), "2m")
    g17 = Game(db8, rid8)
    check("落库了（另一个进程能看到这笔询问）",
          isinstance(g17.c25s2_offer, dict), True)

    # 后面没人了 → 收尾回打牌阶段
    g18 = Game(db8, rid8)
    g18.c25s2_offer = None
    g18.shenshan_offer = {"seat": 0, "from": 1, "tile": "2m", "plan": []}
    g18.phase = "shenshan"
    g18.save_flags()
    r18 = g18.shenshan_resolve(0, "")
    check("没人要了 → 收尾", r18.get("next"), None)
    check("回到打牌阶段", g18.phase, "discard")

    # 海神兜底跳过也不能让摸牌的人多摸一张
    g19 = Game(db8, rid8)
    g19.haishin_offer = {"owner": 0, "from": 1, "tile": "3m", "plan": []}
    g19.phase = "haishin"
    g19.save_flags()
    g19.haishin_pass(0)
    check("海神不要 → 回到打牌阶段（不是再摸一张）", g19.phase, "discard")

    # ── ⑪ 配牌窗口 / 看破询问 也按卡序 ────────────────────────────────
    print("\n⑪ 配牌窗口与看破询问：同样主战在前")
    db9, rid9 = setup("c25s2i")
    # 0 号位：主战 = 自信(3, 配牌技)，协战 = 海神(12, 配牌技)
    order_3_12 = [3, 2, 25, 12, 12]
    with db9.tx():
        db9.conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES('lobby_state', ?)",
            (_json.dumps({"seats": [{"order": order_3_12}] * 4}),))
    g20 = Game(db9, rid9)
    g20.granted = {}
    g20._owns_cache = {}
    opts20 = [(o["card"], o["skill"]) for o in g20._deal_skill_options(0)]
    check("卡序 = 主战 3 → 协战 12", skills.cards_in_order(db9, g20, 0), [3, 12])
    check("配牌窗口按卡序：自信在前、海神在后", opts20, [(3, 1), (12, 1)])

    # 看破：1 号位把看破当协战、2 号位当主战 → 先问 2 号位
    orders_k = [[5, 1, 2, 25, 12], [12, 2, 3, 25, 17], [17, 1, 2, 25, 12],
                [5, 1, 2, 12, 25]]
    with db9.tx():
        db9.conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES('lobby_state', ?)",
            (_json.dumps({"seats": [{"order": o} for o in orders_k]},
                         ensure_ascii=False),))
    g21 = Game(db9, rid9)
    g21.granted = {}
    g21._owns_cache = {}
    g21.poked = set()
    check("主战槽看破排前面（2 号位先、1 号位后）",
          g21._kangpo_askers(0), [2, 1])
    check("发动者自己不问", g21._kangpo_askers(2), [1])

    print("\n" + "=" * 78)
    print(f" 通过 {PASS} / 失败 {FAIL}")
    print("=" * 78)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
