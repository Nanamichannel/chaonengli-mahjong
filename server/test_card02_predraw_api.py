# -*- coding: utf-8 -*-
"""Card02 S1/S2 摸牌前询问 —— 走 api_cli.handle（模拟客户端真实请求）

验证：op=step 先挂换牌(S2)询问 → op=swap 关掉它 → 再 step 挂画板(S1) → op=board 关掉 → 正常摸牌。
跑法：cd server; python test_card02_predraw_api.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")

import api_cli  # noqa: E402
from game import Game  # noqa: E402
from tiles import parse_hand  # noqa: E402
import test_game as tg  # noqa: E402

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


H13 = parse_hand("123m456p789s") + ["1p", "1p", "5m", "5m"]


def setup(tag, seed, discs=12):
    db = tg.fresh_db(tag)
    rid, _m, _u = tg.new_round(db, seed=seed)
    tg.set_hand(db, rid, 0, H13)
    for s in (1, 2, 3):
        tg.set_hand(db, rid, s, H13)
    with db.tx():
        for i in range(int(discs)):
            db.conn.execute(
                "INSERT INTO round_actions(round_id, seq, seat, action, payload) "
                "VALUES(?, ?, 0, 'discard', '{}')", (rid, 500 + i))
        for i, (seat, tile) in enumerate([(1, "3p"), (2, "7m"), (3, "nan")]):
            db.conn.execute(
                "INSERT INTO round_discards(round_id, seq, seat, wall_seq, tile,"
                " is_tsumogiri, is_riichi_tile, face_down, called)"
                " VALUES(?,?,?,?,?,0,0,0,0)", (rid, i + 1, seat, 9000 + i, tile))
    g = Game(db, rid)
    g.round_phase = "play"
    g.granted = {0: {2}, 1: {16}, 2: {16}, 3: {16}}
    tg.to_draw(g, 0)
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",
                        f"_test_{tag}.db")
    return db, rid, path


def asks_of(res):
    st = res.get("state") or {}
    return [str(a.get("kind", "")) for a in (st.get("pending_asks") or [])]


def main() -> int:
    print("=" * 70)
    print(" 天才麻将少女 · Card02 摸牌前询问（走 api_cli.handle）")
    print("=" * 70)

    db, rid, path = setup("c02api", 711)
    print("\n① step：先挂「换牌」询问")
    r = api_cli.handle({"op": "step", "seat": 0, "round_id": rid}, path)
    evs = [str((e or {}).get("event", "")) for e in (r.get("events") or [])]
    check("回了 wait_pre", "wait_pre" in evs)
    check("客户端看到换牌询问", asks_of(r), ["c02s2"])
    check("状态里 c02s2_can", bool((r.get("state") or {}).get("c02s2_can")), True)
    check("还没摸牌", bool((r.get("state") or {}).get("drawn")), False)

    print("\n② op=swap：直接换牌（摸牌前）")
    r2 = api_cli.handle({"op": "swap", "seat": 0, "round_id": rid,
                         "hand_tiles": ["1p", "1p", "5m"], "river": [1, 2, 3]}, path)
    check("换牌成功", bool(r2.get("ok")), True)
    check("换到 3p/7m/nan", (r2.get("swap") or {}).get("got"), ["3p", "7m", "nan"])
    check("询问已关掉", asks_of(r2), [])
    check("只能摸切", bool((r2.get("state") or {}).get("must_tsumogiri")), True)

    print("\n③ step：接着挂「画板」询问")
    r3 = api_cli.handle({"op": "step", "seat": 0, "round_id": rid}, path)
    evs3 = [str((e or {}).get("event", "")) for e in (r3.get("events") or [])]
    check("又回了 wait_pre", "wait_pre" in evs3)
    check("这次是画板询问", asks_of(r3), ["c02s1"])

    print("\n④ op=board：画板当场发动 → 再 step 正常摸牌")
    r4 = api_cli.handle({"op": "board", "seat": 0, "round_id": rid,
                         "tiles": ["9p", "1s", "dong"]}, path)
    check("画板成功", bool(r4.get("ok")), True)
    check("询问已关掉", asks_of(r4), [])
    r5 = api_cli.handle({"op": "step", "seat": 0, "round_id": rid}, path)
    st5 = r5.get("state") or {}
    check("摸到牌了", bool(st5.get("drawn")), True)
    check("不再有摸牌前询问", asks_of(r5), [])
    check("手牌 14 张", len(st5.get("hand") or []), 14)

    print("\n⑤ 第五巡的局：只问画板")
    db6, rid6, path6 = setup("c02api2", 712, discs=5)
    r6 = api_cli.handle({"op": "step", "seat": 0, "round_id": rid6}, path6)
    check("问的是画板", asks_of(r6), ["c02s1"])

    print("\n" + "=" * 70)
    print(f" 通过 {PASS} 项，失败 {FAIL} 项")
    print("=" * 70)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
