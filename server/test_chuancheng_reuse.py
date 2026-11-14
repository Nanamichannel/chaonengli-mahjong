# -*- coding: utf-8 -*-
"""传承（16-1）「复制来的技能要能再用一次」回归（2026-11-13 用户报）

口径：原技能一份一次性配额，传承来的那份**另算一份**。
本文件只盯「实机点得到、点了真的能发动」这条链：
  ① 本小局用过的一次性技能，传承后 can 必须重新变 True（染手 33-1 这种
     以前被 c33s1_on 这个「效果标记」当次数闸门挡住）
  ② skill_used 两本账（24-1 这种纯 skill_used 的）
  ③ 传承候选清单不再列配牌期技能（timing=deal）
  ④ 客户端静态防线：16 号卡转发必须 -1 且带 is_copy=true；
     _apply_used_skills 不能再把 16 号卡那格置灰（那一格显示的是复制来的技能）
"""
from __future__ import annotations

import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")

import api_cli                                            # noqa: E402
from game import Game                                     # noqa: E402
from tiles import parse_hand                              # noqa: E402
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


def make_owned(tag, seed, cards, log):
    """座位 0 同时持有 16 + cards（granted），并把 log 写进 skill_log。"""
    db = tg.fresh_db(tag)
    tc.set_orders(db, [[16, 16, 16, 16, 16], [1, 2, 3, 4, 5],
                       [1, 2, 3, 4, 6], [1, 2, 3, 4, 7]])
    rid, _m, _u = tg.new_round(db, seed=seed)
    tg.set_hand(db, rid, 0, parse_hand("123m456p789s1z2z3z") + ["5m"], drawn="5m")
    for s, hand in ((1, "1m4m7m1p4p7p1s4s7s1z2z3z"),
                    (2, "2m5m8m2p5p8p2s5s8s2z3z4z"),
                    (3, "3m6m9m3p6p9p3s6s9s1z2z3z")):
        tg.set_hand(db, rid, s, parse_hand(hand))
    items = [{"seat": 0, "card": int(c), "skill": int(k), "wind": "dong", "number": 1}
             for c, k in log]
    with db.tx():
        db.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('skill_log', ?)",
                        (json.dumps(items),))
    g = Game(db, rid)
    g.granted = {0: {16} | {int(c) for c in cards}}
    g.round_phase = "play"
    g.turn, g.phase = 0, "discard"
    g.save_flags()
    return db, rid


def main() -> int:
    print("=" * 70)
    print(" 天才麻将少女 · 传承：复制来的技能能再发动一次（2026-11-13）")
    print("=" * 70)

    # ── ① 染手（33-1）：效果标记不能当次数闸门 ──────────────────────
    print("\n① 染手 33-1：本小局用过 → 传承后能再用一次")
    db, rid = make_owned("ccr33", 833, [33], [(33, 1)])
    g = Game(db, rid)
    check("用过之前 can=True", g.c33s1_can(0), True)
    g.note_use(0, 33, 1, gate=False)          # 真发动（used_skills 记一笔）
    g.c33s1_on.add(0)                         # 效果标记（和牌限制）
    g.save_flags()
    g = Game(db, rid)
    check("用过之后 can=False", g.c33s1_can(0), False)
    g.chuancheng_use(0, 33, 1)                # 传承复制 33-1
    g = Game(db, rid)
    check("传承后有复制品", g.copy_granted(0, 33, 1), True)
    check("传承后 can=True（要能再换一次）", g.c33s1_can(0), True)
    check("原技能那本还是「用过」", g.orig_used(0, 33, 1), True)
    check("复制品那本还没用", g.copy_used(0, 33, 1), False)
    g.req_copy_key = "33-1"                   # 客户端点复制品图标 → copy=true
    check("点了复制品 → can 仍 True", g.c33s1_can(0), True)
    g.note_use(0, 33, 1, gate=False)
    check("复制品记到 used_copy", g.copy_used(0, 33, 1), True)
    g.req_copy_key = ""
    g = Game(db, rid)
    check("两份都用完 → can=False", g.c33s1_can(0), False)
    check("效果标记没被清掉（和牌限制还在）", 0 in g.c33s1_on, True)
    db.close()

    # ── ② 一发（24-1）：纯 skill_used 的那一类 ───────────────────────
    print("\n② 一发 24-1：两本账分开算")
    db, rid = make_owned("ccr24", 834, [24], [(24, 1)])
    g = Game(db, rid)
    g.note_use(0, 24, 1, gate=False)
    check("原技能用过 → skill_used=True", g.skill_used(0, 24, 1), True)
    g.chuancheng_use(0, 24, 1)
    g = Game(db, rid)
    check("传承后 skill_used=False（复制品那份额度在）", g.skill_used(0, 24, 1), False)
    g.req_copy_key = "24-1"
    g.note_use(0, 24, 1, gate=False)
    check("复制品用掉", g.copy_used(0, 24, 1), True)
    g.req_copy_key = ""
    check("两份都用完 → skill_used=True", g.skill_used(0, 24, 1), True)
    db.close()

    # ── ③ 传承候选：不列配牌期技能 ──────────────────────────────────
    print("\n③ 传承清单：配牌期技能不列（选了也发不了）")
    db, rid = make_owned("ccrlist", 835, [11, 3], [(3, 1), (11, 1)])
    g = Game(db, rid)
    pairs = [(int(x["card"]), int(x["skill"])) for x in g.chuancheng_list(0)]
    check("3-1（配牌期）被过滤掉", (3, 1) in pairs, False)
    check("11-1（摸牌期）还在", (11, 1) in pairs, True)
    db.close()

    # ── ④ 客户端静态防线 ───────────────────────────────────────────
    print("\n④ 客户端静态防线")
    src = io.open(os.path.join(ROOT, "main.gd"), encoding="utf-8").read()
    check("16 号卡转发带「- 1」（cp.skill 是 1 起）",
          "_on_identity_skill(seat, int(cp.get(\"card\", 0)), int(cp.get(\"skill\", 1)) - 1, true)"
          in src)
    check("_apply_used_skills 跳过 16-1",
          "if int(parts[0]) == 16 and int(parts[1]) == 1:\n\t\t\tcontinue" in src
          or "int(parts[0]) == 16 and int(parts[1]) == 1:" in src)
    check("16 号卡那格按 copy_used 判灰", "copy_used" in src and "set_skill_disabled\", 16, 0" in src)
    gsrc = io.open(os.path.join(ROOT, "server", "game.py"), encoding="utf-8").read()
    check("39-1 隐形：效果标记不再当次数闸门",
          "if self.c39s1_on and int(self.c39s1_by) != s:" in gsrc)

    # ── ⑤ api_cli：copy=true 反查出 (33,1) ─────────────────────────
    print("\n⑤ copy=true → op 反查")
    check("c33s1_swap → (33,1)", api_cli._op_skill_pair("c33s1_swap", {}), (33, 1))

    print()
    print("=" * 70)
    print(" 通过 %d / 失败 %d" % (PASS, FAIL))
    print("=" * 70)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
