# -*- coding: utf-8 -*-
"""七对子的花色系役种：混一色 / 清一色 / 混老头。

跑法：cd server; python test_yaku_chiitoi.py

背景（2026-11-08 实机）：round 5 的 3 号位和了
  4s4s5s5s7s7s8s8s + 南南 + 北北 + 东（荣东 = 七对子）
只给了「立直 1 + 七对子 2 = 3 番 25 符」，**漏了混一色 3 番**（正解 6 番 跳满）。
根因：`yaku.judge()` 给七对子的候选是 `((), -1)`（没有面子分解、没有将），
而 混一色 / 清一色 / 混老头 都只看 `sets` / `pair` → 七对子这一支永远是空集。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")

from game import Game          # noqa: E402
import test_card30 as t30      # noqa: E402
import test_game as tg         # noqa: E402

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


def judge(tag, hand13, win, riichi=False):
    """13 张 + 和到 win → (yaku 名字表, han, fu, 点数)"""
    db, rid = t30.setup(tag, card=8)
    for s in range(4):
        tg.set_hand(db, rid, s, list(hand13))
    with db.tx():
        for t in ("round_dora", "round_discards", "round_riichi"):
            db.conn.execute("DELETE FROM %s WHERE round_id=?" % t, (rid,))
        if riichi:
            db.conn.execute("INSERT INTO round_riichi(round_id, seat, declared_seq, ippatsu)"
                            " VALUES(?,1,0,0)", (rid,))
    g = Game(db, rid)
    g.round_phase = "play"
    g.phase = "discard"
    g.turn = 0
    res = g._judge_win(1, win, tsumo=False)
    if res is None:
        return [], 0, 0, {}
    return ([str(y["name"]) for y in res["yaku"]], int(res["han"]), int(res["fu"]),
            res.get("pays") or {})


def main() -> int:
    print("=" * 74)
    print(" 七对子 × 混一色 / 清一色 / 混老头")
    print("=" * 74)

    print("\n① 实机那一手：索子 + 字牌的七对子（立直）→ 混一色 必须有")
    h1 = ["4s", "4s", "5s", "5s", "7s", "7s", "8s", "8s",
          "nan", "nan", "bei", "bei", "dong"]
    y, han, fu, pays = judge("yct1", h1, "dong", riichi=True)
    print("     yaku =", y, "han =", han, "fu =", fu)
    check("判出混一色", "混一色" in y, True)
    check("混一色 门清 3 番", y.count("混一色") and han >= 6, True)
    check("立直 + 混一色 + 七对子 = 6 番", han, 6)
    check("6 番 = 跳满 12000", int(pays.get("total", 0)), 12000)

    print("\n② 清一色七对子 → 清一色 6 番 + 七对子 2 番 = 8 番")
    h2 = ["1m", "1m", "2m", "2m", "3m", "3m", "4m", "4m",
          "5m", "5m", "6m", "6m", "7m"]
    y2, han2, fu2, pays2 = judge("yct2", h2, "7m")
    print("     yaku =", y2, "han =", han2)
    check("判出清一色", "清一色" in y2, True)
    check("清一色 + 七对子 = 8 番", han2, 8)
    check("8 番 = 倍满 16000", int(pays2.get("total", 0)), 16000)

    print("\n③ 混老头七对子（七个幺九对子）→ 混老头 2 + 七对子 2 = 4 番")
    h3 = ["1m", "1m", "9m", "9m", "1p", "1p", "9p", "9p",
          "1s", "1s", "9s", "9s", "dong"]
    y3, han3, fu3, _ = judge("yct3", h3, "dong")
    print("     yaku =", y3, "han =", han3)
    check("判出混老头", "混老头" in y3, True)
    check("判出七对子", "七对子" in y3, True)
    check("混老头 + 七对子 = 4 番", han3, 4)

    print("\n④ 对照组：三门花的七对子 → 不许白送混一色")
    h4 = ["1m", "1m", "2m", "2m", "4p", "4p", "5p", "5p",
          "6s", "6s", "7s", "7s", "8s"]
    y4, han4, fu4, _ = judge("yct4", h4, "8s")
    print("     yaku =", y4, "han =", han4)
    check("没有混一色", "混一色" in y4, False)
    check("没有清一色", "清一色" in y4, False)
    check("只有七对子 2 番", han4, 2)

    print("\n⑤ 回归：普通（非七对子）的混一色 / 清一色 / 混老头 照旧")
    # 123m456m789m + 东东东 + 1m，荣 1m（将）：混一色 + 一气通贯，不是四暗刻
    h5 = ["1m", "2m", "3m", "4m", "5m", "6m", "7m", "8m",
          "9m", "dong", "dong", "dong", "1m"]
    y5, han5, fu5, _ = judge("yct5", h5, "1m")
    print("     yaku =", y5, "han =", han5)
    check("普通手照常判混一色", "混一色" in y5, True)

    # 清一色 + 平和（门清顺子）
    h6 = ["1m", "2m", "3m", "4m", "5m", "6m", "7m", "8m",
          "9m", "2m", "3m", "4m", "5m"]
    y6, han6, fu6, _ = judge("yct6", h6, "5m")
    print("     yaku =", y6, "han =", han6)
    check("普通手照常判清一色", "清一色" in y6, True)

    # 混老头（非七对子）：111m 999m 1p1p 东东东 + 南南，荣 1p
    #   （荣和补齐的那个刻子是明刻 → 三暗刻 + 混老头 + 对对和，不是四暗刻）
    h7 = ["1m", "1m", "1m", "9m", "9m", "9m", "1p", "1p",
          "dong", "dong", "dong", "nan", "nan"]
    y7, han7, fu7, _ = judge("yct7", h7, "1p")
    print("     yaku =", y7, "han =", han7)
    check("普通手照常判混老头", "混老头" in y7, True)

    print("\n" + "=" * 74)
    print(f" 合计：{PASS} 断言，{FAIL} 失败")
    print("=" * 74)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
