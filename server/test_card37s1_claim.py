# -*- coding: utf-8 -*-
"""Card37 S1【岭上开花】：鸣牌窗口里出现「明杠」按钮时也要能发动。

用户 2026-10-28 报的现场：已经听牌、屏幕上正好有杠按钮（明杠），点技能却提示
「只能在自己的切牌阶段发动」—— 之前 c37s1_can 只认 phase == "discard"。

修好后的链路：
  鸣牌窗口里点【岭上开花】→ 照常答这一手「明杠」（荣和优先由窗口结算保证）
  → 窗口结算真的杠出来 → 摸岭上 → 换进牌山里的和牌张 → state.c37.ready
  → 点【自摸】结算（岭上开花 + 得点 ×2）

跑法：cd N:\\apps\\tianma\\server; python test_card37s1_claim.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from game import Game                              # noqa: E402
import api_cli                                      # noqa: E402
import test_card30 as t30                           # noqa: E402
import test_game as tg                              # noqa: E402
from tiles import parse_hand                        # noqa: E402

PASS = FAIL = 0

# 0 号位 13 张：111m + 123p + 789m + 55p + 34p → 3 面子 + 雀头 + 两面，听 2p / 5p
# 1 号位打出 1m → 0 号位手里 3 张 1m → 鸣牌窗口里出现「明杠」
HANDS = ("111m123p789m55p34p",
         "1m234m567p789s1z2z3z",
         "234m567p234s5z5z6z6z",
         "345m678p345s1z1z2z2z")


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
    for s, h in enumerate(HANDS):
        tg.set_hand(db, rid, s, parse_hand(h))
    with db.tx():
        for tb in ("round_dora", "round_discards", "round_melds"):
            db.conn.execute("DELETE FROM %s WHERE round_id=?" % tb, (rid,))
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


def open_claim(db, rid):
    """1 号位打出 1m → 0 号位的鸣牌窗口；AI 座位像真实对局那样先「过」掉。"""
    g = Game(db, rid)
    g.phase = "discard"
    g.turn = 1
    g.save_flags()
    g = Game(db, rid)
    g.act(1, "discard", tile="1m")
    for s in list((g.pending or {}).get("options", {}).keys()):
        if int(s) != 0:
            g.pass_claim(int(s))
    g = Game(db, rid)
    return g, ((g.pending or {}).get("options", {}).get(0) or [])


def main() -> int:
    print("=" * 78)
    print(" Card37 S1【岭上开花】· 鸣牌窗口（明杠）里发动")
    print("=" * 78)

    print("\n① 听牌但自己没摸牌 / 没有杠 → 不能发动（老行为不变）")
    db, rid = setup("c37s1cl_a")
    g = Game(db, rid)
    check("听牌 2p/5p", sorted(g._c34s2_waits(0)), ["2p", "5p"])
    check("切牌阶段但没杠 → 不能发动", g.c37s1_can(0), False)

    print("\n② 明杠窗口里：能发动")
    db, rid = setup("c37s1cl_b")
    g, opts = open_claim(db, rid)
    check("有明杠按钮", any(str(o.get("action")) == "minkan" for o in opts), True)
    check("鸣牌窗口里能发动", g.c37s1_can(0), True)

    print("\n③ 点技能 → 明杠 + 摸岭上 + 换进和牌张（等自摸）")
    out = api_cli.handle({"op": "c37s1_arm", "seat": 0, "round_id": rid},
                         db_path=db.path)
    check("回包 ok", bool(out.get("ok", False)), True)
    g2 = Game(db, rid)
    check("明杠开出来了",
          any(str(m.get("kind")) == "minkan" for m in g2.melds(0)), True)
    check("轮到我打牌", (g2.phase, g2.turn), ("discard", 0))
    check("换好牌、等自摸", g2.c37s1_ready, 0)
    check("出现自摸按钮",
          any(a.get("action") == "tsumo" for a in g2.legal_actions(0)), True)
    check("技能消耗了", g2.skill_used(0, 37, 1), True)

    print("\n④ 点自摸 → 岭上开花 + 得点 ×2")
    o2 = api_cli.handle({"op": "act", "seat": 0, "action": "tsumo", "round_id": rid},
                        db_path=db.path)
    yaku = [str(y.get("name", "")) for y in ((o2.get("result") or {}).get("yaku") or [])]
    check("役种里有岭上开花", any("岭上开花" in y for y in yaku), True)
    check("带得点 ×2 标记", any("×2" in y for y in yaku), True)
    check("和了之后本局结束", Game(db, rid).phase, "ended")

    print("\n⑤ 不发技能（正常「过」）→ 什么都不发生")
    db, rid = setup("c37s1cl_c")
    g, _opts = open_claim(db, rid)
    g.pass_claim(0)
    g2 = Game(db, rid)
    check("没有副露", len(g2.melds(0)), 0)
    check("技能没被消耗", g2.skill_used(0, 37, 1), False)

    print("\n⑥ 别人荣和这张牌 → 我这一手不成立、技能不消耗")
    db, rid = setup("c37s1cl_d")
    # 2 号位听 1m：手牌改成能荣 1m 的形状
    tg.set_hand(db, rid, 2, parse_hand("23m55p678p234s567s"))
    g = Game(db, rid)
    g.phase, g.turn = "discard", 1
    g.save_flags()
    g = Game(db, rid)
    g.act(1, "discard", tile="1m")
    ron_at = None
    for s in list((g.pending or {}).get("options", {}).keys()):
        acts = {str(o.get("action")) for o in (g.pending["options"][s] or [])}
        if "ron" in acts:
            ron_at = int(s)
        elif int(s) != 0:
            g.pass_claim(int(s))
    check("2 号位能荣和这张 1m", ron_at, 2)
    if ron_at is not None:
        g = Game(db, rid)
        if g.c37s1_can(0):
            api_cli.handle({"op": "c37s1_arm", "seat": 0, "round_id": rid},
                           db_path=db.path)
        api_cli.handle({"op": "act", "seat": int(ron_at), "action": "ron",
                        "round_id": rid}, db_path=db.path)
        g2 = Game(db, rid)
        check("荣和成立（本局结束）", g2.phase, "ended")
        check("我没有杠", len(g2.melds(0)), 0)
        check("技能没被消耗（这一手不成立）", g2.skill_used(0, 37, 1), False)

    print("\n" + "=" * 78)
    print(f" 通过 {PASS} / 失败 {FAIL}")
    print("=" * 78)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
