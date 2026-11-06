# -*- coding: utf-8 -*-
"""询问挂在「没有窗口的座位」上时，服务端要自动替它跳过（防全桌死锁）。

现场（2026-11-06）：room 19822 卡在
    phase=c29s1, prompt={kind:c29s1, waiting:[3]}
3 号位是 AI，但 0 号位客户端看到 prompt 就谁都不动（连 op=step 都不发），
op_step 里的 auto-skip 永远跑不到 → 全桌死锁。

修法：handle() 的自愈块每个请求都调 auto_resolve_prompt()。

用法：cd server; python test_prompt_auto.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")

import api_cli  # noqa: E402
from game import Game  # noqa: E402
import test_game as tg  # noqa: E402

PASS = FAIL = 0


def check(name, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  got={got!r} want={want!r}")


def build(tag, seed):
    db = tg.fresh_db(tag)
    rid, _m, _u = tg.new_round(db, seed=seed)
    g = Game(db, rid)
    g.phase = "c29s1"
    g.turn = 2
    g.c29s1_offer = {"seat": 3, "tile": "9p", "discard_seq": 13, "from": 2,
                     "choices": [["7p", "8p"]]}
    g.save_flags()
    return db, rid


def main() -> int:
    print("=" * 70)
    print(" 天才麻将少女 · 询问挂在 AI 座位上要自动跳过")
    print("=" * 70)

    print("\n① 等的是 AI → 自动跳过，牌局继续")
    db, rid = build("pauto1", 9001)
    g = Game(db, rid)
    check("先确认挂在 3 号位", (g.prompt_state() or {}).get("waiting"), [3])
    k = api_cli.auto_resolve_prompt(g, {0})
    check("处理掉的是 c29s1", k, "c29s1")
    g2 = Game(db, rid)
    check("询问清掉", g2.prompt_state(), None)
    check("加速 offer 清掉", g2.c29s1_offer, None)
    check("牌局往前走（不再卡 c29s1）", g2.phase != "c29s1", True)

    print("\n② 等的是真人 → 不许替他动")
    db, rid = build("pauto2", 9002)
    g = Game(db, rid)
    k2 = api_cli.auto_resolve_prompt(g, {0, 3})
    check("不处理", k2, "")
    g2 = Game(db, rid)
    check("询问还在", bool(g2.c29s1_offer), True)
    check("还在等 3 号位", (g2.prompt_state() or {}).get("kind"), "c29s1")

    print("\n" + "=" * 70)
    print(f" 通过 {PASS} 项，失败 {FAIL} 项")
    print("=" * 70)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
