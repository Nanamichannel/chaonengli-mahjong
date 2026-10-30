# -*- coding: utf-8 -*-
"""结算结果必须落库：state.result 在新进程里读不到的话，客户端永远看不到结算画面
（一次请求一个 python 进程，所以「同一个 Game 实例里 self.result 有值」不够）。

真实现场（2026-10-25 18:48）：国标宣言 → 服务端结算了（rounds.status=ended, result=ron）
→ 客户端靠轮询 / 看破放行后的重放拿 state → state.result=None → 不弹结算、整个卡死。
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")

from game import Game  # noqa: E402
from tiles import parse_hand  # noqa: E402
import test_game as tg  # noqa: E402

PASS = 0
FAIL = 0


def check(name, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  got={got!r} want={want!r}")


H14 = parse_hand("123m456m789m22p34s") + ["9s"]      # 打 9s 听 2s/5s
H_NONE = parse_hand("1m4m7m1p4p7p1s4s7s1z2z3z")


def make(tag, seed, others):
    db = tg.fresh_db(tag)
    rid, _m, _u = tg.new_round(db, seed=seed)
    tg.set_hand(db, rid, 0, H14, drawn="9s")
    for i, h in enumerate(others, start=1):
        tg.set_hand(db, rid, i, h)
    g = Game(db, rid)
    g.granted = {0: {1}}
    g.round_phase = "play"
    g.turn, g.phase = 0, "discard"
    g.save_flags()
    return db, rid


def main() -> int:
    print("=" * 66)
    print(" 天才麻将少女 · 结算结果（result）要能被别的进程读到")
    print("=" * 66)

    # ① 没结算的局：result 是 None
    print("\n① 还在打的局")
    db0, rid0 = make("rp0", 701, [H_NONE, H_NONE, H_NONE])
    st0 = Game(db0, rid0).state_for(0)
    check("没结算 → state.result 是 None", st0.get("result"), None)

    # ② 国标结算后：新实例（= 下一个请求的新进程）也读得到 result
    print("\n② 国标结算之后")
    below = parse_hand("1m2m3m4p5p6p7s8s9s1p1p1p") + ["2s"]      # 下家有我的铳张 2s
    db, rid = make("rp1", 702, [below, H_NONE, H_NONE])
    g = Game(db, rid)
    ev = g.guobiao_declare(0, "9s")
    check("当场结算了", ev.get("event"), "yiding")
    check("本实例里有 result", typeof_dict(g.result))

    fresh = Game(db, rid)                      # ← 模拟「下一个请求 = 新进程」
    st = fresh.state_for(0)
    res = st.get("result")
    check("新实例 state.result 不是 None", res is not None, True)
    check("结果类型 ron", (res or {}).get("result"), "ron")
    check("赢家是 0 号位", int((res or {}).get("winner", -1)), 0)
    check("番数对得上", int((res or {}).get("han", -1)), int(g.result.get("han", -2)))
    check("pays.total 有值", int(((res or {}).get("pays") or {}).get("total", 0)) > 0)
    check("yaku 名字还在", [y.get("name") for y in (res or {}).get("yaku", [])],
          [y.get("name") for y in g.result.get("yaku", [])])

    # ③ 落库的 flags 里确实有 result（不是靠猜）
    print("\n③ flags 里存了 result")
    row = db._row("SELECT flags_json FROM round_flags WHERE round_id=?", (rid,))
    fl = json.loads(row["flags_json"])
    check("flags 里有 result 键", "result" in fl, True)
    check("flags 里的 result 类型对", (fl.get("result") or {}).get("result"), "ron")

    # ④ 流局也要落库
    print("\n④ 流局之后")
    db2, rid2 = make("rp2", 703, [H_NONE, H_NONE, H_NONE])
    g2 = Game(db2, rid2)
    g2._ryuukyoku("exhaustive")
    st2 = Game(db2, rid2).state_for(0)
    check("流局：新实例 state.result 不是 None", st2.get("result") is not None, True)
    check("流局：result 是 ryuukyoku", (st2.get("result") or {}).get("result"), "ryuukyoku")
    check("流局：stopped", (st2.get("result") or {}).get("stopped"), True)
    check("流局：reason 也留着", (st2.get("result") or {}).get("reason"), "exhaustive")

    # ⑤ 老数据兜底：flags 里被人为抹掉 result，也要照 DB 拼出来
    print("\n⑤ flags 里没有 result（老局）→ 照 DB 拼")
    fl2 = json.loads(db._row("SELECT flags_json FROM round_flags WHERE round_id=?",
                             (rid,))["flags_json"])
    fl2.pop("result", None)
    db.save_round_flags(rid, fl2)
    res3 = Game(db, rid).state_for(0).get("result") or {}
    check("兜底拼出来的 result 不是 None", bool(res3), True)
    check("兜底：ron", res3.get("result"), "ron")
    check("兜底：points 有值", int(res3.get("points", 0)) > 0, True)
    check("兜底：标记 from_db", res3.get("from_db"), True)

    print("\n" + "=" * 66)
    print(f" 通过 {PASS} / 失败 {FAIL}")
    print("=" * 66)
    return 0 if FAIL == 0 else 1


def typeof_dict(v) -> bool:
    return isinstance(v, dict) and bool(v)


if __name__ == "__main__":
    sys.exit(main())
