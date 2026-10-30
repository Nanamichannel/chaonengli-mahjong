# -*- coding: utf-8 -*-
"""Card22 S2 重做：① 副露连锁（手里面子一起摊）② 四副露后摸牌与全场牌河互换"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")

from game import Game, RuleError  # noqa: E402
from tiles import parse_hand  # noqa: E402
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


def add_river(db, rid, seq, seat, tile, wseq):
    with db.tx():
        db.conn.execute(
            "INSERT OR REPLACE INTO round_discards(round_id, seq, seat, wall_seq, tile,"
            " is_tsumogiri, is_riichi_tile, face_down, called)"
            " VALUES(?,?,?,?,?,1,0,0,0)", (rid, seq, seat, wseq, tile))


def make(tag, seed, hand0, drawn="5m"):
    db = tg.fresh_db(tag)
    rid, _m, _u = tg.new_round(db, seed=seed)
    tg.set_hand(db, rid, 0, hand0 + [drawn], drawn=drawn)
    tg.set_hand(db, rid, 1, parse_hand("1m4m7m1p4p7p1s4s7s1z2z3z"))
    tg.set_hand(db, rid, 2, parse_hand("2m5m8m2p5p8p2s5s8s2z3z4z"))
    tg.set_hand(db, rid, 3, parse_hand("3m6m9m3p6p9p3s6s9s1z2z3z"))
    g = Game(db, rid)
    g.granted = {0: {22}}
    g.round_phase = "play"
    g.turn, g.phase = 0, "discard"
    g.save_flags()
    return db, rid


def into_claim(db, rid):
    """把局面摆成「1 号位打了 5m，0 号位有碰」的鸣牌窗口"""
    add_river(db, rid, 500, 1, "5m", 9500)
    g = Game(db, rid)
    g.phase = "claim"
    g.turn = 1
    g.pending = {"discard_seq": 500, "tile": "5m", "from": 1,
                 "options": {0: [{"action": "pon", "choices": [["5m", "5m"]]}]},
                 "answers": {}}
    g.save_flags()
    return Game(db, rid)


def main() -> int:
    print("=" * 66)
    print(" 天才麻将少女 · Card22 S2（副露连锁 + 四副露换牌）")
    print("=" * 66)

    # ① 鸣牌窗口里能 arm
    print("\n① 鸣牌窗口 = 发动时机")
    db, rid = make("y1", 901, parse_hand("5m5m123m4p5p6p7s8s9s"))
    g = Game(db, rid)
    check("打牌阶段不能 arm", g.youyin_meld_can(0), False)
    g = into_claim(db, rid)
    check("鸣牌窗口里可以 arm", g.youyin_meld_can(0), True)
    r = g.youyin_meld_arm(0)
    check("arm 成功", r.get("armed"), True)
    check("重复 arm 被拒", g.youyin_meld_can(0), False)

    # ② 副露后进入「摊面子」
    print("\n② 副露后摊面子")
    g = into_claim(db, rid)
    g.youyin_meld_armed = 0
    g.save_flags()
    g = Game(db, rid)
    ev = g._apply_claim(0, "pon", ["5m", "5m"],
                        {"tile": "5m", "from": 1, "discard_seq": 500})
    check("事件是 youyin_meld", ev.get("event"), "youyin_meld")
    check("phase = youyin_meld", g.phase, "youyin_meld")
    check("state 下发了 offer",
          isinstance(g.state_for(0).get("youyin_meld_offer"), dict), True)
    pr = g.prompt_state() or {}
    check("询问锁 = youyin_meld", pr.get("kind"), "youyin_meld")

    # ③ 一次摊 1 组，摊完继续问，直到手里没有面子
    print("\n③ 一次一组，循环摊到没有面子")
    before = sorted(Game(db, rid).hand(0))
    r2 = g.youyin_meld_pick(0, ["1m", "2m", "3m"])
    check("这次摊了 1 组", r2.get("n"), 1)
    check("还有面子 → 继续问", r2.get("more"), True)
    g2 = Game(db, rid)
    check("手里少了 3 张", len(g2.hand(0)), len(before) - 3)
    check("还在摊面子阶段", g2.phase, "youyin_meld")
    r3 = g2.youyin_meld_pick(0, ["4p", "5p", "6p"])
    check("第二组还有更多", r3.get("more"), True)
    g3 = Game(db, rid)
    r4 = g3.youyin_meld_pick(0, ["7s", "8s", "9s"])
    check("最后一组 → 没有更多", r4.get("more"), False)
    g4b = Game(db, rid)
    kinds = [str(r["kind"]) for r in g4b.db._rows(
        "SELECT kind FROM round_melds WHERE round_id=? AND seat=0", (rid,))]
    check("生成的是 open_set（3 组 + 1 张碰）", sorted(kinds).count("open_set"), 3)
    check("另有一副碰", sorted(kinds).count("pon"), 1)
    check("回到打牌", g4b.phase, "discard")
    check("摊完 offer 清空", g4b.youyin_meld_offer, None)
    check("摊完不再挂看破（回归卡死）", g4b.kangpo_ask, None)
    check("摊完 kangpo_pending 为空", g4b.kangpo_pending, None)
    check("摊完没有询问锁", g4b.prompt_state(), None)
    check("段1 不写 used_skills（段2 还要能用）", g4b.skill_used(0, 22, 2), False)
    check("段1 记在 youyin_meld_done", 0 in g4b.youyin_meld_done, True)

    # ④ 无效副露
    print("\n④ 无效副露要拒绝且状态不变")
    db4, rid4 = make("y2", 902, parse_hand("5m5m123m4p5p6p7s8s9s"))
    g4 = into_claim(db4, rid4)
    g4.youyin_meld_armed = 0
    g4.save_flags()
    g4 = Game(db4, rid4)
    g4._apply_claim(0, "pon", ["5m", "5m"], {"tile": "5m", "from": 1, "discard_seq": 500})
    n_before = len(Game(db4, rid4).hand(0))
    try:
        g4.youyin_meld_pick(0, ["1m", "2m", "4p"])     # 12m + 4p 不是面子
        check("无效副露要被拒", False)
    except RuleError as e:
        check("无效副露要被拒", "无效副露" in str(e))
    g5 = Game(db4, rid4)
    check("手牌没动", len(g5.hand(0)), n_before)
    check("还等着重选", isinstance(g5.youyin_meld_offer, dict), True)

    # ⑤ 4 张同种 = 一组杠式副露
    print("\n⑤ 4 张同种可以当一组摊出来")
    db6, rid6 = make("y3", 903, parse_hand("5m5m2p2p2p2p123m456p"))
    g6 = into_claim(db6, rid6)
    g6.youyin_meld_armed = 0
    g6.save_flags()
    g6 = Game(db6, rid6)
    g6._apply_claim(0, "pon", ["5m", "5m"], {"tile": "5m", "from": 1, "discard_seq": 500})
    r6 = g6.youyin_meld_pick(0, ["2p", "2p", "2p", "2p"])
    check("摊了 1 组", r6.get("n"), 1)
    g6b = Game(db6, rid6)
    four = [r for r in g6b.db._rows(
        "SELECT kind, tiles_json FROM round_melds WHERE round_id=? AND seat=0", (rid6,))
        if str(r["kind"]) == "open_set"]
    check("副露 4 张", [len(__import__("json").loads(r["tiles_json"])) for r in four], [4])
    check("全竖置（rot_index=-1）", g6b.db._one(
        "SELECT rot_index FROM round_melds WHERE round_id=? AND seat=0 AND kind='open_set'",
        (rid6,)), -1)

    # ⑤-b 明杠之后也摊面子，且岭上牌推迟到摊完之后才补
    print("\n⑤-b 明杠 → 摊面子 → 摊完才补岭上牌")
    db7b, rid7b = make("y3b", 905, parse_hand("5m5m5m123m4p5p6p"))
    g7b = into_claim(db7b, rid7b)
    g7b.youyin_meld_armed = 0
    g7b.save_flags()
    g7b = Game(db7b, rid7b)
    dora0 = len(Game(db7b, rid7b).revealed_dora("dora"))
    hand0 = len(g7b.hand(0))
    ev7 = g7b._apply_claim(0, "minkan", ["5m", "5m", "5m"],
                           {"tile": "5m", "from": 1, "discard_seq": 500})
    check("明杠也进摊面子", str(ev7.get("event")), "youyin_meld")
    g7c = Game(db7b, rid7b)
    check("杠完还没补岭上牌", len(g7c.hand(0)), hand0 - 3)
    check("杠完还没翻宝牌", len(Game(db7b, rid7b).revealed_dora("dora")), dora0)
    check("记了待补岭上", 0 in g7c.pending_rinshan, True)
    r7b = g7c.youyin_meld_pick(0, parse_hand("123m"))
    check("摊完 123m 还有面子（4p5p6p）", r7b.get("more"), True)
    g7c2 = Game(db7b, rid7b)
    check("还有面子时先不补岭上", len(g7c2.hand(0)), hand0 - 3 - 3)
    r7c = g7c2.youyin_meld_pick(0, parse_hand("456p"))
    check("摊完第 2 组手里没面子了", r7c.get("more"), False)
    g7d = Game(db7b, rid7b)
    check("摊完补上了岭上牌", len(g7d.hand(0)), hand0 - 3 - 6 + 1)
    check("摊完翻了新宝牌", len(Game(db7b, rid7b).revealed_dora("dora")), dora0 + 1)
    check("待补岭上清空", 0 in g7d.pending_rinshan, False)
    check("回到打牌", g7d.phase, "discard")
    check("这张是岭上牌", g7d.last_was_rinshan, True)

    # ⑤-c 加杠 / 暗杠的窗口里也能 arm
    print("\n⑤-c 加杠 / 暗杠窗口能 arm")
    db8 = tg.fresh_db("y3c")
    rid8, _m8, _u8 = tg.new_round(db8, seed=906)
    tg.set_hand(db8, rid8, 0, parse_hand("2p2p2p2p123m456p789s"))
    for _s in (1, 2, 3):
        tg.set_hand(db8, rid8, _s, parse_hand("1m4m7m1p4p7p1s4s7s1z2z3z"))
    g8 = Game(db8, rid8)
    g8.granted = {0: {22}}
    g8.round_phase = "play"
    g8.turn, g8.phase = 0, "discard"
    g8.save_flags()
    g8 = Game(db8, rid8)
    acts = [str(a.get("action", "")) for a in g8.legal_actions(0)]
    check("手里有 4 张同种 → 能暗杠", "ankan" in acts, True)
    check("暗杠窗口里能 arm 友引", g8.youyin_meld_can(0), True)

    # ⑥ 四副露后摸牌才能换
    print("\n⑥ 四副露后摸牌换牌")
    db7 = tg.fresh_db("y4")
    rid7, _m7, _u7 = tg.new_round(db7, seed=904)
    tg.set_hand(db7, rid7, 0, parse_hand("123m456p789s1z1z1z") + ["5s", "5s"], drawn="5s")
    for s in (1, 2, 3):
        tg.set_hand(db7, rid7, s, parse_hand("1m4m7m1p4p7p1s4s7s1z2z3z"))
    with db7.tx():
        for i, tl in enumerate(("1m2m3m", "456p", "789s", "1z1z1z")):
            db7.meld(rid7, 0, "open_set", parse_hand(tl), called_tile="",
                     from_seat=-1, from_discard_seq=None, rot_index=-1)
    with db7.tx():                       # 副露会把 is_drawn 清掉 → 模拟「刚摸完牌」
        db7.conn.execute(
            "UPDATE round_hands SET is_drawn=1 WHERE round_id=? AND seat=0 AND wall_seq="
            "(SELECT MAX(wall_seq) FROM round_hands WHERE round_id=? AND seat=0)",
            (rid7, rid7))
    add_river(db7, rid7, 600, 1, "7p", 9600)
    g7 = Game(db7, rid7)
    g7.granted = {0: {22}}
    g7.round_phase = "play"
    g7.turn, g7.phase = 0, "discard"
    g7.save_flags()
    g7 = Game(db7, rid7)
    check("四副露 + 刚摸牌 → 可以换", g7.youyin_swap_can(0), True)
    r7 = g7.youyin_take(0, 600, "5s")
    check("换到 7p", r7.get("got"), "7p")
    check("5s 进了牌河", db7._one(
        "SELECT tile FROM round_discards WHERE round_id=? AND seq=600", (rid7,)), "5s")
    check("手牌里有 7p", "7p" in Game(db7, rid7).hand(0), True)
    check("换完还是我的回合、能打牌", Game(db7, rid7).turn, 0)

    print("\n" + "=" * 66)
    print(f" 通过 {PASS} / 失败 {FAIL}")
    print("=" * 66)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
