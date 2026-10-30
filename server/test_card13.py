# -*- coding: utf-8 -*-
"""Card13 自测：破发（别人立直时吃牌河）／渣和（无役固定 1 番 30 符）"""
from __future__ import annotations

import json
import os
import sys
import time

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
    uids = [db.create_user(f"po{seed}_{i}") for i in range(4)]
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
            (rid, seat, seq, 700000 + seq, tile, face_down))


ORD_13 = [[13, 1, 2, 3, 4], [1, 2, 3, 5, 6], [1, 2, 3, 5, 7], [1, 2, 3, 5, 8]]
# 手牌：123m 456m 789m 22s 4s6s → 等 5s（顺子）；也留着 5s 做暗置放回那张
H_ME = parse_hand("123m456m789m22s") + ["4s", "6s", "9p"]

# 无役和牌：123m 456m 789m 222s + 单吊 5s
H_DAWA = parse_hand("123m456m222s678p") + ["5s"]


def main() -> int:
    print("=" * 70)
    print(" 天才麻将少女 · Card13（破发 / 渣和）")
    print("=" * 70)

    print("\n◆ 技能登记")
    check("skills.has(13,1)", skills.has(13, 1))
    check("skills.has(13,2)", skills.has(13, 2))
    check("S1 名字", skills.info(13, 1).get("name"), "破发")

    print("\n◆ 破发：只能别人立直之后发动")
    db = tg.fresh_db("po1")
    rid = new_round(db, 1301, ORD_13)
    tg.set_hand(db, rid, 0, H_ME)
    add_discard(db, rid, 1, 101, "5s")
    add_discard(db, rid, 2, 102, "7p", face_down=1)
    g = Game(db, rid)
    check("没有立直窗口 → 不能发动", g.pofa_can(0), False)
    g.pofa_window = {"declarer": 1}
    g.pofa_ask = {"declarer": 1, "waiting": [0], "ts": time.time()}
    g.save_flags()
    g = Game(db, rid)
    check("别人立直后 → 可以发动", g.pofa_can(0), True)
    check("可选牌只有明牌", sorted(g.pofa_seqs(0)), [101])
    check("state 里 pofa_can", g.state_for(0).get("pofa_can"), True)
    check("立直者自己不能破发", g.pofa_can(1), False)

    print("\n◆ 破发：河里一张 + 手牌 2 张 = 副露（吃/碰）")
    try:
        g.pofa_activate(0, 101, ["2p", "3p"])
        check("无效副露 → 拒绝", False)
    except RuleError as e:
        check("无效副露 → 拒绝", "无效副露" in str(e))
    r = g.pofa_activate(0, 101, ["4s", "6s"])
    check("成顺子", r.get("kind"), "chi")
    check("用的是河里那张", r.get("called"), "5s")
    g2 = Game(db, rid)
    check("副露挂上了", len(g2.melds(0)), 1)
    check("手牌少 2 张", len(g2.hand(0)), len(H_ME) - 2)
    check("牌河那张标成被鸣走",
          int(db._row("SELECT called FROM round_discards WHERE round_id=? AND seq=?",
                      (rid, 101))["called"]), 1)
    check("窗口关掉了", g2.pofa_window, None)
    check("阶段：等我暗置打一张", g2.pofa_discard_pending, 0)
    check("回合跳到我", g2.turn, 0)
    rd = g2.pofa_discard(0, "9p")
    check("暗置打出", rd.get("face_down"), True)
    g3 = Game(db, rid)
    check("打出的牌是暗置的",
          int(db._row("SELECT face_down FROM round_discards WHERE round_id=? AND seq=?",
                      (rid, int(rd["seq"])))["face_down"]), 1)
    check("暗置牌不进任何人的振听",
          "9p" not in g3.discards_for_furiten(0), True)

    print("\n◆ 渣和：无役也能和，固定 1 番 30 符")
    db2 = tg.fresh_db("po2")
    rid2 = new_round(db2, 1302, ORD_13)
    tg.set_hand(db2, rid2, 0, H_DAWA)
    g3 = Game(db2, rid2)
    res = g3._judge_win(0, "5s", tsumo=False)
    check("渣和：和得出来（判番给的是 0 番占位）", bool(res), True)
    res = g3.settle_preview(0, None, "ron", res, dry_run=True)   # 1番30符 由结算链垫
    check("标了 dawa", bool(res.get("dawa")), True)
    check("1 番 30 符", (res["han"], res["fu"]), (1, 30))
    check("役种只有渣和", [y["name"] for y in res["yaku"]], ["渣和（无役和牌）"])
    print("       点数", res["pays"].get("total"))
    check("庄家 1 番 30 符 = 1500（不封顶）", res["pays"].get("total"), 1500)

    # 有役的牌不受影响（东东东是役牌）
    tg.set_hand(db2, rid2, 0, parse_hand("123m456m678p") + ["dong", "dong", "dong", "5s"])
    g4 = Game(db2, rid2)
    res2 = g4._judge_win(0, "5s", tsumo=False)
    if res2:
        res2 = g4.settle_preview(0, None, "ron", res2, dry_run=True)
    check("有役时不吃渣和", bool((res2 or {}).get("dawa")), False)

    # 没这张卡的人享受不到
    db3 = tg.fresh_db("po3")
    rid3 = new_round(db3, 1303, [[1, 2, 3, 4, 5], [13, 2, 3, 4, 5],
                                [1, 2, 3, 4, 5], [1, 2, 3, 4, 5]])
    tg.set_hand(db3, rid3, 0, H_DAWA)
    g5 = Game(db3, rid3)
    check("没有 13 号卡 → 无役和不了", g5._judge_win(0, "5s", tsumo=False), None)

    print("\n" + "=" * 70)
    print(f" 通过 {PASS} 项，失败 {FAIL} 项")
    print("=" * 70)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
