# -*- coding: utf-8 -*-
"""租约：进程还活着就永远算「有人在操作」（玩家开着技能面板想多久都不会被代打）"""
from __future__ import annotations

import io
import os
import sys
import time

sys.path.insert(0, r'N:\apps\tianma\server')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import api_cli  # noqa: E402
import test_game as tg  # noqa: E402

OK = 0
BAD = 0


def check(cond, msg):
    global OK, BAD
    if cond:
        OK += 1
    else:
        BAD += 1
        print("  [FAIL]", msg)


def put(db, seat, value):
    with db.tx():
        db.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES(?,?)",
                        (api_cli.LEASE_KEY % seat, value))


def main():
    db = tg.fresh_db("lease")
    # fresh_db 已经写了 4 个座位（未来时间戳 + 当前进程）→ 都算人
    check(api_cli._human_seats(db) == {0, 1, 2, 3},
          f"刚建库应该四家都算人，实际 {api_cli._human_seats(db)}")

    # ── ① 时间戳很旧（远超 12 秒）但进程还活着 → 仍然算人
    put(db, 0, "%.3f:%d" % (time.time() - 600.0, os.getpid()))
    hs = api_cli._human_seats(db)
    check(0 in hs, f"进程还活着就该算人（哪怕 10 分钟没请求），实际 {hs}")

    # ── ② 进程号不存在 → 交回 AI
    put(db, 1, "%.3f:%d" % (time.time(), 9999999))
    hs = api_cli._human_seats(db)
    check(1 not in hs, f"进程没了就该交回 AI，实际 {hs}")

    # ── ③ 老数据（没有进程号）：只能按时间算
    put(db, 2, "%.3f" % (time.time() - 600.0))
    hs = api_cli._human_seats(db)
    check(2 not in hs, f"没有进程号 + 超时 → 交回 AI，实际 {hs}")
    put(db, 2, "%.3f" % (time.time() - 1.0))
    hs = api_cli._human_seats(db)
    check(2 in hs, f"没有进程号 + 刚请求过 → 算人，实际 {hs}")

    print(f"\n通过 {OK} / 失败 {BAD}")
    return 1 if BAD else 0


if __name__ == "__main__":
    sys.exit(main())
