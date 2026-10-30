# -*- coding: utf-8 -*-
"""Card30 S1【向听】+ S2【W立】自测（含 29S2 不可结算四暗刻）

跑法：cd N:\apps\tianma\server; python test_card30.py
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

from game import Game, RuleError               # noqa: E402
import skills                                  # noqa: E402
from rules import wallmodel, score             # noqa: E402
import test_game as tg                         # noqa: E402
from tiles import parse_hand                   # noqa: E402

PASS = FAIL = 0

H0 = "123m456m789m2p4p6s7s"
H1 = "1z2z3z4z1p4p7p9p2s5s8s6m"
H2 = "2m5m8m2p5p8p2s5s8s2z3z4z"
H3 = "3m6m9m3p6p9p3s6s9s1z2z3z"


def check(name, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  got {got!r} want {want!r}")


def setup(tag, card=30, mains=None):
    db = tg.fresh_db(tag)
    rid, _m, _u = tg.new_round(db, seed=113)
    for s, h in enumerate((H0, H1, H2, H3)):
        tg.set_hand(db, rid, s, parse_hand(h))
    m = mains or [card, 6, 7, 8]
    orders = [[m[s], 1, 2, 3, 4] for s in range(4)]
    with db.tx():
        db.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('lobby_state', ?)",
                        (json.dumps({"seats": [{"order": o} for o in orders]},
                                    ensure_ascii=False),))
        db.conn.execute("DELETE FROM round_dora WHERE round_id=?", (rid,))
    g = Game(db, rid)
    g.granted = {0: {int(card)}}
    g.round_phase = "play"
    g.phase = "deal_skill"
    g.turn = 0
    g.deal_wait = {0}
    g.deal_used = set()
    g.save_flags()
    return db, rid


def main() -> int:
    print("=" * 78)
    print(" Card30 S1【向听】+ S2【W立】")
    print("=" * 78)

    print("\n① 注册")
    check("S1 名字", skills.info(30, 1).get("name"), "向听")
    check("S2 名字", skills.info(30, 2).get("name"), "W立")
    check("向听在配牌窗口", (30, 1) in skills.deal_skills(), True)

    # ── ② 向听：选两家 → 顺序 ─────────────────────────────────────
    print("\n② 向听：选两家 → 下家→对家→上家")
    db, rid = setup("c30a")
    g = Game(db, rid)
    err = ""
    try:
        g._c30s1_arm(0, [3, 1])            # 乱序选
    except RuleError as e:
        err = str(e)
    check("不报错", err, "")
    f = g.deal_flow or {}
    check("流程 kind", f.get("kind"), "xiangting")
    check("按 下家(1)→上家(3) 排好了", f.get("targets"), [1, 3])
    check("第一个问 1 号位", f.get("target"), 1)
    check("等对方交牌", f.get("sub"), "give")

    # 目标家的视图
    v1 = g.deal_flow_view(1)
    check("1 号位看得到「交牌」请求", (v1 or {}).get("role"), "give")
    check("要 2~3 张", ((v1 or {}).get("min"), (v1 or {}).get("max")), (2, 3))
    check("2 号位什么都看不到", g.deal_flow_view(2), None)
    check("我（0 号位）看到的是换牌视图", (g.deal_flow_view(0) or {}).get("role"), "swap")
    check("还没交牌时 picked 为空", (g.deal_flow_view(0) or {}).get("picked"), [])

    # 交牌数量校验
    for bad in ([H1[0]], ["1z", "2z", "3z", "4z"]):
        e2 = ""
        try:
            g.c30s1_give(1, bad)
        except RuleError as e:
            e2 = str(e)
        check(f"交 {len(bad)} 张被拒", e2 != "", True)
    e3 = ""
    try:
        g.c30s1_give(2, ["2m", "5m"])
    except RuleError as e:
        e3 = str(e)
    check("2 号位交牌被拒", e3 != "", True)

    # 正常交 2 张
    r = g.c30s1_give(1, ["dong", "nan"])
    check("交牌成功", r.get("tiles"), ["dong", "nan"])
    check("轮到我换牌", str((g.deal_flow or {}).get("sub")), "swap")
    check("我这边看到 picked", (g.deal_flow_view(0) or {}).get("picked"),
          ["dong", "nan"])

    # 换牌
    mine_before = sorted(g.hand(0))
    r2 = g.c30s1_swap(0, "2p", "dong")
    check("换到了 东", r2.get("got"), "dong")
    check("给出去 2p", r2.get("gave"), "2p")
    g2 = Game(db, rid)
    check("我手里多了 东、少了 2p",
          ("dong" in g2.hand(0), "2p" in g2.hand(0)), (True, False))
    check("1 号位反过来拿到 2p", "2p" in g2.hand(1), True)
    check("张数不变（我还是 13 张）", len(g2.hand(0)), len(mine_before))
    check("换进来的牌不算「刚摸的」", g2.drawn_tile(0), None)
    check("轮到问下一家（3 号位）", (g2.deal_flow or {}).get("target"), 3)
    check("下一家也是先交牌", str((g2.deal_flow or {}).get("sub")), "give")

    # 第二家走完 → 收尾
    g2.c30s1_give(3, ["3m", "6m", "9m"])
    g2.c30s1_swap(0, "6s", "3m")        # 6s 是第一轮换完之后手里还有的牌
    g3 = Game(db, rid)
    check("两家都换完 → 流程结束", g3.deal_flow, None)
    check("我已经不在配牌等待里", 0 in g3.deal_wait, False)

    # ── ③ W立：立直一律双立直 ────────────────────────────────────
    print("\n③ W立：立直 = 双立直（2 番）")
    db2, rid2 = setup("c30b")
    tg.set_hand(db2, rid2, 0, parse_hand("123m456m789m5p5p6s7s8s"), drawn="8s")
    with db2.tx():                        # 让他已经打过一张 → 不是「第一巡立直」
        db2.conn.execute(
            "INSERT INTO round_discards(round_id, seq, seat, wall_seq, tile,"
            " is_tsumogiri, is_riichi_tile, face_down, called)"
            " VALUES(?,900,0,901,'1z',1,0,0,0)", (rid2,))
    g4 = Game(db2, rid2)
    g4.phase, g4.turn = "discard", 0
    dismiss = g4.riichi_discards(0)
    check("能立直", bool(dismiss), True)
    g4._do_discard(0, tile="8s", riichi=True)
    g5 = Game(db2, rid2)
    check("立直成立", g5.is_riichi(0), True)
    check("同时算双立直", 0 in g5.double_riichi, True)
    res = g5._judge_win(0, "5s", tsumo=False) if "5s" in g5.waits(0) else None
    if res:
        names = [y["name"] for y in res["yaku"]]
        check("役种写「双立直」（不是立直+双立直）",
              ("双立直" in names, "立直" in names), (True, False))
    else:
        check("（这手不是 8s 听，跳过役种检查）", True)

    # 没卡的人不受影响
    db3, rid3 = setup("c30c", card=6)
    tg.set_hand(db3, rid3, 0, parse_hand("123m456m789m5p5p6s7s8s"), drawn="8s")
    with db3.tx():                        # 同上：排除「第一巡立直」的自然双立直
        db3.conn.execute(
            "INSERT INTO round_discards(round_id, seq, seat, wall_seq, tile,"
            " is_tsumogiri, is_riichi_tile, face_down, called)"
            " VALUES(?,900,0,901,'1z',1,0,0,0)", (rid3,))
    g6 = Game(db3, rid3)
    g6.phase, g6.turn = "discard", 0
    g6._do_discard(0, tile="8s", riichi=True)
    g6b = Game(db3, rid3)
    check("没 30 号卡 → 不是双立直", 0 in g6b.double_riichi, False)

    # ── ④ 里宝 +4：第 4 列被摸过才算 ─────────────────────────────
    print("\n④ W立：第 4 列被摸过 → 里宝 +4")
    db4, rid4 = setup("c30d")
    with db4.tx():
        db4.conn.execute("INSERT INTO round_riichi(round_id, seat, declared_seq) "
                         "VALUES(?,0,1)", (rid4,))
    g7 = Game(db4, rid4)
    g7.dice = (1, 1)                      # 让 wall_first_stack() 有值
    g7.save_flags()
    g7 = Game(db4, rid4)
    g7.dice = (1, 1)
    n = g7.wall_first_stack()
    k = (int(n) - 1) % 17
    need = (51 - k) * 2 + 1
    with db4.tx():
        db4.conn.execute("UPDATE rounds SET live_left=? WHERE round_id=?",
                         (124 - (need - 1), rid4))
    g7 = Game(db4, rid4)
    check("刚好差一张 → 还没到第 4 列", g7._wall_col4_drawn(), False)
    with db4.tx():
        db4.conn.execute("UPDATE rounds SET live_left=? WHERE round_id=?",
                         (124 - need, rid4))
    g7 = Game(db4, rid4)
    check("摸进第 4 列 → True", g7._wall_col4_drawn(), True)

    res2 = {"han": 3, "fu": 30,
            "yaku": [{"name": "双立直", "han": 2},
                     {"name": "宝牌", "han": 1, "detail": {"里宝牌": 1}}],
            "pays": score.payments(2, 30, is_dealer=True, tsumo=False)}
    g7._settle_c30s2(res2, {"winner": 0, "loser": None, "result": "ron",
                            "tsumo": False, "is_dealer": True})
    check("番数 = 2 + 1 + 4", int(res2["han"]), 7)
    det = [y for y in res2["yaku"] if y["name"] == "宝牌"][0]["detail"]
    check("播报里记在「里宝牌」上", int(det["里宝牌"]), 5)

    g7b = Game(db4, rid4)
    res3 = {"han": 1, "fu": 30, "yaku": [{"name": "立直", "han": 1}],
            "pays": score.payments(1, 30, is_dealer=True, tsumo=False)}
    with db4.tx():                       # 把牌山恢复到「还早」
        db4.conn.execute("UPDATE rounds SET live_left=124 WHERE round_id=?", (rid4,))
    g7b = Game(db4, rid4)
    g7b._settle_c30s2(res3, {"winner": 0, "loser": None, "result": "ron",
                             "tsumo": False, "is_dealer": True})
    check("第 4 列没到 → 不加番", int(res3["han"]), 1)

    # ── ⑤ 精算不可结算四暗刻 ─────────────────────────────────────
    print("\n⑤ 精算：不能把副露手重判成四暗刻")
    db5, rid5 = setup("c30e", card=29)
    tg.set_hand(db5, rid5, 0, parse_hand("222m333m444p5s"))
    with db5.tx():
        db5.conn.execute(
            "INSERT INTO round_melds(round_id,meld_id,seat,kind,called_tile,from_seat,"
            "tiles_json,rot_index) VALUES(?,0,0,'pon','1m',3,"
            "'[\"1m\",\"1m\",\"1m\"]',0)", (rid5,))
    g8 = Game(db5, rid5)
    g8.round_phase = "play"
    g8.phase, g8.turn = "discard", 0
    base = g8._judge_win(0, "5s", tsumo=False)
    check("副露手能判出来", base is not None, True)
    if base:
        res4 = g8.settle_preview(0, None, "ron", base, dry_run=True)
        names = [y["name"] for y in (res4 or {}).get("yaku", [])]
        check("没有四暗刻", any("四暗刻" in n for n in names), False)
        check("退化成三暗刻", any("三暗刻" in n for n in names), True)
        check("不是役满", int((res4 or {}).get("yakuman", 0)), 0)

    # ── ⑥ 没人在操作的那家：服务端替他交两张 ───────────────────────
    print("\n⑥ AI 代交")
    db6, rid6 = setup("c30f")
    g9 = Game(db6, rid6)
    ar = g9._c30s1_arm(0, [3, 1])
    check("arm 回带 targets（客户端播报用）", ar.get("targets"), [1, 3])
    check("现在要问 1 号位", g9.c30_ask_for(1), 0)
    ra = g9.c30s1_auto(1)
    check("AI 交了 2 张", len(ra.get("tiles") or []), 2)
    g9b = Game(db6, rid6)
    check("交完轮到挑牌", str((g9b.deal_flow or {}).get("sub")), "swap")
    check("没轮到的那家不能代交", g9b.c30s1_auto(2).get("skipped"), True)

    # ── ⑦ 挑「第二张」给我的牌（以前报「对方手里找不到这张牌」）────────
    print("\n⑦ 挑第 2 张给我的牌")
    db8, rid8 = setup("c30h")
    g10 = Game(db8, rid8)
    g10._c30s1_arm(0, [1, 3])
    g10.c30s1_give(1, ["6m", "9p"])        # 两张不同的牌，对方手里各只有一张
    g11 = Game(db8, rid8)
    mine8 = g11.hand(0)[0]
    r8 = g11.c30s1_swap(0, mine8, "9p")    # ★ 挑的是 picked[1]
    check("挑第二张也能换到", r8.get("got"), "9p")
    g12 = Game(db8, rid8)
    check("我手里多了 9p", "9p" in g12.hand(0), True)
    check("1 号位少了 9p", "9p" in g12.hand(1), False)
    check("1 号位拿到我那张", mine8 in g12.hand(1), True)

    print("\n" + "=" * 78)
    print(f" 通过 {PASS} / 失败 {FAIL}")
    print("=" * 78)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
