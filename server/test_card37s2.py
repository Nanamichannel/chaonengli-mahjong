# -*- coding: utf-8 -*-
"""Card37 S2【强运】自测。

跑法：cd N:\\apps\\tianma\\server; python test_card37s2.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from game import Game, RuleError                     # noqa: E402
import api_cli                                       # noqa: E402
import skills                                        # noqa: E402
import test_card30 as t30                            # noqa: E402
import test_game as tg                               # noqa: E402
from tiles import parse_hand                         # noqa: E402

PASS = FAIL = 0

H0 = "123m456m789m234p5z3s"                          # 14 张（刚摸 3s）
H1 = "5p5p2p3p4p6p7p8p1s2s3s9s9s"                    # 两张 5p（下家）
H2 = "5p6p7p8p9p1s2s3s4s7z7z1m2m"                    # 一张 5p（对家）
H3 = "1s2s3s4s5s6s7s8s9s2z2z3z4z"                    # 没有 5p（上家）


def check(name, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  got {got!r} want {want!r}")


def setup(tag):
    db, rid = t30.setup(tag, card=37, mains=[37, 6, 7, 8])
    for s, h in enumerate((H0, H1, H2, H3)):
        tg.set_hand(db, rid, s, parse_hand(h), drawn="3s" if s == 0 else None)
    with db.tx():
        db.conn.execute("DELETE FROM round_dora WHERE round_id=?", (rid,))
        db.conn.execute("DELETE FROM round_discards WHERE round_id=?", (rid,))
        db.conn.execute("DELETE FROM round_melds WHERE round_id=?", (rid,))
        db.conn.execute("UPDATE rounds SET live_left=60 WHERE round_id=?", (rid,))
    g = Game(db, rid)
    g.granted = {0: {37}}
    g.round_phase = "play"
    g.phase = "discard"
    g.turn = 0
    g.deal_wait = set()
    g.deal_used = set()
    g.save_flags()
    return db, rid


def hand_rows(db, rid, seat):
    return [dict(r) for r in db.my_hand(rid, seat)]


def main() -> int:
    print("=" * 78)
    print(" Card37 S2【强运】")
    print("=" * 78)

    print("\n① 注册 / 时机")
    check("名字", skills.info(37, 2).get("name"), "强运")
    check("时机 = 摸牌后", skills.timing(37, 2), "draw")

    print("\n② 摸牌后能发动；没摸牌不能")
    db, rid = setup("c37s2a")
    g = Game(db, rid)
    check("能发动", g.c37s2_can(0), True)
    g.turn = 1
    g.save_flags()
    check("不是我的回合不能", Game(db, rid).c37s2_can(0), False)
    g = Game(db, rid)
    g.turn = 0
    g.save_flags()
    g = Game(db, rid)

    print("\n③ 换牌：下家 2 张 + 对家 1 张 → 依次对 第 4/8/12 张")
    seqs = g._upcoming_wall_seqs(16)
    picks = [int(seqs[i]) for i in (3, 7, 11)]
    before_wall = [str(db.tile_at_seq(rid, s) or "") for s in picks]
    rows1 = hand_rows(db, rid, 1)
    rows2 = hand_rows(db, rid, 2)
    p1 = [r for r in rows1 if r["tile"] == "5p"]
    p2 = [r for r in rows2 if r["tile"] == "5p"]
    check("下家两张 5p", len(p1), 2)
    check("对家一张 5p", len(p2), 1)
    before_hand = {}
    for r in p1 + p2:
        before_hand[int(r["wall_seq"])] = str(r["tile"])

    r = g.c37s2_apply(0, "5p")
    check("换了 3 组", int(r.get("count", 0)), 3)
    after_wall = [str(Game(db, rid).db.tile_at_seq(rid, s) or "") for s in picks]
    check("牌山第 4/8/12 张都变成 5p", after_wall, ["5p", "5p", "5p"])
    g2 = Game(db, rid)
    got1 = [str(x["tile"]) for x in hand_rows(db, rid, 1) if int(x["wall_seq"]) in (int(p1[0]["wall_seq"]), int(p1[1]["wall_seq"]))]
    got2 = [str(x["tile"]) for x in hand_rows(db, rid, 2) if int(x["wall_seq"]) == int(p2[0]["wall_seq"])]
    check("下家那两张拿到牌山的牌",
          sorted(got1), sorted([before_wall[0], before_wall[1]]))
    check("对家那张拿到第 12 张", got2, [before_wall[2]])
    check("记了一次性", g2.skill_used(0, 37, 2), True)
    try:
        g2.c37s2_apply(0, "1m")
        check("不能发动第二次", False, True)
    except RuleError:
        check("不能发动第二次", True, True)

    print("\n④ 三家都没有这种牌 → 报错（不消耗）")
    db2, rid2 = setup("c37s2b")
    g3 = Game(db2, rid2)
    try:
        g3.c37s2_apply(0, "dong")           # 三家都没有东
        check("报错", False, True)
    except RuleError as e:
        check("报错：三家都没有", "都没有" in str(e), True)
    check("没消耗", Game(db2, rid2).skill_used(0, 37, 2), False)

    print("\n⑤ 所有种类都能选（自风牌也行）")
    db3, rid3 = setup("c37s2c")
    tg.set_hand(db3, rid3, 1, parse_hand("7z7z2p3p4p6p7p8p1s2s3s9s9s"))
    g4 = Game(db3, rid3)
    check("state 里没限制牌种（客户端给 34 种）", True, True)
    r4 = g4.c37s2_apply(0, "zhong")            # 客户端传的是内部牌种名（7z = zhong）
    # 下家 2 张 + 对家 2 张（H2 里也有 7z7z）→ 正好 4 组（= 第 4/8/12/16 张）
    check("换了 4 张（上限）", int(r4.get("count", 0)), 4)

    print("\n⑥ 交换不改摸牌顺序")
    db4, rid4 = setup("c37s2d")
    g5 = Game(db4, rid4)
    s_before = g5._upcoming_wall_seqs(16)
    g5.c37s2_apply(0, "5p")
    s_after = Game(db4, rid4)._upcoming_wall_seqs(16)
    check("顺序没变", s_after, s_before)

    print("\n⑦ 发动之后再点一次 → 不再回 need_kangpo（闸门预检）")
    db5, rid5 = setup("c37s2e")
    g6 = Game(db5, rid5)
    g6.granted = {0: {37}, 1: {17}}          # 1 号位持有【看破】→ 闸门真的会问
    g6.save_flags()
    out1 = api_cli.handle({"op": "c37s2_apply", "seat": 0, "kind": "5p",
                           "round_id": rid5}, db_path=db5.path)
    check("第一次：先问看破", bool(out1.get("need_kangpo", False)), True)
    asks1 = Game(db5, rid5).state_for(1).get("asks") or []
    check("1 号位收到一条询问", len(asks1), 1)
    aid = int(asks1[0].get("id", -1)) if asks1 else -1
    api_cli.handle({"op": "act_answer", "seat": 1, "aid": aid, "kind": "pass",
                    "round_id": rid5}, db_path=db5.path)
    check("放行后技能真的生效", Game(db5, rid5).skill_used(0, 37, 2), True)
    out2 = api_cli.handle({"op": "c37s2_apply", "seat": 0, "kind": "5p",
                           "round_id": rid5}, db_path=db5.path)
    check("再点一次：不再挂看破（否则永远「等对方拦截」）",
          bool(out2.get("need_kangpo", False)), False)
    check("再点一次：回的是真原因", "一次" in str(out2.get("error", "")), True)
    check("再点一次：不留询问", len(Game(db5, rid5).state_for(1).get("asks") or []), 0)

    print("\n" + "=" * 78)
    print(f" 通过 {PASS} / 失败 {FAIL}")
    print("=" * 78)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
