# -*- coding: utf-8 -*-
"""友引段1（22S2）修复回归：

① 手里一个面子都没有时不许进 youyin_meld（以前：面板不可取消 + 服务端拒一切组合 = 全桌卡死）
② armed 后没有真副露（pass / 别人鸣走）→ claim 结算时清掉「开启状态」
③ 摊面子阶段有超时兜底（不替玩家自动摊第一组，直接收尾）
④ 明杠 + 没面子：不进摊面子，照样补岭上 + 翻宝（且只补一张）

跑法：cd N:\apps\tianma\server; python test_youyin_meld_fix.py
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

from game import Game, RuleError          # noqa: E402
import test_game as tg                    # noqa: E402
from tiles import parse_hand              # noqa: E402

PASS = FAIL = 0


def check(name, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  got {got!r} want {want!r}")


def add_river(db, rid, seq, seat, tile, wseq):
    with db.tx():
        db.conn.execute(
            "INSERT OR REPLACE INTO round_discards(round_id, seq, seat, wall_seq, tile,"
            " is_tsumogiri, is_riichi_tile, face_down, called)"
            " VALUES(?,?,?,?,?,1,0,0,0)", (rid, seq, seat, wseq, tile))


def setup(tag, hand13, action="chi", choices=None, tile="2m"):
    """摆成「1 号位打了 tile，0 号位有吃/明杠」的鸣牌窗口"""
    db = tg.fresh_db(tag)
    rid, _m, _u = tg.new_round(db, seed=17)
    tg.set_hand(db, rid, 0, hand13)
    tg.set_hand(db, rid, 1, parse_hand("1m4m7m1p4p7p1s4s7s1z2z3z"))
    tg.set_hand(db, rid, 2, parse_hand("2m5m8m2p5p8p2s5s8s2z3z4z"))
    tg.set_hand(db, rid, 3, parse_hand("3m6m9m3p6p9p3s6s9s1z2z3z"))
    add_river(db, rid, 500, 1, tile, 9500)
    g = Game(db, rid)
    g.granted = {0: {22}}
    g.round_phase = "play"
    g.turn, g.phase = 1, "claim"
    opts = {"action": action, "choices": choices if choices is not None else [["3m", "4m"]]}
    g.pending = {"discard_seq": 500, "tile": tile, "from": 1,
                 "options": {0: [opts]}, "answers": {}}
    g.save_flags()
    return db, rid, Game(db, rid)


def main() -> int:
    print("=" * 74)
    print(" 友引段1：没面子不许进摊面子 / claim 结算清 armed / 超时兜底")
    print("=" * 74)

    # ── ① 吃之后手里没有面子：不许进 youyin_meld ──────────────────────────
    print("\n① 吃 2m（1m5m5m7m9m1p4p7p2s5s8s）→ 一个面子都没有")
    hand13 = parse_hand("1m5m5m7m9m1p4p7p2s5s8s") + ["3m", "4m"]
    db, rid, g = setup("ym_nomianzi", hand13)
    check("鸣牌窗口里能点友引", g.youyin_meld_can(0))
    g.youyin_meld_arm(0)
    g.act(0, "chi", tiles=["3m", "4m"])
    g = Game(db, rid)
    check("没有停在 youyin_meld", g.phase, "discard")
    check("没有 offer 残留", g.youyin_meld_offer, None)
    check("armed 清掉了", g.youyin_meld_armed, -1)
    check("记成「本小局用过了」", 0 in g.youyin_meld_done)
    check("轮到他正常打牌", g.turn, 0)
    check("prompt_state 不再锁桌", g.prompt_state(), None)
    check("能打牌（legal 里有 discard）",
          any(a.get("action") == "discard" for a in g.legal_actions(0)))

    # ── ② 有面子：仍然进摊面子，并且挂了截止时间 ─────────────────────────
    print("\n② 吃 2m（1m2m3m5p6p7p2s3s4s9s9s + 3m4m）→ 有面子")
    hand13b = parse_hand("1m2m3m5p6p7p2s3s4s9s9s") + ["3m", "4m"]
    db2, rid2, g2 = setup("ym_hasmianzi", hand13b)
    g2.youyin_meld_arm(0)
    g2.act(0, "chi", tiles=["3m", "4m"])
    g2 = Game(db2, rid2)
    check("进入摊面子阶段", g2.phase, "youyin_meld")
    check("offer 挂在自己身上", (g2.youyin_meld_offer or {}).get("seat"), 0)
    check("记了截止时间", float(g2.youyin_meld_deadline) > time.time())
    check("现在还没超时", g2.youyin_meld_timeout(), False)
    # 回归：一次摊一组、循环问；摊到手里没面子才收尾
    r = g2.youyin_meld_pick(0, ["1m", "2m", "3m"])
    check("摊了 1 组", r.get("n"), 1)
    check("手里还有面子 → 继续问", r.get("more"), True)
    g2 = Game(db2, rid2)
    check("还在摊面子阶段", g2.phase, "youyin_meld")
    r = g2.youyin_meld_pick(0, ["5p", "6p", "7p"])
    check("第 2 组也能摊", r.get("n"), 1)
    check("还有面子（2s3s4s）→ 继续问", r.get("more"), True)
    r = g2.youyin_meld_pick(0, ["2s", "3s", "4s"])
    check("第 3 组摊完", r.get("n"), 1)
    check("手里没面子了 → 收尾", r.get("more"), False)
    g3 = Game(db2, rid2)
    check("摊完回到打牌", g3.phase, "discard")
    check("摊完 armed 清掉", g3.youyin_meld_armed, -1)
    check("摊完 deadline 归零", float(g3.youyin_meld_deadline), 0.0)
    check("摊了 3 组 + 吃的那副 = 4 副露", len(g3.melds(0)), 4)

    # ── ③ arm 之后 pass：claim 结算时清掉开启状态 ─────────────────────────
    print("\n③ arm 之后 pass（没真副露）")
    db4, rid4, g4 = setup("ym_pass", hand13b)
    g4.youyin_meld_arm(0)
    g4 = Game(db4, rid4)
    check("arm 之后 armed = 0", g4.youyin_meld_armed, 0)
    g4.pass_claim(0)
    g5 = Game(db4, rid4)
    check("pass 之后 armed 清掉", g5.youyin_meld_armed, -1)
    check("没进摊面子", g5.phase != "youyin_meld", True)

    # ── ④ 超时兜底：不替玩家摊，直接收尾 ─────────────────────────────────
    print("\n④ 摊面子阶段超时")
    db6, rid6, g6 = setup("ym_timeout", hand13b)
    g6.youyin_meld_arm(0)
    g6.act(0, "chi", tiles=["3m", "4m"])
    g6 = Game(db6, rid6)
    g6.youyin_meld_deadline = time.time() - 1.0
    g6.save_flags()
    g7 = Game(db6, rid6)
    check("超时判定", g7.youyin_meld_timeout(), True)
    g7.youyin_meld_skip()
    g8 = Game(db6, rid6)
    check("超时后回到打牌", g8.phase, "discard")
    check("超时后 offer 清掉", g8.youyin_meld_offer, None)
    check("超时后没偷偷摊面子", len(g8.melds(0)), 1)     # 只有吃的那一副
    check("超时后 prompt_state 不锁桌", g8.prompt_state(), None)

    # ── ⑤ 明杠 + 没面子：不进摊面子，照样补岭上/翻宝（只补一张）──────────
    print("\n⑤ 明杠 5m（1m5m7m9m1p4p7p2s5s8s + 5m5m5m）→ 没面子")
    hand13c = parse_hand("1m5m7m9m1p4p7p2s5s8s") + ["5m", "5m", "5m"]
    db9, rid9, g9 = setup("ym_minkan_nomianzi", hand13c, action="minkan",
                          choices=[["5m", "5m", "5m"]], tile="5m")
    g9.youyin_meld_arm(0)
    dora_before = len([1 for x in g9.db._rows(
        "SELECT 1 FROM round_dora WHERE round_id=? AND kind='dora' AND revealed=1", (rid9,))])
    g9.act(0, "minkan", tiles=["5m", "5m", "5m"])
    g10 = Game(db9, rid9)
    check("明杠后不进摊面子", g10.phase, "discard")
    check("手牌 = 10 张手牌 + 1 张岭上", len(g10.hand(0)), 11)
    dora_after = len([1 for x in g10.db._rows(
        "SELECT 1 FROM round_dora WHERE round_id=? AND kind='dora' AND revealed=1", (rid9,))])
    check("宝牌只翻了一张", dora_after - dora_before, 1)
    check("armed 清掉", g10.youyin_meld_armed, -1)

    print("\n" + "=" * 74)
    print(f" 结果：{PASS} 项通过，{FAIL} 项失败")
    print("=" * 74)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
