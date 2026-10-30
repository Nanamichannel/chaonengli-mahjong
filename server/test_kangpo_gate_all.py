# -*- coding: utf-8 -*-
"""看破闸门覆盖率（黑名单制）+ 配牌技能一律先问看破 + 额外摸切走公共钩子

用户口径：
  · 所有技能发动点都要问看破；唯一例外是结算类（Card10 S2 四喜 / Card01 S1 国标）。
  · 多步技能只在第 1 步问；点跳过/取消不问。
  · 策略段1（压牌）永不可看破。
"""
from __future__ import annotations

import io
import json
import os
import sys

sys.path.insert(0, r'N:\apps\tianma\server')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import api_cli  # noqa: E402
from game import Game  # noqa: E402
import test_game as tg  # noqa: E402


def _flush_asks(dbp, rid):
    """并行询问：答完自己那条，把其余「没人在操作」的座位放行（测试里全是 AI）。"""
    try:
        from db import DB as _DB
        for _ in range(12):
            g = Game(_DB(dbp), int(rid))
            pend = [n for n in g.acts.values() if n.get("state") == "asking"]
            if not pend:
                return
            n = pend[0]
            seat = -1
            for a in (n.get("asks") or []):
                if not a.get("answer"):
                    seat = int(a.get("seat", -1))
                    break
            if seat < 0:
                break
            api_cli.handle({"op": "kangpo_answer", "seat": seat, "use": False,
                            "round_id": int(rid)}, dbp)
    except Exception:
        return


OK = 0
BAD = 0
HAND = ["1m", "2m", "3m", "4m", "5m", "6m", "7m", "8m", "9m", "1p", "2p", "3p", "4p"]


def check(cond, msg):
    global OK, BAD
    if cond:
        OK += 1
    else:
        BAD += 1
        print("  [FAIL]", msg)


def dbpath(tag):
    return os.path.join(r'N:\apps\tianma\server', 'data', f'_test_{tag}.db')


def call(path, req):
    return api_cli.handle(req, path)


def set_orders(db, orders):
    body = {"seats": [{"ready": False, "hand": [], "picks": [], "order": list(o)}
                      for o in orders], "phase": "playing"}
    with db.tx():
        db.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('lobby_state', ?)",
                        (json.dumps(body, ensure_ascii=False),))


def setup(tag, seed, seat0_cards):
    db = tg.fresh_db(tag)
    set_orders(db, [list(seat0_cards) + [3], [17, 17, 17, 17, 4],
                    [1, 2, 3, 4, 5], [6, 7, 8, 9, 10]])
    rid, _m, _u = tg.new_round(db, seed=seed)
    tg.set_hand(db, rid, 0, HAND)
    g = Game(db, rid)
    g.granted = {0: set(seat0_cards), 1: {17}}
    g.phase, g.turn = "deal_skill", 0
    g.deal_wait = {0}
    g.save_flags()
    return db, rid, g


def main():
    # ── ① 结构：闸门表必须覆盖全部 op（白名单漏发动点的历史 bug）──────
    print("① 闸门表覆盖全集")
    ops = set(api_cli.OPS)
    known = (set(api_cli._NO_GATE_OPS) | set(api_cli._GATE_INLINE)
             | set(api_cli._SKILL_OP_PAIRS))
    check(not (ops - known), f"有 op 没登记闸门：{sorted(ops - known)}")
    check(not (known - ops), f"闸门表里有不存在的 op：{sorted(known - ops)}")

    # ── ② 结算类 / 多步后续步 明确不进闸门 ──────────────────────
    print("\n② 不问看破的白名单")
    for op in ("card10s2_activate", "shenshan_resolve", "card05_hide", "deal_swap",
               "south_wind_kinds", "south_wind_swap", "oracle_pick", "oracle_toggle",
               "haishin_give", "zhalie_swap"):
        check(api_cli._gate_pair(op, {}) is None, f"{op} 不该问看破")

    # ── ③ 配牌技能（op=deal_skill）：一律先问看破 ────────────────
    print("\n③ 配牌技能走 deal_skill 也要问看破")
    # must_run：这套夹具下能真的发动（南风要南场、枷锁要先给番数 → 只验闸门）
    cases = [((3, 1), "自信", True), ((4, 1), "风神", True), ((6, 1), "南风", False),
             ((7, 1), "降神", True), ((14, 1), "点燃", True), ((17, 1), "研究", True),
             ((18, 1), "枷锁", False)]
    for i, (pair, name, must_run) in enumerate(cases):
        tag = "gate%d" % i
        db, rid, _g = setup(tag, 300 + i, [pair[0], pair[0], pair[0], pair[0]])
        r = call(dbpath(tag), {"op": "deal_skill", "seat": 0, "action": "use",
                               "card": pair[0], "skill": pair[1], "round_id": rid})
        check(bool(r.get("need_kangpo")), f"{name} 配牌发动要先问看破，实际 {r}")
        g2 = Game(db, rid)
        check(g2.kangpo_pending is not None, f"{name} 要留下挂起（否则看破者点了也作废不了）")
        check(g2.deal_wait == {0}, f"{name} 被拦下时不能动配牌窗口，实际 {g2.deal_wait}")
        # 放行后：能发动的要真的发动；条件不满足的不能把配牌窗口卡死
        call(dbpath(tag), {"op": "kangpo_answer", "seat": 1, "use": False, "round_id": rid})
        _flush_asks(dbpath(tag), rid)
        g3 = Game(db, rid)
        if must_run:
            ok = (0 not in g3.deal_wait) or (g3.deal_flow is not None)
            check(ok, f"{name} 放行后应该真的走下去（deal_wait={g3.deal_wait} flow={g3.deal_flow}）")
        else:
            check(g3.kangpo_pending is None, f"{name} 放行后不该留挂起")

    # ── ④ 配牌技能「跳过」不问看破 ──────────────────────────────
    print("\n④ 配牌点跳过不问看破")
    db, rid, _g = setup("gate_skip", 340, [3, 3, 3, 3])
    r = call(dbpath("gate_skip"), {"op": "deal_skill", "seat": 0, "action": "skip",
                                   "round_id": rid})
    check(not bool(r.get("need_kangpo")), f"跳过不该问看破，实际 {r}")
    g = Game(db, rid)
    check(g.kangpo_ask is None, "跳过后不该留询问")
    check(0 not in g.deal_wait, "跳过应该真的跳过")

    # ── ⑤ 其它发动点进闸门 ─────────────────────────────────────
    print("\n⑤ 其它发动点")
    for op, pair in (("skill2", (1, 2)), ("card10_hand", (10, 1)),
                     ("card10_meld", (10, 1)), ("wind_swap", (4, 2)),
                     ("card09_swap", (9, 1)), ("press", (3, 2))):
        got = api_cli._gate_pair(op, {"skill": 1})
        check(got == pair, f"{op} 应该在闸门里 {pair}，实际 {got}")

    # ── ⑥ 自风被看破 → 窗口必须关掉（不能把对局卡在 wind_swap）────
    print("\n⑥ 自风被看破要把窗口关掉")
    db, rid, _g = setup("gate_wind", 360, [4, 4, 4, 4])
    g = Game(db, rid)
    g.phase = "wind_swap"
    g.turn = 1
    g.wind_swap = {"owner": 0, "from": 1, "tile": "dong"}
    g.save_flags()
    r = call(dbpath("gate_wind"), {"op": "wind_swap", "seat": 0, "tile": "1m",
                                   "round_id": rid})
    check(bool(r.get("need_kangpo")), f"自风换牌要先问看破，实际 {r}")
    g2 = Game(db, rid)
    check(g2.wind_swap is not None, "被拦下时窗口要留着（还能再点）")
    call(dbpath("gate_wind"), {"op": "kangpo_answer", "seat": 1, "use": True,
                               "round_id": rid})
    _flush_asks(dbpath("gate_wind"), rid)
    g3 = Game(db, rid)
    check(g3.wind_swap is None, "被看破 → 自风窗口要关掉")
    check(g3.phase, "discard")
    check(0 in g3.no_win, "被看破的那家本局不能和")

    # ── ⑦ 被看破只废这一个技能：另一张配牌卡还能用 ──────────────
    print("\n⑦ 被看破后别的配牌技能照常可用")
    db, rid, _g = setup("gate_two", 370, [3])          # 先占位，下面重写 order
    # 1、2 号位都给看破：看破是一次性的，1 号位用掉之后 2 号位还能问
    set_orders(db, [[3, 1, 1, 1, 4], [17, 17, 17, 17, 17],
                    [17, 17, 17, 17, 17], [6, 7, 8, 9, 10]])
    g = Game(db, rid)
    opts = [(int(o["card"]), int(o["skill"])) for o in g._deal_skill_options(0)]
    check((3, 1) in opts and (4, 1) in opts, f"要有两个配牌技能可选，实际 {opts}")
    r = call(dbpath("gate_two"), {"op": "deal_skill", "seat": 0, "action": "use",
                                  "card": 3, "skill": 1, "round_id": rid})
    check(bool(r.get("need_kangpo")), f"自信也要先问，实际 {r}")
    call(dbpath("gate_two"), {"op": "kangpo_answer", "seat": 1, "use": True,
                             "round_id": rid})
    _flush_asks(dbpath("gate_two"), rid)
    g2 = Game(db, rid)
    opts2 = [(int(o["card"]), int(o["skill"])) for o in g2._deal_skill_options(0)]
    check((3, 1) not in opts2, f"被看破的那个技能要消失，实际 {opts2}")
    check((4, 1) in opts2, f"另一个配牌技能要留着，实际 {opts2}")
    check(0 in g2.deal_wait, f"配牌窗口要留着等他改选，实际 {g2.deal_wait}")
    check(g2.phase, "deal_skill")
    # 再点被看破的那个：不再问看破（已经被剔除），也不会生效
    r2 = call(dbpath("gate_two"), {"op": "deal_skill", "seat": 0, "action": "use",
                                  "card": 3, "skill": 1, "round_id": rid})
    check(not bool(r2.get("need_kangpo")), f"剔除过的技能不该再问看破，实际 {r2}")
    check(not bool(r2.get("ok", True)) and str(r2.get("error", "")) != "",
          f"被剔除的技能要直接拒绝，实际 {r2}")
    # 改选另一个 → 正常问看破
    r3 = call(dbpath("gate_two"), {"op": "deal_skill", "seat": 0, "action": "use",
                                   "card": 4, "skill": 1, "round_id": rid})
    check(bool(r3.get("need_kangpo")), f"改选风神要能继续，实际 {r3}")

    print("\n" + "=" * 60)
    print("通过 %d / 失败 %d" % (OK, BAD))
    print("=" * 60)
    return 0 if BAD == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
