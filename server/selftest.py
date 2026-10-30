# -*- coding: utf-8 -*-
"""
数据库层自测：模拟一整局牌，把每一层都验一遍。
运行：  python selftest.py
（会建一个临时库 server/data/_selftest.db，跑完自动删掉）
"""
import itertools
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:                       # 让 Windows 控制台也能正常显示中文
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
from db import DB, build_wall, dora_from_indicator, kind_of, tile_suit, tile_number
from game import Game
from rules import wallmodel

OK = 0
FAIL = 0


def check(name, cond, extra=""):
    global OK, FAIL
    if cond:
        OK += 1
        print(f"  [OK]   {name}" + (f"  ({extra})" if extra else ""))
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  {extra}")


def planned_hands(wall, dealer_seat):
    """离线复算发牌结果，用来和数据库里存的对比。"""
    hands = {s: [] for s in range(4)}
    ptr = 0
    for _ in range(13):
        for k in range(4):
            hands[(dealer_seat + k) % 4].append((ptr, wall[ptr]))
            ptr += 1
    return hands, ptr


def find_chi(wall, dealer_seat):
    """找一个真实存在的吃牌场景：(打出的人, 那张牌, 吃的人, 手里用来吃的两张)"""
    hands, _ = planned_hands(wall, dealer_seat)
    for caller in range(4):
        tiles = [t for _, t in hands[caller]]
        for a, b in itertools.combinations(tiles, 2):
            if tile_suit(a) != tile_suit(b) or tile_suit(a) == "":
                continue
            na, nb = tile_number(a), tile_number(b)
            cand = []
            if abs(na - nb) == 1:
                lo, hi = min(na, nb), max(na, nb)
                if lo - 1 >= 1:
                    cand.append(lo - 1)
                if hi + 1 <= 9:
                    cand.append(hi + 1)
            elif abs(na - nb) == 2:
                cand.append((na + nb) // 2)
            for n in cand:
                need = f"{n}{tile_suit(a)}"
                for other in range(4):
                    if other == caller:
                        continue
                    for seq, t in hands[other]:
                        if t == need:
                            return other, seq, need, caller, [a, b]
    return None


def pick_seed(finder, tries=200):
    for seed in range(tries):
        got = finder(build_wall(True, seed), 0)
        if got:
            return seed, got
    return None, None


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "data", "_selftest.db")
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(path + suffix):
            os.remove(path + suffix)

    print("=" * 70)
    print(" 天马麻将 · 数据库层自测")
    print("=" * 70)

    # ── 1. 建库 ─────────────────────────────────────────────────────────────
    print("\n[1] 建库 / 表结构")
    db = DB(path)
    db.init_schema()
    tables = [t["name"] for t in db._rows(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    views = [v["name"] for v in db._rows("SELECT name FROM sqlite_master WHERE type='view'")]
    check("建表成功", len(tables) >= 14, f"{len(tables)} 张表")
    check("公开视图建好", "v_public_round" in views and "v_hand_counts" in views, f"{len(views)} 个视图")

    # ── 2. 账号 / 会话 ──────────────────────────────────────────────────────
    print("\n[2] 账号 / 登录会话")
    uids = [db.create_user(f"玩家{i+1}") for i in range(4)]
    check("4 个账号建好", len(set(uids)) == 4)
    tok = db.create_session(uids[0])
    sess = db.resolve_session(tok)
    check("token 能换回身份（断线重连）", sess is not None and sess["user_id"] == uids[0])
    check("假 token 换不回来", db.resolve_session("nope") is None)

    # ── 3. 房间 ─────────────────────────────────────────────────────────────
    print("\n[3] 房间 / 座位")
    room = db.create_room(uids[0], mode="east_only", rules={"red_fives": True, "kuitan": True})
    for u in uids[1:]:
        db.join_room(room["room_code"], u)
    rv = db.room_view(room["room_id"])
    check("房间 4 个人坐满", len(rv["seats"]) == 4, f"邀请码 {room['room_code']}")
    try:
        db.join_room(room["room_code"], db.create_user("多出来的"))
        check("第 5 个人进不来", False)
    except ValueError:
        check("第 5 个人进不来", True)

    # ── 4. 配牌（骰子 + 牌山编号，全在服务端算）───────────────────────────
    print("\n[4] 配牌 / 牌山编号（服务端）")
    match_id = db.start_match(room["room_id"])
    rid = db.start_round(match_id, "dong", 1, honba=0, dealer_seat=0)
    g = Game(db, rid)
    g.start()
    check("开局投骰子、算出拿牌起点", g.dice is not None and 2 <= g.wall_first_stack() <= 13,
          f"骰子 {g.dice} → 第 {g.wall_first_stack()} 墩（{g.wall_start_side()}面起）")
    check("配牌前谁都没牌", all(
        (db._one("SELECT COUNT(*) FROM round_hands WHERE round_id=? AND seat=?", (rid, s)) or 0) == 0
        for s in range(4)))
    check("牌山写进库 136 张",
          (db._one("SELECT COUNT(*) FROM round_wall WHERE round_id=?", (rid,)) or 0) == 136)
    check("可摸张数 = 124（136 − 王牌 12）",
          db._one("SELECT live_left FROM rounds WHERE round_id=?", (rid,)) == 124)
    steps = 0
    while not g.deal_done():
        g.deal_step()
        steps += 1
    counts = {r["seat"]: r["tiles"] for r in db._rows(
        "SELECT seat, COUNT(*) AS tiles FROM round_hands WHERE round_id=? GROUP BY seat", (rid,))}
    check("配牌结束：庄家 14 张、其余各 13 张",
          {k: counts[k] for k in sorted(counts)} == {0: 14, 1: 13, 2: 13, 3: 13}, str(counts))
    check("配牌 16 步（3 圈×4 + 第 4 圈 4 步；庄家那步连跳牌）", steps == 16, f"{steps} 步")
    check("配牌后进入「切牌」阶段", g.round_phase == "play", g.round_phase)
    check("牌山已拿走 53 张（含跳牌那张）", len(g.wall_taken()) == 53, len(g.wall_taken()))
    dora = db._rows("SELECT kind, idx, indicator, dora, revealed FROM round_dora "
                    "WHERE round_id=? ORDER BY kind, idx", (rid,))
    check("宝牌指示牌：表 1 张已翻、里宝牌也记着",
          sum(d["revealed"] for d in dora if d["kind"] == "dora") == 1 and len(dora) == 2,
          str(dora))
    check("宝牌换算正确（指示牌 → 宝牌）",
          all(d["dora"] == dora_from_indicator(d["indicator"]) for d in dora),
          f"{dora[0]['indicator']}→{dora[0]['dora']}")

    # ── 5. 行牌：打一张 → 轮流摸打 ─────────────────────────────────────────
    print("\n[5] 打牌 / 摸牌循环（服务端驱动）")
    seat = 0
    g.act(0, "discard", tile=g.hand(0)[0])
    drawn = 0
    for _ in range(40):
        if g.phase == "ended":
            break
        if g.phase == "claim":
            for s in list(g.pending["options"]):
                if s not in g.pending["answers"]:
                    g.pass_claim(s)
            continue
        g.advance()
        drawn += 1
        if g.phase == "discard":
            g.act(g.turn, "discard")
    check("连续摸打不报错", drawn > 5, f"摸了 {drawn} 次")
    check("总分守恒 140000",
          sum(s["score"] for s in db.public_state(rid)["scores"]) == 140000)
    print("\n[9] 防作弊：公开信息里没有任何人的手牌、没有牌山")
    pub = db.public_state(rid)
    check("公开信息不含 hand 字段", "hand" not in pub)
    check("公开信息不含牌山字段", "wall" not in pub and "live_wall" not in pub)
    check("公开信息里关于手牌只有「张数」",
          all(set(h.keys()) == {"seat", "tiles"} for h in pub["hand_counts"]),
          str(pub["hand_counts"]))
    # 真正严格的检查：按「牌的唯一编号」比对，同一个编号只能出现在本人那一份里
    def hand_seqs(seat):
        return {r["wall_seq"] for r in db._rows(
            "SELECT wall_seq FROM round_hands WHERE round_id=? AND seat=?", (rid, seat))}
    priv_ok = True
    leaked = 0
    for s in range(4):
        got = {h["wall_seq"] for h in db.private_state(rid, s)["hand"]}
        mine = hand_seqs(s)
        if got != mine:                     # 该看到的没看到 / 看到别人的
            priv_ok = False
        leaked += len(got - mine)
    check("每个人拿到的私密状态里只有自己的手牌（按唯一编号核对）", priv_ok and leaked == 0)
    dealt = db._one("SELECT COUNT(*) FROM round_wall WHERE round_id=? AND dealt_to IS NOT NULL", (rid,))
    check("完整牌山只有服务器能看（server_state）",
          len(db.server_state(rid)["live_wall"]) == 136 - dealt,
          f"发出去 {dealt} 张，还剩 {len(db.server_state(rid)['live_wall'])} 张")

    # ── 10. 幂等（断线重发同一个动作） ──────────────────────────────────────
    print("\n[10] 幂等：同一个动作号重复发，只执行一次")
    seat = (seat + 1) % 4
    gg = Game(db, rid)
    seq = wallmodel.seq_of_tile(wallmodel.next_live_no(gg.next_no, gg.wall_first_stack()))
    n0 = db._one("SELECT COUNT(*) FROM round_hands WHERE round_id=? AND seat=?", (rid, seat))
    db.draw_seq(rid, seat, seq, client_action_id="cid-1")
    n1 = db._one("SELECT COUNT(*) FROM round_hands WHERE round_id=? AND seat=?", (rid, seat))
    db.draw_seq(rid, seat, seq, client_action_id="cid-1")
    n2 = db._one("SELECT COUNT(*) FROM round_hands WHERE round_id=? AND seat=?", (rid, seat))
    check("重复的摸牌请求被忽略", n1 == n0 + 1 and n2 == n1, f"{n0}→{n1}→{n2}")

    # ── 11. 复盘日志 ────────────────────────────────────────────────────────
    print("\n[11] 动作日志（复盘 / 重连补发）")
    acts = db.replay(rid)
    kinds = [a["action"] for a in acts]
    check("日志按顺序记录", kinds[0] == "round_start" and acts[0]["seq"] == 1)
    check("配牌 / 摸牌 / 打牌都记进日志",
          all(k in kinds for k in ("deal", "draw", "discard")),
          f"共 {len(acts)} 条")
    check("日志 seq 连续不跳号", [a["seq"] for a in acts] == list(range(1, len(acts) + 1)))

    db.finish_match(match_id)
    check("一场结束后房间状态更新",
          db._one("SELECT status FROM rooms WHERE room_id=?", (room["room_id"],)) == "finished")

    db.close()
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(path + suffix):
            os.remove(path + suffix)

    print("\n" + "=" * 70)
    print(f" 结果：{OK} 项通过，{FAIL} 项失败")
    print("=" * 70)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
