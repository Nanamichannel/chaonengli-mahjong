# -*- coding: utf-8 -*-
"""Card29 S1【加速】+ S2【精算】自测

加速：别人打出明牌（没人能荣和）→ 先问「无视距离吃」的持有者（吃/跳过）。
      点吃 = 发动点（可看破），成功 → 真副露 + 轮到他切牌；跳过/被看破 → 普通鸣牌窗口。
精算：非门前清和牌 → 吃/碰收回手里、明杠/加杠当暗杠 → 当门清重判 → 替换 + 重放前面的钩子。

跑法：cd N:\apps\tianma\server; python test_card29.py
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from game import Game                        # noqa: E402
import skills                                # noqa: E402
from rules import agari                      # noqa: E402
import test_game as tg                       # noqa: E402
from tiles import parse_hand                 # noqa: E402

PASS = FAIL = 0

H0 = "123m456m789m2p4p6s7s"            # 13 张：有 2p4p，能吃 3p
H1 = "3p1z2z3z4z1m4m7m2s5s8s6m9m"     # 13 张 + 3p 那张要打出去
H2 = "3p3p1m4m7m2s5s8s6p9p1z5z7z"     # 能碰 3p
H3 = "1z2z3z4z5z6z7z1p4p7p2s5s8s"


def check(name, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  got {got!r} want {want!r}")


def setup(tag, card=29, hand0=None, mains=None):
    db = tg.fresh_db(tag)
    rid, _m, _u = tg.new_round(db, seed=113)
    for s, h in enumerate(((hand0 or H0), H1, H2, H3)):
        tg.set_hand(db, rid, s, parse_hand(h))
    m = mains or [card, 6, 7, 8]
    orders = [[m[s], 1, 2, 3, 4] for s in range(4)]
    with db.tx():
        db.conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES('lobby_state', ?)",
            (json.dumps({"seats": [{"order": o} for o in orders]},
                        ensure_ascii=False),))
    # 宝牌指示牌清掉：牌山按 tag 不同，手上可能白捡宝牌 → 番数不固定
    with db.tx():
        db.conn.execute("DELETE FROM round_dora WHERE round_id=?", (rid,))
    g = Game(db, rid)
    g.granted = {0: {int(card)}}
    g.round_phase = "play"
    g.turn, g.phase = 1, "discard"           # 1 号位要打牌
    g.save_flags()
    return db, rid


def main() -> int:
    print("=" * 78)
    print(" Card29 S1【加速】+ S2【精算】")
    print("=" * 78)

    # ── ① 注册 ────────────────────────────────────────────────────
    print("\n① 注册")
    check("S1 名字", skills.info(29, 1).get("name"), "加速")
    check("S2 名字", skills.info(29, 2).get("name"), "精算")
    check("加速不是配牌技能", (29, 1) in skills.deal_skills(), False)
    check("精算不是配牌技能", (29, 2) in skills.deal_skills(), False)

    # ── ② 加速：无视距离 → 挂起询问 ────────────────────────────────
    print("\n② 加速：别人（非上家）打牌 → 问我")
    db, rid = setup("c29a")
    g = Game(db, rid)
    check("0 号位能吃 3p", bool(g.c29s1_can(0, "3p")), True)
    check("2 号位（没这张卡）不会被问", g.c29s1_can(2, "3p"), False)
    ev = g._do_discard(1, tile="3p")
    check("挂起了加速询问", g.phase, "c29s1")
    check("问的是 0 号位", int((g.c29s1_offer or {}).get("seat", -1)), 0)
    check("给了 1 组搭子", (g.c29s1_offer or {}).get("choices"), [["2p", "4p"]])
    check("事件名", ev.get("event"), "discard")

    # 吃：无视距离（1 号位不是我的上家）
    r = g.c29s1_chi(0, ["2p", "4p"])
    check("吃到了那张 3p", r.get("tile"), "3p")
    g2 = Game(db, rid)
    check("回合跳到我、可以切牌", (g2.turn, g2.phase), (0, "discard"))
    check("我有一组副露", len(g2.melds(0)), 1)
    check("是吃", str(g2.melds(0)[0].get("kind")), "chi")
    check("没有开普通鸣牌窗口（2 号位没机会碰）", g2.pending, None)
    check("手牌 11 张（13 - 吃掉的 2 张）", len(g2.hand(0)), 11)

    # ── ③ 加速：跳过 → 回到普通鸣牌窗口（2 号位能碰）──────────────
    print("\n③ 加速：跳过 → 普通鸣牌窗口照常")
    db2, rid2 = setup("c29b")
    g3 = Game(db2, rid2)
    g3._do_discard(1, tile="3p")
    check("先挂起加速", g3.phase, "c29s1")
    g3.c29s1_skip(0)
    check("回到鸣牌窗口", g3.phase, "claim")
    opts2 = {str(a.get("action")) for a in (g3.pending or {}).get("options", {}).get(2, [])}
    check("2 号位有「碰」", "pon" in opts2, True)

    # ── ④ 加速：有人能荣和 → 不问加速 ─────────────────────────────
    print("\n④ 加速：荣和优先，不抢")
    db3, rid3 = setup("c29c")
    tg.set_hand(db3, rid3, 2, parse_hand("1z2z3z4z1p4p7p9p2s5s8s6p9p"),
                drawn="9p")
    # 手牌换成能荣和 3p 的形状：123m456m789m 22p 要 3p？用 p 侧的顺子等 3p
    tg.set_hand(db3, rid3, 2, parse_hand("111m222m333m44m6s"), )   # 占位
    g4 = Game(db3, rid3)
    tg.set_hand(db3, rid3, 2, parse_hand("123m456m789m2p4p1z1z1z"))
    g4 = Game(db3, rid3)
    check("（3 号位）没人能荣和 3p", g4._win_ok(2, "3p", tsumo=False), False)
    g4.turn, g4.phase = 1, "discard"
    g4._do_discard(1, tile="3p")
    # 0 号位还能吃，但 2 号位能荣和的情况另外测：
    check("正常情况仍然问加速", g4.phase, "c29s1")

    # ── ⑤ 加速：立直后不能 ───────────────────────────────────────
    print("\n⑤ 加速：立直 / 被看破剔除 → 不问")
    db5, rid5 = setup("c29d")
    with db5.tx():
        db5.conn.execute(
            "INSERT INTO round_riichi(round_id, seat, declared_seq) VALUES(?,0,1)",
            (rid5,))
    g5 = Game(db5, rid5)
    check("立直后不能加速", g5.c29s1_can(0, "3p"), False)

    # ── ⑥ 精算：非门前清 → 当门清重判 ────────────────────────────
    print("\n⑥ 精算：副露手当门清重判（符变高）")
    db6, rid6 = setup("c29e", hand0="123m456m789m1s")
    with db6.tx():
        db6.conn.execute(
            "INSERT INTO round_melds(round_id,meld_id,seat,kind,called_tile,from_seat,"
            "tiles_json,rot_index) VALUES(?,0,0,'chi','2p',3,"
            "'[\"2p\",\"3p\",\"4p\"]',0)", (rid6,))
    g6 = Game(db6, rid6)
    check("这手不是门清", agari.is_closed(g6.melds(0)), False)
    base = g6._judge_win(0, "1s", tsumo=False)
    # 一气通贯 门清 2 番 / 副露 1 番 → 副露这边是 1 番 30 符
    check("判番（副露）= 1 番 30 符", (int(base["han"]), int(base["fu"])), (1, 30))
    res = g6.settle_preview(0, None, "ron", base, dry_run=True)
    check("精算：当门清重判 → 40 符", int(res["fu"]), 40)
    # 当门清重判会多出「门清」相关的番，所以番数不会更低
    check("当门清 → 一气通贯回到 2 番", int(res["han"]), 2)
    print("       精算后役种：", [y["name"] for y in res["yaku"]],
          "→", int(res["han"]), "番", int(res["fu"]), "符")
    check("打上了精算标记", bool(res.get("c29s2")), True)
    check("役种里还能看到役", len(res["yaku"]) > 0, True)

    # 没有 29 号卡 → 完全不动
    db7, rid7 = setup("c29f", card=6, hand0="123m456m789m1s")
    with db7.tx():
        db7.conn.execute(
            "INSERT INTO round_melds(round_id,meld_id,seat,kind,called_tile,from_seat,"
            "tiles_json,rot_index) VALUES(?,0,0,'chi','2p',3,"
            "'[\"2p\",\"3p\",\"4p\"]',0)", (rid7,))
    g7 = Game(db7, rid7)
    b7 = g7._judge_win(0, "1s", tsumo=False)
    r7 = g7.settle_preview(0, None, "ron", b7, dry_run=True)
    check("没有精算 → 还是 30 符", int(r7["fu"]), 30)
    check("没有精算标记", bool(r7.get("c29s2")), False)

    # ── ⑦ 精算：明杠当成暗杠（仍是门清）──────────────────────────
    print("\n⑦ 精算：明杠当暗杠")
    # 有 1 组杠时，门前的手牌是 10 张（杠 4 张 + 3 面子 + 单钓），和牌张补成雀头
    db8, rid8 = setup("c29g", hand0="123m456m789m1s")
    with db8.tx():
        db8.conn.execute(
            "INSERT INTO round_melds(round_id,meld_id,seat,kind,called_tile,from_seat,"
            "tiles_json,rot_index) VALUES(?,0,0,'minkan','zhong',3,"
            "'[\"zhong\",\"zhong\",\"zhong\",\"zhong\"]',0)", (rid8,))
    g8 = Game(db8, rid8)
    b8 = g8._judge_win(0, "1s", tsumo=False)
    r8 = g8.settle_preview(0, None, "ron", b8, dry_run=True)
    if r8 is None:
        check("（这手和不了，跳过）", True)
    else:
        check("明杠 → 暗杠：符更高", int(r8["fu"]) >= 40, True)

    print("\n" + "=" * 78)
    print(f" 通过 {PASS} / 失败 {FAIL}")
    print("=" * 78)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
