# -*- coding: utf-8 -*-
"""Card12 自测：海神（借牌 / 挪宝）、X神（跳摸切）。用法 python test_card12.py"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")

from game import Game, RuleError  # noqa: E402
from tiles import parse_hand  # noqa: E402
import skills  # noqa: E402
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


def new_round(db, seed: int, orders) -> int:
    uids = [db.create_user(f"hs{seed}_{i}") for i in range(4)]
    room = db.create_room(uids[0])
    for u in uids[1:]:
        db.join_room(room["room_code"], u)
    match = db.start_match(room["room_id"], seed=seed)
    rid = db.start_round(match, "dong", 1, honba=0, dealer_seat=0, seed=seed)
    g0 = Game(db, rid)
    g0.start()
    while not g0.deal_done():
        g0.deal_step()
    body = {"seats": [{"ready": False, "hand": [], "picks": [], "order": list(o)}
                      for o in orders], "phase": "playing"}
    with db.tx():
        db.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('lobby_state', ?)",
                        (json.dumps(body, ensure_ascii=False),))
    return rid


ORD_12 = [[12, 1, 2, 3, 4], [1, 2, 3, 5, 6], [1, 2, 3, 5, 7], [1, 2, 3, 5, 8]]
H_ME = parse_hand("123m456p789s") + ["1p", "1p", "5m", "5m"]
H_OTHER = parse_hand("234m567p678s") + ["2p", "2p", "9m"]


def main() -> int:
    print("=" * 70)
    print(" 天才麻将少女 · Card12（海神 / X神）")
    print("=" * 70)

    print("\n◆ 技能登记")
    check("skills.has(12,1)", skills.has(12, 1))
    check("skills.has(12,2)", skills.has(12, 2))
    check("S1 名字", skills.info(12, 1).get("name"), "海神")

    print("\n◆ 被动借牌：别人摸到万子/红中")
    db = tg.fresh_db("hs1")
    rid = new_round(db, 1201, ORD_12)
    g = Game(db, rid)
    check("12 号卡是我的主战", g.owns_card12(0))
    check("别人摸 5m → 触发", g._haishin_owner(1, "5m"), 0)
    check("别人摸 0m → 触发", g._haishin_owner(1, "0m"), 0)
    check("别人摸 zhong → 触发", g._haishin_owner(1, "zhong"), 0)
    check("别人摸 3p → 不触发", g._haishin_owner(1, "3p"), None)
    check("自己摸 5m → 不借自己", g._haishin_owner(0, "5m"), None)

    tg.set_hand(db, rid, 0, H_ME)
    tg.set_hand(db, rid, 1, H_OTHER + ["5m"], drawn="5m")
    g = Game(db, rid)
    g.phase = "haishin"
    g.haishin_offer = {"owner": 0, "from": 1, "tile": "5m"}
    g.save_flags()
    g = Game(db, rid)
    check("state 只给 owner 看到 offer",
          isinstance(g.state_for(0).get("haishin_offer"), dict), True)
    check("别家看不到 offer", g.state_for(1).get("haishin_offer"), None)
    try:
        r0 = g.haishin_give(1, "9m")
        check("不是 owner 不能还牌", bool(r0.get("already")))
    except RuleError as e:
        check("不是 owner 不能还牌", "没有要你" in str(e) or "还" in str(e))
    r = g.haishin_give(0, "5m")
    check("借到对方摸的牌", r.get("got"), "5m")
    g2 = Game(db, rid)
    check("我手里多了 5m", "5m" in [t for t in g2.hand(0)], True)
    check("对方手里有我还的牌", "5m" in [t for t in g2.hand(1)], True)
    check("结算后回到打牌阶段", g2.phase, "discard")

    print("\n◆ 立直之后被动失效")
    db2 = tg.fresh_db("hs2")
    rid2 = new_round(db2, 1202, ORD_12)
    with db2.tx():
        db2.conn.execute("INSERT INTO round_riichi(round_id, seat) VALUES(?,0)", (rid2,))
    g3 = Game(db2, rid2)
    check("我立直了 → 不借牌", g3._haishin_owner(1, "5m"), None)

    print("\n◆ 主动挪宝：里宝 → 杠宝 → 杠里宝")
    db3 = tg.fresh_db("hs3")
    rid3 = new_round(db3, 1203, ORD_12)
    tg.set_hand(db3, rid3, 0, H_ME)
    g4 = Game(db3, rid3)
    g4.phase = "draw"
    g4.turn = 0
    g4.save_flags()
    g4 = Game(db3, rid3)
    check("摸牌阶段不再问海神（配牌技能）", g4.haishin_can(0), False)
    g4.phase = "deal_skill"
    g4.deal_wait = {0}
    g4.save_flags()
    g4 = Game(db3, rid3)
    check("配牌阶段可以开启", g4.haishin_can(0), True)
    check("state haishin_can", g4.state_for(0).get("haishin_can"), True)
    try:
        g4.haishin_swap(0, "5m")
        check("配牌阶段不能换宝（用户口径 2026-11-04）", False)
    except RuleError as e:
        check("配牌阶段不能换宝（用户口径 2026-11-04）", "摸牌前" in str(e))
    g4.haishin_start(0)                        # 配牌开启（此时会问看破；测试直接放行）
    g4 = Game(db3, rid3)
    g4.phase = "draw"          # 摸牌前（服务端挪宝只认 draw）
    g4.turn = 0
    g4.save_flags()
    g4 = Game(db3, rid3)
    check("state haishin_swap_can（自己回合·没摸牌）",
          g4.state_for(0).get("haishin_swap_can"), True)
    try:
        g4.haishin_swap(0, "1p")
        check("只能用万子/红中", False)
    except RuleError as e:
        check("只能用万子/红中", "万子" in str(e))
    r1 = g4.haishin_swap(0, "5m")
    check("第 1 步是里宝", r1.get("kind"), "ura")
    check("进度 +1", r1.get("next"), 1)
    g5 = Game(db3, rid3)
    check("没走完 → 和牌门闸", g5.haishin_gate, 0)
    check("手里换到指示牌", r1.get("got") != "", True)
    check("state 里 gate=True", g5.state_for(0).get("haishin_gate"), True)
    # 用户口径 2026-11-06：一回合只能换一张 → 同一巡再换要被拒
    try:
        g5.haishin_swap(0, "5m")
        check("一回合只能换一张", False)
    except RuleError as e:
        check("一回合只能换一张", "一回合" in str(e))
    # 模拟下一巡（本巡指纹翻页）→ 可以换第 2 种：杠宝（没翻也能换）
    g5.haishin_turn_used = {}
    g5.save_flags()
    g5b = Game(db3, rid3)
    r2 = g5b.haishin_swap(0, "5m")
    check("下一巡换杠宝（没翻也能换）", r2.get("kind"), "dora")
    check("第 2 步完 → next=2", int(r2.get("next", -1)), 2)
    check("一种牌只换一次 → step 不会回到 0", int(r2.get("step", -1)), 1)
    tg.set_hand(db3, rid3, 0, H_ME + ["1p"], drawn="1p")
    g6 = Game(db3, rid3)
    g6.phase = "discard"
    g6.turn = 0
    g6.save_flags()
    g6.act(0, "discard", tile="1p")               # 打牌 → 门闸清掉
    g7 = Game(db3, rid3)
    check("打牌后门闸清掉", g7.haishin_gate, None)
    check("打牌后进度保留（整小局累计）", int(g7.haishin_step.get(0, 0)), 2)

    print("\n◆ X神：跳过摸切 2 次")
    db4 = tg.fresh_db("hs4")
    rid4 = new_round(db4, 1204, ORD_12)
    tg.set_hand(db4, rid4, 0, H_ME + ["3p"], drawn="3p")
    g8 = Game(db4, rid4)
    g8.phase = "discard"
    g8.turn = 0
    g8.save_flags()
    g8 = Game(db4, rid4)
    check("摸牌后可以发动", g8.xn_can(0))
    try:
        g8.xn_activate(0, 0)
        check("不能选自己", False)
    except RuleError as e:
        check("不能选自己", "其他玩家" in str(e))
    r2 = g8.xn_activate(0, 2)
    check("目标是 2 号位", r2.get("target"), 2)
    g9 = Game(db4, rid4)
    check("2 号位剩 2 次", int(g9.x_skip.get(2, 0)), 2)
    check("自己不受影响", int(g9.x_skip.get(0, 0)), 0)
    try:
        g9.xn_activate(0, 1)
        check("一轮只能一次", False)
    except RuleError as e:
        check("一轮只能一次", "一次" in str(e))

    g9.phase = "draw"
    g9.turn = 2
    g9.save_flags()
    ev1 = g9.advance()
    check("第 1 次被跳过", ev1.get("event"), "x_skip")
    g10 = Game(db4, rid4)
    check("轮到下家", g10.turn, 3)
    check("剩 1 次", int(g10.x_skip.get(2, 0)), 1)
    g10.phase = "draw"
    g10.turn = 2
    g10.save_flags()
    ev2 = g10.advance()
    check("第 2 次被跳过", ev2.get("event"), "x_skip")
    g11 = Game(db4, rid4)
    check("次数用完就清掉", 2 in g11.x_skip, False)
    g11.phase = "draw"
    g11.turn = 2
    g11.save_flags()
    ev3 = g11.advance()
    check("第 3 次正常摸牌", ev3.get("event"), "draw")

    print("\n" + "=" * 70)
    print(f" 通过 {PASS} 项，失败 {FAIL} 项")
    print("=" * 70)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
