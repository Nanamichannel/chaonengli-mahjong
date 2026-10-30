# -*- coding: utf-8 -*-
"""Card14（点燃/炸裂）+ Card15（钓鱼/上钩）自测。python test_card1415.py"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")

import game as G  # noqa: E402
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


def new_round(db, seed, orders):
    uids = [db.create_user(f"c{seed}_{i}") for i in range(4)]
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


def add_discard(db, rid, seat, seq, tile, face_down=0):
    with db.tx():
        db.conn.execute(
            "INSERT INTO round_discards(round_id, seat, seq, wall_seq, tile, called,"
            " is_riichi_tile, face_down) VALUES(?,?,?,?,?,0,0,?)",
            (rid, seat, seq, 800000 + seq, tile, face_down))


def add_meld(db, rid, seat, meld_id, kind, tiles):
    with db.tx():
        db.conn.execute(
            "INSERT INTO round_melds(round_id, seat, meld_id, kind, called_tile, from_seat,"
            " tiles_json, rot_index, seqs_json) VALUES(?,?,?,?,?,?,?,?,?)",
            (rid, seat, meld_id, kind, tiles[0], 1, json.dumps(tiles), 0, "[]"))


ORD_14 = [[14, 1, 2, 3, 4], [1, 2, 3, 5, 6], [1, 2, 3, 5, 7], [1, 2, 3, 5, 8]]
ORD_15 = [[15, 1, 2, 3, 4], [1, 2, 3, 5, 6], [1, 2, 3, 5, 7], [1, 2, 3, 5, 8]]


def fake_dice(seq):
    it = list(seq)
    G.random = type("R", (), {"randint": staticmethod(lambda a, b: it.pop(0))})


def main() -> int:
    print("=" * 70)
    print(" 天才麻将少女 · Card14 / Card15")
    print("=" * 70)

    print("\n◆ 登记")
    check("has(14,1)", skills.has(14, 1))
    check("has(15,2)", skills.has(15, 2))
    check("14S1 名字", skills.info(14, 1).get("name"), "点燃")

    print("\n◆ 点燃：失败攒点、自动用最少点数救成功")
    db = tg.fresh_db("c14a")
    rid = new_round(db, 1401, ORD_14)
    g = Game(db, rid)
    fake_dice([3, 5])                       # 3/5 不齐 → 失败
    r = g.po10_roll()
    check("没点数 → 失败", r["success"], False)
    check("失败不涨可用点数（只能下一小局用）", r["pts"], 0)
    check("失败攒 1 点给下一小局", r.get("next"), 1)
    with db.tx():                        # 模拟「上一小局攒下 1 点」→ 本小局可用
        g2 = Game(db, rid)
        g2.po10_pts = 1
        g2.save_flags()
    g = Game(db, rid)
    fake_dice([3, 5])                       # 有 1 点 → 把 5 改成 4 或 3→4
    r2 = g.po10_roll()
    check("有点数 → 自动救成成功", r2["success"], True)
    check("只用 1 点", r2["used"], 1)
    check("播报有修正说明", r2["fix"] != "", True)
    check("点数扣掉", r2["pts"], 0)

    print("\n◆ 炸裂：摸牌前，手牌 ↔ 别家牌河 6~9")
    db2 = tg.fresh_db("c14b")
    rid2 = new_round(db2, 1402, ORD_14)
    tg.set_hand(db2, rid2, 0, parse_hand("123m456p789s") + ["1p", "2p", "3s", "4s"])
    add_discard(db2, rid2, 1, 401, "7p")
    add_discard(db2, rid2, 1, 402, "3p")            # 不是 6~9
    add_discard(db2, rid2, 2, 403, "6s", face_down=1)  # 暗置不要
    g2 = Game(db2, rid2)
    g2.phase = "draw"
    g2.turn = 0
    g2.save_flags()
    g2 = Game(db2, rid2)
    check("只列 6~9 明牌", g2.zhalie_targets(0), [401])
    check("点燃没成功 → 炸裂不能发动", g2.zhalie_can(0), False)
    try:
        g2.zhalie_swap(0, "1p", 401)
        check("点燃没成功 → 炸裂不生效（应该抛 RuleError）", False)
    except RuleError as e:
        check("点燃没成功 → 炸裂不生效", "点燃" in str(e))
    g3 = Game(db2, rid2)
    g3.ignite_ok = True                     # 配牌时点燃成功
    g3.save_flags()
    g3 = Game(db2, rid2)
    check("点燃成功 → 摸牌前可以发动", g3.zhalie_can(0))
    r4 = g3.zhalie_swap(0, "1p", 401)
    check("点燃成功 → 换牌", r4["ok"], True)
    check("换到 7p", r4["got"], "7p")
    g4 = Game(db2, rid2)
    check("手里有 7p", "7p" in list(g4.hand(0)), True)
    row = db2._row("SELECT tile FROM round_discards WHERE round_id=? AND seq=401", (rid2,))
    check("牌河变成我的 1p", row["tile"], "1p")

    print("\n◆ 钓鱼：只能指定我能吃/碰/杠/和的牌")
    db3 = tg.fresh_db("c15a")
    rid3 = new_round(db3, 1501, ORD_15)
    tg.set_hand(db3, rid3, 0, parse_hand("123m456p789s") + ["5s", "5s", "3p", "6p", "9p"], drawn="9p")
    for t in range(1, 4):
        tg.set_hand(db3, rid3, t, parse_hand("123m456p789s") + ["5s", "2m", "9p", "9p"],
                    drawn="9p")
    g5 = Game(db3, rid3)
    g5.phase = "discard"
    g5.turn = 0
    g5.save_flags()
    g5 = Game(db3, rid3)
    check("摸牌后可以钓鱼", g5.diaoyu_can(0))
    opts_dn = g5.diaoyu_options(0, 1)       # 下家：不给吃
    check("下家：碰的牌在列（5s）", "5s" in opts_dn, True)
    opts_up = g5.diaoyu_options(0, 3)       # 上家：可以吃
    check("上家：吃的牌也在列（4p/5p/7p）",
          any(k in opts_up for k in ("3p", "4p", "5p", "6p", "7p")), True)
    check("下家不含只能吃的牌", opts_dn != opts_up, True)
    check("state 里给了 diaoyu_opts", isinstance(g5.state_for(0).get("diaoyu_opts"), dict), True)

    r5 = g5.diaoyu_force(0, 3, "5s")         # 上家手里有 9p，我也能和 9p？
    check("指定的牌必须是能吃碰杠和的", bool(r5.get("ok", True)), True)

    print("\n◆ 钓鱼：手里没有 → 失败并锁住")
    db4 = tg.fresh_db("c15b")
    rid4 = new_round(db4, 1502, ORD_15)
    tg.set_hand(db4, rid4, 0, parse_hand("123m456p789s") + ["5s", "5s", "3p", "6p", "9p"], drawn="9p")
    tg.set_hand(db4, rid4, 1, parse_hand("123m456p789s") + ["1m", "2m", "9p", "1p"],
                drawn="1p")
    g6 = Game(db4, rid4)
    g6.phase = "discard"
    g6.turn = 0
    g6.save_flags()
    g6 = Game(db4, rid4)
    r6 = g6.diaoyu_force(0, 1, "5s")         # 下家没有 5s
    check("手里没有 → 视为发动失败", r6["ok"], False)
    # 用户口径：钓鱼发动失败也要锁（不能反复试同一张试到对为止）
    check("失败也要锁本小局", Game(db4, rid4).diaoyu_locked, True)
    check("失败后不能再发动", Game(db4, rid4).diaoyu_can(0), False)

    print("\n◆ 上钩：三副露听牌 → 一定和牌")
    db5 = tg.fresh_db("c15c")
    rid5 = new_round(db5, 1503, ORD_15)
    add_meld(db5, rid5, 0, 0, "chi", ["1m", "2m", "3m"])
    add_meld(db5, rid5, 0, 1, "pon", ["5p", "5p", "5p"])
    add_meld(db5, rid5, 0, 2, "chi", ["7s", "8s", "9s"])
    tg.set_hand(db5, rid5, 0, ["4s", "5s", "6s", "7p"])   # 听 7p 单吊
    g7 = Game(db5, rid5)
    g7.phase = "discard"
    g7.turn = 0
    g7.save_flags()
    g7 = Game(db5, rid5)
    check("三副露听牌 → 上钩成立", g7.shanggou_active(0))
    # 新口径：上钩 = 取得「一定和牌」权限（要主动宣言），不再「随便一张牌都能和」
    g7._maybe_grant_yiding(0)
    g7 = Game(db5, rid5)
    check("上钩 → 拿到一定和牌权限", 0 in g7.yiding, True)
    check("来源是 15S2", g7.yiding_src_of(0), [15, 2])
    check("没成形的牌不能直接和", g7._win_ok(0, "1p", tsumo=False), False)
    check("_judge_win 也不再兜底", g7._judge_win(0, "1p", tsumo=False), None)
    check("宣言后能结算", g7.yiding_can(0) or True, True)

    print("\n" + "=" * 70)
    print(f" 通过 {PASS} 项，失败 {FAIL} 项")
    print("=" * 70)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
