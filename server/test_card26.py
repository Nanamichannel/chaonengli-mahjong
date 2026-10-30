# -*- coding: utf-8 -*-
"""Card26 S1「云外镜」+ S2「天梯」自测

用户口径：
  · S1 配牌发动 → **在我视角里**其他三家的角色卡遮罩永远关闭（已过期的卡不揭）；
  · S2 配牌发动 → 本局开启、红框、不可关闭；每次**自己**摸牌前排接下来 1+n 张；
    n = 连续和牌次数（初始 0，每次自己连续和牌 +1；别人和 / 流局 / 被罚 → 清零）；
  · 发动之后**第一次**和牌没有大小要求，之后每次得点必须 > 上次 + 300，
    否则拿不到得点、付每家 3000，本局按「无人听牌的荒牌流局」记。
  · 排序张数 1+n 无上限（按活牌数封顶）。

跑法：cd N:\apps\tianma\server; python test_card26.py
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

from game import Game, RuleError          # noqa: E402
import skills                             # noqa: E402
import test_game as tg                    # noqa: E402
from tiles import parse_hand              # noqa: E402
from rules import score                   # noqa: E402

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


def setup(tag, cards=(26,)):
    db = tg.fresh_db(tag)
    rid, _m, _u = tg.new_round(db, seed=97)
    for s, h in enumerate((H0, H1, H2, H3)):
        tg.set_hand(db, rid, s, parse_hand(h))
    # 大厅卡序（_char_states / owns_card 都要它）：0 号位主战 = 26
    orders = [[26, 1, 2, 3, 5], [4, 1, 2, 3, 5], [6, 1, 2, 3, 5], [7, 1, 2, 3, 5]]
    with db.tx():
        db.conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES('lobby_state', ?)",
            (json.dumps({"seats": [{"order": o} for o in orders]}, ensure_ascii=False),))
    g = Game(db, rid)
    g.granted = {0: set(cards)}
    g.round_phase = "play"
    g.phase = "deal_skill"
    g.deal_wait = {0}
    g.deal_deadline = time.time() + 20.0
    g.save_flags()
    return db, rid


def main() -> int:
    print("=" * 78)
    print(" Card26 S1「云外镜」+ S2「天梯」")
    print("=" * 78)

    # ── ① 注册 / 配牌窗口 ─────────────────────────────────────────────
    print("\n① 注册与配牌窗口")
    check("S1 名字", skills.info(26, 1).get("name"), "云外镜")
    check("S2 名字", skills.info(26, 2).get("name"), "天梯")
    check("S1 时机 = 配牌", skills.timing(26, 1), "deal")
    check("S2 时机 = 配牌", skills.timing(26, 2), "deal")
    db, rid = setup("c26a")
    g = Game(db, rid)
    opts = [(o["card"], o["skill"]) for o in g._deal_skill_options(0)]
    check("配牌窗口列出云外镜", (26, 1) in opts)
    check("配牌窗口列出天梯", (26, 2) in opts)

    # ── ② 云外镜：只有发动者看得见别人 ────────────────────────────────
    print("\n② 云外镜：别人看不到发动者的卡，但我看得见他们的")
    g0 = Game(db, rid)
    st_me = {d["seat"]: d for d in g0._char_states(0)}
    check("没发动之前：1 号位是盖着的", bool(st_me[1]["main"].get("open")), False)
    r1 = g0.deal_action(0, "use", 26, 1)
    check("云外镜发动成功", r1.get("armed"), True)
    g1 = Game(db, rid)
    st_me = {d["seat"]: d for d in g1._char_states(0)}
    check("发动之后：1 号位揭开了", bool(st_me[1]["main"].get("open")), True)
    check("2 号位也揭开了", bool(st_me[2]["support"].get("open")), True)
    st_other = {d["seat"]: d for d in g1._char_states(1)}
    check("别人眼里 2 号位还是盖着的（云外镜只对我生效）",
          bool(st_other[2]["main"].get("open")), False)
    check("state 里 c26s1_on = true", bool(g1.state_for(0).get("c26s1_on")), True)

    # 过期卡不揭
    used = skills._char_use(db)
    used["1:4"] = -5        # 1 号位的主战卡
    with db.tx():
        import json
        db.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('char_use', ?)",
                        (json.dumps(used),))
    g1b = Game(db, rid)
    st_me = {d["seat"]: d for d in g1b._char_states(0)}
    check("过期的卡标成 expired（客户端据此遮住，云外镜不揭）",
          bool(st_me[1]["main"].get("expired")), True)

    # ── ③ 天梯：配牌发动 ────────────────────────────────────────────
    print("\n③ 天梯：配牌发动 → 本局开启、n 从 0 开始")
    db2, rid2 = setup("c26b")
    g2 = Game(db2, rid2)
    r2 = g2.deal_action(0, "use", 26, 2)
    check("发动成功", r2.get("armed"), True)
    check("kind = c26s2", r2.get("kind"), "c26s2")
    g2 = Game(db2, rid2)
    check("本局开启", 0 in g2.c26s2_on)
    check("n 初始 1（用户口径）", g2.c26_n.get(0), 1)
    check("上次得点还没有", g2.c26_last.get(0), -1)
    # 同一张卡还有云外镜没发 → 先留在配牌窗口
    check("发完天梯还留在配牌窗口（云外镜还没发）", 0 in g2.deal_wait, True)
    g2.deal_action(0, "skip")                 # 不要云外镜了 → 跳过
    check("跳过后配牌阶段结束", Game(db2, rid2).phase, "discard")
    check("state 下发 c26s2_on / c26_n",
          (bool(g2.state_for(0).get("c26s2_on")), int(g2.state_for(0).get("c26_n"))),
          (True, 1))

    # ── ④ 摸牌前排牌山：1 + n 张 ─────────────────────────────────────
    print("\n④ 每次自己摸牌前：排接下来 1+n 张")
    g3 = Game(db2, rid2)
    g3.turn, g3.phase = 0, "draw"
    g3.save_flags()
    g3 = Game(db2, rid2)
    check("轮到我摸牌 → 要排牌山", g3.c26_can_sort(0), True)
    check("张数 = 1 + n = 2", g3.c26_count(0), 2)
    check("摸牌前服务端会停住等我", g3.pre_draw_pending(0), True)
    view = g3.c26_view(0)
    check("给出发动者牌面", len(view), 2)
    g3b = Game(db2, rid2)
    check("别人看不到", g3b.c26_view(1), [])
    r4 = g3.c26_set(0, [1, 0])
    check("排好了", r4.get("k"), 2)
    g4 = Game(db2, rid2)
    check("排过之后这一巡不再拦", g4.c26_can_sort(0), False)
    ev = g4.advance()
    g5 = Game(db2, rid2)
    check("摸到牌了", g5.phase, "discard")
    try:
        g5.c26_set(0, [0, 1])
        check("同一巡不能排第二次", "没拒", "拒了")
    except RuleError:
        check("同一巡不能排第二次", "拒了", "拒了")

    # n 变大 → 张数跟着变
    print("\n   天梯次数 n 变大 → 张数 1+n")
    g5.c26_n[0] = 3
    g5.c26_done = {}
    g5.turn, g5.phase = 0, "draw"
    g5.save_flags()
    g6 = Game(db2, rid2)
    check("n=3 → 排 4 张", g6.c26_count(0), 4)
    check("牌面也是 4 张", len(g6.c26_view(0)), 4)
    view6 = list(g6.c26_view(0))
    r6 = g6.c26_set(0, [3, 2, 1, 0])
    check("倒序排 4 张", r6.get("k"), 4)
    check("返回的就是倒过来的", r6.get("tiles"), list(reversed(view6)))

    # ── ⑤ 得点必须比上次高 300 ──────────────────────────────────────
    print("\n⑤ 天梯代价：得点没涨够 → 白干 + 罚点 + 本局流局")
    db3, rid3 = setup("c26c")
    g7 = Game(db3, rid3)
    g7.c26s2_on = {0}
    g7.c26_n = {0: 0}
    g7.c26_last = {0: -1}
    check("第一次：没有大小要求", g7._c26_check(0, 1000), False)
    g7._c26_commit(0, 1000)
    check("记下得点", g7.c26_last[0], 1000)
    check("天梯次数 +1", g7.c26_n[0], 1)
    check("刚好 1300 → 不合格（要 > 上次+300）", g7._c26_check(0, 1300), True)
    check("1200 → 不合格", g7._c26_check(0, 1200), True)
    check("1400 → 合格", g7._c26_check(0, 1400), False)
    check("没开天梯的人不受影响", g7._c26_check(1, 100), False)

    print("\n   真的走到结算：_finish 里被拦下")
    g8 = Game(db3, rid3)
    g8.c26s2_on = {0}
    g8.c26_last = {0: 5000}
    g8.c26_n = {0: 2}
    g8.save_flags()
    before = g8.scores()
    pays = score.payments(1, 30, is_dealer=True, tsumo=True, yakuman=0,
                          kiriage_mangan=False)
    res = {"yaku": [{"name": "立直", "han": 1}], "han": 1, "fu": 30, "pays": pays}
    g8._finish(0, None, "tsumo", res)
    g9 = Game(db3, rid3)
    check("本局按流局结束", (g9.result or {}).get("result"), "ryuukyoku")
    check("无人听牌", (g9.result or {}).get("tenpai"), [])
    check("结算结果里带 c26_fail", isinstance((g9.result or {}).get("c26_fail"), dict), True)
    sc = g9.scores()
    check("我 -9000", sc[0], before[0] - 9000)
    check("三家各 +3000", [sc[1] - before[1], sc[2] - before[2], sc[3] - before[3]],
          [3000, 3000, 3000])
    check("断连：n 回到初始值 1", g9.c26_n.get(0), 1)
    check("断连：上次得点清掉", g9.c26_last.get(0), -1)

    print("\n   得点够 → 正常和牌并记账")
    db4, rid4 = setup("c26d")
    g10 = Game(db4, rid4)
    g10.c26s2_on = {0}
    g10.c26_last = {0: 1000}
    g10.c26_n = {0: 1}
    g10.save_flags()
    pays2 = score.payments(3, 30, is_dealer=True, tsumo=True, yakuman=0,
                           kiriage_mangan=False)
    res2 = {"yaku": [{"name": "立直", "han": 3}], "han": 3, "fu": 30, "pays": pays2}
    g10._finish(0, None, "tsumo", res2)
    g11 = Game(db4, rid4)
    check("正常和牌", (g11.result or {}).get("result"), "tsumo")
    check("记下这次的得点", g11.c26_last.get(0), int(pays2.get("total", 0)))
    check("天梯次数 +1", g11.c26_n.get(0), 2)

    # ── ⑥ 别人和牌 / 没开 → 不触发 ─────────────────────────────────
    print("\n⑥ 触发条件")
    g12 = Game(db4, rid4)
    g12.c26s2_on = {1}
    g12.c26_last = {-1: 0}
    check("没开天梯的人摸牌 → 不用排", g12.c26_can_sort(0), False)
    g12.c26_last = {}
    check("别人的牌不看", g12.c26_view(0), [])

    # ── ⑦ 同一张卡的两个配牌技能可以连着发动 ──────────────────────────
    print("\n⑦ 云外镜 + 天梯 连着发动（发完一个还留在配牌窗口）")
    db5, rid5 = setup("c26e")
    g13 = Game(db5, rid5)
    r1 = g13.deal_action(0, "use", 26, 1)
    check("先发云外镜", r1.get("armed"), True)
    g13b = Game(db5, rid5)
    check("发完云外镜还留在配牌窗口（天梯还没发）", 0 in g13b.deal_wait, True)
    check("窗口里两行都在（用过的那行客户端会变灰）",
          [o["skill"] for o in g13b._deal_skill_options(0)], [1, 2])
    rr = g13b.deal_action(0, "use", 26, 1)
    check("用过的技能不能再发一次", bool(rr.get("already")), True)
    r2 = g13b.deal_action(0, "use", 26, 2)
    check("再发天梯", r2.get("armed"), True)
    g13c = Game(db5, rid5)
    check("两个都开了", (0 in g13c.c26s2_on, g13c.skill_used(0, 26, 1)), (True, True))
    check("都发完就离开配牌窗口", 0 in g13c.deal_wait, False)
    check("配牌阶段结束", g13c.phase, "discard")

    print("\n" + "=" * 78)
    print(f" 通过 {PASS} / 失败 {FAIL}")
    print("=" * 78)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
