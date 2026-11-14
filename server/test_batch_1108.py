# -*- coding: utf-8 -*-
"""2026-11-08 那批 bug 的回归：一发 / 友引 rot_all / 恶听指示牌 / 传承技能归属 /
见逃（恶灵·神境）/ 新手运 swap 兜底 / 终局 next 保护。

跑法：cd server; python test_batch_1108.py
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")

from game import Game          # noqa: E402
import api_cli                 # noqa: E402
import test_card30 as t30      # noqa: E402
import test_game as tg         # noqa: E402

PASS = 0
FAIL = 0
H13 = ["1m", "2m", "3m", "4p", "5p", "6p", "7s", "8s", "dong", "nan", "xi", "5s", "6s"]


def check(name, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  got={got!r} want={want!r}")


def base(tag, mains=None):
    db, rid = t30.setup(tag, card=8, mains=mains or [8, 8, 8, 8])
    for s in range(4):
        tg.set_hand(db, rid, s, H13)
    with db.tx():
        db.conn.execute("DELETE FROM round_dora WHERE round_id=?", (rid,))
        db.conn.execute("DELETE FROM round_discards WHERE round_id=?", (rid,))
        db.conn.execute("DELETE FROM round_riichi WHERE round_id=?", (rid,))
    return db, rid


def add_discard(db, rid, seat, seq, tile, riichi=0):
    with db.tx():
        db.conn.execute(
            "INSERT INTO round_discards(round_id, seat, seq, wall_seq, tile, called,"
            " is_riichi_tile, face_down, is_tsumogiri) VALUES(?,?,?,?,?,0,?,0,0)",
            (rid, seat, seq, 800000 + seq, tile, int(riichi)))


def main() -> int:
    print("=" * 74)
    print(" 2026-11-08 回归批")
    print("=" * 74)

    # ── ① 一发：立直后打完那一张就该结束 ───────────────────────────
    print("\n① 一发：立直后自己摸打一次 → 之后荣和没有一发")
    db, rid = base("b1108a")
    g = Game(db, rid)
    g.round_phase, g.phase, g.turn = "play", "discard", 0
    g.ippatsu = {0}
    g.round_riichi = getattr(g, "round_riichi", None)
    with db.tx():
        db.conn.execute("INSERT INTO round_riichi(round_id, seat, declared_seq, ippatsu)"
                        " VALUES(?,0,10,1)", (rid,))
    add_discard(db, rid, 0, 10, "1m", riichi=1)      # 立直宣言牌
    g.save_flags()
    g = Game(db, rid)
    check("立直宣言那张不算「已经打过」", g._ippatsu_over(0), False)
    # 立直后自己摸打一张 → 一发巡结束
    tg.set_hand(db, rid, 0, H13[:-1] + ["9p"], drawn="9p")
    g = Game(db, rid)
    g.round_phase, g.phase, g.turn = "play", "discard", 0
    g.save_flags()
    g = Game(db, rid)
    r = g.act(0, "discard", tile="9p")
    check("打完这一张", bool(r is not None), True)
    g2 = Game(db, rid)
    check("一发已经清掉", 0 in g2.ippatsu, False)
    check("_ippatsu_over 为真", g2._ippatsu_over(0), True)

    # ── ② 友引摊面子：rot_all 必须是 False（全竖）────────────────────
    print("\n② 友引 open_set：rot_all=False / rot_index=-1")
    db2, rid2 = base("b1108b")
    with db2.tx():
        db2.conn.execute(
            "INSERT INTO round_melds(round_id, meld_id, seat, kind, called_tile, from_seat,"
            " tiles_json, rot_index, from_discard_seq, seqs_json)"
            " VALUES(?,0,1,'open_set','',-1,?, -1, NULL, ?)",
            (rid2, json.dumps(["2p", "3p", "4p"]), json.dumps([71, 72, 73])))
    g3 = Game(db2, rid2)
    m = g3.melds(1)[0]
    check("kind 是 open_set", m["kind"], "open_set")
    check("rot_all = False（全竖置）", bool(m["rot_all"]), False)
    check("rot_index = -1", int(m["rot_index"]), -1)

    # ── ③ 恶听：已翻开的表宝牌指示牌不算「看不见的牌」────────────────
    print("\n③ 恶听：明着的指示牌不进隐藏池")
    db3, rid3 = base("b1108c")
    g4 = Game(db3, rid3)
    rows = db3._rows("SELECT seq FROM round_wall WHERE round_id=? AND dealt_to IS NULL"
                     " ORDER BY seq LIMIT 1", (rid3,))
    bad_seq = int(rows[0]["seq"])
    before = g4._c46_hidden_counts(0)
    kind_of_bad = str(db3._one("SELECT tile FROM round_wall WHERE round_id=? AND seq=?",
                               (rid3, bad_seq)))
    g4.revealed_dora_seqs = lambda: {bad_seq}          # 假装这张是翻开的指示牌
    g4.ura_indicator_seqs = lambda: set()
    after = g4._c46_hidden_counts(0)
    check("那张牌的计数少了 1", int(before.get(kind_of_bad, 0)) - int(after.get(kind_of_bad, 0)), 1)
    g4.jiasuo_on = {0}
    g4.ura_indicator_seqs = lambda: {bad_seq}
    after2 = g4._c46_hidden_counts(0)
    check("枷锁主连里宝也跳过（同一张同理）",
          int(after2.get(kind_of_bad, 0)), int(after.get(kind_of_bad, 0)))

    # ── ④ 传承：复制 2-2 不能把 2-1 放出来 ───────────────────────────
    print("\n④ 传承：只认复制的那个技能")
    db4, rid4 = base("b1108d")
    g5 = Game(db4, rid4)
    g5.cc_copy = {0: {"card": 2, "skill": 2}}
    g5.cc_grants = {"2-2-0"}
    g5.granted = {0: {2}}
    g5.round_phase, g5.phase, g5.turn = "play", "draw", 0
    check("复制来的 2-2 可用", g5.owns_skill(0, 2, 2), True)
    check("同卡的 2-1 不可用", g5.owns_skill(0, 2, 1), False)
    check("画板 can = False", g5.board_can(0), False)
    g5.save_flags()
    g6 = Game(db4, rid4)
    check("落库后仍然只认 2-2", g6.owns_skill(0, 2, 1), False)
    g7 = Game(db4, rid4)
    g7.cc_copy = {}
    g7.cc_grants = set()
    check("没有复制时（测试环境无卡序）两个都放行", g7.owns_skill(0, 2, 1), True)

    # ── ⑤ 见逃：神境 / 恶灵 封掉的荣和也记振听 ───────────────────────
    print("\n⑤ 见逃：技能封荣 → 同巡振听")
    db5, rid5 = base("b1108e")
    # 1 号位听 5s（123m 456p 789s? 这里用单骑：111m999p234s567s + 5p 等 5p）
    win13 = ["1m", "1m", "2m", "2m", "3p", "3p", "4p", "4p", "5s", "5s", "6s", "6s", "7s"]
    tg.set_hand(db5, rid5, 1, win13)
    g8 = Game(db5, rid5)
    g8.round_phase, g8.phase, g8.turn = "play", "discard", 0
    check("这手能荣 7s（七对子）", g8._win_ok(1, "7s", tsumo=False), True)
    g8.c45s1_on = {1}                                  # 神境
    g8.temp_furiten = set()
    g8.save_flags()
    g9 = Game(db5, rid5)
    g9._open_claim_window(901, "7s", 0)
    g9 = Game(db5, rid5)
    check("神境封荣 → 记同巡振听", 1 in g9.temp_furiten, True)

    db6, rid6 = base("b1108f")
    tg.set_hand(db6, rid6, 1, win13)
    g10 = Game(db6, rid6)
    g10.round_phase, g10.phase, g10.turn = "play", "discard", 0
    g10.oracle = {1: {"suit": "m", "on": True, "dice": 3}}                     # 恶灵（掷过降神）
    g10.temp_furiten = set()
    g10.save_flags()
    g11 = Game(db6, rid6)
    g11._open_claim_window(902, "7s", 0)
    g11 = Game(db6, rid6)
    check("恶灵封荣 → 记同巡振听", 1 in g11.temp_furiten, True)

    # ── ⑥ 新手运 swap 没人操作 → 服务端代换 ─────────────────────────
    print("\n⑥ 新手运 swap 兜底")
    db7, rid7 = base("b1108g")
    tg.set_hand(db7, rid7, 0, H13)
    tg.set_hand(db7, rid7, 1, H13)
    g12 = Game(db7, rid7)
    g12.phase = "deal_skill"
    g12.deal_flow = {"kind": "c32", "seat": 0, "card": 32, "skill": 1,
                     "targets": [1], "stage": 0, "sub": "swap", "target": 1,
                     "picked": ["1m"], "min": 1, "max": 1}
    g12.deal_wait = {0}
    g12.deal_used = set()
    g12.save_flags()
    g13 = Game(db7, rid7)
    r2 = g13.c32s1_auto_swap(0)
    check("替发动者换了牌", bool(r2.get("skipped") in (None, False)), True)
    g14 = Game(db7, rid7)
    check("流程收尾（deal_flow 清空）", g14.deal_flow, None)
    check("配牌窗口也不再等他", 0 in g14.deal_wait, False)

    # ── ⑦ 终局：半庄已结束时 op=next 不许开新的一场 ──────────────────
    print("\n⑦ 终局 op=next 保护")
    db8, rid8 = base("b1108h")
    with db8.tx():
        db8.conn.execute("UPDATE matches SET status='finished', final_json=?",
                         (json.dumps({"0": 1000, "1": 2000, "2": 3000, "3": 4000}),))
        db8.conn.execute("UPDATE rounds SET status='ended', result='ron', winner_seat=3,"
                         " loser_seat=0, points=1000 WHERE round_id=?", (rid8,))
        db8.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('local_round_id', ?)",
                         (str(rid8),))
    n_before = int(db8._one("SELECT COUNT(*) FROM matches"))
    out = api_cli.handle({"op": "next", "seat": 0}, db8.path)
    check("回 match_finished", bool(out.get("match_finished")), True)
    check("带名次", len(out.get("final_rank") or []), 4)
    n_after = int(db8._one("SELECT COUNT(*) FROM matches"))
    check("没有开新的一场", n_after, n_before)

    print("\n" + "=" * 74)
    print(f" 合计：{PASS} 断言，{FAIL} 失败")
    print("=" * 74)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
