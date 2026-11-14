# -*- coding: utf-8 -*-
"""强运（37-2）「摸牌前根本不出询问」回归（2026-11-13 用户报）

根因：客户端 `_c37s2_open()` 用 `String(srv_state.get("drawn", ""))` 判断「还没摸牌」，
     而服务端 `state["drawn"]` 在没摸牌时是 **null** → `String(null)` 直接抛错 /
     或得到 `<null>` → 面板打不开 → 闸门返回 false → `_pda_skip_once()` 把这次询问
     当「不发动」跳掉（发 pre_draw_skip）→ 实机就是「强运从来不问」。

本测试守两件事：
  ① 服务端确实会挂出 c37s2 的摸牌前询问（pending_asks 里看得到），并且 drawn 是 None
  ② 客户端不再用 `String(...get("drawn", ""))` 这种会吃 null 的写法
"""
from __future__ import annotations

import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")

from game import Game                                     # noqa: E402
from tiles import parse_hand, kind_of                      # noqa: E402
import api_cli                                            # noqa: E402
import test_game as tg                                    # noqa: E402
import test_chuancheng_copy as tc                         # noqa: E402

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


def make37(tag, seed):
    """座位 0 持 37，正等自己摸牌（phase=draw, turn=0, 还没摸）"""
    db = tg.fresh_db(tag)
    tc.set_orders(db, [[37, 37, 37, 37, 37], [1, 2, 3, 4, 5],
                       [1, 2, 3, 4, 6], [1, 2, 3, 4, 7]])
    rid, _m, _u = tg.new_round(db, seed=seed)
    tg.set_hand(db, rid, 0, parse_hand("123m456p789s1z2z3z"))
    for s, hand in ((1, "1m4m7m1p4p7p1s4s7s1z2z3z"),
                    (2, "2m5m8m2p5p8p2s5s8s2z3z4z"),
                    (3, "3m6m9m3p6p9p3s6s9s1z1z2z")):
        tg.set_hand(db, rid, s, parse_hand(hand))
    g = Game(db, rid)
    g.granted = {0: {37}}
    g.round_phase = "play"
    g.turn, g.phase = 0, "draw"
    g.save_flags()
    return db, rid


def main() -> int:
    print("=" * 70)
    print(" 天才麻将少女 · 强运 37-2：摸牌前要真的挂出询问")
    print("=" * 70)

    print("\n① 服务端：挂询问 + state 里能看见")
    db, rid = make37("pd37", 1137)
    g = Game(db, rid)
    check("c37s2_can=True", g.c37s2_can(0), True)
    check("摸牌前技能表里有 c37s2", "c37s2" in g._pre_draw_kinds(0), True)
    check("pre_draw_pending=True", g.pre_draw_pending(0), True)
    check("open_pre_draw_ask=True", g.open_pre_draw_ask(0), True)
    st = g.state_for(0)
    kinds = [String_kind.get("kind") for String_kind in (st.get("pending_asks") or [])
             if isinstance(String_kind, dict)]
    check("state.pending_asks 带 c37s2", "c37s2" in kinds, True)
    check("state.c37s2_can=True", bool(st.get("c37s2_can")), True)
    check("还没摸牌 → state.drawn 是 None（客户端必须按 null 判）",
          st.get("drawn"), None)

    print("\n② 跳过 / 用掉后不再挂")
    g = Game(db, rid)
    check("pre_draw_skip 关掉这笔", bool(g.pre_draw_skip(0).get("skipped", False)), True)
    g = Game(db, rid)
    check("跳过之后这一巡不再问", g.open_pre_draw_ask(0), False)
    g.note_use(0, 37, 2, gate=False)
    g.save_flags()
    g = Game(db, rid)
    check("用过之后 c37s2_can=False", g.c37s2_can(0), False)
    db.close()


    print("\n③ 真的发动：选 5p → 下一张真摸到 5p（走 op= c37s2_apply）")
    db2 = tg.fresh_db("pd37b")
    tc.set_orders(db2, [[37, 37, 37, 37, 37], [1, 2, 3, 4, 5],
                        [1, 2, 3, 4, 6], [1, 2, 3, 4, 7]])
    rid2, _m2, _u2 = tg.new_round(db2, seed=2037)
    tg.set_hand(db2, rid2, 0, parse_hand("123m456p789s1z2z3z"))
    tg.set_hand(db2, rid2, 1, parse_hand("1m4m7m1p4p7p1s4s7s9s1z2z"))
    tg.set_hand(db2, rid2, 2, parse_hand("2m5m8m2p5p8p2s5s8s2z3z4z"))
    tg.set_hand(db2, rid2, 3, parse_hand("3m6m9m3p6p9p3s6s9s1z1z2z"))
    g2 = Game(db2, rid2)
    g2.granted = {0: {37}}
    g2.round_phase = "play"
    g2.turn, g2.phase = 0, "draw"
    g2.save_flags()
    g2 = Game(db2, rid2)
    ws = g2._upcoming_wall_seqs(1)[0]
    old = db2._row("SELECT tile FROM round_wall WHERE round_id=? AND seq=?",
                   (rid2, ws))["tile"]
    r = api_cli.handle({"op": "c37s2_apply", "seat": 0, "kind": "5p",
                        "round_id": rid2}, db2.path)
    check("op 回包 ok", bool(r.get("ok")), True)
    check("回包带 c37s2.tiles", (r.get("c37s2") or {}).get("tiles"), [str(old)])
    g3 = Game(db2, rid2)
    new = db2._row("SELECT tile FROM round_wall WHERE round_id=? AND seq=?",
                   (rid2, g3._upcoming_wall_seqs(1)[0]))["tile"]
    check("我下一张变成 5p", new, "5p")
    check("对家少了 5p", any(kind_of(str(x["tile"])) == "5p"
                            for x in db2.my_hand(rid2, 2)), False)
    check("对家拿到我原来那张", any(str(x["tile"]) == str(old)
                             for x in db2.my_hand(rid2, 2)), True)
    check("本小局用掉了", g3.skill_used(0, 37, 2), True)
    g4 = Game(db2, rid2)
    g4.advance()
    check("摸牌真摸到 5p", Game(db2, rid2).drawn_tile(0), "5p")
    r2 = api_cli.handle({"op": "c37s2_apply", "seat": 0, "kind": "5p",
                         "round_id": rid2}, db2.path)
    check("第二次发动被拒", bool(r2.get("ok")), False)
    db2.close()

    print("\n④ 客户端静态防线")
    src = io.open(os.path.join(ROOT, "main.gd"), encoding="utf-8").read()
    code_lines = [ln for ln in src.splitlines()
                  if not ln.strip().startswith("#")]
    check("不再有 String(srv_state.get(\"drawn\", \"\"))（会吃 null）",
          any('String(srv_state.get("drawn", ""))' in ln for ln in code_lines), False)
    check("_c37s2_open 用 null 安全写法", '_dr37 != null and String(_dr37) != ""' in src)
    check("c37s2 登记在 PRE_DRAW_GATES",
          '"c37s2": "_c37s2_gate_before_draw"' in src)
    check("37 登记在 PRE_DRAW_KIND", "37: \"c37s2\"" in src
          or "37: \"c37s2\"," in src)

    print()
    print("=" * 70)
    print(" 通过 %d / 失败 %d" % (PASS, FAIL))
    print("=" * 70)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
