# -*- coding: utf-8 -*-
"""协战卡遮罩（服务端）自测。

协战卡（order 第 5 张）只活两个风场 → 玩家可以手动遮罩：遮罩期间这张卡的
一切技能判定都不成立（owns_card / cards_in_order 都剔掉）。

跑法：cd N:\\apps\\tianma\\server; python test_support_mute.py
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
import skills                                       # noqa: E402
import test_card30 as t30                           # noqa: E402
import test_game as tg                              # noqa: E402

PASS = FAIL = 0


def check(name, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  got {got!r} want {want!r}")


def setup(tag, order=(37, 6, 7, 8, 39)):
    """0 号位：主战 37（第 1 个风场）、协战 39（两风场寿命）。"""
    db, rid = t30.setup(tag, card=int(order[0]), mains=list(order))
    with db.tx():
        # t30.setup 只给 0 号位写了 order；这里显式写全，协战卡 = order[4]
        import json
        row = db.conn.execute("SELECT value FROM meta WHERE key='lobby_state'").fetchone()
        lobby = json.loads(row[0])
        seats = lobby.get("seats") or []
        while len(seats) < 4:
            seats.append({})
        for s in range(4):
            o = list(order) if s == 0 else [order[0], 6, 7, 8, order[4]]
            seats[s]["order"] = o
        lobby["seats"] = seats
        db.conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('lobby_state',?)",
                        (json.dumps(lobby, ensure_ascii=False),))
        db.conn.execute("DELETE FROM meta WHERE key='support_mute'")
    g = Game(db, rid)
    g.round_phase = "play"
    g.phase = "discard"
    g.turn = 0
    g.deal_wait = set()
    g.deal_used = set()
    g.save_flags()
    return db, rid


def main() -> int:
    print("=" * 78)
    print(" 协战人物卡遮罩")
    print("=" * 78)

    db, rid = setup("supmute_a")
    g = Game(db, rid)
    print("\n① 卡序")
    check("0 号位协战卡 = 39", skills.support_card(db, 0), 39)
    check("一开始没遮罩", skills.support_muted(db, g, 0), 0)
    check("39 号卡算持有", skills.owns_card(db, g, 0, 39, strict=True), True)
    check("卡序里有 39", 39 in skills.cards_in_order(db, g, 0), True)
    _fake_before = bool(g.c39s2_fake(0))

    print("\n② 打开遮罩 → 这张卡的一切判定都不成立")
    out = api_cli.handle({"op": "support_mute", "seat": 0, "target": 0, "on": True,
                          "round_id": rid}, db_path=db.path)
    check("op ok", bool(out.get("ok", False)), True)
    g2 = Game(db, rid)
    check("记下来了", skills.support_muted(db, g2, 0), 39)
    check("39 号卡不再算持有", skills.owns_card(db, g2, 0, 39, strict=True), False)
    check("卡序里剔掉了 39", 39 in skills.cards_in_order(db, g2, 0), False)
    check("主战卡 37 照旧算持有", skills.owns_card(db, g2, 0, 37, strict=True), True)
    check("主战卡还在卡序里", 37 in skills.cards_in_order(db, g2, 0), True)
    check("state 里下发 support_mute",
          (g2.state_for(0).get("support_mute") or {}).get("0"), 39)

    print("\n③ 被动技能真的不动了（39S2 无视 = 门清当立直）")
    check("遮罩前：39S2 视为立直", _fake_before, True)
    check("遮罩后：39S2 不再生效", bool(g2.c39s2_fake(0)), False)

    print("\n④ 再关掉遮罩 → 恢复")
    api_cli.handle({"op": "support_mute", "seat": 0, "target": 0, "on": False,
                    "round_id": rid}, db_path=db.path)
    g3 = Game(db, rid)
    check("没遮罩了", skills.support_muted(db, g3, 0), 0)
    check("39 号卡又能用", skills.owns_card(db, g3, 0, 39, strict=True), True)
    check("卡序里回来了", 39 in skills.cards_in_order(db, g3, 0), True)
    check("state 里清空", (g3.state_for(0).get("support_mute") or {}), {})

    print("\n⑤ 遮罩跟着「卡」走：协战卡换掉 → 旧遮罩自动失效")
    api_cli.handle({"op": "support_mute", "seat": 0, "target": 0, "on": True,
                    "round_id": rid}, db_path=db.path)
    import json
    with db.tx():
        row = db.conn.execute("SELECT value FROM meta WHERE key='lobby_state'").fetchone()
        lobby = json.loads(row[0])
        seats = lobby["seats"]
        seats[0]["order"] = [37, 6, 7, 8, 40]        # 协战卡换成 40
        lobby["seats"] = seats
        db.conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('lobby_state',?)",
                        (json.dumps(lobby, ensure_ascii=False),))
    g4 = Game(db, rid)
    check("新协战卡 40 没被遮", skills.support_muted(db, g4, 0), 0)
    check("40 号卡算持有", skills.owns_card(db, g4, 0, 40, strict=True), True)
    check("旧遮罩记的是 39", (skills.support_mute_map(db) or {}).get(0), 39)

    print("\n⑥ 只能遮自己（遮不了别家）")
    out6 = api_cli.handle({"op": "support_mute", "seat": 0, "target": 1, "on": True,
                           "round_id": rid}, db_path=db.path)
    check("被拒", bool(out6.get("ok", True)), False)
    check("错误说明「只能遮罩自己的卡」", "自己" in str(out6.get("error", "")), True)
    g5 = Game(db, rid)
    check("1 号位没被遮", skills.support_muted(db, g5, 1), 0)
    check("0 号位也没被遮", skills.support_muted(db, g5, 0), 0)

    print("\n⑦ op 登记 / 不查看破")
    check("OPS 里有 support_mute", "support_mute" in api_cli.OPS, True)
    check("不问看破", "support_mute" in api_cli._NO_GATE_OPS, True)
    g6 = Game(db, rid)
    check("看破闸门直接放过", g6.kangpo_gate(0, 0, 0, op="support_mute", payload={}), False)

    print("\n" + "=" * 78)
    print(f" 通过 {PASS} / 失败 {FAIL}")
    print("=" * 78)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
