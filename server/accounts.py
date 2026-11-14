# -*- coding: utf-8 -*-
"""全局账号库（`server/data/accounts.db`）。

用户口径 2026-11-14：
· **名字即账号，没有密码**；**区分大小写**（`Tom` ≠ `tom`）
· **每小局**给每个真人账号记一条（点数 = 这一局结束后的点数，delta = 本局变化量）
· **有人机的对局整局不计**（`meta.seat_bot_N`）
· 与房间库完全分离：房间被「闲置回收」也不影响战绩

这里不 import db.py（避免环形依赖）：需要读房间库时由调用方把 `db` 传进来，
只用它的 `_row / _rows / _one / path`。
"""

from __future__ import annotations

import os
import re
import sqlite3

_HERE = os.path.dirname(os.path.abspath(__file__))

#: 测试可以用环境变量指到临时文件，别污染线上库
ENV_PATH = "TIANMA_ACCOUNTS_DB"

# 名字规则：汉字 / 字母 / 数字，1~24 字（客户端也这么过滤，服务端必须再校验一遍）
_NAME_RE = re.compile(r"^[0-9A-Za-z\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]{1,24}$")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
  account_id    INTEGER PRIMARY KEY AUTOINCREMENT,
  name          TEXT NOT NULL UNIQUE,        -- 默认 BINARY：区分大小写
  created_at    TEXT NOT NULL,
  last_login_at TEXT,
  pass_hash     TEXT
);
CREATE TABLE IF NOT EXISTS round_results (
  result_id    INTEGER PRIMARY KEY AUTOINCREMENT,
  account_id   INTEGER NOT NULL,
  round_uid    TEXT NOT NULL,
  match_uid    TEXT NOT NULL,
  room         TEXT NOT NULL,
  seq_in_match INTEGER,
  wind         TEXT,
  number       INTEGER,
  honba        INTEGER,
  score        INTEGER NOT NULL,
  delta        INTEGER,
  result       TEXT,
  created_at   TEXT NOT NULL,
  UNIQUE(account_id, round_uid)
);
CREATE INDEX IF NOT EXISTS idx_rr_account ON round_results(account_id, result_id);
"""


def db_path() -> str:
    p = os.environ.get(ENV_PATH, "").strip()
    if p:
        d = os.path.dirname(os.path.abspath(p))
        if d:
            os.makedirs(d, exist_ok=True)
        return p
    d = os.path.join(_HERE, "data")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "accounts.db")


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(db_path(), timeout=10.0)
    c.row_factory = sqlite3.Row
    try:
        c.execute("PRAGMA journal_mode=WAL")
    except Exception:                                   # noqa: BLE001
        pass
    c.executescript(_SCHEMA)
    return c


def norm(name) -> str | None:
    """校验并规范化账号名；不合法 → None。"""
    s = str(name or "").strip()
    if not _NAME_RE.match(s):
        return None
    return s


# ── 登录 / 注册 ────────────────────────────────────────────────────────────
def login(name) -> dict:
    """库里有这个名字 → 视为登入（顺手刷 last_login_at）。"""
    s = norm(name)
    if s is None:
        return {"exists": False, "name": "", "error": "账号名不合法（汉字/字母/数字，1~24 字）"}
    with _conn() as c:
        row = c.execute("SELECT account_id FROM accounts WHERE name=?", (s,)).fetchone()
        if row is None:
            return {"exists": False, "name": s, "account_id": None}
        c.execute("UPDATE accounts SET last_login_at=datetime('now') WHERE account_id=?",
                  (int(row["account_id"]),))
        return {"exists": True, "name": s, "account_id": int(row["account_id"])}


def create(name) -> dict:
    """建账号（幂等：已存在就返回 created=False）。"""
    s = norm(name)
    if s is None:
        return {"created": False, "exists": False, "name": "",
                "error": "账号名不合法（汉字/字母/数字，1~24 字）"}
    with _conn() as c:
        row = c.execute("SELECT account_id FROM accounts WHERE name=?", (s,)).fetchone()
        if row is not None:
            c.execute("UPDATE accounts SET last_login_at=datetime('now') WHERE account_id=?",
                      (int(row["account_id"]),))
            return {"created": False, "exists": True, "name": s,
                    "account_id": int(row["account_id"])}
        cur = c.execute("INSERT INTO accounts(name, created_at, last_login_at) "
                        "VALUES(?, datetime('now'), datetime('now'))", (s,))
        return {"created": True, "exists": True, "name": s,
                "account_id": int(cur.lastrowid)}


def account_id_of(name) -> int | None:
    s = norm(name)
    if s is None:
        return None
    with _conn() as c:
        row = c.execute("SELECT account_id FROM accounts WHERE name=?", (s,)).fetchone()
        return int(row["account_id"]) if row else None


def _ensure_id(name) -> int | None:
    aid = account_id_of(name)
    if aid is not None:
        return aid
    r = create(name)
    return r.get("account_id")


# ── 战绩 ──────────────────────────────────────────────────────────────────
def record_round(account_id: int, round_uid: str, match_uid: str, room: str,
                 score: int, delta: int = 0, result: str = "",
                 seq_in_match: int = 0, wind: str = "", number: int = 0,
                 honba: int = 0) -> int:
    """写一条小局记录；同一账号同一局重复调用不会写第二条。返回 1=写了 / 0=已有。"""
    if not account_id or not round_uid:
        return 0
    with _conn() as c:
        cur = c.execute(
            "INSERT OR IGNORE INTO round_results(account_id, round_uid, match_uid, room,"
            " seq_in_match, wind, number, honba, score, delta, result, created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?, datetime('now'))",
            (int(account_id), str(round_uid), str(match_uid), str(room),
             int(seq_in_match or 0), str(wind or ""), int(number or 0), int(honba or 0),
             int(score or 0), int(delta or 0), str(result or "")))
        return int(cur.rowcount or 0)


def _room_of(path: str) -> str:
    base = os.path.basename(str(path or ""))
    if base.lower().endswith(".db"):
        base = base[:-3]
    return base or "default"


def note_round(db, round_id: int, result: str, deltas: dict | None = None) -> int:
    """由 `DB.finish_round()` 在小局结算结束后调用（房间库事务已提交）。

    返回写入条数；有人机 / 没人登录 → 0。
    """
    # ① 有人机的对局整局不计
    if db._row("SELECT key FROM meta WHERE key LIKE 'seat_bot_%' AND value='1'"):
        return 0
    # ② 哪些座位是登录账号
    acc: dict[int, str] = {}
    for r in db._rows("SELECT key, value FROM meta WHERE key LIKE 'seat_account_%'"):
        try:
            seat = int(str(r["key"]).rsplit("_", 1)[-1])
        except (ValueError, IndexError):
            continue
        nm = norm(str(r["value"]))
        if nm is not None and 0 <= seat <= 3:
            acc[int(seat)] = nm
    if not acc:
        return 0
    # ③ 这一局的信息 + 各家当前点数
    info = db._row("SELECT match_id, round_index, wind, number, honba FROM rounds "
                   "WHERE round_id=?", (int(round_id),))
    if info is None:
        return 0
    mid = int(info["match_id"])
    scores = {int(r["seat"]): int(r["score"])
              for r in db._rows("SELECT seat, score FROM match_seats WHERE match_id=?",
                                (mid,))}
    room = _room_of(getattr(db, "path", "") or "")
    round_uid = "%s:%d" % (room, int(round_id))
    match_uid = "%s:%d" % (room, mid)
    n = 0
    for seat, nm in sorted(acc.items()):
        aid = _ensure_id(nm)
        if aid is None:
            continue
        n += record_round(
            account_id=aid, round_uid=round_uid, match_uid=match_uid, room=room,
            score=int(scores.get(seat, 0)), delta=int((deltas or {}).get(seat, 0) or 0),
            result=str(result or ""), seq_in_match=int(info["round_index"] or 0),
            wind=str(info["wind"] or ""), number=int(info["number"] or 0),
            honba=int(info["honba"] or 0))
    return n


# ── 查询（先只留接口，界面以后再做）──────────────────────────────────────
def history(name, limit: int = 200) -> list[dict]:
    aid = account_id_of(name)
    if aid is None:
        return []
    with _conn() as c:
        rows = c.execute(
            "SELECT result_id, room, match_uid, seq_in_match, wind, number, honba,"
            " score, delta, result, created_at FROM round_results"
            " WHERE account_id=? ORDER BY result_id DESC LIMIT ?",
            (aid, int(limit))).fetchall()
    return [dict(r) for r in rows]


def stats(name) -> dict:
    aid = account_id_of(name)
    if aid is None:
        return {}
    with _conn() as c:
        row = c.execute(
            "SELECT COUNT(*) AS rounds,"
            " IFNULL(SUM(delta),0) AS total_delta,"
            " IFNULL(MAX(score),0) AS best_score,"
            " IFNULL(SUM(CASE WHEN result IN ('tsumo','ron') THEN 1 ELSE 0 END),0) AS wins"
            " FROM round_results WHERE account_id=?", (aid,)).fetchone()
    return dict(row) if row else {}
