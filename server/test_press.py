# -*- coding: utf-8 -*-
"""Card03 S2「压制」自测（2026-10-25 新口径）

· 每次摸牌后只能交换一次（换明牌 / 换暗置牌都一样）
· 换暗置牌以前是「不限次数」→ 会和自己的弃牌反复换、反复问看破，现在堵住
· 必须真的持 Card03（strict）
· 看破只问一次（ONCE_PAIRS 含 (3,2)）
· 发动要记账（卡面翻明）+ press_win（这一手自摸不算边张/嵌张符）
"""
from __future__ import annotations

import io
import json
import sys

sys.path.insert(0, r'N:\apps\tianma\server')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from game import Game, RuleError, ONCE_PAIRS  # noqa: E402
import test_game as tg  # noqa: E402

OK = 0
BAD = 0
HAND = ["1m", "2m", "3m", "4m", "5m", "7m", "8m", "9m", "1s", "2s", "3s", "4s", "6s", "5p"]


def check(cond, msg):
    global OK, BAD
    if cond:
        OK += 1
    else:
        BAD += 1
        print("  [FAIL]", msg)


def set_orders(db, orders):
    body = {"seats": [{"ready": False, "hand": [], "picks": [], "order": list(o)}
                      for o in orders], "phase": "playing"}
    with db.tx():
        db.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('lobby_state', ?)",
                        (json.dumps(body, ensure_ascii=False),))


def fresh(tag, orders, grant=True):
    db = tg.fresh_db(tag)
    set_orders(db, orders)
    rid, _m, _u = tg.new_round(db, seed=71)
    tg.set_hand(db, rid, 0, HAND, drawn="5p")
    with db.tx():
        for seq, seat, wseq, tile, down in ((600, 0, 9500, "3p", 0),
                                            (601, 0, 9501, "4p", 0),
                                            (700, 2, 9600, "9s", 1),
                                            (701, 2, 9601, "9s", 1)):
            db.conn.execute(
                "INSERT INTO round_discards(round_id, seq, seat, wall_seq, tile, called,"
                " is_riichi_tile, face_down) VALUES(?,?,?,?,?,0,0,?)",
                (rid, seq, seat, wseq, tile, down))
    g = Game(db, rid)
    if grant:
        g.granted = {0: {3}}
    g.phase, g.turn = "discard", 0
    g.save_flags()
    return db, rid, g


def main():
    # 座位卡序：0 号位东一..都是 3 号卡；另造一个没 3 号卡的
    ORDERS = [[3, 3, 3, 3, 4], [1, 2, 3, 4, 5], [6, 7, 8, 9, 10], [11, 12, 13, 14, 15]]
    db, rid, g = fresh("press2", ORDERS)

    # ① 换自己牌河的明牌：成功 + 记账
    print("① 换自己牌河的明牌")
    check(bool(g.press_can(0)), "刚摸牌、没换过 → press_can")
    r = g.suppress_swap(0, "5m", 600)
    check(r.get("mode") == "own", f"mode 应该是 own，实际 {r}")
    check(r.get("got") == "3p", f"应该换到 3p，实际 {r}")
    g = Game(db, rid)
    hand = [str(x) for x in g.hand(0)]
    check("3p" in hand and "5m" not in hand, f"换牌没生效，实际 {hand}")
    check(0 in g.press_used, f"应该记「这次摸牌换过了」，实际 {g.press_used}")
    check(0 in g.press_win, f"应该记 press_win，实际 {g.press_win}")
    check(not g.press_can(0), "换过之后 press_can 应该是 False")
    st = {c["seat"]: c for c in g._char_states()}
    check(bool((st[0].get("main") or {}).get("open")) is True, "3 号卡应该翻明")

    # ② 同一次摸牌里再换（暗置牌）：也要拒绝
    print("\n② 同一次摸牌里再换（连暗置牌也不行）")
    try:
        g.suppress_swap(0, "4m", 700)
        check(False, "同一次摸牌第二次换应该被拒")
    except RuleError as e:
        check("已经交换过" in str(e), f"报错文案不对：{e}")

    # ③ 下一巡（重新摸牌）→ 又能换一次（暗置牌）
    print("\n③ 下次摸牌后又能换一次")
    g3 = Game(db, rid)
    g3.granted = {0: {3}}
    g3.phase, g3.turn = "discard", 0
    g3.save_flags()
    g3._draw_common(0)                      # 真摸一张 → 顺手清掉 press_used
    g3 = Game(db, rid)
    check(0 not in g3.press_used, f"摸牌后标记应该清掉，实际 {g3.press_used}")
    g3.granted = {0: {3}}
    g3.phase, g3.turn = "discard", 0
    g3.save_flags()
    r = g3.suppress_swap(0, "4m", 700)
    check(r.get("mode") == "down", f"换暗置牌 mode 应该是 down，实际 {r}")
    check(r.get("got") == "9s", f"应该换到 9s，实际 {r}")
    g4 = Game(db, rid)
    g4.granted = {0: {3}}
    g4.phase, g4.turn = "discard", 0
    g4.save_flags()
    try:
        g4.suppress_swap(0, "2m", 701)
        check(False, "同一次摸牌里第二张暗置牌也应该被拒")
    except RuleError as e:
        check("已经交换过" in str(e), f"报错文案不对：{e}")

    # ④ 没持 Card03 → 不能换
    print("\n④ 没持 Card03")
    db2, rid2, g5 = fresh("press3", [[1, 2, 4, 5, 6], [1, 2, 3, 4, 5],
                                     [6, 7, 8, 9, 10], [11, 12, 13, 14, 15]], grant=False)
    check(not g5.press_can(0), "没持卡 → press_can 应该是 False")
    try:
        g5.suppress_swap(0, "5m", 600)
        check(False, "没持卡应该被拒")
    except RuleError as e:
        check("人物卡" in str(e), f"报错文案不对：{e}")

    # ⑤ 看破只问一次
    print("\n⑤ 看破")
    check((3, 2) in ONCE_PAIRS, "压制应该进 ONCE_PAIRS（看破只问一次）")

    print(f"\n通过 {OK} / 失败 {BAD}")
    return 1 if BAD else 0


if __name__ == "__main__":
    sys.exit(main())
