"""
客户端（Godot）唯一入口：收 JSON 请求 → 服务器按规则判定 → 回 JSON

Godot 的 OS.execute 在 Windows 上读不到子进程 stdout，所以两边都用文件传：
    python api_cli.py --in 请求.json --out 响应.json
（也支持直接喂 stdin / 打 stdout，方便手测）

请求
    {"op": "start"}                                  开一局新牌（服务器建库、发牌）
    {"op": "state",   "seat": 0}                     只取状态
    {"op": "advance"}                                让当前该摸牌的人摸牌（服务器的锅）
    {"op": "act",     "seat": 0, "action": "discard", "tile": "1m"}
                                                     做动作；能不能做、结果如何都由服务器说了算
    {"op": "pass",    "seat": 0}                     见逃
    （下面几个是「不入库」的纯判定，给客户端做界面提示用，规则仍然是同一份）
    {"op": "tenpai",  "seat": 0, "hand": [...], "melds": [...], "drawn": "1m"}
    {"op": "furiten", "seat": 0, "hand": [...], "melds": [...], "discards": [...]}
    {"op": "ron",     "seat": 0, "hand": [...], "melds": [...], "tile": "1p", "discards": [...]}
    {"op": "judge",   "seat": 0, "hand": [...], "melds": [...], "tile": "1p", "tsumo": true}

响应（永远是这个形状）
    {"ok": true, "state": {...}, "events": [...], "result": {...}|null, "error": ""}
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

sys.stdout.reconfigure(encoding="utf-8") if hasattr(sys.stdout, "reconfigure") else None

from db import DB                                        # noqa: E402
import lobby as lobby_mod                                # noqa: E402
import skills                                            # noqa: E402
from game import Game, RuleError                         # noqa: E402
import game as game_mod                                  # noqa: E402
import bot_ai                                           # 人机打牌 AI（kobalab/majiang-ai 移植）                                  # noqa: E402
from rules import agari, tenpai, wallmodel                # noqa: E402
from tiles import counts_of, parse_hand, sort_tiles      # noqa: E402

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "mahjong.db")
LOCAL_KEY = "local_round_id"
LEASE_KEY = "seat_lease_%d"      # 每个座位一条租约（谁在操作这个座位）
RESULT_CONFIRM_KEY = "result_confirm_%d"  # round_id -> 已确认结算的座位数组
RESULT_PLAYERS_KEY = "result_players_%d"  # round_id -> 本次需要手动确认的真人座位
LEASE_TTL = 12.0                 # 秒：这么久没发过请求，就认为这个窗口关了 → 交回 AI
# ★ 客户端进程号只有「服务端和客户端在同一台机器」时才有意义。
#   单机多窗口（本机 ServerBridge）＝ 进程查得到，用 pid 判活最快；
#   联机（net_server）＝ 玩家在别的机器上，他的 pid 在这台服务器上根本不存在，
#   拿它判活会得出「人都走了」→ 4 个人同时进房全撞 0 号位（已实测复现）。
#   net_server 启动时会把它关掉。
LEASE_PID_LOCAL_ONLY = True
NICKNAMES = ["我", "下家", "对家", "上家"]                 # 座位 0/1/2/3 = 我 / 右 / 上 / 左


# ────────────────────────── 小工具 ──────────────────────────

def _get_round_id(db: DB) -> int | None:
    row = db._row("SELECT value FROM meta WHERE key=?", (LOCAL_KEY,))
    return int(row["value"]) if row else None


def _set_round_id(db: DB, round_id: int) -> None:
    with db.tx():
        db.conn.execute("INSERT INTO meta(key, value) VALUES(?,?) "
                        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (LOCAL_KEY, str(round_id)))


def _game(db: DB, round_id: int, rules: dict | None = None) -> Game:
    g = Game(db, round_id, rules)
    # 看破只问「真的有人在操作」的座位：AI 不发动技能，也不会回答看破，
    # 问它就等于把对局永久挂起（单窗口测试必踩）。
    try:
        g.human_seats = _human_seats(db)
    except Exception:                                    # noqa: BLE001
        g.human_seats = None
    return g


# ────────────────────────── 座位租约（多窗口） ──────────────────────────
# 一个座位只要有「活着」的客户端在操作，服务器就不替它代打；
# 客户端关掉/卡死超过 LEASE_TTL 秒，这个座位自动交回给服务器代打（AI）。

def _pid_alive(pid: int) -> bool:
    """这个进程还在不在（Windows 用 OpenProcess 查退出码；查不了就当活着）。"""
    if pid <= 0:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    try:
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not h:
            # 5 = ERROR_ACCESS_DENIED：进程还在，只是没权限查（比如以管理员身份启动的那个窗口）
            return int(k32.GetLastError()) == 5
        try:
            code = ctypes.c_ulong()
            if not k32.GetExitCodeProcess(h, ctypes.byref(code)):
                return True                     # 查不到就保守当作活着
            return int(code.value) == STILL_ACTIVE
        finally:
            k32.CloseHandle(h)
    except Exception:                                    # noqa: BLE001
        return True


def _lease_value(pid=None) -> str:
    """租约格式：'时间戳' 或 '时间戳:进程号'（老数据没有进程号）。"""
    try:
        p = int(pid) if pid is not None else 0
    except (TypeError, ValueError):
        p = 0
    if p > 0 and not LEASE_PID_LOCAL_ONLY:
        p = 0
    if p > 0 and not _pid_alive(p):
        # ★ 这个进程号在本机不存在 → 客户端在**别的机器**上（公网/局域网联机）。
        #   跨机器的 pid 毫无意义，记下来只会让 _human_seats() 误判成「人已经走了」。
        #   不记它 → 改按时间判活（LEASE_TTL = 12 秒，客户端每 2 秒就有一次请求，够用）。
        p = 0
    return f"{time.time():.3f}:{p}" if p > 0 else f"{time.time():.3f}"


def _touch_lease(db: DB, seat: int, pid=None) -> None:
    """这个座位刚有人发请求 → 续租（顺便记下是哪个进程）。"""
    with db.tx():
        db.conn.execute("INSERT INTO meta(key, value) VALUES(?,?) "
                        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (LEASE_KEY % seat, _lease_value(pid)))


def _stalest_seat(db: DB) -> int:
    """四个座位都「看起来有人」时，挑租约最旧的那个。

    ★ 现场踩过：死掉的窗口留下的 pid 可能被别的程序重用 → 这个座位永远算「有人在坐」，
      四个都这样就再也拿不到空位。以前退回「你想要的座位」，于是多开的窗口全撞在 0 号位。
    """
    best, best_ts = 0, None
    for s in range(4):
        row = db._row("SELECT value FROM meta WHERE key=?", (LEASE_KEY % s,))
        ts = 0.0
        if row:
            try:
                ts = float(str(row["value"]).partition(":")[0])
            except ValueError:
                ts = 0.0
        if best_ts is None or ts < best_ts:
            best, best_ts = s, ts
    return int(best)


def _human_seats(db: DB) -> set:
    """现在「有人在操作」的座位。

    ★ 光看时间不够：编辑器里点停止 / 强杀进程时不会给客户端机会发请求，
      12 秒内重新 F5 就会「继承」上一次的进度。
      所以租约里带上进程号 —— 进程不在了，这个座位立刻算「关掉了」。
    """
    now = time.time()
    out = set()
    for s in range(4):
        row = db._row("SELECT value FROM meta WHERE key=?", (LEASE_KEY % s,))
        if not row:
            continue
        try:
            ts_txt, _, pid_txt = str(row["value"]).partition(":")
            ts = float(ts_txt)
        except ValueError:
            continue
        if pid_txt:
            try:
                alive = _pid_alive(int(pid_txt))
            except ValueError:
                alive = True
            if not alive:
                continue                        # 进程已经没了 → 这个座位算空着
            # 进程还活着 → 就算「有人在操作」，不管多久没发请求。
            # （玩家开着技能面板想 30 秒，不该被别的窗口当成 AI 代打）
            out.add(s)
            continue
        if now - ts >= LEASE_TTL:
            continue                            # 老数据没有进程号：只能按时间算
        out.add(s)
    # ★ 人机座位永远不算「真人」。
    #   人机本身不写租约，但只要曾经有窗口坐过那个座位（4 窗口测试 / 座位串过），
    #   残留租约+持续请求就会让它一直算真人 → 服务端不敢替它摸切/跳过技能
    #   → 轮到人机时整桌卡死（2026-11-01 现场：humans 变成 [0,1,2,3]）。
    try:
        out -= set(lobby_mod.bot_seats(db))
    except Exception:                                    # noqa: BLE001
        pass
    return out


def op_join(db: DB, req: dict) -> dict:
    """客户端认领一个座位（本地多窗口测试用）。

    - 认领后这个座位就归人操作；没人认领的座位继续由服务器代打（AI）。
    - 想认领的座位已经有人了，就顺延到下一个空位（force=true 则强行认领）。
    - 还没有牌局、或者上一局已经结束 → 顺手开新的一局；否则接上当前这一局。

    ★ 整个「看谁在座 → 挑座位 → 记租约 → 必要时开局」必须在一个事务里做完
      （BEGIN IMMEDIATE 会把并发的几个窗口排成一队）。不然四个窗口同时启动时，
      大家都看到「没人坐」，于是都认领 0 号位、甚至各自开一局 —— 座位重复、数据不同步。
    """
    raw = req.get("seat", -1)
    with db.tx():
        humans = _human_seats(db)
        free = [s for s in range(4) if s not in humans]
        if raw is None or int(raw) < 0 or int(raw) > 3:
            # 没指定座位 → 自动给一个没人坐的（几个窗口同时启动时各拿一家）
            seat = free[0] if free else _stalest_seat(db)
        else:
            want = int(raw) % 4
            if want in humans and not req.get("force"):
                # ★ 关键：humans 里那个「有人」可能就是我本人（大厅刚认领过座位，
                #   进牌桌时要坐同一个位子）。以前一律当"别人占着"，于是把自己
                #   挤到了下一个空位 —— 大厅选的是 0 号位的卡，进牌桌却坐 1 号位，
                #   看到的是人机的卡（2026-11-01 现场）。
                if req.get("keep") or humans == {want}:
                    seat = want
                else:
                    # 真的有人想让的座位 → 找空位；四个都有人就抢租约最旧的
                    seat = free[0] if free else _stalest_seat(db)
            else:
                seat = want
        _touch_lease(db, seat, req.get("pid"))
        rid = _get_round_id(db)
        if rid is not None:
            row = db._row("SELECT status FROM rounds WHERE round_id=?", (rid,))
            if not row or row["status"] != "playing":
                rid = None
        created = False
        if rid is None:
            # 上一局已经结束：交给 op_next 按亲家/本场/场风推进；
            # 一场都还没打过时 op_next 自己会走 op_start。
            rid = op_next(db, {"seat": seat})["round_id"]
            created = True
    rows = db._rows("SELECT tile FROM round_wall WHERE round_id=? ORDER BY seq", (rid,))
    return {"ok": True, "seat": seat, "round_id": rid, "created": created,
            "humans": sorted(_human_seats(db)),
            "state": _state(db, rid, seat), "events": [], "result": None,
            "wall": [r["tile"] for r in rows]}


def _tiles(req: dict, key: str = "hand") -> list[str]:
    v = req.get(key) or []
    if isinstance(v, str):
        return parse_hand(v)
    return [str(t) for t in v]


def _melds(req: dict) -> list[dict]:
    out = []
    for m in req.get("melds") or []:
        if isinstance(m, dict):
            out.append({"kind": m.get("kind", "pon"), "tiles": list(m.get("tiles") or []),
                        "called_tile": m.get("called_tile"), "from_seat": m.get("from_seat", 0),
                        "rot_index": m.get("rot_index", 0)})
        elif isinstance(m, str) and ":" in m:                  # "pon:111z" 这种简写
            kind, spec = m.split(":", 1)
            out.append({"kind": kind, "tiles": parse_hand(spec), "called_tile": None,
                        "from_seat": 0, "rot_index": 0})
    return out


def _state(db: DB, round_id: int | None, seat: int | None) -> dict | None:
    if round_id is None:
        return None
    try:
        return _game(db, round_id).state_for(seat)
    except ValueError:
        return None


# ────────────────────────── 各个 op ──────────────────────────

def _local_users(db: DB) -> list[int]:
    """本地客户端固定的 4 个账号（座位 0/1/2/3）。"""
    ids = []
    for nick in NICKNAMES:
        u = db.find_user(nick)
        ids.append(u["user_id"] if u else db.create_user(nick, is_guest=True))
    return ids


def _local_room(db: DB) -> dict:
    """本地客户端固定一个房间；没有就建一个并把 4 个账号坐满。"""
    row = db._row("SELECT value FROM meta WHERE key='local_room_id'")
    if row:
        rid = int(row["value"])
        room = db._row("SELECT * FROM rooms WHERE room_id=?", (rid,))
        if room and len(db._rows("SELECT 1 FROM room_seats WHERE room_id=?", (rid,))) == 4:
            return {"room_id": rid, "room_code": room["room_code"]}
    ids = _local_users(db)
    room = db.create_room(ids[0], mode="hanchan")
    for uid in ids[1:]:
        db.join_room(room["room_code"], uid)
    with db.tx():
        db.conn.execute("INSERT INTO meta(key, value) VALUES('local_room_id', ?) "
                        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (str(room["room_id"]),))
    return room


def _snapshot_round_cards(db: DB, round_id: int) -> None:
    """开局把「四家选的 5 张卡」抄进本局的 meta，供 skills.order_of 读。"""
    try:
        lobby = lobby_mod.load(db)
        data = {}
        for s in range(4):
            st = lobby["seats"][s]
            order = [int(v) for v in (st.get("order") or [])]
            if len(order) < 5:
                order = [int(v) for v in (st.get("picks") or [])][:5]
            data[str(s)] = order
        with db.tx():
            db.conn.execute(
                "INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)",
                ("round_cards_%d" % int(round_id), json.dumps(data, ensure_ascii=False)))
    except Exception:                                    # noqa: BLE001
        pass


def op_start(db: DB, req: dict) -> dict:
    """开一局新牌：房间/比赛都复用，这里只开新的「一局」。"""
    room = _local_room(db)
    row = db._row("SELECT match_id FROM matches WHERE room_id=? AND status='playing' "
                  "ORDER BY match_id DESC LIMIT 1", (room["room_id"],))
    match_id = int(row["match_id"]) if row else db.start_match(room["room_id"], seed=req.get("seed"))
    round_id = db.start_round(match_id, wind=str(req.get("wind", "dong")),
                              number=int(req.get("number", 1)),
                              honba=int(req.get("honba", 0)),
                              dealer_seat=int(req.get("dealer", 0)),
                              riichi_sticks=int(req.get("riichi_sticks", 0)))
    _set_round_id(db, round_id)
    _snapshot_round_cards(db, round_id)      # ★ 卡序抄进本局，之后不看大厅
    g = _game(db, round_id)
    g.start()
    seat = int(req.get("seat", 0))
    rows = db._rows("SELECT tile FROM round_wall WHERE round_id=? ORDER BY seq", (round_id,))
    return {"ok": True, "state": g.state_for(seat), "events": [{"event": "round_start"}],
            "result": None, "round_id": round_id,
            "wall": [r["tile"] for r in rows]}


def _result_confirmed(db: DB, round_id: int) -> set[int]:
    row = db._row("SELECT value FROM meta WHERE key=?", (RESULT_CONFIRM_KEY % int(round_id),))
    if not row:
        return set()
    try:
        return {int(x) for x in (json.loads(str(row["value"])) or []) if int(x) in range(4)}
    except (TypeError, ValueError, json.JSONDecodeError):
        return set()


def _result_players(db: DB, round_id: int) -> set[int]:
    row = db._row("SELECT value FROM meta WHERE key=?", (RESULT_PLAYERS_KEY % int(round_id),))
    if row:
        try:
            return {int(x) for x in (json.loads(str(row["value"])) or []) if int(x) in range(4)}
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
    humans = set(_human_seats(db))
    if humans:
        with db.tx():
            db.conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)",
                            (RESULT_PLAYERS_KEY % int(round_id), json.dumps(sorted(humans))))
    return humans


def _result_confirm_state(db: DB, round_id: int, seat: int = -1) -> dict:
    humans = _result_players(db, round_id)           # 首次读取后锁定，避免租约轮询抖动
    live = set(_human_seats(db))                     # ★ 现在真正还在发请求的座位
    required = set(range(4))
    confirmed = _result_confirmed(db, round_id)
    confirmed |= (required - humans)                 # 从没在线过的座位（AI / 人机）→ 自动确认
    # ★ 锁定时在线、现在已经没有租约的座位也算确认。
    #   现场（2026-11-01）：界面一直显示 3/4，最后一个人永远不点 —— 因为
    #   _result_players 在某一刻把「当时有过租约的座位」锁定成了 humans，
    #   那些座位后来其实没人了（人机 / 关掉的窗口），却还在等它确认。
    confirmed |= (humans - live)
    return {"round_id": int(round_id), "confirmed": sorted(confirmed),
            "required": sorted(required), "ready": required.issubset(confirmed),
            "humans": sorted(humans), "live": sorted(live)}


def op_result_confirm(db: DB, req: dict) -> dict:
    """结算确认屏障：四个人（有人操作的四座）全部确认后才允许 next。"""
    seat = int(req.get("seat", -1))
    rid = _get_round_id(db)
    if rid is None:
        return {"ok": False, "error": "没有牌局"}
    row = db._row("SELECT status FROM rounds WHERE round_id=?", (rid,))
    if row is None or str(row["status"]) == "playing":
        return {"ok": False, "error": "本局还没结束"}
    with db.tx():
        confirmed = _result_confirmed(db, rid)
        players = _result_players(db, rid)
        if seat in range(4):
            confirmed.add(seat)
            players.add(seat)
        db.conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)",
                        (RESULT_PLAYERS_KEY % rid, json.dumps(sorted(players))))
        db.conn.execute("INSERT INTO meta(key,value) VALUES(?,?) "
                        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (RESULT_CONFIRM_KEY % rid, json.dumps(sorted(confirmed))))
    st = _result_confirm_state(db, rid, seat)
    return {"ok": True, "result_confirm": st, "state": _state(db, rid, seat),
            "events": [], "result": None}


def op_next(db: DB, req: dict) -> dict:
    """开下一局：接着上一局的结果算「谁坐庄、几本场、东几局」。

    规则以后细化，但「用什么推下一局」这件事必须在服务端，客户端只负责说一句「下一局」：
      · 亲家赢（自摸/荣和）→ 连庄：同一个亲家，本场 +1
      · 别家赢             → 亲家下移一位，本场归 0，局数 +1
      · 荒牌流局           → 本场 +1；亲家听牌就连庄，没听才亲家下移、局数 +1
      · 途中流局           → 本场不加、亲家不变、局数不变（这一局重来）
      · 立直供托           → 荒牌流局留下的供托带到下一局；和牌时被赢家收走
      · 局数超过 4         → 东风战直接整场结束；半庄推进场风（东→南→西→北）、局数回 1
      · 上一局还没打完     → 只有 force=true 才开（调试用「重开这一局」），否则什么也不做
    """
    seat = int(req.get("seat", -1))
    rid = _get_round_id(db)
    row = db._row("SELECT * FROM rounds WHERE round_id=?", (rid,)) if rid else None
    if row is not None and str(row["status"]) != "playing" \
            and not req.get("force") and not req.get("f2"):
        barrier = _result_confirm_state(db, int(rid), seat)
        # 屏障只在「已经有玩家点过确认」之后生效：
        #   · 没人确认时保持老的直接 next（服务端脚本 / 调试 / 单机跑局不会被卡死）
        #   · 一旦有人确认，就必须集齐本次真人座位，防止第一个点的人把别人甩下
        if _result_confirmed(db, int(rid)) and not bool(barrier.get("ready", False)):
            return {"ok": True, "waiting_confirm": True, "result_confirm": barrier,
                    "state": _state(db, rid, None if seat < 0 else seat), "events": [],
                    "result": None, "round_id": rid, "created": False,
                    "humans": sorted(_human_seats(db))}
    if row is None:                                     # 一局都还没开过 → 直接开第一局
        started = op_start(db, req)
        started["created"] = True
        return started
    if row["status"] == "playing" and not req.get("force") and not req.get("f2"):
        return {"ok": True, "state": _state(db, rid, None if seat < 0 else seat), "events": [],
                "result": None, "round_id": rid, "created": False,
                "humans": sorted(_human_seats(db))}
    # 整场已经打完了（比如东风战打满）→ 再按「下一局」就是开新的一场
    mrow = db._row("SELECT status, room_id FROM matches WHERE match_id=?", (row["match_id"],))
    if mrow and mrow["status"] != "playing":
        started = op_start(db, req)
        started["created"] = True
        started["new_match"] = True
        return started

    sticks = int(row["riichi_sticks"] or 0)             # 上一局的立直供托（荒牌流局才留得下来）
    f2_skip = bool(req.get("f2")) and row["status"] == "playing"
    if f2_skip:
        # F2 调试：当前局直接按「无人听牌的荒牌流局」结束，但不加本场，
        # 只让亲家下移、场次 +1（东二 2 本场 → 东三 2 本场）。
        db.finish_round(rid, "ryuukyoku")
        row = db._row("SELECT * FROM rounds WHERE round_id=?", (rid,))
        sticks = int(row["riichi_sticks"] or 0)
    if row["status"] == "playing":                      # force：这一局重开（条件不变）
        wind, number, honba, dealer = row["wind"], row["number"], row["honba"], row["dealer_seat"]
    else:
        result = row["result"] or ""
        dealer, honba, number, wind = row["dealer_seat"], row["honba"], row["number"], row["wind"]
        if f2_skip:
            dealer = (dealer + 1) % 4
            number += 1                                  # 本场保持原值
        elif result in ("tsumo", "ron"):
            if row["winner_seat"] == dealer:
                honba += 1                              # 亲家和了 → 连庄
            else:
                dealer = (dealer + 1) % 4               # 子家和了 → 亲家下移
                number += 1
                honba = 0
        else:                                           # 流局
            if result == "ryuukyoku":                   # 荒牌流局：本场 +1
                honba += 1
                # 亲家听牌 → 连庄（亲家/局数都不动）；没听 → 亲家下移一位、局数 +1
                g = Game(db, rid)
                if not agari.is_tenpai(counts_of(g.hand13(dealer)), g.melds(dealer)):
                    dealer = (dealer + 1) % 4
                    number += 1
            # 途中流局（九种九牌/四风连打/四家立直/四杠散了/三家和了）：
            #   本场不加、亲家不变、局数不变 —— 就是这一局重来
            #   （立直供托已经在 Game._ryuukyoku 里退还本人了）
        if number > 4:                                  # 一圈打完了
            mode = (db._row("SELECT mode FROM rooms WHERE room_id=?",
                            (mrow["room_id"],)) or {}).get("mode", "hanchan")
            # 东风战打完东四结束；半庄打完南四结束；西/北风只有更长赛制才会用到
            finished = (mode == "east_only") or (mode == "hanchan" and wind == "nan")
            if finished:
                # ★ 幂等：finish_match 会给天梯分加减，重复调用会重复加
                if str(row["status"]) == "finished":
                    final = _match_final(db, int(row["match_id"]))
                else:
                    final = db.finish_match(row["match_id"])
                state = _state(db, rid, None if seat < 0 else seat)
                return {"ok": True, "state": state, "events": [], "result": None,
                        "round_id": rid, "created": False, "match_finished": True,
                        "final": final, "final_rank": _final_rank(final),
                        "confirmed": sorted(_match_confirmed(db, int(row["match_id"]))),
                        "match_id": int(row["match_id"]),
                        "humans": sorted(_human_seats(db))}
            wind = {"dong": "nan", "nan": "xi", "xi": "bei", "bei": "dong"}.get(wind, "dong")
            number = 1
    started = op_start(db, {**req, "wind": wind, "number": number,
                            "honba": honba, "dealer": dealer,
                            "riichi_sticks": sticks})
    started["created"] = True
    started["next_of"] = rid
    return started


MATCH_CONFIRM_KEY = "match_confirm_%d"   # match_id -> 已确认终局的座位
MATCH_CLEARED_KEY = "match_cleared_%d"   # match_id -> "1"（房间数据已清）


def _final_rank(final) -> list:
    """{座位: 分数} → 1/2/3/4 名（分数从高到低；同分按座位号）。"""
    try:
        rows = [(int(s), int(v)) for s, v in (final or {}).items()]
    except (TypeError, ValueError):
        return []
    rows.sort(key=lambda x: (-x[1], x[0]))
    return [{"seat": s, "score": sc, "rank": i + 1} for i, (s, sc) in enumerate(rows)]


def _match_id_of(db: DB) -> int | None:
    rid = _get_round_id(db)
    if rid is None:
        return None
    row = db._row("SELECT match_id FROM rounds WHERE round_id=?", (int(rid),))
    return int(row["match_id"]) if row else None


def _match_final(db: DB, mid: int) -> dict:
    row = db._row("SELECT final_json FROM matches WHERE match_id=?", (int(mid),))
    if not row or not row["final_json"]:
        return {}
    try:
        return json.loads(str(row["final_json"])) or {}
    except (ValueError, TypeError):
        return {}


def _match_confirmed(db: DB, mid: int) -> set:
    row = db._row("SELECT value FROM meta WHERE key=?", (MATCH_CONFIRM_KEY % int(mid),))
    if not row:
        return set()
    try:
        return {int(x) for x in (json.loads(str(row["value"])) or []) if int(x) in range(4)}
    except (ValueError, TypeError):
        return set()


def _match_finished_info(db: DB, rid) -> dict:
    """这一局所属的半庄已经打完了吗？是 → 带上终局排名（供轮询兜底）。"""
    if rid is None:
        return {}
    row = db._row("SELECT m.match_id AS mid, m.status AS st, m.final_json AS fj "
                  "FROM rounds r JOIN matches m ON m.match_id = r.match_id "
                  "WHERE r.round_id=?", (int(rid),))
    if not row or str(row["st"]) != "finished":
        return {}
    try:
        final = json.loads(str(row["fj"])) if row["fj"] else {}
    except (ValueError, TypeError):
        final = {}
    mid = int(row["mid"])
    return {"match_finished": True, "final": final, "final_rank": _final_rank(final),
            "match_id": mid, "confirmed": sorted(_match_confirmed(db, mid))}


def op_match_confirm(db: DB, req: dict) -> dict:
    """半庄终局确认：四家都点过确认 → 清房间数据，客户端各自回大厅。"""
    seat = int(req.get("seat", -1))
    mid = _match_id_of(db)
    if mid is None:
        # 数据已经被清掉了（有人先确认完）→ 直接告诉客户端「都结束了，可以退」
        return {"ok": True, "all_done": True, "confirmed": [0, 1, 2, 3],
                "final_rank": [], "cleared": True}
    final = _match_final(db, mid)
    rank = _final_rank(final)
    cleared = False
    with db.tx():
        cur = _match_confirmed(db, mid)
        if 0 <= seat <= 3:
            cur.add(seat)
        db.conn.execute("INSERT INTO meta(key,value) VALUES(?,?) "
                        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (MATCH_CONFIRM_KEY % mid, json.dumps(sorted(cur))))
        humans = set(_human_seats(db))
        all_done = bool(humans) and humans.issubset(cur)
        # ★ 全员确认 → 清这个房间的对局数据（每个 match 只清一次）
        if all_done:
            flag = db._row("SELECT value FROM meta WHERE key=?", (MATCH_CLEARED_KEY % mid,))
            if not flag:
                db.conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)",
                                (MATCH_CLEARED_KEY % mid, "1"))
                cleared = True
    if cleared:
        try:
            op_wipe(db, {"seat": seat, "force": True})
            log_line = "[match] %d 号半庄终局，四家已确认 → 房间数据已清理" % mid
            print(log_line, flush=True)
        except Exception as e:                              # noqa: BLE001
            print("[match] 清理失败：%s" % e, flush=True)
    return {"ok": True, "all_done": bool(all_done), "confirmed": sorted(cur),
            "final_rank": rank, "cleared": cleared, "match_id": mid,
            "state": None, "events": [], "result": None}


def op_new_hanchan(db: DB, req: dict) -> dict:
    """测试用：把当前场结束，重新开一个半庄（东一 0 本场，0 号位坐庄）。"""
    room = _local_room(db)
    seat = max(0, min(3, int(req.get("seat", 0))))
    with db.tx():
        for m in db._rows("SELECT match_id FROM matches WHERE room_id=? AND status='playing'",
                          (room["room_id"],)):
            db.finish_match(int(m["match_id"]))
    match_id = db.start_match(room["room_id"], seed=req.get("seed"))
    with db.tx():
        # 新半庄 = 人物卡状态从零开始：清掉「发动过 / 寿命」记录
        db.conn.execute("DELETE FROM meta WHERE key='char_use'")
        db.conn.execute("DELETE FROM meta WHERE key='skill_log'")
    round_id = db.start_round(match_id, "dong", 1, honba=0, dealer_seat=0,
                              seed=req.get("seed"))
    _set_round_id(db, round_id)
    g = _game(db, round_id)
    g.start()
    rows = db._rows("SELECT tile FROM round_wall WHERE round_id=? ORDER BY seq", (round_id,))
    return {"ok": True, "seat": seat, "round_id": round_id, "created": True,
            "humans": sorted(_human_seats(db)), "state": g.state_for(seat),
            "events": [{"event": "round_start"}], "result": None,
            "wall": [r["tile"] for r in rows], "new_hanchan": True}


def _state_ver(st) -> str:
    """state 的指纹：客户端拿它判断「和上次一样吗」，一样就不用再传 21KB。"""
    try:
        raw = json.dumps(st, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return ""
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]


def _auto_drive(db: DB, g, seat) -> list:
    """★ 通用兜底：轮次落在「没人在操作」的座位 → 服务器替他走一步。

    现场事故（2026-11-01）：Card25 S2『宝牌的集合』换完牌，phase 回到 discard，
    但轮次还在「刚摸牌的那家」身上。如果那是人机，客户端只在 claim/deal_skill
    阶段才会发 op=step，于是没人触发他打牌 → 整桌永久卡死
    （日志表现：`act ... 现在不能 discard（可选：[]）` 一直刷）。

    放在 poll 里做：客户端每 0.5 秒必问一次，等于给所有技能兜了一层底。
    turn 是活人的时候 _drive_others 会立刻 break，开销可忽略。
    """
    try:
        if getattr(g, "round_phase", "") != "play" or g.phase == "ended":
            return []
        human = int(seat) if isinstance(seat, int) else -1
        # 每次 poll 只推 2 步：单次请求保持轻，剩下的交给下一次 poll
        return _drive_others(db, g, human, 2)
    except Exception:                                    # noqa: BLE001
        return []


def _deal_catchup(g, max_steps: int = 3) -> int:
    """配牌兜底：客户端没人推进时，服务端自己往前推几步。

    ★ 现场事故（2026-11-01）：客户端只有「座位号最小的真人」负责推配牌
      （main.gd 的 _is_deal_driver）。而状态没变化时服务端回 {"same": true}
      不带 humans 字段 → 客户端拿不到「谁在线」，判断退化成「只认 0 号位」。
      1 个人玩 + 3 个人机时人是 1 号位 → 没人推 → 一张牌都不发，界面卡死。

    deal_step 是按 deal_i 顺着计划走的，重复调用既不会重复发牌也不会跳步，
    所以这里由服务端补推是安全的（客户端正常推的时候，两边最多各推一步，
    由事务串行化，进度以 deal_i 为准）。
    """
    n = 0
    try:
        while n < max_steps and getattr(g, "round_phase", "") == "deal":
            g.deal_step()
            n += 1
    except Exception:                                    # noqa: BLE001
        pass
    return n


# ── A2/A13：任何「只能某一家答」的询问，超时一律自动放行 ──────────────
#   今晚踩过的：配牌技能窗口、向听换牌流程、海神还牌。一个人没点就锁死全桌。
#   每分钟被 op_poll 调几十次，每个 *_timeout() 内部自己判「还没到点 → 返回 False」。
_BOT_TIME = 0.0


def _tick_timeouts(g) -> list:
    """把各种挂起询问推到「超时就跳过」。全部 try/except：缺函数/状态不对都不影响。"""
    out = []
    for name in ("deal_skill_timeout", "deal_flow_timeout", "haishin_timeout",
                 "kangpo_timeout", "pofa_timeout", "c42s2_timeout",
                 "youyin_meld_timeout", "future_timeout", "c35_timeout",
                 "c40s2_timeout", "c45s2_timeout", "c26_timeout", "act_timeout"):
        fn = getattr(g, name, None)
        if fn is None:
            continue
        try:
            r = fn()
        except Exception:
            continue
        if r:
            out.append({"event": "timeout", "what": name, "ret": r if isinstance(r, dict) else True})
    return out


def op_poll(db: DB, req: dict) -> dict:
    try:
        _rid_t = _get_round_id(db)
        if _rid_t:
            _tick_timeouts(_game(db, _rid_t))   # A2/A13: 挂起询问超时自动放行
    except Exception:
        pass
    """轻量轮询：客户端带上次的 ver，没变化就只回 {"same": true}。

    没变化时**不回 state**（几十字节），客户端直接用本地那份。
    """
    rid = req.get("round_id") or _get_round_id(db)
    seat = req.get("seat")
    seat = int(seat) if isinstance(seat, int) else None
    with db.tx():
        _g_poll = _game(db, rid)
        _deal_catchup(_g_poll)                 # ← 配牌没人推时由服务端补
        _auto_drive(db, _g_poll, seat)         # ← 轮次落在人机身上时替他走
        st = _state(db, rid, seat)
    ver = _state_ver(st)
    humans = sorted(_human_seats(db))
    if str(req.get("ver", "")) == ver:
        return {"ok": True, "state": None, "events": [], "result": None,
                "round_id": rid, "ver": ver, "same": True, "humans": humans}
    g = _game(db, rid)
    out = {"ok": True, "state": st, "events": [], "result": g.result,
           "round_id": rid, "ver": ver, "same": False, "humans": humans}
    out.update(_match_finished_info(db, rid))          # 半庄打完 → 带终局排名
    return out


def op_state(db: DB, req: dict) -> dict:
    rid = req.get("round_id") or _get_round_id(db)
    seat = req.get("seat")
    with db.tx():
        _deal_catchup(_game(db, rid))          # ← 同上：配牌兜底
        st = _state(db, rid, None if seat is None else int(seat))
        row = db._row("SELECT status FROM rounds WHERE round_id=?", (rid,)) if rid else None
        barrier = (_result_confirm_state(db, int(rid), -1 if seat is None else int(seat))
                   if row is not None and str(row["status"]) != "playing" else None)
    out = {"ok": True, "state": st, "events": [],
           "result": st and st.get("result"), "result_confirm": barrier,
           "round_id": rid, "humans": sorted(_human_seats(db))}
    out.update(_match_finished_info(db, rid))          # 半庄打完 → 带终局排名
    return out


def _auto_ai(db: DB) -> bool:
    """没有客户端连接的座位，要不要服务器替他摸切。

    Test.txt 的 [代打] 里写「关」就不代打（四家都必须有窗口）；
    没写 / 写「开」= 和以前一样，空座位由服务器摸切。
    """
    import testfile
    return testfile.auto_ai()


def _bot_discard(g, seat: int) -> str:
    """人机打牌：AI 选一张，但**必须**是服务端 legal 允许的牌。

    人机的手牌可能被别人的技能换掉 / 暗置 / 加杠，所以：
      · 每次都从 DB 现读手牌（bot_ai.choose_discard 里读的就是 g.hand）
      · 结果先和 legal_actions 对一遍，对不上就退回「摸切 → 手里第一张」
      · 全程 try/except，绝不因为「选牌失败」把整桌卡死
    """
    legal: list[str] | None = None
    try:
        for a in g.legal_actions(seat):
            if str(a.get("action")) == "discard":
                ts = a.get("tiles") or []
                if ts:
                    legal = [str(x) for x in ts]
                break
    except Exception:
        legal = None

    cand = ""
    try:
        cand = bot_ai.choose_discard(g, seat)
    except Exception:
        cand = ""

    def _norm(x: str) -> str:
        return ("5" + x[1]) if len(x) == 2 and x[0] == "0" else x

    drawn = ""
    hand: list[str] = []
    try:
        drawn = g.drawn_tile(seat) or ""
        hand = list(g.hand(seat) or [])
    except Exception:
        pass

    order = [cand, drawn] + hand
    for x in order:
        if not x:
            continue
        if legal is None:
            return x
        if x in legal:
            return x
        for y in legal:                       # 赤五 0m 和普通 5m 当同一种
            if _norm(y) == _norm(x):
                return y
    if legal:
        return legal[0]
    return hand[-1] if hand else ""


def _bot_skip_asks(g, bots) -> list[dict]:
    """人机被问到任何技能 → 一律跳过（用户口径 2026-11-01）。

    只认「这一笔询问确实在等人机回答」的那几种，全部包 try/except；
    返回本次产生的事件（非空 = 有进展，主循环继续推）。
    """
    ev: list[dict] = []
    bots = set(int(b) for b in bots)

    # ① 配牌技能窗口（deal_wait 里等人的座位）
    try:
        if getattr(g, "phase", "") == "deal_skill":
            for s in sorted(set(getattr(g, "deal_wait", set()) or set()) & bots):
                try:
                    g.deal_action(s, "skip")
                except Exception:
                    pass
    except Exception:
        pass

    # ② 复制（c41）：池子里有东西就是在等人挑
    try:
        for s in sorted(set((getattr(g, "c41_ask", {}) or {}).keys()) & bots):
            try:
                ev.append(g.c41s1_skip(s))
            except Exception:
                pass
    except Exception:
        pass

    # ③ 看破（kangpo）：被问的人里有人机 → 放行
    try:
        for s in sorted(bots):
            # ★ kangpo_list() 是「这一局所有技能」的清单（给玩家挑一个剔除），
            #   不是待答询问！以前拿它判「有人机在等看破」→ 永远为真 →
            #   主循环每次都 continue，人机一张牌都打不出去（牌河不增长）。
            try:
                mine = g.act_ask_view(int(s))
            except Exception:
                mine = []
            if mine:
                try:
                    ev.append(g.kangpo_skip(s))
                except Exception:
                    pass
    except Exception:
        pass

    # ④ 夺目（c42s2）：挂起的结算在等几家回答
    try:
        st = getattr(g, "c42s2_settle", None)
        if isinstance(st, dict):
            for s in sorted(set(st.get("waiting") or []) & bots):
                try:
                    ev.append(g.c42s2_answer(s, -1))
                except Exception:
                    pass
    except Exception:
        pass

    # ⑤ 破发（pofa）：被问的人机直接「过」
    try:
        pd = getattr(g, "pofa_pending", None)
        if isinstance(pd, dict):
            for s in sorted(set(pd.get("waiting") or []) & bots):
                try:
                    ev.append(g.pofa_pass(s))
                except Exception:
                    pass
    except Exception:
        pass

    # ⑥ 面板类技能：人机持有的话，面板会一直挂着等人点 → 用各自的「跳过/超时」
    #    这里全部「先确认这一手确实是人机在等」，再调服务端那条安全的默认路径。
    def _probe(fn, s):
        try:
            return bool(fn(s))
        except Exception:
            return False

    # 三色同刻 / 三色同顺（c35）
    try:
        for s in sorted(bots):
            if _probe(lambda x: g.c35_view(x), s):
                try:
                    g.c35_skip(s)
                    ev.append({"event": "bot_skip", "seat": s, "what": "c35"})
                except Exception:
                    pass
    except Exception:
        pass
    # 替身（c45s2）：只有「真的有人在等第二位指定切牌」时才兜底
    #   ★ 以前写 `if v:`（view 永远返回非空字典）→ 每轮都给每个机 append 一个
    #     空操作事件 c45s2_skip → _drive_others 永远 continue → 人机一步都走不了
    #     （2026-11-02 现场：【命中】暗置打出后整桌卡死）。
    try:
        for s in sorted(bots):
            v = None
            try:
                v = g.c45s2_view(s)
            except Exception:
                v = None
            w = v.get("wait") if isinstance(v, dict) else None
            if isinstance(w, dict):
                try:
                    ev.append(g.c45s2_auto())
                except Exception:
                    pass
    except Exception:
        pass
    # 恶听（c40s2）
    try:
        for s in sorted(bots):
            tg = -1
            try:
                tg = int(g.c40s2_view_target(s))
            except Exception:
                tg = -1
            if tg >= 0:
                try:
                    ev.append(g.c40s2_auto())
                except Exception:
                    pass
    except Exception:
        pass
    # 未来（c24s2 排序）
    try:
        for s in sorted(bots):
            ft = None
            try:
                ft = g.future_view(s)
            except Exception:
                ft = None
            if ft:
                try:
                    g.future_abort()
                    ev.append({"event": "bot_skip", "seat": s, "what": "future"})
                except Exception:
                    pass
    except Exception:
        pass
    # 友引（副露摊面子）
    try:
        if getattr(g, "youyin_meld_seat", -1) in bots:
            try:
                ev.append(g.youyin_meld_skip())
            except Exception:
                pass
    except Exception:
        pass
    # 向听（c30s1）/ 新手运（c32s1）：各自有「交牌/换牌」两步，超时会自动走
    try:
        for s in sorted(bots):
            if _probe(lambda x: g.c30_ask_for(x) == x, s):
                try:
                    g.c30s1_auto(s)
                    ev.append({"event": "bot_skip", "seat": s, "what": "c30"})
                except Exception:
                    pass
    except Exception:
        pass
    try:
        for s in sorted(bots):
            if g.c32_give_target() == s:
                try:
                    ev.append(g.c32s1_auto(s))
                except Exception:
                    pass
    except Exception:
        pass
    # 宝牌的集合（c25s2）：人机必须换 → 用服务端自己的自动换
    try:
        for s in sorted(bots):
            if _probe(lambda x: g.c25s2_need(x) if hasattr(g, "c25s2_need") else False, s):
                try:
                    ev.append(g.c25s2_auto_swap(s))
                except Exception:
                    pass
    except Exception:
        pass
    return ev


def _drive_others(db: DB, g: Game, human: int, limit: int = 24) -> list[dict]:
    """不是人类玩家的位置，交给服务器自己摸打（简单打刚摸那张）。

    一直推到这个人为止：轮到他摸牌、轮到他打牌、或鸣牌窗口里等他作答。
    """
    if not _auto_ai(db):
        return []                           # 关掉代打：谁的座位谁自己动
    humans = _human_seats(db) | {human}     # human = 发起请求的这个窗口
    bots = {0, 1, 2, 3} - humans
    events: list[dict] = []
    for _ in range(limit):
        if g.phase == "ended":
            break
        # 人机被问到技能 → 全部跳过（配牌 / 复制 / 看破 / 夺目 / 破发）
        try:
            _skip_ev = _bot_skip_asks(g, bots)
        except Exception:
            _skip_ev = []
        if _skip_ev:
            events.extend(_skip_ev)
            continue
        p = getattr(g, "pending", None)
        if g.phase == "claim" and p:
            others = [s for s in p["options"] if s not in humans and s not in p["answers"]]
            if others:
                for s in others:
                    events.append(g.pass_claim(s))
                continue
            break                              # 等某个有人的座位作答（荣和/碰/吃/过）
        if g.turn in humans:
            break                              # 轮到有人的座位：摸牌或打牌都交给他
        if g.phase == "draw":
            events.append(g.advance())
            continue
        if g.phase == "discard":
            # ★ 人机不再无脑摸切：走 bot_ai（kobalab/majiang-ai 的思路）
            t0 = _bot_discard(g, int(g.turn))
            try:
                events.append(g.act(int(g.turn), "discard", tile=t0))
            except Exception:
                # 万一 AI 给的牌服务端不认（被换牌/暗置/加杠过）→ 退回摸切
                d = g.drawn_tile(g.turn) or ((g.hand(g.turn) or [""])[-1])
                events.append(g.act(int(g.turn), "discard", tile=d))
            continue
        break
    return events


def op_advance(db: DB, req: dict) -> dict:
    """人类玩家摸牌（客户端按「摸牌」时调）。"""
    rid = req.get("round_id") or _get_round_id(db)
    seat = int(req.get("seat", 0))
    g = _game(db, rid)
    events = _drive_others(db, g, seat, 2)
    if g.phase == "draw" and g.turn == seat and g.phase != "ended":
        events.append(g.advance())
    events += _drive_others(db, g, seat, 2)
    return {"ok": True, "state": g.state_for(seat), "events": events,
            "result": g.result, "round_id": rid}


def op_act(db: DB, req: dict) -> dict:
    """客户端发动作上来：服务器校验 + 执行 + 回最新状态。"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    action = str(req.get("action", ""))
    kw = {}
    if req.get("tile"):
        kw["tile"] = req["tile"]
    if req.get("tiles"):
        kw["tiles"] = _tiles(req, "tiles")
    if "riichi" in req:
        kw["riichi"] = bool(req["riichi"])
    if "c25_ok" in req:
        kw["c25_ok"] = bool(req["c25_ok"])
    events = []
    if action == "pass":
        events.append(g.pass_claim(seat))
    else:
        events.append(g.act(seat, action, **kw))
    # ★ 只推 1 步：让「我出牌」这条请求马上返回；其余三家由客户端下一次 poll 推进
    events += _drive_others(db, g, seat, 1)
    return {"ok": True, "state": g.state_for(seat), "events": events,
            "result": g.result, "round_id": rid}


# 多步技能：op=skill 只是开面板，真正结算在各自的确认 op 里
#   → 看破改在「玩家选完、效果还没生效」的那一刻询问
_GATE_AT_CONFIRM = set()             # 没有「只开面板」的技能了：都在配牌/结算那一步问

# 立直之后不许再动的技能：它们会改动「自己的手牌」（立直后手牌是锁死的）
_RIICHI_BLOCK_OPS = {
    "card05_swap", "card05_hide", "card09_swap", "card10_hand", "card10_meld",
    "press",
    "card11_swap", "card11s2_swap", "haishin_give", "haishin_swap", "c27s1_swap",
    "zhalie_swap", "diaoyu_force", "gift_swap", "xianfu_swap", "youyin_take",
    "shenshan_resolve", "swap",
}
# 立直之后仍可用：降神(oracle_*)、感知、枷锁、连接、浓雾、前路、加热、X神、
#   看破、深山开关、点燃、研究、传承


# 技能结算 op → (卡号, 技能号)。这些 op 执行前都要先问「看破」。
# ── 看破闸门：黑名单制 ───────────────────────────────────────────────
# 用户口径（2026-10）：
#   · **所有技能发动点都要问看破**。唯一例外是「结算类」技能。
#   · 结算类：Card10 S2「四喜」、Card01 S1「国标」（后者没有独立 op，走 op=act）。
#   · Card03 S1「自信」虽然是结算类效果，但发动点在配牌 → 要问，且问过一次后
#     就不能再被看破（ONCE_PAIRS 管）。
#   · 多步技能只在「第 1 步点确认」时问；后面的选牌/换牌/开关不再重复问。
#   · 询问类技能：点「确认发动」才问看破；点跳过/取消不问。
#   · Card05「策略」三段特殊：段1 压牌永不可看破；段2/段3 待按新规则实现。
#
# 所以这里反过来写：先列「明确不问的 op」，剩下的**默认全部要问**，
# 卡号/技能号在 _SKILL_OP_PAIRS 里给。import 时断言三张表正好覆盖 OPS 全集，
# 以后新增 op 忘登记会直接抛错（历史 bug：白名单漏了 deal_skill 等 8 个发动点）。
_NO_GATE_OPS = {
    # ── 非技能：流程 / 查询 / 游戏动作 ──
    "join", "result_confirm", "next", "new_hanchan", "match_confirm",
    "start", "deal_step", "state", "poll", "advance",
    "act", "wall", "step", "tenpai", "furiten", "ron", "judge",
    "wipe", "view_hand",
    "lobby_join", "lobby_order", "lobby_pick", "lobby_ready", "lobby_reset",
    "lobby_state", "lobby_unorder", "test_seats",
    "rename",                       # 本局昵称：不是技能，不问看破
    "lobby_add_bot", "lobby_remove_bot",      # 房间管理，不是技能，不问看破
    # ── 看破自己 / 取消 ──
    "kangpo", "kangpo_answer", "kangpo_skip", "skill_cancel", "card05_cancel",
    # ── 结算类技能：永远不能被看破 ──
    "card10s2_activate",          # Card10 S2 四喜
    # （Card01 S1 国标没有独立 op，走 op=act 的和牌判定）
    # ── 多步技能的后续步：第 1 步已经问过看破，不能再问一遍 ──
    "deal_swap",                  # 风神（4-1）第 2 步：选牌换牌
    "south_wind_kinds",           # 南风（6-1）第 2 步：选种类
    "south_wind_swap",            # 南风（6-1）第 3 步：换牌
    "oracle_toggle",              # 降神（7-1）后续：开关
    "oracle_pick",                # 降神（7-1）后续：选花色
    "shenshan_resolve",           # 深山（19-1）：用户口径「只问开这一次」
    "haishin_give",               # 海神（12-1）：配牌开启时已问过
    "haishin_swap",               # 海神（12-1）后续
    "haishin_pass",
    "zhalie_swap",                # 炸裂（14-2）：点燃（配牌）那一步已问过
    "pofa_discard", "pofa_pass",
    "youyin_meld_pick",           # 友引段1 的第二步（arm 时已经问过看破）
    "c29s1_skip",                 # 加速：点「跳过」= 不发动，没有发动点可看破
    "c32s1_give",                 # 新手运：被问的那家交牌
    "c32s1_swap",                 # 新手运：我挑一张换
    "c34s1_arm",                  # 厄运：用户口径「不能被看破」
    "c34s2_probe",                # 海底：点图标的只读诊断，没有发动点可看破
    "c38s1_view",                 # 重整：只读预览（真正发动在 apply）
    "c41_copy",                   # 复制：即时响应（别人发动技能的那一刻）
    "c41_skip",                   # 复制：这次不复制
    "c45s2_pick",                 # 替身：第二位指定切哪张（效果执行，不是发动）
    "c40s2_pick",                 # 同盟：发动者挑一组搭子（效果执行）
    "c43s2_answer",               # 免疫：回答要不要免疫（询问的答复）
    "c42s2_answer",               # 夺目：结算前那一问的答复（不是发动点）
    "support_mute",               # 协战卡遮罩：开关，不是技能发动
    "act_answer",                 # 拦截树：回答看破/封堵/阻止/免疫
    "c30s1_give",                 # 向听：被问的那家交牌（发动点已经问过看破）
    "c30s1_swap",                 # 向听：挑牌互换（同上）
    "future_set",                 # 未来（24S2）：arm（发动）那一步已经问过看破
    "c26_set",                    # 天梯（26S2）：配牌发动时已经问过看破
    "c25s2_swap",                 # 宝牌的集合（25-2）：arm 那一步已经问过看破
    # ── Card05「策略」三段（待按新规则实现，先明确排除）──
    # Card05「策略」段1：被别人「观看手牌」时压三张 → 永远不能被看破
    "card05_hide",
}

# 自己内部已经问过看破的 op（要带 card/skill 参数，静态表里给不了）
_GATE_INLINE = {"skill", "yiding"}


def _op_skill_pair(op: str, req: dict):
    """这次请求对应哪张卡的哪个技能（给「复制品独立配额」用）。没有就 None。"""
    c, k = req.get("card"), req.get("skill")
    if isinstance(c, int) and isinstance(k, int) and c > 0 and k > 0:
        return (int(c), int(k))
    if op == "card09_swap":
        return (9, int(req.get("skill") or 1))
    p = _SKILL_OP_PAIRS.get(op)
    if p:
        return (int(p[0]), int(p[1]))
    return None


def _gate_pair(op: str, req: dict):
    """这次请求要不要问看破？返回 (card, skill)；None = 不问。"""
    if op in _NO_GATE_OPS or op in _GATE_INLINE:
        return None
    if op not in _SKILL_OP_PAIRS:
        return None              # import 时的断言保证不会走到这里
    if op == "deal_skill":
        if str(req.get("action", "")) != "use":
            return None          # 跳过 / 取消不问看破
        return (int(req.get("card", 0) or 0), int(req.get("skill", 0) or 0))
    if op == "card09_swap":
        return (9, int(req.get("skill", 1) or 1))     # 1 守 / 2 攻
    if op == "chuancheng":
        # 发动的是 16 号卡本身（复制来的技能发动时会再问一次，pair 是那个技能）
        return (16, 1)
    return _SKILL_OP_PAIRS[op]


# 拦截树预检表：这些 op 的**第一句**就是 `if not self.XXX_can(seat): raise`，
# 所以「can 为假」⇒ 这次发动必然失败 ⇒ 没必要挂节点问看破
# （没人能拦一个根本不会发生的发动）。只收这种等价的，没把握的别往里加。
_GATE_PRECHECK = {
    "c36s2_arm": "c36s2_can",
    "c37s1_arm": "c37s1_can",
    "c37s2_apply": "c37s2_can",
    "c38s1_apply": "c38s1_can",
    "c39s1_apply": "c39s1_can",
    "c40s1_apply": "c40s1_can",
    "c40s2_apply": "c40s2_can",
    "c42s1_apply": "c42s1_can",
    "c42s2_arm": "c42s2_can",
    "c43s1_apply": "c43s1_can",
    "c44s2_arm": "c44s2_can",
    "c45s1_apply": "c45s1_can",
    "c45s2_apply": "c45s2_can",
    "c46s1_apply": "c46s1_can",
}


def _gate_cannot_fire(db: DB, rid, op: str, seat: int,
                      card: int, skill: int) -> bool:
    """这次发动是不是「注定失败」？True = 别挂节点、别问看破，让 op 自己回真原因。

    ★ 2026-10-28 现场（【强运】）：技能已经发动成功、牌都换完了，玩家再点一次「开始」
      → 闸门照样建节点去问看破 → 永远回 need_kangpo，客户端就一直弹
      「已确认，等对方决定是否拦截…」，而这一手本来就该回「本小局只能发动一次」。
    """
    if not rid:
        return False
    try:
        g = _game(db, rid)
    except Exception:                                    # noqa: BLE001
        return False
    try:
        if int(card) > 0 and g.skill_used(int(seat), int(card), int(skill)):
            return True                      # 一次性技能：本小局已经用过了
    except Exception:                                    # noqa: BLE001
        pass
    name = _GATE_PRECHECK.get(str(op))
    fn = getattr(g, name, None) if name else None
    if fn is None:
        return False
    try:
        return not bool(fn(int(seat)))
    except Exception:                                    # noqa: BLE001
        return False                         # 预检自己出错 → 保守：照常问看破


# 其余所有 op 默认要问：op → (卡号, 技能号)
_SKILL_OP_PAIRS = {
    "guobiao": (1, 1),            # 国标（宣言式）
    "skill2": (1, 2),             # 避开
    "board": (2, 1),              # 画板
    "swap": (2, 2),               # 3⇄3 换牌
    "press": (3, 2),              # 压制
    "wind_swap": (4, 2),          # 自风
    "duel_start": (8, 1),         # 决斗
    "card05_swap": (5, 1),        # 策略段2：选完牌点「确认」那一下问
    "card05_extra": (5, 1),       # 策略段3：摸牌后点「额外摸切」时问
    "card05_nuki": (5, 2),        # 拔北（即时类，点确认时问）
    "card09_swap": (9, 1),        # 间合（实际技能号看 req.skill）
    "card10_hand": (10, 1),       # 鬼门·甲
    "card10_meld": (10, 1),       # 鬼门·乙
    "card11_swap": (11, 1),       # 魔术
    "card11s2_swap": (11, 2),     # 快手
    "haishin_start": (12, 1),     # 海神：配牌时开启
    "xn_activate": (12, 2),       # X神
    "pofa_activate": (13, 1),     # 破发
    "ignite": (14, 1),            # 点燃
    "diaoyu_force": (15, 1),      # 钓鱼
    "chuancheng": (16, 1),        # 传承
    "yanjiu": (17, 1),            # 研究
    "jiasuo": (18, 1),            # 枷锁
    "link": (18, 2),              # 连接
    "shenshan_toggle": (19, 1),   # 深山（开/关那一步算发动）
    "nongwu": (19, 2),            # 浓雾
    "qianlu": (20, 1),            # 前路
    "ganzhi": (20, 2),            # 感知
    "gift_swap": (21, 2),         # 馈赠段2（换牌）
    "gift_skip": (21, 2),         # 跳过（同一个发动点）
    "xianfu_swap": (22, 1),       # 先负
    "c24_declare": (24, 1),       # 一发（24S1）：选一张打出去立直
    "future_arm": (24, 2),        # 未来（24S2）：点技能 = 直接发动（可被看破）
    "c27s1_swap": (27, 1),        # 调包（27S1）：手牌 ⇄ 别人牌河
    "c27s2_declare": (27, 2),     # 伏兵（27S2）：暗置打出
    "c25s2_arm": (25, 2),         # 宝牌的集合（25S2）：配牌紧随宝牌运自动发动
    "youyin_take": (22, 2),       # 友引段2：与牌河互换
    "c29s1_chi": (29, 1),         # 加速：点「吃」这一下就是发动时机
    "c30s1_arm": (30, 1),         # 向听：配牌点「开始」= 发动时机
    "c32s1_arm": (32, 1),         # 新手运：配牌点「开始」= 发动时机
    "c33s1_swap": (33, 1),        # 染手：摸牌后 3 张手牌 ⇄ 牌河一组面子
    "c33s2_try": (33, 2),         # 记忆：切牌状态输入上局点数 → 下一张暗置
    "c35s1_set": (35, 1),          # 流势：副露后排牌山，排的那一下问
    "c36s2_arm": (36, 2),          # 故意：点图标开启那一下问
    "c37s1_arm": (37, 1),          # 岭上开花：点技能那一下问
    "c37s2_apply": (37, 2),        # 强运：选好牌点确认那一下问
    "c38s1_apply": (38, 1),        # 重整：点确认那一下问
    "c40s1_apply": (40, 1),        # 透视：选好一家那一下问
    # 复制（41-1）：即时响应技能，本身不查看破（否则每次复制都要问一圈）
    "c44s2_arm": (44, 2),          # telegram: reveal + 30fu1han
    "c45s1_apply": (45, 1),        # 神境: 13 tiles from river+hand
    "c45s2_apply": (45, 2),        # 替身：指定两位玩家
    "c46s1_apply": (46, 1),        # 恶听：切一张能听牌的手牌 → 一定和牌
    "c39s1_apply": (39, 1),        # 隐形：打出的牌不能被鸣/被荣
    "c42s1_apply": (42, 1),        # 理论战：配牌封死全场技能
    "c42s2_arm": (42, 2),          # 夺目：指定结算用的庄家
    "c40s2_apply": (40, 2),        # 同盟：指定一名玩家
    "c43s1_apply": (43, 1),        # NO MISS：点「开始」那一下问
    "youyin_meld_arm": (22, 2),    # 友引段1：鸣牌窗口里点技能
    "heat": (23, 1),              # 加热
    "deal_skill": (0, 0),         # 配牌技能：实际 pair 看 req.card / req.skill
}

# 旧名字留着，别的地方（测试）还在用
_GATE_SKILL_OPS = _SKILL_OP_PAIRS


def op_skill(db: DB, req: dict) -> dict:
    """发动人物卡技能（主动技能）。

    只做「检查 + 挂牌子」：条件成立时 Game.armed_skill 会记下这一手，
    客户端据此显示技能给的按钮（比如自摸）；按下按钮再走 op=act。
    """
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    # 看破：别人发动技能前先问持有者（除非这次请求就是「放行后重放」）
    pair = (int(req.get("card", 0)), int(req.get("skill", 0)))
    # 只有「摸牌后挂牌子」的技能才走 op=skill（国标 / 自信）。
    # 其它技能都有自己的专属 op；误发到这里以前会先问看破、再回「还没实现」，
    # 玩家看到的就是「点了技能先问看破、放行后什么也没发生」。
    if pair not in {(3, 1)}:
        return {"ok": False, "state": None, "events": [], "result": None,
                "error": "这个技能没有「挂牌子」的发动方式（%d-%d）" % pair}
    if not req.get("_gate_ok") and pair not in _GATE_AT_CONFIRM:
        if g.kangpo_gate(seat, pair[0], pair[1], op="skill", payload={}):
            return {"ok": True, "need_kangpo": True, "state": g.state_for(seat),
                    "events": [], "result": g.result, "round_id": rid}
    # 配牌技能：这家已经决定过了（不在 deal_wait）→ 别再执行一遍
    # （风神/南风/研究/枷锁 之前没有幂等保护，重复点会把 deal_flow 重置）
    if g.phase == "deal_skill" and seat not in g.deal_wait:
        return {"ok": True, "already": True, "armed": False, "state": g.state_for(seat),
                "events": [], "result": g.result, "round_id": rid}
    r = g.arm_skill(seat, int(req.get("card", 0)), int(req.get("skill", 0)))
    r["state"] = g.state_for(seat)
    r["events"] = []
    r["result"] = g.result
    r["round_id"] = rid
    return r


def op_wipe(db: DB, req: dict) -> dict:
    """清空「上一次运行」留下的全部记录（本地多开测试用）。

    触发时机由客户端决定：
      · 启动时：没有别的窗口在（没有活着的座位租约）→ 说明这是一次全新的运行
      · 关窗口时：自己是最后一个窗口 → 把记录清掉，下次启动不继承进度

    清掉的东西：
      · 对局数据：matches（级联 rounds / 手牌 / 牌河 / 副露 / 宝牌 / 旗标 / 分数事件）
      · 房间与用户：rooms（级联 room_seats）、sessions、users
      · meta：local_round_id / local_room_id / 四个座位的租约
      · 大厅：回到 waiting（四家未准备、没有手牌和卡序）
    """
    raw = req.get("seat")
    me = int(raw) if isinstance(raw, int) and 0 <= int(raw) <= 3 else None
    with db.tx():
        others = _human_seats(db)
        if me is not None:
            others.discard(me)                   # 自己要关掉了，不算「别人」
        if others and not req.get("force"):
            return {"ok": True, "wiped": False, "others": sorted(others),
                    "state": None, "events": [], "result": None, "reason": "还有窗口在"}
        lobby = lobby_mod.load(db)
        db.conn.execute("DELETE FROM matches")
        db.conn.execute("DELETE FROM rooms")
        db.conn.execute("DELETE FROM sessions")
        db.conn.execute("DELETE FROM users")
        db.conn.execute("DELETE FROM meta WHERE key LIKE 'seat_lease_%'")
        db.conn.execute("DELETE FROM meta WHERE key IN (?, ?)", (LOCAL_KEY, "local_room_id"))
        db.conn.execute("DELETE FROM meta WHERE key = 'revealed_seats'")
    lobby = lobby_mod.reset(lobby)
    lobby_mod.save(db, lobby)
    return {"ok": True, "wiped": True, "reason": "", "lobby": lobby,
            "state": None, "events": [], "result": None}


def op_skill2(db: DB, req: dict) -> dict:
    """Card01 Skill2「避开」：选一名玩家 + 两张手牌 → 告诉你哪几张是他的铳张。

    只回命中下标（hits），不回对方的听牌列表。
    """
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    raw = req.get("target")
    target = int(raw) if isinstance(raw, int) else -1
    tiles = _tiles(req, "tiles")
    if not (0 <= target <= 3) or target == seat:
        return {"ok": False, "state": None, "events": [], "result": None,
                "error": "对象玩家不对"}
    if g.phase != "discard" or seat != g.turn:
        return {"ok": False, "state": None, "events": [], "result": None,
                "error": "现在不是你的出牌回合"}
    if g.drawn_tile(seat) is None:
        return {"ok": False, "state": None, "events": [], "result": None,
                "error": "摸牌之后才能发动"}
    if len(tiles) != 2:
        return {"ok": False, "state": None, "events": [], "result": None,
                "error": "要选两张手牌"}
    if g.skill_used(seat, 1, 2):
        return {"ok": False, "state": None, "events": [], "result": None,
                "error": "这个技能本局已经用过了"}
    # 这两张必须是自己的手牌
    from collections import Counter
    have = Counter(g.hand(seat))
    for tile in tiles:
        if have[tile] <= 0:
            return {"ok": False, "state": None, "events": [], "result": None,
                    "error": "这两张里有不在手上的牌"}
        have[tile] -= 1
    hits = skills.target_hits(g, target, tiles)
    g.mark_skill_used(seat, 1, 2)
    g.note_skill(seat, 1, 2)
    g.save_flags()
    return {"ok": True, "hits": hits, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_board(db: DB, req: dict) -> dict:
    """Card02 Skill1「画板」：指定三种手牌（本小局一次）。"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g.choose_board(seat, _tiles(req, "tiles"))
    return {"ok": True, "board": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_swap(db: DB, req: dict) -> dict:
    """Card02 Skill2：三张手牌暗置换进牌河，换回三张牌河牌。"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    hand_tiles = [str(t) for t in (req.get("hand_tiles") or [])]
    river = [int(x) for x in (req.get("river") or [])]
    r = g.swap_river(seat, hand_tiles, river)
    return {"ok": True, "swap": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_card05_extra(db: DB, req: dict) -> dict:
    """Card05 Skill1「策略」：花 1 点计数，换一次额外的摸切。"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g.card05_extra_activate(seat)
    return {"ok": True, "card05": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_south_wind_kinds(db: DB, req: dict) -> dict:
    """Card06 Skill1「南风」：指定两种牌。"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g.south_wind_kinds(seat, [str(k) for k in (req.get("kinds") or [])])
    return {"ok": True, "south_wind": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_south_wind_swap(db: DB, req: dict) -> dict:
    """Card06 Skill1「南风」：选两张手牌，跟三家按顺序换。"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g.south_wind_swap(seat, [str(t) for t in (req.get("tiles") or [])])
    return {"ok": True, "south_wind": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_card05_nuki(db: DB, req: dict) -> dict:
    """Card05 Skill2「拔北」：把手里的北放出去，从正常牌山补一张。"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g.card05_nuki(seat)
    return {"ok": True, "nuki": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_card05_swap(db: DB, req: dict) -> dict:
    """Card05 Skill1：王牌 / 弃牌 一张 ↔ 自己一张手牌。"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g.card05_swap(seat, str(req.get("hand", "")), str(req.get("kind", "")),
                      int(req.get("stack", 0) or 0), str(req.get("half", "top")),
                      int(req.get("river", -1) or -1))
    return {"ok": True, "card05_swap": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_card05_cancel(db: DB, req: dict) -> dict:
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g.card05_cancel(seat)
    return {"ok": True, "card05_cancel": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_card11_swap(db: DB, req: dict) -> dict:
    """Card11 S1「魔术」：手牌一张 ? 宝牌指示牌"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g.card11_swap(seat, str(req.get("hand", "")), int(req.get("idx", 0)))
    return {"ok": True, "card11": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_card11s2_swap(db: DB, req: dict) -> dict:
    """Card11 S2「快手」：摸的牌暗置换别家牌河第一列/第六列"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g.card11s2_swap(seat, int(req.get("river", -1)),
                        int(req.get("ts", -1)), int(req.get("slot", -1)))
    return {"ok": True, "card11s2": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def _simple(op_name: str, fn, key: str):
    def _op(db: DB, req: dict) -> dict:
        rid = req.get("round_id") or _get_round_id(db)
        g = _game(db, rid)
        seat = int(req.get("seat", 0))
        r = fn(g, seat, req)
        return {"ok": True, key: r, "state": g.state_for(seat), "events": [],
                "result": g.result, "round_id": rid}
    _op.__name__ = "op_" + op_name
    return _op


op_shenshan_toggle = _simple("shenshan_toggle", lambda g, s, r: g.shenshan_toggle(s),
                             "shenshan")
op_shenshan_resolve = _simple(
    "shenshan_resolve", lambda g, s, r: g.shenshan_resolve(s, str(r.get("hand", ""))),
    "shenshan")
op_nongwu = _simple("nongwu", lambda g, s, r: g.nongwu_activate(s), "nongwu")
op_qianlu = _simple("qianlu", lambda g, s, r: g.qianlu_set(
    s, [str(x) for x in (r.get("tiles") or [])]), "qianlu")
op_ganzhi = _simple("ganzhi", lambda g, s, r: g.ganzhi_activate(s), "ganzhi")
op_gift_swap = _simple("gift_swap", lambda g, s, r: g.gift_swap(
    s, str(r.get("hand", "")), int(r.get("river", -1))), "gift")
op_xianfu_swap = _simple("xianfu_swap", lambda g, s, r: g.xianfu_swap(
    s, str(r.get("hand", "")), int(r.get("river", -1))), "xianfu")
op_gift_skip = _simple("gift_skip", lambda g, s, r: g.gift_skip(s),
                             "gift")
op_youyin_take = _simple("youyin_take", lambda g, s, r: g.youyin_take(
    s, int(r.get("river", -1)), str(r.get("hand", ""))), "youyin")
op_youyin_meld_arm = _simple("youyin_meld_arm",
                             lambda g, s, r: g.youyin_meld_arm(s), "youyin_meld")
op_youyin_meld_pick = _simple("youyin_meld_pick",
                              lambda g, s, r: g.youyin_meld_pick(
                                  s, [str(x) for x in (r.get("tiles") or [])]),
                              "youyin_meld")
def _c32_give_tile(req: dict) -> str:
    """新手运的「交牌」：客户端复用 c30 面板，发的是 tiles 数组（只 1 张）；

    也兼容单数 tile（手工请求 / 旧客户端）。"""
    t = str(req.get("tile", "") or "")
    if t:
        return t
    ts = req.get("tiles")
    if isinstance(ts, list) and ts:
        return str(ts[0])
    return ""


op_c32s1_give = _simple("c32s1_give", lambda g, s, r: g.c32s1_give(
    s, _c32_give_tile(r)), "c32")
op_c32s1_swap = _simple("c32s1_swap", lambda g, s, r: g.c32s1_swap(
    s, str(r.get("hand", ""))), "c32")


# ── Card34 S1【厄运】：静默期内只有「非技能类」的 op 放行 ─────────────
_C34_FREE_OPS = {
    # 基础：看状态 / 推进 / 打牌 / 荣和 / 见逃 / 纯判定
    "join", "state", "step", "advance", "act", "pass", "ron", "tenpai", "furiten",
    "match_confirm",
    "judge", "wall", "view_hand", "deal_step", "wipe", "next", "start",
    "new_hanchan", "test_seats",
    # 大厅
    "lobby_join", "lobby_order", "lobby_pick", "lobby_ready", "lobby_reset",
    "lobby_state", "lobby_unorder", "lobby_add_bot", "lobby_remove_bot",
    "rename",
    # 应答类（被别人问 / 取消 / 遮罩）：不是「自己发动技能」
    "deal_skill", "deal_swap", "south_wind_kinds", "south_wind_swap",
    "haishin_give", "haishin_swap", "haishin_pass",
    "zhalie_swap", "pofa_discard", "pofa_pass",
    "youyin_meld_pick", "youyin_take",
    "gift_swap", "gift_skip", "xianfu_swap",
    "kangpo", "kangpo_answer", "kangpo_skip", "skill_cancel", "card05_cancel",
    "c30s1_give", "c30s1_swap", "c32s1_give", "c32s1_swap",
    "c29s1_skip", "c11s2_swap", "c25s2_swap", "c26_set", "future_set",
    "card05_hide",
    "c34s2_probe",                # 海底：点图标的只读诊断，不改任何状态
    "c38s1_view",                 # 重整：只读预览（真正发动在 apply）
    "c41_copy",                   # 复制：即时响应（别人发动技能的那一刻）
    "c41_skip",                   # 复制：这次不复制
    "support_mute",               # 协战卡遮罩：开关，不是「自己发动技能」
}


def op_c34s1_arm(db: DB, req: dict) -> dict:
    """Card34 S1【厄运】：切牌前发动，其他三家三巡内一切无效。"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g.c34s1_arm(seat)
    return {"ok": True, "c34": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def _act_auto_pass_others(db: DB, g, rid: int, answered: int) -> None:
    """答复之后：其余询问里「没人在操作」的座位自动放行。

    真人窗口（有租约的）照旧各自弹窗；先答先落由 act_answer 保证。
    """
    humans = _human_seats(db)
    if not humans:
        humans = set()                      # 一个客户端都没连 → 全当 AI，别卡住
    for n in list(g.acts.values()):
        if n.get("state") != "asking":
            continue
        for a in (n.get("asks") or []):
            s2 = int(a.get("seat", -1))
            if a.get("answer") or s2 == int(answered) or s2 in humans:
                continue
            try:
                g.act_answer(s2, int(n.get("id", -1)), "pass")
            except Exception:
                pass


def _after_act(db: DB, g, rid: int, seat: int) -> tuple[list, dict]:
    """拦截树有结论之后：把 applied 的根节点真正执行掉。

    返回 (事件列表, 最后一次执行的回包) —— 回包要合并进答复里，
    这样 `card05_swap` / `chuancheng` / `card09` 这些键还在（老客户端和测试都认）。
    """
    evs: list = []
    last: dict = {}
    for node in g.act_take_ready():
        if str(node.get("state")) != "applied":
            continue
        want = str(node.get("op", "") or "")
        if not want:
            continue
        sub = {"op": want, "seat": int(node.get("actor", 0)), "round_id": rid,
               "_gate_ok": True, "_act_ran": True, "pid": None}
        sub.update(dict(node.get("payload") or {}))
        fn = OPS.get(want)
        try:
            out = fn(db, sub) if fn is not None else op_state(db, sub)
        except Exception as e:                          # noqa: BLE001
            out = {"ok": False, "events": [], "error": f"{type(e).__name__}: {e}"}
        evs += list(out.get("events") or [])
        last = out
    return evs, last


def op_act_answer(db: DB, req: dict) -> dict:
    """拦截树：回答一条询问（kind = sight/block/stop/imm/pass）。"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g.act_answer(seat, int(req.get("aid", -1)), str(req.get("kind", "pass")))
    _act_auto_pass_others(db, g, rid, seat)
    evs, last = _after_act(db, g, rid, seat)
    g2 = _game(db, rid)
    out = dict(last) if last else {}
    out.update({"ok": True, "act": r, "state": g2.state_for(seat), "events": evs,
                "result": g2.result, "round_id": rid})
    return out


def op_c43s2_answer(db: DB, req: dict) -> dict:
    """Card43 S2【免疫】：被指向的人回答 —— 发动（这次作废 + 以后免疫）或跳过（照常发动）。"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    use = bool(req.get("use", False))
    r = g.c43s2_answer(seat, use)
    if not use:
        pend = r.get("pending") or {}
        if pend:
            want = str(pend.get("op", "") or "")
            sub = {"seat": int(pend.get("actor", -1)), "_gate_ok": True,
                   "round_id": rid, "pid": req.get("pid"), "_imm_ok": True}
            payload = dict(pend.get("payload") or {})
            try:
                if want and want != "skill":
                    sub["op"] = want
                    sub.update(payload)
                    fn = OPS.get(want)
                    out = fn(db, sub) if fn is not None else op_state(db, sub)
                else:
                    sub.update({"op": "skill", "card": int(pend.get("card", 0)),
                                "skill": int(pend.get("skill", 0))})
                    out = op_skill(db, sub)
            except Exception as e:                       # 重放失败也要回包
                out = {"ok": False, "state": None, "events": [], "result": None,
                       "error": str(e)}
            out["c43s2"] = r
            return out
    return {"ok": True, "c43s2": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_c40s2_apply(db: DB, req: dict) -> dict:
    """Card40 S2【同盟】：指定一名玩家（手牌常显 + 我打出的牌他自动副露）。"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g.c40s2_apply(seat, int(req.get("target", -1)))
    return {"ok": True, "c40s2": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_c40s2_pick(db: DB, req: dict) -> dict:
    """Card40 S2【同盟】：发动者挑一组搭子 → 替他自动副露。"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    ev = g.c40s2_pick(seat, str(req.get("kind", "")), int(req.get("index", -1)))
    return {"ok": True, "c40s2": {"picked": True}, "state": g.state_for(seat),
            "events": [ev] if ev else [], "result": g.result, "round_id": rid}


def op_c42s1_apply(db: DB, req: dict) -> dict:
    """Card42 S1【理论战】：已发动的配牌技能作废，之后谁都不能发动技能。"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g.c42s1_apply(seat)
    return {"ok": True, "c42": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_support_mute(db: DB, req: dict) -> dict:
    """协战人物卡遮罩：把 target 那家的协战卡「遮罩」或「取消遮罩」。

    遮罩期间这张卡的**一切技能判定都不成立**（skills.owns_card / cards_in_order 里剔掉）。
    协战卡只活两个风场，出场时机很关键 —— 所以允许任意时刻开关。
    """
    rid = req.get("round_id") or _get_round_id(db)
    seat = int(req.get("seat", 0))
    tgt = int(req.get("target", seat))
    # 只遮自己那一家（用户口径 2026-10-28：遮罩是「自己的角色卡别自动发动 / 别来问我」）
    if tgt != seat:
        return {"ok": False, "state": None, "events": [], "result": None,
                "error": "协战卡遮罩：只能遮罩自己的卡"}
    if not (0 <= tgt < 4):
        return {"ok": False, "state": None, "events": [], "result": None,
                "error": "协战卡遮罩：座位不对"}
    card = int(skills.support_card(db, tgt))
    if card <= 0:
        return {"ok": False, "state": None, "events": [], "result": None,
                "error": "协战卡遮罩：这家还没有协战卡"}
    on = bool(req.get("on", True))
    skills.set_support_mute(db, tgt, card if on else 0)
    g2 = _game(db, rid)
    return {"ok": True, "support_mute": {"seat": tgt, "card": card, "on": on},
            "state": g2.state_for(seat), "events": [], "result": g2.result,
            "round_id": rid, "error": ""}


def op_c42s2_answer(db: DB, req: dict) -> dict:
    """Card42 S2【夺目】：**结算前**那一问的回答。

    target >= 0 → 这次结算把他当庄家算点数；target = -1 → 按真庄家结算（跳过）。
    """
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g.c42s2_answer(seat, int(req.get("target", -1)))
    g2 = _game(db, rid)
    return {"ok": True, "c42s2": r, "state": g2.state_for(seat), "events": r.get("events") or [],
            "result": g2.result, "round_id": rid}


def op_c42s2_arm(db: DB, req: dict) -> dict:
    """Card42 S2【夺目】：指定一位玩家，结算时把他当庄家（只影响点数）。"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g.c42s2_arm(seat, int(req.get("target", -1)))
    return {"ok": True, "c42": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_c39s1_apply(db: DB, req: dict) -> dict:
    """Card39 S1【隐形】：本局打出的牌谁都不能吃碰杠荣，也不造成振听。"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g.c39s1_apply(seat)
    return {"ok": True, "c39": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_c46s1_apply(db: DB, req: dict) -> dict:
    """Card46 S1【恶听】：切出一张能听牌的手牌 → 立刻按【一定和牌】结算。"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g.c46s1_apply(seat, str(req.get("tile", "")))
    return {"ok": True, "c46": r, "state": g.state_for(seat),
            "events": [r] if r else [], "result": g.result, "round_id": rid}


def op_c45s2_apply(db: DB, req: dict) -> dict:
    """Card45 S2【替身】：指定「第一位（被接管切牌）」+「第二位（指定切哪张）」。"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g.c45s2_apply(seat, int(req.get("first", -1)), int(req.get("second", -1)))
    return {"ok": True, "c45s2": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_c45s2_pick(db: DB, req: dict) -> dict:
    """Card45 S2【替身】：第二位玩家点一张手牌 → 第一位自动切出这张。"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    ev = g.c45s2_pick(seat, str(req.get("tile", "")))
    return {"ok": True, "c45s2": {"picked": str(req.get("tile", ""))},
            "state": g.state_for(seat), "events": [ev] if ev else [],
            "result": g.result, "round_id": rid}


def op_c45s1_apply(db: DB, req: dict) -> dict:
    """Card45 S1【神境】：手牌 + 牌河挑 13 张当新手牌（之后只能自摸、得点有上限）。"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    hand = [str(t) for t in (req.get("hand_tiles") or [])]
    river = [int(x) for x in (req.get("river") or [])]
    r = g.c45s1_apply(seat, hand, river)
    return {"ok": True, "c45": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_c44s2_arm(db: DB, req: dict) -> dict:
    """Card44 S2【电报】：宣言明牌（别人看得到我的手牌），本局和牌按 30 符 1 番。"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g.c44s2_arm(seat)
    return {"ok": True, "c44s2": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_c43s1_apply(db: DB, req: dict) -> dict:
    """Card43 S1【NO MISS】：手牌一组搭子 ⇄ 牌河一个搭子（换完能自摸就直接结算）。"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    hand = [str(t) for t in (req.get("hand_tiles") or [])]
    river = [int(x) for x in (req.get("river") or [])]
    r = g.c43s1_apply(seat, hand, river)
    return {"ok": True, "c43": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_c41_copy(db: DB, req: dict) -> dict:
    """Card41 S1【复制】：把刚才那个技能复制过来（之后自己用）。"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g.c41s1_copy(seat, int(req.get("card", 0) or 0), int(req.get("skill", 0) or 0))
    return {"ok": True, "c41": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_c41_skip(db: DB, req: dict) -> dict:
    """Card41 S1【复制】：这次不复制。"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g.c41s1_skip(seat)
    return {"ok": True, "c41": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_c40s1_apply(db: DB, req: dict) -> dict:
    """Card40 S1【透视】：看一家手牌（立直免费；非立直消耗那一家的一次）。"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g.c40s1_apply(seat, int(req.get("target", -1)))
    return {"ok": True, "c40": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_c38s1_view(db: DB, req: dict) -> dict:
    """Card38 S1【重整】：看「接下来 3 张指示牌」+ 我的手牌（只读）。"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    return {"ok": True, "c38": g.c38s1_view(seat), "round_id": rid}


def op_c38s1_apply(db: DB, req: dict) -> dict:
    """Card38 S1【重整】：选中的 3 张按顺序放进第 2/3/4 张指示牌的位置。"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    picks = req.get("picks") or []
    r = g.c38s1_apply(seat, picks)
    return {"ok": True, "c38": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_c37s2_apply(db: DB, req: dict) -> dict:
    """Card37 S2【强运】：选一种牌 → 三家手里这种牌与牌山第 4/8/12/16 张对调。"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g.c37s2_apply(seat, str(req.get("kind", "") or ""))
    return {"ok": True, "c37s2": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_c37s1_arm(db: DB, req: dict) -> dict:
    """Card37 S1【岭上开花】：自动杠开 + 把牌山里的和牌张换进岭上那张（得点 ×2）。

    · 自己的摸打阶段 → 暗杠 / 加杠，当场结算；
    · 鸣牌窗口里（别人打出的牌正好能明杠）→ 先答这一手明杠，
      窗口结算时真的杠出来才继续（荣和优先）；那一手的事件走 `ev` 带回去。
    """
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g.c37s1_arm(seat)
    evs = []
    if r.get("kan"):
        evs.append(r["kan"])
    if isinstance(r.get("ev"), dict) and r["ev"]:
        evs.append(r["ev"])
    return {"ok": bool(r.get("ok", True)), "c37": r, "state": g.state_for(seat),
            "events": evs,
            "result": g.result, "round_id": rid,
            "error": "" if r.get("ok", True) else str(r.get("why", "岭上开花失败"))}


def op_c36s2_arm(db: DB, req: dict) -> dict:
    """Card36 S2【故意】：切牌前开启 —— 打出的那张若能让某家成和牌型 → 我付他 1000。"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g.c36s2_arm(seat)
    return {"ok": True, "c36s2": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_c35s1_set(db: DB, req: dict) -> dict:
    """Card35 S1【流势】：副露后自动弹面板，排接下来 4 张牌山（不限次数）。"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g.c35s1_set(seat, [int(x) for x in (req.get("order") or [])])
    return {"ok": True, "c35": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_c34s2_probe(db: DB, req: dict) -> dict:
    """Card34 S2【海底】：点技能图标时的只读诊断（不改任何状态）。"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    return {"ok": True, "c34s2": g.c34s2_probe(seat), "round_id": rid}


def op_c33s2_try(db: DB, req: dict) -> dict:
    """Card33 S2【记忆】：输入上局结算点数，对了就武装「下一张暗置」。"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g.c33s2_try(seat, int(req.get("number", 0) or 0))
    return {"ok": True, "c33s2": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_c33s1_swap(db: DB, req: dict) -> dict:
    """Card33 S1【染手】：3 张手牌暗置换进牌河，换回牌河里一组面子。"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    hands = [str(t) for t in (req.get("hand_tiles") or [])]
    river = [int(x) for x in (req.get("river") or [])]
    r = g.c33s1_swap(seat, hands, river)
    return {"ok": True, "c33": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_c32s1_arm(db: DB, req: dict) -> dict:
    """Card32 S1【新手运】：配牌点开始（拦截询问在 op 层）。"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g._c32s1_arm(seat)
    return {"ok": True, "c32": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


op_c30s1_give = _simple("c30s1_give", lambda g, s, r: g.c30s1_give(
    s, [str(x) for x in (r.get("tiles") or [])]), "c30")
op_c30s1_swap = _simple("c30s1_swap", lambda g, s, r: g.c30s1_swap(
    s, str(r.get("hand", "")), str(r.get("tile", ""))), "c30")


def op_c30s1_arm(db: DB, req: dict) -> dict:
    """Card30 S1「向听」：配牌选两家 → 开始（看破在这一步问）。"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g._c30s1_arm(seat, [int(x) for x in (req.get("targets") or [])])
    return {"ok": True, "c30": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


op_c29s1_chi = _simple("c29s1_chi", lambda g, s, r: g.c29s1_chi(
    s, [str(x) for x in (r.get("tiles") or [])]), "c29s1")
op_c29s1_skip = _simple("c29s1_skip", lambda g, s, r: g.c29s1_skip(s), "c29s1")
op_heat = _simple("heat", lambda g, s, r: g.heat_activate(s, str(r.get("kind", ""))),
                  "heat")
op_c24_declare = _simple("c24_declare",
                         lambda g, s, r: g.c24_declare(s, str(r.get("tile", ""))),
                         "c24")
op_future_set = _simple("future_set",
                        lambda g, s, r: g.future_set(
                            s, [int(x) for x in (r.get("order") or [])]),
                        "future")


def op_chuancheng(db: DB, req: dict) -> dict:
    """Card16 S1 传承：把半庄里宣告过的技能当成自己的"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g.chuancheng_use(seat, int(req.get("card", 0)), int(req.get("skill", 0)))
    return {"ok": True, "chuancheng": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_yanjiu(db: DB, req: dict) -> dict:
    """Card17 S1 研究：摇骰子看一家手牌"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g.yanjiu_activate(seat)
    return {"ok": True, "yanjiu": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_ignite(db: DB, req: dict) -> dict:
    """Card14 S1 点燃：摸牌后再试一次骰子"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g.ignite_activate(seat)
    return {"ok": True, "ignite": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_kangpo_answer(db: DB, req: dict) -> dict:
    """看破：回答询问（use=True 拦下 / False 放行）—— 已并入拦截树。"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    use = bool(req.get("use", False))
    r = g.kangpo_answer(seat, use, str(req.get("kind", "")))
    _act_auto_pass_others(db, g, rid, seat)
    evs, last = _after_act(db, g, rid, seat)
    g2 = _game(db, rid)
    out = dict(last) if last else {}
    out.update({"ok": True, "kangpo": r, "state": g2.state_for(seat), "events": evs,
                "result": g2.result, "round_id": rid})
    return out


def op_kangpo_skip(db: DB, req: dict) -> dict:
    """看破：放行（已并入拦截树）。"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g.kangpo_skip(seat)
    _act_auto_pass_others(db, g, rid, seat)
    evs, last = _after_act(db, g, rid, seat)
    g2 = _game(db, rid)
    out = dict(last) if last else {}
    out.update({"ok": True, "kangpo": r, "state": g2.state_for(seat), "events": evs,
                "result": g2.result, "round_id": rid})
    return out


def op_kangpo(db: DB, req: dict) -> dict:
    """Card17 S2 看破：剔除一家一个技能（代价：本局不能和）"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g.kangpo_poke(seat, int(req.get("target", -1)),
                      int(req.get("card", 0)), int(req.get("skill", 0)))
    return {"ok": True, "kangpo": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_jiasuo(db: DB, req: dict) -> dict:
    """Card18 S1 枷锁：定本局期待的番数"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g.jiasuo_set(seat, int(req.get("han", 0)))
    return {"ok": True, "jiasuo": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_link(db: DB, req: dict) -> dict:
    """Card18 S2 连接：与一家平分得点"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g.link_use(seat, int(req.get("target", -1)))
    return {"ok": True, "link": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_zhalie_swap(db: DB, req: dict) -> dict:
    """Card14 S2 炸裂：点燃判定 → 手牌 ↔ 别家牌河 6~9"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g.zhalie_swap(seat, str(req.get("hand", "")), int(req.get("river", -1)))
    return {"ok": True, "zhalie": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_diaoyu_force(db: DB, req: dict) -> dict:
    """Card15 S1 钓鱼：强制某家打出我指定的牌"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g.diaoyu_force(seat, int(req.get("target", -1)), str(req.get("tile", "")))
    return {"ok": True, "diaoyu": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_pofa_activate(db: DB, req: dict) -> dict:
    """Card13 S1 破发：河里一张 + 手牌搭子 → 副露，再暗置放回一张"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g.pofa_activate(seat, int(req.get("river", -1)),
                        [str(x) for x in (req.get("tiles") or [])])
    return {"ok": True, "pofa": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_haishin_give(db: DB, req: dict) -> dict:
    """Card12 S1 被动：把对方摸到的牌借过来"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g.haishin_give(seat, str(req.get("hand", "")))
    return {"ok": True, "haishin": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_haishin_swap(db: DB, req: dict) -> dict:
    """Card12 S1 主动：挪宝（里宝 → 杠宝 → 杠里宝）"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g.haishin_swap(seat, str(req.get("hand", "")))
    return {"ok": True, "haishin": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_xn_activate(db: DB, req: dict) -> dict:
    """Card12 S2 X神：让一位其他玩家跳过摸切 2 次"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g.xn_activate(seat, int(req.get("target", -1)))
    return {"ok": True, "xn": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_card10s2_activate(db: DB, req: dict) -> dict:
    """Card10 Skill2「四喜」：明置东/北，之后第 5 张摸牌视为小四喜自摸。"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g.card10s2_activate(seat)
    return {"ok": True, "card10s2": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_card10_hand(db: DB, req: dict) -> dict:
    """Card10 S1「鬼门」甲：3 张手牌 ↔ 牌河 3 张东/北。"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g.card10_swap_hand(seat, str(req.get("kind", "")),
                           [str(t) for t in (req.get("tiles") or [])],
                           [int(x) for x in (req.get("rivers") or [])])
    return {"ok": True, "card10": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_card10_meld(db: DB, req: dict) -> dict:
    """Card10 S1「鬼门」乙：我的一组副露 ↔ 别家东/北的刻子或杠。"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g.card10_swap_meld(seat, str(req.get("kind", "")), int(req.get("my_meld", -1)),
                           int(req.get("target", -1)), int(req.get("their_meld", -1)))
    return {"ok": True, "card10": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_card09_swap(db: DB, req: dict) -> dict:
    """Card09：摸牌前用一张手牌换一张牌河明牌（skill 1=自己的河 / 2=别家的河）。"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g.card09_swap(seat, int(req.get("skill", 1)),
                      str(req.get("hand", "")), int(req.get("river", -1)))
    return {"ok": True, "card09": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_pofa_discard(db: DB, req: dict) -> dict:
    """破发副露之后：暗置打出一张"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g.pofa_discard(seat, str(req.get("tile", "")))
    return {"ok": True, "pofa_discard": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_pofa_pass(db: DB, req: dict) -> dict:
    """破发：这次不副露"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g.pofa_pass(seat)
    return {"ok": True, "pofa_pass": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_haishin_start(db: DB, req: dict) -> dict:
    """Card12 S1「海神」：配牌时开启（本小局别人摸万子/红中都会强制问你换不换）"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g.haishin_start(seat)
    return {"ok": True, "haishin": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_haishin_pass(db: DB, req: dict) -> dict:
    """兜底：没人操作/遮罩时把「借牌」放掉，别挂死对局"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g.haishin_pass(seat)
    return {"ok": True, "haishin_pass": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_duel_start(db: DB, req: dict) -> dict:
    """Card08 Skill1「决斗」：选一个风 = 指定一家当对手。"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g.duel_start(seat, int(req.get("target", -1)))
    return {"ok": True, "duel_start": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_oracle_toggle(db: DB, req: dict) -> dict:
    """Card07 Skill1「降神」：再点一次技能图标 → 打开 / 关闭。"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g.oracle_toggle(seat)
    return {"ok": True, "oracle": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_oracle_pick(db: DB, req: dict) -> dict:
    """Card07 Skill1「降神」：摸牌前指定一张牌，跟别家 / 牌山交换。"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    # 降神的发动点在配牌（op=skill）那一次；这里不再问看破
    r = g.oracle_pick(seat, str(req.get("tile", "")))
    return {"ok": True, "oracle": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_skill_cancel(db: DB, req: dict) -> dict:
    """还在选牌时再点一次技能图标：取消这次发动（服务端状态一起回退）。"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g.skill_cancel(seat, str(req.get("what", "")))
    return {"ok": True, "skill_cancel": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_card05_hide(db: DB, req: dict) -> dict:
    """Card05 Skill1：被看手牌时盖住最多三张。"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g.card05_hide(seat, [str(x) for x in (req.get("tiles") or [])])
    return {"ok": True, "card05_hide": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_view_hand(db: DB, req: dict) -> dict:
    """看某个座位的手牌（策略：盖住的三张看不到；第一次看会先让对方选盖哪三张）。"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    target = int(req.get("target", -1))
    r = g.card05_view_hand(seat, target)
    return {"ok": True, "view": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_wind_swap(db: DB, req: dict) -> dict:
    """Card04 Skill2「自风」：用我的一张手牌，换对方刚摸到的自风。"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g.wind_swap_apply(seat, str(req.get("tile", "")))
    return {"ok": True, "wind_swap": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_deal_swap(db: DB, req: dict) -> dict:
    """Card04 Skill1「风神」：这一步选中的手牌 ↔ 对手所有风牌。"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    tiles = [str(t) for t in (req.get("tiles") or [])]
    r = g.deal_swap(seat, int(req.get("stage", -1)), tiles)
    return {"ok": True, "deal_swap": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_deal_skill(db: DB, req: dict) -> dict:
    """配牌阶段技能窗口：发动（use）或跳过（skip）。"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    action = str(req.get("action", "skip"))
    r = g.deal_action(seat, action, int(req.get("card", 0) or 0),
                      int(req.get("skill", 0) or 0))
    return {"ok": True, "deal_skill": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_c26_set(db: DB, req: dict) -> dict:
    """Card26 Skill2「天梯」：每次自己摸牌前，把接下来 1+n 张排好。"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g.c26_set(seat, [int(x) for x in (req.get("order") or [])])
    return {"ok": True, "c26": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_c27s1_swap(db: DB, req: dict) -> dict:
    """Card27 Skill1「调包」：一张手牌 ⇄ 别人牌河的一张明牌，并标记那一家。"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g.c27s1_swap(seat, str(req.get("hand", "")), int(req.get("river", -1)))
    return {"ok": True, "c27s1": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_c27s2_declare(db: DB, req: dict) -> dict:
    """Card27 Skill2「伏兵」：有役听牌的牌暗置打出（门清连立直），并按序数标记一家。"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g.c27s2_declare(seat, str(req.get("tile", "")))
    return {"ok": True, "c27s2": r, "state": g.state_for(seat),
            "events": [r["event"]] if r.get("event") else [],
            "result": g.result, "round_id": rid}


def op_future_arm(db: DB, req: dict) -> dict:
    """Card24 Skill2「未来」：点技能 = 直接发动（之后才出现选牌界面，不可跳过）。"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g.future_arm(seat)
    return {"ok": True, "future": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_c25s2_arm(db: DB, req: dict) -> dict:
    """Card25 Skill2「宝牌的集合」：宝牌运结算完紧接着发动（本局开启）。"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g.c25s2_arm(seat)
    return {"ok": True, "c25s2": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_c25s2_swap(db: DB, req: dict) -> dict:
    """Card25 Skill2「宝牌的集合」：别人摸到宝牌 → 我拿一张非宝牌换过来（不能跳过）。"""
    rid = req.get("round_id") or _get_round_id(db)
    seat = int(req.get("seat", 0))
    events: list = []
    with db.tx():
        g = _game(db, rid)
        r = g.c25s2_swap(seat, str(req.get("hand", "")))
        # ★ 换的是「别人刚摸的那张」，所以换完轮次还在那个人身上。
        #   他不一定是真人（1 个人玩的时候是人机）→ 这里顺手把该动的都动掉，
        #   否则客户端不会发 step，整桌就卡在「不能 discard」。
        events += _drive_others(db, g, seat)
        return {"ok": True, "c25s2_swap": r, "state": g.state_for(seat),
                "events": events, "result": g.result, "round_id": rid}


def op_press(db: DB, req: dict) -> dict:
    """Card03 Skill2「压制」：一张手牌 ↔ 一张牌河牌（自己牌河的明牌 / 任意暗置牌）。"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g.suppress_swap(seat, str(req.get("hand", "")), int(req.get("river", -1)))
    return {"ok": True, "press": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_tenpai(db: DB, req: dict) -> dict:
    """纯判定：这手牌听什么、哪几张有役（不入库）。"""
    hand = _tiles(req)
    drawn = req.get("drawn") or ""
    if drawn and drawn in hand:
        hand = list(hand)
        hand.remove(drawn)
    base = req.get("base") or {}
    r = tenpai.tenpai_report(hand, _melds(req), base or None)
    return {"ok": True, "state": None, "events": [], "result": None, "tenpai": r}


def op_furiten(db: DB, req: dict) -> dict:
    hand = _tiles(req)
    f = tenpai.furiten_info(counts_of(hand), _melds(req),
                            req.get("discards") or [],
                            temp=bool(req.get("temp", False)),
                            riichi=bool(req.get("riichi", False)))
    return {"ok": True, "state": None, "events": [], "result": None, "furiten": f}


def op_guobiao(db: DB, req: dict) -> dict:
    """Card01 S1「国标」：宣言 → 打一张听牌的牌 → 按「一定和牌」结算"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    ev = g.guobiao_declare(seat, str(req.get("tile", "")))
    return {"ok": True, "event": ev, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_yiding(db: DB, req: dict) -> dict:
    """Card21/15/20 的「一定和牌」：宣言 → 打牌 → 立刻结算

    看破在**这里**问：pair 是「授予权限的那个技能」（yiding_src），
    因为一定和牌可能来自 21S2 / 15S2 / 20S1，静态表给不了。
    """
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    src = g.yiding_src_of(seat) or [21, 2]
    if not req.get("_gate_ok"):
        if g.kangpo_gate(seat, int(src[0]), int(src[1]), op="yiding",
                         payload={"tile": str(req.get("tile", "")),
                                  "round_id": rid}):
            return {"ok": True, "need_kangpo": True, "state": g.state_for(seat),
                    "events": [], "result": g.result, "round_id": rid}
    ev = g.yiding_declare(seat, str(req.get("tile", "")))
    return {"ok": True, "event": ev, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_ron(db: DB, req: dict) -> dict:
    """纯判定：这张牌能不能荣和（含振听 / 无役）。"""
    r = tenpai.ron_availability(_tiles(req), str(req.get("tile", "")), _melds(req),
                                req.get("discards") or [],
                                temp=bool(req.get("temp", False)),
                                riichi=bool(req.get("riichi", False)),
                                base=req.get("base") or None)
    return {"ok": True, "state": None, "events": [], "result": None, "ron": r}


def op_judge(db: DB, req: dict) -> dict:
    """纯判定：这手牌和下来多少番多少符多少点（不入库）。"""
    hand = _tiles(req)
    tile = str(req.get("tile", ""))
    if not tile:
        return {"ok": False, "state": None, "events": [], "result": None, "error": "要带 tile"}
    r = tenpai.win_summary(hand, _melds(req), tile, bool(req.get("tsumo", False)),
                           req.get("base") or None)
    return {"ok": True, "state": None, "events": [], "result": None, "judge": r}


def op_deal_step(db: DB, req: dict) -> dict:
    """配牌一步：服务端按计划发牌，客户端照着摆（庄家那一步连第 14 张一起跳）。

    ★ 整个「读计划 → 发这一步 → 记进度」放在一个事务里：两个窗口同时推配牌时，
      不会各自读一遍进度、把同一张牌发两次（那样会少牌）。
    """
    rid = req.get("round_id") or _get_round_id(db)
    seat = int(req.get("seat", 0))
    with db.tx():
        g = _game(db, rid)
        ev = g.deal_step()
        return {"ok": True, "state": g.state_for(seat), "events": [ev],
                "result": g.result, "round_id": rid}


# ★ 这里原来有 op_draw（摸牌 / 岭上摸牌）和 op_dora（翻宝牌）两个 op，
#   它们**没有任何前置校验**：客户端发一次就摸一张牌 / 翻一张宝牌，
#   不看阶段、不看轮次、也不看有没有开杠。现场事故：一局里没有任何杠，
#   却翻了 3 张杠宝牌、摸走 2 张岭上牌、庄家手牌涨到 28 张。
#   这两个 op 已经删掉（客户端只照 state 画，翻宝牌/岭上摸牌一律由
#   game.py 的 _kan / _apply_claim / _youyin_finish 在服务端内部触发）。
#   Game.reveal_dora / _draw_rinshan 里另有「杠数对不对得上」的兜底校验。


def op_step(db: DB, req: dict) -> dict:
    """单步推进器：一次只替「没人在操作」的座位走一格，需要人动手就停下。

    - 配牌阶段：直接走 deal_step。
    - 鸣牌窗口：该我答就停下等我；别的座位要是「没人操作」，替他过掉。
    - 摸牌阶段：轮到我就我摸；轮到另一个窗口的人等他；没人的座位服务器替他摸。
    - 打牌阶段：轮到我就停下等我切牌；没人的座位摸切掉刚摸的那张。

    ★ 整段放在一个事务里：「读现在轮到谁 → 动一下 → 记进度」不能被别的窗口插队，
      否则两个窗口同时推的时候会把同一张牌摸两遍 / 替同一个人打两张。
    """
    rid = req.get("round_id") or _get_round_id(db)
    seat = int(req.get("seat", 0))
    with db.tx():
        g = _game(db, rid)
        humans = _human_seats(db)
        auto = _auto_ai(db)                      # 关掉代打时，没人的座位也不替它动
        ev = None
        if g.phase == "ended" or g.round_phase != "play":
            ev = None
        elif g.phase == "c40s2":
            off = getattr(g, "c40s2_offer", None) or {}
            who = int(off.get("by", -1))
            if who == seat or who in humans:
                ev = None                                  # 等发动者自己挑
            elif auto:
                ev = g.c40s2_auto()                        # 没人在操作 → 兜底副露
            else:
                ev = None
        elif g.c45s2_wait >= 0:
            # Card45 S2【替身】：等「第二位玩家」指定切牌
            _b = int((g.c45s2 or {}).get("second", -1))
            if _b == seat or _b in humans:
                ev = None                                  # 等人点
            elif auto:
                ev = g.c45s2_auto()                        # 没人在操作 → 兜底摸切
            else:
                ev = None
        elif g.phase == "wind_swap":
            w = getattr(g, "wind_swap", None) or {}
            owner = int(w.get("owner", -1))
            if owner == seat:
                ev = None                                  # 等我自己选牌
            elif owner not in humans and auto:
                ev = g.wind_swap_pass()                    # 没人在操作 → 兜底跳过
            else:
                ev = None
        elif g.phase == "deal_skill":
            pending = getattr(g, "deal_wait", set())
            _ask = g.c30_ask_for(seat)               # 向听：问到我了吗？
            _tgt = g.c30_give_target()               # 现在该谁交牌
            if _ask >= 0:
                ev = (None if (seat in humans or not auto)
                      else g.c30s1_auto(seat))       # 没人在操作 → 替他交两张
            elif _tgt >= 0 and _tgt not in humans and auto:
                ev = g.c30s1_auto(_tgt)              # 轮询的人替「没人的座位」交牌
            elif seat in pending:
                ev = None                                    # 等我决定（发动 / 跳过）
            else:
                others = ([s for s in sorted(pending) if s not in humans]
                          if auto else [])
                ev = g.deal_action(others[0], "skip") if others else None
        elif g.phase == "c25s2":
            off = getattr(g, "c25s2_offer", None) or {}
            who = int(off.get("owner", -1))
            if who == seat or who in humans:
                ev = None                                    # 等我自己选牌
            elif auto and who >= 0:
                ev = g.c25s2_auto_swap(who)                  # 没人在操作 → 替他换一张
            else:
                ev = None
        elif g.phase == "c29s1":
            off = getattr(g, "c29s1_offer", None) or {}
            who = int(off.get("seat", -1))
            if who == seat or who in humans:
                ev = None                                # 等他自己决定（不设超时）
            elif auto and who >= 0:
                ev = g.c29s1_skip(who)                   # 这个座位没人在操作 → 跳过
            else:
                ev = None
        elif g.phase in ("haishin", "shenshan", "youyin", "gift", "youyin_meld"):
            off = (g.haishin_offer if g.phase == "haishin"
                   else (g.shenshan_offer if g.phase == "shenshan"
                         else (g.youyin_meld_offer if g.phase == "youyin_meld"
                               else (g.gift_offer if g.phase == "gift"
                                     else g.youyin_offer)))) or {}
            who = int(off.get("owner", off.get("seat", -1)))
            if who == seat or who in humans:
                ev = None                                    # 等他自己决定
            elif auto and who >= 0:
                if g.phase == "haishin":
                    ev = g.haishin_pass(who)                 # 没人的座位 → 放弃借牌
                elif g.phase == "shenshan":
                    ev = g.shenshan_resolve(who, "")         # 跳过
                elif g.phase == "gift":
                    ev = g.gift_skip(who)                    # 跳过这次换牌
                elif g.phase == "youyin_meld":
                    ev = g.youyin_meld_skip()                # 没人的座位 → 直接收尾
                else:
                    ev = g.youyin_take(who, -1)              # 跳过
            else:
                ev = None
        elif g.phase == "claim":
            p = getattr(g, "pending", None)
            mine = bool(p) and seat in p["options"] and seat not in p["answers"]
            if mine:
                ev = None                                    # 等我决定
            else:
                # 只替「没人在操作」的座位过掉；别的人还在等自己的窗口作答
                others = ([s for s in (p["options"] if p else {})
                           if s not in humans and s not in p["answers"]] if auto else [])
                ev = g.pass_claim(others[0]) if others else None
        elif g.phase == "draw":
            if g.turn == seat:
                if bool(req.get("pre_ok")) or not g.pre_draw_pending(seat):
                    ev = g.advance()                         # 我自己摸（客户端问完技能了）
                else:
                    ev = {"event": "wait_pre", "seat": seat}  # 还有摸牌前技能要问
            elif g.turn in humans:
                ev = None                                    # 另一个窗口的人还没摸 → 等他
            elif auto:
                ev = g.advance()                             # 没人的座位 → 服务器替他摸
        elif g.phase == "discard":
            if g.turn == seat:
                ev = None                                    # 该我打牌 → 停下等我
            elif g.turn in humans:
                ev = None                                    # 另一个窗口的人还没打 → 等他
            elif auto:
                d = g.drawn_tile(g.turn) or ((g.hand(g.turn) or ["1m"])[-1])
                ev = g.act(g.turn, "discard", tile=d)
        return {"ok": True, "state": g.state_for(seat), "events": [ev] if ev else [],
                "result": g.result, "round_id": rid}


def op_wall(db: DB, req: dict) -> dict:
    """把这一局的牌山序列（seq 0..135 的顺序）给客户端。

    客户端拿它给牌山上每一张牌编号：编号 1 = seq 0 …… 编号 136 = seq 135，
    前 14 张就是王牌（岭上 4 + 表宝牌指示牌 4 + 里宝牌指示牌 4 + 留 2）。
    本地单机调试用；真联机时这个接口只留给服务器自己。
    """
    rid = req.get("round_id") or _get_round_id(db)
    rows = db._rows("SELECT seq, tile, zone FROM round_wall WHERE round_id=? ORDER BY seq", (rid,))
    return {"ok": True, "state": None, "events": [], "result": None,
            "wall": [r["tile"] for r in rows],
            "zones": [r["zone"] for r in rows],
            "round_id": rid}


OPS = {
    "join": op_join,
    "lobby_join": lobby_mod.op_join,
    "lobby_add_bot": lobby_mod.op_add_bot,       # 放入人机（自动摸切 / 跳过技能）
    "lobby_remove_bot": lobby_mod.op_remove_bot,
    "lobby_state": lobby_mod.op_state,
    "lobby_ready": lobby_mod.op_ready,
    "rename": lobby_mod.op_rename,          # 本局昵称
    "lobby_pick": lobby_mod.op_pick,
    "lobby_order": lobby_mod.op_order,
    "lobby_unorder": lobby_mod.op_unorder,
    "lobby_reset": lobby_mod.op_reset,
    "test_seats": lobby_mod.op_test_seats,      # 测试用：直接指定四家出战人物
    "result_confirm": op_result_confirm,
    "next": op_next,
    "new_hanchan": op_new_hanchan,
    "match_confirm": op_match_confirm,        # 半庄终局：四家确认 → 清房间
    "start": op_start,
    "deal_step": op_deal_step,
    "state": op_state,
    "poll": op_poll,
    "advance": op_advance,
    "act": op_act,
    "wall": op_wall,
    "step": op_step,
    "tenpai": op_tenpai,
    "press": op_press,
    "deal_skill": op_deal_skill,
    "deal_swap": op_deal_swap,
    "wind_swap": op_wind_swap,
    "card05_extra": op_card05_extra,
    "card05_swap": op_card05_swap,
    "card05_nuki": op_card05_nuki,
    "south_wind_kinds": op_south_wind_kinds,
    "south_wind_swap": op_south_wind_swap,
    "card05_cancel": op_card05_cancel,
    "skill_cancel": op_skill_cancel,
    "oracle_toggle": op_oracle_toggle,
    "oracle_pick": op_oracle_pick,
    "duel_start": op_duel_start,
    "card09_swap": op_card09_swap,
    "card10_hand": op_card10_hand,
    "card11_swap": op_card11_swap,
    "card11s2_swap": op_card11s2_swap,
    "shenshan_toggle": op_shenshan_toggle,
    "shenshan_resolve": op_shenshan_resolve,
    "nongwu": op_nongwu,
    "qianlu": op_qianlu,
    "ganzhi": op_ganzhi,
    "gift_swap": op_gift_swap,
    "xianfu_swap": op_xianfu_swap,
    "gift_skip": op_gift_skip,
    "youyin_take": op_youyin_take,
    "c29s1_chi": op_c29s1_chi,
    "c29s1_skip": op_c29s1_skip,
    "c30s1_arm": op_c30s1_arm,
    "c32s1_arm": op_c32s1_arm,
    "c32s1_give": op_c32s1_give,
    "c32s1_swap": op_c32s1_swap,
    "c33s1_swap": op_c33s1_swap,
    "c33s2_try": op_c33s2_try,
    "c34s1_arm": op_c34s1_arm,
    "c34s2_probe": op_c34s2_probe,
    "c35s1_set": op_c35s1_set,
    "c36s2_arm": op_c36s2_arm,
    "c37s1_arm": op_c37s1_arm,
    "c37s2_apply": op_c37s2_apply,
    "c38s1_view": op_c38s1_view,
    "c38s1_apply": op_c38s1_apply,
    "c40s1_apply": op_c40s1_apply,
    "c41_copy": op_c41_copy,
    "c43s1_apply": op_c43s1_apply,
    "c44s2_arm": op_c44s2_arm,
    "c45s1_apply": op_c45s1_apply,
    "c45s2_apply": op_c45s2_apply,
    "c45s2_pick": op_c45s2_pick,
    "c46s1_apply": op_c46s1_apply,
    "c39s1_apply": op_c39s1_apply,
    "c42s1_apply": op_c42s1_apply,
    "c40s2_apply": op_c40s2_apply,
    "c43s2_answer": op_c43s2_answer,
    "act_answer": op_act_answer,
    "c40s2_pick": op_c40s2_pick,
    "c42s2_arm": op_c42s2_arm,
    "c42s2_answer": op_c42s2_answer,
    "support_mute": op_support_mute,
    "c41_skip": op_c41_skip,
    "c30s1_give": op_c30s1_give,
    "c30s1_swap": op_c30s1_swap,
    "youyin_meld_arm": op_youyin_meld_arm,
    "youyin_meld_pick": op_youyin_meld_pick,
    "heat": op_heat,
    "c24_declare": op_c24_declare,
    "c27s1_swap": op_c27s1_swap,
    "c27s2_declare": op_c27s2_declare,
    "future_arm": op_future_arm,
    "c26_set": op_c26_set,
    "future_set": op_future_set,
    "chuancheng": op_chuancheng,
    "yanjiu": op_yanjiu,
    "kangpo": op_kangpo,
    "ignite": op_ignite,
    "kangpo_answer": op_kangpo_answer,
    "kangpo_skip": op_kangpo_skip,
    "jiasuo": op_jiasuo,
    "link": op_link,
    "zhalie_swap": op_zhalie_swap,
    "diaoyu_force": op_diaoyu_force,
    "pofa_activate": op_pofa_activate,
    "pofa_discard": op_pofa_discard,
    "pofa_pass": op_pofa_pass,
    "c25s2_arm": op_c25s2_arm,
    "c25s2_swap": op_c25s2_swap,
    "haishin_give": op_haishin_give,
    "haishin_swap": op_haishin_swap,
    "haishin_start": op_haishin_start,
    "haishin_pass": op_haishin_pass,
    "xn_activate": op_xn_activate,
    "card10s2_activate": op_card10s2_activate,
    "card10_meld": op_card10_meld,
    "card05_hide": op_card05_hide,
    "view_hand": op_view_hand,
    "skill": op_skill,
    "skill2": op_skill2,
    "board": op_board,
    "swap": op_swap,
    "wipe": op_wipe,
    "furiten": op_furiten,
    "yiding": op_yiding,
    "guobiao": op_guobiao,
    "ron": op_ron,
    "judge": op_judge,
}

# 看破闸门表必须覆盖全部 op（白名单漏发动点是历史 bug，这里 import 时就炸）
_GATE_KNOWN = set(_NO_GATE_OPS) | set(_GATE_INLINE) | set(_SKILL_OP_PAIRS)
_gate_dup = ((set(_NO_GATE_OPS) & set(_SKILL_OP_PAIRS))
             | (set(_GATE_INLINE) & set(_SKILL_OP_PAIRS))
             | (set(_NO_GATE_OPS) & set(_GATE_INLINE)))
if set(OPS) - _GATE_KNOWN or _GATE_KNOWN - set(OPS) or _gate_dup:
    raise RuntimeError(
        "看破闸门表没覆盖全：漏 %s / 多余 %s / 重复 %s"
        % (sorted(set(OPS) - _GATE_KNOWN), sorted(_GATE_KNOWN - set(OPS)),
           sorted(_gate_dup)))



# ★ 常驻服务端复用连接：原来每个请求都 DB(db_path) 新建连接，连 PRAGMA journal_mode=WAL
#   （这是个写操作）也要重跑一遍。实测带 0.6 秒间隔的请求要 73 ms，连续请求只要 4 ms
#   —— 时间全花在重新开连接/碰磁盘上。缓存后每次只剩业务查询。
#   · 只给 net_server 打开（CACHE_CONN=True）；测试脚本保持默认 False，
#     否则测试里删库文件会撞到未关闭的连接（WinError 32）。
CACHE_CONN = False
_DB_CACHE: dict = {}            # key -> {"db": DB, "used": float}
_DB_CACHE_MAX = 50              # ★ 最多缓存这么多房间的连接
_DB_CACHE_IDLE = 60.0           # ★ 只淘汰「空闲超过这么久」的（还在用的绝不关）
_DB_CACHE_LOCK = threading.Lock()


def _open_db(db_path: str):
    """缓存模式：连接建好时就初始化 schema，之后每个请求不用再查一次库。

    原来 handle() 每次都 db.init_schema()（查 meta 表 = 碰磁盘），
    实测这就是「空闲 200ms 后第一个请求要 57~72ms」的来源。

    ★ LRU：以前这个字典**只增不减**，每开一个新房间就多一条 sqlite 连接
      （每连接 cache_size = 16MB），跑上几天内存就被僵尸房间吃满。
      现在超过 _DB_CACHE_MAX 条就把最久没用的关掉。
    """
    if not CACHE_CONN:
        return DB(db_path)
    key = os.path.abspath(db_path)
    now = time.time()
    with _DB_CACHE_LOCK:
        slot = _DB_CACHE.pop(key, None)          # 先摘出来 → 重新插到末尾 = LRU
        if slot is not None:
            slot["used"] = now
            _DB_CACHE[key] = slot
            return slot["db"]
        d = DB(key)
        d.init_schema()
        _DB_CACHE[key] = {"db": d, "used": now}
        # 超上限 → 淘汰最久没用、且**空闲够久**的（空闲中的才可能没人在用）
        if len(_DB_CACHE) > _DB_CACHE_MAX:
            order = sorted(_DB_CACHE.items(), key=lambda kv: kv[1]["used"])
            for old_key, old_slot in order:
                if len(_DB_CACHE) <= _DB_CACHE_MAX:
                    break
                if now - old_slot["used"] < _DB_CACHE_IDLE:
                    break                        # 剩下的都是热连接，先留着
                if old_key == key:
                    continue
                _DB_CACHE.pop(old_key, None)
                try:
                    old_slot["db"].close()
                except Exception:                # noqa: BLE001
                    pass
        return d


def drop_cached_db(db_path: str) -> None:
    """把某个房间的缓存连接关掉（闲置房间回收时用，见 net_server.reap_idle_rooms）。"""
    if not db_path:
        return
    key = os.path.abspath(db_path)
    with _DB_CACHE_LOCK:
        slot = _DB_CACHE.pop(key, None)
    if slot:
        try:
            slot["db"].close()
        except Exception:                                # noqa: BLE001
            pass


def close_cached_dbs() -> None:
    with _DB_CACHE_LOCK:
        slots = list(_DB_CACHE.values())
        _DB_CACHE.clear()
    for s in slots:
        try:
            s["db"].close()
        except Exception:                                     # noqa: BLE001
            pass


def handle(req: dict, db_path: str = DB_PATH) -> dict:
    op = str(req.get("op", "state"))
    fn = OPS.get(op)
    if fn is None:
        return {"ok": False, "state": None, "events": [], "result": None,
                "error": f"不认识的 op: {op}"}
    # 复制品 / 传承品有**自己一份**一次性配额：客户端点左侧图标时带 copy=true，
    # 这里翻成 "card-skill" 告诉 Game「这一下花的是复制品那本账」。
    # 每次都先清空，避免上一次请求的标记漏到这一次。
    game_mod.REQ_COPY_KEY = ""
    if bool(req.get("copy")):
        _cp = _op_skill_pair(op, req)
        if _cp:
            game_mod.REQ_COPY_KEY = "%d-%d" % (_cp[0], _cp[1])
    db = None
    try:
        db = _open_db(db_path)
        if not CACHE_CONN:
            db.init_schema()       # 缓存连接在 _open_db 里已经初始化过了                       # 失败也要回 JSON，不能让客户端「没回话」
        seat = req.get("seat")
        # ★ 每个「带座位的请求」都刷新一次租约。
        #   以前只有 join 才刷：一个人在正常玩（12 秒内没再 join）租约就过期，
        #   别人 join 时服务端把这个座位分给他 → 两个人操控同一个人。
        #   现在他只要还活着、还在发请求，座位就一直归他（死窗口不再发请求，照样过期）。
        if isinstance(seat, int) and 0 <= int(seat) <= 3:
            _touch_lease(db, int(seat))
        # Card34 S1【厄运】：静默期内其他三家不能使用任何技能
        if (op not in _C34_FREE_OPS and isinstance(seat, int)
                and 0 <= int(seat) <= 3):
            _rid_c34 = req.get("round_id") or _get_round_id(db)
            if _rid_c34:
                _g_c34 = _game(db, _rid_c34)
                if _g_c34.c34_muted(int(seat)):
                    return {"ok": False, "state": _g_c34.state_for(int(seat)),
                            "events": [], "result": _g_c34.result,
                            "error": "【厄运】期间不能使用技能"}
        # Card42 S1【理论战】：本局所有技能封死（连看破都不问）
        if (op in _SKILL_OP_PAIRS or op in _GATE_INLINE) \
                and isinstance(seat, int) and 0 <= int(seat) <= 3:
            _rid_42 = req.get("round_id") or _get_round_id(db)
            if _rid_42 and _game(db, _rid_42).c42s1_lock():
                return {"ok": False, "state": None, "events": [], "result": None,
                        "error": "【理论战】：本局谁都不能发动技能"}
        # Card45 S2【替身】：被接管切牌的那一家，这一回合不能发动任何技能
        if (op in _SKILL_OP_PAIRS and isinstance(seat, int) and 0 <= int(seat) <= 3):
            _rid_s2 = req.get("round_id") or _get_round_id(db)
            if _rid_s2 and _game(db, _rid_s2).c45s2_locked(int(seat)):
                return {"ok": False, "state": None, "events": [], "result": None,
                        "error": "【替身】：这一回合你的切牌由对方指定，不能发动技能"}
        # 拦截树：询问超时 → 当作放行
        if op != "act_answer":
            _rid_at = req.get("round_id") or _get_round_id(db)
            if _rid_at:
                _gat = _game(db, _rid_at)
                if _gat.act_timeout():
                    _after_act(db, _gat, _rid_at,
                               int(seat) if isinstance(seat, int) else 0)
        # 先续租：任何带座位的请求都算「这个座位还活着」。
        # 必须放在看破判断之前 —— 否则刚开的窗口第一发技能会被当成 AI。
        if isinstance(seat, int) and 0 <= seat <= 3 and op != "join":
            _touch_lease(db, seat, req.get("pid"))
        # 向听：该交牌的那家没人在操作（AI / 窗口关了）→ 任何请求顺手替它交。
        # 放在这里而不是只放 step 里：客户端卡在「被询问」时只会发 op=state，
        # 只认 step 的话这种局面永远推不动（2026-10-27 现场就卡成这样）。
        _rid_x = req.get("round_id") or _get_round_id(db)
        if _rid_x and op not in ("c30s1_give", "c30s1_swap"):
            _gx = _game(db, _rid_x)
            if _gx.phase == "deal_skill":
                _tgt_x = _gx.c30_give_target()
                if _tgt_x >= 0 and _tgt_x not in _human_seats(db):
                    try:
                        _gx.c30s1_auto(_tgt_x)
                    except Exception:
                        pass
                _tgt_y = _gx.c32_give_target()
                if _tgt_y >= 0 and _tgt_y not in _human_seats(db):
                    try:
                        _gx.c32s1_auto(_tgt_y)
                    except Exception:
                        pass
        # 看破挂起太久（持有者窗口关了 / 一直没回答）→ 自动放弃这一次，别把整局卡死
        # （c42s2_answer 自己也要排除：玩家卡着点答上来时别先被超时抢先结算掉）
        if op not in ("kangpo_answer", "kangpo_skip", "c42s2_answer"):
            _rid_t = req.get("round_id") or _get_round_id(db)
            if _rid_t:
                _gt = _game(db, _rid_t)
                _p = _gt.kangpo_pending or {}
                _ts = float(_p.get("ts", 0) or 0)
                if _ts and (time.time() - _ts) > 15.0:
                    _gt.kangpo_ask = None
                    _gt.kangpo_pending = None
                    _gt.save_flags()
                # 【同盟】：发动者一直不挑搭子 → 按第一组直接副露
                if _gt.c40s2_timeout():
                    try:
                        _gt.c40s2_auto()
                    except Exception:
                        pass
                # 【替身】：第二位一直不点 → 替第一位摸切，别把整局卡死
                if _gt.c45s2_timeout():
                    try:
                        _gt.c45s2_auto()
                    except Exception:
                        pass
                # 破发询问超时：当前这个不回答 → 跳过他，问下一个
                _pa = _gt.pofa_ask or {}
                _ts2 = float(_pa.get("ts", 0) or 0)
                if _ts2 and (time.time() - _ts2) > 15.0:
                    _w = [int(x) for x in (_pa.get("waiting") or [])]
                    if _w:
                        _w.pop(0)
                    if _w:
                        _pa["waiting"] = _w
                        _pa["ts"] = time.time()
                        _gt.pofa_ask = _pa
                    else:
                        _gt.pofa_ask = None
                        _gt.pofa_window = None
                    _gt.save_flags()
                # 配牌技能阶段：有人一直不点「发动 / 开始」→ 超时就服务端自己跳过。
                # 不兜底的话整局停在 deal_skill，四家谁都不能摸打（手牌卡死）。
                if _gt.phase == "deal_skill" and _gt.deal_skill_timeout():
                    _gt.deal_skip_all()
                # 友引段1 摊面子：掉线 / 一直不选 → 服务端自己收尾。
                # 不兜底的话 prompt_state 会把全桌的 step/advance/draw/act 全拦死。
                if _gt.phase == "youyin_meld" and _gt.youyin_meld_timeout():
                    _gt.youyin_meld_skip()
                # 未来：已经发动了却一直不排序（客户端掉线）→ 放弃这次重排，放开摸牌。
                if _gt.future_timeout():
                    _gt.future_abort()
                # 天梯：轮到某人摸牌却一直不排牌山 → 第一次发现记截止时间，超时就跳过。
                if _gt.turn is not None and _gt.c26_can_sort(int(_gt.turn)):
                    if float(_gt.c26_deadline or 0) <= 0.0:
                        _gt.c26_deadline = time.time() + 30.0
                        _gt.save_flags()
                elif _gt.c26_timeout():
                    _gt.c26_skip()
        # 自愈：phase 卡在加速询问却没有 offer（异常路径）→ 这一手收尾，轮到下家摸。
        # 不加的话 flags 里会永远留着 phase=c29s1，全桌谁都动不了。
        _rid_h = req.get("round_id") or _get_round_id(db)
        if _rid_h:
            _gh = _game(db, _rid_h)
            if _gh.phase == "c29s1" and not _gh.c29s1_offer:
                _gh._advance_after_discard(int(_gh.turn if _gh.turn is not None else 0))
                _gh.save_flags()
        # 统一询问锁：只要有人在等回答（看破/海神/深山/友引/破发），
        # 谁都不能摸牌、打牌、推进对局。
        if op in ("step", "advance", "draw", "act"):
            _rid_w = req.get("round_id") or _get_round_id(db)
            if _rid_w:
                _gw = _game(db, _rid_w)
                _pr = _gw.prompt_state()
                if _pr:
                    _w = [int(x) for x in (_pr.get("waiting") or [])]
                    if not any(x in _human_seats(db) for x in _w):
                        _pr = None          # 等的是 AI（没窗口）→ 不锁，让 step 去跳过
                if _pr:
                    _sw = int(seat) if isinstance(seat, int) and 0 <= int(seat) <= 3 else 0
                    _kind = str(_pr.get("kind", ""))
                    return {"ok": False, "state": _gw.state_for(_sw), "events": [],
                            "result": _gw.result, "round_id": _rid_w,
                            "waiting_prompt": _kind,
                            "waiting_kangpo": _kind in ("kangpo", "act"),
                            "error": "现在有人在等回答，稍后"}
        # 拦截树：可被拦的技能发动 → 先建节点；有人要答就停在这里（op 不执行）
        _gp = _gate_pair(op, req)
        # A7【阻止】(31-2)：本回合被阻止过的「同一家 + 同一技能」不许再发一次
        if _gp and isinstance(seat, int) and 0 <= int(seat) <= 3 and not req.get("_act_ran"):
            _rid_s = req.get("round_id") or _get_round_id(db)
            if _rid_s:
                _gs = _game(db, _rid_s)
                try:
                    _stopd = _gs.c31s2_stopped_now(int(seat), int(_gp[0]), int(_gp[1]))
                except Exception:
                    _stopd = False
                if _stopd:
                    return {"ok": False, "state": _gs.state_for(int(seat)), "events": [],
                            "result": _gs.result, "round_id": _rid_s,
                            "error": "这个技能本回合已经被【阻止】了，这一巡不能再发动"}
        # ★ 注定发不动的（已经用过 / 时机不对）→ 不问看破，让 op 自己回真正的原因。
        #   不加这一条，客户端收到的永远是 need_kangpo =「等对方拦截」死循环。
        if (_gp and not req.get("_gate_ok") and not req.get("_act_ran")
                and op != "act_answer" and isinstance(seat, int) and 0 <= seat <= 3
                and _gate_cannot_fire(db, req.get("round_id") or _get_round_id(db),
                                      op, int(seat), int(_gp[0]), int(_gp[1]))):
            _gp = None
        if (_gp and not req.get("_gate_ok") and not req.get("_act_ran")
                and op != "act_answer" and isinstance(seat, int) and 0 <= seat <= 3):
            _rid_k = req.get("round_id") or _get_round_id(db)
            if _rid_k:
                _gk = _game(db, _rid_k)
                _card, _skill = _gp
                _pl = {k: v for k, v in req.items() if k not in ("op", "seat", "pid")}
                _aid = _gk.act_spawn(int(seat), int(_card), int(_skill), op=op, payload=_pl)
                _node = _gk.act_node(_aid)
                if (_node.get("state") == "voided"
                        and str(_node.get("note", "")) in ("poked", "免疫")):
                    if str(_node.get("note", "")) == "poked":
                        req = dict(req)
                        req["_act_ran"] = True          # 这张卡已经被剔除 → 让 op 自己拒
                    else:
                        return {"ok": False, "state": _gk.state_for(int(seat)),
                                "events": [], "result": _gk.result, "round_id": _rid_k,
                                "error": "【免疫】：这个技能对你无效（本次发动作废）"}
                if _node.get("state") != "applied" and not req.get("_act_ran"):
                    _st = _gk.state_for(int(seat))
                    if _node.get("state") == "voided" and _node.get("note") == "免疫":
                        return {"ok": False, "state": _st, "events": [],
                                "result": _gk.result, "round_id": _rid_k,
                                "error": "【免疫】：这个技能对你无效（本次发动作废）"}
                    return {"ok": True, "need_kangpo": True, "state": _st,
                            "events": [], "result": _gk.result, "round_id": _rid_k,
                            "asks": _gk.act_ask_view(int(seat))}
                # 没人可拦 → 继续往下执行（下面 fn(db, req) 会再 spawn 一次，
                #  这里补 _act_ran 标志让它跳过闸门）
                req = dict(req)
                req["_act_ran"] = True
        if op in _RIICHI_BLOCK_OPS and isinstance(seat, int) and 0 <= seat <= 3:
            _rid = req.get("round_id") or _get_round_id(db)
            if _rid:
                _g = _game(db, _rid)
                if _g.is_riichi(int(seat)):
                    return {"ok": False, "state": _g.state_for(int(seat)),
                            "events": [], "result": None,
                            "error": "已经立直了：不能再发动会改动自己手牌的技能"}
        res = fn(db, req)
        # 所有带 state 的响应都附上 ver：客户端轮询时带回来，服务端就能只回
        # {"same": true}（几十字节），不用每次都传整份 21KB
        if isinstance(res, dict) and isinstance(res.get("state"), dict):
            res["ver"] = _state_ver(res["state"])
        return res
    except RuleError as e:
        return {"ok": False, "state": None, "events": [], "result": None, "error": str(e)}
    except Exception as e:                                    # noqa: BLE001
        return {"ok": False, "state": None, "events": [], "result": None,
                "error": f"{type(e).__name__}: {e}"}
    finally:
        if db is not None and not CACHE_CONN:
            db.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="infile")
    ap.add_argument("--out", dest="outfile")
    ap.add_argument("--db", dest="db_path", default=DB_PATH)
    ap.add_argument("--op")
    ap.add_argument("--seat", type=int)
    ap.add_argument("--action")
    ap.add_argument("--tile")
    ap.add_argument("--hand")
    args = ap.parse_args()

    if args.infile:
        with open(args.infile, "r", encoding="utf-8") as f:
            req = json.load(f)
    elif args.op:
        req = {"op": args.op}
        for k in ("seat", "action", "tile", "hand"):
            v = getattr(args, k)
            if v is not None:
                req[k] = v
    else:
        req = json.loads(sys.stdin.read() or "{}")

    res = handle(req, args.db_path)
    text = json.dumps(res, ensure_ascii=False)
    if args.outfile:
        try:
            with open(args.outfile, "w", encoding="utf-8") as f:
                f.write(text)
        except OSError as e:
            print(f"写响应文件失败: {e}", file=sys.stderr)
    print(text)
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
