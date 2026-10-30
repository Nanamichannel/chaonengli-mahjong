# -*- coding: utf-8 -*-
"""人物卡寿命：一张卡存活两个风场（= 两个小局）。

用户口径（2026-10-25）：东一/东二/东三/东四/南一/南二/南三/南四 是八个风场，
一张卡存活两个风场；本场（连庄 honba）与卡寿命无关。

旧实现用「卡槽号 0..3」（东一二=0、东三四=1、南一二=2、南三四=3）算寿命
→ 东一用过的卡到南一二就废了（少算一个风场），协战卡也会「悄悄过期」，
表现就是「钓鱼/压制的图标没锁，但一次也用不了」。
"""
from __future__ import annotations

import io
import json
import sys

sys.path.insert(0, r'N:\apps\tianma\server')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import skills  # noqa: E402
import test_game as tg  # noqa: E402

OK = 0
BAD = 0


def check(cond, msg):
    global OK, BAD
    if cond:
        OK += 1
    else:
        BAD += 1
        print("  [FAIL]", msg)


class FakeG:
    """只给 skills 用：round_wind / round / granted / poked"""

    def __init__(self, wind, number, honba=0):
        self.round_wind = wind
        self.round = {"number": number, "honba": honba}
        self.granted = {}
        self.poked = set()


def setup_db(tag, order, char_use):
    db = tg.fresh_db(tag)
    seats = [{"ready": False, "hand": [], "picks": [], "order": [1, 2, 3, 4, 5]}
             for _ in range(4)]
    seats[0] = {"ready": False, "hand": [], "picks": [], "order": list(order)}
    with db.tx():
        db.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('lobby_state', ?)",
                        (json.dumps({"seats": seats, "phase": "playing"},
                                    ensure_ascii=False),))
        db.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('char_use', ?)",
                        (json.dumps(char_use, ensure_ascii=False),))
    return db


def main():
    print("① 局号（0..7）")
    check(skills._round_no("dong", 1) == 0, "东一 = 0")
    check(skills._round_no("dong", 4) == 3, "东四 = 3")
    check(skills._round_no("nan", 1) == 4, "南一 = 4")
    check(skills._round_no("nan", 4) == 7, "南四 = 7")

    print("\n② 存活两个风场（东一用 → 东一/东二行，东三废）")
    db = setup_db("clife1", [3, 3, 3, 3, 15], {"0:3": 0, "0:15": 0})
    for wind, num, want in (("dong", 1, False), ("dong", 2, False),
                            ("dong", 3, True), ("dong", 4, True),
                            ("nan", 1, True), ("nan", 4, True)):
        g = FakeG(wind, num)
        got = skills.char_expired(db, g, 0, 3)
        check(got == want, f"{wind}{num} 过期应该是 {want}，实际 {got}")

    print("\n③ 本场（连庄）不影响寿命")
    g1 = FakeG("dong", 2, honba=0)
    g2 = FakeG("dong", 2, honba=5)
    check(skills.char_expired(db, g1, 0, 3) == skills.char_expired(db, g2, 0, 3),
          "本场 0 和本场 5 的过期判定应该一样")

    print("\n④ 协战卡（order[4]）也是两个风场，不会提前废")
    check(skills.owns_card(db, FakeG("dong", 2), 0, 15, strict=True),
          "东二：协战 15 还应该能用")
    check(not skills.owns_card(db, FakeG("dong", 3), 0, 15, strict=True),
          "东三：协战 15 应该失效")
    check(skills.char_expired(db, FakeG("dong", 3), 0, 15), "东三：15 判过期")

    print("\n⑤ owns_card 跟着寿命走（主战卡）")
    check(skills.owns_card(db, FakeG("dong", 2), 0, 3, strict=True), "东二：3 号卡还能用")
    check(not skills.owns_card(db, FakeG("nan", 1), 0, 3, strict=True), "南一：3 号卡应该失效")
    check(skills.char_expired(db, FakeG("nan", 1), 0, 3), "南一：判过期")

    print("\n⑥ 从没用过的卡不过期")
    db2 = setup_db("clife2", [3, 3, 3, 3, 15], {})
    check(not skills.char_expired(db2, FakeG("nan", 4), 0, 3), "南四：没用过就不过期")
    check(skills.owns_card(db2, FakeG("nan", 4), 0, 3, strict=True), "南四：还能用")

    print(f"\n通过 {OK} / 失败 {BAD}")
    return 1 if BAD else 0


if __name__ == "__main__":
    sys.exit(main())
