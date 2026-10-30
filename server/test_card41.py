# -*- coding: utf-8 -*-
"""Card41 S1【复制】自测。

跑法：cd N:\\apps\\tianma\\server; python test_card41.py
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
from tiles import parse_hand                         # noqa: E402

PASS = FAIL = 0
H0 = "123m456m789m234p5z3s"


def check(name, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  got {got!r} want {want!r}")


def setup(tag):
    """seat0 拿 41；seat1 拿 28（满贯，配牌技能）；seat2 拿 33（染手，摸牌技能）。"""
    db, rid = t30.setup(tag, card=41, mains=[41, 28, 33, 6])
    tg.set_hand(db, rid, 0, parse_hand(H0), drawn="3s")
    with db.tx():
        db.conn.execute("DELETE FROM round_dora WHERE round_id=?", (rid,))
        db.conn.execute("DELETE FROM round_discards WHERE round_id=?", (rid,))
        db.conn.execute("DELETE FROM round_melds WHERE round_id=?", (rid,))
        db.conn.execute("DELETE FROM round_riichi WHERE round_id=?", (rid,))
    g = Game(db, rid)
    g.granted = {0: {41}}
    g.round_phase = "play"
    g.phase = "discard"
    g.turn = 0
    g.deal_wait = set()
    g.deal_used = set()
    g.save_flags()
    return db, rid


def pool_of(db, rid, seat=0):
    """延迟复制：这是一个「可复制池」（列表）。"""
    v = (Game(db, rid).state_for(seat).get("c41") or {}).get("ask")
    return list(v) if isinstance(v, list) else []


def ask_of(db, rid, seat=0):
    """池子里最上面那个（没有就 None）。"""
    v = pool_of(db, rid, seat)
    return v[-1] if v else None


def main() -> int:
    print("=" * 78)
    print(" Card41 S1【复制】")
    print("=" * 78)

    print("\n① 注册 / 时机")
    check("名字", skills.info(41, 1).get("name"), "复制")
    check("时机 = 任意", skills.timing(41, 1), "any")

    print("\n② 别人宣告「摸牌类」技能 → 我收到复制询问")
    db, rid = setup("c41a")
    g = Game(db, rid)
    g.c41s1_offer(2, 33, 1)                    # seat2 宣告「染手」（draw 时机）
    a = ask_of(db, rid)
    check("有询问", isinstance(a, dict), True)
    check("池子里 1 条", len(pool_of(db, rid)), 1)
    check("技能名", str((a or {}).get("name", "")), "染手")
    check("是谁发动", int((a or {}).get("target", -1)), 2)

    print("\n③ 复制 → 清单里多一条；能当成自己持有")
    g2 = Game(db, rid)
    r = g2.c41s1_copy(0)
    check("复制到 33-1", [int(r.get("card", 0)), int(r.get("skill", 0))], [33, 1])
    g3 = Game(db, rid)
    check("清单 1 条", len(g3.c41_copies.get(0, [])), 1)
    check("owns_card 认了", skills.owns_card(db, g3, 0, 33, strict=True), True)
    check("询问清掉", ask_of(db, rid), None)
    check("state.c41.copies", len(((g3.state_for(0).get("c41") or {}).get("copies") or [])), 1)

    print("\n④ 重复复制同一个 → 清单不重复")
    g4 = Game(db, rid)
    g4.c41s1_offer(2, 33, 1)
    g4 = Game(db, rid)
    g4.c41s1_copy(0)
    check("还是一条", len(Game(db, rid).c41_copies.get(0, [])), 1)

    print("\n⑤ 配牌时机的技能不可复制")
    db2, rid2 = setup("c41b")
    g5 = Game(db2, rid2)
    g5.c41s1_offer(1, 28, 1)                   # 满贯：timing=deal
    check("不挂询问", ask_of(db2, rid2), None)

    print("\n⑥ 自己发动的技能不挂询问")
    db3, rid3 = setup("c41c")
    g6 = Game(db3, rid3)
    g6.c41s1_offer(0, 33, 1)                   # actor 就是我
    check("不挂询问", ask_of(db3, rid3), None)

    print("\n⑦ 无限使用：再来一个不同的技能，又能复制")
    db4, rid4 = setup("c41d")
    g7 = Game(db4, rid4)
    g7.c41s1_offer(2, 33, 1)
    g7 = Game(db4, rid4)
    g7.c41s1_copy(0)
    g7 = Game(db4, rid4)
    g7.c41s1_offer(3, 6, 2)                    # 坚韧（settle）
    g7 = Game(db4, rid4)
    check("又挂上询问", isinstance(ask_of(db4, rid4), dict), True)
    g7.c41s1_copy(0)
    lst = Game(db4, rid4).c41_copies.get(0, [])
    check("清单两条", len(lst), 2)
    check("包含 6-2", any(int(x["card"]) == 6 and int(x["skill"]) == 2 for x in lst), True)

    print("\n⑧ 跳过 → 询问清掉、清单不变")
    db5, rid5 = setup("c41e")
    g8 = Game(db5, rid5)
    g8.c41s1_offer(2, 33, 1)
    g8 = Game(db5, rid5)
    g8.c41s1_skip(0)
    check("询问清掉", ask_of(db5, rid5), None)
    check("清单还是空", Game(db5, rid5).c41_copies.get(0, []), [])

    print("\n⑧b 延迟复制：技能照常进行、我过后还能复制（池子不过期）")
    db6, rid6 = setup("c41f")
    g6 = Game(db6, rid6)
    g6.c41s1_offer(2, 33, 1)
    g6.c41s1_offer(3, 37, 2)                 # 又发动了一个
    check("池子里攒了 2 个", len(pool_of(db6, rid6)), 2)
    g7 = Game(db6, rid6)
    r7 = g7.c41s1_copy(0, 37, 2)             # 指定复制「旧」的那个
    check("指定复制到 37-2", [int(r7.get("card", 0)), int(r7.get("skill", 0))], [37, 2])
    g8 = Game(db6, rid6)
    check("池子里还剩 1 个", len(pool_of(db6, rid6)), 1)
    check("剩下的是 33-1", int(ask_of(db6, rid6).get("card", 0)), 33)
    g8.c41s1_copy(0)                         # 不指定 = 取最新的
    check("池子清空", pool_of(db6, rid6), [])
    check("清单 2 条", len(Game(db6, rid6).c41_copies.get(0, [])), 2)

    print("\n⑨ 没有询问时复制 → 报错")
    try:
        Game(db5, rid5).c41s1_copy(0)
        check("被拒", False, True)
    except RuleError:
        check("被拒", True, True)

    print("\n" + "=" * 78)
    print(f" 通过 {PASS} / 失败 {FAIL}")
    print("=" * 78)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
