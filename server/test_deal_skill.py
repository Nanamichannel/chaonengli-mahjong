# -*- coding: utf-8 -*-
"""配牌技能窗口 + 技能播报 + 人物卡翻明 自测
跑法： python test_deal_skill.py
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")

from game import Game, RuleError  # noqa: E402
import skills  # noqa: E402
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


def new_round(db, seed: int, orders=None) -> int:
    uids = [db.create_user(f"ds{seed}_{i}") for i in range(4)]
    room = db.create_room(uids[0])
    for u in uids[1:]:
        db.join_room(room["room_code"], u)
    match = db.start_match(room["room_id"], seed=seed)
    rid = db.start_round(match, "dong", 1, honba=0, dealer_seat=0, seed=seed)
    if orders:
        seats = [{"ready": False, "hand": [], "picks": [], "order": [41 if int(v) == 7 else int(v) for v in o]}
                 for o in orders]
        body = {"seats": seats, "phase": "playing"}
        with db.tx():
            db.conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES('lobby_state', ?)",
                (json.dumps(body, ensure_ascii=False),))
    return rid


def deal_all(g: Game) -> None:
    g.start()
    while not g.deal_done():
        g.deal_step()


def main() -> int:
    print("=" * 70)
    print(" 天才麻将少女 · 配牌技能窗口 / 播报 / 翻明")
    print("=" * 70)

    # ── 1. 时机标记 ──────────────────────────────────────────────
    print("\n① 每个 Skill 的发动时机")
    want = {
        (1, 1): "draw", (1, 2): "draw",
        (2, 1): "draw", (2, 2): "draw",
        (3, 1): "deal", (3, 2): "draw",
    }
    for key, timing in want.items():
        check(f"Card{key[0]:02d} Skill{key[1]} = {timing}",
              skills.timing(*key), timing)
    check("配牌技能清单（含 12-1 海神）", skills.deal_skills(),
          [(3, 1), (4, 1), (6, 1), (7, 1), (12, 1), (14, 1), (17, 1), (18, 1),
           (25, 1), (25, 2), (26, 1), (26, 2), (28, 1), (30, 1), (32, 1), (42, 1)])  # 33-2【记忆】是切牌技能，不在配牌清单里
    check("中文名", [skills.timing_cn(3, 1), skills.timing_cn(1, 1),
                    skills.timing_cn(1, 2)], ["配牌", "摸牌", "摸牌"])

    # ── 2. 没人有配牌技能 → 配牌完直接切牌 ──────────────────────
    print("\n② 没人有配牌技能：直接进切牌")
    db0 = tg.fresh_db("deal_none")
    rid0 = new_round(db0, seed=101, orders=[[1, 2, 3, 4, 5], [2, 3, 4, 5, 6],
                                            [1, 3, 4, 5, 6], [1, 4, 5, 6, 7]])
    g0 = Game(db0, rid0)
    deal_all(g0)
    check("阶段是 discard", g0.phase, "discard")
    check("没有等任何人", g0.deal_wait, set())

    # ── 3. 庄家有配牌技能 → 卡住等决定 ──────────────────────────
    print("\n③ 有配牌技能：庄家跳完牌先等")
    db = tg.fresh_db("deal_wait")
    rid = new_round(db, seed=102, orders=[[3, 1, 2, 4, 5], [1, 2, 4, 5, 6],
                                          [2, 3, 4, 5, 6], [1, 4, 5, 6, 7]])
    g = Game(db, rid)
    deal_all(g)
    check("阶段变成 deal_skill", g.phase, "deal_skill")
    check("等 0 号位", sorted(g.deal_wait), [0])
    check("庄家不能打牌（没有可选动作）", g.legal_actions(0), [])
    st = g.state_for(0)
    check("state 里报 pending", st["deal_skill"]["pending"], [0])
    check("state 里报我能发动的技能",
          [(x["card"], x["skill"]) for x in st["deal_skill"]["mine"]], [(3, 1)])
    check("别人 state 里没有可选技能", g.state_for(1)["deal_skill"]["mine"], [])
    # 配牌技能是「基本属性」：没结算完 / 没跳过之前，谁都不许切牌、也不许推进
    try:
        g.act(0, "discard", tile=g.hand(0)[0])
        check("配牌期间不能切牌", False)
    except RuleError as e:
        check("配牌期间不能切牌", str(e) != "")
    try:
        g._do_discard(0, tile=g.hand(0)[0])
        check("绕过 legal_actions 也切不了", False)
    except RuleError as e:
        check("绕过 legal_actions 也切不了", "配牌技能还没结算完" in str(e))
    check("推进被拦下（不摸牌）", g._advance().get("event"), "dealing")
    check("阶段没变", g.phase, "deal_skill")

    # ── 4. 跳过 → 进入切牌 ─────────────────────────────────────
    print("\n④ 点「开始」= 跳过")
    r = g.deal_action(0, "skip")
    check("skipped", r.get("skipped"), True)
    check("阶段回到 discard", g.phase, "discard")
    check("轮到庄家", g.turn, 0)
    check("能打牌了", "discard" in {a["action"] for a in g.legal_actions(0)}, True)

    # ── 5. 发动技能 → 结算 + 广播 + 翻明 ───────────────────────
    print("\n⑤ 发动「自信」：结算 / 播报 / 翻明")
    db5 = tg.fresh_db("deal_use")
    rid5 = new_round(db5, seed=103, orders=[[3, 1, 2, 4, 5], [1, 2, 4, 5, 6],
                                            [2, 3, 4, 5, 6], [1, 4, 5, 6, 7]])
    g5 = Game(db5, rid5)
    deal_all(g5)
    check("先卡在窗口", g5.phase, "deal_skill")
    r5 = g5.deal_action(0, "use", 3, 1)
    check("发动成功", r5.get("armed"), True)
    check("自信已生效", 0 in g5.confident)
    check("窗口关闭，进入切牌", g5.phase, "discard")
    check("发动顺序记录", [(q["seat"], q["skill"]) for q in g5.deal_queue], [(0, 1)])
    b = g5.state_for(0).get("broadcast") or {}
    check("播报技能名", b.get("name"), "自信")
    check("播报风位（庄家=东）", b.get("wind"), "dong")
    check("播报有 id", int(b.get("id", 0)) > 0, True)
    check("我的人物卡翻明", 0 in (g5.state_for(0).get("revealed") or []), True)
    g5b = Game(db5, rid5)
    check("翻明是永久的（换请求还在）", 0 in g5b.state_for(0).get("revealed", []), True)

    # ── 6. 两家都能发动：按顺序，一个完成另一个还没选也行 ──────
    print("\n⑥ 两家都能发动：一家完成时另一家还没选")
    db6 = tg.fresh_db("deal_two")
    rid6 = new_round(db6, seed=104, orders=[[3, 1, 2, 4, 5], [3, 2, 4, 5, 6],
                                            [2, 3, 4, 5, 6], [1, 4, 5, 6, 7]])
    g6 = Game(db6, rid6)
    deal_all(g6)
    check("两家都在等", sorted(g6.deal_wait), [0, 1])
    r6 = g6.deal_action(1, "use", 3, 1)
    check("1 号位先发动", r6.get("armed"), True)
    check("还在等 0 号位", sorted(g6.deal_wait), [0])
    check("阶段还是 deal_skill", g6.phase, "deal_skill")
    check("1 号位播报的风位是南", (g6.state_for(0).get("broadcast") or {}).get("wind"), "nan")
    r6b = g6.deal_action(0, "skip")
    check("0 号位跳过后进入切牌", g6.phase, "discard")
    check("发动顺序是 1 → 0", [q["seat"] for q in g6.deal_queue], [1])

    # ── 7. 不是配牌技能 / 时机不对 ─────────────────────────────
    print("\n⑦ 错误处理")
    db7 = tg.fresh_db("deal_bad")
    rid7 = new_round(db7, seed=105, orders=[[1, 2, 4, 5, 6], [2, 3, 4, 5, 6],
                                            [1, 3, 4, 5, 6], [1, 4, 5, 6, 7]])
    g7 = Game(db7, rid7)
    deal_all(g7)
    try:
        g7.deal_action(0, "skip")
        check("没人有配牌技能时不能调用", False)
    except Exception as e:
        check("没人有配牌技能时不能调用", "配牌技能阶段" in str(e))

    db8 = tg.fresh_db("deal_wrong")
    rid8 = new_round(db8, seed=106, orders=[[3, 1, 2, 4, 5], [1, 2, 4, 5, 6],
                                            [2, 3, 4, 5, 6], [1, 4, 5, 6, 7]])
    g8 = Game(db8, rid8)
    deal_all(g8)
    try:
        g8.deal_action(0, "use", 3, 2)          # 3-2 是摸牌技能，不是配牌
        check("不能拿摸牌技能来配牌", False)
    except Exception as e:
        check("不能拿摸牌技能来配牌", "配牌阶段" in str(e))
    try:
        g8.deal_action(1, "skip")               # 1 号位不在 pending
        check("不在窗口里的座位不能动", g8.phase, "deal_skill")
    except Exception as e:
        check("不在窗口里的座位不能动", False)

    # ── 8. 配牌动画里就发动了 → 窗口不再等他 ────────────────────
    print("\n⑧ 窗口出现前就发动过：不再重复等")
    db9 = tg.fresh_db("deal_early")
    rid9 = new_round(db9, seed=107, orders=[[3, 1, 2, 4, 5], [1, 2, 4, 5, 6],
                                            [2, 3, 4, 5, 6], [1, 4, 5, 6, 7]])
    g9 = Game(db9, rid9)
    g9.start()
    check("配牌动画里已经能发动", g9.arm_skill(0, 3, 1).get("armed"), True)
    while not g9.deal_done():
        g9.deal_step()
    check("发完牌直接进切牌", g9.phase, "discard")
    check("不再把 0 号位列进窗口", g9.deal_wait, set())
    check("自信仍然有效", 0 in g9.confident)

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
