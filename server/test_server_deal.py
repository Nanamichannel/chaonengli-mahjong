"""服务端配牌 / 岭上 / 翻宝牌 自测：python test_server_deal.py"""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8")

import api_cli
from db import DB
from game import Game

DB_PATH = api_cli.DB_PATH


def counts(state) -> list[int]:
    """每家手上几张（含刚摸的那张）。"""
    out = [0, 0, 0, 0]
    for h in state["hand_counts"]:
        out[int(h["seat"])] = int(h["tiles"])
    return out


def main() -> int:
    r = api_cli.handle({"op": "start", "seat": 0})
    if not r.get("ok"):
        print("start 失败:", r.get("error"))
        return 1
    s = r["state"]
    print(f"开桌：骰子 {s['dice']} → 第 {s['first_stack']} 墩（{s['start_side']}面起）"
          f"，阶段={s['round_phase']}，牌山 {len(r['wall'])} 张")
    print(f"      王牌墩号：岭上 {s.get('dora_stacks')} / 牌山已拿 {len(s['wall_taken'])}")

    # ── 一步步配牌 ──
    step = 0
    while True:
        s = r["state"]
        if s["deal_done"] and s["round_phase"] == "play":
            break
        r = api_cli.handle({"op": "deal_step", "seat": 0})
        if not r.get("ok"):
            print("deal_step 失败:", r.get("error"))
            return 1
        ev = r["events"][0]
        step += 1
        if ev.get("event") == "deal":
            print(f"  第 {step:2d} 步 → {ev['seat']} 号位 拿 {ev['tiles']}"
                  + (f" + 跳牌 {ev['jump']}" if ev.get("jump") else "")
                  + f"   手上 {counts(r['state'])}")
        else:
            print(f"  第 {step:2d} 步 → {ev.get('event')} {ev.get('dora')}")
        if step > 25:
            print("!! 配牌没结束，可能死循环")
            return 1

    s = r["state"]
    print(f"\n配牌结束：手牌张数 {counts(s)}（庄家 14、其余 13），阶段={s['round_phase']}")
    print(f"      phase={s['phase']} turn={s['turn']} legal={[a['action'] for a in s['legal']]}")
    print(f"      牌山已拿走 {len(s['wall_taken'])} 张，宝牌指示牌 {s['dora'][:1]}"
          f"（第 {s['dora_stacks'][0]} 墩）")

    # ── 庄家打一张，进入切牌 ──
    hand = r["state"]["hand"]
    r2 = api_cli.handle({"op": "act", "seat": 0, "action": "discard", "tile": hand[0]})
    if r2.get("ok"):
        print(f"打牌 {hand[0]} → ok，牌山已拿 {len(r2['state']['wall_taken'])} 张")
    else:
        print("打牌失败:", r2.get("error"))

    # ── 岭上 + 翻宝牌（直接调服务端的方法，模拟开杠）──
    db = DB(DB_PATH)
    g = Game(db, r["round_id"])
    ev1 = g.reveal_dora(force=True)
    t1 = g._draw_rinshan(0, force=True)
    g.save_flags()
    print(f"开杠 → 翻宝牌 {ev1}，岭上摸到 {t1}")
    ev2 = g.reveal_dora(force=True)
    t2 = g._draw_rinshan(0, force=True)
    g.save_flags()
    print(f"再开一杠 → 翻宝牌 {ev2}，岭上摸到 {t2}")
    st = g.state_for(0)
    print(f"宝牌指示牌 = {st['dora']}，对应墩 {st['dora_stacks']}，"
          f"岭上用了 {st['rinshan_used']} 张，牌山已拿 {len(st['wall_taken'])} 张")
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
