# -*- coding: utf-8 -*-
"""本局昵称：rename → lobby.seats[i].nick → 开局抄进 match_seats → state.scores"""
import io, os, sys, tempfile
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
HERE = r"N:\apps\tianma\server"
sys.path.insert(0, HERE)
os.chdir(HERE)

from db import DB
import api_cli
import lobby as lobby_mod

PASS = FAIL = 0


def check(name, got, want):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print("  \u2713 " + name)
    else:
        FAIL += 1
        print("  \u2717 %s  got=%r want=%r" % (name, got, want))


dbp = os.path.join(tempfile.mkdtemp(), "nick.db")
db = DB(dbp)
db.init_schema()
pid = os.getpid()
run = lambda req: api_cli.handle(req, db_path=dbp)

r = run({"op": "lobby_join", "seat": -1, "pid": pid})
seat = int(r.get("seat", -1))
check("进房拿到座位", seat >= 0, True)

r = run({"op": "rename", "seat": seat, "nick": "  风间彻  "})
check("改名成功", bool(r.get("ok")), True)
seats = (r.get("lobby") or {}).get("seats") or []
check("昵称去空白后写入", String := str((seats[seat] or {}).get("nick", "")), "风间彻")

r = run({"op": "rename", "seat": seat, "nick": "一二三四五六七八九十"})
check("超过 8 字被截断", len(str(((r.get("lobby") or {}).get("seats") or [{}])[seat].get("nick", ""))), 8)

r = run({"op": "rename", "seat": seat, "nick": "   "})
check("空昵称被拒", bool(r.get("ok")), False)

# 开局：把大厅昵称抄进 match_seats
run({"op": "rename", "seat": seat, "nick": "风间彻"})
room = api_cli._local_room(db)
mid = db.start_match(room["room_id"])
rows = db._rows("SELECT seat, nickname FROM match_seats WHERE match_id=? ORDER BY seat", (mid,))
got = {int(x["seat"]): str(x["nickname"]) for x in rows}
check("开局后 match_seats 用大厅昵称", got.get(seat), "风间彻")

print("\n%d 项通过 / %d 项失败" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
