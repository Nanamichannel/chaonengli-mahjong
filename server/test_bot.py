# -*- coding: utf-8 -*-
"""人机（bot）座位：放入房间 → 自动准备/留牌/调序 → 对局里自动摸切、不用技能。

跑法：
    cd server
    python test_bot.py
"""
import io
import os
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import api_cli                                                   # noqa: E402

PASS = 0
FAIL = 0


def check(name, got, want):
    global PASS, FAIL
    if got == want:
        PASS += 1
    else:
        FAIL += 1
        print("  [FAIL] %s  got=%r want=%r" % (name, got, want))


def run(db, req):
    return api_cli.handle(req, db_path=db)


def lobby_of(db, seat=0):
    return run(db, {"op": "lobby_state", "seat": seat}).get("lobby") or {}


def river_counts(st):
    out = {0: 0, 1: 0, 2: 0, 3: 0}
    for d in (st.get("discards") or []):
        s = int(d.get("seat", -1))
        if s in out:
            out[s] += 1
    return out


def main():
    db = os.path.join(tempfile.mkdtemp(), "bot.db")
    me = os.getpid()

    print("── 1) 放入人机 ──")
    r = run(db, {"op": "lobby_join", "seat": -1, "pid": me})
    check("真人进房成功", bool(r.get("ok")), True)
    check("自动拿到 0 号位", r.get("seat"), 0)
    check("刚进房没有人机", lobby_of(db).get("bots"), [])

    r = run(db, {"op": "lobby_add_bot", "seat": 0, "bot_seat": 2})
    check("放人机到 2 号位", bool(r.get("ok")), True)
    check("bots = [2]", lobby_of(db).get("bots"), [2])
    check("人机可以直接放在空位（不占真人位）", r.get("seat"), 2)

    r = run(db, {"op": "lobby_add_bot", "seat": 0, "bot_seat": -1})
    check("自动补位不撞真人 0 号位", r.get("seat"), 1)
    r = run(db, {"op": "lobby_add_bot", "seat": 0, "bot_seat": -1})
    check("再补一个 → 3 号位", r.get("seat"), 3)
    check("三个都在", lobby_of(db).get("bots"), [1, 2, 3])
    r = run(db, {"op": "lobby_add_bot", "seat": 0, "bot_seat": -1})
    check("满了以后拒绝再加", bool(r.get("ok")), False)
    r = run(db, {"op": "lobby_add_bot", "seat": 0, "bot_seat": 0})
    check("不能往真人座位上放", bool(r.get("ok")), False)

    print("── 2) 人机自动准备 ──")
    lb = lobby_of(db)
    check("人机座位都 ready", [lb["seats"][s]["ready"] for s in (1, 2, 3)], [True, True, True])
    check("真人还没准备", lb["seats"][0]["ready"], False)

    print("── 3) 真人准备 → 自动发牌进 draft ──")
    r = run(db, {"op": "lobby_ready", "seat": 0, "value": True})
    check("四家齐了 → 开始选卡", r.get("started"), True)
    lb = lobby_of(db)
    check("进入 draft", lb["phase"], "draft")
    # 人机一进 draft 就会自动留一张 → hand + picks 恒等于 5
    check("每家共 5 张（手里 + 已留）",
          [len(lb["seats"][s]["hand"]) + len(lb["seats"][s]["picks"]) for s in range(4)],
          [5, 5, 5, 5])
    check("人机已经先留了一张", [len(lb["seats"][s]["picks"]) for s in (1, 2, 3)], [1, 1, 1])

    print("── 4) draft：人机自动留牌 + 传牌 5 轮 ──")
    for _ in range(40):
        lb = lobby_of(db)
        if lb["phase"] != "draft":
            break
        if not lb["pending"][0]:
            hand = lb["seats"][0]["hand"]
            run(db, {"op": "lobby_pick", "seat": 0, "card": int(hand[0])})
    lb = lobby_of(db)
    check("走完 5 轮 → order", lb["phase"], "order")
    check("每家都留了 5 张", [len(lb["seats"][s]["picks"]) for s in range(4)], [5, 5, 5, 5])
    check("人机已自己排好顺序", [lb["seats"][s]["ready"] for s in (1, 2, 3)], [True, True, True])

    print("── 5) order：真人提交 → play ──")
    picks = lb["seats"][0]["picks"]
    r = run(db, {"op": "lobby_order", "seat": 0, "order": picks})
    check("提交后进 play", (r.get("lobby") or {}).get("phase"), "play")
    check("半庄已开", r.get("new_hanchan"), True)

    print("── 6) 对局：人机自动摸切、不鸣牌不用技能 ──")
    # 配牌是客户端一步步推的（真实客户端开局会连发几十次 deal_step）
    for _ in range(80):
        st = run(db, {"op": "state", "seat": 0}).get("state") or {}
        if bool(st.get("deal_done", True)):
            break
        run(db, {"op": "deal_step", "seat": 0})
    # 配牌窗口（deal_skill）：人机由服务端自动跳过，我要自己点"跳过"
    for _ in range(60):
        st = run(db, {"op": "state", "seat": 0}).get("state") or {}
        if st.get("phase") in ("draw", "discard", "claim"):
            break
        if st.get("phase") == "deal_skill":
            run(db, {"op": "deal_skill", "seat": 0, "action": "skip"})
        run(db, {"op": "step", "seat": 0})
    st = run(db, {"op": "state", "seat": 0}).get("state") or {}
    check("配牌完成", bool(st.get("deal_done", False)), True)
    check("牌局在打", st.get("phase") in ("draw", "discard", "claim"), True)
    before = river_counts(st)
    for _ in range(80):
        if st.get("phase") == "ended":
            break
        st = run(db, {"op": "step", "seat": 0}).get("state") or st
        if st.get("turn") == 0 and st.get("phase") == "discard":
            d = st.get("drawn") or ((st.get("hand") or ["1m"])[-1])
            st = run(db, {"op": "act", "seat": 0, "action": "discard",
                          "tile": d}).get("state") or st
        after = river_counts(st)
        if all(after[s] > before[s] for s in (1, 2, 3)):
            break
    after = river_counts(st)
    check("人机自己打过牌（三家牌河都变多）",
          all(after[s] > before[s] for s in (1, 2, 3)), True)
    check("人机没开副露（不鸣牌）",
          [m for m in (st.get("melds") or []) if int(m.get("seat", -1)) in (1, 2, 3)], [])
    check("人机没立直", [s for s in (st.get("riichi") or []) if int(s) in (1, 2, 3)], [])

    print("── 7) 真人抢人机座位 ──")
    r = run(db, {"op": "lobby_join", "seat": 2, "pid": me})
    check("不给 force → 不会抢到 2 号位", r.get("seat") != 2, True)
    r = run(db, {"op": "lobby_join", "seat": 2, "pid": me, "force": True})
    check("force → 坐进 2 号位", r.get("seat"), 2)
    check("人机被让位", lobby_of(db).get("bots"), [1, 3])

    print("── 8) 移除人机 ──")
    r = run(db, {"op": "lobby_remove_bot", "seat": 0, "bot_seat": -1})
    check("移除最后一个", bool(r.get("ok")), True)
    check("剩一个", lobby_of(db).get("bots"), [1])
    r = run(db, {"op": "lobby_remove_bot", "seat": 0, "bot_seat": 1})
    check("指定座位移除", lobby_of(db).get("bots"), [])
    r = run(db, {"op": "lobby_remove_bot", "seat": 0, "bot_seat": 9})
    check("移除不存在的位 → 报错", bool(r.get("ok")), False)
    r = run(db, {"op": "lobby_remove_bot", "seat": 0, "bot_seat": -1})
    check("没有可移除的 → 报错", bool(r.get("ok")), False)

    print("\n%d 项通过 / %d 项失败" % (PASS, FAIL))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
