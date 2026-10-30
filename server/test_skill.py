# -*- coding: utf-8 -*-
"""角色卡技能自测（Card01 Skill1「国标」）
跑法： python test_skill.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")

from game import Game  # noqa: E402
from rules import patterns  # noqa: E402
from rules.agari import decompositions  # noqa: E402
from tiles import counts_of, parse_hand  # noqa: E402
import test_game as tg  # noqa: E402

PASS = 0
FAIL = 0


def check(name, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  got={got!r} want={want!r}")


def at_discard(g: Game, seat: int) -> Game:
    g.turn = seat
    g.phase = "discard"
    g.save_flags()
    return g


def patterns_of(hand: str) -> list:
    out = set()
    for s, p in decompositions(counts_of(parse_hand(hand)), []):
        out.add(tuple(patterns.matched(s, p)))
    return sorted(out)


def main() -> int:
    print("=" * 70)
    print(" 天才麻将少女 · 角色卡技能（Card01 Skill1「国标」）")
    print("=" * 70)

    # ── 1. 三种番种本身 ─────────────────────────────────────────────
    print("\n① 五门齐 / 花龙 / 三色三步高")
    check("三色三步高（123m 234p 345s）",
          ("三色三步高",) in patterns_of("123m234p345s789m11z"))
    check("花龙（123m 456p 789s）",
          ("花龙",) in patterns_of("123m456p789s234m11z"))
    check("五门齐+花龙（万筒索风箭齐全）",
          ("五门齐", "花龙") in patterns_of("123m456p789s11z555z"))
    check("普通牌型没有这三种番", patterns_of("111m222p333s444s11z") == [()])
    check("五门齐：少一门就不算",
          patterns.matched([("run", 0), ("run", 9), ("run", 18)], 31), [])

    # ── 2. 门清听牌 → 挂牌子 → 自摸结算 ───────────────────────────
    print("\n② 门清：三色三步高听牌 → 出现自摸 → 结算 +2 番")
    db = tg.fresh_db("skill_closed")
    rid, _m, _u = tg.new_round(db, seed=7)
    tg.set_hand(db, rid, 0, parse_hand("123m234p345s789m1z5z"), drawn="bai")
    g = at_discard(Game(db, rid), 0)
    plan = __import__("skills").card01_s1_plan(g, 0)
    check("技能找得到方案", plan is not None)
    check("方案里的番种", plan["patterns"], ["三色三步高"])
    check("方案是「打一张、发一张」14 张对得上",
          (len(g.hand(0)), plan["discard"] in g.hand(0)), (14, True))

    r = g.arm_skill(0, 1, 1)
    check("发动成功（挂牌子）", r.get("armed"), True)
    check("奖励番（门清 +2）", r.get("han_bonus"), 2)
    acts = {a["action"] for a in g.legal_actions(0)}
    check("可选动作里多了 skill_tsumo", "skill_tsumo" in acts)

    ev = g.act(0, "skill_tsumo")
    check("事件类型", ev.get("event"), "skill_tsumo")
    res = g.result or {}
    check("结果是自摸", res.get("result"), "tsumo")
    names = [y["name"] for y in res.get("yaku", [])]
    check("播报里有「三色三步高」", "三色三步高" in names)
    bonus = [y["han"] for y in res.get("yaku", []) if "三色三步高" in y["name"]]
    check("奖励番写成 2 番", bonus, [2])
    check("三家都付了钱（收付合计为 0）", sum(res.get("deltas", {}).values()), 0)
    check("和牌后局面结束", g.phase, "ended")
    check("技能牌子已收起", g.armed_skill, None)

    # ── 3. 副露：同样牌型只 +1 番 ─────────────────────────────────
    print("\n③ 副露（234p 吃过）：同样的牌型奖励番 +1")
    db2 = tg.fresh_db("skill_open")
    rid2, _m2, _u2 = tg.new_round(db2, seed=8)
    tg.set_hand(db2, rid2, 0, parse_hand("2p3p1z5z"))          # 先给吃牌用的两张
    db2.meld(rid2, 0, "chi", ["2p", "3p", "4p"], called_tile="4p", from_seat=1, rot_index=0)
    tg.set_hand(db2, rid2, 0, parse_hand("123m345s789m1z5z"), drawn="bai")
    g2 = at_discard(Game(db2, rid2), 0)
    plan2 = __import__("skills").card01_s1_plan(g2, 0)
    check("副露也能找到方案", plan2 is not None)
    check("副露方案的番种", plan2["patterns"], ["三色三步高"])
    r2 = g2.arm_skill(0, 1, 1)
    check("副露奖励番 +1", r2.get("han_bonus"), 1)
    ev2 = g2.act(0, "skill_tsumo")
    names2 = [y["name"] for y in (g2.result or {}).get("yaku", [])]
    check("副露播报里也有三色三步高", "三色三步高" in names2)
    check("副露的奖励番是 1 番",
          [y["han"] for y in (g2.result or {}).get("yaku", []) if "三色三步高" in y["name"]], [1])

    # ── 4. 没有这种听牌 → 发动失败（不算错）────────────────────────
    print("\n④ 没有那三种番的听牌：发动失败，不给自摸按钮")
    db3 = tg.fresh_db("skill_none")
    rid3, _m3, _u3 = tg.new_round(db3, seed=9)
    tg.set_hand(db3, rid3, 0, parse_hand("111m222p333s444s1z5z"), drawn="bai")
    g3 = at_discard(Game(db3, rid3), 0)
    r3 = g3.arm_skill(0, 1, 1)
    check("没方案 → armed=False", r3.get("armed"), False)
    check("有原因提示", "五门齐" in str(r3.get("reason", "")), True)
    check("不给 skill_tsumo",
          "skill_tsumo" in {a["action"] for a in g3.legal_actions(0)}, False)

    # ── 5. 不是自己的回合 / 没摸牌 ─────────────────────────────────
    print("\n⑤ 时机检查")
    g4 = Game(db3, rid3)
    g4.turn = 0
    g4.phase = "draw"
    g4.save_flags()
    r4 = g4.arm_skill(0, 1, 1)
    check("摸牌前不能发动", r4.get("armed"), False)
    g5 = at_discard(Game(db3, rid3), 1)
    r5 = g5.arm_skill(0, 1, 1)
    check("不是自己的回合不能发动", r5.get("armed"), False)

    # ── 6. 不认识的技能 ───────────────────────────────────────────
    print("\n⑥ 技能表")
    g6 = at_discard(Game(db3, rid3), 0)
    r6 = g6.arm_skill(0, 2, 1)
    check("没登记的卡不发技能", r6.get("armed"), False)

    # ── 7. Card01 Skill2「避开」：选两张牌，看哪张是他的铳张 ──────────
    print("\n⑦ Skill2：选对象 + 两张手牌 → 铳张")
    db7 = tg.fresh_db("skill2")
    rid7, _m7, _u7 = tg.new_round(db7, seed=61)
    # 1 号位听 1p / 4p
    tg.set_hand(db7, rid7, 1, parse_hand("123m456m789m23p55s"))
    # 我（0 号位）刚摸完 14 张，手里有 1p（铳张）和 9s（安全牌）
    tg.set_hand(db7, rid7, 0, parse_hand("1p9s1234567m1234z") + ["bai"], drawn="bai")
    g7 = at_discard(Game(db7, rid7), 0)
    check("1 号位确实在听 1p/4p", sorted(g7.waits(1)), ["1p", "4p"])
    check("选 1p + 9s → 只有 1p 是铳张",
          __import__("skills").target_hits(g7, 1, ["1p", "9s"]), [0])
    check("选 9s + 2z → 都不是铳张",
          __import__("skills").target_hits(g7, 1, ["9s", "2z"]), [])

    r7 = __import__("api_cli").handle(
        {"op": "skill2", "seat": 0, "target": 1, "tiles": ["1p", "9s"],
         "round_id": rid7}, db7.path)
    check("op=skill2 成功", r7.get("ok"), True)
    check("返回命中下标", r7.get("hits"), [0])
    check("不把对方的听牌整份发下来", "waits" in r7, False)

    r8 = __import__("api_cli").handle(
        {"op": "skill2", "seat": 0, "target": 0, "tiles": ["1p", "9s"],
         "round_id": rid7}, db7.path)
    check("不能选自己", r8.get("ok"), False)

    r9 = __import__("api_cli").handle(
        {"op": "skill2", "seat": 0, "target": 1, "tiles": ["1p", "7z"],
         "round_id": rid7}, db7.path)
    check("不在手上的牌不给查", r9.get("ok"), False)

    r10 = __import__("api_cli").handle(
        {"op": "skill2", "seat": 0, "target": 1, "tiles": ["1p"],
         "round_id": rid7}, db7.path)
    check("必须选两张", r10.get("ok"), False)

    for d in tg._OPEN_DBS:
        try:
            d.close()
        except Exception:
            pass

    print("\n" + "=" * 70)
    print(f" 通过 {PASS} 项，失败 {FAIL} 项")
    print("=" * 70)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
