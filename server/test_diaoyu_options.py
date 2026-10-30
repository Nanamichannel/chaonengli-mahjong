# -*- coding: utf-8 -*-
"""钓鱼（Card15 S1）的「能让他打出的牌」必须用真正的吃/碰判定。

回归用户报的 bug：手里 4p6p + 副露 456p 时，「吃 3p」被列了出来。
（旧实现只看「有没有一张差 1~2 的牌」，3p4p6p 并不是顺子。）

跑法：cd N:\apps\tianma\server; python test_diaoyu_options.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from game import Game                    # noqa: E402
import test_game as tg                   # noqa: E402
from tiles import parse_hand             # noqa: E402

PASS = FAIL = 0


def check(name, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  got {got!r} want {want!r}")


def fresh(tag, hand0, meld=None, seat3=None, drawn=""):
    db = tg.fresh_db(tag)
    rid, _m, _u = tg.new_round(db, seed=31)
    if drawn:
        tg.set_hand(db, rid, 0, hand0, drawn=drawn)
    else:
        tg.set_hand(db, rid, 0, hand0)
    tg.set_hand(db, rid, 1, parse_hand("1m4m7m1p4p7p1s4s7s1z2z3z"))
    tg.set_hand(db, rid, 2, parse_hand("2m5m8m2p5p8p2s5s8s2z3z4z"))
    tg.set_hand(db, rid, 3, seat3 or parse_hand("3m6m9m3p6p9p3s6s9s1z2z3z"))
    if meld is not None:
        with db.tx():
            db.conn.execute(
                "INSERT OR REPLACE INTO round_discards(round_id, seq, seat, wall_seq, tile,"
                " is_tsumogiri, is_riichi_tile, face_down, called)"
                " VALUES(?,?,?,?,?,1,0,0,0)", (rid, 400, 3, 9400, "4p"))
        db.meld(rid, 0, "chi", ["4p", "5p", "6p"], called_tile="4p",
                from_seat=3, from_discard_seq=400, rot_index=0)
    g = Game(db, rid)
    g.round_phase = "play"
    g.turn, g.phase = 0, "discard"
    g.save_flags()
    return Game(db, rid)


def main() -> int:
    print("=" * 74)
    print(" 钓鱼：能让他打出的牌（吃只能用真搭子，且不看副露牌）")
    print("=" * 74)

    # ── ① 用户报的局面：手里 4p6p（+副露 456p）→ 不能吃 3p ──────────────
    print("\n① 手牌 4p4p6p（副露 456p）→ 4p7p 剩在手里")
    # 先 4p4p5p6p6p，吃 4p5p6p 之后：手里剩 4p、7p
    g = fresh("dy_chi_46",
              parse_hand("4p4p5p6p6p7p1m2m3m5s6s7s9s9s"),
              meld=True)
    opts = g.diaoyu_options(0, 3)          # 3 号位是我的上家
    print("  上家能打出的牌:", opts)
    check("不能吃 3p（4p6p 不是搭子）", "3p" in opts, False)
    check("不能吃 7p", "7p" in opts, False)
    check("不能吃 2p", "2p" in opts, False)
    check("能吃 8p（6p+7p 真搭子）", "8p" in opts, True)
    check("能吃 5p（4p+6p 真搭子）", "5p" in opts, True)
    check("9s 对子 → 能碰", "9s" in opts, True)

    # ── ② 副露出去的牌不能替他凑搭子 ─────────────────────────────────────
    print("\n② 副露 456p 吃掉手里的 5p6p → 只剩 4p7p，不能吃 5p/6p")
    g2 = fresh("dy_meld_leak",
               parse_hand("4p5p6p7p1m2m3m5s6s8s9s9s"),
               meld=True)
    opts2 = g2.diaoyu_options(0, 3)
    print("  上家能打出的牌:", opts2)
    check("不能吃 5p（6p 已经副露）", "5p" in opts2, False)
    check("不能吃 6p", "6p" in opts2, False)
    check("不能吃 3p", "3p" in opts2, False)
    check("不能吃 8p", "8p" in opts2, False)

    # ── ③ 正常的吃：4p5p → 3p / 6p 都行 ─────────────────────────────────
    print("\n③ 手里 4p5p（无副露）→ 能吃 3p / 6p")
    g3 = fresh("dy_chi_45", parse_hand("4p5p1m2m3m5s6s7s9s9s1z2z3z"))
    opts3 = g3.diaoyu_options(0, 3)
    print("  上家能打出的牌:", opts3)
    check("能吃 3p（4p5p）", "3p" in opts3, True)
    check("能吃 6p（4p5p）", "6p" in opts3, True)
    check("不能吃 2p", "2p" in opts3, False)
    check("不能吃 7p", "7p" in opts3, False)

    # ── ④ 「吃」只对上家开放：对下家只列碰/杠/和 ──────────────────────────
    print("\n④ 同一个 4p5p 手牌：对下家（1 号位）不列吃")
    opts4 = g3.diaoyu_options(0, 1)
    print("  下家能打出的牌:", opts4)
    check("对下家不列 3p", "3p" in opts4, False)
    check("对下家不列 6p", "6p" in opts4, False)
    check("对下家仍列对子 9s（碰）", "9s" in opts4, True)

    # ── ⑤ 和（铳牌）照旧 ─────────────────────────────────────────────────
    print("\n⑤ 听牌：4p5p 之外的手牌听 3s 单骑 → 列表里有 3s")
    g5 = fresh("dy_ron", parse_hand("1m2m3m5p6p7p2s3s4s9s9s9s") + ["dong"])
    g5 = Game(g5.db, g5.round_id)
    opts5 = g5.diaoyu_options(0, 2)
    print("  对家能打出的牌:", opts5)
    check("列表非空", len(opts5) > 0)

    # ── ⑥ 赤 5：目标手里只有 0m，我手里 4m6m → 列表给 5m，发动要能成功 ────
    print("\n⑥ 赤 5（目标手里只有 0m）")
    g6 = fresh("dy_red5",
               parse_hand("4m6m1p2p3p5s6s7s9s9s1z2z3z"),
               seat3=parse_hand("0m1p4p7p2s5s8s3z4z5z6z7z") + ["9m"],
               drawn="xi")
    g6.granted = {0: {15}}
    g6.save_flags()
    g6 = Game(g6.db, g6.round_id)
    check("能钓鱼（有 15 号卡 + 刚摸牌）", g6.diaoyu_can(0))
    opts6 = g6.diaoyu_options(0, 3)
    print("  上家能打出的牌:", opts6)
    check("列表里有 5m（能吃）", "5m" in opts6)
    r6 = g6.diaoyu_force(0, 3, "5m")
    check("赤 5 也能钓出来（不再误判「他手里没有」）", r6.get("ok"), True)
    g6 = Game(g6.db, g6.round_id)
    mine = [o.get("action") for o in ((g6.pending or {}).get("options", {}).get(0) or [])]
    print("  我的鸣牌窗口:", mine)
    check("窗口里能吃", "chi" in mine)

    print("\n" + "=" * 74)
    print(f" 结果：{PASS} 项通过，{FAIL} 项失败")
    print("=" * 74)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
