# -*- coding: utf-8 -*-
"""规则修正回归（用户口径 2026-11-06）：
  ① 每开一次杠 → 本局可摸张数 -1（王牌从活牌山尾部补）
  ② 刚碰完的牌不能马上加杠（等自己下一次摸牌）
  ③ 渣和：无役也能和 —— **自动判定**，不用手动发动（判定链里 dawa 开着就给和牌）
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")

from game import Game  # noqa: E402
from tiles import parse_hand  # noqa: E402
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


H_NOYAKU = parse_hand("111m234m789m456p") + ["9s", "9s"]      # 无役（有幺九、无役牌、非平和）
# 荣和时手里只有 13 张（和牌那张是别人打的，不在手里）
H_RON13 = parse_hand("111m234m789m456p") + ["9s"]
H_OTHER = parse_hand("234m567p678s") + ["2p", "2p", "9m"]
H_OTHER2 = parse_hand("2m5m8m2p5p8p2s5s8s") + ["dong", "nan", "xi", "bei"]
H_OTHER3 = parse_hand("3m6m9m3p6p9p3s6s9s") + ["bei", "bai", "fa"]


def setup(tag, granted=None):
    db = tg.fresh_db(tag)
    rid, _m, _u = tg.new_round(db, seed=21)
    tg.set_hand(db, rid, 0, H_NOYAKU, drawn="9s")
    tg.set_hand(db, rid, 1, H_OTHER)
    tg.set_hand(db, rid, 2, H_OTHER2)
    tg.set_hand(db, rid, 3, H_OTHER3)
    # 已经打过一张 → 不成立「天和/地和」，这样才是真正的"无役"
    with db.tx():
        db.conn.execute(
            "INSERT INTO round_discards(round_id, seq, seat, tile, wall_seq, is_tsumogiri) "
            "VALUES(?,?,?,?,?,1)", (rid, 901, 0, "1p", 991))
    g = Game(db, rid)
    g.round_phase = "play"
    g.phase, g.turn = "discard", 0
    if granted:
        g.granted = granted
    g.save_flags()
    return db, rid, g


def ron_game(db, rid, granted=None) -> Game:
    """荣和场景：手里只有 13 张（H_RON13），和牌那张是别人打的。

    ★ 以前 ③ 直接用 setup() 的 14 张手牌再 +1 张和牌张 = 15 张，
      永远不是和牌形 → 「判番为 None / 判番有了」这两条断言其实什么都没测到。
    """
    tg.set_hand(db, rid, 0, H_RON13, drawn=None)
    g = Game(db, rid)
    g.round_phase = "play"
    g.phase, g.turn = "discard", 0
    if granted:
        g.granted = granted
    g.save_flags()
    return g


print("① 开杠 → 活牌山少一张（live_left -1）")
db, rid, g = setup("kan1")
before = g.live_left()
g._draw_rinshan(0, force=True)
check("live_left -1", g.live_left(), before - 1)
g._draw_rinshan(0, force=True)
check("再开一杠再 -1", g.live_left(), before - 2)

print("\n② 刚碰完的牌不能马上加杠")
db2, rid2, g2 = setup("kan2")
g2.pon_lock[0] = "zhong"
check("碰中之后不能加杠中", g2.kakan_allowed(0, "zhong"), False)
check("别的牌不受影响", g2.kakan_allowed(0, "9s"), True)
g2._draw_after(0, "9s", extra_checks=False)
check("摸牌后解锁", g2.kakan_allowed(0, "zhong"), True)

print("\n③ 渣和：无役也能和（自动判定，无手动发动）")
db3, rid3, g3 = setup("kan3")            # 没有渣和
g3 = ron_game(db3, rid3)
# 用「荣和」判：自摸的话这手牌有门前清自摸和，不是无役
check("没渣和：无役不能和（判番为 None）", g3._judge_win(0, "9s", tsumo=False) is None, True)

db4, rid4, _g4old = setup("kan4", granted={0: {13}})
g4 = ron_game(db4, rid4, granted={0: {13}})
res = g4._judge_win(0, "9s", tsumo=False)
check("持渣和：判番有了", res is not None, True)
if res:
    check("判番是 dawa_pending（等结算补）", bool(res.get("dawa_pending")), True)
    settled = g4.settle_preview(0, 1, "ron", res, dry_run=True)
    names = [str(y.get("name")) for y in (settled.get("yaku") or [])]
    check("结算后判成【渣和】", "渣和" in names, True)
    check("30 符", int(settled.get("fu", 0)), 30)
check("持渣和：判定链自动带上 dawa（不需要手动发动）", bool(g4.win_ctx(
    0, g4.hand(0), "9s", False).get("dawa", False)), True)
check("持渣和：不需要手动发动（used_skills 里没有 13-2）",
      "13-2-0" in g4.used_skills, False)
# 「自动判定弹出」= 和牌闸门直接放行 → legal_actions / 鸣牌窗口里自然有「和」
check("持渣和：荣和闸门自动放行（和牌按钮会弹）", g4._win_ok(0, "9s", tsumo=False), True)
check("没渣和：闸门不放行（无役不和）", g3._win_ok(0, "9s", tsumo=False), False)
# 「正确的时机自动弹出」：别人打出和牌张 → 鸣牌窗口里就有「和」，不用先点技能图标
g4.turn = 1
g4._open_claim_window(902, "9s", 1)
_opts = (g4.pending or {}).get("options", {}).get(0, [])
check("持渣和：鸣牌窗口自动给「和」",
      any(a.get("action") == "ron" for a in _opts), True)

print("\n" + "=" * 70)
print(" 通过 %d 项，失败 %d 项" % (PASS, FAIL))
print("=" * 70)
sys.exit(1 if FAIL else 0)
