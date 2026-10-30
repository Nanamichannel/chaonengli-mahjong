# -*- coding: utf-8 -*-
"""Card33 S1【染手】自测。

跑法：cd N:\\apps\\tianma\\server; python test_card33.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from game import Game, RuleError                     # noqa: E402
import skills                                        # noqa: E402
import test_card30 as t30                            # noqa: E402
import test_game as tg                               # noqa: E402
from tiles import parse_hand                          # noqa: E402

PASS = FAIL = 0

# 0 号位 14 张：跨 3 种花色，最后一张 3s = 刚摸到的
H_MINE = "1m2m3m4p5p6p7s8s9s5z5z1m6m3s"

# (seq, seat, tile, called, face_down)
RIVER = [
    (1, 1, "4s", 0, 0),      # 下家：4s5s6s 顺子
    (2, 1, "5s", 0, 0),
    (3, 1, "6s", 0, 0),
    (4, 2, "9p", 0, 0),      # 对家
    (5, 3, "1z", 1, 0),      # 上家：被鸣走
    (6, 2, "2z", 0, 1),      # 对家：暗置
    (7, 0, "3z", 0, 0),      # 自己
    (8, 1, "7z", 0, 0),      # 下家：7z 刻子
    (9, 1, "7z", 0, 0),
    (10, 1, "7z", 0, 0),
    (12, 3, "5p", 0, 0),     # 三家各一张 5p（刻子，跨座位）
    (13, 2, "5p", 0, 0),
    (14, 1, "5p", 0, 0),
]
# 字牌 z 记法 → 真牌名（dong/nan/…/bai），DB 里存的是真名
RIVER = [(s0, s1, parse_hand(t0)[0], c0, f0) for (s0, s1, t0, c0, f0) in RIVER]


def check(name, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  got {got!r} want {want!r}")


def setup(tag, card=33):
    db, rid = t30.setup(tag, card=card)
    tg.set_hand(db, rid, 0, parse_hand(H_MINE), drawn="3s")
    with db.tx():
        for seq, seat, tile, called, fd in RIVER:
            db.conn.execute(
                "INSERT INTO round_discards(round_id, seq, seat, wall_seq, tile, "
                "is_tsumogiri, is_riichi_tile, face_down, is_nuki, called) "
                "VALUES(?,?,?,?,?,0,0,?,0,?)",
                (rid, seq, seat, 5000 + seq, tile, fd, called))
        db.conn.execute("DELETE FROM round_dora WHERE round_id=?", (rid,))
    g = Game(db, rid)
    g.round_phase = "play"
    g.phase = "discard"
    g.turn = 0
    g.deal_wait = set()
    g.deal_used = set()
    g.save_flags()
    return db, rid


def err_of(fn):
    try:
        fn()
    except RuleError as e:
        return str(e)
    return ""


def main() -> int:
    print("=" * 78)
    print(" Card33 S1【染手】")
    print("=" * 78)

    print("\n① 注册 / 时机")
    check("名字", skills.info(33, 1).get("name"), "染手")
    check("时机 = 摸牌", skills.timing(33, 1), "draw")
    check("不是配牌技能", (33, 1) in skills.deal_skills(), False)

    print("\n② 面子 / 牌型 纯函数")
    check("顺子 4s5s6s", Game._c33_is_meld(["4s", "5s", "6s"]))
    check("刻子 7z7z7z", Game._c33_is_meld(["7z", "7z", "7z"]))
    check("赤5按5算：0s4s6s 是 456s 顺子", Game._c33_is_meld(["0s", "4s", "6s"]), True)
    check("4s5s7s 不成面子", Game._c33_is_meld(["4s", "5s", "7s"]), False)
    check("跨花色 4s5s6p 不成面子", Game._c33_is_meld(["4s", "5s", "6p"]), False)
    check("字牌连续 1z2z3z 不是顺子", Game._c33_is_meld(["1z", "2z", "3z"]), False)
    check("混一色牌型(索+发)", Game._c33_suit_ok(["2s", "3s", "4s", "fa", "fa"]))
    check("清一色牌型(纯索)", Game._c33_suit_ok(["2s", "3s", "4s", "6s"]))
    check("字一色牌型(纯字)", Game._c33_suit_ok(["bai", "bai", "fa", "zhong"]))
    check("万+筒 → 不是染手", Game._c33_suit_ok(["1m", "2p"]), False)
    check("万+索+字 → 不是染手", Game._c33_suit_ok(["1m", "2s", "fa"]), False)

    print("\n③ 可发动条件")
    db, rid = setup("c33a")
    g = Game(db, rid)
    check("摸牌后 can", g.c33s1_can(0), True)
    check("别人回合 / 没摸牌 → 不能发", g.c33s1_can(1), False)
    check("可选牌河不含自己的", 7 in g.c33_river_seqs(0), False)
    check("可选牌河不含被鸣走的", 5 in g.c33_river_seqs(0), False)
    check("可选牌河不含暗置的", 6 in g.c33_river_seqs(0), False)
    check("可选牌河含别家明牌", 1 in g.c33_river_seqs(0))

    print("\n④ 各种拒绝")
    for name, hand, rivers, want in [
        ("手牌只选 2 张", ["3s", "1m"], [1, 2, 3], "3 张"),
        ("牌河只选 2 张", ["3s", "1m", "bai"], [1, 2], "3 张"),
        ("牌河重复", ["3s", "1m", "bai"], [1, 1, 2], "重复"),
        ("拿自己的河", ["3s", "1m", "bai"], [1, 2, 7], "其他三家"),
        ("被鸣走的", ["3s", "1m", "bai"], [1, 2, 5], "不能拿"),
        ("暗置牌", ["3s", "1m", "bai"], [1, 2, 6], "不能拿"),
        ("不是面子", ["3s", "1m", "bai"], [1, 2, 4], "面子"),
        ("手里没有的牌", ["3s", "9m", "bai"], [1, 2, 3], "手里没有"),
    ]:
        gx = Game(db, rid)
        msg = err_of(lambda h=hand, rr=rivers, gx=gx: gx.c33s1_swap(0, h, rr))
        check(name + " → 被拒", want in msg, True)

    print("\n⑤ 交换：顺子（传参乱序也要按 下家→对家→上家 / 同家从早到晚）")
    g = Game(db, rid)
    r = g.c33s1_swap(0, ["3s", "1m", "bai"], [3, 1, 2])
    check("拿到 4s5s6s", r.get("got"), ["4s", "5s", "6s"])
    g2 = Game(db, rid)
    hand2 = g2.hand(0)
    check("手牌张数不变 14", len(hand2), 14)
    check("手牌里有 4s5s6s", all(t in hand2 for t in ("4s", "5s", "6s")), True)
    check("手牌里少了一张 1m", hand2.count("1m"), 1)
    check("牌河 seq1 = 3s 且暗置",
          (g2.db._row("SELECT tile, face_down FROM round_discards WHERE round_id=? AND seq=1",
                      (rid,))["tile"]), "3s")
    check("牌河 seq1 face_down", int(g2.db._row(
        "SELECT face_down FROM round_discards WHERE round_id=? AND seq=1", (rid,))["face_down"]), 1)
    check("牌河 seq2 = 1m", g2.db._row(
        "SELECT tile FROM round_discards WHERE round_id=? AND seq=2", (rid,))["tile"], "1m")
    check("牌河 seq3 = 白 且仍占原位", g2.db._row(
        "SELECT tile FROM round_discards WHERE round_id=? AND seq=3", (rid,))["tile"], "bai")
    check("刚摸到的牌补上了（3s 被换走 → 4s）", g2.drawn_tile(0), "4s")
    check("is_drawn 恰 1 张", g2.db._one(
        "SELECT COUNT(*) FROM round_hands WHERE round_id=? AND seat=0 AND is_drawn=1",
        (rid,)), 1)
    check("已经记入 used_skills", g2.skill_used(0, 33, 1))

    print("\n⑥ 一局一次 + 同参数重放（看破放行）")
    check("同参数重放返回上次结果",
          g2.c33s1_swap(0, ["3s", "1m", "bai"], [3, 1, 2]).get("got"),
          ["4s", "5s", "6s"])
    msg = err_of(lambda: g2.c33s1_swap(0, ["2m", "2m", "3m"], [8, 9, 10]))
    check("换一组参数 → 已经用过了", "已经用过" in msg, True)

    print("\n⑦ 换完正常切牌（不是只能摸切）")
    out = g2._do_discard(0, "1m")
    check("手切 1m 成功", out.get("tile"), "1m")

    print("\n⑧ 跨座位刻子：填位顺序按 下家→对家→上家（不看 seq 大小）")
    db2, rid2 = setup("c33b")
    g4 = Game(db2, rid2)
    r4 = g4.c33s1_swap(0, ["3s", "1m", "bai"], [12, 13, 14])   # 12=上家 13=对家 14=下家
    check("拿到三张 5p", r4.get("got"), ["5p", "5p", "5p"])
    g5 = Game(db2, rid2)
    check("下家的位置(seq14) ← 手牌第 1 张 3s", g5.db._row(
        "SELECT tile FROM round_discards WHERE round_id=? AND seq=14", (rid2,))["tile"], "3s")
    check("对家的位置(seq13) ← 手牌第 2 张 1m", g5.db._row(
        "SELECT tile FROM round_discards WHERE round_id=? AND seq=13", (rid2,))["tile"], "1m")
    check("上家的位置(seq12) ← 手牌第 3 张 5z", g5.db._row(
        "SELECT tile FROM round_discards WHERE round_id=? AND seq=12", (rid2,))["tile"], "bai")

    print("\n⑨ 截停：用过染手 → 牌型不是混一色/清一色/字一色 就不能和")
    db3, rid3 = t30.setup("c33c", card=6)      # 6 号卡，免得 33 的相关字段干扰
    tg.set_hand(db3, rid3, 0, parse_hand("123m456m789m234p5z"))
    gc = Game(db3, rid3)
    gc.phase = "discard"
    gc.turn = 0
    gc.round_phase = "play"
    gc.save_flags()

    res_off = Game(db3, rid3)._judge_win(0, "bai", tsumo=False)
    gc.c33s1_on = {0}
    res_on = gc._judge_win(0, "bai", tsumo=False)
    check("没用染手 → 能和", res_off is not None, True)
    check("用了染手 + 跨花色 → 不能和", res_on, None)
    check("_win_ok 也 False", gc._win_ok(0, "bai", tsumo=False), False)

    db4, rid4 = t30.setup("c33d", card=6)
    tg.set_hand(db4, rid4, 0, parse_hand("123p456p789p234p5z"))
    gd = Game(db4, rid4)
    gd.phase = "discard"
    gd.turn = 0
    gd.round_phase = "play"
    gd.c33s1_on = {0}
    gd.save_flags()
    res_suit = gd._judge_win(0, "bai", tsumo=False)
    check("用了染手 + 混一色 → 能和", res_suit is not None, True)
    check("确实是混一色", any("混一色" in y["name"] for y in res_suit["yaku"]), True)

    print("\n⑩ 渣和不能兜底")
    db5, rid5 = t30.setup("c33e", card=13)     # 13 号卡 = 渣和
    tg.set_hand(db5, rid5, 0, parse_hand("3m4m5m3p4p5p5z5z6s7s"))
    with db5.tx():
        db5.conn.execute(
            "INSERT INTO round_melds(round_id,meld_id,seat,kind,called_tile,from_seat,"
            "tiles_json,rot_index,seqs_json) VALUES(?,0,0,'pon','2m',3,?,0,'[]')",
            (rid5, '["2m","2m","2m"]'))
    ge = Game(db5, rid5)
    ge.phase = "discard"
    ge.turn = 0
    ge.round_phase = "play"
    ge.save_flags()
    ge = Game(db5, rid5)
    check("本人有渣和", ge.owns_dawa(0), True)
    r_off = ge._judge_win(0, "8s", tsumo=False)
    check("没染手 → 渣和兜底（dawa_pending）", bool((r_off or {}).get("dawa_pending")), True)
    ge.c33s1_on = {0}
    r_on = ge._judge_win(0, "8s", tsumo=False)
    check("染手生效 → 渣和也兜不了", r_on, None)

    print("\n⑪ 一定和牌也绕不过去")
    db6, rid6 = t30.setup("c33f", card=6)
    tg.set_hand(db6, rid6, 0, parse_hand("123m456m789m234p5z"))
    gf = Game(db6, rid6)
    gf.phase = "discard"
    gf.turn = 0
    gf.round_phase = "play"
    gf.c33s1_on = {0}
    gf.yiding = {0}
    gf.save_flags()
    ev = gf._yiding_settle(0)
    check("一定和牌作废", str(ev.get("event", "")), "yiding_void")
    check("原因写着染手", "染手" in str((ev.get("data") or {}).get("reason", "")
                                     or (ev.get("reason") or "")), True)

    print("\n⑫ API 入口：客户端发 hand_tiles + river")
    import api_cli
    db7, rid7 = setup("c33g")
    rr = api_cli.handle({"op": "c33s1_swap", "seat": 0,
                         "hand_tiles": ["3s", "1m", "bai"],
                         "river": [1, 2, 3], "round_id": rid7}, db7.path)
    check("API ok", bool(rr.get("ok")), True)
    check("API 拿到 4s5s6s", (rr.get("c33") or {}).get("got"), ["4s", "5s", "6s"])
    st7 = ((rr.get("state") or {}).get("c33") or {})
    check("state.c33.used", bool(st7.get("used")), True)
    check("state.c33.can 变 false", bool(st7.get("can")), False)

    print("\n" + "=" * 78)
    print(f" 通过 {PASS} / 失败 {FAIL}")
    print("=" * 78)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
