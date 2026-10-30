"""四人准备 / 传递选卡 / 调序的大厅状态（存在 meta 表里，四个客户端共用）。

四个实例 = 四个客户端，各自一个座位。整个流程由服务端推进：

    waiting  点「开始」= 准备；四家都准备 → 随机 20 张，一家 5 张，进入 draft
    draft    传递选卡：每人从自己手里的 5 张里留 1 张，
             剩下 4 张整手传给下家（0→1→2→3→0），一共转 5 轮
    order    各自把自己选的 5 张排成 1..5（1-4 主战、5 协战），点「开始」提交
    play     四家都提交 → 服务端开新半庄 → 客户端一起进 node_2d

状态存在 meta 表 key=lobby_state 的 JSON 里；读写都在一个事务内，
四个进程同时请求也不会互相踩。
"""
from __future__ import annotations

import json
import random
import time

LOBBY_KEY = "lobby_state"

DRAFT_TOTAL = 20          # 严格 20 张
PICK_PER_SEAT = 5         # 一人 5 张
CARD_MIN, CARD_MAX = 1, 46
DEAD_GRACE = 10.0         # 秒：某一轮有人掉线，超过这么久就替他选，别让三家干等


def _default() -> dict:
    return {
        "phase": "waiting",
        "seats": [{"ready": False, "hand": [], "picks": [], "order": []} for _ in range(4)],
        "joined": [False, False, False, False],
        "pool": [],
        "round": 0,
        "pending": [False, False, False, False],
        "since": 0.0,
        "draft_no": 0,
    }


def load(db) -> dict:
    row = db._row("SELECT value FROM meta WHERE key=?", (LOBBY_KEY,))
    data = None
    if row:
        try:
            data = json.loads(row["value"])
        except (ValueError, TypeError):
            data = None
    out = _default()
    if isinstance(data, dict):
        out.update(data)

    seats = []
    raw_seats = out.get("seats") if isinstance(out.get("seats"), list) else []
    for i in range(4):
        s = raw_seats[i] if len(raw_seats) > i and isinstance(raw_seats[i], dict) else {}
        seats.append({
            "ready": bool(s.get("ready", False)),
            "hand": [int(v) for v in (s.get("hand") or [])],
            "picks": [int(v) for v in (s.get("picks") or [])],
            "order": [int(v) for v in (s.get("order") or [])],
        })
    out["seats"] = seats
    out["pool"] = [int(v) for v in (out.get("pool") or [])]
    out["phase"] = str(out.get("phase") or "waiting")
    out["round"] = int(out.get("round") or 0)
    out["draft_no"] = int(out.get("draft_no") or 0)
    for key in ("joined", "pending"):
        arr = out.get(key)
        vals = [bool(arr[i]) if isinstance(arr, list) and len(arr) > i else False for i in range(4)]
        out[key] = vals
    return out


def save(db, lobby: dict) -> None:
    with db.tx():
        db.conn.execute(
            "INSERT INTO meta(key, value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (LOBBY_KEY, json.dumps(lobby, ensure_ascii=False)))


def reset(lobby: dict) -> dict:
    """回到 waiting（新的一局选卡）。draft_no 只增不减，方便客户端判断是不是同一轮。"""
    d = _default()
    d["draft_no"] = int(lobby.get("draft_no", 0)) + 1
    return d


def payload(lobby: dict, seat: int) -> dict:
    return {
        "phase": lobby.get("phase", "waiting"),
        "seats": lobby.get("seats", []),
        "pool": lobby.get("pool", []),
        "round": int(lobby.get("round", 0)),
        "pending": lobby.get("pending", [False] * 4),
        "joined": lobby.get("joined", [False] * 4),
        "draft_no": int(lobby.get("draft_no", 0)),
        "my_seat": int(seat),
        "total": DRAFT_TOTAL,
        "per_seat": PICK_PER_SEAT,
    }


def _error(msg: str) -> dict:
    return {"ok": False, "state": None, "events": [], "result": None, "error": msg}


def _ok(lobby: dict, seat: int, extra: dict | None = None) -> dict:
    out = {"ok": True, "state": None, "events": [], "result": None,
           "seat": seat, "lobby": payload(lobby, seat)}
    if isinstance(extra, dict):
        out.update(extra)
    return out


def start_draft(lobby: dict) -> None:
    """随机 20 张，一家 5 张，开始传着选。

    Test.txt 的 [人物卡] 里写了编号 → 这几张一定在 20 张里，剩下的随机补满；
    没写 → 和正式一样，全随机。
    """
    import testfile
    fixed = list(dict.fromkeys(c for c in testfile.cards() if CARD_MIN <= c <= CARD_MAX))
    fixed = fixed[:DRAFT_TOTAL]
    rest = [c for c in range(CARD_MIN, CARD_MAX + 1) if c not in fixed]
    pool = fixed + random.sample(rest, DRAFT_TOTAL - len(fixed))
    random.shuffle(pool)
    lobby["pool"] = pool
    for i, s in enumerate(lobby["seats"]):
        s["hand"] = pool[i * PICK_PER_SEAT:(i + 1) * PICK_PER_SEAT]
        s["picks"] = []
        s["order"] = []
        s["ready"] = False
    lobby["round"] = 0
    lobby["pending"] = [False, False, False, False]
    lobby["since"] = time.time()
    lobby["phase"] = "draft"
    lobby["draft_no"] = int(lobby.get("draft_no", 0)) + 1


def _settle_round(lobby: dict) -> None:
    """四个人都留好一张 → 剩下的 4 张整手传给下家。"""
    hands = [list(s["hand"]) for s in lobby["seats"]]
    new_hands = [[] for _ in range(4)]
    for i in range(4):
        new_hands[(i + 1) % 4] = hands[i]
    for i in range(4):
        lobby["seats"][i]["hand"] = new_hands[i]
    lobby["round"] = int(lobby.get("round", 0)) + 1
    lobby["pending"] = [False, False, False, False]
    lobby["since"] = time.time()
    if lobby["round"] >= PICK_PER_SEAT:
        lobby["phase"] = "order"
        for s in lobby["seats"]:
            s["ready"] = False


def _autopick_dead(db, lobby: dict) -> bool:
    """某一轮里有人关了窗口 → 替他留一张，别让其他三家一直等。"""
    if lobby.get("phase") != "draft":
        return False
    if time.time() - float(lobby.get("since") or 0) < DEAD_GRACE:
        return False
    from api_cli import _human_seats
    humans = _human_seats(db)
    changed = False
    for s in range(4):
        if lobby["pending"][s] or not lobby["joined"][s]:
            continue
        if s in humans:
            continue
        hand = lobby["seats"][s]["hand"]
        if not hand:
            continue
        card = int(hand[0])
        lobby["seats"][s]["hand"].remove(card)
        lobby["seats"][s]["picks"].append(card)
        lobby["pending"][s] = True
        changed = True
    # 只有四家都留完牌才传牌 —— 别因为替某一家自动留了牌就提前结算
    if changed and all(lobby["pending"]):
        _settle_round(lobby)
    return changed


def op_join(db, req: dict) -> dict:
    """认领座位（和 op_join 一样的租约规则），只进大厅、不开牌局。"""
    from api_cli import _human_seats, _touch_lease   # 复用座位租约

    raw = req.get("seat", -1)
    with db.tx():
        humans = _human_seats(db)
        if raw is None or int(raw) < 0 or int(raw) > 3:
            seat = next((s for s in range(4) if s not in humans), None)
        else:
            want = int(raw) % 4
            if want in humans and not req.get("force"):
                seat = next((s for s in range(4) if s not in humans), None)
            else:
                seat = want
        # ★ 四家都被活人占着 → 拒绝。绝不能再退回 0 号位：
        #   旧写法 next(..., 0) 会让第 5 个窗口顶到 0 号位，两边都以为自己是 0 号位，
        #   互相看到对方的牌、互相替对方出牌，还会互相顶掉租约。
        if seat is None:
            return _error("房间已满（4/4），有人退出后会自动加入")

        lobby = load(db)
        # 之前四个窗口全都关了（一个活跃租约都没有）→ 当作全新开始
        if not humans and lobby.get("phase") != "waiting":
            lobby = reset(lobby)
        lobby["joined"][seat] = True
        _touch_lease(db, seat, req.get("pid"))
        save(db, lobby)
    return _ok(lobby, seat, {"humans": sorted(_human_seats(db))})


def op_state(db, req: dict) -> dict:
    seat = int(req.get("seat", 0)) % 4
    with db.tx():
        lobby = load(db)
        if _autopick_dead(db, lobby):
            save(db, lobby)
    return _ok(lobby, seat)


def op_ready(db, req: dict) -> dict:
    """waiting 阶段：准备 / 取消准备。四家都准备 → 发 20 张，进 draft。"""
    seat = int(req.get("seat", 0)) % 4
    value = bool(req.get("value", True))
    with db.tx():
        lobby = load(db)
        if lobby["phase"] != "waiting":
            return _error("现在不是准备阶段")
        lobby["seats"][seat]["ready"] = value
        started = False
        if all(s["ready"] for s in lobby["seats"]):
            start_draft(lobby)
            started = True
        save(db, lobby)
    return _ok(lobby, seat, {"started": started})


def op_pick(db, req: dict) -> dict:
    """draft 阶段：从自己手里留一张。四家都留好 → 剩下的 4 张传给下家。"""
    seat = int(req.get("seat", 0)) % 4
    card = int(req.get("card", 0))
    with db.tx():
        lobby = load(db)
        if lobby["phase"] != "draft":
            return _error("现在不是选卡阶段")
        if lobby["pending"][seat]:
            return _error("这一轮你已经留过牌了，等其他家")
        hand = lobby["seats"][seat]["hand"]
        if card not in hand:
            return _error("这张牌不在你手里")
        hand.remove(card)
        lobby["seats"][seat]["picks"].append(card)
        lobby["pending"][seat] = True
        if all(lobby["pending"]):
            _settle_round(lobby)
        save(db, lobby)
    return _ok(lobby, seat)


def op_order(db, req: dict) -> dict:
    """order 阶段：提交自己的 5 张顺序（1..5）。四家都提交 → play。"""
    seat = int(req.get("seat", 0)) % 4
    order = [int(v) for v in (req.get("order") or [])]
    with db.tx():
        lobby = load(db)
        if lobby["phase"] != "order":
            return _error("现在不是调序阶段")
        picks = list(lobby["seats"][seat]["picks"])
        if len(order) != len(picks) or sorted(order) != sorted(picks):
            return _error("顺序里的牌必须正好是你留的 5 张")
        lobby["seats"][seat]["order"] = order
        lobby["seats"][seat]["ready"] = True
        if all(s["ready"] and len(s["order"]) == PICK_PER_SEAT for s in lobby["seats"]):
            lobby["phase"] = "play"
            save(db, lobby)
            _start_new_hanchan(db)      # 四家一起进牌桌 = 新半庄
            return _ok(lobby, seat, {"new_hanchan": True})
        save(db, lobby)
    return _ok(lobby, seat)


def op_unorder(db, req: dict) -> dict:
    """order 阶段反悔（取消已提交的顺序）。"""
    seat = int(req.get("seat", 0)) % 4
    with db.tx():
        lobby = load(db)
        if lobby["phase"] != "order":
            return _error("现在不是调序阶段")
        lobby["seats"][seat]["order"] = []
        lobby["seats"][seat]["ready"] = False
        save(db, lobby)
    return _ok(lobby, seat)


def _start_new_hanchan(db) -> None:
    """四家准备完毕 → 服务端直接把牌局重置到东一 0 本场。

    这样四个客户端进 node_2d 时看到的是同一局，不会各自「发现上一局结束了」
    又各开一局。客户端那边的 F5 重置逻辑在这种情况下就不再触发了。
    """
    from api_cli import op_new_hanchan        # 延迟导入，避免循环依赖
    op_new_hanchan(db, {"seat": 0})


def op_test_seats(db, req: dict) -> dict:
    """【测试用】直接指定四家的 5 张卡，跳过选卡 / 调序阶段。

    请求： {"op": "test_seats", "orders": [[5 个卡号] x 4]}
           卡号 1..46；数组前 4 张 = 主战（东1-2 / 东3-4 / 南1-2 / 南3-4），
           第 5 张 = 协战。
    效果：四家 ready + order 写好 + phase=play + 立刻开新半庄。
    """
    raw = req.get("orders") or []
    if not isinstance(raw, list) or len(raw) != 4:
        return _error("orders 必须是 4 家、每家 5 个卡号")
    orders: list[list[int]] = []
    for i in range(4):
        arr = raw[i] if isinstance(raw[i], list) else []
        vals = [int(v) for v in arr]
        if len(vals) != PICK_PER_SEAT:
            return _error("第 %d 家要正好 %d 张卡" % (i, PICK_PER_SEAT))
        for v in vals:
            if v < 1 or v > 46:
                return _error("第 %d 家有个卡号不在 1..46：%d" % (i, v))
        orders.append(vals)
    with db.tx():
        lobby = reset(load(db))
        for i in range(4):
            lobby["seats"][i]["order"] = list(orders[i])
            lobby["seats"][i]["picks"] = list(orders[i])
            lobby["seats"][i]["ready"] = True
            lobby["joined"][i] = True
        lobby["phase"] = "play"
        save(db, lobby)
        _start_new_hanchan(db)
    return _ok(lobby, int(req.get("seat", 0)) % 4, {"test_seats": True})


def op_reset(db, req: dict) -> dict:
    """调试：把大厅打回 waiting。"""
    with db.tx():
        lobby = reset(load(db))
        save(db, lobby)
    return _ok(lobby, int(req.get("seat", 0)) % 4)
