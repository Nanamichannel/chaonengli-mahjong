# -*- coding: utf-8 -*-
"""鸣牌窗口：答过之后不再把 options 发给客户端（吃按钮不消失 / 跑到一号位 / 卡死）

现场：2 号位能吃上家（1 号位）的牌 → 点「跳过」→ 吃按钮不消失、还挪到一号位，
随后手牌点不动、界面彻底卡死。

根因：`state_for()` 把 `pending["options"][seat]` 原样下发，不看 `answers`。
pass 之后客户端仍然 `has_action("chi")` 为真 → 吃按钮继续显示（按优先级落到 1 号槽）、
`waiting_for_others` 也被算成 false → 没人继续推进这个窗口 → 全桌卡死。

跑法：cd N:\apps\tianma\server; python test_claim_after_pass.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from game import Game                    # noqa: E402
import test_game as tg                   # noqa: E402
from tiles import parse_hand             # noqa: E402

PASS = FAIL = 0


def check(name, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  got {got!r} want {want!r}")


def acts(opts):
    return sorted({str(o.get("action", "")) for o in (opts or [])})


def main() -> int:
    print("=" * 74)
    print(" 鸣牌窗口：答过之后不该再显示可选项")
    print("=" * 74)

    db = tg.fresh_db("claim_pass")
    rid, _m, _u = tg.new_round(db, seed=61)
    # 0 号位：手里两张 5m → 能碰
    tg.set_hand(db, rid, 0, parse_hand("5m5m1m2m3m4p5p6p1s2s3s9s9s"))
    # 1 号位：打出 5m（2 号位的上家）
    tg.set_hand(db, rid, 1, parse_hand("5m1m2m3m7p8p9p4s5s6s1z2z3z"))
    # 2 号位：3m4m → 能吃 5m
    tg.set_hand(db, rid, 2, parse_hand("3m4m1p2p3p7s8s9s1z2z3z4z"))
    tg.set_hand(db, rid, 3, parse_hand("6m7m8m1p4p7p2s5s8s1z2z3z"))

    g = Game(db, rid)
    g.round_phase = "play"
    g.turn, g.phase = 1, "discard"
    g.save_flags()
    g = Game(db, rid)
    g.act(1, "discard", tile="5m")
    g = Game(db, rid)

    print("\n① 窗口刚开：0 号位能碰、2 号位能吃")
    check("窗口里有 2 号位", 2 in (g.pending or {}).get("options", {}))
    st2 = g.state_for(2)
    check("2 号位看到能吃", "chi" in acts((st2.get("claim") or {}).get("options")))
    check("2 号位还没答过", (st2.get("claim") or {}).get("answered"), False)
    st0 = g.state_for(0)
    check("0 号位看到能碰", "pon" in acts((st0.get("claim") or {}).get("options")))

    print("\n② 2 号位点「跳过」")
    g.pass_claim(2)
    g = Game(db, rid)
    check("窗口还开着（0 号位还没答）", g.phase, "claim")

    st2b = g.state_for(2)
    print("   2 号位 claim =", st2b.get("claim"))
    check("答过之后不再下发可选项（吃按钮该消失）",
          acts((st2b.get("claim") or {}).get("options")), [])
    check("标记成 answered", (st2b.get("claim") or {}).get("answered"), True)
    check("legal 里也没有 chi / pass", acts(g.legal_actions(2)), [])

    print("\n③ 别人的可选项不受影响")
    st0b = g.state_for(0)
    check("0 号位仍然能碰", "pon" in acts((st0b.get("claim") or {}).get("options")))

    print("\n④ 0 号位也过掉 → 窗口结算，轮到下家摸牌")
    g.pass_claim(0)
    g = Game(db, rid)
    check("窗口关了", g.pending, None)
    check("不再是 claim 阶段", g.phase != "claim", True)
    check("轮到 2 号位摸牌（1 的下家）", (g.turn, g.phase), (2, "draw"))

    print("\n⑤ 我自己吃下来之后同理（吃成功 → 下一手没有残留选项）")
    db2 = tg.fresh_db("claim_pass2")
    rid2, _m2, _u2 = tg.new_round(db2, seed=62)
    tg.set_hand(db2, rid2, 0, parse_hand("5m5m1m2m3m4p5p6p1s2s3s9s9s"))
    tg.set_hand(db2, rid2, 1, parse_hand("5m1m2m3m7p8p9p4s5s6s1z2z3z"))
    tg.set_hand(db2, rid2, 2, parse_hand("3m4m1p2p3p7s8s9s1z2z3z4z"))
    tg.set_hand(db2, rid2, 3, parse_hand("6m7m8m1p4p7p2s5s8s1z2z3z"))
    gg = Game(db2, rid2)
    gg.round_phase = "play"
    gg.turn, gg.phase = 1, "discard"
    gg.save_flags()
    gg = Game(db2, rid2)
    gg.act(1, "discard", tile="5m")
    gg = Game(db2, rid2)
    gg.act(2, "chi", tiles=["3m", "4m"])
    gg = Game(db2, rid2)
    check("0 号位还没答 → 窗口先不结算", gg.phase, "claim")
    gg.pass_claim(0)                       # 0 号位过掉 → 吃（优先级高于碰）生效
    gg = Game(db2, rid2)
    check("吃完轮到自己打牌", (gg.turn, gg.phase), (2, "discard"))
    check("手里没有残留的 claim", gg.state_for(2).get("claim"), None)

    print("\n" + "=" * 74)
    print(f" 结果：{PASS} 项通过，{FAIL} 项失败")
    print("=" * 74)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
