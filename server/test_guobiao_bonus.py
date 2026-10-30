# -*- coding: utf-8 -*-
"""【国标】(Card01 S1) 的番数效果：五门齐 / 花龙 / 三色三步高 = 门清 +2 / 副露 +1。

「一定和牌」是**通用结算规则**（找铳张 / 自摸 / 取最高点数 / 判不出才兜底），
加番是**国标自己的效果**：国标宣言时把自己的判番开关（pattern_bonus）当参数交给结算，
结算原样透传给判番函数；别的一定和牌来源（21S2 馈赠等）不传 → 不加奖励番。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")

from game import Game  # noqa: E402
from tiles import parse_hand  # noqa: E402
import test_game as tg  # noqa: E402

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


# 和牌形：123m 234p 345s 789m 55p → 三色三步高（123m / 234p / 345s，数字依次 +1）+ 平和
# 13 张听牌：123m 234p 345s 78m 55p ← 听 6m / 9m
H13 = parse_hand("123m234p345s78m55p")
H14 = H13 + ["dong"]                 # 刚摸完的 14 张，打东回到上面那手
DISCARD = "dong"
WIN = "9m"

H_NONE = parse_hand("1m4m7m1p4p7p1s4s7s1z2z3z")
H_9M = parse_hand("1m2m3m4p5p6p7s8s9s1p1p") + ["9m"]       # 手里有 9m 的对手（13 张）


def make(tag, seed, others, hand=None, drawn=None):
    db = tg.fresh_db(tag)
    rid, _m, _u = tg.new_round(db, seed=seed)
    tg.set_hand(db, rid, 0, hand or H14, drawn=drawn)
    for i, h in enumerate(others, start=1):
        tg.set_hand(db, rid, i, h)
    g = Game(db, rid)
    g.granted = {0: {1}}
    g.round_phase = "play"
    g.turn, g.phase = 0, "discard"
    g.save_flags()
    return db, rid


def yaku_names(res):
    return [str(y.get("name", "")) for y in (res or {}).get("yaku", [])]


def main() -> int:
    print("=" * 66)
    print(" 天马麻将 · 国标的番数效果（五门齐 / 花龙 / 三色三步高）")
    print("=" * 66)

    # ① 判番层面：同一手牌，开关开/关
    print("\n① 门清 +2")
    db, rid = make("gb_b1", 801, [H_9M, H_NONE, H_NONE], hand=H13)
    g = Game(db, rid)
    pb = g._judge_win(0, WIN, tsumo=False, quiet=True, judge_opts={"pattern_bonus": True})
    plain = g._judge_win(0, WIN, tsumo=False, quiet=True)
    check("开关打开 → 认识三色三步高", "三色三步高" in yaku_names(pb), True)
    check("开关不传 → 不当成役", "三色三步高" in yaku_names(plain), False)
    pat_han = [int(y.get("han", 0)) for y in (pb or {}).get("yaku", [])
               if "三色三步高" in str(y.get("name", ""))]
    check("门清时这条役是 2 番", pat_han, [2])
    check("番数正好多 2（门清）", int(pb.get("han", 0)) - int(plain.get("han", 0)), 2)
    check("点数也跟着涨",
          int((pb.get("pays") or {}).get("total", 0))
          > int((plain.get("pays") or {}).get("total", 0)), True)

    # ② 国标宣言：结算里带着奖励番
    print("\n② 国标宣言 → 结算带奖励番")
    db, rid = make("gb_b2", 802, [H_9M, H_NONE, H_NONE], hand=H14, drawn=DISCARD)
    g = Game(db, rid)
    ev = g.guobiao_declare(0, DISCARD)
    res = g.result or {}
    check("结算事件是 yiding", ev.get("event"), "yiding")
    check("出铳的是下家（他有 9m）", ev.get("from"), 1)
    check("结算里有三色三步高", "三色三步高" in yaku_names(res), True)
    plain_same = g._judge_win(0, WIN, tsumo=False, quiet=True)     # 同一局面、不带开关
    check("结算番数 = 同一局面不带开关 + 2",
          int(res.get("han", 0)) - int((plain_same or {}).get("han", 0)), 2)
    check("结算点数也比不带开关高",
          int((res.get("pays") or {}).get("total", 0))
          > int(((plain_same or {}).get("pays") or {}).get("total", 0)), True)

    # ③ 同样一手牌走 21S2 馈赠的「一定和牌」→ 不加奖励番
    print("\n③ 同样一手牌走 21S2 → 不加奖励番（加番是国标自己的效果）")
    db2, rid2 = make("gb_b3", 803, [H_9M, H_NONE, H_NONE], hand=H14, drawn=DISCARD)
    g2 = Game(db2, rid2)
    g2.yiding_grant(0, 21, 2)
    check("拿到一定和牌权限", g2.yiding_can(0), True)
    g2.yiding_declare(0, DISCARD)
    res2 = g2.result or {}
    check("也结算成荣和", res2.get("result"), "ron")
    check("没有三色三步高", "三色三步高" in yaku_names(res2), False)
    pb_same = g2._judge_win(0, WIN, tsumo=False, quiet=True,
                            judge_opts={"pattern_bonus": True})
    check("番数比「开了开关」少 2（开关只由国标传）",
          int((pb_same or {}).get("han", 0)) - int(res2.get("han", 0)), 2)

    # ④ 副露 +1
    print("\n④ 副露 +1")
    # 副露 789m 已亮出 → 手里只需 10 张暗牌（+ 和的 5p = 11 张，加副露 3 张 = 14）
    db3, rid3 = make("gb_b4", 804, [H_9M, H_NONE, H_NONE],
                     hand=parse_hand("123m234p345s5p"))
    with db3.tx():
        db3.conn.execute(
            "INSERT INTO round_melds(round_id, meld_id, seat, kind, called_tile, from_seat, "
            "tiles_json, rot_index, from_discard_seq, seqs_json) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (rid3, 0, 0, "chi", "9m", 1, '["7m","8m","9m"]', 0, None, "[]"))
    g3 = Game(db3, rid3)
    check("副露数 = 1", len(g3.melds(0)), 1)
    pb2 = g3._judge_win(0, "5p", tsumo=False, quiet=True,
                        judge_opts={"pattern_bonus": True})
    plain2 = g3._judge_win(0, "5p", tsumo=False, quiet=True)      # 副露没有别的役 → None
    check("副露也认三色三步高", "三色三步高" in yaku_names(pb2), True)
    check("开关不传时没有这个役", "三色三步高" in yaku_names(plain2), False)
    # 直接看那一条役的番数（宝牌会随宝牌指示牌变化，别用总番数相减）
    pat_han = [int(y.get("han", 0)) for y in (pb2 or {}).get("yaku", [])
               if "三色三步高" in str(y.get("name", ""))]
    check("副露 +1（不是 +2）", pat_han, [1])

    # ⑤ 挑铳张的口径跟开关一致
    print("\n⑤ 挑铳张用同一套判番口径")
    db4, rid4 = make("gb_b5", 805, [H_9M, H_NONE, H_NONE], hand=H14, drawn=DISCARD)
    g4 = Game(db4, rid4)
    best_pb = -1
    for k in (1, 2, 3):
        o = k
        for t in set(g4.hand(o)):
            r = g4._judge_win(0, t, tsumo=False, quiet=True,
                              judge_opts={"pattern_bonus": True})
            best_pb = max(best_pb, int((r or {}).get("pays", {}).get("total", 0)))
    payer, tile = g4._yiding_payer(0, {"pattern_bonus": True})
    check("找到出铳的人", payer, 1)
    check("挑的是 9m", tile, "9m")
    got = g4._judge_win(0, tile, tsumo=False, quiet=True,
                        judge_opts={"pattern_bonus": True})
    check("挑中的那张就是「开关下点数最高」的",
          int((got or {}).get("pays", {}).get("total", 0)), best_pb)

    print("\n" + "=" * 66)
    print(f" 通过 {PASS} / 失败 {FAIL}")
    print("=" * 66)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
