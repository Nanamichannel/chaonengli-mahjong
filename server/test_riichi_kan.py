# -*- coding: utf-8 -*-
"""
立直后的杠（标准日麻，天凤 / 雀魂同款）
=====================================================================
用户口径（2026-11-02）：立直后可以暗杠，但暗杠**不能改变听牌**，
连「杠完就不听了」都不行。

规则：
  · 立直后不能加杠；
  · 立直后暗杠必须 ① 用刚摸到的那张（禁送り槓）
                    ② 杠完待牌种类一张不差。

运行：python test_riichi_kan.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from game import Game, RuleError
from tiles import counts_of, parse_hand
from rules import agari
from test_game import _OPEN_DBS, fresh_db, new_round, set_hand

OK = FAIL = 0
HERE = os.path.dirname(os.path.abspath(__file__))


def check(name, cond, extra=""):
    global OK, FAIL
    if cond:
        OK += 1
        print(f"  [OK]   {name}" + (f"  ({extra})" if extra else ""))
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  {extra}")


def riichi(db, rid, seat=0):
    with db.tx():
        db.conn.execute("INSERT INTO round_riichi(round_id, seat, declared_seq) "
                        "VALUES(?,?,0)", (rid, seat))


def at_discard(db, rid, seat=0) -> Game:
    g = Game(db, rid)
    g.turn = seat
    g.phase = "discard"
    g.save_flags()
    return g


def waits13(g, seat=0):
    """听牌要看 13 张（去掉刚摸那张）—— g.waits() 是 14 张的，不能直接用。"""
    return agari.winning_tiles(counts_of(g.hand13(seat)), g.melds(seat))


def acts_of(g: Game, seat=0) -> set:
    return {str(a.get("action", "")) for a in g.legal_actions(seat)}


def ankan_tiles(g: Game, seat=0) -> list:
    return [str(a.get("tile", "")) for a in g.legal_actions(seat)
            if str(a.get("action", "")) == "ankan"]


def main() -> int:
    # ── 1. 允许：摸到第 4 张，暗杠后仍然只听同一张 ───────────────────
    print("\n[1] 立直 + 摸到第 4 张，杠完听牌不变 → 允许")
    db = fresh_db("rk1")
    rid, _, _ = new_round(db, seed=41)
    # 手牌：1111m 234m 567m 234p 东（最后一张 1m = 刚摸到的）
    set_hand(db, rid, 0,
             ["1m", "1m", "1m", "2m", "3m", "4m", "5m", "6m", "7m",
              "2p", "3p", "4p", "dong", "1m"], drawn="1m")
    riichi(db, rid, 0)
    g = at_discard(db, rid, 0)
    check("杠前听 东（dong）", waits13(g, 0) == ["dong"], str(waits13(g, 0)))
    check("立直后暗杠 1m 出现在合法动作里", "1m" in ankan_tiles(g, 0), str(ankan_tiles(g, 0)))
    check("ankan_allowed 返回 True", g.ankan_allowed(0, "1m"))
    # 杠完：手牌剩 10 张 + 1 个杠，听牌必须还是 东
    check("杠后仍听 东（dong）",
          g.ankan_allowed(0, "1m") and waits13(g, 0) == ["dong"], str(waits13(g, 0)))
    check("立直后不能加杠", not g.kakan_allowed(0, "1m"))

    # ── 2. 禁止：摸到第 4 张，但杠完就不听了 ─────────────────────────
    print("\n[2] 立直 + 杠完不听 → 不给出这个动作")
    db2 = fresh_db("rk2")
    rid2, _, _ = new_round(db2, seed=43)
    # 13 张听牌：111m 22m 33m 44m 55m 66m（七对子听 1m），再摸到第 4 张 1m
    set_hand(db2, rid2, 0,
             ["1m", "1m", "1m", "2m", "2m", "3m", "3m", "4m", "4m",
              "5m", "5m", "6m", "6m", "1m"], drawn="1m")
    riichi(db2, rid2, 0)
    g2 = at_discard(db2, rid2, 0)
    check("杠前听 1m（七对子）", "1m" in waits13(g2, 0), str(waits13(g2, 0)))
    check("杠完不再听牌 → ankan_allowed False", not g2.ankan_allowed(0, "1m"))
    check("legal 里没有 ankan", ankan_tiles(g2, 0) == [], str(ankan_tiles(g2, 0)))

    # ── 3. 禁止：杠的不是刚摸到的那张（送り槓）──────────────────────
    print("\n[3] 立直 + 用手里原有的 4 张暗杠 → 禁止")
    db3 = fresh_db("rk3")
    rid3, _, _ = new_round(db3, seed=47)
    set_hand(db3, rid3, 0,
             ["1m", "1m", "1m", "2m", "3m", "4m", "5m", "6m", "7m",
              "2p", "3p", "4p", "1m", "dong"], drawn="dong")
    riichi(db3, rid3, 0)
    g3 = at_discard(db3, rid3, 0)
    check("摸到的不是 1m → 不能暗杠 1m", not g3.ankan_allowed(0, "1m"))
    check("legal 里没有 ankan", ankan_tiles(g3, 0) == [], str(ankan_tiles(g3, 0)))

    # ── 4. 没立直时不受影响 ───────────────────────────────────────────
    print("\n[4] 没立直 → 暗杠照常（规则只管立直后）")
    db4 = fresh_db("rk4")
    rid4, _, _ = new_round(db4, seed=53)
    set_hand(db4, rid4, 0,
             ["1m", "1m", "1m", "2m", "3m", "4m", "5m", "6m", "7m",
              "2p", "3p", "4p", "dong", "1m"], drawn="1m")
    g4 = at_discard(db4, rid4, 0)
    check("未立直：legal 里有 ankan 1m", "1m" in ankan_tiles(g4, 0), str(ankan_tiles(g4, 0)))
    check("未立直：ankan_allowed True", g4.ankan_allowed(0, "1m"))
    check("未立直：kakan_allowed True", g4.kakan_allowed(0, "1m"))

    # ── 5. 硬校验：绕过 legal 直接 _kan 也会被拒 ─────────────────────
    print("\n[5] 直接调 _kan 也要拦住（防止别的入口绕过去）")
    try:
        g2._kan(0, "ankan", "1m")
        check("立直后非法暗杠抛 RuleError", False, "没有抛异常")
    except RuleError as e:
        check("立直后非法暗杠抛 RuleError", True, str(e))
    try:
        g.kakan_allowed(0, "1m")
        g._kan(0, "kakan", "1m")
        check("立直后加杠抛 RuleError", False, "没有抛异常")
    except RuleError as e:
        check("立直后加杠抛 RuleError", True, str(e))

    print("\n" + "=" * 70)
    print(f" 结果：{OK} 项通过，{FAIL} 项失败")
    print("=" * 70)
    for d in _OPEN_DBS:
        try:
            d.close()
        except Exception:
            pass
    data_dir = os.path.join(HERE, "data")
    if os.path.isdir(data_dir):
        for f in os.listdir(data_dir):
            if f.startswith("_test_"):
                try:
                    os.remove(os.path.join(data_dir, f))
                except OSError:
                    pass
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
