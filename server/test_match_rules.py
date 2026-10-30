# -*- coding: utf-8 -*-
"""「几个规则」自测：立直供托 / 流局连庄 / 东风战终局。

规则都在服务端，这个文件就钉住它们：

  · 立直宣言牌打出去 → rounds.riichi_sticks +1、立直的人当场 -1000
  · 和牌              → 场上所有供托全归赢家（每根 1000），供托立刻清零
  · 荒牌流局          → 供托留在桌上，下一局继续挂着（op=next 带过去）、本场 +1
  · 荒牌流局 + 亲家听牌 → 连庄（亲家和局数都不动）
  · 荒牌流局 + 亲家没听 → 亲家下移一位、局数 +1
  · 途中流局（九种九牌）→ 供托退还本人；本场不加、亲家不变、局数不变（这一局重来）
  · state 里带着 riichi_sticks（客户端要显示）

跑法： python test_match_rules.py
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
from game import Game  # noqa: E402

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


# 一副「123m456m789m 11p23p 9s」：打掉 9s 就听 1p/4p（立直用）
RIICHI_14 = ["1m", "2m", "3m", "4m", "5m", "6m", "7m", "8m", "9m",
             "1p", "1p", "2p", "3p", "9s"]
# 自摸和牌的那 14 张：上面那副摸到 1p
WIN_14 = ["1m", "2m", "3m", "4m", "5m", "6m", "7m", "8m", "9m",
          "1p", "1p", "2p", "3p", "1p"]
# 绝对不听的手牌（荒牌流局里摆「亲家没听」用）
NOTEN_13 = ["1m", "4m", "7m", "1p", "4p", "7p", "1s", "4s", "7s",
            "dong", "nan", "xi", "bei"]


def main() -> int:
    print("=" * 74)
    print(" 天才麻将少女 · 立直供托 / 流局连庄 / 东风战终局")
    print("=" * 74)

    db = tg.fresh_db("match_rules")
    _OPEN_DBS.append(db)
    rid, match, _uids = tg.new_round(db, seed=7)      # 直接摆好一局（配牌已由服务端做完）
    api_cli._set_round_id(db, rid)                    # 让 op=next 认这一局

    def call(req):
        return api_cli.handle(req, db.path)

    def sticks(r):
        return int(db._one("SELECT riichi_sticks FROM rounds WHERE round_id=?", (r,)) or 0)

    def cond(r):
        row = db._row("SELECT wind, number, honba, dealer_seat FROM rounds WHERE round_id=?", (r,))
        return (row["wind"], row["number"], row["honba"], row["dealer_seat"])

    def put_discard_phase(g, seat, tiles, drawn=None):
        """把局面摆成「轮到 seat 打牌」，手牌换成 tiles。"""
        tg.set_hand(db, g.round_id, seat, tiles, drawn=drawn)
        g.turn = seat
        g.phase = "discard"
        g.save_flags()
        return g

    def next_round(seat=0):
        """按「下一局」→ 顺手把配牌推完（op_start 只管开，配牌是 deal_step 一步一步做的）。"""
        res = call({"op": "next", "seat": seat})
        gg = Game(db, res["round_id"])
        while not gg.deal_done():
            gg.deal_step()
        return res

    # ── ① 立直宣言牌 → 供托 +1、本人 -1000、state 能看到 ────────────────
    print("\n① 立直供托")
    g = Game(db, rid)
    put_discard_phase(g, 0, RIICHI_14)
    check("立直能打的是 1p / 9s（打 1p 变单骑 9s）", sorted(g.riichi_discards(0)), ["1p", "9s"])
    before = g.scores()[0]
    g.act(0, "riichi", tile="9s")
    check("rounds.riichi_sticks 变成 1", sticks(rid), 1)
    check("立直的人当场 -1000", g.scores()[0], before - 1000)
    check("别人还没立直", g.is_riichi(1), False)
    check("state 里带着供托数", g.state_for(0).get("riichi_sticks"), 1)
    check("state 里带着供托数（别家视角也一样）", g.state_for(2).get("riichi_sticks"), 1)

    # ── ② 和牌 → 供托全归赢家、清零 ───────────────────────────────────
    print("\n② 和牌收供托")
    g = Game(db, rid)
    put_discard_phase(g, 0, WIN_14, drawn="1p")
    base = g.scores()[0]
    ev = g.act(0, "tsumo")
    paid = ev["points"]["total"]
    names = [y["name"] if isinstance(y, dict) else y for y in ev["yaku"]]
    check("和了（有立直系役种）", any(n in names for n in ("立直", "双立直")), True)
    check("和牌的人拿到点数 + 那 1 根供托", g.scores()[0], base + paid + 1000)
    check("供托被收走、清零", sticks(rid), 0)
    check("和牌之后这一局结束", g.phase, "ended")

    # ── ③ 荒牌流局 → 供托留到下一局、本场 +1 ──────────────────────────
    print("\n③ 荒牌流局：供托跟着下一局走")
    r2 = next_round()
    rid2 = r2["round_id"]
    check("开了新的一局", r2["created"], True)
    check("亲家赢了 → 连庄、本场 +1", cond(rid2), ("dong", 1, 1, 0))
    g2 = Game(db, rid2)
    put_discard_phase(g2, 1, RIICHI_14)
    g2.act(1, "riichi", tile="9s")
    check("1 号位立直 → 供托 1 根", sticks(rid2), 1)
    g2._ryuukyoku("exhaustive")                        # 荒牌流局
    check("荒牌流局后供托还挂在桌上", sticks(rid2), 1)
    check("这一局记成荒牌流局", db._one("SELECT result FROM rounds WHERE round_id=?", (rid2,)),
          "ryuukyoku")
    r3 = next_round()
    rid3 = r3["round_id"]
    check("供托带到下一局", sticks(rid3), 1)
    check("荒牌流局本场 +1（1 → 2）", cond(rid3)[2], 2)
    check("下一局的 state 里也带着供托数", r3["state"].get("riichi_sticks"), 1)

    # ── ④ 途中流局（九种九牌）→ 供托退还本人、本场/亲家/局数都不动 ────
    print("\n④ 途中流局：供托退回本人、这一局重来")
    g3 = Game(db, rid3)
    put_discard_phase(g3, 2, RIICHI_14)
    before2 = g3.scores()[2]
    g3.act(2, "riichi", tile="9s")
    check("2 号位立直 → 供托 2 根", sticks(rid3), 2)
    g3._ryuukyoku("kyuushu")                           # 九种九牌（途中流局）
    check("九种九牌退还本人 1000", g3.scores()[2], before2)
    check("另一根（上一局带来的）还挂着", sticks(rid3), 1)
    check("这一局记成 kyuushu（不是 ryuukyoku）",
          db._one("SELECT result FROM rounds WHERE round_id=?", (rid3,)), "kyuushu")
    r4 = next_round()
    rid4 = r4["round_id"]
    check("途中流局：亲家不变", cond(rid4)[3], cond(rid3)[3])
    check("途中流局：局数不变", cond(rid4)[1], cond(rid3)[1])
    check("途中流局：本场不加", cond(rid4)[2], cond(rid3)[2])
    check("途中流局后供托照旧带过去", sticks(rid4), 1)

    # ── ⑤ 荒牌流局 + 亲家听牌 → 连庄 ─────────────────────────────────
    print("\n⑤ 荒牌流局但亲家听牌 → 连庄")
    dealer = cond(rid4)[3]
    g4 = Game(db, rid4)
    tg.set_hand(db, rid4, dealer, ["1m", "2m", "3m", "4m", "5m", "6m", "7m", "8m", "9m",
                                  "1p", "1p", "2p", "3p"])       # 13 张听 1p/4p
    check("亲家确实听牌了", len(g4.waits(dealer)) > 0, True)
    g4._ryuukyoku("exhaustive")
    r5 = next_round()
    rid5 = r5["round_id"]
    check("亲家还是原来那位（连庄）", cond(rid5)[3], dealer)
    check("局数不动", cond(rid5)[1], cond(rid4)[1])
    check("本场 +1", cond(rid5)[2], cond(rid4)[2] + 1)
    check("供托还是 1 根", sticks(rid5), 1)

    # ── ⑥ 荒牌流局 + 亲家没听 → 亲家下移、局数 +1 ────────────────────
    print("\n⑥ 荒牌流局且亲家没听 → 亲家下移")
    dealer = cond(rid5)[3]
    g5 = Game(db, rid5)
    tg.set_hand(db, rid5, dealer, NOTEN_13)
    check("亲家确实没听", g5.waits(dealer), [])
    g5._ryuukyoku("exhaustive")
    r6 = next_round()
    rid6 = r6["round_id"]
    check("亲家下移一位", cond(rid6)[3], (dealer + 1) % 4)
    check("局数 +1", cond(rid6)[1], cond(rid5)[1] + 1)
    check("供托还在（荒牌流局不清供托）", sticks(rid6), 1)

    print()
    print(f"{PASS} 项通过 / {FAIL} 项失败")
    for d in _OPEN_DBS:
        try:
            d.close()
        except Exception:
            pass
    data_dir = os.path.dirname(os.path.abspath(__file__))
    for f in os.listdir(os.path.join(data_dir, "data")):
        if f.startswith("_test_match_rules"):
            try:
                os.remove(os.path.join(data_dir, "data", f))
            except OSError:
                pass
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
