# -*- coding: utf-8 -*-
"""传承（Card16 S1）：发动后 16 号卡「变成」被复制的技能

覆盖：cc_copy 落库/跨实例、state 下发、卡面翻 16、复制来的技能能真的发动、
      新一局清空、看破问两次（传承一次 + 复制技能一次）
"""
from __future__ import annotations

import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")

import api_cli  # noqa: E402
from game import Game  # noqa: E402
from tiles import parse_hand  # noqa: E402
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


def set_orders(db, orders):
    body = {"seats": [{"ready": False, "hand": [], "picks": [], "order": list(o)}
                      for o in orders], "phase": "playing"}
    with db.tx():
        db.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('lobby_state', ?)",
                        (json.dumps(body),))


def seed_log(db, seat=0, card=11, skill=1):
    item = {"seat": int(seat), "card": int(card), "skill": int(skill),
            "wind": "dong", "number": 1}
    with db.tx():
        db.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('skill_log', ?)",
                        (json.dumps([item]),))


def make(tag, seed):
    db = tg.fresh_db(tag)
    set_orders(db, [[16, 16, 16, 16, 16], [1, 2, 3, 4, 5],
                    [1, 2, 3, 4, 6], [1, 2, 3, 4, 7]])
    rid, _m, _u = tg.new_round(db, seed=seed)
    tg.set_hand(db, rid, 0, parse_hand("123m456p789s1z2z3z") + ["5m"], drawn="5m")
    tg.set_hand(db, rid, 1, parse_hand("1m4m7m1p4p7p1s4s7s1z2z3z"))
    tg.set_hand(db, rid, 2, parse_hand("2m5m8m2p5p8p2s5s8s2z3z4z"))
    tg.set_hand(db, rid, 3, parse_hand("3m6m9m3p6p9p3s6s9s1z2z3z"))
    seed_log(db, 0, 11, 1)
    g = Game(db, rid)
    g.granted = {0: {16}}
    g.round_phase = "play"
    g.turn, g.phase = 0, "discard"
    g.save_flags()
    return db, rid


def main() -> int:
    print("=" * 66)
    print(" 天马麻将 · 传承：16 号卡变成被复制的技能")
    print("=" * 66)

    # ① 发动
    print("\n① 发动传承")
    db, rid = make("cc16", 601)
    g = Game(db, rid)
    check("复制清单里有魔术", [(x["card"], x["skill"]) for x in g.chuancheng_list(0)],
          [(11, 1)])
    r = g.chuancheng_use(0, 11, 1)
    check("返回复制结果", (r["card"], r["skill"]), (11, 1))
    g = Game(db, rid)
    check("cc_copy 落库", g.cc_copy.get(0), {"card": 11, "skill": 1})
    check("传承这一手用掉了", g.skill_used(0, 16, 1), True)
    check("复制来的卡也算我的", g.granted.get(0, set()) >= {11}, True)

    # ② state 下发
    print("\n② state 下发 copy")
    st = g.state_for(0)
    cc = st.get("chuancheng") or {}
    check("used=True", cc.get("used"), True)
    check("copy.card=11", (cc.get("copy") or {}).get("card"), 11)
    check("copy.name=魔术", (cc.get("copy") or {}).get("name"), "魔术")
    check("别人看不到我的 copy", (g.state_for(1).get("chuancheng") or {}).get("copy"), None)

    # ③ 卡面翻 16（不是 11）
    print("\n③ 用复制来的技能 → 卡面翻 16")
    g = Game(db, rid)
    g.note_use(0, 11, 1)
    used = g._char_states()
    me = used[0]
    check("主战卡（16）翻明", (me.get("main") or {}).get("open"), True)
    check("主战卡就是 16", (me.get("main") or {}).get("card"), 16)
    check("播报带「传承·」", str((g.broadcast or {}).get("name", ""))[:3], "传承·")

    # ④ 复制来的技能真的能发动
    print("\n④ 复制来的技能能发动")
    db2, rid2 = make("cc16b", 602)
    g2 = Game(db2, rid2)
    g2.chuancheng_use(0, 11, 1)
    g2 = Game(db2, rid2)
    check("魔术可以发动（owns_card11）", g2.owns_card11(0), True)
    check("card11_can", g2.card11_can(0), bool(g2.dora_revealed > 0))

    # ⑤ 看破两次：传承一次、复制技能一次
    print("\n⑤ 看破要问两次")
    db3, rid3 = make("cc16c", 603)
    set_orders(db3, [[16, 16, 16, 16, 16], [17, 17, 17, 17, 17],
                     [17, 17, 17, 17, 17], [1, 2, 3, 4, 7]])
    g3 = Game(db3, rid3)
    g3.granted = {0: {16}, 1: {17}, 2: {17}}
    g3.turn, g3.phase = 0, "discard"
    g3.save_flags()
    path = os.path.join(r"N:\apps\tianma\server", "data", "_test_cc16c.db")
    r1 = api_cli.handle({"op": "chuancheng", "seat": 0, "card": 11, "skill": 1,
                         "round_id": rid3}, path)
    check("发动传承先问看破 (16,1)", bool(r1.get("need_kangpo")), True)
    api_cli.handle({"op": "kangpo_answer", "seat": 1, "use": False, "round_id": rid3}, path)
    _flush_asks(path, rid3)
    g3 = Game(db3, rid3)
    check("放行后真的复制", (g3.cc_copy.get(0) or {}).get("card"), 11)
    r2 = api_cli.handle({"op": "card11_swap", "seat": 0, "hand": "5m",
                         "stack": 0, "half": "top", "round_id": rid3}, path)
    check("复制技能再问一次看破 (11,1)", bool(r2.get("need_kangpo")), True)
    g3 = Game(db3, rid3)
    check("第二次挂起的是 11-1", (g3.kangpo_pending or {}).get("card"), 11)

    # ⑥ 新一局清空
    print("\n⑥ 新一局 cc_copy 清空")
    rid4, _m2, _u2 = tg.new_round(db, seed=604)
    g4 = Game(db, rid4)
    check("新一局没有 copy", g4.cc_copy.get(0), None)
    check("state 里 copy=None", (g4.state_for(0).get("chuancheng") or {}).get("copy"), None)

    # ⑦ 复制「已经用过」的技能 → 要能再用一次
    print("\n⑦ 复制已用过的技能能再用")
    db7, rid7 = tg.fresh_db("cc16d"), None
    rid7, _m3, _u3 = tg.new_round(db7, seed=607)
    set_orders(db7, [[16, 16, 16, 16, 16], [1, 2, 3, 4, 5],
                     [1, 2, 3, 4, 6], [1, 2, 3, 4, 7]])
    tg.set_hand(db7, rid7, 0, parse_hand("123m456p789s1z2z3z") + ["5m"], drawn="5m")
    for _s in (1, 2, 3):
        tg.set_hand(db7, rid7, _s, parse_hand("1m4m7m1p4p7p1s4s7s1z2z3z"))
    seed_log(db7, 0, 20, 2)                    # 这半庄用过的「感知」
    g7 = Game(db7, rid7)
    g7.granted = {0: {16, 20}}
    g7.round_phase = "play"
    g7.turn, g7.phase = 0, "discard"
    g7.mark_skill_used(0, 20, 2)               # 已经用掉了
    g7.save_flags()
    g7 = Game(db7, rid7)
    check("用掉之后不能再发动", g7.ganzhi_can(0), False)
    g7.chuancheng_use(0, 20, 2)                # 复制「感知」
    g7 = Game(db7, rid7)
    check("复制后 used 被清掉", g7.skill_used(0, 20, 2), False)
    check("复制后可以再发动一次", g7.ganzhi_can(0), True)
    check("发动完又变回不可用", True)

    print("\n" + "=" * 66)
    print(f" 通过 {PASS} / 失败 {FAIL}")
    print("=" * 66)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
