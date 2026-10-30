# -*- coding: utf-8 -*-
"""「宝牌 / 岭上」只能由杠触发（现场事故回归）

事故：一局里**一个杠都没有**，却翻了 3 张杠宝牌、摸走 2 张岭上牌、庄家手牌涨到 28 张。
原因：客户端可以随便发 op=draw（摸牌 / 岭上）和 op=dora（翻宝牌），服务端零校验。

现在的三层防线：
  ① api_cli 的 OPS 里没有 draw / dora（客户端根本发不进来）
  ② Game.reveal_dora() 校验 dora_revealed < 1 + 杠数
  ③ Game._draw_rinshan() 校验 rinshan_used < 杠数

跑法：cd N:\apps\tianma\server; python test_dora_kan_gate.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import api_cli                            # noqa: E402
from game import Game                     # noqa: E402
import test_game as tg                    # noqa: E402
from tiles import parse_hand              # noqa: E402

PASS = FAIL = 0


def check(name, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  got {got!r} want {want!r}")


def dora_rows(g) -> int:
    return int(g.db._one(
        "SELECT COUNT(*) FROM round_dora WHERE round_id=? AND kind='dora'",
        (g.round_id,)) or 0)


def main() -> int:
    print("=" * 74)
    print(" 宝牌 / 岭上只能由杠触发")
    print("=" * 74)

    # ── ① 入口层：OPS 里没有 draw / dora ────────────────────────────────
    print("\n① 客户端已经没有「自己摸牌 / 自己翻宝牌」的入口")
    check("OPS 里没有 draw", "draw" in api_cli.OPS, False)
    check("OPS 里没有 dora", "dora" in api_cli.OPS, False)
    r = api_cli.handle({"op": "dora", "seat": 0})
    check("发 op=dora 被当成不认识的 op", "不认识的 op" in str(r.get("error", "")))

    # ── ② 没有杠：底层函数也拒绝 ────────────────────────────────────────
    print("\n② 一个杠都没有 → 翻不出宝牌、摸不到岭上")
    db = tg.fresh_db("dora_gate")
    rid, _m, _u = tg.new_round(db, seed=41)
    tg.set_hand(db, rid, 0, parse_hand("1m1m1m1m2m3m4m5p6p7p8s9s9s"))
    g = Game(db, rid)
    g.round_phase = "play"
    g.turn, g.phase = 0, "discard"
    g.save_flags()

    check("开局就 1 张宝牌（配牌时翻的那张）", dora_rows(g), 1)
    check("杠数 = 0", g.kan_count(), 0)
    check("没有杠还想翻第 2 张 → 拒绝", g.reveal_dora(), None)
    check("宝牌还是 1 张", dora_rows(g), 1)
    check("没有杠还想摸岭上 → 拒绝", g._draw_rinshan(0), None)
    check("rinshan_used 没变", g.rinshan_used, 0)
    check("手牌没变多", len(g.hand(0)), 13)

    # ── ③ 真开一个暗杠：宝牌 / 岭上各放行一次 ──────────────────────────
    print("\n③ 暗杠 1m → 允许翻 1 张宝牌 + 摸 1 张岭上")
    db.meld(rid, 0, "ankan", ["1m", "1m", "1m", "1m"], called_tile="1m",
            from_seat=0, rot_index=-1)
    g = Game(db, rid)
    check("杠数 = 1", g.kan_count(), 1)
    check("应翻宝牌数 = 2", g.expected_dora(), 2)
    ev = g.reveal_dora()
    check("这一杠能翻宝牌", ev is not None)
    check("宝牌变 2 张", dora_rows(g), 2)
    check("同一杠不能再翻第 3 张", g.reveal_dora(), None)
    t = g._draw_rinshan(0)
    check("这一杠能摸岭上", bool(t))
    check("同一杠不能再摸第 2 张", g._draw_rinshan(0), None)

    # ── ④ 第二个杠再加一张 ──────────────────────────────────────────────
    print("\n④ 再开一个杠 → 又能各来一次")
    tg.set_hand(db, rid, 0, parse_hand("9s9s9s9s2m3m4m5p6p7p8p1z2z"))
    db.meld(rid, 0, "ankan", ["9s", "9s", "9s", "9s"], called_tile="9s",
            from_seat=0, rot_index=-1)
    g = Game(db, rid)
    check("杠数 = 2", g.kan_count(), 2)
    check("能翻第 3 张宝牌", g.reveal_dora() is not None)
    check("宝牌 3 张", dora_rows(g), 3)
    check("能摸这一杠的岭上（第 1 张）", bool(g._draw_rinshan(0)))
    check("能摸这一杠的岭上（第 2 张）", bool(g._draw_rinshan(0)))
    check("第 3 张岭上被拒（已经 2 张 = 杠数）", g._draw_rinshan(0), None)

    # ── ⑤ 里宝跟表宝同步 ────────────────────────────────────────────────
    print("\n⑤ 里宝和表宝张数一致")
    ura = int(g.db._one("SELECT COUNT(*) FROM round_dora WHERE round_id=? AND kind='ura'",
                        (rid,)) or 0)
    check("里宝 3 张", ura, 3)

    print("\n" + "=" * 74)
    print(f" 结果：{PASS} 项通过，{FAIL} 项失败")
    print("=" * 74)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
