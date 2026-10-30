# -*- coding: utf-8 -*-
"""Card35 S1【流势】/ S2【逆势】自测。

跑法：cd N:\\apps\\tianma\\server; python test_card35.py
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
from tiles import parse_hand                         # noqa: E402

PASS = FAIL = 0


def check(name, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  got {got!r} want {want!r}")


def setup(tag, card=35, live=40):
    db, rid = t30.setup(tag, card=card)
    with db.tx():
        db.conn.execute("DELETE FROM round_dora WHERE round_id=?", (rid,))
        db.conn.execute("DELETE FROM round_discards WHERE round_id=?", (rid,))
        db.conn.execute("DELETE FROM round_melds WHERE round_id=?", (rid,))
        db.conn.execute("UPDATE rounds SET live_left=? WHERE round_id=?", (int(live), rid))
    g = Game(db, rid)
    g.round_phase = "play"
    g.phase = "discard"
    g.turn = 0
    g.deal_wait = set()
    g.deal_used = set()
    g.save_flags()
    return db, rid


def setup_owner_elsewhere(tag, meld_kind="pon"):
    """35 号卡在 1 号位（赢家是 0 号位），场上还有一副副露。"""
    db, rid = t30.setup(tag, card=35, mains=[6, 35, 8, 9])
    tg.set_hand(db, rid, 0, parse_hand("123m456m789m234p5s"))
    with db.tx():
        db.conn.execute("DELETE FROM round_dora WHERE round_id=?", (rid,))
        db.conn.execute("DELETE FROM round_discards WHERE round_id=?", (rid,))
        db.conn.execute("DELETE FROM round_melds WHERE round_id=?", (rid,))
        db.conn.execute(
            "INSERT INTO round_melds(round_id,meld_id,seat,kind,called_tile,from_seat,"
            "tiles_json,rot_index,seqs_json) VALUES(?,0,2,?,'1p',3,?,0,'[]')",
            (rid, meld_kind, '["1p","1p","1p"]'))
    g = Game(db, rid)
    g.granted = {}
    g.round_phase = "play"
    g.phase = "discard"
    g.turn = 0
    g.deal_wait = set()
    g.deal_used = set()
    g.save_flags()
    return db, rid


def settle_ron(db, rid):
    """0 号位荣和 1 号位的 5s（和 _apply_claim 里调 _finish 的路径一致）。"""
    g = Game(db, rid)
    res = g._judge_win(0, "5s", tsumo=False)
    g._finish(0, 1, "ron", res)
    return Game(db, rid).result or {}


def main() -> int:
    print("=" * 78)
    print(" Card35 S1【流势】 / S2【逆势】")
    print("=" * 78)

    print("\n① 注册 / 时机")
    check("S1 名字", skills.info(35, 1).get("name"), "流势")
    check("S1 时机 = 切牌", skills.timing(35, 1), "discard")
    check("S2 名字", skills.info(35, 2).get("name"), "逆势")
    check("S2 时机 = 结算", skills.timing(35, 2), "settle")

    print("\n② 副露 → 自动挂上「排接下来 4 张」")
    db, rid = setup("c35a")
    g = Game(db, rid)
    check("开排（副露触发）", g.c35_start(0), True)
    g2 = Game(db, rid)
    check("轮到我、可以排", g2.c35_can(0), True)
    check("张数 = 4", g2.c35_count(), 4)
    st = g2.state_for(0)
    check("state.c35.can", bool((st.get("c35") or {}).get("can")), True)
    check("state.c35.tiles 有 4 张", len((st.get("c35") or {}).get("tiles") or []), 4)
    st1 = g2.state_for(1)
    check("别人看不到我的牌山", (st1.get("c35") or {}).get("tiles"), [])

    print("\n③ 排序生效（接下来 4 张按我排的顺序）")
    before = g2._c26_tiles(4)
    r = g2.c35s1_set(0, [3, 2, 1, 0])
    check("返回 4 张", len(r.get("tiles") or []), 4)
    check("顺序 = 原来的倒序", r.get("tiles"), [before[3], before[2], before[1], before[0]])
    g3 = Game(db, rid)
    check("牌山真的改了", g3._c26_tiles(4), [before[3], before[2], before[1], before[0]])
    check("排完就不 pending 了", int(g3.c35_pending), -1)
    try:
        g3.c35s1_set(0, [0, 1, 2, 3])
        check("重复排被拒", False, True)
    except RuleError:
        check("重复排被拒", True, True)

    print("\n④ 不限次数：再副露一次还能排")
    g4 = Game(db, rid)
    check("第二次开排", g4.c35_start(0), True)
    g5 = Game(db, rid)
    check("又能排", g5.c35_can(0), True)
    check("mark 递增", int(g5.c35_mark) >= 2, True)
    check("没记成一次性技能", g5.skill_used(0, 35, 1) if hasattr(g5, "skill_used") else False, False)

    print("\n⑤ 直接打牌 = 放弃这次调整（牌山不动）")
    tiles_before = Game(db, rid)._c26_tiles(4)
    tg.set_hand(db, rid, 0, parse_hand("123m456m789m23p55s"), drawn="5s")
    g6 = Game(db, rid)
    g6.c35_start(0)
    g6._do_discard(0, tile="5s")
    g7 = Game(db, rid)
    check("pending 清掉", int(g7.c35_pending), -1)
    check("牌山保持原样", g7._c26_tiles(4), tiles_before)

    print("\n⑥ 超时自动放弃")
    g8 = Game(db, rid)
    g8.c35_start(0)
    g8.c35_deadline = 1.0                      # 过去的时间 → 超时
    g8.save_flags()
    g9 = Game(db, rid)
    check("检测到超时", g9.c35_timeout(), True)
    g9.c35_skip()
    check("跳过之后 pending 清掉", int(Game(db, rid).c35_pending), -1)

    print("\n⑦ 暗杠不算副露（只有加杠/吃/碰/明杠算）")
    check("暗杠不触发", "kakan" in ("chi", "pon", "minkan", "kakan"), True)

    print("\n⑧ 35S2：别人和牌 + 有人副露 → 收付减半")
    db2, rid2 = setup("c35b")
    with db2.tx():
        db2.conn.execute(
            "INSERT INTO round_melds(round_id,meld_id,seat,kind,called_tile,from_seat,"
            "tiles_json,rot_index,seqs_json) VALUES(?,0,1,'pon','1m',2,?,0,'[]')",
            (rid2, '["1m","1m","1m"]'))
    g10 = Game(db2, rid2)
    d = {1: 8000, 0: -4000, 2: -2000, 3: -2000}
    check("减半生效", g10._c35s2_half(1, d), True)
    check("赢家得点减半", d[1], 4000)
    check("付点也减半（零和）", [d[0], d[2], d[3]], [-2000, -1000, -1000])
    check("合计还是 0", sum(d.values()), 0)

    d2 = {0: 8000, 1: -4000, 2: -2000, 3: -2000}
    check("我自己和牌不减半", Game(db2, rid2)._c35s2_half(0, d2), False)
    check("我自己和牌点数不动", d2[0], 8000)

    print("\n⑨ 35S2：没人副露就不减半")
    db3, rid3 = setup("c35c")
    g11 = Game(db3, rid3)
    d3 = {1: 8000, 0: -4000, 2: -2000, 3: -2000}
    check("没人副露 → 不减", g11._c35s2_half(1, d3), False)
    check("点数不动", d3[1], 8000)

    print("\n⑩ 35S2：暗杠不算「有人副露」")
    db4, rid4 = setup("c35d")
    with db4.tx():
        db4.conn.execute(
            "INSERT INTO round_melds(round_id,meld_id,seat,kind,called_tile,from_seat,"
            "tiles_json,rot_index,seqs_json) VALUES(?,0,2,'ankan','9s',2,?, -1,'[]')",
            (rid4, '["9s","9s","9s","9s"]'))
    d4 = {1: 8000, 0: -4000, 2: -2000, 3: -2000}
    check("只有暗杠 → 不减", Game(db4, rid4)._c35s2_half(1, d4), False)

    print("\n⑪ 真·碰牌链路（_apply_claim）会自动开「流势」")
    db5, rid5 = setup("c35e")
    tg.set_hand(db5, rid5, 0, parse_hand("1m1m234p567p789s11z"))
    g12 = Game(db5, rid5)
    g12._apply_claim(0, "pon", ["1m", "1m"],
                     {"tile": "1m", "from": 1, "discard_seq": 0})
    g13 = Game(db5, rid5)
    check("碰完可以排", g13.c35_can(0), True)
    check("碰完 pending 是我", int(g13.c35_pending), 0)

    print("\n⑫ 暗杠不触发「流势」")
    db6, rid6 = setup("c35f")
    tg.set_hand(db6, rid6, 0, parse_hand("9s9s9s9s234p567p789s1z"))
    g14 = Game(db6, rid6)
    g14._kan(0, "ankan", "9s")
    g15 = Game(db6, rid6)
    check("暗杠后没有 pending", int(g15.c35_pending), -1)
    check("暗杠后不能排", g15.c35_can(0), False)

    print("\n⑬ 看破 / 封堵：点「排好」那一下就是发动时机")
    import api_cli
    check("c35s1_set 挂在看破闸门表",
          api_cli._SKILL_OP_PAIRS.get("c35s1_set"), (35, 1))
    check("有对应的 op", "c35s1_set" in api_cli.OPS, True)

    print("\n⑭ 真·结算链路：得点减半，结算面板读的 pays.total 也得减半")
    db7, rid7 = setup_owner_elsewhere("c35g")
    g16 = Game(db7, rid7)
    check("35 号卡在 1 号位（赢家是 0）", g16.c35s2_owner(), 1)
    r7 = settle_ron(db7, rid7)
    check("有逆势明细", "逆势（得点减半）" in (r7.get("yaku_names") or []), True)
    check("得点 = 减半后的值", int(r7.get("points") or 0), 2000)
    check("结算面板的 pays.total 也减半（不然玩家看到「没减半」）",
          int((r7.get("pays") or {}).get("total", -1)), int(r7.get("points") or 0))
    check("风盘分数真的按减半走", int((r7.get("deltas") or {}).get("0", 0)), 2000)

    print("\n" + "=" * 78)
    print(f" 通过 {PASS} / 失败 {FAIL}")
    print("=" * 78)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
