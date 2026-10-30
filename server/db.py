# -*- coding: utf-8 -*-
"""
天马麻将 · 服务器数据库层
======================================================================
只用 Python 自带的 sqlite3，不需要装任何东西（不需要联网、不需要数据库服务）。

它是「服务器的记忆」。记住的东西：
    账号 / 登录会话 / 房间 / 座位 / 对局 / 每一局 / 牌山 / 手牌 /
    牌河 / 副露 / 立直 / 宝牌 / 动作日志 / 分数流水

三条铁律（联机防作弊的关键）：
    1. 牌山顺序、别人的手牌 → 只存在这里，永远不发给客户端。
    2. 一张物理牌 = 一个唯一编号 wall_seq（0..135），所有表都用它指代，
       否则两张"5m"分不清谁是谁。
    3. 每个动作一个事务；客户端重复发同一个动作（client_action_id 相同）
       不会被执行两次。

用法：
    from db import DB
    db = DB()                      # 默认 server/data/mahjong.db
    db.init_schema()               # 建表（可重复调用）

    # 一局牌从发牌开始
    rid = db.start_round(match_id, "dong", 1, honba=0, dealer_seat=0)
    t = db.draw(rid, seat=0)                 # 摸牌
    db.discard(rid, seat=0)                  # 打刚摸的那张（摸切）
    db.public_state(rid)                     # 公开信息（不含任何手牌/牌山）
    db.private_state(rid, seat=0)            # 公开信息 + 我自己的手牌

命令行：
    python db.py init  [数据库路径]     # 建库
    python db.py info  [数据库路径]     # 看库里的概况
"""

from __future__ import annotations

import contextlib
import json
import os
import random
import sqlite3
import time

SCHEMA_VERSION = "1"

# ── 牌的基础工具：统一放在 tiles.py，数据库层和规则层共用同一份 ──────────────
from tiles import (RED_FIVES, TILE_KINDS, build_entity_wall, dora_from_indicator,   # noqa: E402
                   entity_tile, is_honor, kind_of, tile_number, tile_suit)

# 王牌（dead wall）14 张的用途，服务器自己定死，别改乱
DEAD_KAN_FROM = 0      # dead[0:4]  = 岭上牌（杠了从这里补摸）
DEAD_DORA_FROM = 4     # dead[4:8]  = 表宝牌指示牌（第 1 张开局翻开，杠一次多翻一张）
DEAD_URA_FROM = 8      # dead[8:12] = 里宝牌指示牌


# ═══════════════════════════════════════════════════════════════════════════
#  数据库
# ═══════════════════════════════════════════════════════════════════════════
class DB:
    def __init__(self, path: str | None = None, schema_path: str | None = None):
        here = os.path.dirname(os.path.abspath(__file__))
        self.path = path or os.path.join(here, "data", "mahjong.db")
        self.schema_path = schema_path or os.path.join(here, "schema.sql")
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.conn = sqlite3.connect(self.path, isolation_level=None, timeout=10.0)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")     # 读写不会互相卡住
        self.conn.execute("PRAGMA busy_timeout = 10000")
        self._tx_depth = 0

    # ── 生命周期 ────────────────────────────────────────────────────────────
    def close(self) -> None:
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _schema_current(self) -> bool:
        """表已经建好、版本也对得上 → 不用再跑一遍建表脚本。"""
        try:
            row = self._row("SELECT value FROM meta WHERE key='schema_version'")
        except sqlite3.OperationalError:
            return False
        return bool(row) and str(row["value"]) == str(SCHEMA_VERSION)

    def init_schema(self) -> None:
        # ★ 四个窗口同时启动时，每个请求都会调 init_schema。
        #   每次都 executescript（建表 + 索引）会抢写锁，偶尔直接 OperationalError，
        #   那条请求就没有响应文件了 → 客户端显示「连不上服务端」。
        #   版本没变就直接返回；真要建表时对 database is locked 重试几次。
        if self._schema_current():
            # ★ 版本对上也不能直接 return：老库可能还缺新加的列（_migrate 负责补）
            self._migrate()
            return
        with open(self.schema_path, "r", encoding="utf-8") as f:
            sql = f.read()
        for attempt in range(6):
            try:
                self.conn.executescript(sql)
                break
            except sqlite3.OperationalError as e:
                if "locked" not in str(e).lower() or attempt == 5:
                    raise
                time.sleep(0.15 * (attempt + 1))
        self._migrate()
        self.conn.execute(
            "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (SCHEMA_VERSION,),
        )

    def _migrate(self) -> None:
        """老库补新字段。

        CREATE TABLE IF NOT EXISTS 只对「还不存在的表」生效，
        已经建好的表不会因为 schema.sql 改了就多出列来，所以这里手动补。
        """
        cols = {r["name"] for r in self._rows("PRAGMA table_info(round_melds)")}
        if "seqs_json" not in cols:          # 副露里每张牌的物理编号（wall_seq）
            self.conn.execute("ALTER TABLE round_melds "
                              "ADD COLUMN seqs_json TEXT NOT NULL DEFAULT '[]'")
        dcols = {r["name"] for r in self._rows("PRAGMA table_info(round_discards)")}
        if "face_down" not in dcols:          # 换牌技能：暗置进牌河的牌
            self.conn.execute("ALTER TABLE round_discards "
                              "ADD COLUMN face_down INTEGER NOT NULL DEFAULT 0")
        if "is_nuki" not in dcols:            # 拔北放下的北（不算振听）
            self.conn.execute("ALTER TABLE round_discards "
                              "ADD COLUMN is_nuki INTEGER NOT NULL DEFAULT 0")
        wcols = {r["name"] for r in self._rows("PRAGMA table_info(round_wall)")}
        if "entity" not in wcols:            # 牌山实体编号（1m01 这种全局唯一 ID）
            self.conn.execute("ALTER TABLE round_wall "
                              "ADD COLUMN entity TEXT NOT NULL DEFAULT ''")

    @contextlib.contextmanager
    def tx(self):
        """一个事务。可以嵌套（内层用 SAVEPOINT）。"""
        if self._tx_depth > 0:
            name = f"sp{self._tx_depth}"
            self.conn.execute(f"SAVEPOINT {name}")
            self._tx_depth += 1
            try:
                yield
            except Exception:
                self.conn.execute(f"ROLLBACK TO {name}")
                raise
            else:
                self.conn.execute(f"RELEASE {name}")
                self._tx_depth -= 1
            return
        self.conn.execute("BEGIN IMMEDIATE")
        self._tx_depth = 1
        try:
            yield
        except Exception:
            self.conn.execute("ROLLBACK")
            self._tx_depth = 0
            raise
        else:
            self.conn.execute("COMMIT")
            self._tx_depth = 0

    # ── 小工具 ──────────────────────────────────────────────────────────────
    def _rows(self, sql: str, params=()) -> list[dict]:
        return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def _row(self, sql: str, params=()) -> dict | None:
        r = self.conn.execute(sql, params).fetchone()
        return dict(r) if r else None

    def _one(self, sql: str, params=()):
        r = self.conn.execute(sql, params).fetchone()
        return r[0] if r else None

    # ── 本局临时状态落库（服务器一次请求一个进程，内存里的东西不能只放内存）──
    def save_round_flags(self, round_id: int, flags: dict) -> None:
        with self.tx():
            self.conn.execute(
                "INSERT INTO round_flags(round_id, flags_json, updated_at) VALUES(?,?,datetime('now')) "
                "ON CONFLICT(round_id) DO UPDATE SET flags_json=excluded.flags_json, "
                "updated_at=excluded.updated_at",
                (round_id, json.dumps(flags, ensure_ascii=False)))

    def load_round_flags(self, round_id: int) -> dict:
        row = self._row("SELECT flags_json FROM round_flags WHERE round_id=?", (round_id,))
        if not row:
            return {}
        try:
            return json.loads(row["flags_json"] or "{}") or {}
        except (ValueError, TypeError):
            return {}

    # ── 牌山相关（编号系统在服务端：编号 no ↔ seq no-1）────────────────────
    def tile_at_seq(self, round_id: int, seq: int) -> str | None:
        row = self._row("SELECT tile FROM round_wall WHERE round_id=? AND seq=?", (round_id, seq))
        return row["tile"] if row else None

    def draw_seq(self, round_id: int, seat: int, seq: int, tile: str | None = None,
                 drawn: bool = False, dead: bool = False,
                 client_action_id: str | None = None) -> str | None:
        """把「seq 那张牌」发给某家（配牌 / 岭上 / 普通摸牌都走它）。

        drawn=True = 刚摸进还没打出的那张（手里最多一张）。
        dead=True  = 从王牌里拿（岭上），不动 live_left。
        """
        with self.tx():
            if self._is_duplicate(round_id, seat, client_action_id):
                return None
            row = self._row("SELECT tile FROM round_wall WHERE round_id=? AND seq=?", (round_id, seq))
            if not row:
                return None
            t = tile or row["tile"]
            self.conn.execute("UPDATE round_hands SET is_drawn = 0 WHERE round_id=? AND seat=?",
                              (round_id, seat))
            slot = (self._one("SELECT COALESCE(MAX(slot), -1) + 1 FROM round_hands "
                              "WHERE round_id=? AND seat=?", (round_id, seat)) or 0)
            self.conn.execute(
                "INSERT INTO round_hands(round_id, seat, wall_seq, tile, slot, is_drawn) "
                "VALUES(?,?,?,?,?,?)", (round_id, seat, seq, t, slot, 1 if drawn else 0))
            draw_no = (self._one("SELECT COALESCE(MAX(draw_no), -1) + 1 FROM round_wall "
                                 "WHERE round_id=?", (round_id,)) or 0)
            self.conn.execute("UPDATE round_wall SET dealt_to=?, draw_no=? WHERE round_id=? AND seq=?",
                              (seat, draw_no, round_id, seq))
            if not dead:
                self.conn.execute("UPDATE rounds SET live_left = MAX(live_left - 1, 0) WHERE round_id=?",
                                  (round_id,))
            self._log(round_id, seat, "draw" if drawn else "deal",
                      {"seq": seq, "tile": t, "dead": bool(dead)}, client_action_id)
        return t

    def add_dora(self, round_id: int, kind: str, idx: int, indicator: str,
                 dora: str | None = None) -> None:
        """翻开一张宝牌指示牌（kind='dora'）或里宝牌指示牌（kind='ura'）。"""
        with self.tx():
            self.conn.execute(
                "INSERT INTO round_dora(round_id, kind, idx, indicator, dora, revealed) "
                "VALUES(?,?,?,?,?,1) "
                "ON CONFLICT(round_id, kind, idx) DO UPDATE SET indicator=excluded.indicator, "
                "dora=excluded.dora, revealed=1",
                (round_id, kind, idx, indicator, dora or ""))

    def entity_states(self, round_id: int) -> list[dict]:
        """返回 136 张牌的全局实体状态（按 seq 排序）。

        每张牌：id(实体编号)、kind(牌种)、loc(wall/dead/hand/meld/river/dora)、
        seat(归属座位，墙内为 -1)、form(显示形式)、rotated(是否横置)、slot(槽位)、
        group(副露组号，仅 loc=meld 有)。服务端只给「语义状态」，客户端据此算位置。
        """
        wall = self._rows(
            "SELECT seq, tile, entity, zone, dealt_to FROM round_wall "
            "WHERE round_id=? ORDER BY seq", (round_id,))
        hands = {r["wall_seq"]: r for r in self._rows(
            "SELECT wall_seq, seat, slot, is_drawn FROM round_hands WHERE round_id=?",
            (round_id,))}
        # 牌河：按全场打出顺序（seq）排，再按座位给每家自己的槽位号
        discards = {}
        river_counter = {}
        for r in self._rows(
                "SELECT seq, wall_seq, seat, is_riichi_tile, face_down FROM round_discards "
                "WHERE round_id=? AND called=0 ORDER BY seq", (round_id,)):
            s = int(r["seat"])
            slot = int(river_counter.get(s, 0))
            river_counter[s] = slot + 1
            discards[int(r["wall_seq"])] = {
                "seat": s, "is_riichi_tile": r["is_riichi_tile"], "slot": slot,
                "discard_seq": int(r["seq"]), "face_down": int(r["face_down"] or 0),
            }
        # 副露：seqs_json 是物理编号数组，tiles_json 是显示顺序；meld_id 是组号
        meld_seq = {}
        for r in self._rows(
                "SELECT meld_id, seat, kind, rot_index, seqs_json, tiles_json "
                "FROM round_melds WHERE round_id=?", (round_id,)):
            try:
                seqs = json.loads(r["seqs_json"] or "[]")
                tiles = json.loads(r["tiles_json"] or "[]")
            except (ValueError, TypeError):
                seqs, tiles = [], []
            for i, ws in enumerate(seqs):
                meld_seq[int(ws)] = {
                    "seat": r["seat"], "kind": r["kind"],
                    "rot": int(r["rot_index"]) == i,
                    "closed": r["kind"] == "ankan",
                    "tiles": tiles, "pos": i, "group": int(r["meld_id"]),
                }
        dora_seq = set()
        for r in self._rows(
                "SELECT indicator FROM round_dora WHERE round_id=? AND revealed=1",
                (round_id,)):
            # 宝牌指示牌本身在 round_wall 里靠 tile 匹配（indicator 是牌名）
            for w in wall:
                if w["tile"] == r["indicator"] and w["seq"] not in dora_seq and w["zone"] == "dead":
                    dora_seq.add(w["seq"])
                    break

        out = []
        seen: dict[str, int] = {}
        for w in wall:
            seq = int(w["seq"])
            # 实体编号 = 牌面 + 「这个牌面的第几张」（按 seq 顺序现算）。
            # 换牌后牌面变了，序号跟着重排 → 同一编号永远只对应一种牌面，
            # 不会出现「两张一样的牌」，也不会「旧牌面挂旧编号」。
            seen[str(w["tile"])] = seen.get(str(w["tile"]), 0) + 1
            entity = str(w["tile"]) + f"{seen[str(w['tile'])]:02d}"
            st = {"id": entity, "kind": w["tile"], "seq": seq,
                  "loc": "wall", "seat": -1, "form": "hidden", "rotated": False,
                  "slot": 0}
            if seq in hands:
                h = hands[seq]
                st.update({"loc": "hand", "seat": h["seat"],
                           "form": "hand", "slot": h["slot"],
                           "drawn": bool(h["is_drawn"])})
            elif seq in meld_seq:
                m = meld_seq[seq]
                form = "back_meld" if m["closed"] else "face_meld"
                st.update({"loc": "meld", "seat": m["seat"], "form": form,
                           "rotated": m["rot"], "slot": m["pos"],
                           "meld_kind": m["kind"], "group": m["group"]})
            elif seq in discards:
                d = discards[seq]
                st.update({"loc": "river", "seat": d["seat"], "form": "river",
                           "rotated": bool(d["is_riichi_tile"]), "slot": d["slot"],
                           "discard_seq": d["discard_seq"], "face_down": d["face_down"]})
            elif seq in dora_seq:
                st.update({"loc": "dora", "seat": -1, "form": "dora"})
            elif w["zone"] in ("dead",):
                st.update({"loc": "dead", "form": "hidden"})
            out.append(st)
        return out

    def wall_taken_nos(self, round_id: int) -> list[int]:
        """已经拿走的牌「编号」列表（编号 = seq + 1），客户端拿去改牌墩显示。"""
        return [r["seq"] + 1 for r in self._rows(
            "SELECT seq FROM round_wall WHERE round_id=? AND dealt_to IS NOT NULL ORDER BY seq",
            (round_id,))]

    # ═══════════════════════════════════════════════════════════════════════
    #  1. 账号 / 登录
    # ═══════════════════════════════════════════════════════════════════════
    def create_user(self, nickname: str, pass_hash: str | None = None,
                    is_guest: bool = False, rating: int = 1500) -> int:
        with self.tx():
            cur = self.conn.execute(
                "INSERT INTO users(nickname, pass_hash, is_guest, rating) VALUES(?,?,?,?)",
                (nickname, pass_hash, 1 if is_guest else 0, rating),
            )
            return cur.lastrowid

    def find_user(self, nickname: str) -> dict | None:
        return self._row("SELECT * FROM users WHERE nickname = ?", (nickname,))

    def create_session(self, user_id: int, token: str | None = None,
                       ttl_hours: int = 24 * 7) -> str:
        import secrets
        token = token or secrets.token_urlsafe(24)
        with self.tx():
            self.conn.execute(
                "INSERT INTO sessions(token, user_id, expires_at, last_seen) "
                "VALUES(?,?,datetime('now', ?), datetime('now'))",
                (token, user_id, f"+{ttl_hours} hours"),
            )
        return token

    def resolve_session(self, token: str) -> dict | None:
        """断线重连：拿 token 换回玩家身份。"""
        row = self._row(
            "SELECT s.token, s.user_id, u.nickname FROM sessions s "
            "JOIN users u ON u.user_id = s.user_id "
            "WHERE s.token = ? AND (s.expires_at IS NULL OR s.expires_at > datetime('now'))",
            (token,),
        )
        if row:
            with self.tx():
                self.conn.execute("UPDATE sessions SET last_seen = datetime('now') WHERE token = ?",
                                  (token,))
        return row

    # ═══════════════════════════════════════════════════════════════════════
    #  2. 房间
    # ═══════════════════════════════════════════════════════════════════════
    def create_room(self, host_user: int, mode: str = "east_only",
                    rules: dict | None = None, room_code: str | None = None) -> dict:
        import secrets
        code = room_code or "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789")
                                    for _ in range(6))
        with self.tx():
            cur = self.conn.execute(
                "INSERT INTO rooms(room_code, host_user, mode, rule_json) VALUES(?,?,?,?)",
                (code, host_user, mode, json.dumps(rules or {}, ensure_ascii=False)),
            )

            room_id = cur.lastrowid
            self.conn.execute(
                "INSERT INTO room_seats(room_id, seat, user_id, ready) VALUES(?,0,?,1)",
                (room_id, host_user),
            )
        return {"room_id": room_id, "room_code": code}

    def join_room(self, room_code: str, user_id: int) -> dict:
        with self.tx():
            room = self._row("SELECT * FROM rooms WHERE room_code = ?", (room_code,))
            if not room:
                raise ValueError("房间不存在")
            if room["status"] != "waiting":
                raise ValueError("这局已经开始了")
            used = {r["seat"] for r in self._rows(
                "SELECT seat FROM room_seats WHERE room_id = ?", (room["room_id"],))}
            free = [s for s in range(4) if s not in used]
            if not free:
                raise ValueError("房间满了")
            seat = free[0]
            self.conn.execute(
                "INSERT INTO room_seats(room_id, seat, user_id) VALUES(?,?,?)",
                (room["room_id"], seat, user_id),
            )
            self.conn.execute("UPDATE rooms SET updated_at = datetime('now') WHERE room_id = ?",
                              (room["room_id"],))
        return {"room_id": room["room_id"], "seat": seat}

    def set_ready(self, room_id: int, seat: int, ready: bool = True) -> None:
        with self.tx():
            self.conn.execute("UPDATE room_seats SET ready = ? WHERE room_id = ? AND seat = ?",
                              (1 if ready else 0, room_id, seat))

    def room_view(self, room_id: int) -> dict:
        room = self._row("SELECT * FROM rooms WHERE room_id = ?", (room_id,))
        if not room:
            return {}
        room["rule_json"] = json.loads(room["rule_json"] or "{}")
        room["seats"] = self._rows(
            "SELECT s.seat, s.ready, s.user_id, u.nickname FROM room_seats s "
            "LEFT JOIN users u ON u.user_id = s.user_id WHERE s.room_id = ? ORDER BY s.seat",
            (room_id,),
        )
        return room

    # ═══════════════════════════════════════════════════════════════════════
    #  3. 开局：match（一场） → round（一局）
    # ═══════════════════════════════════════════════════════════════════════
    def start_match(self, room_id: int, seed: int | None = None) -> int:
        """房间人齐了 → 开一场对局；座位按房间顺序 0..3 → 东南西北。"""
        with self.tx():
            seats = self._rows(
                "SELECT s.seat, s.user_id, u.nickname FROM room_seats s "
                "LEFT JOIN users u ON u.user_id = s.user_id "
                "WHERE s.room_id = ? ORDER BY s.seat", (room_id,))
            if len(seats) != 4:
                raise ValueError("要 4 个人才能开局")
            cur = self.conn.execute(
                "INSERT INTO matches(room_id, status, wall_seed) VALUES(?, 'playing', ?)",
                (room_id, seed),
            )
            match_id = cur.lastrowid
            for s in seats:
                self.conn.execute(
                    "INSERT INTO match_seats(match_id, seat, user_id, nickname, score) "
                    "VALUES(?,?,?,?,35000)",
                    (match_id, s["seat"], s["user_id"], s["nickname"]),
                )
            self.conn.execute("UPDATE rooms SET status = 'playing' WHERE room_id = ?", (room_id,))
        return match_id

    def start_round(self, match_id: int, wind: str, number: int, honba: int,
                    dealer_seat: int, seed: int | None = None,
                    dead_wall_size: int = 14, red_fives: bool = True,
                    riichi_sticks: int = 0) -> int:
        """
        发牌：洗牌 → 写牌山（136 张全部标 live，王牌哪几墩由服务端的骰子决定）。

        注意：开局**不发牌、不翻宝牌** —— 发牌由 Game.deal_step() 按骰子点数一步步发
        （客户端只照着摆）；宝牌指示牌也由 Game.reveal_dora() 按王牌位置翻。
        """
        wall = build_entity_wall(red_fives=red_fives, seed=seed)

        # 场次数据只允许：dong/nan/xi/bei + 1..4 + 本场 >= 0
        wind = wind if wind in ("dong", "nan", "xi", "bei") else "dong"
        number = max(1, min(4, int(number)))
        honba = max(0, int(honba))

        with self.tx():
            idx = self._one("SELECT COALESCE(MAX(round_index),0)+1 FROM rounds WHERE match_id = ?",
                            (match_id,))
            cur = self.conn.execute(
                "INSERT INTO rounds(match_id, round_index, wind, number, honba, dealer_seat, "
                "turn_seat, status, riichi_sticks) VALUES(?,?,?,?,?,?,?, 'playing', ?)",
                (match_id, idx, wind, number, honba, dealer_seat, dealer_seat,
                 int(riichi_sticks or 0)),      # 上一局留下的立直供托跟着过来
            )
            round_id = cur.lastrowid

            # 牌山：136 张按 seq 0..135 存进去（编号 no ↔ seq = no - 1）
            for seq, entity in enumerate(wall):
                self.conn.execute(
                    "INSERT INTO round_wall(round_id, seq, tile, entity, zone) VALUES(?,?,?,?, 'live')",
                    (round_id, seq, entity_tile(entity), entity),
                )
            _dead = 14                                    # 王牌 7 墩 = 14 张（岭上 4 + 宝牌/里宝 8 + 保障 2）
            self.conn.execute("UPDATE rounds SET live_left = ? WHERE round_id = ?",
                              (len(wall) - _dead, round_id))

            self._log(round_id, -1, "round_start",
                      {"wind": wind, "number": number, "honba": honba,
                       "dealer_seat": dealer_seat, "live_left": len(wall)})
        return round_id

    # ═══════════════════════════════════════════════════════════════════════
    #  4. 行牌：摸 / 打 / 鸣 / 立直 / 和
    # ═══════════════════════════════════════════════════════════════════════
    def draw(self, round_id: int, seat: int, from_dead: bool = False,
             client_action_id: str | None = None) -> dict | None:
        """摸牌。from_dead=True 是杠之后补岭上牌。返回摸到的那张牌。"""
        with self.tx():
            if self._is_duplicate(round_id, seat, client_action_id):
                return None
            if from_dead:
                card = self._row(
                    "SELECT seq, tile FROM round_wall WHERE round_id=? AND zone='dead' "
                    "AND draw_no IS NULL AND dealt_to IS NULL ORDER BY seq LIMIT 1", (round_id,))
            else:
                card = self._row(
                    "SELECT seq, tile FROM round_wall WHERE round_id=? AND zone='live' "
                    "AND dealt_to IS NULL AND draw_no IS NOT NULL ORDER BY draw_no LIMIT 1",
                    (round_id,))
            if not card:
                return None                                   # 牌山摸完了 → 该流局
            self.conn.execute(
                "UPDATE round_hands SET is_drawn = 0 WHERE round_id=? AND seat=?", (round_id, seat))
            self.conn.execute(
                "INSERT INTO round_hands(round_id, seat, wall_seq, tile, slot, is_drawn) "
                "VALUES(?,?,?,?,?,1)",
                (round_id, seat, card["seq"], card["tile"], 999),
            )
            self.conn.execute(
                "UPDATE round_wall SET dealt_to=? WHERE round_id=? AND seq=?",
                (seat, round_id, card["seq"]))
            if not from_dead:
                self.conn.execute(
                    "UPDATE rounds SET live_left = MAX(live_left - 1, 0) WHERE round_id=?",
                    (round_id,))
            self._log(round_id, seat, "draw",
                      {"tile": card["tile"], "wall_seq": card["seq"], "from_dead": from_dead},
                      client_action_id)
        return {"tile": card["tile"], "wall_seq": card["seq"]}

    def discard(self, round_id: int, seat: int, wall_seq: int | None = None,
                riichi_tile: bool = False, face_down: bool = False,
                client_action_id: str | None = None) -> dict | None:
        """
        打出一张牌。
        wall_seq = None → 打刚摸进来的那张（摸切），和自己的手牌对不上就报错。
        打完这张就进牌河，手牌恢复成「待摸牌状态」。
        """
        with self.tx():
            if self._is_duplicate(round_id, seat, client_action_id):
                return None
            if wall_seq is None:
                row = self._row(
                    "SELECT wall_seq, tile FROM round_hands WHERE round_id=? AND seat=? "
                    "AND is_drawn=1", (round_id, seat))
                tsumogiri = 1
                if row is None:                               # 没有刚摸的牌：随便打一张手牌
                    row = self._row(
                        "SELECT wall_seq, tile FROM round_hands WHERE round_id=? AND seat=? "
                        "ORDER BY wall_seq LIMIT 1", (round_id, seat))
                    tsumogiri = 0
            else:
                row = self._row(
                    "SELECT wall_seq, tile, is_drawn FROM round_hands "
                    "WHERE round_id=? AND seat=? AND wall_seq=?", (round_id, seat, wall_seq))
                tsumogiri = 1 if row and row["is_drawn"] else 0
            if not row:
                raise ValueError("这张牌不在他手里")

            self.conn.execute("DELETE FROM round_hands WHERE round_id=? AND wall_seq=?",
                              (round_id, row["wall_seq"]))
            self.conn.execute("UPDATE round_hands SET is_drawn=0 WHERE round_id=? AND seat=?",
                              (round_id, seat))

            nxt = (self._one("SELECT COALESCE(MAX(seq),0)+1 FROM round_discards WHERE round_id=?",
                             (round_id,)) or 1)
            self.conn.execute(
                "INSERT INTO round_discards(round_id, seq, seat, wall_seq, tile, is_tsumogiri, "
                "is_riichi_tile, face_down) VALUES(?,?,?,?,?,?,?,?)",
                (round_id, nxt, seat, row["wall_seq"], row["tile"], tsumogiri,
                 1 if riichi_tile else 0, 1 if face_down else 0),
            )
            if riichi_tile:
                # 立直宣言牌打出去 → 牌河横置 + 供托 +1000
                self.conn.execute(
                    "INSERT INTO round_riichi(round_id, seat, declared_seq, ippatsu) "
                    "VALUES(?,?,?,1) ON CONFLICT(round_id, seat) DO NOTHING",
                    (round_id, seat, nxt))
                self.conn.execute(
                    "UPDATE rounds SET riichi_sticks = riichi_sticks + 1 WHERE round_id=?",
                    (round_id,))
                self._score(round_id, seat, -1000, "riichi")

            self.conn.execute("UPDATE rounds SET turn_seat=? WHERE round_id=?",
                              ((seat + 1) % 4, round_id))
            self._log(round_id, seat, "discard",
                      {"tile": row["tile"], "tsumogiri": bool(tsumogiri),
                       "riichi_tile": bool(riichi_tile), "discard_seq": nxt},
                      client_action_id)
        return {"tile": row["tile"], "discard_seq": nxt, "tsumogiri": bool(tsumogiri)}

    def meld(self, round_id: int, seat: int, kind: str, tiles: list[str],
             called_tile: str, from_seat: int, from_discard_seq: int | None = None,
             rot_index: int = 0, client_action_id: str | None = None) -> int:
        """
        吃 / 碰 / 杠。
        tiles       = 这副副露的显示顺序（和客户端摆放一致，含被鸣的那张）
        rot_index   = 横置那张在 tiles 里的下标（谁打出的决定：上家0/对家1/下家2）
        kind        = chi / pon / minkan / ankan / kakan
        """
        with self.tx():
            if self._is_duplicate(round_id, seat, client_action_id):
                return -1
            # open_set（友引段1）可以是 3 张（刻子/顺子）或 4 张（杠）
            need = len(tiles) if kind == "open_set" else (3 if kind in ("chi", "pon") else 4)
            # 这一鸣，自己手里要出几张：
            #   吃/碰 = 2 张（另 1 张是鸣来的）；明杠 = 3 张；暗杠 = 4 张全在自己手里；
            #   加杠 = 1 张（把之前碰的那副升成杠）
            if kind in ("chi", "pon"):
                from_hand = 2
            elif kind == "minkan":
                from_hand = 3
            elif kind == "ankan":
                from_hand = 4
            elif kind == "open_set":
                from_hand = len(tiles)         # 友引：全部从手牌出（没有「被鸣的那张」）
            else:                                             # kakan
                from_hand = 1
            hand = self._rows(
                "SELECT wall_seq, tile FROM round_hands WHERE round_id=? AND seat=? "
                "ORDER BY wall_seq", (round_id, seat))
            pool = list(hand)
            # 要出的牌 = 这副副露里的牌，按「种类张数」扣（被鸣的那张不算手里的）。
            # 不能按牌面值 remove：碰 5m 时手里两张也是 5m，会扣错。
            want_counts: dict[str, int] = {}
            for t in tiles:
                want_counts[kind_of(t)] = want_counts.get(kind_of(t), 0) + 1
            if kind in ("chi", "pon", "minkan"):
                k = kind_of(called_tile)
                want_counts[k] = want_counts.get(k, 0) - 1
            use: list[dict] = []
            for k, n in want_counts.items():
                if n <= 0:
                    continue
                got = [h for h in pool if kind_of(h["tile"]) == k][:n]
                if len(got) < n:
                    raise ValueError(f"手里没有 {n} 张 {k}，这副副露凑不出来")
                for g_ in got:
                    pool.remove(g_)
                use += got
            if len(use) != from_hand:
                raise ValueError(f"{kind} 需要从手里出 {from_hand} 张，实际凑到 {len(use)} 张")
            for h in use:
                self.conn.execute("DELETE FROM round_hands WHERE round_id=? AND wall_seq=?",
                                  (round_id, h["wall_seq"]))
            self.conn.execute("UPDATE round_hands SET is_drawn=0 WHERE round_id=? AND seat=?",
                              (round_id, seat))

            if from_discard_seq is not None:                  # 被鸣的那张从牌河拿走
                self.conn.execute(
                    "UPDATE round_discards SET called=1, called_by=?, called_kind=? "
                    "WHERE round_id=? AND seq=?",
                    (seat, kind, round_id, from_discard_seq))

            # 这副副露里每一张牌「对应哪一张物理牌」：顺序和 tiles 一一对应。
            # （被鸣的那张查牌河记录的 wall_seq；其余按牌面从手里出的那几张里对上。
            #   存成 seqs_json 以后就能回答「这副杠到底是哪四张牌」。）
            called_seq = None
            if from_discard_seq is not None:
                crow = self._row("SELECT wall_seq FROM round_discards "
                                 "WHERE round_id=? AND seq=?", (round_id, from_discard_seq))
                called_seq = crow["wall_seq"] if crow else None
            seq_of: list = []
            spare = list(use)
            for k, t in enumerate(tiles):
                if k == rot_index and from_discard_seq is not None:
                    # 被鸣的那张：它不在自己手里，编号只能从牌河那条记录取。
                    # （查不到就记 None —— 千万别退回去从手里挑一张顶上，那会错配。）
                    seq_of.append(called_seq)
                    continue
                pick = next((h for h in spare if h["tile"] == t), None)
                if pick is None:
                    pick = next((h for h in spare if kind_of(h["tile"]) == kind_of(t)), None)
                if pick is not None:
                    spare.remove(pick)
                    seq_of.append(pick["wall_seq"])
                else:
                    seq_of.append(None)

            # 加杠：把之前碰的那副升级成杠，不新增一副
            if kind == "kakan":
                row = self._row("SELECT meld_id, tiles_json, seqs_json FROM round_melds "
                                "WHERE round_id=? AND seat=? AND kind='pon' AND called_tile=?",
                                (round_id, seat, called_tile))
                if row is None:
                    raise ValueError("没有可以加杠的碰")
                tiles4 = json.loads(row["tiles_json"]) + [use[0]["tile"]]
                # 加杠的第 4 张也记上它的物理编号（原来那 3 张保持不变）
                seqs4 = json.loads(row["seqs_json"] or "[]") + [seq_of[0]]
                self.conn.execute(
                    "UPDATE round_melds SET kind='kakan', tiles_json=?, seqs_json=? "
                    "WHERE round_id=? AND seat=? AND meld_id=?",
                    (json.dumps(tiles4, ensure_ascii=False),
                     json.dumps(seqs4, ensure_ascii=False), round_id, seat, row["meld_id"]))
                self.conn.execute("UPDATE rounds SET kan_count = kan_count + 1 WHERE round_id=?",
                                  (round_id,))
                self.conn.execute("UPDATE rounds SET turn_seat = ? WHERE round_id = ?",
                                  (seat, round_id))
                self._log(round_id, seat, kind,
                          {"tiles": tiles4, "meld_id": row["meld_id"]}, client_action_id)
                return row["meld_id"]

            mid = (self._one("SELECT COALESCE(MAX(meld_id),-1)+1 FROM round_melds "
                             "WHERE round_id=? AND seat=?", (round_id, seat)) or 0)
            self.conn.execute(
                "INSERT INTO round_melds(round_id, meld_id, seat, kind, called_tile, from_seat, "
                "tiles_json, rot_index, from_discard_seq, seqs_json) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (round_id, mid, seat, kind, called_tile, from_seat,
                 json.dumps(tiles, ensure_ascii=False), rot_index, from_discard_seq,
                 json.dumps(seq_of, ensure_ascii=False)))
            if kind in ("minkan", "ankan", "kakan"):
                self.conn.execute("UPDATE rounds SET kan_count = kan_count + 1 WHERE round_id=?",
                                  (round_id,))
            # 鸣完之后轮到自己打牌
            self.conn.execute("UPDATE rounds SET turn_seat = ? WHERE round_id = ?",
                              (seat, round_id))
            self._log(round_id, seat, kind,
                      {"tiles": tiles, "seqs": seq_of, "called": called_tile,
                       "from_seat": from_seat, "rot_index": rot_index, "meld_id": mid},
                      client_action_id)
        return mid

    def finish_round(self, round_id: int, result: str, winner_seat: int | None = None,
                     loser_seat: int | None = None, han: int | None = None,
                     fu: int | None = None, points: int | None = None,
                     yaku: list | None = None, dora: dict | None = None,
                     deltas: dict | None = None) -> None:
        """
        结算一局。result = tsumo / ron / ryuukyoku(荒牌流局) / kyuushu(九种九牌) /
        sufon_renda(四风连打) / sucha_riichi(四家立直) / sukan_santan(四杠散了) /
        sanchahou(三家和了) / chombo
        deltas = {seat: 分数增减}，不传就按 points 粗算（真正的得点计算以后单独写）。
        """
        with self.tx():
            self.conn.execute(
                "UPDATE rounds SET status='ended', ended_at=datetime('now'), result=?, "
                "winner_seat=?, loser_seat=?, han=?, fu=?, points=?, yaku_json=?, dora_json=? "
                "WHERE round_id=?",
                (result, winner_seat, loser_seat, han, fu, points,
                 json.dumps(yaku or [], ensure_ascii=False),
                 json.dumps(dora or {}, ensure_ascii=False), round_id))
            if deltas is None and points and winner_seat is not None:
                deltas = {winner_seat: points}
                if result == "ron" and loser_seat is not None:
                    deltas[loser_seat] = -points
                elif result == "tsumo":
                    others = [s for s in range(4) if s != winner_seat]
                    each = points // len(others)
                    for s in others:
                        deltas[s] = -each
            for seat, d in (deltas or {}).items():
                self._score(round_id, seat, d, result or "score")
            self._log(round_id, -1, "round_end",
                      {"result": result, "winner": winner_seat, "loser": loser_seat,
                       "han": han, "fu": fu, "points": points})
            # 谁赢了给账号记一笔
            if winner_seat is not None:
                self.conn.execute(
                    "UPDATE users SET games = games + 1, wins = wins + 1 WHERE user_id = "
                    "(SELECT user_id FROM match_seats WHERE match_id = "
                    " (SELECT match_id FROM rounds WHERE round_id=?) AND seat = ?)",
                    (round_id, winner_seat))

    def reveal_next_dora(self, round_id: int, kind: str = "dora") -> dict | None:
        """杠了以后翻开下一张宝牌指示牌（里宝牌同理，和了的时候才翻）。"""
        row = self._row("SELECT idx, indicator, dora FROM round_dora WHERE round_id=? AND kind=? "
                        "AND revealed=0 ORDER BY idx LIMIT 1", (round_id, kind))
        if not row:
            return None
        with self.tx():
            self.conn.execute(
                "UPDATE round_dora SET revealed=1 WHERE round_id=? AND kind=? AND idx=?",
                (round_id, kind, row["idx"]))
        return row

    def _score(self, round_id: int, seat: int, delta: int, reason: str) -> None:
        mid = self._one("SELECT match_id FROM rounds WHERE round_id=?", (round_id,))
        self.conn.execute("UPDATE match_seats SET score = score + ? WHERE match_id=? AND seat=?",
                          (delta, mid, seat))
        after = self._one("SELECT score FROM match_seats WHERE match_id=? AND seat=?", (mid, seat))
        self.conn.execute(
            "INSERT INTO score_events(round_id, seat, delta, after, reason) VALUES(?,?,?,?,?)",
            (round_id, seat, delta, after, reason))

    def finish_match(self, match_id: int) -> dict:
        """一场打完：记终局分数、更新每个人的天梯分（这里先按名次给个简单增减）。"""
        with self.tx():
            seats = self._rows("SELECT seat, user_id, score FROM match_seats "
                               "WHERE match_id=? ORDER BY score DESC", (match_id,))
            final = {str(s["seat"]): s["score"] for s in seats}
            bonus = {0: 15, 1: 5, 2: -5, 3: -15}
            for rank, s in enumerate(seats):
                if s["user_id"]:
                    self.conn.execute("UPDATE users SET rating = rating + ?, games = games + 1 "
                                      "WHERE user_id = ?", (bonus[rank], s["user_id"]))
            self.conn.execute(
                "UPDATE matches SET status='finished', ended_at=datetime('now'), final_json=? "
                "WHERE match_id=?", (json.dumps(final, ensure_ascii=False), match_id))
            self.conn.execute(
                "UPDATE rooms SET status='finished' WHERE room_id = "
                "(SELECT room_id FROM matches WHERE match_id=?)", (match_id,))
        return final

    # ═══════════════════════════════════════════════════════════════════════
    #  5. 查询：公开信息 / 自己的手牌
    # ═══════════════════════════════════════════════════════════════════════
    def public_state(self, round_id: int) -> dict:
        """【可以发给所有人的】信息。注意：这里没有任何人的手牌和牌山。"""
        r = self._row("SELECT * FROM v_public_round WHERE round_id=?", (round_id,))
        if not r:
            return {}
        scores = self._rows(
            "SELECT seat, nickname, score, connected FROM match_seats WHERE match_id=? "
            "ORDER BY seat", (r["match_id"],))
        return {
            "round": r,
            "scores": scores,
            "discards": self._rows(
                "SELECT seq, seat, tile, is_tsumogiri, is_riichi_tile, called, face_down "
                "FROM round_discards WHERE round_id=? ORDER BY seq", (round_id,)),
            "melds": self._rows(
                "SELECT seat, meld_id, kind, called_tile, from_seat, tiles_json, rot_index "
                "FROM round_melds WHERE round_id=? ORDER BY seat, meld_id", (round_id,)),
            "dora": self._rows(
                "SELECT kind, idx, indicator, dora FROM round_dora "
                "WHERE round_id=? AND revealed=1 ORDER BY kind, idx", (round_id,)),
            "hand_counts": self._rows(
                "SELECT seat, tiles FROM v_hand_counts WHERE round_id=? ORDER BY seat",
                (round_id,)),
        }

    def my_hand(self, round_id: int, seat: int) -> list[dict]:
        """【只发给本人的】自己的手牌。绝不要把 seat 换成别人的。"""
        rows = self._rows(
            "SELECT wall_seq, tile, is_drawn FROM round_hands WHERE round_id=? AND seat=? "
            "ORDER BY is_drawn, wall_seq", (round_id, seat))
        return rows

    def private_state(self, round_id: int, seat: int) -> dict:
        """给某个玩家看的东西 = 公开信息 + 他自己的手牌。"""
        st = self.public_state(round_id)
        st["seat"] = seat
        st["hand"] = self.my_hand(round_id, seat)
        return st

    def server_state(self, round_id: int) -> dict:
        """【只有服务器自己看】的完整状态，含牌山和四家手牌。别发给客户端。"""
        return {
            "wall_left": self._one(
                "SELECT COUNT(*) FROM round_wall WHERE round_id=? AND zone='live' "
                "AND dealt_to IS NULL AND draw_no IS NOT NULL", (round_id,)),
            "hands": self._rows(
                "SELECT seat, wall_seq, tile, is_drawn FROM round_hands "
                "WHERE round_id=? ORDER BY seat, wall_seq", (round_id,)),
            "live_wall": self._rows(
                "SELECT seq, tile FROM round_wall WHERE round_id=? AND dealt_to IS NULL "
                "ORDER BY seq", (round_id,)),
        }

    def replay(self, round_id: int) -> list[dict]:
        """把这一局的动作从头看一遍（复盘 / 断线重连补发）。"""
        return self._rows(
            "SELECT seq, seat, action, payload, created_at FROM round_actions "
            "WHERE round_id=? ORDER BY seq", (round_id,))

    # ═══════════════════════════════════════════════════════════════════════
    #  6. 动作日志（幂等）
    # ═══════════════════════════════════════════════════════════════════════
    def _is_duplicate(self, round_id: int, seat: int | None, client_action_id: str | None) -> bool:
        """客户端动作号重复 = 断线重发，直接跳过，别执行两次。"""
        if not client_action_id:
            return False
        return self._one(
            "SELECT COUNT(*) FROM round_actions WHERE round_id=? AND seat IS ? "
            "AND client_action_id=?", (round_id, seat, client_action_id)) > 0

    def _log(self, round_id: int, seat: int, action: str, payload: dict | None = None,
             client_action_id: str | None = None) -> int:
        nxt = (self._one("SELECT COALESCE(MAX(seq),0)+1 FROM round_actions WHERE round_id=?",
                         (round_id,)) or 1)
        self.conn.execute(
            "INSERT INTO round_actions(round_id, seq, seat, action, payload, client_action_id) "
            "VALUES(?,?,?,?,?,?)",
            (round_id, nxt, seat, action,
             json.dumps(payload or {}, ensure_ascii=False), client_action_id))
        return nxt


def _count_called(tiles: list[str], called_tile: str) -> int:
    return 1 if called_tile in tiles else 0


# ═══════════════════════════════════════════════════════════════════════════
#  命令行小工具
# ═══════════════════════════════════════════════════════════════════════════
def _main() -> None:
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "info"
    path = sys.argv[2] if len(sys.argv) > 2 else None
    db = DB(path)
    db.init_schema()
    if cmd == "init":
        print(f"建库完成：{db.path}")
    else:
        tables = db._rows("SELECT name FROM sqlite_master WHERE type='table' "
                          "AND name NOT LIKE 'sqlite_%' ORDER BY name")
        views = db._rows("SELECT name FROM sqlite_master WHERE type='view' ORDER BY name")
        print(f"数据库：{db.path}")
        print(f"表（{len(tables)}）：" + ", ".join(t["name"] for t in tables))
        print(f"视图（{len(views)}）：" + ", ".join(v["name"] for v in views))
        for t in tables:
            n = db._one(f"SELECT COUNT(*) FROM {t['name']}")
            print(f"  {t['name']:<18} {n} 行")
    db.close()


if __name__ == "__main__":
    _main()
