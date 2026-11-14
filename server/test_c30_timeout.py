# -*- coding: utf-8 -*-
"""【向听】(30-1) 60 秒宽松兜底：一个人挂机不能把整桌钉死。

用户口径 2026-11-09（取代 10-28「向听不做超时兜底」）：
  · 被问的那家 60 秒不交牌 → 替他交前两张
  · 发动者 60 秒不挑牌   → 直接放过这一步（两家都完就收尾）

跑法：cd N:\\apps\\tianma\\server; python test_c30_timeout.py
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from game import Game                    # noqa: E402
import test_card30 as t30               # noqa: E402

PASS = FAIL = 0


def check(name, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  got {got!r} want {want!r}")


def age_flow(db, rid, seconds_ago: float = 120.0) -> None:
    """把 deal_flow.ts 拨回过去（直接改字典再存，别用 SQL 改 JSON）。"""
    g = Game(db, rid)
    if not g.deal_flow:
        return
    g.deal_flow["ts"] = time.time() - float(seconds_ago)
    g.save_flags()


def flow(db, rid):
    return dict(Game(db, rid).deal_flow or {})


def main() -> int:
    print("=" * 74)
    print(" 向听 60 秒兜底")
    print("=" * 74)

    print("\n① 等交牌超时 → 自动替他交前两张")
    db, rid = t30.setup("c30to1")
    Game(db, rid)._c30s1_arm(0, [3, 1])
    f = flow(db, rid)
    check("流程起来了（等交牌）", str(f.get("sub")), "give")
    check("flow 带时间戳", float(f.get("ts", 0) or 0) > 0, True)
    check("刚发动 → 不触发", Game(db, rid).c30s1_timeout(60.0), False)
    age_flow(db, rid)
    check("120 秒后触发兜底", Game(db, rid).c30s1_timeout(60.0), True)
    f2 = flow(db, rid)
    check("已经推进到「我挑牌」", str(f2.get("sub")), "swap")
    check("他交了两张", len(f2.get("picked") or []), 2)

    print("\n② 发动者不挑牌超时 → 放过这一步")
    tgt1 = int(f2.get("target", -1))
    age_flow(db, rid)
    check("120 秒后触发兜底", Game(db, rid).c30s1_timeout(60.0), True)
    f3 = flow(db, rid)
    print("     flow =", {k: f3.get(k) for k in ("sub", "stage", "target", "picked")})
    check("这一步被放过（改问另一家 / 或已收尾）",
          (not f3) or (str(f3.get("sub")) == "give" and int(f3.get("target", -1)) != tgt1),
          True)

    print("\n③ 反复兜底 → 最终必须收尾（不能钉死）")
    for _ in range(5):
        if not flow(db, rid):
            break
        age_flow(db, rid)
        Game(db, rid).c30s1_timeout(60.0)
    check("流程已收尾", bool(flow(db, rid)), False)

    print("\n" + "=" * 74)
    print(" 合计：%d 断言，%d 失败" % (PASS, FAIL))
    print("=" * 74)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
