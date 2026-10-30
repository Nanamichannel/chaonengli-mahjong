# -*- coding: utf-8 -*-
"""Card34 S2【海底】自测。

跑法：cd N:\\apps\\tianma\\server; python test_card34s2.py
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
import skills                                        # noqa: E402
import test_card30 as t30                            # noqa: E402
import test_game as tg                               # noqa: E402
from tiles import counts_of, parse_hand                  # noqa: E402
from rules import agari                              # noqa: E402

PASS = FAIL = 0
# 13 张 + 刚摸的 3s（听 白，见下）
H0 = "123m456m789m234p5z3s"
H1 = "1p1p2p3p4p5p6p7p8p9s9s9s9s"
H2 = "1m4m7m2p5p8p2s5s8s2z3z4z6z"
H3 = "3m6m9m3p6p9p3s6s9s1z2z3z5z"


def check(name, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  got {got!r} want {want!r}")


def setup(tag, card=34, live=12):
    db, rid = t30.setup(tag, card=card)
    for s, h in enumerate((H0, H1, H2, H3)):
        tg.set_hand(db, rid, s, parse_hand(h), drawn="3s" if s == 0 else None)
    with db.tx():
        db.conn.execute("DELETE FROM round_dora WHERE round_id=?", (rid,))
        db.conn.execute("DELETE FROM round_discards WHERE round_id=?", (rid,))
        db.conn.execute("UPDATE rounds SET live_left=? WHERE round_id=?", (int(live), rid))
    g = Game(db, rid)
    g.round_phase = "play"
    g.phase = "discard"
    g.turn = 0
    g.deal_wait = set()
    g.deal_used = set()
    g.save_flags()
    return db, rid


def force_wall_tile(db, rid, seat, tile):
    """把「接下来第一张活牌」改成指定牌，返回它的 wall_seq。"""
    g = Game(db, rid)
    seqs = g._upcoming_wall_seqs(1)
    assert seqs, "牌山空了"
    with db.tx():
        db.conn.execute("UPDATE round_wall SET tile=? WHERE round_id=? AND seq=?",
                        (tile, rid, int(seqs[0])))
    return int(seqs[0])


def main() -> int:
    print("=" * 78)
    print(" Card34 S2【海底】")
    print("=" * 78)

    print("\n① 注册 / 时机")
    check("名字", skills.info(34, 2).get("name"), "海底")
    check("时机 = 切牌", skills.timing(34, 2), "discard")

    print("\n② wall_find：活牌 → 王牌 → 找不到")
    db, rid = setup("c34s2a")
    seq_live = force_wall_tile(db, rid, 0, "9p")
    g = Game(db, rid)
    hit = g.wall_find({"9p"})
    check("活牌里找到 9p", (int(hit[0]) if hit else -1), seq_live)
    # 王牌：库里 136 张全是 zone='live'，王牌按牌号（最后 7 墩）算
    import rules.wallmodel as wm
    g = Game(db, rid)
    dead_no = wm.tile_nos_of_stack(wm.dead_stack_nos(g.wall_first_stack())[0])[0]
    dead_seq = int(wm.seq_of_tile(dead_no))
    with db.tx():
        db.conn.execute("UPDATE round_wall SET tile=? WHERE round_id=? AND seq=?",
                        ("1z", rid, dead_seq))
    hit2 = Game(db, rid).wall_find({"1z"})
    check("王牌里也能找到 1z", (int(hit2[0]) if hit2 else -1), dead_seq)
    check("空集合 → None", Game(db, rid).wall_find(set()), None)
    check("_c27_wall_win 也走同一套", Game(db, rid)._c27_wall_win(0, {"9p"}), "9p")

    print("\n③ 条件：剩余 12 张 + 听牌 + 牌山有和牌张")
    db2, rid2 = setup("c34s2b", live=13)
    force_wall_tile(db2, rid2, 0, "bai")
    check("剩 13 张 → 不触发", Game(db2, rid2).c34s2_try(0), False)

    db3, rid3 = setup("c34s2c", live=12)
    force_wall_tile(db3, rid3, 0, "bai")
    check("剩 12 张 + 听白 + 牌山有白 → 触发", Game(db3, rid3).c34s2_try(0), True)

    db4, rid4 = setup("c34s2d", live=12)
    # 把牌山里的白全部改掉 → 听牌但牌山没有
    with db4.tx():
        db4.conn.execute("UPDATE round_wall SET tile='2m' WHERE round_id=? AND tile='bai'", (rid4,))
    g4 = Game(db4, rid4)
    check("听牌但牌山里没有 → 不触发", g4.c34s2_try(0), False)

    db5, rid5 = setup("c34s2e", live=12)
    tg.set_hand(db5, rid5, 0, parse_hand("123m456m789m2p4p6s7s"), drawn="7s")   # 不听
    force_wall_tile(db5, rid5, 0, "bai")
    check("不听牌 → 不触发", Game(db5, rid5).c34s2_try(0), False)

    print("\n③b 鸣牌后的打牌（没有刚摸到的牌）也能触发")
    db6, rid6 = setup("c34s2i", live=12)
    # 碰 1m + 手牌 10 张（无 is_drawn），听 白
    tg.set_hand(db6, rid6, 0, parse_hand("2m3m4m5m6m7m2p3p4p5z"))
    with db6.tx():
        db6.conn.execute(
            "INSERT INTO round_melds(round_id,meld_id,seat,kind,called_tile,from_seat,"
            "tiles_json,rot_index,seqs_json) VALUES(?,0,0,'pon','1m',3,?,0,'[]')",
            (rid6, '["1m","1m","1m"]'))
    force_wall_tile(db6, rid6, 0, "bai")
    gg = Game(db6, rid6)
    check("鸣牌后没有 drawn", gg.drawn_tile(0), None)
    check("鸣牌后也能触发", gg.c34s2_try(0), True)

    print("\n④ 触发后：次数 +1 再自动发动（重置 3 巡）")
    g6 = Game(db3, rid3)
    g6.c34s2_try(0)
    g7 = Game(db3, rid3)
    check("c34s2_fired", g7.c34s2_fired, True)
    check("记录铳张牌面", g7.c34s2_tile, "bai")
    check("厄运自动发动", int(g7.c34_by), 0)
    check("重置成 3 巡", int(g7.c34_left), 3)
    check("其他三家静默", [g7.c34_muted(1), g7.c34_muted(2), g7.c34_muted(3)],
          [True, True, True])
    check("次数：1 起步 → +1 → 自动发动 -1 → 还是 1", g7.c34_charges_of(0), 1)
    check("不能触发第二次", Game(db3, rid3).c34s2_try(0), False)

    print("\n⑤ 厄运期间：发动者自己的和牌无视拦截链")
    g8 = Game(db3, rid3)
    g8.no_win.add(0)                      # 看破代价 / 封堵：本来不能和
    check("厄运期间无视 no_win", g8._win_gate(0, "bai", False), True)
    g8.c28s1_on = {0}
    check("厄运期间无视满贯缚", g8._c28s1_allows(0, "bai", False), True)

    print("\n⑥ 海底自摸：换进锁定的铳张并结算")
    db9, rid9 = setup("c34s2f", live=12)
    force_wall_tile(db9, rid9, 0, "bai")
    g9 = Game(db9, rid9)
    g9.c34s2_try(0)
    g9 = Game(db9, rid9)
    for _ in range(3):
        g9._c34_tick(0)
    hand_seq = g9.db._one(
        "SELECT wall_seq FROM round_hands WHERE round_id=? AND seat=0 AND is_drawn=1", (rid9,))
    ev = g9._c34s2_last_tsumo(0, {"wall_seq": int(hand_seq)})
    check("出了海底事件", str((ev or {}).get("event", "")), "c34_last")
    g10 = Game(db9, rid9)
    check("只换牌、不自动结算", bool(g10.result), False)
    check("手里换进了白", "bai" in g10.hand(0), True)
    check("s2 状态清掉", int(g10.c34s2_on), -1)
    check("legal 里有自摸按钮",
          "tsumo" in [a.get("action") for a in g10.legal_actions(0)], True)
    g10.act(0, "tsumo")
    g10b = Game(db9, rid9)
    check("点了自摸才结算", bool(g10b.result), True)
    if g10b.result:
        check("是自摸", g10b.result.get("result"), "tsumo")

    print("\n⑥a 真实摸牌的 info 键是 seq（不是 wall_seq）也必须能自摸")
    db26, rid26 = setup("c34s2o", live=12)
    force_wall_tile(db26, rid26, 0, "bai")
    g26 = Game(db26, rid26)
    g26.c34s2_try(0)
    g26 = Game(db26, rid26)
    for _ in range(3):
        g26._c34_tick(0)
    hs26 = g26.db._one("SELECT wall_seq FROM round_hands WHERE round_id=? AND seat=0 "
                       "AND is_drawn=1", (rid26,))
    ev26 = g26._c34s2_last_tsumo(0, {"tile": "x", "seq": int(hs26)})
    check("info 给 seq 也能海底换牌", str((ev26 or {}).get("event", "")), "c34_last")
    check("换完还没结算", bool(Game(db26, rid26).result), False)
    g26.act(0, "tsumo")
    check("点自摸后结算落地", bool(Game(db26, rid26).result), True)

    print("\n⑥b 摸进来才听牌（hand13 不听）也要能触发")
    db20, rid20 = setup("c34s2j", live=12)
    # 14 张：摸进 5s 那张放最后（set_hand 只认最后一张是刚摸的）；
    # 去掉刚摸的 5s 后是 123m456m789m 23p 5s9s → 不听；打掉 9s → 听 1p/4p
    tg.set_hand(db20, rid20, 0, parse_hand("123m456m789m2p3p9s5s5s"), drawn="5s")
    force_wall_tile(db20, rid20, 0, "4p")
    g20 = Game(db20, rid20)
    check("hand13 确实不听（旧口径会判不听）",
          agari.is_tenpai(counts_of(g20.hand13(0)), g20.melds(0)), False)
    check("14 张口径听 1p/4p", sorted(g20._c34s2_waits(0)), ["1p", "4p"])
    check("摸进来才听 → 能触发", g20.c34s2_try(0), True)

    db21, rid21 = setup("c34s2k", live=13)
    tg.set_hand(db21, rid21, 0, parse_hand("123m456m789m2p3p9s5s5s"), drawn="5s")
    force_wall_tile(db21, rid21, 0, "4p")
    pr = Game(db21, rid21).c34s2_probe(0)
    check("probe：剩 13 张 → 说明张数不对",
          str(pr.get("why", "")).startswith("现在剩 13 张"), True)
    check("probe：剩 13 张 → 不发动", pr.get("would_fire"), False)
    check("probe：能列出听牌", pr.get("waits"), ["1p", "4p"])

    db22, rid22 = setup("c34s2l", live=12)
    tg.set_hand(db22, rid22, 0, parse_hand("123m456m789m2p3p9s5s5s"), drawn="5s")
    force_wall_tile(db22, rid22, 0, "4p")
    pr2 = Game(db22, rid22).c34s2_probe(0)
    check("probe：条件满足", pr2.get("would_fire"), True)
    check("probe：锁定最近的 4p", str(pr2.get("in_wall", "")), "4p")

    db23, rid23 = setup("c34s2m", live=12)
    tg.set_hand(db23, rid23, 0, parse_hand("123m456m789m2p4p6s7s"), drawn="7s")
    force_wall_tile(db23, rid23, 0, "bai")
    pr3 = Game(db23, rid23).c34s2_probe(0)
    check("probe：不听 → 说明还没听牌", str(pr3.get("why", "")).startswith("还没听牌"), True)

    print("\n⑥c 立直家只能摸切：手切出来的听牌形状不算")
    db24, rid24 = setup("c34s2n", live=12)
    tg.set_hand(db24, rid24, 0, parse_hand("123m456m789m2p3p9s5s5s"), drawn="5s")
    force_wall_tile(db24, rid24, 0, "4p")
    with db24.tx():
        db24.conn.execute("INSERT INTO round_riichi(round_id, seat, declared_seq, ippatsu) "
                          "VALUES(?,0,-1,0)", (rid24,))
    g24 = Game(db24, rid24)
    check("立直：摸切 5s 后不听 → 不算听牌", sorted(g24._c34s2_waits(0)), [])
    check("立直：不触发", g24.c34s2_try(0), False)

    print("\n⑦ 海底自摸仍会被拦截链拦（满贯 / 浓雾）")
    db11, rid11 = setup("c34s2g", live=12)
    # 碰「中」（役牌 1 番）+ 234m/567m/234p + 白雀头 → 1 番 30 符，打点不到满贯
    tg.set_hand(db11, rid11, 0, parse_hand("2m3m4m5m6m7m2p3p4p5z5z"), drawn="bai")
    with db11.tx():
        db11.conn.execute(
            "INSERT INTO round_melds(round_id,meld_id,seat,kind,called_tile,from_seat,"
            "tiles_json,rot_index,seqs_json) VALUES(?,0,0,'pon','zhong',1,?,0,'[]')",
            (rid11, '["zhong","zhong","zhong"]'))
    force_wall_tile(db11, rid11, 0, "bai")
    g11 = Game(db11, rid11)
    g11.c34s2_try(0)
    g11 = Game(db11, rid11)
    for _ in range(3):                    # 真实时序：摸到最后一张时厄运已经结束
        g11._c34_tick(0)
    g11.c28s1_on = {0}                    # 满贯：这手只有 1 番 → 不到满贯
    g11.save_flags()
    hs = g11.db._one("SELECT wall_seq FROM round_hands WHERE round_id=? AND seat=0 AND is_drawn=1",
                     (rid11,))
    _res = g11._judge_win(0, "bai", tsumo=True)
    _pv = (g11.settle_preview(0, None, "tsumo", g11._res_clone(_res), dry_run=True)
           if _res else None)
    check("这手确实不到满贯", bool(g11._c28s1_blocks(_pv)), True)
    ev2 = g11._c34s2_last_tsumo(0, {"wall_seq": int(hs)})
    check("换牌照做（拦住的是按钮，不是换牌）",
          str((ev2 or {}).get("event", "")), "c34_last")
    check("满贯 → 自摸按钮不出现",
          "tsumo" in [a.get("action") for a in Game(db11, rid11).legal_actions(0)], False)
    check("没有结算", bool(Game(db11, rid11).result), False)

    db12, rid12 = setup("c34s2h", live=12)
    force_wall_tile(db12, rid12, 0, "bai")
    g12 = Game(db12, rid12)
    g12.c34s2_try(0)
    g12 = Game(db12, rid12)
    for _ in range(3):
        g12._c34_tick(0)                  # 厄运走完（海底那一刻）
    g12.nongwu = {"seat": 1, "left": 4}   # 浓雾：4 巡内别家不能自摸
    g12.save_flags()
    hs2 = g12.db._one("SELECT wall_seq FROM round_hands WHERE round_id=? AND seat=0 AND is_drawn=1",
                      (rid12,))
    ev3 = g12._c34s2_last_tsumo(0, {"wall_seq": int(hs2)})
    check("浓雾 → 自摸按钮不出现",
          "tsumo" in [a.get("action") for a in Game(db12, rid12).legal_actions(0)], False)
    check("浓雾：没有结算", bool(Game(db12, rid12).result), False)

    print("\n" + "=" * 78)
    print(f" 通过 {PASS} / 失败 {FAIL}")
    print("=" * 78)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
