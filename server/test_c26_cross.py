# -*- coding: utf-8 -*-
"""Card26 S2「天梯」跨局自测

用户口径（2026-11-05）：
  「天梯应该可以看 n+1 张牌，实测胡牌完一把后第二把没有 +1」

根因：c26_n / c26s2_on 存在 round_flags 里，每开新一局就被清空 → n 又变回 1。
修法：存 meta，key = c26_state_<match_id>（半庄级），换半庄自然重置。

跑法：cd N:\apps\tianma\server; python test_c26_cross.py
"""
from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from game import Game                 # noqa: E402
import test_game as tg                # noqa: E402
from tiles import parse_hand          # noqa: E402

PASS = FAIL = 0

H0 = "123m456m789m5p5p6s7s9s"
H1 = "1m4m7m1p4p7p1s4s7s1z2z3z"
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


def arm_round(db, rid, seed=0):
    """把这一局的配牌窗口摆好，让 0 号位能发天梯。"""
    for s, h in enumerate((H0, H1, H2, H3)):
        tg.set_hand(db, rid, s, parse_hand(h))
    g = Game(db, rid)
    g.granted = {0: {26}}
    g.round_phase = "play"
    g.phase = "deal_skill"
    g.deal_wait = {0}
    g.deal_deadline = time.time() + 20.0
    g.save_flags()
    return g


def main() -> int:
    print("=" * 78)
    print(" Card26 S2「天梯」：n 要跨局保留")
    print("=" * 78)

    db = tg.fresh_db("c26x")
    rid1, match, _uids = tg.new_round(db, seed=97)
    orders = [[26, 1, 2, 3, 5], [4, 1, 2, 3, 5], [6, 1, 2, 3, 5], [7, 1, 2, 3, 5]]
    with db.tx():
        db.conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES('lobby_state', ?)",
            (json.dumps({"seats": [{"order": o} for o in orders]}, ensure_ascii=False),))

    # ── 第 1 小局：发天梯 → n=1 → 连续和两次 ───────────────────────────
    print("\n① 第 1 小局：发天梯，连续和牌 2 次 → n=3")
    g = arm_round(db, rid1)
    r = g.deal_action(0, "use", 26, 2)
    check("天梯发动成功", r.get("armed"), True)
    g = Game(db, rid1)
    check("n 初始 1", g.c26_n.get(0), 1)
    check("排牌张数 = 1+n = 2", g.c26_count(0), 2)

    g._c26_commit(0, 2000)          # 第一次和牌（没有大小要求）
    g._c26_commit(0, 3900)          # 第二次和牌（> 2000+300）
    check("本局内 n 涨到 3", g.c26_n.get(0), 3)
    g.save_flags()

    # ── 第 2 小局（同一半庄）：n 应该还是 3 ────────────────────────────
    print("\n② 第 2 小局（同一半庄）：n 不能丢")
    rid2 = db.start_round(match, "dong", 2, honba=0, dealer_seat=1, seed=98)
    g2 = Game(db, rid2)
    check("新一局的 round_flags 里确实没有天梯",
          db.load_round_flags(rid2).get("c26_n"), None)
    check("从 meta 接回来了：n=3", g2.c26_n.get(0), 3)
    check("「本局开没开」不复用：新一局要重新发", 0 in g2.c26s2_on, False)
    check("上次得点还在", g2.c26_last.get(0), 3900)
    check("排牌张数 = 1+3 = 4 张", g2.c26_count(0), 4)

    g2 = arm_round(db, rid2)
    r2 = g2.deal_action(0, "use", 26, 2)
    check("新一局再发天梯", r2.get("armed"), True)
    check("不是 already（是这一局重新发的）", bool(r2.get("already")), False)
    g2b = Game(db, rid2)
    check("重新发牌没把 n 打回 1", g2b.c26_n.get(0), 3)
    check("新一局排牌还是 4 张", g2b.c26_count(0), 4)

    g2b.turn, g2b.phase = 0, "draw"
    g2b.save_flags()
    g2c = Game(db, rid2)
    g2c.turn, g2c.phase = 0, "draw"
    g2c.save_flags()
    g2d = Game(db, rid2)
    check("轮到自己摸牌 → 能排", g2d.c26_can_sort(0), True)
    check("给出发动者 4 张牌面", len(g2d.c26_view(0)), 4)

    # ── 第 3 小局：再 +1 → n=4 ──────────────────────────────────────
    print("\n③ 第 3 小局：接着 +1 → n=4（5 张）")
    g2d._c26_commit(0, 6000)
    rid3 = db.start_round(match, "dong", 3, honba=0, dealer_seat=2, seed=99)
    g3 = Game(db, rid3)
    check("n=4", g3.c26_n.get(0), 4)
    check("排牌 5 张", g3.c26_count(0), 5)

    # ── 断连（_c26_fail）要写进 meta ────────────────────────────────
    print("\n④ 断连被罚 → n 清零，下一局从 1+n=2 张重新来")
    g3f = Game(db, rid3)
    g3f.c26s2_on = {0}
    g3f._c26_fail(0, 100, {"yaku": []})
    rid4 = db.start_round(match, "dong", 4, honba=0, dealer_seat=3, seed=100)
    g4 = Game(db, rid4)
    check("断连后 n=1", g4.c26_n.get(0), 1)
    check("上次得点清掉", g4.c26_last.get(0), -1)

    # ── 换半庄 → 清零 ─────────────────────────────────────────────
    print("\n⑤ 换半庄：meta 换了 key，n 从 1 重新开始")
    g4.c26s2_on = {0}                 # 这一局也发天梯（进度才继续涨）
    g4._c26_commit(0, 8000)
    rid5 = db.start_round(match, "dong", 5, honba=0, dealer_seat=0, seed=101)
    check("同一半庄内 n 继续涨", Game(db, rid5).c26_n.get(0), 2)
    _u2 = [db.create_user(f"y2_{i}") for i in range(4)]
    _room2 = db.create_room(_u2[0])
    for _u in _u2[1:]:
        db.join_room(_room2["room_code"], _u)
    m2 = db.start_match(_room2["room_id"], seed=5)
    rid6 = db.start_round(m2, "dong", 1, honba=0, dealer_seat=0, seed=6)
    g6 = Game(db, rid6)
    check("新半庄：meta 是空的", g6.c26_n, {})
    check("新半庄：天梯没开", g6.c26s2_on, set())

    # ── 理论战作废：只清本局的排牌机会，半庄级进度保留 ──────────────────
    print("\n⑥ 理论战作废：本局不能再排，但半庄级 n 不会被抹掉")
    rid7 = db.start_round(match, "dong", 6, honba=0, dealer_seat=1, seed=102)
    g7 = arm_round(db, rid7)
    g7.deal_action(0, "use", 26, 2)
    g7 = Game(db, rid7)
    check("发完之后 n=2（前面攒的）", g7.c26_n.get(0), 2)
    g7._c42s1_void_deal()
    g7.save_flags()
    g7b = Game(db, rid7)
    check("本局不能再排牌", 0 in g7b.c26s2_on, False)
    check("半庄级 n 还在（没被对家的理论战抹掉）", g7b.c26_n.get(0), 2)
    check("上次得点也还在", g7b.c26_last.get(0), 8000)

    print("\n" + "=" * 78)
    print(f" 通过 {PASS} / 失败 {FAIL}")
    print("=" * 78)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
