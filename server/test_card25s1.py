# -*- coding: utf-8 -*-
"""Card25 S1「宝牌运」自测

用户口径（4 条已确认）：
  ① 宝牌含赤 5（0m/0p/0s）
  ② 3000×3 立即记账（牌桌立刻 -9000 / 对手各 +3000）
  ③ 罚过一次之后本局【宝牌运】关掉（之后切宝牌不再确认）
  ④ 对方有多张宝牌时全部换给我（我出等量）

跑法：cd N:\apps\tianma\server; python test_card25s1.py
"""
from __future__ import annotations

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

PASS = FAIL = 0

H0 = "1m3m4m5m6m7m8m9m5p5p6s7s9s"     # 13 张，没有 2m / 赤 5
H1 = "2m2m1p4p7p1s4s7s1z2z3z"         # 2 张宝牌（2m）
H2 = "3m6m9m3p6p9p3s6s9s4z5z6z7z"     # 没有宝牌
H3 = "0m2m3m6m9m3p6p9p3s6s9s1z2z"     # 2 张宝牌（赤 0m + 2m）


def check(name, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  got {got!r} want {want!r}")


def setup(tag, hands=(H0, H1, H2, H3), indicator="1m", dora="2m"):
    db = tg.fresh_db(tag)
    rid, _m, _u = tg.new_round(db, seed=83)
    for s, h in enumerate(hands):
        tg.set_hand(db, rid, s, parse_hand(h))
    db.add_dora(rid, "dora", 0, indicator, dora)     # 宝牌 = 2m
    g = Game(db, rid)
    g.granted = {0: {25}}
    g.round_phase = "play"
    g.phase = "deal_skill"
    g.deal_wait = {0}
    g.deal_deadline = time.time() + 20.0
    g.save_flags()
    return db, rid


def dora_count(g, seat) -> int:
    ks = g._dora_kinds()
    return sum(1 for t in g.hand(seat) if g._is_dora(t, ks))


def main() -> int:
    print("=" * 78)
    print(" Card25 S1「宝牌运」：配牌换宝牌 → 本局切宝牌要确认 + 罚 3000×3")
    print("=" * 78)

    # ── ① 注册 / 配牌窗口 ─────────────────────────────────────────────
    print("\n① 技能注册 + 配牌阶段能发动")
    check("REGISTRY 里叫「宝牌运」", skills.info(25, 1).get("name"), "宝牌运")
    check("发动时机是配牌", skills.timing(25, 1), "deal")
    db, rid = setup("c25a")
    g = Game(db, rid)
    opts = [(o["card"], o["skill"]) for o in g._deal_skill_options(0)]
    check("有 25 号卡 → 配牌窗口列出 (25,1)", (25, 1) in opts)
    g2 = Game(db, rid)
    g2.granted = {}
    g2.save_flags()
    g3 = Game(db, rid)
    check("没有 25 号卡 → 不列", [(o["card"], o["skill"])
                                for o in g3._deal_skill_options(1)], [])

    # ── ② 发动：统计三家宝牌 ─────────────────────────────────────────
    print("\n② 发动 → 依次换下家/对家/上家的宝牌")
    r = g.deal_action(0, "use", 25, 1)
    check("发动成功", r.get("armed"), True)
    check("kind = dora_luck", r.get("kind"), "dora_luck")
    fl = r.get("flow") or {}
    check("第一个目标是下家", fl.get("target"), 1)
    check("下家有 2 张宝牌", fl.get("n"), 2)
    check("别人看不到这个流程", g.state_for(1).get("deal_flow"), None)
    check("还没换完 → 宝牌运没开", bool(g.state_for(0).get("c25_on")), False)
    check("下发宝牌种类（2m）", list(g.state_for(0).get("c25_kinds") or []), ["2m"])
    check("我的宝牌数 = 0", dora_count(g, 0), 0)
    check("非宝牌张数 = 13", g._non_dora_count(0), 13)

    # ── ③ 换牌（不能拿宝牌去换）────────────────────────────────────────
    print("\n③ 换牌：我出 2 张非宝牌 → 拿到 2 张宝牌")
    r2 = g.deal_swap(0, 0, ["1m", "3m"])
    check("换了 2 张", r2.get("count"), 2)
    check("拿到的是 2m、2m", sorted(r2.get("got") or []), ["2m", "2m"])
    nx = r2.get("next") or {}
    check("跳过没有宝牌的对家 → 直接到上家", nx.get("target"), 3)
    check("上家有 2 张宝牌（含赤 0m）", nx.get("n"), 2)
    err = ""
    try:
        g.deal_swap(0, 2, ["2m", "2m"])
    except RuleError as e:
        err = str(e)
    check("拿宝牌去换 → 拒绝", "宝牌不能拿去交换" in err)
    r3 = g.deal_swap(0, 2, ["5p", "6s"])
    check("第二次换了 2 张", r3.get("count"), 2)
    check("拿到 2m + 赤 0m", sorted(r3.get("got") or []), ["0m", "2m"])
    check("换完流程收尾", g.deal_flow, None)
    # 持 25 号卡 → 【宝牌的集合】(25-2) 紧接着挂着，先不离开配牌阶段
    check("还留在配牌阶段（等宝牌的集合）", g.phase, "deal_skill")
    check("下发 c25s2_can", bool(g.state_for(0).get("c25s2_can")), True)
    g.c25s2_arm(0)
    check("宝牌的集合发动后 → 配牌结束、轮到庄家切牌", (g.turn, g.phase), (0, "discard"))
    check("宝牌的集合已开启", 0 in g.c25s2_on)
    check("我手里 4 张宝牌（含赤）", dora_count(g, 0), 4)
    check("宝牌运已开启", 0 in g.c25_on)
    check("下发 c25_on = True", bool(g.state_for(0).get("c25_on")), True)
    check("我的宝牌运状态只有自己看得到", bool(g.state_for(1).get("c25_on")), False)

    # ── ④ 切宝牌要确认，确认了就罚点 ──────────────────────────────────
    print("\n④ 切宝牌：第一次被拒 → 确认后真的打出并罚点")
    before = g.scores()
    err = ""
    try:
        g.act(0, "discard", tile="2m")
    except RuleError as e:
        err = str(e)
    check("没确认 → 拒绝", "确认要切出宝牌吗" in err)
    check("宝牌还在手里（没打出去）", dora_count(g, 0), 4)
    ev = g.act(0, "discard", tile="2m", c25_ok=True)
    check("确认后打出去了", ev.get("event"), "discard")
    check("事件标记了宝牌运", bool(ev.get("c25")), True)
    check("本局不能胡牌", 0 in g.no_win)
    sc = g.scores()
    check("我 -9000", sc[0], before[0] - 9000)
    check("三家各 +3000", [sc[1] - before[1], sc[2] - before[2], sc[3] - before[3]],
          [3000, 3000, 3000])
    rows = g.db._rows("SELECT seat, delta, reason FROM score_events WHERE round_id=? "
                      "AND reason='宝牌运' ORDER BY seat", (rid,))
    check("记了 4 条账", [(int(x["seat"]), int(x["delta"])) for x in rows],
          [(0, -9000), (1, 3000), (2, 3000), (3, 3000)])
    check("罚过之后关掉（不会再问第二次）", 0 in g.c25_on, False)

    # ── ⑤ 关掉之后切宝牌不再确认 ──────────────────────────────────────
    print("\n⑤ 罚过一次 → 本局关掉，之后切宝牌不再确认")
    g4 = Game(db, rid)
    g4.turn, g4.phase = 0, "discard"
    g4.save_flags()
    before2 = g4.scores()
    ev2 = g4.act(0, "discard", tile="0m")
    check("不确认也能打（技能已关）", ev2.get("event"), "discard")
    check("没再罚点", g4.scores(), before2)

    # ── ⑥ 点了技能又反悔跳过 → 不能误开 ───────────────────────────────
    print("\n⑥ 发动后跳过 / 超时兜底 → 不算开启")
    db2, rid2 = setup("c25b")
    g5 = Game(db2, rid2)
    g5.deal_action(0, "use", 25, 1)
    check("流程已开始", g5.deal_flow is not None)
    g5.deal_skip_all()
    check("跳过之后流程没了", g5.deal_flow, None)
    check("也没开启宝牌运", 0 in g5.c25_on, False)

    # ── ⑦ 三家都没宝牌 → 直接收尾，照样开启 ───────────────────────────
    print("\n⑦ 三家都没宝牌 → 不用换，直接进切牌；技能照样开启")
    no_dora = (H0, H1, H2, "4m2m3m6m9m3p6p9p3s6s9s1z2z")   # 没有 2s、也没有赤 5
    db3, rid3 = setup("c25c", hands=no_dora, indicator="1s", dora="2s")
    g6 = Game(db3, rid3)
    check("三家都没有宝牌", [len(g6._doras_of(s)) for s in (1, 2, 3)], [0, 0, 0])
    r6 = g6.deal_action(0, "use", 25, 1)
    check("发动成功", r6.get("armed"), True)
    check("没有 target（不用换）", (r6.get("flow") or {}).get("target", -1), -1)
    g6.c25s2_arm(0)                      # 持 25 号卡：宝牌的集合会接着挂出来
    check("宝牌的集合结算完 → 进切牌", g6.phase, "discard")
    check("照样开启宝牌运", 0 in g6.c25_on)

    print("\n" + "=" * 78)
    print(f" 通过 {PASS} / 失败 {FAIL}")
    print("=" * 78)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
