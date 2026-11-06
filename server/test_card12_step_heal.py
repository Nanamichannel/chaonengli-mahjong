# -*- coding: utf-8 -*-
"""海神·挪宝计数（haishin_step）自愈回归。

用户 2026-11-06 现场：上一小局换满 3 次 → 新一小局**一次都没换**，
服务端 flags 里却还是 haishin_step={'0': 3} → 从此再也不发挪宝询问。

期望：
  · 载入 flags 时，step 只认 haishin_done 里「真的换过」的位置数
    （脏数据 3 没有记录 → 归 0，这一局重新开始问）
  · 每真的换一次 → haishin_done 多一条、step = 记录数
  · 三步换满 → 不再问

用法：cd server; python test_card12_step_heal.py
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")

from game import Game  # noqa: E402
from tiles import parse_hand  # noqa: E402
import test_game as tg  # noqa: E402

PASS = FAIL = 0


def check(name, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  got={got!r} want={want!r}")


H0 = parse_hand("123m456p789s") + ["1p", "1p", "5m", "5m"]
H1 = parse_hand("234m567p678s") + ["2p", "2p", "9m"]
H2 = parse_hand("2m5m8m2p5p8p2s5s8s") + ["2z", "3z", "4z", "5m"]
H3 = parse_hand("3m6m9m3p6p9p3s6s9s") + ["1z", "2z", "3z", "5z"]


def setup(tag, seed=7):
    db = tg.fresh_db(tag)
    rid, _m, _u = tg.new_round(db, seed=seed)
    tg.set_hand(db, rid, 0, H0)
    tg.set_hand(db, rid, 1, H1)
    tg.set_hand(db, rid, 2, H2)
    tg.set_hand(db, rid, 3, H3)
    g = Game(db, rid)
    g.round_phase = "play"
    g.granted = {0: {12: 1}}
    g.haishin_on = True
    g.phase, g.turn = "draw", 0
    g.save_flags()
    return db, rid


print("① 脏数据：step=3 但没有任何换宝记录 → 载入后归 0，还能问")
db, rid = setup("hs_heal")
raw = db.load_round_flags(rid)
raw["haishin_step"] = {"0": 3}
raw["haishin_swap_asked"] = {"0": "60-0"}
raw["haishin_turn_used"] = {"0": "60-0"}
db.save_round_flags(rid, raw)
g = Game(db, rid)
check("step 自愈成 0", int(g.haishin_step.get(0, 0)), 0)
check("swap_can 恢复", bool(g.haishin_swap_can(0)), True)

print("\n② 真的换一次 → 记录 +1，step=1")
r = g.haishin_swap(0, "5m")
check("真的换了（got 非空）", str(r.get("got", "")) != "", True)
check("step=1", int(g.haishin_step.get(0, 0)), 1)
check("记录 1 条", len(g.haishin_done.get(0) or []), 1)
g2 = Game(db, rid)
check("落库后再读还是 1", int(g2.haishin_step.get(0, 0)), 1)

print("\n③ 换满三步 → 不再问")
for i, t in enumerate(["1m", "2m"]):
    g2.phase, g2.turn = "draw", 0
    g2.haishin_turn_used.clear()          # 模拟「下一巡」
    g2.haishin_swap(0, t)
check("step=3", int(g2.haishin_step.get(0, 0)), 3)
check("swap_can=False", bool(g2.haishin_swap_can(0)), False)
g3 = Game(db, rid)
check("换满后重新载入仍是 3", int(g3.haishin_step.get(0, 0)), 3)
check("换满后不再问", bool(g3.haishin_swap_can(0)), False)

print("\n" + "=" * 70)
print(" 通过 %d 项，失败 %d 项" % (PASS, FAIL))
print("=" * 70)
sys.exit(1 if FAIL else 0)
