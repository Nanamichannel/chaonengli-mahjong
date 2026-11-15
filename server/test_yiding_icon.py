# -*- coding: utf-8 -*-
"""前路（20-1）三张全中拿到「一定和牌」之后，图标还是灰的、点不动（2026-11-14 用户报）

根因：客户端 `_apply_used_skills()` 只看 `used_skills`，前路一发动就被记成「用过」→
      图标置灰；可它的产物是**一定和牌的权限**，玩家还要点同一个图标去宣言。
      馈赠 21-2 早有一条「跳过置灰」的特例，前路没有 → 于是灰。

本测试守三件事：
  ① 服务端：前路三张全中 → 真的给出权限，且 **来源记成 [20,1]**、**落盘不丢**
  ② 服务端：已有权限时再授予，来源要跟着最后一笔走（馈赠→前路 的先后顺序不会漏）
  ③ 客户端：`_apply_used_skills()` 用「一定和牌来源」解锁图标，不再按卡号特判
"""
from __future__ import annotations

import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")

from game import Game                    # noqa: E402
from tiles import parse_hand             # noqa: E402
import test_game as tg                   # noqa: E402
import test_chuancheng_copy as tc        # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
CLIENT = os.path.join(os.path.dirname(HERE), "main.gd")

PASS = 0
FAIL = 0


def check(name, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print("  [OK]   %s" % name)
    else:
        FAIL += 1
        print("  [FAIL] %s  got=%r want=%r" % (name, got, want))


def make_ql(tag, seed):
    """座位 0 持 20，轮到 0 打牌，前路已经预言了两张、第三张正要切"""
    db = tg.fresh_db(tag)
    tc.set_orders(db, [[20, 20, 20, 20, 20], [1, 2, 3, 4, 5],
                       [1, 2, 3, 4, 6], [1, 2, 3, 4, 7]])
    rid, _m, _u = tg.new_round(db, seed=seed)
    tg.set_hand(db, rid, 0, parse_hand("123m456p789s1z2z3z"))
    for s, hand in ((1, "1m4m7m1p4p7p1s4s7s1z2z3z"),
                    (2, "2m5m8m2p5p8p2s5s8s2z3z4z"),
                    (3, "3m6m9m3p6p9p3s6s9s1z1z2z")):
        tg.set_hand(db, rid, s, parse_hand(hand))
    g = Game(db, rid)
    g.granted = {0: {20}}
    g.round_phase = "play"
    g.turn, g.phase = 0, "discard"
    g.save_flags()
    return db, rid


def main() -> int:
    print("=" * 70)
    print(" 天才麻将少女 · 前路 20-1：一定和牌权限拿到后图标不能是灰的")
    print("=" * 70)

    print("\n① 前路三张全中 → 给权限 + 记来源 + 落盘")
    db, rid = make_ql("ql20", 2020)
    g = Game(db, rid)
    g.qianlu = {"seat": 0, "pred": ["5m", "5p", "5s"], "idx": 2}
    g.save_flags()
    g._after_discard_hooks(0, "5s")            # 第三张也中了
    check("拿到一定和牌权限", 0 in g.yiding, True)
    check("来源记成前路 [20,1]", g.yiding_src_of(0), [20, 1])
    check("前路状态已清空", g.qianlu, None)

    g2 = Game(db, rid)                          # 换一个实例 = 走 load_flags（api_cli 每次请求都这样）
    check("重开实例仍持有权限（落盘没漏）", 0 in g2.yiding, True)
    check("重开实例来源仍是 [20,1]", g2.yiding_src_of(0), [20, 1])
    st = g2.state_for(0)
    check("state.yiding=True（客户端就靠它判）", bool(st.get("yiding")), True)
    check("state.yiding_src=[20,1]",
          [int(x) for x in (st.get("yiding_src") or [])], [20, 1])

    print("\n② 已经持有权限时再授予 → 来源跟着最后一笔走")
    g3 = Game(db, rid)
    g3.yiding_grant(0, 21, 2)                   # 模拟「馈赠先授予」
    check("来源先变 21-2", g3.yiding_src_of(0), [21, 2])
    g3.yiding_grant(0, 20, 1)                   # 前路后满足
    check("来源更新为 20-1（不会卡在馈赠上）", g3.yiding_src_of(0), [20, 1])
    g4 = Game(db, rid)
    check("这次更新也落盘了", g4.yiding_src_of(0), [20, 1])

    print("\n③ 客户端：用「一定和牌来源」解锁图标")
    src = io.open(CLIENT, encoding="utf-8").read()
    check("有 _yiding_from() 判据", "func _yiding_from(st: Dictionary, card: int, skill: int) -> bool" in src)
    check("判据读 state.yiding_src", 'var src = st.get("yiding_src")' in src)
    check("_apply_used_skills 里按来源跳过置灰",
          "if _yiding_from(st, int(parts[0]), int(parts[1])):" in src)
    i_apply = src.find("func _apply_used_skills")
    i_use = src.find("if _yiding_from(st, int(parts[0]), int(parts[1])):")
    check("跳过置灰那句确实在 _apply_used_skills 里",
          i_apply >= 0 and i_use > i_apply, True)
    # ★ 2026-11-15：判据从 state.yiding_can（"现在能宣言"）改成
    #   「有权限（yiding_src=[20,1]）就进一定和牌面板」——否则三张全中后
    #   点图标会掉进 _sf_qianlu()，把前路重新武装成选牌界面。
    check("前路图标按「有没有权限」进一定和牌面板",
          'if _yiding_from(srv_state, 20, 1):' in src
          and "_yiding_on_clicked()       # 前路成功 → 一定和牌" in src
          and "_yiding_why_not()" in src)
    check("前路 done/fail 只对自己座位 toast",
          'get("seat", my_seat)) == my_seat' in src)

    print("\n" + "=" * 70)
    print(" 断言 %d 条 / 失败 %d 条" % (PASS, FAIL))
    print("=" * 70)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
