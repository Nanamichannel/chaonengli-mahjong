# -*- coding: utf-8 -*-
"""Card45 S1【神境】自测。

跑法：cd N:\\apps\\tianma\\server; python test_card45.py
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
import skills                                      # noqa: E402
import test_card30 as t30                          # noqa: E402
import test_game as tg                             # noqa: E402
from tiles import parse_hand                       # noqa: E402

PASS = FAIL = 0
H13 = "123m456m789m23p5s5s"                        # 13 张（门清，能碰 5s）
RIVER0 = ["1z", "2z", "3z", "4z", "1m", "2m", "3m", "4m", "6p", "7p", "8p", "9p"]


def check(name, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  got {got!r} want {want!r}")


def add_river(db, rid, seq, seat, tile, wseq, down=False):
    with db.tx():
        db.conn.execute(
            "INSERT INTO round_discards(round_id, seq, seat, wall_seq, tile,"
            " is_tsumogiri, is_riichi_tile, face_down, called)"
            " VALUES(?,?,?,?,?,1,0,?,0)", (rid, seq, seat, wseq, tile, 1 if down else 0))


def setup(tag, hand=H13, river_n=12, card=45, meld=False):
    db, rid = t30.setup(tag, card=int(card))
    tg.set_hand(db, rid, 0, parse_hand(hand))
    with db.tx():
        db.conn.execute("DELETE FROM round_dora WHERE round_id=?", (rid,))
        db.conn.execute("DELETE FROM round_discards WHERE round_id=?", (rid,))
        db.conn.execute("DELETE FROM round_melds WHERE round_id=?", (rid,))
        db.conn.execute("DELETE FROM round_riichi WHERE round_id=?", (rid,))
    for i in range(int(river_n)):
        add_river(db, rid, 100 + i, 0, RIVER0[i], 900 + i)
    # 别家牌河也放几张（神境能挑所有人打出的牌）
    add_river(db, rid, 200, 1, "1s", 950)
    add_river(db, rid, 201, 2, "2s", 951)
    if meld:
        with db.tx():
            db.conn.execute(
                "INSERT INTO round_melds(round_id,meld_id,seat,kind,called_tile,from_seat,"
                "tiles_json,rot_index,seqs_json) VALUES(?,0,0,'pon','9s',1,?,0,'[]')",
                (rid, '["9s","9s","9s"]'))
    g = Game(db, rid)
    g.granted = {0: ({45} if int(card) == 45 else set())}
    g.round_phase = "play"
    g.phase = "draw"
    g.turn = 0
    g.deal_wait = set()
    g.deal_used = set()
    g.save_flags()
    return db, rid


def main() -> int:
    print("=" * 78)
    print(" Card45 S1【神境】")
    print("=" * 78)

    print("\n① 注册 / 时机")
    check("名字", skills.info(45, 1).get("name"), "神境")
    check("时机 = 摸牌前", skills.timing(45, 1), "draw")

    print("\n② 发动条件")
    dbA, ridA = setup("c45a", river_n=11)
    check("牌河只有 11 张 → 不能发动", Game(dbA, ridA).c45s1_can(0), False)

    dbB, ridB = setup("c45b", meld=True)
    check("有副露 → 不能发动", Game(dbB, ridB).c45s1_can(0), False)

    dbC, ridC = setup("c45c", card=6)
    gC = Game(dbC, ridC)
    check("不持卡 → 不能发动", gC.c45s1_can(0), False)

    db, rid = setup("c45d")
    g = Game(db, rid)
    check("牌河 12 张 + 门清 13 张 + 持卡 → 能发动", g.c45s1_can(0), True)
    check("不是我的回合 → 不能", g.c45s1_can(1), False)
    check("摸牌前会问一句（pre_draw_pending）", g.pre_draw_pending(0), True)
    check("可选弃牌：自己 12 张 + 别家 2 张", len(g.c45s1_rivers(0)), 14)
    st = g.state_for(0)
    check("state.c45.can", bool((st.get("c45") or {}).get("can", False)), True)

    print("\n③ 挑 13 张：手牌 13 张换掉、牌河位置补暗置牌")
    picks = ["123m", "456m", "789m", "23p", "5s5s"]
    hand_picks = ["1m", "2m", "3m", "5s", "5s"]          # 手牌里留这 5 张
    seqs = [100, 101, 200, 201, 102, 103, 104, 105]      # 牌河拿这 8 张
    out = g.c45s1_apply(0, hand_picks, seqs)
    check("回包 got = 牌河那 8 张", out.get("got"), ["1z", "2z", "1s", "2s",
                                                   "3z", "4z", "1m", "2m"])
    g2 = Game(db, rid)
    hand = [str(t) for t in g2.hand(0)]
    check("新手牌 13 张", len(hand), 13)
    check("留下了选中的 5 张",
          sorted([t for t in hand if t in hand_picks]).count("5s"), 2)
    check("牌河那 8 张进了手牌",
          all(t in hand for t in ("1z", "2z", "3z", "4z", "1s", "2s")), True)
    check("被拿走的手牌数 = 被拿走的牌河数（8）", 13 - len(hand_picks), len(seqs))

    rows = {int(r["seq"]): r for r in db._rows(
        "SELECT seq, tile, face_down FROM round_discards WHERE round_id=?", (rid,))}
    filled = [rows[int(sq)] for sq in seqs]
    check("拿走的牌河位置全变成暗置", all(int(r["face_down"]) == 1 for r in filled), True)
    expect_left = sorted(["4m", "5m", "6m", "7m", "8m", "9m", "2p", "3p"])
    check("填回去的就是被放弃的手牌",
          sorted([str(r["tile"]) for r in filled]), expect_left)

    print("\n③b 全选牌河：0 张手牌 + 13 张牌河")
    dbE, ridE = setup("c45g")
    gE = Game(dbE, ridE)
    seqs13 = list(gE.c45s1_rivers(0))[:13]
    check("可选牌河够 13 张", len(seqs13), 13)
    out3 = gE.c45s1_apply(0, [], seqs13)
    check("回包 got = 13 张", len(out3.get("got") or []), 13)
    hE = [str(t) for t in Game(dbE, ridE).hand(0)]
    check("新手牌 13 张", len(hE), 13)
    check("13 张全是牌河拿来的",
          sorted(hE) == sorted(out3.get("got") or []), True)

    print("\n④ 打开之后：不能手切 / 不能立直 / 只能自摸")
    check("落库：本局常开", 0 in g2.c45s1_on, True)
    check("只能摸切", 0 in g2.must_tsumogiri, True)
    check("一次性技能记上了", g2.skill_used(0, 45, 1), True)
    check("不能再发动（一次）", g2.c45s1_can(0), False)
    check("不能立直", g2.can_riichi(0), False)
    check("荣和链路堵死", g2._win_gate(0, "5s", False), False)
    check("自摸照旧放行", g2._win_gate(0, None, True), True)

    print("\n⑤ 鸣牌窗口：神境的人不能吃碰杠")
    g3 = Game(db, rid)
    g3.phase = "discard"
    g3.turn = 3
    g3._open_claim_window(300, "5s", 3)          # 3 号位打 5s：本来 0 号位能碰
    opts = (g3.pending or {}).get("options") or {}
    check("0 号位没有选项", 0 in opts, False)

    print("\n⑥ 得点上限：闲家 32000 / 庄家 48000（压过 ×2 ×3）")
    dbE, ridE = setup("c45e")
    gE = Game(dbE, ridE)
    d1 = {0: 40000, 1: -20000, 2: -10000, 3: -10000}
    check("没开神境 → 不动", gE._c45s1_cap(0, dict(d1)), None)
    gE.c45s1_on = {1}
    d2 = {1: 40000, 0: -20000, 2: -10000, 3: -10000}
    cap = gE._c45s1_cap(1, d2)
    check("闲家上限 32000", cap, 32000)
    check("赢家拿到 32000", int(d2[1]), 32000)
    check("零和", sum(int(v) for v in d2.values()), 0)
    check("付点按比例缩", int(d2[0]), -16000)

    gE.c45s1_on = {int(gE.dealer)}
    dw = {int(gE.dealer): 60000}
    for s in range(4):
        if s != int(gE.dealer):
            dw[s] = -20000
    check("庄家上限 48000", gE._c45s1_cap(int(gE.dealer), dw), 48000)
    check("庄家拿到 48000", int(dw[int(gE.dealer)]), 48000)
    check("零和", sum(int(v) for v in dw.values()), 0)

    gE.c45s1_on = {1}
    d3 = {1: 8000, 0: -4000, 2: -2000, 3: -2000}
    check("没超上限 → 不动", gE._c45s1_cap(1, d3), None)
    check("deltas 不变", int(d3[1]), 8000)

    print("\n⑦ 整局跑一遍：结算里能看到「神境（得点上限 …）」")
    dbF, ridF = setup("c45f")
    gF = Game(dbF, ridF)
    tg.set_hand(dbF, ridF, 0, parse_hand("123m456m789m234p5s5s"), drawn="5s")
    gF = Game(dbF, ridF)
    gF.phase = "discard"
    gF.turn = 0
    gF.c45s1_on = {0}
    gF.C45S1_CAP_DEALER = 1000                   # 故意压低上限，验证收付链最后一道
    gF.C45S1_CAP_NONDEALER = 1000
    gF.save_flags()
    gF = Game(dbF, ridF)
    gF.C45S1_CAP_DEALER = 1000
    gF.C45S1_CAP_NONDEALER = 1000
    gF.act(0, "tsumo")
    res = (Game(dbF, ridF).result or {})
    check("记了上限", int(res.get("c45s1", 0)), 1000)
    # 付点按比例缩到百位（向下取整），所以赢家拿到的会「不超过上限、略少一点」
    check("点数不超过上限", int(res.get("points", 0)) <= 1000, True)
    check("点数还是正数", int(res.get("points", 0)) > 0, True)
    check("役种里带神境",
          any("神境" in str(y.get("name", "")) for y in (res.get("yaku") or [])), True)
    dd = {int(k): int(v) for k, v in (res.get("deltas") or {}).items()}
    check("收付零和", sum(dd.values()), 0)

    print("\n" + "=" * 78)
    print(f" 合计：{PASS + FAIL} 断言，{FAIL} 失败")
    print("=" * 78)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
