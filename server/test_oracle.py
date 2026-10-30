# -*- coding: utf-8 -*-
"""Card07 Skill1「降神」自测

规则：
  · 配牌时发动，掷一次骰子：2/5/8/11=万，3/6/9/12=筒，4/7/10=条
  · 本局固定花色，默认打开；再点图标可以关 / 开
  · 打开时，每次摸牌前指定一张牌 → 别家（下家→对家→上家）有这张的，
    跟「牌山接下来第 1/2/3 张」交换

跑法： python test_oracle.py
"""
from __future__ import annotations

import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")

import game as game_mod  # noqa: E402
from game import Game, RuleError  # noqa: E402
from tiles import parse_hand  # noqa: E402
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


def new_round(db, seed: int, orders) -> int:
    uids = [db.create_user(f"ora{seed}_{i}") for i in range(4)]
    room = db.create_room(uids[0])
    for u in uids[1:]:
        db.join_room(room["room_code"], u)
    match = db.start_match(room["room_id"], seed=seed)
    rid = db.start_round(match, "dong", 1, honba=0, dealer_seat=0, seed=seed)
    body = {"seats": [{"ready": False, "hand": [], "picks": [], "order": list(o)}
                      for o in orders],
            "phase": "playing"}
    with db.tx():
        db.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('lobby_state', ?)",
                        (json.dumps(body, ensure_ascii=False),))
    return rid


ORD_7 = [[7, 1, 2, 3, 4], [1, 2, 3, 5, 8], [1, 2, 3, 5, 9], [1, 2, 3, 5, 10]]


def force_dice(total: int):
    """把 random.randint 钉死成能掷出 total 的两颗骰子。"""
    d1 = max(1, total - 6)
    d2 = total - d1
    seq = [d1, d2]

    def fake(a, b):
        return seq.pop(0) if seq else 1
    return fake


def main() -> int:
    print("=" * 70)
    print(" 天才麻将少女 · Card07 Skill1「降神」")
    print("=" * 70)

    # ── ① 登记 ──────────────────────────────────────────────────
    print("\n① 技能登记")
    check("skills.has(7,1)", skills.has(7, 1))
    check("名字是「降神」", skills.info(7, 1).get("name"), "降神")
    check("时机是配牌", skills.timing(7, 1), "deal")
    check("是配牌技能", (7, 1) in skills.deal_skills())

    # ── ② 骰子 → 花色 ───────────────────────────────────────────
    print("\n② 骰子点数 → 花色")
    want = {2: "m", 3: "p", 4: "s", 5: "m", 6: "p", 7: "s",
            8: "m", 9: "p", 10: "s", 11: "m", 12: "p"}
    db = tg.fresh_db("ora_map")
    rid = new_round(db, 811, ORD_7)
    g = Game(db, rid)
    for total, suit in want.items():
        g.oracle.pop(0, None)
        real = random.randint
        game_mod.random.randint = force_dice(total)
        try:
            r = g._start_oracle(0, 7, 1)
        finally:
            game_mod.random.randint = real
        check(f"{total} 点 → {suit}", (r.get("oracle") or {}).get("suit"), suit)

    # ── ③ 配牌窗口发动 + 播报 + 默认打开 ────────────────────────
    print("\n③ 配牌阶段发动")
    db2 = tg.fresh_db("ora_arm")
    rid2 = new_round(db2, 812, ORD_7)
    g2 = Game(db2, rid2)
    g2.start()
    while not g2.deal_done():
        g2.deal_step()                       # 配牌跑完 → 开配牌技能窗口
    g2 = Game(db2, rid2)
    check("开局在配牌窗口", g2.phase, "deal_skill")
    real = random.randint
    game_mod.random.randint = force_dice(9)          # 9 → 筒
    try:
        r2 = g2.deal_action(0, "use", 7, 1)
    finally:
        game_mod.random.randint = real
    check("发动成功", r2.get("armed"), True)
    check("花色是筒", (r2.get("oracle") or {}).get("suit"), "p")
    check("默认打开", (r2.get("oracle") or {}).get("on"), True)
    check("窗口里不再等我（掷完就算决定完）", sorted(g2.deal_wait), [])
    check("阶段变切牌", g2.phase, "discard")
    b = g2.broadcast or {}
    check("播报文字格式", b.get("text"), "【降神】：随机花色为【筒】")
    check("技能还在（不算一次性用掉）", 0 in g2.deal_used, False)
    check("state 里看得到花色", g2.state_for(0)["oracle"]["suit_cn"], "筒")
    check("别人看不到我的降神", g2.state_for(1).get("oracle"), None)
    check("落库后还在", Game(db2, rid2).state_for(0)["oracle"]["on"], True)

    # 再点一次技能：不能再掷
    r3 = g2._start_oracle(0, 7, 1)
    check("已掷过骰子要拒绝", r3.get("already"), True)
    check("花色没变", (r3.get("oracle") or {}).get("suit"), "p")

    # ── ④ 打开 / 关闭 ───────────────────────────────────────────
    print("\n④ 再点一次图标：关 / 开")
    check("现在开着", g2.oracle_view(0)["on"], True)
    check("点一下关掉", g2.oracle_toggle(0).get("on"), False)
    check("再点打开", g2.oracle_toggle(0).get("on"), True)
    check("重新读进程也是开", Game(db2, rid2).oracle_view(0)["on"], True)

    # ── ⑤ 摸牌前指定牌 → 和别家 / 牌山交换 ─────────────────────
    print("\n⑤ 指定 5m：下家、对家有 → 换走")
    db3 = tg.fresh_db("ora_pick")
    rid3 = new_round(db3, 813, ORD_7)
    tg.set_hand(db3, rid3, 0, parse_hand("123m456m789m123p1z"), drawn="1z")
    tg.set_hand(db3, rid3, 1, parse_hand("5m5m123p456p789s12s"))     # 下家有两张 5m
    tg.set_hand(db3, rid3, 2, parse_hand("5m123m456p789s123s"))      # 对家一张 5m
    tg.set_hand(db3, rid3, 3, parse_hand("123p456p789p12s1z1z"))     # 上家一张万子都没有
    g3 = Game(db3, rid3)
    g3.oracle[0] = {"suit": "m", "on": True, "dice": 5}
    g3.save_flags()
    g3.phase = "draw"
    g3.turn = 0
    g3.save_flags()
    upcoming = g3._upcoming_wall_seqs(3)
    check("接下来 3 张互不相同", len(set(upcoming)), 3)
    wall_before = [g3.db._one("SELECT tile FROM round_wall WHERE round_id=? AND seq=?",
                              (rid3, s)) for s in upcoming]
    check("下家手里有 5m", g3.hand(1).count("5m"), 2)

    # 先试一张谁都没有的牌
    r0 = g3.oracle_pick(0, "7m")
    check("没人有 7m → 换 0 家", len(r0.get("swaps") or []), 0)

    r5 = g3.oracle_pick(0, "5m")
    swaps = r5.get("swaps") or []
    check("只换一家（下家）", len(swaps), 1)
    check("先换下家", [int(s["seat"]) for s in swaps], [1])
    check("用的是下一张", [int(s["order"]) for s in swaps], [1])
    check("牌山下一张变成 5m",
          g3.db._one("SELECT tile FROM round_wall WHERE round_id=? AND seq=?",
                     (rid3, upcoming[0])), "5m")
    check("牌山下下张没动",
          g3.db._one("SELECT tile FROM round_wall WHERE round_id=? AND seq=?",
                     (rid3, upcoming[1])), str(wall_before[1]))
    check("下家少了一张 5m", g3.hand(1).count("5m"), 1)
    check("下家换到了牌山那张", g3.hand(1).count(str(wall_before[0])),
          parse_hand("5m5m123p456p789s12s").count(str(wall_before[0])) + 1)
    check("对家没被换", g3.hand(2).count("5m"), 1)
    check("上家没动", g3.hand(3), parse_hand("123p456p789p12s1z1z"))
    check("手牌张数不变", [len(g3.hand(s)) for s in range(4)], [13, 13, 13, 13])

    # ── ⑥ 各个拒绝条件 ─────────────────────────────────────────
    print("\n⑥ 拒绝条件")
    try:
        g3.oracle_pick(0, "5p")
        check("花色不对要拒绝", False)
    except RuleError as e:
        check("花色不对要拒绝", "花色" in str(e))
    g3.oracle_toggle(0)                                  # 关掉
    try:
        g3.oracle_pick(0, "5m")
        check("关掉后不能指定", False)
    except RuleError as e:
        check("关掉后不能指定", "关着" in str(e))
    g3.oracle_toggle(0)                                  # 再打开
    g3.phase = "discard"
    try:
        g3.oracle_pick(0, "5m")
        check("不是摸牌前要拒绝", False)
    except RuleError as e:
        check("不是摸牌前要拒绝", "摸牌之前" in str(e))
    g3.phase = "draw"
    g3.turn = 1
    try:
        g3.oracle_pick(0, "5m")
        check("不是我的回合要拒绝", False)
    except RuleError as e:
        check("不是我的回合要拒绝", "摸牌之前" in str(e))
    try:
        g3.oracle_toggle(1)
        check("没掷过骰子不能开关", False)
    except RuleError as e:
        check("没掷过骰子不能开关", "还没掷骰子" in str(e))

    # ── ⑦ 恶灵（Card07 Skill2）：降神发动过 → 只能门清自摸和 ──────────
    print("\n⑦ 恶灵：只能门清自摸和")
    check("skills.has(7,2)", skills.has(7, 2))
    check("名字是「恶灵」", skills.info(7, 2).get("name"), "恶灵")
    check("不是配牌技能", (7, 2) in skills.deal_skills(), False)

    db7 = tg.fresh_db("ora_evil")
    rid7 = new_round(db7, 814, ORD_7)
    # 0 号听 3p（13 张荣和用）；自摸另摆 14 张
    tg.set_hand(db7, rid7, 0, parse_hand("123m456m789m12p55z"))
    g7 = Game(db7, rid7)
    check("没发动降神 → 能荣和", g7._win_ok(0, "3p", tsumo=False), True)
    check("没发动降神 → oracle_lock 是 False", g7._oracle_lock(0), False)
    check("state 里 oracle_lock=False", g7.state_for(0).get("oracle_lock"), False)

    g7.oracle[0] = {"suit": "m", "on": True, "dice": 5}
    g7.save_flags()
    g7 = Game(db7, rid7)                       # 重新读，模拟新进程
    check("发动降神后 oracle_lock=True", g7._oracle_lock(0), True)
    check("state 里 oracle_lock=True", g7.state_for(0).get("oracle_lock"), True)
    check("别人看不到我的限制", g7.state_for(1).get("oracle_lock"), False)
    check("荣和被封", g7._win_ok(0, "3p", tsumo=False), False)

    # 自摸（门清）还能和
    tg.set_hand(db7, rid7, 0, parse_hand("123m456m789m123p55z"), drawn="bai")
    g7 = Game(db7, rid7)
    check("门清自摸还能和", g7._win_ok(0, "bai", tsumo=True), True)
    check("门清 → 手牌是门清", g7.melds(0), [])

    # 有副露（碰）→ 自摸也不让和
    with db7.tx():
        db7.conn.execute(
            "INSERT INTO round_melds(round_id, seat, meld_id, kind, called_tile, from_seat,"
            " tiles_json, rot_index, seqs_json) VALUES(?,?,?,?,?,?,?,?,?)",
            (rid7, 0, 0, "pon", "1p", 1, json.dumps(["1p", "1p", "1p"]), 0, json.dumps([])))
    g7 = Game(db7, rid7)
    check("有副露就不是门清", g7.melds(0) and g7.melds(0)[0]["kind"], "pon")
    check("副露之后自摸也不让和", g7._win_ok(0, "bai", tsumo=True), False)

    # 关掉降神也解除不了（「发动过」就算）
    g7.oracle_toggle(0)
    check("降神关了，但限制还在", g7._oracle_lock(0), True)
    check("关掉之后照样不能荣和", g7._win_ok(0, "3p", tsumo=False), False)

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
