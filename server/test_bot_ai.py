# -*- coding: utf-8 -*-
"""人机 AI 的冒烟测试：① 不打无脑摸切 ② 手牌被换过也能切出去"""
import io, os, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import importlib
tg = importlib.import_module("test_game")
from game import Game
import bot_ai
import api_cli

FAIL = []


def check(name, cond, extra=""):
    if cond:
        print("  ✓ %s" % name)
    else:
        print("  ✗ %s   %s" % (name, extra))
        FAIL.append(name)


def main():
    db = tg.fresh_db("botai")
    rid, match, uids = tg.new_round(db, seed=7)
    g = Game(db, rid)

    # ── ① AI 应该扔孤张字牌，而不是打刚摸的那张 ──
    hand = ["1m", "2m", "3m", "4p", "5p", "6p", "7s", "8s", "9s",
            "bei", "1p", "1p", "5s"]
    tg.set_hand(db, rid, 1, hand, drawn=None)
    with db.tx():
        db.conn.execute("DELETE FROM round_hands WHERE round_id=? AND seat=1 AND tile=?", (rid, "5s"))
        db.conn.execute(
            "INSERT INTO round_hands(round_id, seat, wall_seq, tile, slot, is_drawn)"
            " VALUES(?,?,?,?,?,1)", (rid, 1, 9901, "6s", 13))
    g2 = Game(db, rid)
    drawn = g2.drawn_tile(1)
    pick = bot_ai.choose_discard(g2, 1)
    print("  手牌 14 张，摸到 %s → AI 打 %s" % (drawn, pick))
    check("AI 打的不是刚摸的那张（不是无脑摸切）", pick != drawn, "drawn=%s pick=%s" % (drawn, pick))
    check("AI 扔掉孤张字牌「北」", pick == "bei", "pick=%s" % pick)

    # ── ② 手牌被技能换掉（整手替换、没有 drawn 标记）后仍然能切 ──
    swapped = ["2s", "2s", "3s", "4s", "5s", "6s", "7p", "8p", "9p",
               "dong", "nan", "bai", "zhong"]
    tg.set_hand(db, rid, 2, swapped, drawn=None)
    g3 = Game(db, rid)
    pick2 = api_cli._bot_discard(g3, 2)
    check("被换牌后仍能选出一张（不卡死）", pick2 in swapped, "pick=%s" % pick2)

    # ── ③ 空手牌 / 异常情况不抛异常 ──
    with db.tx():
        db.conn.execute("DELETE FROM round_hands WHERE round_id=? AND seat=3", (rid,))
    g4 = Game(db, rid)
    try:
        pick3 = api_cli._bot_discard(g4, 3)
        ok = isinstance(pick3, str)
    except Exception as e:
        ok = False
        pick3 = repr(e)
    check("空手牌不崩（返回字符串即可）", ok, "pick=%s" % pick3)

    print("\n%d 项通过 / %d 项失败" % (5 - len(FAIL), len(FAIL)))
    return 1 if FAIL else 0


sys.exit(main())
