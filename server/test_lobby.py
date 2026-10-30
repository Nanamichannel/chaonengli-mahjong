"""大厅流程自测：4 个客户端 → 准备 → 20 张（一家 5 张）传递选卡 → 调序 → play。"""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from api_cli import handle

FAIL = 0
OK = 0


def check(name, cond, extra=""):
    global FAIL, OK
    if cond:
        OK += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {extra}")


def main() -> int:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.remove(path)
    try:
        print("① 四个窗口各自认领座位")
        seats = []
        for i in range(4):
            r = handle({"op": "lobby_join", "seat": -1}, path)
            check(f"窗口 {i} join ok", r.get("ok"), r.get("error"))
            seats.append(r["seat"])
        check("四家座位互不相同", sorted(seats) == [0, 1, 2, 3], str(seats))

        print("② 四家准备 → 发 20 张，一家 5 张")
        for s in seats:
            r = handle({"op": "lobby_ready", "seat": s, "value": True}, path)
            check(f"座位 {s} ready ok", r.get("ok"), r.get("error"))
        lb = handle({"op": "lobby_state", "seat": 0}, path)["lobby"]
        check("阶段变成 draft", lb["phase"] == "draft", lb["phase"])
        check("池子 20 张", len(lb["pool"]) == 20, len(lb["pool"]))
        hands = [lb["seats"][s]["hand"] for s in range(4)]
        check("每家 5 张", all(len(h) == 5 for h in hands), [len(h) for h in hands])
        check("20 张不重复", len(set(v for h in hands for v in h)) == 20)
        check("四家手牌不重叠",
              len(set(v for h in hands for v in h)) == sum(len(h) for h in hands))

        print("③ 传递选卡：每人留 1 张，剩下 4 张传给下家（共 5 轮）")
        picks = {s: [] for s in seats}
        for rnd in range(5):
            before = [list(lb["seats"][s]["hand"]) for s in range(4)]
            # 不在自己手里的牌不能留
            other_card = next(v for v in before[(0 + 1) % 4] if v not in before[0])
            bad = handle({"op": "lobby_pick", "seat": 0, "card": other_card}, path)
            check(f"第 {rnd+1} 轮：不能留别人手里的牌", not bad.get("ok"))
            for s in seats:
                card = lb["seats"][s]["hand"][0]
                r = handle({"op": "lobby_pick", "seat": s, "card": card}, path)
                check(f"第 {rnd+1} 轮 座位 {s} 留 {card}", r.get("ok"), r.get("error"))
                picks[s].append(card)
                if s == 0:
                    again = handle({"op": "lobby_pick", "seat": 0, "card": card}, path)
                    check("同一轮不能留第二张", not again.get("ok"))
            lb = handle({"op": "lobby_state", "seat": 0}, path)["lobby"]
            check(f"第 {rnd+1} 轮结束轮次 +1", lb["round"] == rnd + 1, lb["round"])
            if rnd < 4:
                check(f"第 {rnd+1} 轮后剩余 4 张",
                      all(len(lb["seats"][s]["hand"]) == 4 - rnd for s in range(4)),
                      [len(lb["seats"][s]["hand"]) for s in range(4)])
                # 座位 s 的新手牌 = 上一家剩下的牌
                shifted_ok = True
                for s in range(4):
                    prev = (s - 1) % 4
                    expect = [v for v in before[prev] if v not in picks[prev]]
                    if sorted(lb["seats"][s]["hand"]) != sorted(expect):
                        shifted_ok = False
                check(f"第 {rnd+1} 轮后牌传到下家", shifted_ok)

        lb = handle({"op": "lobby_state", "seat": 0}, path)["lobby"]
        check("5 轮后进入 order", lb["phase"] == "order", lb["phase"])
        for s in seats:
            check(f"座位 {s} 留满 5 张", len(lb["seats"][s]["picks"]) == 5, lb["seats"][s]["picks"])
            check(f"座位 {s} 的 5 张互不相同", len(set(lb["seats"][s]["picks"])) == 5)
        all_picked = [v for s in seats for v in lb["seats"][s]["picks"]]
        check("20 张全部被留走", len(set(all_picked)) == 20, len(set(all_picked)))

        print("④ 调序 → 提交")
        bad = handle({"op": "lobby_order", "seat": 0, "order": [1, 2, 3, 4, 5]}, path)
        check("顺序必须是自己的牌", not bad.get("ok"), bad.get("error"))
        for s in seats:
            order = list(reversed(lb["seats"][s]["picks"]))
            r = handle({"op": "lobby_order", "seat": s, "order": order}, path)
            check(f"座位 {s} 提交顺序", r.get("ok"), r.get("error"))
        lb = handle({"op": "lobby_state", "seat": 2}, path)["lobby"]
        check("四家提交后进入 play", lb["phase"] == "play", lb["phase"])
        check("四家顺序都齐了", all(len(lb["seats"][s]["order"]) == 5 for s in seats))

        print("⑤ 四家都掉线后重新 join 会回到 waiting")
        from db import DB
        db = DB(path)
        with db.tx():
            for s in range(4):
                db.conn.execute("DELETE FROM meta WHERE key=?", (f"seat_lease_{s}",))
        db.close()
        r = handle({"op": "lobby_join", "seat": -1}, path)
        check("回到 waiting", r["lobby"]["phase"] == "waiting", r["lobby"]["phase"])
        check("手牌清空", all(len(s["hand"]) == 0 for s in r["lobby"]["seats"]))
    finally:
        if os.path.exists(path):
            os.remove(path)
    print(f"\n{OK} 项通过 / {FAIL} 项失败")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
