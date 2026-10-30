"""牌山编号系统自测：python test_wallmodel.py"""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8")

from rules import wallmodel as wm

OK = 0
FAIL = 0


def check(name: str, got, want) -> None:
    global OK, FAIL
    if got == want:
        OK += 1
        print(f"[ok]   {name}: {got}")
    else:
        FAIL += 1
        print(f"[FAIL] {name}: got {got!r}  want {want!r}")


def main() -> int:
    # ── 骰子 → 起点（你给的两个例子）──
    check("4+5=9 → 第 10 墩", wm.first_stack_no((4, 5)), 10)
    check("2+1=3 → 第 4 墩", wm.first_stack_no((2, 1)), 4)
    check("点数指向的牌山面", (wm.start_side((4, 5)), wm.start_side((2, 1)),
                        wm.start_side((1, 1))), ("北", "南", "东"))

    # ── 编号 ↔ 墩 ──
    check("第 1 墩两张牌", wm.tile_nos_of_stack(1), (1, 2))
    check("编号 63 属于第 32 墩", wm.stack_of_tile(63), 32)
    check("编号 64 也属于第 32 墩", wm.stack_of_tile(64), 32)
    check("编号 67 属于第 34 墩", wm.stack_of_tile(67), 34)
    check("编号 → seq", (wm.seq_of_tile(1), wm.seq_of_tile(136)), (0, 135))
    check("seq → 编号", wm.tile_of_seq(0), 1)

    # ── 绕圈 ──
    check("墩号绕圈", (wm.wrap_stack(69), wm.wrap_stack(0), wm.wrap_stack(-1)), (1, 68, 67))
    check("编号绕圈", (wm.wrap_tile(137), wm.wrap_tile(0)), (1, 136))

    # ── 王牌（以 n=8 为例：骰子 4+3=7 → 第 8 墩起拿）──
    n = 8
    check("王牌 7 墩 = 14 张", wm.dead_stack_nos(n), [7, 6, 5, 4, 3, 2, 1])
    check("岭上 4 张（摸的顺序 = 编号大的先）", wm.rinshan_tile_nos(n), [14, 13, 12, 11])
    check("宝牌指示牌 4 墩", [wm.dora_stack_no(n, i) for i in range(4)], [5, 4, 3, 2])
    check("第 1 张宝牌指示牌那墩两张牌", wm.dora_tile_nos(n, 0), (9, 10))
    check("第 5 墩是王牌", wm.is_dead_tile(9, n), True)
    check("第 8 墩不是王牌", wm.is_dead_tile(15, n), False)

    # ── 绕圈的王牌（n=3：岭上 = 第 2、1 墩；宝牌 = 第 68、67、66、65 墩）──
    check("n=3 王牌墩（绕圈）", wm.dead_stack_nos(3), [2, 1, 68, 67, 66, 65, 64])
    check("n=3 岭上 4 张", wm.rinshan_tile_nos(3), [4, 3, 2, 1])

    # ── 配牌计划 ──
    plan = wm.deal_plan(8)
    steps = plan["steps"]
    check("配牌共 17 步（3 圈×4 + 第 4 圈 4 步）", len(steps), 16)
    check("第 1 步给庄家 4 张、编号 15~18", (steps[0]["seat"], steps[0]["tiles"]), (0, [15, 16, 17, 18]))
    check("第 2 步给下家 4 张", (steps[1]["seat"], steps[1]["tiles"]), (1, [19, 20, 21, 22]))
    check("13 步之后庄家第 13 张 = 63", steps[12]["tiles"], [63])
    check("庄家跳牌那张 = 67", steps[12]["jump"], 67)
    check("下家第 13 张 = 64", steps[13]["tiles"], [64])
    check("上家第 13 张 = 66", steps[15]["tiles"], [66])
    check("配牌结束后牌山前面 = 68", plan["next_no"], 68)

    # ── 普通摸牌跳过王牌 ──
    # n=8 时王牌 = 第 2~7 墩 = 编号 3~14；从 3 开始摸应该直接跳到 15
    check("摸牌跳过王牌（3→15）", wm.next_live_no(3, 8), 15)
    check("非王牌不跳", wm.next_live_no(15, 8), 15)
    check("跳到下一墩的上面那张（5→7）", wm.skip_to_next_stack(5), 7)

    print(f"\n{OK} 项通过 / {FAIL} 项失败")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
