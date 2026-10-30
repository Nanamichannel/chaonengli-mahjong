#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""线上联机用的 HTTP 服务端（把 api_cli.handle() 包成 HTTP）

    python net_server.py --host 0.0.0.0 --port 8000

客户端（Godot）做的事还是那一件：POST 一份和 srv_req.json 完全一样的 JSON 过来，
服务端用它跑一遍规则、把响应 JSON 原样回去。所以**规则一行都不用改**，
api_cli / game / db / rules 全部照旧。

接口
    POST /rpc/<房间号>      body = 请求 JSON，返回 api_cli.handle() 的那份响应
    GET  /health            健康检查 → {"ok": true, "rooms": [...]}
    GET  /                  给人看的说明页

鉴权（可选）
    net_config.json 里给房间配 token，客户端要带 ?token=xxx 或 X-Token 头。
    token 留空 = 不校验 —— 只建议在局域网/自己的内网穿透上用。

多房间
    每个房间一个独立 SQLite 文件（默认 data/room_<房间号>.db），互不干扰。
    net_config.json 不写的话：只有一个房间 "default"，用老的 data/mahjong.db
    （所以现在这台机器上的进度直接就能接着打）。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import api_cli                                                   # noqa: E402

# api_cli 在 import 时把 stdout 改成了 utf-8（Godot 从文件/stdout 读 JSON 需要）。
# 但 net_server 的日志是打给人看的控制台 —— 这里改回控制台自己的编码，
# 否则中文在 Windows 的 cp936 窗口里会变成「澶╅┈楹诲皢」这种乱码。
if os.name == "nt":
    try:
        import ctypes
        _cp = ctypes.windll.kernel32.GetConsoleOutputCP() or 936
        sys.stdout.reconfigure(encoding="cp%d" % _cp, errors="replace")
        sys.stderr.reconfigure(encoding="cp%d" % _cp, errors="replace")
    except Exception:                                        # noqa: BLE001
        pass

LOG_DIR = os.path.join(HERE, "logs")
LOG_PATH = os.path.join(LOG_DIR, "net_server.log")

# 房间号 → {"token": str, "db": 绝对路径}
ROOMS: dict[str, dict] = {}
DEFAULT_ROOM = "default"
_room_locks: dict[str, threading.Lock] = {}
_lock_guard = threading.Lock()


# ────────────────────────── 配置 ──────────────────────────

def load_config(path: str) -> None:
    """读 net_config.json；没有就用「单房间 default + 老的 mahjong.db」。"""
    global ROOMS, DEFAULT_ROOM
    rooms: dict[str, dict] = {}
    default = "default"
    if path and os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                cfg = json.load(f) or {}
        except Exception as e:                                   # noqa: BLE001
            print(f"[warn] 读不了 {path}：{e}（改用默认单房间）")
            cfg = {}
        default = str(cfg.get("default_room") or "default")
        for name, spec in (cfg.get("rooms") or {}).items():
            spec = spec if isinstance(spec, dict) else {}
            db = str(spec.get("db") or os.path.join("data", "room_%s.db" % name))
            if not os.path.isabs(db):
                db = os.path.join(HERE, db)
            rooms[str(name)] = {"token": str(spec.get("token") or ""), "db": db}
    if not rooms:
        rooms = {"default": {"token": "",
                             "db": os.path.join(HERE, "data", "mahjong.db")}}
    ROOMS = rooms
    DEFAULT_ROOM = default if default in rooms else sorted(rooms)[0]
    for name in rooms:
        _room_locks.setdefault(name, threading.Lock())


def room_of(name: str) -> str:
    """'abc' → 已配置的房间；没配置过 → 自动建一个（多房间开箱即用）。"""
    if not name:
        return DEFAULT_ROOM
    # ★ 先 URL 解码（客户端会把房间号 uri_encode，中文房间号才认得出来）
    # ★ 再净化：房间名要直接当文件名用，只留字母/数字/下划线/连字符/中文，
    #   否则 /rpc/../../x 这种就能把 db 写到 data 目录外面去。
    name = re.sub(r"[^0-9a-z_\-\u4e00-\u9fff]", "", unquote(str(name)).strip().lower())[:32]
    if not name:
        return DEFAULT_ROOM
    with _lock_guard:
        if name not in ROOMS:
            db = os.path.join(HERE, "data", "room_%s.db" % name)
            ROOMS[name] = {"token": "", "db": db}
            _room_locks.setdefault(name, threading.Lock())
            log(f"[room] 自动创建房间 {name} → {db}")
        return name


def log(text: str) -> None:
    line = "[%s] %s" % (time.strftime("%m-%d %H:%M:%S"), text)
    print(line, flush=True)
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > 8 * 1024 * 1024:
            os.replace(LOG_PATH, LOG_PATH + ".1")
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:                                            # noqa: BLE001
        pass


def lan_ip() -> str:
    """尽量猜出本机在局域网里的地址（给朋友填）。"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.2)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:                                            # noqa: BLE001
        return "127.0.0.1"


# ────────────────────────── HTTP ──────────────────────────

class Handler(BaseHTTPRequestHandler):
    server_version = "TianmaNet/1.0"
    protocol_version = "HTTP/1.1"

    # 让 Godot 那边不用等 DNS/连接超时
    timeout = 30

    def setup(self) -> None:
        super().setup()
        # ★ 关掉 Nagle。响应是「header 一段 + body 一段」两个小包，开着 Nagle 时
        #   第二段会等对方的 delayed ACK，实测本机直连都要多 75 ms（连续请求只要 4 ms），
        #   表现出来就是「点了牌要等一下」。
        try:
            self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass

    def log_message(self, fmt, *args):                           # noqa: D401
        pass                                                     # 自己记日志

    # ── 小工具 ──
    def _send(self, code: int, body: dict) -> None:
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        try:
            self.wfile.write(raw)
        except Exception:                                        # noqa: BLE001
            pass

    def _text(self, code: int, text: str) -> None:
        raw = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        try:
            self.wfile.write(raw)
        except Exception:                                        # noqa: BLE001
            pass

    def _token_ok(self, room: str, query: dict) -> bool:
        need = str((ROOMS.get(room) or {}).get("token") or "")
        if not need:
            return True
        got = (query.get("token") or [""])[0] or self.headers.get("X-Token", "")
        return str(got) == need

    # ── GET ──
    def do_GET(self) -> None:
        u = urlparse(self.path)
        if u.path in ("/", "/index.html"):
            self._text(200, "天马麻将 联机服务端在跑。\n"
                            "接口：POST /rpc/<房间号>（body = 请求 JSON）\n"
                            "健康检查：GET /health\n")
            return
        if u.path == "/health":
            self._send(200, {"ok": True, "rooms": sorted(ROOMS.keys()),
                             "default": DEFAULT_ROOM, "ts": time.time()})
            return
        self._send(404, {"ok": False, "error": "not found"})

    # ── POST /rpc/<room> ──
    def do_POST(self) -> None:
        u = urlparse(self.path)
        query = parse_qs(u.query)
        if not u.path.startswith("/rpc"):
            self._send(404, {"ok": False, "error": "not found"})
            return
        room = room_of((u.path[len("/rpc"):].strip("/")) or query.get("room", [""])[0])
        if not self._token_ok(room, query):
            self._send(403, {"ok": False, "error": "token 不对"})
            return
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > 8 * 1024 * 1024:
            self._send(400, {"ok": False, "error": "body 长度不对"})
            return
        try:
            req = json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception as e:                                   # noqa: BLE001
            self._send(400, {"ok": False, "error": "body 不是 JSON：%s" % e})
            return
        if not isinstance(req, dict):
            self._send(400, {"ok": False, "error": "body 必须是一个 JSON 对象"})
            return

        op = str(req.get("op", "?"))
        seat = req.get("seat", "-")
        t0 = time.time()
        try:
            db_path = ROOMS[room]["db"]
            # 同一房间的请求排队跑：SQLite 是单写者，排队比让它们互相等锁更快、更稳
            lock = _room_locks.setdefault(room, threading.Lock())
            with lock:
                out = api_cli.handle(req, db_path=db_path)
            out.setdefault("room", room)
        except Exception as e:                                   # noqa: BLE001
            log("[ERR ] %s/%s seat=%s %s\n%s" % (room, op, seat, e,
                                                 traceback.format_exc()))
            out = {"ok": False, "error": "服务端内部错误：%s" % e,
                   "state": None, "events": [], "result": None}
        dt = (time.time() - t0) * 1000.0
        flag = "" if out.get("ok") else "  ← %s" % str(out.get("error", ""))[:120]
        log("%s/%s seat=%s %.0fms%s" % (room, op, seat, dt, flag))
        self._send(200, out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0", help="监听地址（0.0.0.0 = 局域网都能连）")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--config", default=os.path.join(HERE, "net_config.json"))
    args = ap.parse_args()

    load_config(args.config)
    api_cli.CACHE_CONN = True          # 常驻服务：复用 SQLite 连接（见 api_cli._open_db）
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    srv.daemon_threads = True
    ip = lan_ip()
    log("=" * 64)
    log("天马麻将 联机服务端已启动")
    log("  监听：%s:%d" % (args.host, args.port))
    log("  本机局域网地址：http://%s:%d   （同一路由器的朋友填这个）" % (ip, args.port))
    log("  公网访问：先在路由器把 %d 端口映射到这台机器，或挂 frp / cloudflare tunnel" % args.port)
    log("  房间：%s" % ", ".join(sorted(ROOMS.keys())))
    log("  数据：%s" % os.path.join(HERE, "data"))
    log("  日志：%s" % LOG_PATH)
    log("=" * 64)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        log("收到 Ctrl+C，服务端关闭")
    finally:
        api_cli.close_cached_dbs()
    return 0


if __name__ == "__main__":
    sys.exit(main())
