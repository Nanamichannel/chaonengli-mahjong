# -*- coding: utf-8 -*-
"""Card11 Skill1「魔术」自测。

· 摸牌后、打牌前发动一次：一张手牌 ↔ 一张已翻开的宝牌指示牌
· 换完指示牌 → 宝牌信息（round_dora 的 dora 列）必须重新算
· 交换后直接和牌：不计边/坎/吊 2 符，并且一律按自摸结算
· 一次性；打出牌之后「交换后直接和牌」窗口关闭

用法： python test_card11.py
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")

from game import Game, RuleError  # noqa: E402
from tiles import dora_from_indicator, parse_hand  # noqa: E402
from rules import wallmodel  # noqa: E402
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
    uids = [db.create_user(f"mg{seed}_{i}") for i in range(4)]
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
                      for o in orders],
            "phase": "playing"}
    with db.tx():
        db.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('lobby_state', ?)",
                        (json.dumps(body, ensure_ascii=False),))
    return rid


# 0 号位带 11 号卡，别人都是普通牌
ORD_11 = [[11, 2, 3, 4, 5], [1, 2, 3, 4, 5], [1, 2, 3, 4, 5], [1, 2, 3, 4, 5]]

# 手牌：123m 456m 789m 4s6s 11p —— 等 5s（嵌张，2 符）
H13 = parse_hand("123m456m789m") + ["4s", "6s", "1p", "1p"]


def deal_dora(g: Game, rid: int, ind: str = "1m") -> None:
    """夹具：把王牌第一张指示牌改成 ind 并「翻开」（state/flags 一致）。"""
    n = g.wall_first_stack()
    no_d, no_u = wallmodel.dora_tile_nos(n, 0)
    ura = g._tile_of_no(no_u)
    with g.db.tx():
        g.db.conn.execute("DELETE FROM round_dora WHERE round_id=?", (rid,))
        g.db.conn.execute("UPDATE round_wall SET tile=? WHERE round_id=? AND seq=?",
                          (ind, rid, int(wallmodel.seq_of_tile(no_d))))
    g.db.add_dora(rid, "dora", 0, ind, dora_from_indicator(ind))
    g.db.add_dora(rid, "ura", 0, ura, dora_from_indicator(ura))
    g.dora_revealed = 1
    g.save_flags()


def to_discard(g: Game, seat: int) -> Game:
    g.round_phase = "play"
    g.turn = seat
    g.phase = "discard"
    g.save_flags()
    return g


def wait_fu(items) -> list[str]:
    return [n for n, _ in (items or []) if "听牌形" in n]


def add_discard(db, rid: int, seat: int, seq: int, tile: str, face_down: int = 0) -> None:
    with db.tx():
        db.conn.execute(
            "INSERT INTO round_discards(round_id, seat, seq, wall_seq, tile, called,"
            " is_riichi_tile, face_down) VALUES(?,?,?,?,?,0,0,?)",
            (rid, seat, seq, 500000 + seq, tile, face_down))


def main() -> int:
    print("=" * 70)
    print(" 天马麻将 · Card11 Skill1「魔术」")
    print("=" * 70)

    # ── 1 登记 ────────────────────────────────────────────
    print("\n◆ 技能登记")
    check("skills.has(11,1)", skills.has(11, 1))
    check("名字是「魔术」", skills.info(11, 1).get("name"), "魔术")
    check("时机是摸牌后", skills.timing(11, 1), "draw")

    # ── 2 发动条件 ────────────────────────────────────────
    print("\n◆ 发动条件：摸牌后、打牌前、还有指示牌")
    db = tg.fresh_db("mg_gate")
    rid = new_round(db, 971, ORD_11)
    tg.set_hand(db, rid, 0, H13)                      # 13 张，没摸牌
    g = to_discard(Game(db, rid), 0)
    check("没摸牌 → 不能发动", g.card11_can(0), False)
    tg.set_hand(db, rid, 0, H13 + ["9s"], drawn="9s")
    g = Game(db, rid)
    check("配牌后第一张指示牌已经翻开", g.dora_revealed >= 1, True)
    deal_dora(g, rid)
    g = Game(db, rid)
    check("摸牌 + 有指示牌 → 可以发动", g.card11_can(0), True)
    check("state 里 card11_can=True", g.state_for(0).get("card11_can"), True)
    check("1 号位没有魔术卡", g.owns_card11(1), False)

    # ── 3 交换手牌 ↔ 指示牌 ──────────────────────────────
    print("\n◆ 换：手牌一张 ↔ 宝牌指示牌，宝牌信息跟着变")
    ind = g.revealed_dora("dora")[0]
    print(f"       交换前指示牌 = {ind}（宝牌 {dora_from_indicator(ind)}）")
    r = g.card11_swap(0, "9s", 0)
    check("换到手的是原指示牌", r.get("got"), ind)
    check("打出去的是 9s", r.get("hand"), "9s")
    g2 = Game(db, rid)
    hand = list(g2.hand(0))
    check("手里有了原指示牌", ind in hand, True)
    check("手里没有 9s 了", "9s" in hand, False)
    check("指示牌变成 9s", g2.revealed_dora("dora")[0], "9s")
    row = db._row("SELECT indicator, dora FROM round_dora WHERE round_id=? "
                  "AND kind='dora' AND idx=0", (rid,))
    check("宝牌重算 = 9s 的宝牌", row["dora"], dora_from_indicator("9s"))
    check("用了就记一次", g2.skill_used(0, 11, 1), True)
    check("state: card11_win=True（这一手算交换后直接和牌）",
          g2.state_for(0).get("card11_win"), True)
    check("打出去之后窗口关闭", g2.state_for(1).get("card11_win"), False)
    try:
        g2.card11_swap(0, "1p", 0)
        check("一轮只能一次", False)
    except RuleError as e:
        check("一轮只能一次", "一次" in str(e))

    # ── 4 拒绝条件 ────────────────────────────────────────
    print("\n◆ 拒绝条件")
    db2 = tg.fresh_db("mg_reject")
    rid2 = new_round(db2, 972, ORD_11)
    tg.set_hand(db2, rid2, 0, H13 + ["9s"], drawn="9s")
    g3 = to_discard(Game(db2, rid2), 0)
    deal_dora(g3, rid2)
    g3 = Game(db2, rid2)
    try:
        g3.card11_swap(0, "fa", 0)                   # 手里没有发财
        check("手里没这张 → 拒绝", False)
    except RuleError as e:
        check("手里没这张 → 拒绝", "没有" in str(e))
    try:
        Game(db2, rid2).card11_swap(0, "9s", 9)      # 没有第 10 张指示牌
        check("指示牌下标越界 → 拒绝", False)
    except RuleError as e:
        check("指示牌下标越界 → 拒绝", "翻开" in str(e))
    try:
        g3.card11_swap(1, "9s", 0)
        check("没这张卡的人不能发动", False)
    except RuleError as e:
        check("没这张卡的人不能发动", "魔术" in str(e))

    # ── 5 交换后直接和牌：不算边坎吊、按自摸 ─────────────
    print("\n◆ 交换后直接和牌：不计听牌形符 + 视为自摸")
    db3 = tg.fresh_db("mg_win")
    rid3 = new_round(db3, 973, ORD_11)
    tg.set_hand(db3, rid3, 0, H13)                   # 13 张，等 5s
    g4 = to_discard(Game(db3, rid3), 0)
    plain = g4._judge_win(0, "5s", tsumo=False)               # 普通荣和
    magic = g4._judge_win(0, "5s", tsumo=False, as_tsumo=True)  # 魔术：视为自摸
    print("       普通荣和：", plain["fu_items"])
    print("       魔术和牌：", magic["fu_items"])
    check("普通荣和有「听牌形（嵌张）」", wait_fu(plain["fu_items"]),
          ["听牌形（嵌张）"])
    check("魔术和牌没有听牌形符", wait_fu(magic["fu_items"]), [])
    check("魔术和牌有自摸符",
          any(n == "自摸" for n, _ in magic["fu_items"]), True)
    check("魔术和牌算门前清自摸和",
          any(y["name"] == "门前清自摸和" for y in magic["yaku"]), True)
    check("魔术和牌按自摸摊（pays 有 each）", "each" in magic["pays"], True)
    check("普通荣和没有自摸役",
          any(y["name"] == "门前清自摸和" for y in plain["yaku"]), False)
    check("魔术和牌总值是自摸总额", magic["pays"]["total"], magic["pays"]["each"] * 3)
    print("       魔术和牌 %d 番 %d 符 / 总点 %s"
          % (magic["han"], magic["fu"], magic["pays"].get("total")))

    # 自摸也一样免符（自摸要 14 张，单独来一手）
    tg.set_hand(db3, rid3, 0, H13 + ["5s"], drawn="5s")
    with db3.tx():                                    # 已经有打过牌 → 不算天和
        db3.conn.execute(
            "INSERT INTO round_discards(round_id, seat, seq, wall_seq, tile) "
            "VALUES(?,?,?,?,?)", (rid3, 0, 9901, 990001, "9p"))
    g4b = to_discard(Game(db3, rid3), 0)
    tsu = g4b._judge_win(0, "5s", tsumo=True, as_tsumo=True)
    check("自摸 + 魔术也不计听牌形符", wait_fu(tsu["fu_items"]), [])
    check("自摸 + 魔术照常算自摸符",
          any(n == "自摸" for n, _ in tsu["fu_items"]), True)

    # ── 6 换完指示牌 → 里宝那条也要跟着变 ────────────────
    print("\n◆ 王牌上的牌换了 → 指示牌/里宝指示牌都按牌墩现状重算")
    db4 = tg.fresh_db("mg_sync")
    rid4 = new_round(db4, 974, ORD_11)
    tg.set_hand(db4, rid4, 0, H13 + ["9s"], drawn="9s")
    g5 = to_discard(Game(db4, rid4), 0)
    deal_dora(g5, rid4)
    g5 = Game(db4, rid4)
    n = g5.wall_first_stack()
    no_d, no_u = wallmodel.dora_tile_nos(n, 0)
    seq_u = int(wallmodel.seq_of_tile(no_u))
    old_ura = g5._tile_of_no(no_u)
    with db4.tx():                                    # 手动把里宝那张换成 1m
        db4.conn.execute("UPDATE round_wall SET tile='1m' WHERE round_id=? AND seq=?",
                         (rid4, seq_u))
    changed = g5._c11_sync_dora({seq_u})
    check("里宝那条被重算", [c["kind"] for c in changed], ["ura"])
    ura_now = db4._row("SELECT indicator, dora FROM round_dora WHERE round_id=? "
                       "AND kind='ura' AND idx=0", (rid4,))
    check("里宝指示牌变成 1m", ura_now["indicator"], "1m")
    check("里宝变成 2m", ura_now["dora"], dora_from_indicator("1m"))
    check("原来是别的牌", old_ura != "1m", True)

    # ── 7 打牌后窗口关闭 ──────────────────────────────────
    print("\n◆ 打出牌 → 不再是「交换后直接和牌」")
    db5 = tg.fresh_db("mg_clear")
    rid5 = new_round(db5, 975, ORD_11)
    tg.set_hand(db5, rid5, 0, H13 + ["9s"], drawn="9s")
    g6 = to_discard(Game(db5, rid5), 0)
    deal_dora(g6, rid5)
    g6 = Game(db5, rid5)
    g6.card11_swap(0, "9s", 0)
    check("换完 c11_win 有值", g6.c11_win, 0)
    g6.act(0, "discard", tile="1p")
    g7 = Game(db5, rid5)
    check("打牌后 c11_win 清掉", g7.c11_win, None)
    res = g7._judge_win(1, "5s", tsumo=False, as_tsumo=(g7.c11_win == 1))
    check("别人不受影响（正常荣和）", "each" in (res or {}).get("pays", {}), False)


    # ── 8 快手（Card11 S2）────────────────────────────────
    print("\n◆ 快手（Card11 S2）：摸的牌暗置换别家牌河第 1 / 6 列")
    check("skills.has(11,2)", skills.has(11, 2))
    check("名字是「快手」", skills.info(11, 2).get("name"), "快手")

    db6 = tg.fresh_db("mg_fast")
    rid6 = new_round(db6, 976, ORD_11)
    tg.set_hand(db6, rid6, 0, H13 + ["9s"], drawn="9s")
    g8 = to_discard(Game(db6, rid6), 0)
    check("牌河空 → 不能发动", g8.card11s2_can(0), False)
    for k, t in enumerate(["1p", "2p", "3p", "4p", "5p", "6p", "7p"]):
        add_discard(db6, rid6, 1, 101 + k, t)          # 下家 7 张：第 1/6/7 张可换
    add_discard(db6, rid6, 1, 190, "9p", face_down=1)  # 暗置的，不列出来
    g8 = Game(db6, rid6)
    tg_seq = sorted(g8.state_for(0)["card11s2_seqs"])
    check("只有第 1 列 / 第 6 列 / 下一排第 1 张", tg_seq, [101, 106, 107])
    check("state: card11s2_can=True", g8.state_for(0).get("card11s2_can"), True)

    try:
        g8.card11s2_swap(0, 102)
        check("第 2 列 → 拒绝", False)
    except RuleError as e:
        check("第 2 列 → 拒绝", "第一列" in str(e))

    r2 = g8.card11s2_swap(0, 101)
    check("换到的是牌河那张", r2.get("got"), "1p")
    check("换出去的是刚摸的 9s", r2.get("gave"), "9s")
    row = db6._row("SELECT tile, face_down FROM round_discards WHERE round_id=? AND seq=?",
                   (rid6, 101))
    check("牌河那张变成 9s（暗置）", (row["tile"], int(row["face_down"])), ("9s", 1))
    g9 = Game(db6, rid6)
    check("我手里有了 1p", "1p" in list(g9.hand(0)), True)
    check("我手里没 9s 了", "9s" in list(g9.hand(0)), False)
    check("用了就记一次", g9.skill_used(0, 11, 2), True)
    try:
        g9.card11s2_swap(0, 106)
        check("一轮只能一次", False)
    except RuleError as e:
        check("一轮只能一次", "一次" in str(e))

    # 按「哪家 + 第几张」定位（客户端走这条路，不依赖全局 seq）
    db8 = tg.fresh_db("mg_fast3")
    rid8 = new_round(db8, 978, ORD_11)
    tg.set_hand(db8, rid8, 0, H13 + ["9s"], drawn="9s")
    for k, t in enumerate(["1p", "2p", "3p", "4p", "5p", "6p"]):
        add_discard(db8, rid8, 2, 301 + k, t)
    g11 = to_discard(Game(db8, rid8), 0)
    try:
        g11.card11s2_swap(0, -1, 2, 1)                 # 对家第 2 张（第 2 列）
        check("按位置：第 2 列 → 拒绝", False)
    except RuleError as e:
        check("按位置：第 2 列 → 拒绝", "第一列" in str(e))
    r3 = g11.card11s2_swap(0, -1, 2, 5)                # 对家第 6 张（第 6 列）
    check("按位置：第 6 列可以换", r3.get("got"), "6p")
    row3 = db8._row("SELECT tile, face_down FROM round_discards WHERE round_id=? AND seq=?",
                    (rid8, 306))
    check("对家那张变 9s 且暗置", (row3["tile"], int(row3["face_down"])), ("9s", 1))

    # 自己牌河 / 暗置目标都不许
    db7 = tg.fresh_db("mg_fast2")
    rid7 = new_round(db7, 977, ORD_11)
    tg.set_hand(db7, rid7, 0, H13 + ["9s"], drawn="9s")
    add_discard(db7, rid7, 0, 201, "3p")               # 我自己牌河第 1 张
    add_discard(db7, rid7, 1, 202, "3p", face_down=1)  # 别家暗置
    g10 = to_discard(Game(db7, rid7), 0)
    check("只剩暗置的 → 不能发动", g10.card11s2_can(0), False)
    try:
        g10.card11s2_swap(0, 201)
        check("自己牌河不能换", False)
    except RuleError as e:
        check("自己牌河不能换", "第一列" in str(e))

    print("\n" + "=" * 70)
    print(f" 通过 {PASS} 项，失败 {FAIL} 项")
    print("=" * 70)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
