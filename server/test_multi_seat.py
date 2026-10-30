# -*- coding: utf-8 -*-
"""多窗口（4 个客户端各坐一家）自测。

规矩：
  - 一个座位只要「有人在操作」（活着的客户端），服务器就不替它代打；
  - 没人操作的座位继续由服务器代打（AI）；
  - 客户端停了（心跳超时）→ 座位自动交回 AI。

跑法： python test_multi_seat.py
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import api_cli  # noqa: E402
import test_game as tg  # noqa: E402
from db import DB  # noqa: E402
from game import Game  # noqa: E402
from tiles import parse_hand  # noqa: E402

PASS = FAIL = 0
_OPEN_DBS: list = []
RID = [0]


def check(name, got, want):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  got {got!r} want {want!r}")


def call(req, db):
    return api_cli.handle(req, db.path)          # 走真实入口（含续租）


def join(db, seat, force=True):
    return call({"op": "join", "seat": seat, "force": force}, db)


def state(db, seat):
    return call({"op": "state", "seat": seat}, db)["state"]


def step(db, seat):
    return call({"op": "step", "seat": seat}, db)


def act(db, seat, action, **kw):
    req = {"op": "act", "seat": seat, "action": action}
    req.update(kw)
    return call(req, db)


def events_of(r) -> list:
    return [(e["event"], e.get("seat")) for e in (r.get("events") or [])
            if isinstance(e, dict) and e.get("event")]


def settle_claims(db, seats=(0, 1, 2, 3)):
    """测试里扮演所有「有人的窗口」：鸣牌窗口一律过掉（不和）"""
    for _ in range(8):
        g = Game(db, RID[0])
        p = g.pending
        if not p:
            return
        todo = [s for s in p["options"] if s not in p["answers"] and s in seats]
        if not todo:
            return
        for s in todo:
            act(db, s, "pass")
    return


def any_discard(db, seat):
    """这个座位随便打一张能打的牌"""
    acts = [a for a in state(db, seat)["legal"] if a["action"] == "discard"]
    act(db, seat, "discard", tile=acts[0]["tiles"][0])


def main() -> int:
    print("=" * 74)
    print(" 天才麻将少女 · 四个客户端各坐一家")
    print("=" * 74)

    db = tg.fresh_db("multi_seat")
    _OPEN_DBS.append(db)

    # ── ① 四个窗口依次认领 0/1/2/3 ──────────────────────────────────────
    print("\n① 认领座位")
    j0 = join(db, 0)
    RID[0] = j0["round_id"]
    check("第一个窗口拿到 0 号位", j0["seat"], 0)
    check("第一个窗口顺手开了一局", j0["created"], True)
    check("开局后配牌还没发完", j0["state"]["deal_done"], False)
    for seat in (1, 2, 3):
        j = join(db, seat)
        check("第 %d 个窗口拿到 %d 号位" % (seat + 1, seat), j["seat"], seat)
        check("第 %d 个窗口接上同一局（不另开）" % (seat + 1),
              (j["created"], j["round_id"]), (False, RID[0]))
    check("四个座位都有人在操作", sorted(api_cli._human_seats(db)), [0, 1, 2, 3])

    # ── ② 配牌：四个窗口各自推进，直到发完 ──────────────────────────────
    print("\n② 配牌")
    for _ in range(80):
        if state(db, 0)["deal_done"]:
            break
        call({"op": "deal_step", "seat": 0}, db)
    st = state(db, 0)
    check("配牌完成", st["deal_done"], True)
    check("从 3 号位看出去，自己也是 14 张里的庄家视角…（各家状态独立）",
          len(state(db, 3)["hand"]) > 0, True)
    check("现在轮到 0 号位打牌", (st["phase"], int(st["turn"])), ("discard", 0))

    # ── ③ 有人的座位不会被代打 ─────────────────────────────────────────
    print("\n③ 有人在的座位，服务器不代打")
    r = step(db, 1)                       # 1 号位窗口问一下
    check("1 号位 step 之后什么都没发生（都在等人）", events_of(r), [])
    check("0 号位还是 14 张（没被代打）", len(state(db, 0)["hand"]), 14)
    check("2/3 号位也还是 13 张（没被代打）",
          (len(state(db, 2)["hand"]), len(state(db, 3)["hand"])), (13, 13))

    # ── ④ 各窗口自己驱动自己的座位 ─────────────────────────────────────
    print("\n④ 各窗口自己驱动自己的座位")
    any_discard(db, 0)
    settle_claims(db)
    st1 = state(db, 1)
    check("打完轮到 1 号位摸牌", (st1["phase"], int(st1["turn"])), ("draw", 1))
    r = step(db, 1)                       # 1 号位的窗口自己摸
    check("1 号位摸完变成该打牌", r["state"]["phase"], "discard")
    check("1 号位手牌 14 张（自己摸的）", len(r["state"]["hand"]), 14)
    any_discard(db, 1)
    settle_claims(db)
    check("轮到 2 号位", (state(db, 2)["phase"], int(state(db, 2)["turn"])), ("draw", 2))

    # ── ⑤ 窗口关掉 → 座位交回 AI ───────────────────────────────────────
    print("\n⑤ 窗口关掉之后，座位交回给服务器代打")
    with db.tx():
        db.conn.execute("DELETE FROM meta WHERE key IN ('seat_lease_2','seat_lease_3')")
    check("2/3 号位不再是「有人在操作」", sorted(api_cli._human_seats(db)), [0, 1])
    seen = set()
    for _ in range(10):
        st = state(db, 0)
        if int(st["turn"]) in (0, 1) and st["phase"] != "claim":
            break
        r = step(db, 0)
        for e in events_of(r):
            if e[0] == "draw":
                seen.add(e[1])
        settle_claims(db, seats=(0, 1))       # 有人的窗口该过就过
    check("服务器替 2 号位摸过牌", 2 in seen, True)
    check("服务器替 3 号位摸过牌", 3 in seen, True)
    check("最后停在「轮到有人的座位」", int(state(db, 0)["turn"]) in (0, 1), True)

    # ── ⑥ 鸣牌窗口：有人的座位要自己作答 ───────────────────────────────
    print("\n⑥ 鸣牌窗口里，有人的座位要自己答")
    for s_ in range(4):                       # 四个窗口都还在（⑤ 里删过 2/3 的租约）
        api_cli._touch_lease(db, s_)
    g = Game(db, RID[0])
    g.turn = 0
    g.phase = "discard"
    g.save_flags()
    tg.set_hand(db, RID[0], 0, parse_hand("123m456m789m123p") + ["5s", "5s"], drawn="5s")
    tg.set_hand(db, RID[0], 2, parse_hand("111m234567p99s") + ["5s", "5s"])
    act(db, 0, "discard", tile="5s")
    g2 = Game(db, RID[0])
    check("打出去之后开了鸣牌窗口", g2.phase, "claim")
    opts = list((g2.pending or {}).get("options", {}))
    check("2 号位（手里两张 5s）在窗口里", 2 in opts, True)
    step(db, 1)                                        # 1 号位窗口问一下
    ans = set((Game(db, RID[0]).pending or {}).get("answers", {}))
    check("没替有人的座位作答", ans & {1, 2, 3}, set())
    if 2 in opts:
        act(db, 2, "pass")
        g3 = Game(db, RID[0])
        check("2 号位自己过掉之后窗口没卡住",
              g3.pending is None or 2 in (g3.pending or {}).get("answers", {}), True)

    # ── ⑦ 心跳续租 ─────────────────────────────────────────────────────
    print("\n⑦ 请求本身就算心跳")
    with db.tx():
        db.conn.execute("DELETE FROM meta WHERE key='seat_lease_3'")
    check("3 号位这会儿没人", 3 in api_cli._human_seats(db), False)
    state(db, 3)                                       # 3 号位窗口又发了一次请求
    check("发过一次请求之后 3 号位又「有人」了", 3 in api_cli._human_seats(db), True)

    # ── ⑧ 不指定座位 → 自动给一个空位（4 个窗口同时打开时各拿一家）────────
    print("\n⑧ 不指定座位时自动分配")
    db2 = tg.fresh_db("multi_auto")
    _OPEN_DBS.append(db2)
    with db2.tx():                       # fixture 预写的 4 个租约清掉（模拟真开窗口）
        db2.conn.execute("DELETE FROM meta WHERE key LIKE 'seat_lease_%'")
    got = []
    for _ in range(4):
        got.append(api_cli.handle({"op": "join", "seat": -1}, db2.path)["seat"])
    check("四个窗口自动拿到 0/1/2/3（各一家，不打架）", sorted(got), [0, 1, 2, 3])

    # ── ⑨ 配牌没配完就断线 → 另一个窗口接着推进 ──────────────────────────
    print("\n⑨ 配牌中断之后，别的窗口能接手配完")
    rid2 = api_cli.handle({"op": "state", "seat": 0}, db2.path)["round_id"]
    st2 = api_cli.handle({"op": "state", "seat": 0}, db2.path)["state"]
    check("这时候还没配完牌", st2["deal_done"], False)
    api_cli.handle({"op": "deal_step", "seat": 0}, db2.path)      # 推进两步
    api_cli.handle({"op": "deal_step", "seat": 0}, db2.path)
    check("推了两步还是没配完", api_cli.handle(
        {"op": "state", "seat": 0}, db2.path)["state"]["deal_done"], False)
    with db.tx():                                                 # 0 号位那个窗口关了
        db.conn.execute("DELETE FROM meta WHERE key='seat_lease_0'")
    check("0 号位交回 AI 了", 0 in api_cli._human_seats(db), False)
    check("现在最小座位号是 1（由 1 号位窗口接手推进）",
          min(api_cli._human_seats(db)), 1)
    for _ in range(60):                                           # 1 号位窗口把它推完
        if api_cli.handle({"op": "state", "seat": 1}, db2.path)["state"]["deal_done"]:
            break
        api_cli.handle({"op": "deal_step", "seat": 1}, db2.path)
    st2 = api_cli.handle({"op": "state", "seat": 1}, db2.path)["state"]
    check("配牌被另一个窗口推完了", st2["deal_done"], True)
    check("四家手牌张数都齐了",
          sorted(len(api_cli.handle({"op": "state", "seat": s2}, db2.path)["state"]["hand"])
                 for s2 in range(4)), [13, 13, 13, 14])

    # ── ⑩ 四个窗口同时启动：四个「进程」一起 join ────────────────────────
    # 客户端那侧还有一层：窗口之间不能抢同一对请求/响应文件（现在按进程号分开，
    # 见 server_bridge.gd）。这里只钉服务端这一半：并发的 join 不能撞座位、不能各开一局。
    print("\n⑩ 四个进程同时 join（要排队，不能撞车）")
    here = os.path.dirname(os.path.abspath(__file__))
    race_db = os.path.join(here, "data", "_test_multi_race.db")
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(race_db + suffix):
            os.remove(race_db + suffix)
    tmp = DB(race_db)
    tmp.init_schema()
    tmp.close()

    procs = []
    for i in range(4):
        req_f = os.path.join(here, "data", f"_race_req_{i}.json")
        res_f = os.path.join(here, "data", f"_race_res_{i}.json")
        for f2 in (req_f, res_f):
            if os.path.exists(f2):
                os.remove(f2)
        with io.open(req_f, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"op": "join", "seat": -1}))
        argv = [sys.executable, os.path.join(here, "api_cli.py"),
                "--in", req_f, "--out", res_f, "--db", race_db]
        procs.append((req_f, res_f,
                      subprocess.Popen(argv, cwd=here, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.PIPE)))
    seats, rids = [], set()
    errs = []
    for req_f, res_f, p in procs:
        _, err = p.communicate(timeout=90)
        if p.returncode != 0:
            errs.append((err or b"").decode("utf-8", "replace")[-200:])
        with io.open(res_f, encoding="utf-8") as fh:
            data = json.load(fh)
        seats.append(data.get("seat"))
        rids.add(data.get("round_id"))
    check("四个进程都没报错", errs, [])
    check("座位各不相同（0/1/2/3 各一家）", sorted(seats), [0, 1, 2, 3])
    check("四个进程都在同一局里（不会各开一局）", len(rids), 1)

    print()
    print(f"{PASS} 项通过 / {FAIL} 项失败")
    for d in _OPEN_DBS:
        try:
            d.close()
        except Exception:
            pass
    data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    for f in os.listdir(data_dir):
        if (f.startswith("_test_multi_seat") or f.startswith("_test_multi_auto")
                or f.startswith("_test_multi_race") or f.startswith("_race_req_")
                or f.startswith("_race_res_")):
            try:
                os.remove(os.path.join(data_dir, f))
            except OSError:
                pass
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
