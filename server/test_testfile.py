# -*- coding: utf-8 -*-
"""Test.txt（指定人物卡 / 起始手牌 / 牌山）自测
跑法： python test_testfile.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")

import lobby  # noqa: E402
import testfile  # noqa: E402
import test_game as tg  # noqa: E402

PASS = 0
FAIL = 0
HERE = os.path.dirname(os.path.abspath(__file__))
SPEC = os.path.join(HERE, "data", "_test_Test.txt")


def check(name, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  got={got!r} want={want!r}")


def write_spec(text: str) -> None:
    with open(SPEC, "w", encoding="utf-8") as f:
        f.write(text)
    testfile.PATH = SPEC


def clear_spec() -> None:
    testfile.PATH = os.path.join(HERE, "data", "_test_Test_none.txt")


def main() -> int:
    print("=" * 70)
    print(" 天马麻将 · Test.txt 指定内容")
    print("=" * 70)

    # ── 1. 牌名写法 ────────────────────────────────────────────────
    print("\n① 牌名解析")
    check("紧凑式 123m77z", testfile.parse_tiles("123m11z"),
          ["1m", "2m", "3m", "dong", "dong"])
    check("实体编号 1m01 0p01", testfile.parse_tiles("1m01 0p01"), ["1m", "0p"])
    check("空格 / 中文风牌", testfile.parse_tiles("1m 2m dong"), ["1m", "2m", "dong"])

    # ── 2. 人物卡：指定的编号一定在 20 张里 ─────────────────────────
    print("\n② 人物卡")
    write_spec("[人物卡]\n01 08\n")
    db = tg.fresh_db("tf_cards")
    lb = lobby.load(db)
    lobby.start_draft(lb)
    pool = lb["pool"]
    check("还是 20 张", len(pool), 20)
    check("没有重复", len(set(pool)), 20)
    check("包含 01", 1 in pool, True)
    check("包含 08", 8 in pool, True)
    check("一家 5 张", [len(s["hand"]) for s in lb["seats"]], [5, 5, 5, 5])
    check("20 张都被四家分完", sum(len(s["hand"]) for s in lb["seats"]), 20)
    db.close()

    # ── 3. 起始手牌：配牌直接发指定的牌 ────────────────────────────
    print("\n③ 起始手牌（东一 0 本场）")
    hand0 = "1m2m3m4p5p6p7s8s9s1z1z2z2z5z"
    hand1 = "2m3m4m5p6p7p8s9s1s2z2z3z3z"
    hand2 = "3m4m5m6p7p8p9s1s2s3z3z4z4z"
    hand3 = "4m5m6m7p8p9p1s2s3s4z4z5z5z"
    write_spec("[手牌]\n0: %s\n1: %s\n2: %s\n3: %s\n" % (hand0, hand1, hand2, hand3))
    db = tg.fresh_db("tf_hands")
    rid, _m, _u = tg.new_round(db, seed=31)
    g = __import__("game").Game(db, rid)
    check("0 号位（庄家）14 张对得上", g.hand(0), testfile.parse_tiles(hand0))
    check("1 号位 13 张对得上", g.hand(1), testfile.parse_tiles(hand1))
    check("2 号位 13 张对得上", g.hand(2), testfile.parse_tiles(hand2))
    check("3 号位 13 张对得上", g.hand(3), testfile.parse_tiles(hand3))
    check("庄家最后一张是摸到的", g.drawn_tile(0), "bai")
    ents = [r["entity"] for r in db._rows(
        "SELECT entity FROM round_wall WHERE round_id=? ORDER BY seq", (rid,))]
    check("136 张实体编号没有重复", len(set(ents)), 136)
    db.close()

    # ── 4. 牌山：指定前几张 ────────────────────────────────────────
    print("\n④ 牌山")
    write_spec("[牌山]\n9p 9p 9p 9p 1s 1s\n")
    db = tg.fresh_db("tf_wall")
    rid, _m, _u = tg.new_round(db, seed=32)
    tiles = [r["tile"] for r in db._rows(
        "SELECT tile FROM round_wall WHERE round_id=? ORDER BY seq LIMIT 6", (rid,))]
    check("前 6 张按写的来", tiles, ["9p", "9p", "9p", "9p", "1s", "1s"])
    ents = [r["entity"] for r in db._rows(
        "SELECT entity FROM round_wall WHERE round_id=?", (rid,))]
    check("实体编号仍然唯一", len(set(ents)), 136)
    db.close()

    # ── 5. 什么都没写 = 和正式一样随机 ─────────────────────────────
    print("\n⑤ 留空 / 没有文件 → 随机")
    clear_spec()
    db = tg.fresh_db("tf_none")
    lb2 = lobby.load(db)
    lobby.start_draft(lb2)
    check("随机 20 张", len(lb2["pool"]), 20)
    check("随机池不重复", len(set(lb2["pool"])), 20)
    rid2, _m2, _u2 = tg.new_round(db, seed=33)
    g2 = __import__("game").Game(db, rid2)
    check("手牌按正常配牌（庄家 14 张）", (len(g2.hand(0)), len(g2.hand(1))), (14, 13))
    check("没有命中测试手牌", g2.hand(0) != testfile.parse_tiles(hand0), True)
    db.close()

    for d in tg._OPEN_DBS:
        try:
            d.close()
        except Exception:
            pass
    for f in ("_test_Test.txt",):
        p = os.path.join(HERE, "data", f)
        if os.path.exists(p):
            os.remove(p)

    print("\n" + "=" * 70)
    print(f" 通过 {PASS} 项，失败 {FAIL} 项")
    print("=" * 70)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
