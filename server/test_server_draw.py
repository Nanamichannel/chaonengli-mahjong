"""服务端「摸牌 / 翻宝牌」接口自测（客户端只渲染，规则全在服务端）。

跑法： python test_server_draw.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import api_cli  # noqa: E402
from game import Game  # noqa: E402
from rules import wallmodel  # noqa: E402

PASS = FAIL = 0


def check(name, got, want):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  got {got!r} want {want!r}")


def main() -> int:
    db = api_cli.DB(api_cli.DB_PATH)
    db.init_schema()
    rid_old = api_cli._get_round_id(db)

    r = api_cli.handle({"op": "start", "seat": 0})
    check("开桌返回牌山 136 张", len(r["wall"]), 136)
    st = r["state"]
    check("骰子来自服务端", len(st["dice"]), 2)
    check("拿牌起点 = 骰子点数 + 1", st["first_stack"], sum(st["dice"]) + 1)
    check("牌山面来自服务端", st["start_side"], wallmodel.start_side(tuple(st["dice"])))
    check("开局阶段 = 配牌", st["round_phase"], "deal")
    check("开局一张牌都没拿走", st["wall_taken"], [])
    check("开局一张宝牌都没翻", st["dora"], [])

    n = st["deal_steps"]
    for i in range(n):
        r = api_cli.handle({"op": "deal_step", "seat": 0})
    st = r["state"]
    check("配牌结束", st["deal_done"], True)
    check("配牌后阶段 = 切牌", st["round_phase"], "play")
    check("配牌拿走 53 张", len(st["wall_taken"]), 53)
    check("配牌后翻开第 1 张宝牌", len(st["dora"]), 1)
    check("宝牌指示牌有墩号", len(st["dora_stacks"]), 1)
    check("宝牌指示牌在 n-3 墩",
          st["dora_stacks"][0], wallmodel.dora_stack_no(st["first_stack"], 0))
    check("配牌后 0 号位 14 张、其余 13 张",
          [c["tiles"] for c in st["hand_counts"]], [14, 13, 13, 13])

    # 牌山拿走 53 张：前 53 张编号 15..67（含跳牌）不该出现在待摸序列
    taken = set(st["wall_taken"])
    check("跳牌那张（庄家第 14 张）也被拿走", wallmodel.deal_plan(st["first_stack"])["jump_no"] in taken, True)
    check("普通摸牌的下一张不在已拿走里",
          wallmodel.next_live_no(st["next_no"], st["first_stack"]) in taken, False)

    # ★ op=draw / op=dora 已经删除：客户端不能自己摸牌 / 翻宝牌
    check("op=draw 已经删掉", api_cli.handle({"op": "draw", "seat": 0}).get("ok"), False)
    check("op=dora 已经删掉", api_cli.handle({"op": "dora", "seat": 0}).get("ok"), False)

    # 后面测的是牌山机制本身 → 直接调服务端的方法
    rid = r["round_id"]
    g = Game(api_cli.DB(api_cli.DB_PATH), rid)
    check("没有杠时不许翻宝牌", g.reveal_dora(), None)
    check("没有杠时不许摸岭上", g._draw_rinshan(0), None)

    # 连续摸 12 张（普通摸牌），看看编号是否连续、是否跳过王牌
    nos = []
    tiles = []
    for _ in range(12):
        no = wallmodel.next_live_no(g.next_no, g.wall_first_stack())
        tiles.append(g._draw_next(0))
        nos.append(no)
    g.save_flags()
    first = wallmodel.deal_plan(st["first_stack"])["next_no"]
    check("摸牌编号从 next_no 起连号", nos, [wallmodel.wrap_tile(first + i) for i in range(12)])
    check("摸牌拿到了牌（不是空）", all(bool(t) for t in tiles), True)
    check("摸牌后牌山又少了 12 张",
          len(g.state_for(0)["wall_taken"]), 53 + 12)

    # 翻宝牌：再翻 3 次（force=True 绕开「杠数」校验，这里测的是牌山位置）
    stacks = [g.state_for(0)["dora_stacks"][0]]
    for _ in range(3):
        stacks.append(g.reveal_dora(force=True)["stack"])
    check("翻了 4 张宝牌", len(g.state_for(0)["dora"]), 4)
    want_stacks = [wallmodel.dora_stack_no(st["first_stack"], i) for i in range(4)]
    check("4 张宝牌指示牌的墩号 = n-3 ~ n-6", stacks, want_stacks)
    check("再翻第 5 张没有了（宝牌最多 4 张）", g.reveal_dora(force=True), None)

    # 岭上摸牌：第 1 张 = 编号最大的那张
    want_rinshan = wallmodel.rinshan_tile_nos(st["first_stack"])
    no1 = want_rinshan[g.rinshan_used]
    g._draw_rinshan(0, force=True)
    check("岭上第一张 = 编号最大的那张", no1, want_rinshan[0])
    no2 = want_rinshan[g.rinshan_used]
    g._draw_rinshan(0, force=True)
    check("岭上第二张 = 编号第二大的那张", no2, want_rinshan[1])

    check("每家牌河 / 副露都返回了（渲染用）",
          len(r["state"]["all_discards"]), 4)
    check("配牌没有牌河", r["state"]["all_discards"], [[], [], [], []])

    api_cli._set_round_id(db, rid_old) if rid_old else None
    print()
    print(f"{PASS} 项通过 / {FAIL} 项失败")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
