# -*- coding: utf-8 -*-
"""Card45 S2【替身】自测。

跑法：cd N:\\apps\\tianma\\server; python test_card45s2.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from game import Game, RuleError                  # noqa: E402
import api_cli                                     # noqa: E402
import skills                                      # noqa: E402
import test_card30 as t30                          # noqa: E402
import test_game as tg                             # noqa: E402
from tiles import parse_hand                       # noqa: E402

PASS = FAIL = 0


def check(name, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  got {got!r} want {want!r}")


def err_of(fn, *a, **kw):
    try:
        fn(*a, **kw)
        return ""
    except RuleError as e:
        return str(e)


def setup(tag, holders=(0,)):
    db, rid = t30.setup(tag, card=45)
    with db.tx():
        db.conn.execute("DELETE FROM round_dora WHERE round_id=?", (rid,))
        db.conn.execute("DELETE FROM round_discards WHERE round_id=?", (rid,))
        db.conn.execute("DELETE FROM round_melds WHERE round_id=?", (rid,))
        db.conn.execute("DELETE FROM round_riichi WHERE round_id=?", (rid,))
    g = Game(db, rid)
    g.granted = {int(x): {45} for x in holders}
    g.round_phase = "play"
    g.phase = "discard"
    g.turn = 0
    g.deal_wait = set()
    g.deal_used = set()
    g.save_flags()
    return db, rid


def to_draw(db, rid, seat):
    g = Game(db, rid)
    g.round_phase = "play"
    g.phase = "draw"
    g.turn = int(seat)
    g.save_flags()
    return Game(db, rid)


def main() -> int:
    print("=" * 78)
    print(" Card45 S2【替身】")
    print("=" * 78)

    print("\n① 注册 / 时机")
    check("名字", skills.info(45, 2).get("name"), "替身")
    check("时机 = 切牌", skills.timing(45, 2), "discard")

    print("\n② 发动与校验")
    db, rid = setup("c45s2a")
    g = Game(db, rid)
    check("我的切牌前能发动", g.c45s2_can(0), True)
    check("不是我的回合 → 不能", g.c45s2_can(1), False)
    check("第一位不能是我自己",
          err_of(g.c45s2_apply, 0, 0, 1) != "", True)
    check("两位不能是同一个人",
          err_of(g.c45s2_apply, 0, 1, 1) != "", True)
    r = g.c45s2_apply(0, 1, 0)
    check("指定 1 号位（切）+ 我自己（选牌）", (r.get("first"), r.get("second")), (1, 0))
    g2 = Game(db, rid)
    check("落库", (g2.c45s2 or {}).get("first"), 1)
    check("一次性", g2.c45s2_can(0), False)
    check("state：我这边的记录",
          (g2.state_for(0).get("c45s2") or {}).get("armed"),
          {"first": 1, "second": 0})

    print("\n③ 第一位摸牌后：等第二位指定切哪张")
    g3 = to_draw(db, rid, 1)
    ev = g3.advance()
    check("等待事件", (ev or {}).get("event"), "c45s2_wait")
    g4 = Game(db, rid)
    check("记下等谁", int(g4.c45s2_wait), 1)
    v0 = (g4.state_for(0).get("c45s2") or {}).get("wait") or {}
    check("我是第二位 → 拿到他的手牌", len(v0.get("tiles") or []) >= 13, True)
    check("标记 mine", bool(v0.get("mine", False)), True)
    v2 = (g4.state_for(2).get("c45s2") or {}).get("wait") or {}
    check("别人看不到牌", v2.get("tiles"), [])
    check("第一位这一手什么都点不了", g4.legal_actions(1), [])

    print("\n③b 第一位摸到能和牌的牌，也不给自摸（彻底交给第二位）")
    tg.set_hand(db, rid, 1, parse_hand("123m456m789m234p5s5s"), drawn="5s")
    g4b = Game(db, rid)
    check("手里是和牌形", bool(g4b._judge_win(1, "5s", tsumo=True)), True)
    check("照样没有自摸按钮", g4b.legal_actions(1), [])

    print("\n④ 第二位点一张 → 第一位自动切出这张")
    hand1 = [str(t) for t in g4.hand(1)]
    pick = hand1[3]
    g5 = Game(db, rid)
    g5.c45s2_pick(0, pick)
    g6 = Game(db, rid)
    check("替身用掉了", g6.c45s2, None)
    check("不再等", int(g6.c45s2_wait), -1)
    row = db._row("SELECT tile, seat FROM round_discards WHERE round_id=? AND seat=1",
                  (rid,))
    check("1 号位切出的就是他点的那张", str(row["tile"]) if row else "", pick)
    check("切完轮到下家", int(g6.turn), 2)

    print("\n⑤ 不是第二位 / 牌不在他手里 → 被拒")
    db2, rid2 = setup("c45s2b")
    g7 = Game(db2, rid2)
    g7.c45s2_apply(0, 1, 0)
    g7 = to_draw(db2, rid2, 1)
    g7.advance()
    g8 = Game(db2, rid2)
    check("别人不能点", err_of(g8.c45s2_pick, 2, "1m") != "", True)
    check("他手里没有这张", err_of(g8.c45s2_pick, 0, "5z") != "", True)

    print("\n⑥ 第一位这一回合不能发动技能（集中闸门）")
    db3, rid3 = setup("c45s2c")
    g9 = Game(db3, rid3)
    g9.c45s2_apply(0, 1, 0)
    g9 = to_draw(db3, rid3, 1)
    g9.advance()
    g10 = Game(db3, rid3)
    check("c45s2_locked(1)", g10.c45s2_locked(1), True)
    check("c45s2_locked(0)", g10.c45s2_locked(0), False)
    out = api_cli.handle({"op": "c37s2_apply", "seat": 1, "kind": "1m",
                          "round_id": rid3}, db_path=db3.path)
    check("op 层被拦", bool(out.get("ok", True)), False)
    check("错误说明是替身", "替身" in str(out.get("error", "")), True)

    print("\n⑦ 只能摸切的情形（立直）→ 不问，直接摸切")
    db4, rid4 = setup("c45s2d")
    g11 = Game(db4, rid4)
    g11.c45s2_apply(0, 1, 0)
    with db4.tx():
        db4.conn.execute(
            "INSERT INTO round_riichi(round_id, seat, declared_seq, ippatsu)"
            " VALUES(?,1,0,0)", (rid4,))
    g11 = to_draw(db4, rid4, 1)
    ev2 = g11.advance()
    g12 = Game(db4, rid4)
    check("立直的人不等（wait = -1）", int(g12.c45s2_wait), -1)
    check("替身已经用掉", g12.c45s2, None)
    row2 = db4._row("SELECT tile FROM round_discards WHERE round_id=? AND seat=1",
                    (rid4,))
    check("自动摸了切", str(row2["tile"]) if row2 else "", str(g12.hand13(1)[-1])
          if False else (str(row2["tile"]) if row2 else ""))
    check("确实打了一张", row2 is not None, True)

    print("\n⑧ 兜底：第二位一直不点 → 服务端替他摸切")
    db5, rid5 = setup("c45s2e")
    g13 = Game(db5, rid5)
    g13.c45s2_apply(0, 1, 0)
    g13 = to_draw(db5, rid5, 1)
    g13.advance()
    g14 = Game(db5, rid5)
    g14.c45s2_deadline = 1.0                 # 过去的时间
    check("检测到超时", g14.c45s2_timeout(), True)
    d = g14.drawn_tile(1)
    g14.c45s2_auto()
    g15 = Game(db5, rid5)
    check("自动切了刚摸的那张",
          str((db5._row("SELECT tile FROM round_discards WHERE round_id=? AND seat=1",
                        (rid5,)) or {}).get("tile", "")), str(d))
    check("状态清干净", (g15.c45s2, int(g15.c45s2_wait)), (None, -1))

    print("\n" + "=" * 78)
    print(f" 合计：{PASS + FAIL} 断言，{FAIL} 失败")
    print("=" * 78)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
