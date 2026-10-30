# -*- coding: utf-8 -*-
"""「下一局」的推进规则自测（op="next"）。

  · 上一局没打完 + 没 force → 什么都不做（联机时客户端只管等/渲染）
  · 上一局没打完 + force    → 这一局重开（条件不变）
  · 亲家赢 → 连庄：同一个亲家、本场 +1
  · 别家赢 → 亲家下移一位、本场归 0、局数 +1
  · 荒牌流局 → 本场 +1；亲家听牌就连庄，没听才亲家下移、局数 +1
  · 途中流局 → 本场不加、亲家不变、局数不变（这一局重来）
  · 局数超过 4 → 东风战整场结束；半庄推进场风（东→南）、局数回到 1
  · 分数跨局保留（match_seats.score 不清零）

跑法： python test_next_round.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import api_cli  # noqa: E402
import test_game as tg  # noqa: E402

PASS = FAIL = 0
_OPEN_DBS: list = []


def check(name, got, want):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  got {got!r} want {want!r}")


def main() -> int:
    print("=" * 74)
    print(" 天才麻将少女 · 下一局怎么开（op=next）")
    print("=" * 74)

    db = tg.fresh_db("next_round")
    _OPEN_DBS.append(db)

    def call(req):
        return api_cli.handle(req, db.path)

    def round_cond(rid):
        r = db._row("SELECT wind, number, honba, dealer_seat, status, result FROM rounds "
                    "WHERE round_id=?", (rid,))
        return (r["wind"], r["number"], r["honba"], r["dealer_seat"])

    # ── ① 还没有局 → 开一局（东1局0本场，0 号位坐庄）──────────────────
    print("\n① 还没有局")
    r1 = call({"op": "next", "seat": 0})
    rid1 = r1["round_id"]
    check("开了一局", r1["created"], True)
    check("东 1 局、0 本场、0 号位坐庄", round_cond(rid1), ("dong", 1, 0, 0))

    # ── ② 这一局还在打：不带 force 就别动它 ──────────────────────────
    print("\n② 还在打的时候")
    r2 = call({"op": "next", "seat": 0})
    check("不带 force → 还是原来这一局", r2["round_id"], rid1)
    check("不带 force → 没开新局", r2["created"], False)

    # ── ③ 带 force → 这一局重开（条件不变）────────────────────────────
    print("\n③ 强制重开这一局")
    r3 = call({"op": "next", "seat": 0, "force": True})
    check("换了一局（新的 round_id）", r3["round_id"] != rid1, True)
    check("条件不变（东 1 局 0 本场 庄 0）", round_cond(r3["round_id"]), ("dong", 1, 0, 0))

    # ── ④ 亲家赢 → 连庄，本场 +1 ─────────────────────────────────────
    print("\n④ 亲家赢了（连庄）")
    rid = r3["round_id"]
    db.finish_round(rid, "tsumo", winner_seat=0, points=2000)
    r4 = call({"op": "next", "seat": 0})
    check("还是同一个亲家（连庄）", round_cond(r4["round_id"])[3], 0)
    check("本场 +1", round_cond(r4["round_id"])[2], 1)
    check("局数不变", round_cond(r4["round_id"])[1], 1)

    # ── ⑤ 别家赢 → 亲家下移一位、本场归 0、局数 +1 ────────────────────
    print("\n⑤ 别家赢了")
    rid = r4["round_id"]
    db.finish_round(rid, "ron", winner_seat=2, loser_seat=0, points=1000)
    r5 = call({"op": "next", "seat": 0})
    check("亲家下移一位（0 → 1）", round_cond(r5["round_id"])[3], 1)
    check("本场归 0", round_cond(r5["round_id"])[2], 0)
    check("局数 +1（1 → 2）", round_cond(r5["round_id"])[1], 2)

    # ── ⑥ 荒牌流局 → 本场 +1；亲家没听 → 亲家下移 ──────────────────────
    print("\n⑥ 荒牌流局（亲家没听）")
    rid = r5["round_id"]
    # 把亲家（1 号位）的手牌摆成「绝对不听」：全散张，省得随机配牌碰巧听牌
    tg.set_hand(db, rid, 1, ["1m", "4m", "7m", "1p", "4p", "7p",
                             "1s", "4s", "7s", "dong", "nan", "xi", "bei"])
    db.finish_round(rid, "ryuukyoku")            # 荒牌流局（牌山摸完）
    r6 = call({"op": "next", "seat": 0})
    check("亲家下移一位（1 → 2）", round_cond(r6["round_id"])[3], 2)
    check("本场 +1", round_cond(r6["round_id"])[2], 1)

    # ── ⑦ 东 4 局打完：东风战就到这儿了 ───────────────────────────────
    print("\n⑦ 东 4 局打完之后（东风战 → 整场结束）")
    rid = r6["round_id"]
    with db.tx():                       # 直接摆成「东 4 局」
        db.conn.execute("UPDATE rooms SET mode='east_only'")
        db.conn.execute("UPDATE rounds SET number=4, honba=0, dealer_seat=3 WHERE round_id=?",
                        (rid,))
    db.finish_round(rid, "ron", winner_seat=0, loser_seat=3, points=1000)
    r7 = call({"op": "next", "seat": 0})
    check("东风战打满 → 整场结束", r7.get("match_finished"), True)
    check("没有开新的一局（round_id 还是刚才那局）", r7["round_id"], rid)
    mstatus = db._one("SELECT status FROM matches WHERE match_id="
                      "(SELECT match_id FROM rounds WHERE round_id=?)", (rid,))
    check("整场状态不再是 playing", mstatus != "playing", True)

    # ── ⑦-b 半庄的话：东 4 打完进南风、局数回 1 ───────────────────────
    print("\n⑦-b 半庄（hanchan）：东 4 打完进南风")
    db2 = tg.fresh_db("next_round_hanchan")
    _OPEN_DBS.append(db2)
    r = api_cli.handle({"op": "next", "seat": 0}, db2.path)
    rid2 = r["round_id"]
    with db2.tx():                      # 先有房间，再把它改成半庄
        db2.conn.execute("UPDATE rooms SET mode='hanchan'")
        db2.conn.execute("UPDATE rounds SET number=4, honba=0, dealer_seat=3 WHERE round_id=?",
                         (rid2,))
    db2.finish_round(rid2, "ron", winner_seat=0, loser_seat=3, points=1000)
    r = api_cli.handle({"op": "next", "seat": 0}, db2.path)
    rr = db2._row("SELECT wind, number, dealer_seat FROM rounds WHERE round_id=?",
                  (r["round_id"],))
    check("场风推进到南", rr["wind"], "nan")
    check("局数回到 1", rr["number"], 1)
    check("亲家按「下移一位」算（3 → 0）", rr["dealer_seat"], 0)

    # ── ⑧ 分数跨局保留 ─────────────────────────────────────────────
    print("\n⑧ 分数跨局")
    row = db._row("SELECT match_id FROM rounds WHERE round_id=?", (r7["round_id"],))
    scores = {s["seat"]: s["score"] for s in db._rows(
        "SELECT seat, score FROM match_seats WHERE match_id=? ORDER BY seat", (row["match_id"],))}
    check("0 号位因为④自摸了 2000、⑤又荣和 1000 → 分数不是初始的 35000",
          scores[0] != 35000, True)
    print("         当前分数:", scores)
    check("每个人的分数都记在 match_seats（跨局不清零）", len(scores), 4)

    print()
    print(f"{PASS} 项通过 / {FAIL} 项失败")
    for d in _OPEN_DBS:
        try:
            d.close()
        except Exception:
            pass
    data_dir = os.path.dirname(os.path.abspath(__file__))
    for f in os.listdir(os.path.join(data_dir, "data")):
        if f.startswith("_test_next_round"):
            try:
                os.remove(os.path.join(data_dir, "data", f))
            except OSError:
                pass
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
