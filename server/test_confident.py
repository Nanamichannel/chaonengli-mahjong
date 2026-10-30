# -*- coding: utf-8 -*-
"""Card03 Skill1「自信」自测
跑法： python test_confident.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")

from game import Game  # noqa: E402
from rules import score  # noqa: E402
import skills  # noqa: E402
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


def new_undealt_round(db, seed: int) -> int:
    """开一局但先不配牌（round_phase 还是 deal）。"""
    uids = [db.create_user(f"conf{seed}_{i}") for i in range(4)]
    room = db.create_room(uids[0])
    for u in uids[1:]:
        db.join_room(room["room_code"], u)
    match = db.start_match(room["room_id"], seed=seed)
    return db.start_round(match, "dong", 1, honba=0, dealer_seat=0, seed=seed)


def mark_discarded(db, rid: int, seat: int) -> None:
    """假装这个座位已经打过一张牌 —— 不然第一次自摸会算天和/地和（役满）。"""
    with db.tx():
        db.conn.execute(
            "INSERT INTO round_discards(round_id, seq, seat, wall_seq, tile,"
            " is_tsumogiri, is_riichi_tile, face_down, called)"
            " VALUES(?,?,?,?,?,1,0,0,0)",
            (rid, 500 + seat, seat, 700 + seat, "1m"))


def to_discard(g: Game, seat: int) -> Game:
    g.round_phase = "play"
    g.turn = seat
    g.phase = "discard"
    g.save_flags()
    return g


def main() -> int:
    print("=" * 70)
    print(" 天马麻将 · Card03 Skill1「自信」")
    print("=" * 70)

    # ── 1. 登记 ──────────────────────────────────────────────────
    print("\n① 技能登记")
    check("skills.has(3,1)", skills.has(3, 1))
    check("名字是「自信」", skills.info(3, 1).get("name"), "自信")

    # ── 2. 配牌阶段发动 + 持久化 ────────────────────────────────
    print("\n② 配牌阶段发动（整小局有效）")
    db = tg.fresh_db("conf_deal")
    rid = new_undealt_round(db, seed=71)
    g = Game(db, rid)
    check("开局是配牌阶段", g.round_phase, "deal")
    r = g.arm_skill(0, 3, 1)
    check("配牌阶段能发动", r.get("armed"), True)
    check("返回 kind=confidence", r.get("kind"), "confidence")
    check("本局记住了自信", 0 in g.confident)
    check("state 里 confident=True", g.state_for(0).get("confident"), True)
    check("别的座位看不到我的（False）", g.state_for(1).get("confident"), False)

    g2 = Game(db, rid)                     # 新进程重新读
    check("落库后还在", 0 in g2.confident)
    r2 = g2.arm_skill(0, 3, 1)
    check("再点一次 → already", r2.get("already"), True)
    check("再点一次不会重复生效", len(g2.confident), 1)

    # ── 3. 出了配牌阶段就不能发动 ──────────────────────────────
    print("\n③ 只在配牌阶段")
    db3 = tg.fresh_db("conf_late")
    rid3 = new_undealt_round(db3, seed=72)
    g3 = Game(db3, rid3)
    tg.set_hand(db3, rid3, 0, parse_hand("123m456p789s111z22m"), drawn="2m")
    g3 = Game(db3, rid3)
    to_discard(g3, 0)
    r3 = g3.arm_skill(0, 3, 1)
    check("打牌阶段发动失败", r3.get("armed"), False)
    check("给了原因", "配牌阶段" in str(r3.get("reason", "")))

    # ── 4. 和牌：番数双倍 ───────────────────────────────────────
    print("\n④ 和牌：番数双倍")
    # 对照：同一个牌型，不开自信
    dbc = tg.fresh_db("conf_ctrl")
    ridc = new_undealt_round(dbc, seed=73)
    tg.set_hand(dbc, ridc, 0, parse_hand("123m456m789m123p55z"), drawn="bai")
    mark_discarded(dbc, ridc, 0)
    gc = to_discard(Game(dbc, ridc), 0)
    gc.act(0, "tsumo")
    resc = gc.result or {}
    base_han = int(resc.get("han", 0))
    base_fu = int(resc.get("fu", 0))
    base_total = int((resc.get("pays") or {}).get("total", 0))
    check("对照：正常和牌", resc.get("result"), "tsumo")
    check("对照：不是役满", int(resc.get("yakuman", 0)), 0)

    db4 = tg.fresh_db("conf_win")
    rid4 = new_undealt_round(db4, seed=74)
    g4 = Game(db4, rid4)
    check("配牌阶段发动", g4.arm_skill(0, 3, 1).get("armed"), True)
    tg.set_hand(db4, rid4, 0, parse_hand("123m456m789m123p55z"), drawn="bai")
    mark_discarded(db4, rid4, 0)
    g4 = Game(db4, rid4)
    to_discard(g4, 0)
    g4.act(0, "tsumo")
    res4 = g4.result or {}
    check("和牌了", res4.get("result"), "tsumo")
    check("番数双倍", int(res4.get("han", 0)), base_han * 2)
    names4 = [y["name"] for y in res4.get("yaku", [])]
    check("播报里有「自信（番数双倍）」", "自信（番数双倍）" in names4)
    want4 = score.payments(base_han * 2, base_fu, is_dealer=True,
                           tsumo=True).get("total")
    check("点数按双倍番重算", int((res4.get("pays") or {}).get("total", 0)), want4)
    check("比不开技能拿得多", int((res4.get("pays") or {}).get("total", 0)) > base_total)
    check("收付合计为 0", sum((res4.get("deltas") or {}).values()), 0)

    # ── 5. 放铳：失点双倍 ───────────────────────────────────────
    print("\n⑤ 没和牌：放铳失点双倍")
    # 对照：同样放铳，不开自信
    dbc5 = tg.fresh_db("conf_ron_ctrl")
    ridc5 = new_undealt_round(dbc5, seed=75)
    tg.set_hand(dbc5, ridc5, 0, parse_hand("123m456m789m123p55z") + ["3p"], drawn="3p")
    tg.set_hand(dbc5, ridc5, 1, parse_hand("123m456m789m12p55z"))
    gc5 = to_discard(Game(dbc5, ridc5), 0)
    gc5.act(0, "discard", tile="3p")
    gc5.act(1, "ron")
    rc5 = gc5.result or {}
    base5_total = int((rc5.get("pays") or {}).get("total", 0))
    base5_han = int(rc5.get("han", 0))

    db5 = tg.fresh_db("conf_ron")
    rid5 = new_undealt_round(db5, seed=76)
    g5 = Game(db5, rid5)
    check("配牌阶段发动", g5.arm_skill(0, 3, 1).get("armed"), True)
    tg.set_hand(db5, rid5, 0, parse_hand("123m456m789m123p55z") + ["3p"], drawn="3p")
    tg.set_hand(db5, rid5, 1, parse_hand("123m456m789m12p55z"))
    g5 = Game(db5, rid5)
    to_discard(g5, 0)
    g5.act(0, "discard", tile="3p")
    check("开了鸣牌窗口", g5.phase, "claim")
    g5.act(1, "ron")
    res5 = g5.result or {}
    check("1 号位荣和", res5.get("winner"), 1)
    check("和牌的人不是我，番数没翻倍", int(res5.get("han", 0)), base5_han)
    deltas5 = res5.get("deltas") or {}
    check("我付了双倍", deltas5.get(0), -2 * base5_total)
    check("我多付的那份进了赢家的腰包", deltas5.get(1), 2 * base5_total)
    check("收付合计为 0", sum(deltas5.values()), 0)

    # ── 6. 别人自摸：只有我的那一份翻倍 ─────────────────────────
    print("\n⑥ 别人自摸：我的失点双倍，其他家不变")
    db6 = tg.fresh_db("conf_tsumo")
    rid6 = new_undealt_round(db6, seed=77)
    g6 = Game(db6, rid6)
    check("配牌阶段发动", g6.arm_skill(0, 3, 1).get("armed"), True)
    tg.set_hand(db6, rid6, 1, parse_hand("123m456m789m123p55z"), drawn="bai")
    mark_discarded(db6, rid6, 1)
    g6 = Game(db6, rid6)
    to_discard(g6, 1)
    g6.act(1, "tsumo")
    res6 = g6.result or {}
    check("1 号位自摸", res6.get("winner"), 1)
    check("不是役满", int(res6.get("yakuman", 0)), 0)
    pays6 = res6.get("pays") or {}
    deltas6 = res6.get("deltas") or {}
    check("我（亲家）付双倍", deltas6.get(0), -2 * int(pays6.get("from_dealer", 0)))
    check("子家付原价", deltas6.get(2), -int(pays6.get("from_other", 0)))
    check("收付合计为 0", sum(deltas6.values()), 0)

    # ── 7. 役满不受影响 ────────────────────────────────────────
    print("\n⑦ 役满：没有番数可翻，保持原样")
    db7 = tg.fresh_db("conf_yakuman")
    rid7 = new_undealt_round(db7, seed=78)
    g7 = Game(db7, rid7)
    g7.arm_skill(0, 3, 1)
    tg.set_hand(db7, rid7, 0, parse_hand("111m222m333m444m55m"), drawn="5m")
    mark_discarded(db7, rid7, 0)
    g7 = Game(db7, rid7)
    to_discard(g7, 0)
    g7.act(0, "tsumo")
    res7 = g7.result or {}
    check("是役满", int(res7.get("yakuman", 0)) > 0)
    check("没有加「自信」番", "自信（番数双倍）" not in
          [y["name"] for y in res7.get("yaku", [])])

    # ── 8. 荣和也翻倍 ─────────────────────────────────────────
    print("\n⑧ 我荣和：番数同样双倍")
    dbc8 = tg.fresh_db("conf_ron_win_ctrl")
    ridc8 = new_undealt_round(dbc8, seed=79)
    tg.set_hand(dbc8, ridc8, 0, parse_hand("123m456m789m12p55z"))
    tg.set_hand(dbc8, ridc8, 1, parse_hand("123m456m789m123p55z") + ["3p"], drawn="3p")
    gc8 = to_discard(Game(dbc8, ridc8), 1)
    gc8.act(1, "discard", tile="3p")
    gc8.act(0, "ron")
    rc8 = gc8.result or {}
    base8_han = int(rc8.get("han", 0))
    base8_fu = int(rc8.get("fu", 0))
    check("对照：荣和", rc8.get("winner"), 0)

    db8 = tg.fresh_db("conf_ron_win")
    rid8 = new_undealt_round(db8, seed=80)
    g8 = Game(db8, rid8)
    check("配牌阶段发动", g8.arm_skill(0, 3, 1).get("armed"), True)
    tg.set_hand(db8, rid8, 0, parse_hand("123m456m789m12p55z"))
    tg.set_hand(db8, rid8, 1, parse_hand("123m456m789m123p55z") + ["3p"], drawn="3p")
    g8 = Game(db8, rid8)
    to_discard(g8, 1)
    g8.act(1, "discard", tile="3p")
    g8.act(0, "ron")
    res8 = g8.result or {}
    check("我荣和", res8.get("winner"), 0)
    check("番数双倍", int(res8.get("han", 0)), base8_han * 2)
    want8 = score.payments(base8_han * 2, base8_fu, is_dealer=True,
                           tsumo=False).get("total")
    check("点数按双倍番重算", int((res8.get("pays") or {}).get("total", 0)), want8)
    check("收付合计为 0", sum((res8.get("deltas") or {}).values()), 0)

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
