# -*- coding: utf-8 -*-
"""账号库 + 每小局战绩（2026-11-14 用户口径）

· 名字即账号，**没有密码**，**区分大小写**
· 每小局给每个登录账号记一条（分数 = 该局结束后的点数，delta = 本局变化量）
· **有人机的对局整局不计**
· 房间库被回收也不影响（记账在独立的 data/accounts.db）
"""
from __future__ import annotations

import io
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding="utf-8")

# ★ 测试用临时账号库，别污染 server/data/accounts.db
_TMP = os.path.join(tempfile.gettempdir(), "tianma_test_accounts.db")
for _suffix in ("", "-wal", "-shm"):
    try:
        os.remove(_TMP + _suffix)
    except OSError:
        pass
os.environ["TIANMA_ACCOUNTS_DB"] = _TMP

import accounts                          # noqa: E402
import api_cli                            # noqa: E402
import test_game as tg                    # noqa: E402
import test_chuancheng_copy as tc         # noqa: E402
from tiles import parse_hand              # noqa: E402

PASS = 0
FAIL = 0


def check(name, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print("  [OK]   %s" % name)
    else:
        FAIL += 1
        print("  [FAIL] %s  got=%r want=%r" % (name, got, want))


def room(tag, seed):
    """一间房 + 一局（四家人手，座位 0/1 是登录账号）"""
    db = tg.fresh_db(tag)
    tc.set_orders(db, [[27, 27, 27, 27, 27], [1, 2, 3, 4, 5],
                       [1, 2, 3, 4, 6], [1, 2, 3, 4, 7]])
    rid, _m, _u = tg.new_round(db, seed=seed)
    for s, h in enumerate(("123m456p789s1z2z3z", "1m4m7m1p4p7p1s4s7s1z2z3z",
                           "2m5m8m2p5p8p2s5s8s2z3z4z", "3m6m9m3p6p9p3s6s9s1z1z2z")):
        tg.set_hand(db, rid, s, parse_hand(h))
    return db, rid


def main() -> int:
    print("=" * 72)
    print(" 天才麻将少女 · 账号库 + 每小局战绩")
    print("=" * 72)

    print("\n① 登录 / 注册")
    r = accounts.login("阿知贺")
    check("库里没有 → exists=False", r.get("exists"), False)
    r = accounts.create("阿知贺")
    check("注册 → created=True", r.get("created"), True)
    check("注册后 exists=True", r.get("exists"), True)
    r = accounts.login("阿知贺")
    check("再登录 → exists=True", r.get("exists"), True)
    r = accounts.create("阿知贺")
    check("重复注册 → created=False（幂等）", r.get("created"), False)

    print("\n② 区分大小写")
    accounts.create("Tom")
    check("Tom 已存在", accounts.login("Tom").get("exists"), True)
    check("tom 是**另一个**账号（不存在）", accounts.login("tom").get("exists"), False)
    accounts.create("tom")
    check("tom 注册后与 Tom 各自独立",
          accounts.account_id_of("Tom") != accounts.account_id_of("tom"), True)

    print("\n③ 非法名字")
    for bad in ("", "   ", "a" * 25, "a b", "牌!", "  中文 空格  "):
        check("拒绝 %r" % bad, accounts.create(bad).get("created"), False)
    check("24 字刚好可以", accounts.create("字" * 24).get("created"), True)

    print("\n④ api_cli 的两个 op（不依赖房间库）")
    out = api_cli.handle({"op": "account_login", "name": "阿知贺"}, db_path=os.path.join(HERE, "data", "mahjong.db"))
    check("op account_login ok", out.get("ok"), True)
    check("op account_login exists", out.get("exists"), True)
    out = api_cli.handle({"op": "account_create", "name": "新名字"}, db_path=os.path.join(HERE, "data", "mahjong.db"))
    check("op account_create ok", out.get("ok"), True)
    check("op account_create created", out.get("created"), True)
    out = api_cli.handle({"op": "account_create", "name": "!!"}, db_path=os.path.join(HERE, "data", "mahjong.db"))
    check("非法名字 → ok=False", out.get("ok"), False)

    print("\n⑤ 每小局记账（全真人）")
    db, rid = room("acc_room", 1414)
    db.conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('seat_account_0','阿知贺')")
    db.conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('seat_account_1','Tom')")
    _before0 = int(db._one(
        "SELECT score FROM match_seats WHERE seat=0 AND match_id="
        "(SELECT match_id FROM rounds WHERE round_id=?)", (rid,)) or 0)
    db.finish_round(rid, "tsumo", deltas={0: 2000, 1: -700, 2: -700, 3: -600})
    h0 = accounts.history("阿知贺")
    check("阿知贺 记到 1 条", len(h0), 1)
    rec = h0[0] if h0 else {}
    check("分数 = 这一局结束后的点数（起分 %d + 2000）" % _before0,
          int(rec.get("score", -1)), _before0 + 2000)
    check("delta = 本局变化量", int(rec.get("delta", 0)), 2000)
    check("result = tsumo", rec.get("result"), "tsumo")
    check("Tom 也记到 1 条", len(accounts.history("Tom")), 1)
    check("没登录的座位不记（2 号位）", len(accounts.history("")), 0)

    db.finish_round(rid, "tsumo", deltas={0: 2000})      # 同一局再结算一次
    check("同一局重复结算 → 不会写第二条", len(accounts.history("阿知贺")), 1)

    print("\n⑥ 有人机的对局整局不计")
    db2, rid2 = room("acc_bot", 2424)
    db2.conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('seat_account_0','阿知贺')")
    db2.conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('seat_bot_2','1')")
    db2.finish_round(rid2, "ron", deltas={0: 1200, 2: -1200})
    check("有人机 → 这一局 0 条", len(accounts.history("阿知贺")), 1)   # 仍是上面那条

    print("\n⑦ 流局也计入（delta=0）")
    db3, rid3 = room("acc_draw", 3434)
    db3.conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('seat_account_0','阿知贺')")
    db3.finish_round(rid3, "ryuukyoku", deltas={})
    hh = accounts.history("阿知贺")
    check("流局也记了一条", len(hh), 2)
    check("流局 result=ryuukyoku", hh[0].get("result"), "ryuukyoku")
    check("流局 delta=0", int(hh[0].get("delta", -1)), 0)

    print("\n⑧ 统计")
    st = accounts.stats("阿知贺")
    check("局数 = 2", int(st.get("rounds", 0)), 2)
    check("和了局数 = 1", int(st.get("wins", 0)), 1)

    print("\n" + "=" * 72)
    print(" 断言 %d 条 / 失败 %d 条" % (PASS, FAIL))
    print("=" * 72)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
